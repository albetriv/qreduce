"""Unified pipeline orchestration for QReduce reduction and classical solve."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from time import perf_counter
from types import MappingProxyType

from qreduce.artifacts.metadata import redact_metadata, sha256_hex, to_primitive
from qreduce.config import (
    ValidationResult,
    effective_timeout,
    validate_resolved_run_config,
)
from qreduce.domains import (
    DomainEvaluationMetric,
    FinalSolutionValidationResult,
    FixingManifest,
    LogicalVariableCounts,
    ReducibleProblemAdapter,
)
from qreduce.models import ResolvedRunConfig, RunResult
from qreduce.pipeline.multi_round import RecoveryAttempt
from qreduce.pipeline.single_pass import (
    CandidateDomainItemRecord,
    CandidateRecord,
)
from qreduce.solving.mwis import (
    MISBackendResult,
    MISCompilationResult,
    MISSolverRegistry,
    RawMISSample,
)
from qreduce.solving.residual import ClassicalSolveResult, ClassicalSolverRegistry
from qreduce.status import (
    AdoptionStatus,
    ClassicalSolverStatus,
    PipelineStage,
    PostcheckStatus,
    RunStatus,
    TerminalReason,
)


@dataclass(frozen=True, slots=True)
class ReductionRoundResult:
    """Detailed result for one reduction round within a unified pipeline run.

    This captures all the audit data from what was previously SinglePassRunResult,
    structured as a round within the unified workflow.
    """

    round_index: int
    run_status: RunStatus
    stage: PipelineStage
    terminal_reason: TerminalReason | None

    # MIS and candidate selection
    selected_mis_samples: tuple[RawMISSample, ...] = ()
    candidate_records: tuple[CandidateRecord, ...] = ()
    candidate_domain_item_records: tuple[CandidateDomainItemRecord, ...] = ()
    mis_compilation_result: MISCompilationResult | None = None
    mis_execution_result: MISBackendResult | None = None

    # Fixing
    fixing_manifest: FixingManifest | None = None
    retained_item_ids: tuple[str, ...] = ()

    # Classical solve for this round (may be None if round failed before this stage)
    classical_result: ClassicalSolveResult | None = None
    postcheck_result: FinalSolutionValidationResult | None = None

    # Round metrics
    runtime_seconds: float | None = None
    round_reduction_ratio: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "selected_mis_samples", tuple(self.selected_mis_samples))
        object.__setattr__(self, "candidate_records", tuple(self.candidate_records))
        object.__setattr__(
            self, "candidate_domain_item_records", tuple(self.candidate_domain_item_records)
        )
        object.__setattr__(self, "retained_item_ids", tuple(self.retained_item_ids))

    def to_dict(self) -> dict[str, object]:
        """Return the round result for artifact serialization."""
        return redact_metadata(to_primitive(self))  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class PipelineRunResult:
    """Complete in-memory, serializable output of a unified QReduce pipeline run.

    This is the single top-level result type that replaces both SinglePassRunResult
    and MultiRoundRunResult as the public API output.

    Semantics by max_reduction_rounds:
    - 0: Classical baseline, round_results is empty, no reduction applied
    - 1: Single reduction round
    - >1: Iterative reduction up to the configured limit
    """

    run_result: RunResult
    resolved_config: ResolvedRunConfig

    # Reduction rounds (empty for classical-only baseline)
    round_results: tuple[ReductionRoundResult, ...] = ()
    recovery_attempts: tuple[RecoveryAttempt, ...] = ()

    # Cumulative fixing across all rounds
    cumulative_fixing_manifest: FixingManifest | None = None
    final_retained_item_ids: tuple[str, ...] = ()

    # Variable counts
    original_variable_counts: LogicalVariableCounts | None = None
    residual_variable_counts: LogicalVariableCounts | None = None

    # Final solve and validation
    classical_result: ClassicalSolveResult | None = None
    postcheck_result: FinalSolutionValidationResult | None = None
    domain_evaluation_metrics: tuple[DomainEvaluationMetric, ...] | None = None

    # Optimality tracking
    objective_sense: str = "minimize"
    original_primal_bound: float | None = None
    original_dual_bound: float | None = None
    original_bound_provenance: str = "none"
    original_problem_optimality_claim: str = "none"
    residual_problem_optimality_claim: str = "unavailable"

    # Aggregate metrics
    metrics: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "round_results", tuple(self.round_results))
        object.__setattr__(self, "recovery_attempts", tuple(self.recovery_attempts))
        object.__setattr__(self, "final_retained_item_ids", tuple(self.final_retained_item_ids))
        object.__setattr__(self, "metrics", MappingProxyType(dict(self.metrics)))

    @property
    def reduction_round_count(self) -> int:
        """Number of reduction rounds executed (0 for classical-only baseline)."""
        return len(self.round_results)

    @property
    def has_reduction(self) -> bool:
        """True if at least one reduction round was executed."""
        return len(self.round_results) > 0

    @property
    def is_classical_only(self) -> bool:
        """True if this was a classical-only baseline with no MWIS reduction."""
        return len(self.round_results) == 0

    # Convenience properties for single-round access (for backward compatibility)
    # These delegate to the first round when available

    @property
    def retained_item_ids(self) -> tuple[str, ...]:
        """Retained item IDs from the first reduction round, or final_retained_item_ids."""
        if self.round_results:
            return self.round_results[0].retained_item_ids
        return self.final_retained_item_ids

    @property
    def fixing_manifest(self) -> FixingManifest | None:
        """Fixing manifest from the first reduction round."""
        if self.round_results:
            return self.round_results[0].fixing_manifest
        return self.cumulative_fixing_manifest

    @property
    def selected_mis_samples(self) -> tuple[RawMISSample, ...]:
        """Selected MIS samples from the first reduction round."""
        if self.round_results:
            return self.round_results[0].selected_mis_samples
        return ()

    @property
    def candidate_records(self) -> tuple[CandidateRecord, ...]:
        """Candidate records from the first reduction round."""
        if self.round_results:
            return self.round_results[0].candidate_records
        return ()

    @property
    def candidate_domain_item_records(self) -> tuple[CandidateDomainItemRecord, ...]:
        """Candidate domain item records from the first reduction round."""
        if self.round_results:
            return self.round_results[0].candidate_domain_item_records
        return ()

    @property
    def mis_compilation_result(self) -> MISCompilationResult | None:
        """MIS compilation result from the first reduction round."""
        if self.round_results:
            return self.round_results[0].mis_compilation_result
        return None

    @property
    def mis_execution_result(self) -> MISBackendResult | None:
        """MIS execution result from the first reduction round."""
        if self.round_results:
            return self.round_results[0].mis_execution_result
        return None

    def to_dict(self) -> dict[str, object]:
        """Return the complete in-memory result for repository runner persistence."""
        return redact_metadata(to_primitive(self))  # type: ignore[return-value]


def run_pipeline(
    problem: object,
    adapter: ReducibleProblemAdapter,
    config: ResolvedRunConfig,
    *,
    mis_solver_registry: MISSolverRegistry | None = None,
    classical_solver_registry: ClassicalSolverRegistry | None = None,
) -> PipelineRunResult:
    """Execute the unified QReduce pipeline.

    Behavior is determined by config.reduction.max_reduction_rounds:
    - 0: Classical-only baseline (no MIS, no reduction)
    - 1: Single reduction round
    - >1: Iterative reduction with optional recovery

    Returns a PipelineRunResult that unifies what was previously split between
    SinglePassRunResult and MultiRoundRunResult.
    """
    started_at = perf_counter()

    # Validate configuration
    validation = validate_resolved_run_config(config)
    if not validation.is_valid:
        return _failed_pipeline(
            config, PipelineStage.VALIDATION, validation.terminal_reason,
            _issues_message(validation), started_at,
        )

    max_rounds = config.reduction.max_reduction_rounds

    if max_rounds == 0:
        return _run_classical_only(
            problem, adapter, config,
            classical_solver_registry=classical_solver_registry,
            started_at=started_at,
        )
    else:
        return _run_reduction_pipeline(
            problem, adapter, config,
            mis_solver_registry=mis_solver_registry,
            classical_solver_registry=classical_solver_registry,
            started_at=started_at,
        )


def _run_classical_only(
    problem: object,
    adapter: ReducibleProblemAdapter,
    config: ResolvedRunConfig,
    *,
    classical_solver_registry: ClassicalSolverRegistry | None = None,
    started_at: float,
) -> PipelineRunResult:
    """Execute classical-only baseline without any MWIS reduction.

    This path:
    1. Identifies all reducible items (to populate manifest)
    2. Creates an empty fixing manifest with origin="no_reduction"
    3. Restricts the problem (no actual restriction, full domain)
    4. Builds residual model and solves classically
    5. Runs post-check on original problem
    6. Evaluates domain metrics
    """
    from qreduce.solving.residual import (
        ClassicalSolveRequest,
        UnknownClassicalSolverError,
        builtin_classical_solver_registry,
    )

    # Compute input hash if adapter supports it
    input_hash = _compute_input_hash(adapter, problem)

    # Get original variable counts
    try:
        describe = getattr(adapter, "describe_logical_variables", None)
        if not callable(describe):
            raise TypeError("Adapter must implement describe_logical_variables.")
        original_counts = _validate_logical_counts(describe(problem))
    except Exception as error:  # noqa: BLE001
        return _failed_pipeline(
            config, PipelineStage.VALIDATION, TerminalReason.ADAPTER_FAILURE,
            str(error), started_at, input_hash=input_hash,
        )

    # Identify all reducible items
    try:
        original_item_ids = tuple(adapter.identify_reducible_items(problem))
    except Exception as error:  # noqa: BLE001
        return _failed_pipeline(
            config, PipelineStage.GRAPH, TerminalReason.ADAPTER_FAILURE,
            f"identify_reducible_items: {error}", started_at, input_hash=input_hash,
            original_variable_counts=original_counts,
        )

    # Create empty fixing manifest with no_reduction origin
    empty_manifest = FixingManifest(
        retained_item_ids=original_item_ids,
        excluded_item_ids=(),
        entries=(),
        origin="no_reduction",
        provenance={
            "reduction_applied": False,
            "optimality_preservation_claim": "not_applicable",
        },
        round_index=0,
    )

    # Restrict problem (effectively no restriction, full domain)
    try:
        restricted_problem = adapter.restrict_problem(problem, original_item_ids, empty_manifest)
    except Exception as error:  # noqa: BLE001
        return _failed_pipeline(
            config, PipelineStage.RESTRICTION, TerminalReason.ADAPTER_FAILURE,
            f"restrict_problem: {error}", started_at, input_hash=input_hash,
            original_variable_counts=original_counts,
            cumulative_fixing_manifest=empty_manifest,
            final_retained_item_ids=original_item_ids,
        )

    # Get residual variable counts (should match original for no_reduction)
    try:
        residual_counts = _validate_logical_counts(describe(restricted_problem))
    except Exception as error:  # noqa: BLE001
        return _failed_pipeline(
            config, PipelineStage.RESTRICTION, TerminalReason.ADAPTER_FAILURE,
            f"describe_logical_variables on restricted: {error}", started_at, input_hash=input_hash,
            original_variable_counts=original_counts,
            cumulative_fixing_manifest=empty_manifest,
            final_retained_item_ids=original_item_ids,
        )

    # Get classical solver
    registry = classical_solver_registry or builtin_classical_solver_registry()
    try:
        classical_solver = registry.create(config.classical_solve.classical_solver_id)
    except UnknownClassicalSolverError as error:
        return _failed_pipeline(
            config, PipelineStage.CLASSICAL, TerminalReason.CLASSICAL_BACKEND_UNAVAILABLE,
            str(error), started_at, input_hash=input_hash,
            original_variable_counts=original_counts,
            residual_variable_counts=residual_counts,
            cumulative_fixing_manifest=empty_manifest,
            final_retained_item_ids=original_item_ids,
        )

    # Check time budget
    reduction = config.reduction
    remaining = reduction.max_end_to_end_runtime_seconds - (perf_counter() - started_at)
    timeout = effective_timeout(config.classical_solve.time_limit_seconds, remaining)
    if not timeout.validation.is_valid:
        return _failed_pipeline(
            config, PipelineStage.CLASSICAL, TerminalReason.END_TO_END_TIME_BUDGET_EXHAUSTED,
            "Time budget exhausted before classical solve", started_at, input_hash=input_hash,
            original_variable_counts=original_counts,
            residual_variable_counts=residual_counts,
            cumulative_fixing_manifest=empty_manifest,
            final_retained_item_ids=original_item_ids,
        )

    # Execute classical solve - pass restricted_problem directly (it implements ClassicalModelProvider)
    # The backend calls restricted_problem.build_classical_model() internally
    try:
        classical_result = classical_solver.solve(
            restricted_problem,
            ClassicalSolveRequest(
                run_id=config.run_identity.run_id,
                round_index=0,
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
        return _failed_pipeline(
            config, PipelineStage.CLASSICAL, TerminalReason.CLASSICAL_SOLVER_FAILED,
            str(error), started_at, input_hash=input_hash,
            original_variable_counts=original_counts,
            residual_variable_counts=residual_counts,
            cumulative_fixing_manifest=empty_manifest,
            final_retained_item_ids=original_item_ids,
        )

    # Check classical result
    if not classical_result.solver_claimed_feasible:
        return _make_pipeline_result(
            config, PipelineStage.CLASSICAL, RunStatus.FAILED,
            classical_result.terminal_reason or TerminalReason.CLASSICAL_SOLVER_INFEASIBLE,
            started_at, input_hash=input_hash,
            original_variable_counts=original_counts,
            residual_variable_counts=residual_counts,
            cumulative_fixing_manifest=empty_manifest,
            final_retained_item_ids=original_item_ids,
            classical_result=classical_result,
        )

    # Post-check on original problem with empty manifest
    try:
        postcheck_result = adapter.validate_final_solution(
            problem, classical_result.variable_values, empty_manifest,
            config.classical_solve, solver_objective_value=classical_result.objective_value,
        )
    except Exception as error:  # noqa: BLE001
        return _make_pipeline_result(
            config, PipelineStage.POSTCHECK, RunStatus.FAILED,
            TerminalReason.ADAPTER_FAILURE, started_at,
            diagnostic=f"Post-check failed: {error}",
            input_hash=input_hash,
            original_variable_counts=original_counts,
            residual_variable_counts=residual_counts,
            cumulative_fixing_manifest=empty_manifest,
            final_retained_item_ids=original_item_ids,
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

    # Evaluate domain metrics if post-check passed
    domain_metrics: tuple[DomainEvaluationMetric, ...] | None = None
    if postcheck_result.postcheck_feasible:
        try:
            evaluate = getattr(adapter, "evaluate_domain_metrics", None)
            if callable(evaluate):
                metrics = evaluate(problem, classical_result, postcheck_result)
                if isinstance(metrics, tuple | list) and all(
                    isinstance(m, DomainEvaluationMetric) for m in metrics
                ):
                    domain_metrics = tuple(metrics)
        except Exception:  # noqa: BLE001, S110 - Domain metrics are optional
            pass

    # Build final result
    elapsed = perf_counter() - started_at
    primal = postcheck_result.objective_recomputed if adoption == AdoptionStatus.ADOPTED else None
    residual_claim = "unavailable"
    if classical_result.solver_claimed_feasible:
        residual_claim = "certified_optimal" if classical_result.is_optimal else (
            "gap_bounded" if classical_result.gap is not None else "feasible_incumbent"
        )

    run_result = RunResult(
        run_id=config.run_identity.run_id,
        run_status=run_status,
        stage=PipelineStage.POSTCHECK,
        terminal_reason=terminal_reason,
        classical_solver_status=classical_result.classical_solver_status,
        postcheck_status=postcheck_status,
        adoption_status=adoption,
        config_hash=config.config_hash(),
        input_hash=input_hash,
        policy_hash=config.policy_provenance.policy_hash,
    )

    return PipelineRunResult(
        run_result=run_result,
        resolved_config=config,
        round_results=(),  # No reduction rounds for classical-only
        recovery_attempts=(),
        cumulative_fixing_manifest=empty_manifest,
        final_retained_item_ids=original_item_ids,
        original_variable_counts=original_counts,
        residual_variable_counts=residual_counts,
        classical_result=classical_result,
        postcheck_result=postcheck_result,
        domain_evaluation_metrics=domain_metrics,
        original_primal_bound=primal,
        residual_problem_optimality_claim=residual_claim,
        metrics={
            "end_to_end_runtime_seconds": elapsed,
            "round_count": 0,
            "recovery_attempt_count": 0,
        },
    )


def _run_reduction_pipeline(
    problem: object,
    adapter: ReducibleProblemAdapter,
    config: ResolvedRunConfig,
    *,
    mis_solver_registry: MISSolverRegistry | None = None,
    classical_solver_registry: ClassicalSolverRegistry | None = None,
    started_at: float,
) -> PipelineRunResult:
    """Execute reduction pipeline with one or more rounds.

    This delegates to the internal multi-round implementation which returns
    PipelineRunResult directly.
    """
    from qreduce.pipeline.multi_round import _run_multi_round_impl

    # _run_multi_round_impl now returns PipelineRunResult directly
    return _run_multi_round_impl(
        problem, adapter, config,
        mis_solver_registry=mis_solver_registry,
        classical_solver_registry=classical_solver_registry,
    )


def _compute_input_hash(adapter: ReducibleProblemAdapter, problem: object) -> str | None:
    """Compute input hash if adapter supports describe_input."""
    describe_input = getattr(adapter, "describe_input", None)
    if callable(describe_input):
        try:
            return sha256_hex(redact_metadata(to_primitive(describe_input(problem))))
        except Exception:  # noqa: BLE001, S110 - Input hash is optional
            pass
    return None


def _validate_logical_counts(value: object) -> LogicalVariableCounts:
    """Validate that value is a LogicalVariableCounts."""
    if not isinstance(value, LogicalVariableCounts):
        raise TypeError("describe_logical_variables must return LogicalVariableCounts.")
    return value


def _issues_message(validation: ValidationResult) -> str:
    """Format validation issues into a diagnostic message."""
    return "; ".join(f"{issue.field}: {issue.message}" for issue in validation.issues)


def _failed_pipeline(
    config: ResolvedRunConfig,
    stage: PipelineStage,
    terminal_reason: TerminalReason | None,
    message: str,
    started_at: float,
    *,
    input_hash: str | None = None,
    original_variable_counts: LogicalVariableCounts | None = None,
    residual_variable_counts: LogicalVariableCounts | None = None,
    cumulative_fixing_manifest: FixingManifest | None = None,
    final_retained_item_ids: tuple[str, ...] = (),
    round_results: tuple[ReductionRoundResult, ...] = (),
    recovery_attempts: tuple[RecoveryAttempt, ...] = (),
) -> PipelineRunResult:
    """Create a failed PipelineRunResult."""
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
        round_results=round_results,
        recovery_attempts=recovery_attempts,
        cumulative_fixing_manifest=cumulative_fixing_manifest,
        final_retained_item_ids=final_retained_item_ids,
        original_variable_counts=original_variable_counts,
        residual_variable_counts=residual_variable_counts,
        metrics={
            "end_to_end_runtime_seconds": elapsed,
            "round_count": len(round_results),
            "recovery_attempt_count": len(recovery_attempts),
        },
    )


def _make_pipeline_result(
    config: ResolvedRunConfig,
    stage: PipelineStage,
    run_status: RunStatus,
    terminal_reason: TerminalReason | None,
    started_at: float,
    *,
    diagnostic: str | None = None,
    input_hash: str | None = None,
    original_variable_counts: LogicalVariableCounts | None = None,
    residual_variable_counts: LogicalVariableCounts | None = None,
    cumulative_fixing_manifest: FixingManifest | None = None,
    final_retained_item_ids: tuple[str, ...] = (),
    classical_result: ClassicalSolveResult | None = None,
    postcheck_result: FinalSolutionValidationResult | None = None,
    round_results: tuple[ReductionRoundResult, ...] = (),
    recovery_attempts: tuple[RecoveryAttempt, ...] = (),
    adoption_status: AdoptionStatus = AdoptionStatus.NOT_ADOPTED,
    postcheck_status: PostcheckStatus = PostcheckStatus.NOT_RUN,
) -> PipelineRunResult:
    """Create a PipelineRunResult with specified parameters."""
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
        input_hash=input_hash,
        policy_hash=config.policy_provenance.policy_hash,
    )
    return PipelineRunResult(
        run_result=run_result,
        resolved_config=config,
        round_results=round_results,
        recovery_attempts=recovery_attempts,
        cumulative_fixing_manifest=cumulative_fixing_manifest,
        final_retained_item_ids=final_retained_item_ids,
        original_variable_counts=original_variable_counts,
        residual_variable_counts=residual_variable_counts,
        classical_result=classical_result,
        postcheck_result=postcheck_result,
        metrics={
            "end_to_end_runtime_seconds": elapsed,
            "round_count": len(round_results),
            "recovery_attempt_count": len(recovery_attempts),
        },
    )
