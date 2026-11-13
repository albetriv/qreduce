"""Multi-round iterative reduction orchestration."""

from __future__ import annotations

from dataclasses import dataclass, replace
from time import perf_counter
from typing import TYPE_CHECKING

from qreduce.artifacts.metadata import redact_metadata, sha256_hex, to_primitive
from qreduce.config import ValidationResult, validate_resolved_run_config
from qreduce.domains import (
    FixingManifest,
    ReducibleProblemAdapter,
)
from qreduce.models import ResolvedRunConfig, RoundResult, RunResult
from qreduce.pipeline.recovery import expand_ranked_domain, rank_recovery_items
from qreduce.pipeline.rounds import cumulative_fixing_manifest
from qreduce.pipeline.single_pass import (
    CandidateRecord,
    SinglePassRunResult,
    _run_single_pass_with_counts,
)
from qreduce.solving.mwis import MISSolverRegistry
from qreduce.solving.residual import ClassicalSolveResult, ClassicalSolverRegistry
from qreduce.status import (
    AdoptionStatus,
    ClassicalSolverStatus,
    PipelineStage,
    PostcheckStatus,
    RunStatus,
    TerminalReason,
)

if TYPE_CHECKING:
    from qreduce.pipeline.unified import PipelineRunResult


@dataclass(frozen=True, slots=True)
class RecoveryAttempt:
    """Record of one recovery attempt within a round."""

    attempt_index: int
    trigger_reason: TerminalReason
    expanded_domain_size: int
    previous_domain_size: int
    outcome: str  # "success", "exhausted", "failed"


def run_multi_round(
    problem: object,
    adapter: ReducibleProblemAdapter,
    config: ResolvedRunConfig,
    *,
    mis_solver_registry: MISSolverRegistry | None = None,
    classical_solver_registry: ClassicalSolverRegistry | None = None,
) -> PipelineRunResult:
    """Execute iterative reduction with stopping criteria and optional recovery.

    .. deprecated:: 0.6.0
        Use :func:`qreduce.pipeline.run_pipeline` instead. The unified pipeline
        handles all modes based on ``max_reduction_rounds`` in the configuration:
        - 0: Classical-only baseline (no reduction)
        - 1: Single reduction round
        - >1: Iterative reduction with optional recovery

    Note:
        As of 0.7.0, this function returns PipelineRunResult instead of the
        legacy MultiRoundRunResult. Code using this deprecated function should
        migrate to run_pipeline().
    """
    import warnings

    warnings.warn(
        "run_multi_round is deprecated. Use run_pipeline instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    return _run_multi_round_impl(
        problem, adapter, config,
        mis_solver_registry=mis_solver_registry,
        classical_solver_registry=classical_solver_registry,
    )


