"""Unified pipeline orchestration for QReduce reduction and classical solve."""

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from time import perf_counter
from types import MappingProxyType

from qreduce.artifacts.metadata import redact_metadata, to_primitive
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
    ProtectionDeclaration,
    ReducibleProblemAdapter,
)
from qreduce.logging_context import logging_context
from qreduce.models import ResolvedRunConfig, RunResult
from qreduce.pipeline.classical_execution import (
    evaluate_domain_metrics,
    execute_classical_solver,
)
from qreduce.pipeline.context import compute_input_hash, validate_logical_counts
from qreduce.pipeline.recovery import RecoveryAttempt
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

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ReductionRoundResult:
    """Detailed result for one reduction round within a unified pipeline run.

    This captures the audit data produced by one reduction round within the
    unified workflow.
    """

    round_index: int
    run_status: RunStatus
    stage: PipelineStage
    terminal_reason: TerminalReason | None

    # MIS and candidate selection
    selected_mis_samples: tuple[RawMISSample, ...] = ()
    candidate_records: tuple[CandidateRecord, ...] = ()
    candidate_domain_item_records: tuple[CandidateDomainItemRecord, ...] = ()
    protection_declaration: ProtectionDeclaration | None = None
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

    This is the single top-level result type for the public pipeline API.

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
        """Whether integer zero requested the baseline, even for invalid configs."""
        value = self.resolved_config.reduction.max_reduction_rounds
        return isinstance(value, int) and not isinstance(value, bool) and value == 0

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
    _model_export_write_path: str | None = None,
) -> PipelineRunResult:
    """Execute the unified QReduce pipeline.

    Behavior is determined by config.reduction.max_reduction_rounds:
    - 0: Classical-only baseline (no MIS, no reduction)
    - 1: Single reduction round
    - >1: Iterative reduction with optional recovery

    Returns the complete result for the selected pipeline mode.

    The _model_export_write_path parameter is for internal use by the experiment
    runner. It allows the runner to specify a staging path for the model export
    that differs from config.classical_solve.model_export_path (the logical/final
    path). The backend writes to _model_export_write_path; the runner is responsible
    for moving the file to the final path after successful completion.
    """
    run_id = config.run_identity.run_id
    max_rounds = config.reduction.max_reduction_rounds

    with logging_context(run_id=run_id, stage="pipeline_start"):
        logger.info(
            "Starting pipeline run_id=%s max_rounds=%d classical_solver=%s mis_solver=%s",
            run_id, max_rounds,
            config.classical_solve.classical_solver_id,
            config.mis_solver_id,
        )

        started_at = perf_counter()

        # Validate configuration
        validation = validate_resolved_run_config(config)
        if not validation.is_valid:
            logger.warning(
                "Configuration validation failed: %s",
                _issues_message(validation),
            )
            return _failed_pipeline(
                config, PipelineStage.VALIDATION, validation.terminal_reason,
                _issues_message(validation), started_at,
            )

        if max_rounds == 0:
            logger.info("Executing classical-only baseline (no reduction)")
            result = _run_classical_only(
                problem, adapter, config,
                classical_solver_registry=classical_solver_registry,
                started_at=started_at,
                _model_export_write_path=_model_export_write_path,
            )
        else:
            logger.info("Executing reduction pipeline with up to %d rounds", max_rounds)
            result = _run_reduction_pipeline(
                problem, adapter, config,
                mis_solver_registry=mis_solver_registry,
                classical_solver_registry=classical_solver_registry,
                started_at=started_at,
                _model_export_write_path=_model_export_write_path,
            )

        elapsed = perf_counter() - started_at
        _log_pipeline_result(result, elapsed)
        return result


def _log_pipeline_result(result: PipelineRunResult, elapsed: float) -> None:
    """Log the final pipeline result."""
    run_result = result.run_result
    status = run_result.run_status.value

    with logging_context(stage="pipeline_complete"):
        if run_result.run_status == RunStatus.SUCCESS:
            logger.info(
                "Pipeline completed status=%s stage=%s elapsed=%.2fs rounds=%d",
                status, run_result.stage.value, elapsed, result.reduction_round_count,
            )
        elif run_result.run_status == RunStatus.PARTIAL_SUCCESS:
            logger.info(
                "Pipeline completed with partial success status=%s stage=%s elapsed=%.2fs rounds=%d",
                status, run_result.stage.value, elapsed, result.reduction_round_count,
            )
        else:
            terminal = run_result.terminal_reason.value if run_result.terminal_reason else "unknown"
            logger.warning(
                "Pipeline failed status=%s stage=%s terminal_reason=%s elapsed=%.2fs",
                status, run_result.stage.value, terminal, elapsed,
            )


