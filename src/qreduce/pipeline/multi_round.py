"""Multi-round iterative reduction orchestration."""

from __future__ import annotations

import logging
from dataclasses import replace
from time import perf_counter

from qreduce.domains import (
    FinalSolutionValidationResult,
    FixingManifest,
    ReducibleProblemAdapter,
)
from qreduce.logging_context import logging_context
from qreduce.models import ResolvedRunConfig, RoundResult, RunResult
from qreduce.pipeline.classical_execution import execute_classical_solver
from qreduce.pipeline.context import compute_input_hash, validate_logical_counts
from qreduce.pipeline.recovery import (
    RecoveryAttempt,
    expand_ranked_domain,
    rank_recovery_items,
)
from qreduce.pipeline.rounds import cumulative_fixing_manifest
from qreduce.pipeline.single_pass import (
    CandidateRecord,
    RoundExecutionResult,
    _evaluate_round_domain_metrics,
    _execute_reduction_round_with_counts,
)
from qreduce.pipeline.unified import PipelineRunResult, ReductionRoundResult
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

logger = logging.getLogger(__name__)

_RECOVERY_ATTEMPT_METRICS = frozenset({
    "candidate_domain_size", "classical_runtime_seconds",
    "classical_solver_claimed_feasible", "objective_value", "best_bound",
    "solver_gap", "postcheck_feasible", "postcheck_failure_reasons",
    "objective_recomputed",
})