def _run_multi_round_impl(
    problem: object,
    adapter: ReducibleProblemAdapter,
    config: ResolvedRunConfig,
    *,
    mis_solver_registry: MISSolverRegistry | None = None,
    classical_solver_registry: ClassicalSolverRegistry | None = None,
) -> PipelineRunResult:
    """Internal implementation of multi-round reduction.

    This function contains the actual orchestration logic and returns PipelineRunResult
    directly. It is called by run_pipeline() and by the deprecated run_multi_round() wrapper.

    The return type uses a forward reference to avoid circular imports.
    """
    started_at = perf_counter()

    # Validate configuration
    validation = validate_resolved_run_config(config)
    if not validation.is_valid:
        return _failed_pipeline_result(
            config, PipelineStage.VALIDATION, validation.terminal_reason,
            _issues_message(validation), started_at,
        )

    # Compute input hash if adapter supports it
    input_hash = _compute_input_hash(adapter, problem)

    # Get original item IDs for monotonicity validation
    try:
        original_item_ids = tuple(adapter.identify_reducible_items(problem))
    except Exception as error:  # noqa: BLE001
        return _failed_pipeline_result(
            config, PipelineStage.GRAPH, TerminalReason.ADAPTER_FAILURE,
            f"identify_reducible_items: {error}", started_at,
        )

    reduction = config.reduction
    max_rounds = reduction.max_reduction_rounds

    round_results: list[SinglePassRunResult] = []
    round_manifests: list[FixingManifest] = []
    all_recovery_attempts: list[RecoveryAttempt] = []
    current_problem = problem
    current_item_ids = original_item_ids
    original_problem = problem  # Keep reference for cumulative post-check

    for round_index in range(max_rounds):
        # Check time budget
        elapsed = perf_counter() - started_at
        remaining_budget = reduction.max_end_to_end_runtime_seconds - elapsed
        if remaining_budget <= 0:
            return _build_pipeline_result(
                config, round_results, round_manifests, all_recovery_attempts,
                original_item_ids, TerminalReason.END_TO_END_TIME_BUDGET_EXHAUSTED,
                started_at, input_hash, original_problem, adapter,
            )

        # Run one round with recovery
        round_result, manifest, recovery_attempts = _run_round_with_recovery(
            current_problem, original_problem, adapter, config, round_index,
            current_item_ids, original_item_ids, round_manifests,
            mis_solver_registry, classical_solver_registry, started_at,
        )

        round_results.append(round_result)
        all_recovery_attempts.extend(recovery_attempts)

        # Check if round produced a valid manifest
        if manifest is None:
            # Round failed without producing a manifest - check if recoverable
            terminal = round_result.run_result.terminal_reason
            if _is_recoverable_failure(terminal, reduction) and round_index < max_rounds - 1:
                # This failure type could continue to next round in some designs,
                # but without a manifest we cannot proceed
                pass
            return _build_pipeline_result(
                config, round_results, round_manifests, all_recovery_attempts,
                original_item_ids, terminal, started_at, input_hash,
                original_problem, adapter,
            )

        round_manifests.append(manifest)

        # Check if we achieved success
        if round_result.run_result.run_status in (RunStatus.SUCCESS, RunStatus.PARTIAL_SUCCESS):
            return _build_pipeline_result(
                config, round_results, round_manifests, all_recovery_attempts,
                original_item_ids, None, started_at, input_hash,
                original_problem, adapter,
            )

        # Check stopping criteria for continuing
        stop_reason = _check_stopping_criteria(
            round_result, round_index, max_rounds, reduction, current_item_ids,
        )
        if stop_reason is not None:
            terminal = stop_reason if isinstance(stop_reason, TerminalReason) else None
            return _build_pipeline_result(
                config, round_results, round_manifests, all_recovery_attempts,
                original_item_ids, terminal, started_at, input_hash,
                original_problem, adapter,
            )

        # Prepare next round with restricted problem
        current_item_ids = manifest.retained_item_ids
        if not current_item_ids:
            return _build_pipeline_result(
                config, round_results, round_manifests, all_recovery_attempts,
                original_item_ids, TerminalReason.CANDIDATE_DOMAIN_TOO_SMALL,
                started_at, input_hash, original_problem, adapter,
            )

        try:
            current_problem = adapter.restrict_problem(
                current_problem, current_item_ids, manifest
            )
        except Exception as error:  # noqa: BLE001
            return _failed_pipeline_result(
                config, PipelineStage.RESTRICTION, TerminalReason.ADAPTER_FAILURE,
                f"restrict_problem: {error}", started_at,
                round_results=tuple(round_results),
                recovery_attempts=tuple(all_recovery_attempts),
            )

    # Reached max rounds
    return _build_pipeline_result(
        config, round_results, round_manifests, all_recovery_attempts,
        original_item_ids, TerminalReason.REDUCTION_ROUND_LIMIT_REACHED,
        started_at, input_hash, original_problem, adapter,
    )