def _run_classical_only(
    problem: object,
    adapter: ReducibleProblemAdapter,
    config: ResolvedRunConfig,
    *,
    classical_solver_registry: ClassicalSolverRegistry | None = None,
    started_at: float,
    _model_export_write_path: str | None = None,
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
    input_hash = compute_input_hash(adapter, problem)

    # Get original variable counts
    try:
        describe = getattr(adapter, "describe_logical_variables", None)
        if not callable(describe):
            raise TypeError("Adapter must implement describe_logical_variables.")
        original_counts = validate_logical_counts(describe(problem))
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
        residual_counts = validate_logical_counts(describe(restricted_problem))
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
    configured_budget = reduction.max_end_to_end_runtime_seconds
    remaining = configured_budget - (perf_counter() - started_at) if configured_budget > 0 else 0.0
    timeout = effective_timeout(
        config.classical_solve.time_limit_seconds,
        remaining,
        configured_budget,
    )
    if not timeout.validation.is_valid:
        return _failed_pipeline(
            config, PipelineStage.CLASSICAL, TerminalReason.END_TO_END_TIME_BUDGET_EXHAUSTED,
            "Time budget exhausted before classical solve", started_at, input_hash=input_hash,
            original_variable_counts=original_counts,
            residual_variable_counts=residual_counts,
            cumulative_fixing_manifest=empty_manifest,
            final_retained_item_ids=original_item_ids,
        )

    # Determine time_limit_seconds for the request
    # If unlimited (both limits=0), pass 0 to signal no limit
    # Otherwise pass the computed effective timeout
    request_time_limit = 0.0 if timeout.is_unlimited else (timeout.timeout_seconds or 0.0)

    # Execute classical solve - pass restricted_problem directly (it implements ClassicalModelProvider)
    # The backend calls restricted_problem.build_classical_model() internally
    with logging_context(stage="classical_solve", solver_id=config.classical_solve.classical_solver_id):
        logger.info("Starting classical solve (baseline) solver_id=%s", config.classical_solve.classical_solver_id)
        try:
            classical_result = execute_classical_solver(
                classical_solver,
                restricted_problem,
                ClassicalSolveRequest(
                    run_id=config.run_identity.run_id,
                    round_index=0,
                    time_limit_seconds=request_time_limit,
                    remaining_end_to_end_seconds=remaining,
                    mip_gap_tolerance=config.classical_solve.mip_gap_tolerance,
                    threads=config.classical_solve.threads,
                    random_seed=config.classical_solve.random_seed,
                    model_export_enabled=config.classical_solve.model_export_enabled,
                    model_export_path=(
                        _model_export_write_path or config.classical_solve.model_export_path
                    ),
                    requested_solver_id=config.classical_solve.classical_solver_id,
                    configured_end_to_end_budget_seconds=configured_budget,
                ),
                staging_path=_model_export_write_path,
                logical_path=config.classical_solve.model_export_path,
            )
            logger.debug("Classical solve completed feasible=%s objective=%s", classical_result.solver_claimed_feasible, classical_result.objective_value)
        except Exception as error:  # noqa: BLE001
            logger.warning("Classical solver failed: %s", error)
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
    with logging_context(stage="postcheck"):
        logger.debug("Starting post-check validation (baseline)")
        try:
            postcheck_result = adapter.validate_final_solution(
                problem, classical_result.variable_values, empty_manifest,
                config.classical_solve, solver_objective_value=classical_result.objective_value,
            )
            if not isinstance(postcheck_result, FinalSolutionValidationResult):
                raise TypeError("validate_final_solution must return FinalSolutionValidationResult.")
            logger.debug("Post-check completed feasible=%s", postcheck_result.postcheck_feasible)
        except Exception as error:  # noqa: BLE001
            logger.warning("Post-check failed: %s", error)
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

    try:
        domain_metrics = evaluate_domain_metrics(problem, adapter, classical_result, postcheck_result)
    except Exception as error:  # noqa: BLE001 - Adapter errors are normalized.
        return _make_pipeline_result(
            config, PipelineStage.POSTCHECK, RunStatus.FAILED,
            TerminalReason.ADAPTER_FAILURE, started_at,
            diagnostic=f"evaluate_domain_metrics: {error}", input_hash=input_hash,
            original_variable_counts=original_counts, residual_variable_counts=residual_counts,
            cumulative_fixing_manifest=empty_manifest, final_retained_item_ids=original_item_ids,
            classical_result=classical_result, postcheck_result=postcheck_result,
            postcheck_status=postcheck_status,
        )

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
    _model_export_write_path: str | None = None,
) -> PipelineRunResult:
    """Execute reduction pipeline with one or more rounds.

    This delegates to the internal multi-round implementation which returns
    PipelineRunResult directly.
    """
    from qreduce.pipeline.multi_round import _run_reduction_rounds

    return _run_reduction_rounds(
        problem, adapter, config,
        mis_solver_registry=mis_solver_registry,
        classical_solver_registry=classical_solver_registry,
        started_at=started_at,
        _model_export_write_path=_model_export_write_path,
    )


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