def _run_reduction_rounds(
    problem: object,
    adapter: ReducibleProblemAdapter,
    config: ResolvedRunConfig,
    *,
    mis_solver_registry: MISSolverRegistry | None = None,
    classical_solver_registry: ClassicalSolverRegistry | None = None,
    _model_export_write_path: str | None = None,
    started_at: float,
) -> PipelineRunResult:
    """Internal implementation of multi-round reduction.

    The public unified pipeline owns the end-to-end timer and invokes this
    internal orchestrator for every positive reduction-round configuration.

    The _model_export_write_path parameter allows the experiment runner to specify a
    staging path for model export that differs from config.classical_solve.model_export_path.
    """
    # Compute input hash if adapter supports it
    input_hash = compute_input_hash(adapter, problem)

    reduction = config.reduction
    max_rounds = reduction.max_reduction_rounds

    if max_rounds > 1 or reduction.max_recovery_attempts > 0:
        try:
            original_item_ids = tuple(adapter.identify_reducible_items(problem))
        except Exception as error:  # noqa: BLE001
            logger.error("Failed to identify reducible items: %s", error)
            return _failed_pipeline_result(
                config, PipelineStage.GRAPH, TerminalReason.ADAPTER_FAILURE,
                f"identify_reducible_items: {error}", started_at, input_hash=input_hash,
            )
    else:
        original_item_ids = ()

    round_results: list[RoundExecutionResult] = []
    round_manifests: list[FixingManifest] = []
    all_recovery_attempts: list[RecoveryAttempt] = []
    current_problem = problem
    current_item_ids = original_item_ids
    original_problem = problem  # Keep reference for cumulative post-check

    for round_index in range(max_rounds):
        with logging_context(round_index=round_index, stage="reduction_round"):
            # Check time budget
            elapsed = perf_counter() - started_at
            remaining_budget = reduction.max_end_to_end_runtime_seconds - elapsed
            if remaining_budget <= 0:
                logger.warning(
                    "Time budget exhausted at round %d after %.2fs",
                    round_index, elapsed,
                )
                return _build_pipeline_result(
                    config, round_results, round_manifests, all_recovery_attempts,
                    original_item_ids, TerminalReason.END_TO_END_TIME_BUDGET_EXHAUSTED,
                    started_at, input_hash, original_problem, adapter,
                )

            logger.info(
                "Starting reduction round %d/%d remaining_budget=%.1fs",
                round_index + 1, max_rounds, remaining_budget,
            )

            # The local timer includes all recovery attempts; the global timer is
            # still passed to every backend for end-to-end budget enforcement.
            round_started_at = perf_counter()
            round_result, manifest, recovery_attempts = _run_round_with_recovery(
                current_problem, original_problem, adapter, config, round_index,
                current_item_ids, original_item_ids, round_manifests,
                mis_solver_registry, classical_solver_registry, started_at,
                _model_export_write_path=_model_export_write_path,
            )
            round_metrics = dict(round_result.metrics)
            round_runtime = perf_counter() - round_started_at
            round_metrics["round_runtime_seconds"] = round_runtime
            if manifest is not None:
                input_size = len(manifest.retained_item_ids) + len(manifest.excluded_item_ids)
                if input_size:
                    round_metrics["round_reduction_ratio"] = len(manifest.excluded_item_ids) / input_size
            round_result = replace(round_result, metrics=round_metrics)

            round_results.append(round_result)
            all_recovery_attempts.extend(recovery_attempts)

            # Log recovery attempts
            if recovery_attempts:
                logger.info(
                    "Round %d completed with %d recovery attempts",
                    round_index, len(recovery_attempts),
                )

            # Check if round produced a valid manifest
            if manifest is None:
                # Round failed without producing a manifest - check if recoverable
                terminal = round_result.run_result.terminal_reason
                logger.warning(
                    "Round %d failed without manifest terminal_reason=%s",
                    round_index, terminal.value if terminal else "unknown",
                )
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
            if not original_item_ids:
                original_item_ids = tuple(
                    dict.fromkeys((*manifest.retained_item_ids, *manifest.excluded_item_ids))
                )

            logger.debug(
                "Round %d manifest: retained=%d excluded=%d runtime=%.2fs",
                round_index, len(manifest.retained_item_ids),
                len(manifest.excluded_item_ids), round_runtime,
            )

            # Check if we achieved success
            if round_result.run_result.run_status in (RunStatus.SUCCESS, RunStatus.PARTIAL_SUCCESS):
                logger.info(
                    "Round %d achieved %s",
                    round_index, round_result.run_result.run_status.value,
                )
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
                if terminal:
                    logger.info("Stopping at round %d: %s", round_index, terminal.value)
                return _build_pipeline_result(
                    config, round_results, round_manifests, all_recovery_attempts,
                    original_item_ids, terminal, started_at, input_hash,
                    original_problem, adapter,
                )

            # Prepare next round with restricted problem
            current_item_ids = manifest.retained_item_ids
            if not current_item_ids:
                logger.warning("Round %d: empty candidate domain", round_index)
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
                logger.error("Round %d: restrict_problem failed: %s", round_index, error)
                result = _build_pipeline_result(
                    config, round_results, round_manifests, all_recovery_attempts,
                    original_item_ids, TerminalReason.ADAPTER_FAILURE, started_at,
                    input_hash, original_problem, adapter,
                )
                return replace(result, run_result=replace(
                    result.run_result, run_status=RunStatus.FAILED,
                    stage=PipelineStage.RESTRICTION,
                    terminal_reason=TerminalReason.ADAPTER_FAILURE,
                    adoption_status=AdoptionStatus.NOT_ADOPTED,
                    diagnostic_message=f"restrict_problem: {error}",
                ))

    # Reached max rounds
    logger.info("Reached maximum reduction rounds (%d)", max_rounds)
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
    *,
    _model_export_write_path: str | None = None,
) -> tuple[RoundExecutionResult, FixingManifest | None, list[RecoveryAttempt]]:
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
    last_result: RoundExecutionResult | None = None
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
                _model_export_write_path=_model_export_write_path,
            )
            if last_result is not None:
                result = replace(
                    result,
                    selected_mis_samples=last_result.selected_mis_samples,
                    candidate_records=last_result.candidate_records,
                    candidate_domain_item_records=last_result.candidate_domain_item_records,
                    protection_declaration=last_result.protection_declaration,
                    mis_compilation_result=last_result.mis_compilation_result,
                    mis_execution_result=last_result.mis_execution_result,
                    original_variable_counts=last_result.original_variable_counts,
                    metrics={
                        **{key: value for key, value in last_result.metrics.items()
                           if key not in _RECOVERY_ATTEMPT_METRICS},
                        **result.metrics,
                    },
                )
        else:
            # Normal execution
            result = _execute_reduction_round_with_counts(
                current_problem, adapter, config,
                mis_solver_registry=mis_registry,
                classical_solver_registry=classical_registry,
                _started_at=started_at,
                _round_index=round_index,
                _model_export_write_path=_model_export_write_path,
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
            logger.info(
                "Recovery exhausted: cannot expand domain further attempt=%d domain_size=%d",
                attempt, len(previous_retained),
            )
            recovery_attempts.append(RecoveryAttempt(
                attempt_index=attempt,
                trigger_reason=terminal,  # type: ignore[arg-type]
                expanded_domain_size=len(previous_retained),
                previous_domain_size=len(previous_retained),
                outcome="exhausted",
            ))
            return result, manifest, recovery_attempts

        # Record recovery attempt
        logger.info(
            "Recovery attempt %d: trigger=%s previous_size=%d expanded_size=%d",
            attempt, terminal.value if terminal else "unknown",
            len(previous_retained), len(new_expanded),
        )
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
    *,
    _model_export_write_path: str | None = None,
) -> RoundExecutionResult:
    """Re-run from fixing phase with an expanded retained domain.

    This is the core of recovery: we bypass MIS and directly use the
    expanded domain to build fixing manifest, restrict problem, and solve.
    """
    with logging_context(round_index=round_index, stage="recovery_expanded"):
        logger.debug(
            "Running with expanded domain round=%d expanded_size=%d",
            round_index, len(expanded_retained),
        )
        # Validate expanded domain
        try:
            validation = adapter.validate_candidate_domain(current_problem, expanded_retained)
            if not validation.is_valid:
                logger.warning("Expanded domain invalid: %s", validation.failure_reasons)
                return _failed_round(
                    config, PipelineStage.CANDIDATE_DOMAIN,
                    TerminalReason.CANDIDATE_DOMAIN_TOO_SMALL,
                    f"Expanded domain invalid: {validation.failure_reasons}",
                    round_index, started_at, retained_item_ids=expanded_retained,
                )
        except Exception as error:  # noqa: BLE001
            logger.warning("validate_candidate_domain failed: %s", error)
            return _failed_round(
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
            logger.warning("build_fixing_manifest failed: %s", error)
            return _failed_round(
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
            logger.warning("restrict_problem failed: %s", error)
            return _failed_round(
                config, PipelineStage.RESTRICTION,
                TerminalReason.ADAPTER_FAILURE,
                f"restrict_problem: {error}",
                round_index, started_at,
                retained_item_ids=expanded_retained,
                fixing_manifest=fixing_manifest,
            )

        try:
            residual_counts = validate_logical_counts(adapter.describe_logical_variables(reduced_problem))
        except Exception as error:  # noqa: BLE001 - Adapter failures are normalized.
            return _failed_round(
                config, PipelineStage.RESTRICTION, TerminalReason.ADAPTER_FAILURE,
                str(error), round_index, started_at, retained_item_ids=expanded_retained,
                fixing_manifest=fixing_manifest,
            )

        # Now run the classical solve
        # We need to import and use the classical solve infrastructure
        result = _run_classical_and_postcheck(
            current_problem, original_problem, reduced_problem, adapter, config,
            round_index, expanded_retained, fixing_manifest, previous_manifests,
            classical_registry, started_at,
            _model_export_write_path=_model_export_write_path,
        )
        metrics = dict(result.metrics)
        metrics["candidate_domain_size"] = len(expanded_retained)
        if result.classical_result is not None:
            classical = result.classical_result
            metrics.update({
                "classical_runtime_seconds": classical.runtime_seconds,
                "classical_solver_claimed_feasible": classical.solver_claimed_feasible,
                "objective_value": classical.objective_value,
                "best_bound": classical.best_bound,
                "solver_gap": classical.gap,
            })
        if result.postcheck_result is not None:
            metrics["postcheck_feasible"] = result.postcheck_result.postcheck_feasible
            metrics["postcheck_failure_reasons"] = result.postcheck_result.failure_reasons
            if result.postcheck_result.objective_recomputed is not None:
                metrics["objective_recomputed"] = result.postcheck_result.objective_recomputed
        result = replace(result, residual_variable_counts=residual_counts, metrics=metrics)
        return _evaluate_round_domain_metrics(current_problem, adapter, result)


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
    *,
    _model_export_write_path: str | None = None,
) -> RoundExecutionResult:
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
        return _failed_round(
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
        return _failed_round(
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
        classical_result = execute_classical_solver(
            classical_solver,
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
                model_export_path=(
                    _model_export_write_path or config.classical_solve.model_export_path
                ),
                requested_solver_id=config.classical_solve.classical_solver_id,
            ),
            staging_path=_model_export_write_path,
            logical_path=config.classical_solve.model_export_path,
        )
    except Exception as error:  # noqa: BLE001
        return _failed_round(
            config, PipelineStage.CLASSICAL,
            TerminalReason.CLASSICAL_SOLVER_FAILED,
            str(error),
            round_index, started_at,
            retained_item_ids=retained_item_ids,
            fixing_manifest=fixing_manifest,
        )

    # Check classical result
    if not classical_result.solver_claimed_feasible:
        return _make_round_result(
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
    except Exception as error:  # noqa: BLE001 - Adapter and manifest failures are normalized.
        return _failed_round(
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
        if not isinstance(postcheck_result, FinalSolutionValidationResult):
            raise TypeError("validate_final_solution must return FinalSolutionValidationResult.")
    except Exception as error:  # noqa: BLE001
        return _make_round_result(
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

    return _make_round_result(
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
    result: RoundExecutionResult,
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


def _failed_round(
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
) -> RoundExecutionResult:
    """Create a failed RoundExecutionResult for recovery attempts."""
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
    return RoundExecutionResult(
        run_result=run_result,
        resolved_config=config,
        retained_item_ids=retained_item_ids,
        fixing_manifest=fixing_manifest,
        classical_result=classical_result,
        metrics={"end_to_end_runtime_seconds": elapsed, "round_index": round_index},
    )


def _make_round_result(
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
) -> RoundExecutionResult:
    """Create a RoundExecutionResult with specified parameters."""
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
    return RoundExecutionResult(
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
    round_results: list[RoundExecutionResult],
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
    converting RoundExecutionResult to ReductionRoundResult inline.
    """
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
        original_counts = round_results[0].original_variable_counts
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
            if run_status in (RunStatus.SUCCESS, RunStatus.PARTIAL_SUCCESS):
                run_status = RunStatus.FAILED
                terminal_reason = TerminalReason.ADAPTER_FAILURE
                adoption_status = AdoptionStatus.NOT_ADOPTED

    # Build round result summaries for RunResult
    round_result_models = tuple(
        RoundResult(
            round_index=i,
            stage=r.run_result.stage,
            terminal_reason=r.run_result.terminal_reason,
            runtime_seconds=r.metrics.get("round_runtime_seconds"),  # type: ignore[arg-type]
            metadata={
                "retained_count": len(r.retained_item_ids),
                "excluded_count": len(r.fixing_manifest.excluded_item_ids) if r.fixing_manifest else 0,
            },
        )
        for i, r in enumerate(round_results)
    )

    # Convert RoundExecutionResult to ReductionRoundResult
    converted_rounds = tuple(
        ReductionRoundResult(
            round_index=i,
            run_status=r.run_result.run_status,
            stage=r.run_result.stage,
            terminal_reason=r.run_result.terminal_reason,
            selected_mis_samples=r.selected_mis_samples,
            candidate_records=r.candidate_records,
            candidate_domain_item_records=r.candidate_domain_item_records,
            protection_declaration=r.protection_declaration,
            mis_compilation_result=r.mis_compilation_result,
            mis_execution_result=r.mis_execution_result,
            fixing_manifest=r.fixing_manifest,
            retained_item_ids=r.retained_item_ids,
            classical_result=r.classical_result,
            postcheck_result=r.postcheck_result,
            runtime_seconds=(
                r.metrics.get("round_runtime_seconds")
                if isinstance(r.metrics.get("round_runtime_seconds"), int | float)
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

    diagnostic = cumulative_error or (
        last.run_result.diagnostic_message if round_results else None
    )
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

    metrics: dict[str, object] = dict(last.metrics) if round_results else {}
    metrics.update({
        "end_to_end_runtime_seconds": elapsed,
        "round_count": len(round_results),
        "recovery_attempt_count": len(recovery_attempts),
    })
    if round_results and last.candidate_records:
        metrics.setdefault(
            "repaired_candidate_count",
            sum(record.repair_status == "repaired" for record in last.candidate_records),
        )
    if round_manifests:
        total_excluded = sum(len(m.excluded_item_ids) for m in round_manifests)
        if original_item_ids:
            metrics["cumulative_reduction_ratio"] = total_excluded / len(original_item_ids)
            if len(round_results) == 1:
                metrics["round_reduction_ratio"] = (
                    len(original_item_ids) - len(final_retained)
                ) / len(original_item_ids)

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
    *,
    input_hash: str | None = None,
) -> PipelineRunResult:
    """Create a failed result before any reduction round has executed."""
    elapsed = perf_counter() - started_at

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
        input_hash=input_hash,
        policy_hash=config.policy_provenance.policy_hash,
    )
    return PipelineRunResult(
        run_result=run_result,
        resolved_config=config,
        metrics={"end_to_end_runtime_seconds": elapsed, "round_count": 0,
                 "recovery_attempt_count": 0},
    )