def _run_round_with_recovery(
    current_problem: object,
    original_problem: object,
    adapter: ReducibleProblemAdapter,
    config: ResolvedRunConfig,
    round_index: int,
    current_item_ids: tuple[str, ...],
    original_item_ids: tuple[str, ...],
    previous_manifests: list[FixingManifest],
    mis_registry: MISSolverRegistry | None,
    classical_registry: ClassicalSolverRegistry | None,
    started_at: float,
) -> tuple[SinglePassRunResult, FixingManifest | None, list[RecoveryAttempt]]:
    """Execute one round with recovery attempts that actually modify the domain.

    Recovery works by:
    1. Running single_pass to get MIS candidates and initial domain
    2. If failure is recoverable, expand the retained domain
    3. Rebuild P_t from the round's input problem with expanded domain
    4. Re-run only the post-MIS phases (fixing, classical solve, post-check)

    Returns (final_result, manifest, recovery_attempts).
    """
    reduction = config.reduction
    max_recovery = reduction.max_recovery_attempts
    recovery_on_small = reduction.recovery_policy_on_domain_too_small
    recovery_on_infeasible = reduction.recovery_policy_on_infeasible

    recovery_attempts: list[RecoveryAttempt] = []
    ranked_items: tuple[str, ...] | None = None
    last_result: SinglePassRunResult | None = None
    expanded_retained: tuple[str, ...] | None = None

    attempt = 0
    while attempt <= max_recovery:
        # Run single pass (or re-run with expanded domain)
        if expanded_retained is not None:
            # Recovery: rebuild problem with expanded domain and re-run
            result = _run_with_expanded_domain(
                current_problem, original_problem, adapter, config, round_index,
                current_item_ids, expanded_retained, previous_manifests,
                mis_registry, classical_registry, started_at,
            )
        else:
            # Normal execution
            result = _run_single_pass_with_counts(
                current_problem, adapter, config,
                mis_solver_registry=mis_registry,
                classical_solver_registry=classical_registry,
                _started_at=started_at,
                _round_index=round_index,
            )

        last_result = result
        manifest = result.fixing_manifest
        terminal = result.run_result.terminal_reason

        # Check if recovery is needed and possible
        needs_recovery = False
        if terminal == TerminalReason.CANDIDATE_DOMAIN_TOO_SMALL:
            needs_recovery = recovery_on_small == "retry_with_larger_domain"
        elif terminal == TerminalReason.CLASSICAL_SOLVER_INFEASIBLE:
            needs_recovery = recovery_on_infeasible == "retry_with_larger_domain"

        if not needs_recovery or attempt >= max_recovery:
            return result, manifest, recovery_attempts

        # Build ranking for expansion if not yet available
        if ranked_items is None:
            ranked_items = _build_recovery_ranking(
                adapter, current_problem, current_item_ids, result.candidate_records
            )
            if ranked_items is None:
                # Cannot build ranking, recovery not possible
                return result, manifest, recovery_attempts

        # Expand domain
        previous_retained = expanded_retained or (
            manifest.retained_item_ids if manifest else ()
        )
        max_items = config.reduction.candidate_domain_max_items
        new_expanded = expand_ranked_domain(
            current_item_ids, previous_retained, ranked_items, max_items
        )

        if new_expanded == previous_retained:
            # Cannot expand further
            recovery_attempts.append(RecoveryAttempt(
                attempt_index=attempt,
                trigger_reason=terminal,  # type: ignore[arg-type]
                expanded_domain_size=len(previous_retained),
                previous_domain_size=len(previous_retained),
                outcome="exhausted",
            ))
            return result, manifest, recovery_attempts

        # Record recovery attempt
        recovery_attempts.append(RecoveryAttempt(
            attempt_index=attempt,
            trigger_reason=terminal,  # type: ignore[arg-type]
            expanded_domain_size=len(new_expanded),
            previous_domain_size=len(previous_retained),
            outcome="retry",
        ))

        expanded_retained = new_expanded
        attempt += 1

    # Should not reach here, but return last result if we do
    assert last_result is not None
    return last_result, last_result.fixing_manifest, recovery_attempts


def _run_with_expanded_domain(
    current_problem: object,
    original_problem: object,
    adapter: ReducibleProblemAdapter,
    config: ResolvedRunConfig,
    round_index: int,
    input_item_ids: tuple[str, ...],
    expanded_retained: tuple[str, ...],
    previous_manifests: list[FixingManifest],
    mis_registry: MISSolverRegistry | None,
    classical_registry: ClassicalSolverRegistry | None,
    started_at: float,
) -> SinglePassRunResult:
    """Re-run from fixing phase with an expanded retained domain.

    This is the core of recovery: we bypass MIS and directly use the
    expanded domain to build fixing manifest, restrict problem, and solve.
    """
    # Validate expanded domain
    try:
        validation = adapter.validate_candidate_domain(current_problem, expanded_retained)
        if not validation.is_valid:
            return _failed_single_pass(
                config, PipelineStage.CANDIDATE_DOMAIN,
                TerminalReason.CANDIDATE_DOMAIN_TOO_SMALL,
                f"Expanded domain invalid: {validation.failure_reasons}",
                round_index, started_at, retained_item_ids=expanded_retained,
            )
    except Exception as error:  # noqa: BLE001
        return _failed_single_pass(
            config, PipelineStage.CANDIDATE_DOMAIN,
            TerminalReason.ADAPTER_FAILURE,
            f"validate_candidate_domain: {error}",
            round_index, started_at, retained_item_ids=expanded_retained,
        )

    # Build fixing manifest for expanded domain
    try:
        fixing_manifest = adapter.build_fixing_manifest(current_problem, expanded_retained)
        fixing_manifest = replace(
            fixing_manifest,
            round_index=round_index,
            provenance={**dict(fixing_manifest.provenance), "recovery_expanded": True},
        )
    except Exception as error:  # noqa: BLE001
        return _failed_single_pass(
            config, PipelineStage.RESTRICTION,
            TerminalReason.ADAPTER_FAILURE,
            f"build_fixing_manifest: {error}",
            round_index, started_at, retained_item_ids=expanded_retained,
        )

    # Restrict problem with expanded domain
    try:
        reduced_problem = adapter.restrict_problem(
            current_problem, expanded_retained, fixing_manifest
        )
    except Exception as error:  # noqa: BLE001
        return _failed_single_pass(
            config, PipelineStage.RESTRICTION,
            TerminalReason.ADAPTER_FAILURE,
            f"restrict_problem: {error}",
            round_index, started_at,
            retained_item_ids=expanded_retained,
            fixing_manifest=fixing_manifest,
        )

    # Now run the classical solve
    # We need to import and use the classical solve infrastructure
    return _run_classical_and_postcheck(
        current_problem, original_problem, reduced_problem, adapter, config,
        round_index, expanded_retained, fixing_manifest, previous_manifests,
        classical_registry, started_at,
    )


def _run_classical_and_postcheck(
    current_problem: object,
    original_problem: object,
    reduced_problem: object,
    adapter: ReducibleProblemAdapter,
    config: ResolvedRunConfig,
    round_index: int,
    retained_item_ids: tuple[str, ...],
    fixing_manifest: FixingManifest,
    previous_manifests: list[FixingManifest],
    classical_registry: ClassicalSolverRegistry | None,
    started_at: float,
) -> SinglePassRunResult:
    """Execute classical solve and post-check with cumulative fixing validation."""
    from qreduce.config import effective_timeout
    from qreduce.solving.residual import (
        ClassicalSolveRequest,
        UnknownClassicalSolverError,
        builtin_classical_solver_registry,
    )

    reduction = config.reduction

    # Get classical solver
    registry = classical_registry or builtin_classical_solver_registry()
    try:
        classical_solver = registry.create(config.classical_solve.classical_solver_id)
    except UnknownClassicalSolverError as error:
        return _failed_single_pass(
            config, PipelineStage.CLASSICAL,
            TerminalReason.CLASSICAL_BACKEND_UNAVAILABLE,
            str(error),
            round_index, started_at,
            retained_item_ids=retained_item_ids,
            fixing_manifest=fixing_manifest,
        )

    # Check time budget
    remaining = reduction.max_end_to_end_runtime_seconds - (perf_counter() - started_at)
    timeout = effective_timeout(config.classical_solve.time_limit_seconds, remaining)
    if not timeout.validation.is_valid:
        return _failed_single_pass(
            config, PipelineStage.CLASSICAL,
            TerminalReason.END_TO_END_TIME_BUDGET_EXHAUSTED,
            "Time budget exhausted before classical solve",
            round_index, started_at,
            retained_item_ids=retained_item_ids,
            fixing_manifest=fixing_manifest,
        )

    # Execute classical solve - pass reduced_problem directly (it implements ClassicalModelProvider)
    # The backend calls reduced_problem.build_classical_model() internally
    try:
        classical_result = classical_solver.solve(
            reduced_problem,
            ClassicalSolveRequest(
                run_id=config.run_identity.run_id,
                round_index=round_index,
                time_limit_seconds=timeout.timeout_seconds,
                remaining_end_to_end_seconds=remaining,
                mip_gap_tolerance=config.classical_solve.mip_gap_tolerance,
                threads=config.classical_solve.threads,
                random_seed=config.classical_solve.random_seed,
                model_export_enabled=config.classical_solve.model_export_enabled,
                model_export_path=config.classical_solve.model_export_path,
                requested_solver_id=config.classical_solve.classical_solver_id,
            ),
        )
    except Exception as error:  # noqa: BLE001
        return _failed_single_pass(
            config, PipelineStage.CLASSICAL,
            TerminalReason.CLASSICAL_SOLVER_FAILED,
            str(error),
            round_index, started_at,
            retained_item_ids=retained_item_ids,
            fixing_manifest=fixing_manifest,
        )

    # Check classical result
    if not classical_result.solver_claimed_feasible:
        return _make_single_pass_result(
            config, PipelineStage.CLASSICAL,
            RunStatus.FAILED,
            classical_result.terminal_reason or TerminalReason.CLASSICAL_SOLVER_INFEASIBLE,
            round_index, started_at,
            retained_item_ids=retained_item_ids,
            fixing_manifest=fixing_manifest,
            classical_result=classical_result,
        )

    # Build cumulative manifest for post-check
    all_manifests = [*previous_manifests, fixing_manifest]
    try:
        original_items = tuple(adapter.identify_reducible_items(original_problem))
        cumulative_manifest = cumulative_fixing_manifest(original_items, tuple(all_manifests))
    except ValueError as error:
        return _failed_single_pass(
            config, PipelineStage.POSTCHECK,
            TerminalReason.ADAPTER_FAILURE,
            f"Cumulative manifest validation failed: {error}",
            round_index, started_at,
            retained_item_ids=retained_item_ids,
            fixing_manifest=fixing_manifest,
            classical_result=classical_result,
        )

    # Post-check against ORIGINAL problem with CUMULATIVE manifest
    try:
        postcheck_result = adapter.validate_final_solution(
            original_problem,  # Use ORIGINAL problem
            classical_result.variable_values,
            cumulative_manifest,  # Use CUMULATIVE manifest
            config.classical_solve,  # Pass the full options object, not a dict
            solver_objective_value=classical_result.objective_value,
        )
    except Exception as error:  # noqa: BLE001
        return _make_single_pass_result(
            config, PipelineStage.POSTCHECK,
            RunStatus.FAILED,
            TerminalReason.ADAPTER_FAILURE,
            round_index, started_at,
            diagnostic=f"Post-check failed: {error}",
            retained_item_ids=retained_item_ids,
            fixing_manifest=fixing_manifest,
            classical_result=classical_result,
        )

    # Determine final status
    if postcheck_result.postcheck_feasible:
        run_status = RunStatus.SUCCESS if classical_result.is_optimal else RunStatus.PARTIAL_SUCCESS
        terminal_reason = None
        adoption = AdoptionStatus.ADOPTED
        postcheck_status = PostcheckStatus.PASSED
    else:
        run_status = RunStatus.FAILED
        terminal_reason = TerminalReason.POSTCHECK_FAILED
        adoption = AdoptionStatus.NOT_ADOPTED
        postcheck_status = PostcheckStatus.FAILED

    return _make_single_pass_result(
        config, PipelineStage.POSTCHECK,
        run_status, terminal_reason,
        round_index, started_at,
        retained_item_ids=retained_item_ids,
        fixing_manifest=fixing_manifest,
        classical_result=classical_result,
        postcheck_result=postcheck_result,
        adoption_status=adoption,
        postcheck_status=postcheck_status,
    )


def _build_recovery_ranking(
    adapter: ReducibleProblemAdapter,
    problem: object,
    input_item_ids: tuple[str, ...],
    candidate_records: tuple[CandidateRecord, ...],
) -> tuple[str, ...] | None:
    """Build item ranking for recovery expansion."""
    try:
        graph = adapter.build_conflict_graph(problem)
        candidate_items = _extract_ranked_items_from_records(candidate_records)
        return rank_recovery_items(input_item_ids, candidate_items, graph.node_weights)
    except Exception:  # noqa: BLE001
        return None


def _extract_ranked_items_from_records(
    records: tuple[CandidateRecord, ...]
) -> tuple[str, ...]:
    """Extract item ranking from candidate selection frequency."""
    item_counts: dict[str, int] = {}
    for record in records:
        if record.selection_status == "selected":
            for item in record.selected_item_ids:
                item_counts[item] = item_counts.get(item, 0) + 1
    return tuple(sorted(item_counts, key=lambda x: (-item_counts[x], x)))


def _is_recoverable_failure(
    terminal: TerminalReason | None,
    reduction: object,
) -> bool:
    """Check if a failure type could potentially be recovered."""
    if terminal == TerminalReason.CANDIDATE_DOMAIN_TOO_SMALL:
        return reduction.recovery_policy_on_domain_too_small == "retry_with_larger_domain"  # type: ignore[union-attr]
    if terminal == TerminalReason.CLASSICAL_SOLVER_INFEASIBLE:
        return reduction.recovery_policy_on_infeasible == "retry_with_larger_domain"  # type: ignore[union-attr]
    return False


def _check_stopping_criteria(
    result: SinglePassRunResult,
    round_index: int,
    max_rounds: int,
    reduction: object,
    input_item_ids: tuple[str, ...],
) -> TerminalReason | str | None:
    """Check if iteration should stop. Returns reason or None to continue."""
    run_result = result.run_result

    # Success stops iteration
    if run_result.run_status in (RunStatus.SUCCESS, RunStatus.PARTIAL_SUCCESS):
        return "success"

    # Non-recoverable failures stop iteration
    if run_result.run_status == RunStatus.FAILED and not _is_recoverable_failure(
        run_result.terminal_reason, reduction
    ):
        return run_result.terminal_reason

    # Check reduction ratio (stall detection)
    manifest = result.fixing_manifest
    if manifest is not None and input_item_ids:
        retained = len(manifest.retained_item_ids)
        excluded = len(input_item_ids) - retained
        if len(input_item_ids) > 0:
            ratio = excluded / len(input_item_ids)
            if ratio < reduction.min_reduction_ratio:  # type: ignore[union-attr]
                return TerminalReason.CANDIDATE_DOMAIN_NO_MEANINGFUL_REDUCTION

    # Check target binary variables
    if result.residual_variable_counts is not None:
        target = reduction.target_binary_variables  # type: ignore[union-attr]
        if target > 0 and result.residual_variable_counts.binary_free <= target:
            return "target_reached"

    # Max rounds check
    if round_index >= max_rounds - 1:
        return TerminalReason.REDUCTION_ROUND_LIMIT_REACHED

    return None


def _compute_input_hash(adapter: ReducibleProblemAdapter, problem: object) -> str | None:
    """Compute input hash if adapter supports it."""
    describe_input = getattr(adapter, "describe_input", None)
    if callable(describe_input):
        try:
            return sha256_hex(redact_metadata(to_primitive(describe_input(problem))))
        except Exception:  # noqa: BLE001, S110 - Input hash is optional
            pass
    return None


def _failed_single_pass(
    config: ResolvedRunConfig,
    stage: PipelineStage,
    terminal_reason: TerminalReason,
    message: str,
    round_index: int,
    started_at: float,
    *,
    retained_item_ids: tuple[str, ...] = (),
    fixing_manifest: FixingManifest | None = None,
    classical_result: ClassicalSolveResult | None = None,
) -> SinglePassRunResult:
    """Create a failed SinglePassRunResult for recovery attempts."""
    elapsed = perf_counter() - started_at
    run_result = RunResult(
        run_id=config.run_identity.run_id,
        run_status=RunStatus.FAILED,
        stage=stage,
        terminal_reason=terminal_reason,
        classical_solver_status=(
            classical_result.classical_solver_status if classical_result
            else ClassicalSolverStatus.NOT_RUN
        ),
        postcheck_status=PostcheckStatus.NOT_RUN,
        adoption_status=AdoptionStatus.NOT_ADOPTED,
        diagnostic_message=message,
        config_hash=config.config_hash(),
    )
    return SinglePassRunResult(
        run_result=run_result,
        resolved_config=config,
        retained_item_ids=retained_item_ids,
        fixing_manifest=fixing_manifest,
        classical_result=classical_result,
        metrics={"end_to_end_runtime_seconds": elapsed, "round_index": round_index},
    )


def _make_single_pass_result(
    config: ResolvedRunConfig,
    stage: PipelineStage,
    run_status: RunStatus,
    terminal_reason: TerminalReason | None,
    round_index: int,
    started_at: float,
    *,
    diagnostic: str | None = None,
    retained_item_ids: tuple[str, ...] = (),
    fixing_manifest: FixingManifest | None = None,
    classical_result: ClassicalSolveResult | None = None,
    postcheck_result: object | None = None,
    adoption_status: AdoptionStatus = AdoptionStatus.NOT_ADOPTED,
    postcheck_status: PostcheckStatus = PostcheckStatus.NOT_RUN,
) -> SinglePassRunResult:
    """Create a SinglePassRunResult with specified parameters."""
    elapsed = perf_counter() - started_at
    run_result = RunResult(
        run_id=config.run_identity.run_id,
        run_status=run_status,
        stage=stage,
        terminal_reason=terminal_reason,
        classical_solver_status=(
            classical_result.classical_solver_status if classical_result
            else ClassicalSolverStatus.NOT_RUN
        ),
        postcheck_status=postcheck_status,
        adoption_status=adoption_status,
        diagnostic_message=diagnostic,
        config_hash=config.config_hash(),
    )
    return SinglePassRunResult(
        run_result=run_result,
        resolved_config=config,
        retained_item_ids=retained_item_ids,
        fixing_manifest=fixing_manifest,
        classical_result=classical_result,
        postcheck_result=postcheck_result,
        metrics={"end_to_end_runtime_seconds": elapsed, "round_index": round_index},
    )



def _build_pipeline_result(
    config: ResolvedRunConfig,
    round_results: list[SinglePassRunResult],
    round_manifests: list[FixingManifest],
    recovery_attempts: list[RecoveryAttempt],
    original_item_ids: tuple[str, ...],
    terminal_reason: TerminalReason | None,
    started_at: float,
    input_hash: str | None,
    original_problem: object,
    adapter: ReducibleProblemAdapter,
) -> PipelineRunResult:
    """Build final PipelineRunResult from accumulated round data.

    This is the unified result builder that constructs PipelineRunResult directly,
    converting SinglePassRunResult to ReductionRoundResult inline.
    """
    from qreduce.pipeline.unified import PipelineRunResult, ReductionRoundResult

    elapsed = perf_counter() - started_at

    # Determine final status from last round
    if round_results:
        last = round_results[-1]
        run_status = last.run_result.run_status
        stage = last.run_result.stage
        classical_status = last.run_result.classical_solver_status
        postcheck_status = last.run_result.postcheck_status
        adoption_status = last.run_result.adoption_status
        classical_result = last.classical_result
        original_counts = last.original_variable_counts
        residual_counts = last.residual_variable_counts
        objective_sense = last.objective_sense
        primal = last.original_primal_bound
        dual = last.original_dual_bound
        bound_provenance = last.original_bound_provenance
        original_claim = last.original_problem_optimality_claim
        residual_claim = last.residual_problem_optimality_claim
        postcheck = last.postcheck_result
        domain_metrics = last.domain_evaluation_metrics
    else:
        run_status = RunStatus.FAILED
        stage = PipelineStage.VALIDATION
        classical_status = ClassicalSolverStatus.NOT_RUN
        postcheck_status = PostcheckStatus.NOT_RUN
        adoption_status = AdoptionStatus.NOT_ADOPTED
        classical_result = None
        original_counts = None
        residual_counts = None
        objective_sense = "minimize"
        primal = None
        dual = None
        bound_provenance = "none"
        original_claim = "none"
        residual_claim = "unavailable"
        postcheck = None
        domain_metrics = None

    # Build cumulative manifest - MUST NOT silently fail
    cumulative_manifest: FixingManifest | None = None
    final_retained: tuple[str, ...] = ()
    cumulative_error: str | None = None

    if round_manifests:
        try:
            cumulative_manifest = cumulative_fixing_manifest(
                original_item_ids, tuple(round_manifests)
            )
            final_retained = cumulative_manifest.retained_item_ids
        except ValueError as error:
            cumulative_error = str(error)
            if run_status == RunStatus.SUCCESS:
                run_status = RunStatus.FAILED
                terminal_reason = TerminalReason.ADAPTER_FAILURE
                adoption_status = AdoptionStatus.NOT_ADOPTED

    # Build round result summaries for RunResult
    round_result_models = tuple(
        RoundResult(
            round_index=i,
            stage=r.run_result.stage,
            terminal_reason=r.run_result.terminal_reason,
            runtime_seconds=r.metrics.get("end_to_end_runtime_seconds"),  # type: ignore[arg-type]
            metadata={
                "retained_count": len(r.retained_item_ids),
                "excluded_count": len(r.fixing_manifest.excluded_item_ids) if r.fixing_manifest else 0,
            },
        )
        for i, r in enumerate(round_results)
    )

    # Convert SinglePassRunResult to ReductionRoundResult
    converted_rounds = tuple(
        ReductionRoundResult(
            round_index=i,
            run_status=r.run_result.run_status,
            stage=r.run_result.stage,
            terminal_reason=r.run_result.terminal_reason,
            selected_mis_samples=r.selected_mis_samples,
            candidate_records=r.candidate_records,
            candidate_domain_item_records=r.candidate_domain_item_records,
            mis_compilation_result=r.mis_compilation_result,
            mis_execution_result=r.mis_execution_result,
            fixing_manifest=r.fixing_manifest,
            retained_item_ids=r.retained_item_ids,
            classical_result=r.classical_result,
            postcheck_result=r.postcheck_result,
            runtime_seconds=(
                r.metrics.get("end_to_end_runtime_seconds")
                if isinstance(r.metrics.get("end_to_end_runtime_seconds"), int | float)
                else None
            ),
            round_reduction_ratio=(
                r.metrics.get("round_reduction_ratio")
                if isinstance(r.metrics.get("round_reduction_ratio"), int | float)
                else None
            ),
        )
        for i, r in enumerate(round_results)
    )

    diagnostic = cumulative_error
    run_result = RunResult(
        run_id=config.run_identity.run_id,
        run_status=run_status,
        stage=stage,
        terminal_reason=terminal_reason,
        classical_solver_status=classical_status,
        postcheck_status=postcheck_status,
        adoption_status=adoption_status,
        round_results=round_result_models,
        diagnostic_message=diagnostic,
        config_hash=config.config_hash(),
        input_hash=input_hash,
        policy_hash=config.policy_provenance.policy_hash,
    )

    metrics: dict[str, object] = {
        "end_to_end_runtime_seconds": elapsed,
        "round_count": len(round_results),
        "recovery_attempt_count": len(recovery_attempts),
    }
    if round_manifests:
        total_excluded = sum(len(m.excluded_item_ids) for m in round_manifests)
        if original_item_ids:
            metrics["cumulative_reduction_ratio"] = total_excluded / len(original_item_ids)

    # Calculate residual_problem_optimality_claim if not set
    if residual_claim == "unavailable" and classical_result and classical_result.solver_claimed_feasible:
        residual_claim = "certified_optimal" if classical_result.is_optimal else (
            "gap_bounded" if classical_result.gap is not None else "feasible_incumbent"
        )

    # Calculate original_primal_bound from postcheck if adopted
    if primal is None and adoption_status == AdoptionStatus.ADOPTED and postcheck:
        primal = postcheck.objective_recomputed

    return PipelineRunResult(
        run_result=run_result,
        resolved_config=config,
        round_results=converted_rounds,
        recovery_attempts=tuple(recovery_attempts),
        cumulative_fixing_manifest=cumulative_manifest,
        final_retained_item_ids=final_retained,
        original_variable_counts=original_counts,
        residual_variable_counts=residual_counts,
        classical_result=classical_result,
        postcheck_result=postcheck,
        domain_evaluation_metrics=domain_metrics,
        objective_sense=objective_sense,
        original_primal_bound=primal,
        original_dual_bound=dual,
        original_bound_provenance=bound_provenance,
        original_problem_optimality_claim=original_claim,
        residual_problem_optimality_claim=residual_claim,
        metrics=metrics,
    )


def _failed_pipeline_result(
    config: ResolvedRunConfig,
    stage: PipelineStage,
    terminal_reason: TerminalReason | None,
    message: str,
    started_at: float,
    round_results: tuple[SinglePassRunResult, ...] = (),
    recovery_attempts: tuple[RecoveryAttempt, ...] = (),
) -> PipelineRunResult:
    """Create a failed PipelineRunResult."""
    from qreduce.pipeline.unified import PipelineRunResult, ReductionRoundResult

    elapsed = perf_counter() - started_at

    # Convert any existing round results
    converted_rounds = tuple(
        ReductionRoundResult(
            round_index=i,
            run_status=r.run_result.run_status,
            stage=r.run_result.stage,
            terminal_reason=r.run_result.terminal_reason,
            selected_mis_samples=r.selected_mis_samples,
            candidate_records=r.candidate_records,
            candidate_domain_item_records=r.candidate_domain_item_records,
            mis_compilation_result=r.mis_compilation_result,
            mis_execution_result=r.mis_execution_result,
            fixing_manifest=r.fixing_manifest,
            retained_item_ids=r.retained_item_ids,
            classical_result=r.classical_result,
            postcheck_result=r.postcheck_result,
            runtime_seconds=(
                r.metrics.get("end_to_end_runtime_seconds")
                if isinstance(r.metrics.get("end_to_end_runtime_seconds"), int | float)
                else None
            ),
            round_reduction_ratio=(
                r.metrics.get("round_reduction_ratio")
                if isinstance(r.metrics.get("round_reduction_ratio"), int | float)
                else None
            ),
        )
        for i, r in enumerate(round_results)
    )

    run_result = RunResult(
        run_id=config.run_identity.run_id,
        run_status=RunStatus.FAILED,
        stage=stage,
        terminal_reason=terminal_reason,
        classical_solver_status=ClassicalSolverStatus.NOT_RUN,
        postcheck_status=PostcheckStatus.NOT_RUN,
        adoption_status=AdoptionStatus.NOT_ADOPTED,
        diagnostic_message=message,
        config_hash=config.config_hash(),
    )
    return PipelineRunResult(
        run_result=run_result,
        resolved_config=config,
        round_results=converted_rounds,
        recovery_attempts=recovery_attempts,
        metrics={"end_to_end_runtime_seconds": elapsed},
    )


def _issues_message(validation: ValidationResult) -> str:
    """Format validation issues into a diagnostic message."""
    return "; ".join(f"{issue.field}: {issue.message}" for issue in validation.issues)
