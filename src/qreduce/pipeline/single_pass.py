"""Domain-neutral single-pass MWIS reduction and residual solve orchestration."""

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from time import perf_counter
from types import MappingProxyType

from qreduce.artifacts.metadata import redact_metadata, sha256_hex, to_primitive
from qreduce.capabilities import validate_backend_compatibility
from qreduce.config import effective_timeout, validate_resolved_run_config
from qreduce.domains import (
    DomainEvaluationMetric,
    FinalSolutionValidationResult,
    FixingManifest,
    LogicalVariableCounts,
    ProtectionDeclaration,
    ReducibleProblemAdapter,
)
from qreduce.models import ResolvedRunConfig, RunResult
from qreduce.mwis import CanonicalMWISProblem, build_mwis_qubo, qubo_to_ising
from qreduce.mwis.energy import qubo_energy
from qreduce.mwis.validation import validate_binary_selection
from qreduce.solving.mwis import (
    MISBackendRequest,
    MISBackendResult,
    MISCompilationRequest,
    MISCompilationResult,
    MISCompletionStatus,
    MISSolverRegistry,
    RawMISSample,
    UnknownMISSolverError,
    builtin_mis_solver_registry,
    deduplicate_raw_mis_samples,
    normalize_backend_result,
)
from qreduce.solving.residual import (
    ClassicalSolveRequest,
    ClassicalSolveResult,
    ClassicalSolverRegistry,
    UnknownClassicalSolverError,
    builtin_classical_solver_registry,
)
from qreduce.status import (
    AdoptionStatus,
    ClassicalSolverStatus,
    PipelineStage,
    PostcheckStatus,
    ProblemForm,
    RunStatus,
    TerminalReason,
)


@dataclass(frozen=True, slots=True)
class CandidateRecord:
    """Audit record for one deduplicated MIS sample considered by the pipeline."""

    candidate_id: str
    raw_sample_id: str
    selected_item_ids: tuple[str, ...]
    raw_energy: float | None
    energy_recomputed_after_repair: float | None
    selection_weight: float | None
    num_selected: int | None
    num_violated_edges_before_repair: int
    repair_status: str
    repair_actions: tuple[str, ...] = ()
    candidate_rank_key: tuple[object, ...] | None = None
    selection_status: str = "not_selected"
    rejection_reason: str | None = None

    def __post_init__(self) -> None:
        if not self.candidate_id.strip() or not self.raw_sample_id.strip():
            raise ValueError("Candidate IDs cannot be blank.")
        object.__setattr__(self, "selected_item_ids", tuple(self.selected_item_ids))
        object.__setattr__(self, "repair_actions", tuple(self.repair_actions))
        if self.candidate_rank_key is not None:
            object.__setattr__(self, "candidate_rank_key", tuple(self.candidate_rank_key))

    def to_dict(self) -> dict[str, object]:
        return redact_metadata(to_primitive(self))  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class CandidateDomainItemRecord:
    """Audit record explaining one item's retained or excluded domain status."""

    item_id: str
    selection_frequency: int
    mean_candidate_quality: float | None
    decision: str
    reason: str

    def __post_init__(self) -> None:
        if not self.item_id.strip() or self.selection_frequency < 0:
            raise ValueError("Candidate-domain item records require valid item data.")
        if self.decision not in {"retained", "excluded"} or not self.reason.strip():
            raise ValueError("Candidate-domain item records require a decision and reason.")

    def to_dict(self) -> dict[str, object]:
        return redact_metadata(to_primitive(self))  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class SinglePassRunResult:
    """Complete in-memory, serializable output of one single-pass run."""

    run_result: RunResult
    resolved_config: ResolvedRunConfig
    original_variable_counts: LogicalVariableCounts | None = None
    residual_variable_counts: LogicalVariableCounts | None = None
    retained_item_ids: tuple[str, ...] = ()
    fixing_manifest: FixingManifest | None = None
    selected_mis_samples: tuple[RawMISSample, ...] = ()
    candidate_records: tuple[CandidateRecord, ...] = ()
    candidate_domain_item_records: tuple[CandidateDomainItemRecord, ...] = ()
    protection_declaration: ProtectionDeclaration | None = None
    mis_compilation_result: MISCompilationResult | None = None
    mis_execution_result: MISBackendResult | None = None
    classical_result: ClassicalSolveResult | None = None
    postcheck_result: FinalSolutionValidationResult | None = None
    domain_evaluation_metrics: tuple[DomainEvaluationMetric, ...] | None = None
    objective_sense: str = "minimize"
    original_primal_bound: float | None = None
    original_dual_bound: float | None = None
    original_bound_provenance: str = "none"
    original_problem_optimality_claim: str = "none"
    residual_problem_optimality_claim: str = "unavailable"
    metrics: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "retained_item_ids", tuple(self.retained_item_ids))
        object.__setattr__(
            self, "selected_mis_samples", tuple(self.selected_mis_samples)
        )
        object.__setattr__(self, "candidate_records", tuple(self.candidate_records))
        object.__setattr__(
            self, "candidate_domain_item_records", tuple(self.candidate_domain_item_records)
        )
        object.__setattr__(self, "metrics", MappingProxyType(dict(self.metrics)))

    def to_dict(self) -> dict[str, object]:
        """Return the complete in-memory result for repository runner persistence or transport."""

        return redact_metadata(to_primitive(self))  # type: ignore[return-value]


def run_single_pass(
    problem: object,
    adapter: ReducibleProblemAdapter,
    config: ResolvedRunConfig,
    *,
    mis_solver_registry: MISSolverRegistry | None = None,
    classical_solver_registry: ClassicalSolverRegistry | None = None,
    _model_export_write_path: str | None = None,
) -> SinglePassRunResult:
    """Execute one run and record end-to-end time for every terminal outcome."""
    started_at = perf_counter()
    input_hash = None
    describe_input = getattr(adapter, "describe_input", None)
    if callable(describe_input):
        try:
            input_hash = sha256_hex(redact_metadata(to_primitive(describe_input(problem))))
        except Exception:  # noqa: BLE001 - Input identity is optional for opaque adapters.
            input_hash = None
    result = _run_single_pass_with_counts(
        problem, adapter, config, mis_solver_registry=mis_solver_registry,
        classical_solver_registry=classical_solver_registry,
        _model_export_write_path=_model_export_write_path,
        _started_at=started_at,
    )
    metrics = dict(result.metrics)
    metrics["end_to_end_runtime_seconds"] = perf_counter() - started_at
    if result.candidate_records or "unique_sample_count" in metrics:
        metrics["unique_sample_count"] = len(result.candidate_records)
        metrics["processed_unique_sample_count"] = sum(
            record.repair_status != "not_processed_after_deduplication"
            for record in result.candidate_records
        )
        metrics["repaired_candidate_count"] = sum(
            record.repair_status == "repaired" for record in result.candidate_records
        )
    if result.candidate_domain_item_records:
        total = len(result.candidate_domain_item_records)
        retained = sum(record.decision == "retained" for record in result.candidate_domain_item_records)
        metrics["round_reduction_ratio"] = (total - retained) / total
        metrics["cumulative_reduction_ratio"] = metrics["round_reduction_ratio"]
    classical = result.classical_result
    residual_claim = "unavailable"
    if classical is not None and classical.solver_claimed_feasible:
        residual_claim = "certified_optimal" if classical.is_optimal else (
            "gap_bounded" if classical.gap is not None else "feasible_incumbent"
        )
    primal = None
    if result.run_result.adoption_status is AdoptionStatus.ADOPTED and result.postcheck_result:
        primal = result.postcheck_result.objective_recomputed
    return replace(result, metrics=metrics, run_result=replace(
        result.run_result, policy_hash=config.policy_provenance.policy_hash, input_hash=input_hash,
    ), original_primal_bound=primal, residual_problem_optimality_claim=residual_claim)


def _run_single_pass_with_counts(
    problem: object,
    adapter: ReducibleProblemAdapter,
    config: ResolvedRunConfig,
    *,
    mis_solver_registry: MISSolverRegistry | None = None,
    classical_solver_registry: ClassicalSolverRegistry | None = None,
    _model_export_write_path: str | None = None,
    _started_at: float | None = None,
    _round_index: int = 0,
) -> SinglePassRunResult:
    """Validate mandatory logical counts and preserve them across partial outcomes."""

    validation = validate_resolved_run_config(config)
    if not validation.is_valid:
        return _failed(config, PipelineStage.VALIDATION, validation.terminal_reason, _issues_message(validation))
    try:
        describe = getattr(adapter, "describe_logical_variables", None)
        if not callable(describe):
            raise TypeError("Adapter must implement describe_logical_variables.")
        original_counts = _validate_logical_counts(describe(problem))
    except Exception as error:  # noqa: BLE001 - Adapter contract failures are normalized.
        return _failed(config, PipelineStage.VALIDATION, TerminalReason.ADAPTER_FAILURE, str(error))
    tracking_adapter = _LogicalCountsAdapter(adapter)
    result = _run_single_pass(
        problem, tracking_adapter, config,
        mis_solver_registry=mis_solver_registry,
        classical_solver_registry=classical_solver_registry,
        _model_export_write_path=_model_export_write_path,
        _started_at=_started_at,
        _round_index=_round_index,
    )
    result = replace(
        result, original_variable_counts=original_counts,
        residual_variable_counts=tracking_adapter.residual_counts,
    )
    if result.postcheck_result is None:
        return result
    try:
        evaluate = getattr(adapter, "evaluate_domain_metrics", None)
        if not callable(evaluate):
            raise TypeError("Adapter must implement evaluate_domain_metrics.")
        metrics = evaluate(problem, result.classical_result, result.postcheck_result)
        if not isinstance(metrics, tuple | list) or any(
            not isinstance(metric, DomainEvaluationMetric) for metric in metrics
        ):
            raise TypeError("evaluate_domain_metrics must return a sequence of DomainEvaluationMetric.")
        if len({metric.metric_id for metric in metrics}) != len(metrics):
            raise ValueError("Domain metric IDs must be unique within a run.")
        return replace(result, domain_evaluation_metrics=tuple(metrics))
    except Exception as error:  # noqa: BLE001 - Adapter failures are normalized.
        return replace(result, run_result=replace(
            result.run_result, run_status=RunStatus.FAILED,
            terminal_reason=TerminalReason.ADAPTER_FAILURE,
            adoption_status=AdoptionStatus.NOT_ADOPTED,
            diagnostic_message=f"evaluate_domain_metrics: {error}",
        ))


def _validate_logical_counts(value: object) -> LogicalVariableCounts:
    if not isinstance(value, LogicalVariableCounts):
        raise TypeError("describe_logical_variables must return LogicalVariableCounts.")
    return value


class _LogicalCountsAdapter:
    """Capture residual counts as part of restriction without changing domain objects."""

    def __init__(self, adapter: ReducibleProblemAdapter) -> None:
        self._adapter = adapter
        self.residual_counts: LogicalVariableCounts | None = None

    def __getattr__(self, name: str) -> object:
        return getattr(self._adapter, name)

    def restrict_problem(
        self, problem: object, retained_item_ids: tuple[str, ...], fixing_manifest: FixingManifest
    ) -> object:
        residual = self._adapter.restrict_problem(problem, retained_item_ids, fixing_manifest)
        self.residual_counts = _validate_logical_counts(
            self._adapter.describe_logical_variables(residual)
        )
        return residual


def _run_single_pass(
    problem: object,
    adapter: ReducibleProblemAdapter,
    config: ResolvedRunConfig,
    *,
    mis_solver_registry: MISSolverRegistry | None = None,
    classical_solver_registry: ClassicalSolverRegistry | None = None,
    _model_export_write_path: str | None = None,
    _started_at: float | None = None,
    _round_index: int = 0,
) -> SinglePassRunResult:
    """Run one reduction using built-in solver factories and optional extensions."""

    validation = validate_resolved_run_config(config)
    if not validation.is_valid:
        return _failed(
            config,
            PipelineStage.VALIDATION,
            validation.terminal_reason,
            _issues_message(validation),
        )
    if (
        config.classical_solve.model_export_enabled
        and _model_export_write_path is None
        and Path(config.classical_solve.model_export_path).exists()
    ):
        return _failed(
            config, PipelineStage.VALIDATION, TerminalReason.INVALID_CONFIGURATION,
            "Model export path already exists; refusing to overwrite it.",
        )
    started_at = _started_at if _started_at is not None else perf_counter()
    mis_solver_registry = mis_solver_registry or builtin_mis_solver_registry()
    classical_solver_registry = classical_solver_registry or builtin_classical_solver_registry()
    try:
        mis_solver = mis_solver_registry.create(config.mis_solver_id)
    except UnknownMISSolverError as error:
        return _failed(
            config,
            PipelineStage.VALIDATION,
            TerminalReason.INVALID_CONFIGURATION,
            str(error),
        )
    try:
        graph = adapter.build_conflict_graph(problem)
        qubo = build_mwis_qubo(
            graph,
            _resolved_lambda_edge(config),
            allow_noncertifying_penalty=config.allow_noncertifying_penalty,
        )
        canonical_problem = CanonicalMWISProblem(graph, qubo, qubo_to_ising(qubo))
    except Exception as error:  # noqa: BLE001 - Domain errors become normalized outcomes.
        return _failed(
            config,
            PipelineStage.GRAPH,
            TerminalReason.GRAPH_CONSTRUCTION_FAILED,
            str(error),
        )

    try:
        capabilities = mis_solver.capabilities()
    except Exception as error:  # noqa: BLE001 - Extension failures must be normalized.
        return _failed(config, PipelineStage.MIS, TerminalReason.MIS_BACKEND_UNAVAILABLE, str(error))
    required_problem_form = _select_problem_form(capabilities.supported_problem_forms)
    if required_problem_form is None:
        return _failed(
            config,
            PipelineStage.MIS,
            TerminalReason.MIS_PROBLEM_REPRESENTATION_UNSUPPORTED,
            "The selected MIS solver does not support a canonical QReduce problem representation.",
        )
    capability_validation = validate_backend_compatibility(
        config.mis_execution, capabilities, required_problem_form
    )
    if not capability_validation.is_valid:
        return _failed(
            config,
            PipelineStage.MIS,
            capability_validation.terminal_reason,
            _issues_message(capability_validation),
        )
    compilation_timeout = effective_timeout(
        config.mis_execution.compilation_time_limit_seconds,
        _remaining_budget_or_zero(config, started_at),
    )
    if not compilation_timeout.validation.is_valid:
        return _budget_exhausted(config, PipelineStage.MIS)
    assert compilation_timeout.timeout_seconds is not None
    try:
        compilation = mis_solver.compile(
        canonical_problem,
        MISCompilationRequest(
            run_id=config.run_identity.run_id,
            round_index=_round_index,
            node_order=graph.node_ids,
            residual_time_budget_seconds=compilation_timeout.timeout_seconds,
            requested_provider_id=capabilities.provider_id,
            requested_backend_id=capabilities.backend_id,
            requested_backend_family=capabilities.backend_family,
            requested_execution_mode=capabilities.execution_mode,
            required_problem_form=required_problem_form,
        ),
        )
        if not isinstance(compilation, MISCompilationResult):
            raise TypeError("MIS backend must return MISCompilationResult.")
    except Exception as error:  # noqa: BLE001 - Extension failures must be normalized.
        return _failed(config, PipelineStage.MIS, TerminalReason.MIS_COMPILATION_FAILED, str(error))
    if compilation.compiled_job is None:
        return _failed(
            config,
            PipelineStage.MIS,
            compilation.terminal_reason,
            compilation.diagnostic_message,
            mis_compilation_result=compilation,
            metrics=_run_metrics(started_at, mis_compilation_result=compilation),
        )
    execution_timeout = effective_timeout(
        config.mis_execution.execution_time_limit_seconds,
        _remaining_budget_or_zero(config, started_at),
    )
    if not execution_timeout.validation.is_valid:
        return _budget_exhausted(
            config, PipelineStage.MIS, mis_compilation_result=compilation
        )
    assert execution_timeout.timeout_seconds is not None
    try:
        execution = mis_solver.solve(
        compilation.compiled_job,
        MISBackendRequest(
            run_id=config.run_identity.run_id,
            round_index=_round_index,
            compiled_job_id=compilation.compiled_job.compiled_job_id,
            node_order=graph.node_ids,
            random_seed=config.mis_execution.random_seed,
            requested_solution_count=config.mis_execution.requested_solution_count,
            residual_time_budget_seconds=execution_timeout.timeout_seconds,
            execution_parameters=config.mis_execution.provider_parameters,
        ),
        )
        if not isinstance(execution, MISBackendResult):
            raise TypeError("MIS backend must return MISBackendResult.")
    except Exception as error:  # noqa: BLE001 - Extension failures must be normalized.
        return _failed(
            config, PipelineStage.MIS, TerminalReason.MIS_EXECUTION_FAILED, str(error),
            mis_compilation_result=compilation,
            metrics=_run_metrics(started_at, mis_compilation_result=compilation),
        )
    if execution.completion_status not in {
        MISCompletionStatus.COMPLETED,
        MISCompletionStatus.TIME_LIMITED,
    }:
        return _failed(
            config,
            PipelineStage.MIS,
            execution.terminal_reason,
            execution.diagnostic_message,
            mis_compilation_result=compilation,
            mis_execution_result=execution,
            metrics=_run_metrics(
                started_at,
                mis_compilation_result=compilation,
                mis_execution_result=execution,
            ),
        )
    normalized = normalize_backend_result(canonical_problem, execution)
    if normalized.terminal_reason is not None:
        return _failed(
            config,
            PipelineStage.MIS,
            normalized.terminal_reason,
            normalized.diagnostic_message,
            mis_compilation_result=compilation,
            mis_execution_result=execution,
            metrics=_run_metrics(
                started_at,
                mis_compilation_result=compilation,
                mis_execution_result=execution,
            ),
        )
    deduplicated = deduplicate_raw_mis_samples(
        normalized.samples, config.mis_execution.max_distinct_samples
    )
    valid_samples = _valid_or_repaired_samples(
        canonical_problem, deduplicated.samples, config
    )
    selected_samples, selection_rejection_reasons = _select_diverse_samples_with_audit(
        valid_samples, config
    )
    candidate_records = _candidate_records(
        canonical_problem,
        deduplicated.samples,
        deduplicated.discarded_samples,
        valid_samples,
        selected_samples,
        selection_rejection_reasons,
        config,
    )
    if not selected_samples:
        return _failed(
            config,
            PipelineStage.CANDIDATE_DOMAIN,
            TerminalReason.NO_VALID_MIS_CANDIDATE,
            "The MIS solver produced no valid independent-set candidate samples.",
            mis_compilation_result=compilation,
            mis_execution_result=execution,
            candidate_records=candidate_records,
            metrics=_run_metrics(
                started_at,
                raw_sample_count=len(execution.samples),
                unique_sample_count=len(deduplicated.samples),
                valid_candidate_count=len(valid_samples),
                mis_compilation_result=compilation,
                mis_execution_result=execution,
            ),
        )
    try:
        protection_declaration = _normalize_protection_declaration(
            adapter.declare_protected_items(problem)
        )
    except Exception as error:  # noqa: BLE001 - Adapter failures are normalized.
        return _failed(
            config,
            PipelineStage.CANDIDATE_DOMAIN,
            TerminalReason.ADAPTER_FAILURE,
            f"The adapter failed while declaring protected items: {error}",
            selected_mis_samples=selected_samples,
            candidate_records=candidate_records,
            mis_compilation_result=compilation,
            mis_execution_result=execution,
            metrics=_candidate_metrics(
                started_at,
                execution,
                compilation,
                deduplicated.samples,
                valid_samples,
                selected_samples,
                (),
            ),
        )
    protected_item_ids = (
        protection_declaration.required_item_ids
        + protection_declaration.best_effort_item_ids
    )
    unknown_protected_item_ids = tuple(
        item_id for item_id in protected_item_ids if item_id not in graph.node_weights
    )
    if unknown_protected_item_ids:
        return _failed(
            config,
            PipelineStage.CANDIDATE_DOMAIN,
            TerminalReason.ADAPTER_FAILURE,
            "The adapter declared protected item IDs outside the reduction graph: "
            + ", ".join(unknown_protected_item_ids),
            selected_mis_samples=selected_samples,
            candidate_records=candidate_records,
            protection_declaration=protection_declaration,
            mis_compilation_result=compilation,
            mis_execution_result=execution,
            metrics=_candidate_metrics(
                started_at,
                execution,
                compilation,
                deduplicated.samples,
                valid_samples,
                selected_samples,
                (),
            ),
        )
    if (
        len(protection_declaration.required_item_ids)
        > config.reduction.candidate_domain_max_items
    ):
        return _failed(
            config,
            PipelineStage.CANDIDATE_DOMAIN,
            TerminalReason.PROTECTED_ITEMS_EXCEED_CANDIDATE_DOMAIN_CAP,
            "The number of protected candidate-domain items exceeds candidate_domain_max_items.",
            selected_mis_samples=selected_samples,
            candidate_records=candidate_records,
            protection_declaration=protection_declaration,
            mis_compilation_result=compilation,
            mis_execution_result=execution,
            metrics=_candidate_metrics(
                started_at,
                execution,
                compilation,
                deduplicated.samples,
                valid_samples,
                selected_samples,
                (),
            ),
        )
    retained_item_ids = _candidate_domain_item_ids(
        graph.node_ids,
        graph.node_weights,
        selected_samples,
        config,
        protected_item_ids=protection_declaration.required_item_ids,
        best_effort_item_ids=protection_declaration.best_effort_item_ids,
    )
    candidate_domain_item_records = _candidate_domain_item_records(
        graph.node_ids,
        selected_samples,
        retained_item_ids,
        protection_declaration,
    )
    if len(retained_item_ids) < config.reduction.candidate_domain_min_items:
        return _failed(
            config,
            PipelineStage.CANDIDATE_DOMAIN,
            TerminalReason.CANDIDATE_DOMAIN_TOO_SMALL,
            "The capped candidate domain is smaller than candidate_domain_min_items.",
            retained_item_ids,
            selected_mis_samples=selected_samples,
            candidate_records=candidate_records,
            candidate_domain_item_records=candidate_domain_item_records,
            protection_declaration=protection_declaration,
            mis_compilation_result=compilation,
            mis_execution_result=execution,
            metrics=_run_metrics(
                started_at,
                raw_sample_count=len(execution.samples),
                unique_sample_count=len(deduplicated.samples),
                valid_candidate_count=len(valid_samples),
                selected_candidate_count=len(selected_samples),
                candidate_domain_size=len(retained_item_ids),
                mis_compilation_result=compilation,
                mis_execution_result=execution,
            ),
        )
    try:
        domain_validation = adapter.validate_candidate_domain(problem, retained_item_ids)
    except Exception as error:  # noqa: BLE001 - Adapter failures are normalized.
        return _failed(
            config,
            PipelineStage.CANDIDATE_DOMAIN,
            TerminalReason.ADAPTER_FAILURE,
            f"The adapter failed while validating the candidate domain: {error}",
            retained_item_ids,
            selected_mis_samples=selected_samples,
            candidate_records=candidate_records,
            candidate_domain_item_records=candidate_domain_item_records,
            protection_declaration=protection_declaration,
            mis_compilation_result=compilation,
            mis_execution_result=execution,
            metrics=_candidate_metrics(
                started_at,
                execution,
                compilation,
                deduplicated.samples,
                valid_samples,
                selected_samples,
                retained_item_ids,
            ),
        )
    if not domain_validation.is_valid:
        return _failed(
            config,
            PipelineStage.CANDIDATE_DOMAIN,
            TerminalReason.CANDIDATE_DOMAIN_TOO_SMALL,
            "; ".join(domain_validation.failure_reasons),
            retained_item_ids,
            selected_mis_samples=selected_samples,
            candidate_records=candidate_records,
            candidate_domain_item_records=candidate_domain_item_records,
            protection_declaration=protection_declaration,
            mis_compilation_result=compilation,
            mis_execution_result=execution,
            metrics=_candidate_metrics(
                started_at,
                execution,
                compilation,
                deduplicated.samples,
                valid_samples,
                selected_samples,
                retained_item_ids,
            ),
        )
    if (
        domain_validation.minimum_required_items is not None
        and len(retained_item_ids) < domain_validation.minimum_required_items
    ):
        return _failed(
            config,
            PipelineStage.CANDIDATE_DOMAIN,
            TerminalReason.CANDIDATE_DOMAIN_TOO_SMALL,
            "The candidate domain is smaller than the adapter's minimum_required_items.",
            retained_item_ids,
            selected_mis_samples=selected_samples,
            candidate_records=candidate_records,
            candidate_domain_item_records=candidate_domain_item_records,
            protection_declaration=protection_declaration,
            mis_compilation_result=compilation,
            mis_execution_result=execution,
            metrics=_candidate_metrics(
                started_at,
                execution,
                compilation,
                deduplicated.samples,
                valid_samples,
                selected_samples,
                retained_item_ids,
            ),
        )
    try:
        fixing_manifest = adapter.build_fixing_manifest(problem, retained_item_ids)
        if isinstance(fixing_manifest, FixingManifest):
            fixing_manifest = replace(
                fixing_manifest, round_index=_round_index,
                source_candidate_ids=tuple(
                    record.candidate_id for record in candidate_records
                    if record.selection_status == "selected"
                ),
                policy_version=graph.graph_policy_version,
            )
    except Exception as error:  # noqa: BLE001 - Adapter restriction failures are normalized.
        return _failed(
            config,
            PipelineStage.RESTRICTION,
            TerminalReason.ADAPTER_FAILURE,
            str(error),
            retained_item_ids,
            selected_mis_samples=selected_samples,
            candidate_records=candidate_records,
            candidate_domain_item_records=candidate_domain_item_records,
            protection_declaration=protection_declaration,
            mis_compilation_result=compilation,
            mis_execution_result=execution,
            metrics=_candidate_metrics(
                started_at,
                execution,
                compilation,
                deduplicated.samples,
                valid_samples,
                selected_samples,
                retained_item_ids,
            ),
        )
    if not _fixing_manifest_matches_candidate_domain(
        fixing_manifest, graph.node_ids, retained_item_ids
    ):
        return _failed(
            config,
            PipelineStage.RESTRICTION,
            TerminalReason.ADAPTER_FAILURE,
            "The adapter returned a fixing manifest inconsistent with the candidate domain.",
            retained_item_ids,
            fixing_manifest=fixing_manifest,
            selected_mis_samples=selected_samples,
            candidate_records=candidate_records,
            candidate_domain_item_records=candidate_domain_item_records,
            protection_declaration=protection_declaration,
            mis_compilation_result=compilation,
            mis_execution_result=execution,
            metrics=_candidate_metrics(
                started_at,
                execution,
                compilation,
                deduplicated.samples,
                valid_samples,
                selected_samples,
                retained_item_ids,
            ),
        )
    try:
        reduced_problem = adapter.restrict_problem(
            problem, retained_item_ids, fixing_manifest
        )
    except Exception as error:  # noqa: BLE001 - Adapter restriction failures are normalized.
        return _failed(
            config,
            PipelineStage.RESTRICTION,
            TerminalReason.ADAPTER_FAILURE,
            str(error),
            retained_item_ids,
            fixing_manifest=fixing_manifest,
            selected_mis_samples=selected_samples,
            candidate_records=candidate_records,
            candidate_domain_item_records=candidate_domain_item_records,
            protection_declaration=protection_declaration,
            mis_compilation_result=compilation,
            mis_execution_result=execution,
            metrics=_candidate_metrics(
                started_at,
                execution,
                compilation,
                deduplicated.samples,
                valid_samples,
                selected_samples,
                retained_item_ids,
            ),
        )
    try:
        classical_solver = classical_solver_registry.create(
            config.classical_solve.classical_solver_id
        )
    except UnknownClassicalSolverError as error:
        return _failed(
            config,
            PipelineStage.CLASSICAL,
            TerminalReason.INVALID_CONFIGURATION,
            str(error),
            retained_item_ids,
            selected_mis_samples=selected_samples,
            candidate_records=candidate_records,
            candidate_domain_item_records=candidate_domain_item_records,
            protection_declaration=protection_declaration,
            fixing_manifest=fixing_manifest,
            mis_compilation_result=compilation,
            mis_execution_result=execution,
            metrics=_candidate_metrics(
                started_at,
                execution,
                compilation,
                deduplicated.samples,
                valid_samples,
                selected_samples,
                retained_item_ids,
            ),
        )
    remaining_budget = _remaining_budget_seconds(config, started_at)
    if remaining_budget is None:
        return _budget_exhausted(
            config,
            PipelineStage.CLASSICAL,
            retained_item_ids,
            selected_mis_samples=selected_samples,
            candidate_records=candidate_records,
            candidate_domain_item_records=candidate_domain_item_records,
            protection_declaration=protection_declaration,
            fixing_manifest=fixing_manifest,
            mis_compilation_result=compilation,
            mis_execution_result=execution,
            metrics=_candidate_metrics(
                started_at,
                execution,
                compilation,
                deduplicated.samples,
                valid_samples,
                selected_samples,
                retained_item_ids,
            ),
        )
    try:
        classical_result = classical_solver.solve(
        reduced_problem,
        ClassicalSolveRequest(
            run_id=config.run_identity.run_id,
            round_index=_round_index,
            time_limit_seconds=config.classical_solve.time_limit_seconds,
            remaining_end_to_end_seconds=remaining_budget,
            mip_gap_tolerance=config.classical_solve.mip_gap_tolerance,
            random_seed=config.classical_solve.random_seed,
            threads=config.classical_solve.threads,
            model_export_enabled=config.classical_solve.model_export_enabled,
            model_export_path=(
                _model_export_write_path or config.classical_solve.model_export_path
            ),
            requested_solver_id=config.classical_solve.classical_solver_id,
        ),
        )
        if not isinstance(classical_result, ClassicalSolveResult):
            raise TypeError("Classical backend must return ClassicalSolveResult.")
    except Exception as error:  # noqa: BLE001 - Extension failures must be normalized.
        return _failed(
            config, PipelineStage.CLASSICAL, TerminalReason.CLASSICAL_SOLVER_FAILED,
            str(error), retained_item_ids, fixing_manifest=fixing_manifest,
            selected_mis_samples=selected_samples, candidate_records=candidate_records,
            candidate_domain_item_records=candidate_domain_item_records,
            protection_declaration=protection_declaration,
            mis_compilation_result=compilation, mis_execution_result=execution,
            metrics=_candidate_metrics(started_at, execution, compilation,
                                       deduplicated.samples, valid_samples,
                                       selected_samples, retained_item_ids),
        )
    if _model_export_write_path and classical_result.model_export_path:
        classical_result = replace(
            classical_result, model_export_path=config.classical_solve.model_export_path
        )
    if not classical_result.solver_claimed_feasible:
        return _failed(
            config,
            PipelineStage.CLASSICAL,
            classical_result.terminal_reason,
            classical_result.diagnostic_message,
            retained_item_ids,
            classical_result,
            selected_mis_samples=selected_samples,
            candidate_records=candidate_records,
            candidate_domain_item_records=candidate_domain_item_records,
            protection_declaration=protection_declaration,
            fixing_manifest=fixing_manifest,
            mis_compilation_result=compilation,
            mis_execution_result=execution,
            metrics=_candidate_metrics(
                started_at,
                execution,
                compilation,
                deduplicated.samples,
                valid_samples,
                selected_samples,
                retained_item_ids,
                classical_result,
            ),
        )
    try:
        postcheck = adapter.validate_final_solution(
            problem,
            dict(classical_result.variable_values),
            fixing_manifest,
            config.classical_solve,
            solver_objective_value=classical_result.objective_value,
        )
        if not isinstance(postcheck, FinalSolutionValidationResult):
            raise TypeError("validate_final_solution must return FinalSolutionValidationResult.")
    except Exception as error:  # noqa: BLE001 - Adapter failures must be normalized.
        return _failed(
            config, PipelineStage.POSTCHECK, TerminalReason.ADAPTER_FAILURE,
            f"The adapter failed during post-check: {error}",
            retained_item_ids, classical_result,
            fixing_manifest=fixing_manifest, selected_mis_samples=selected_samples,
            candidate_records=candidate_records,
            candidate_domain_item_records=candidate_domain_item_records,
            protection_declaration=protection_declaration,
            mis_compilation_result=compilation, mis_execution_result=execution,
            metrics=_candidate_metrics(
                started_at, execution, compilation, deduplicated.samples,
                valid_samples, selected_samples, retained_item_ids, classical_result,
            ),
        )
    if not postcheck.postcheck_feasible:
        return SinglePassRunResult(
            run_result=RunResult(
                run_id=config.run_identity.run_id,
                run_status=RunStatus.FAILED,
                stage=PipelineStage.POSTCHECK,
                terminal_reason=TerminalReason.POSTCHECK_FAILED,
                classical_solver_status=classical_result.classical_solver_status,
                postcheck_status=PostcheckStatus.FAILED,
                adoption_status=AdoptionStatus.NOT_ADOPTED,
                diagnostic_message="; ".join(postcheck.failure_reasons),
                config_hash=config.config_hash(),
            ),
            retained_item_ids=retained_item_ids,
            resolved_config=config,
            fixing_manifest=fixing_manifest,
            selected_mis_samples=selected_samples,
            candidate_records=candidate_records,
            candidate_domain_item_records=candidate_domain_item_records,
            protection_declaration=protection_declaration,
            mis_compilation_result=compilation,
            mis_execution_result=execution,
            classical_result=classical_result,
            postcheck_result=postcheck,
            metrics=_candidate_metrics(
                started_at,
                execution,
                compilation,
                deduplicated.samples,
                valid_samples,
                selected_samples,
                retained_item_ids,
                classical_result,
                postcheck,
            ),
        )
    run_status = (
        RunStatus.PARTIAL_SUCCESS
        if classical_result.is_time_limited
        else RunStatus.SUCCESS
    )
    return SinglePassRunResult(
        run_result=RunResult(
            run_id=config.run_identity.run_id,
            run_status=run_status,
            stage=PipelineStage.POSTCHECK,
            terminal_reason=classical_result.terminal_reason,
            classical_solver_status=classical_result.classical_solver_status,
            postcheck_status=PostcheckStatus.PASSED,
            adoption_status=AdoptionStatus.ADOPTED,
            config_hash=config.config_hash(),
        ),
        retained_item_ids=retained_item_ids,
        resolved_config=config,
        fixing_manifest=fixing_manifest,
        selected_mis_samples=selected_samples,
        candidate_records=candidate_records,
        candidate_domain_item_records=candidate_domain_item_records,
        protection_declaration=protection_declaration,
        mis_compilation_result=compilation,
        mis_execution_result=execution,
        classical_result=classical_result,
        postcheck_result=postcheck,
        metrics=_candidate_metrics(
            started_at,
            execution,
            compilation,
            deduplicated.samples,
            valid_samples,
            selected_samples,
            retained_item_ids,
            classical_result,
            postcheck,
        ),
    )


def _failed(
    config: ResolvedRunConfig,
    stage: PipelineStage,
    terminal_reason: TerminalReason | None,
    diagnostic_message: str | None,
    retained_item_ids: tuple[str, ...] = (),
    classical_result: ClassicalSolveResult | None = None,
    *,
    fixing_manifest: FixingManifest | None = None,
    selected_mis_samples: tuple[RawMISSample, ...] = (),
    candidate_records: tuple[CandidateRecord, ...] = (),
    candidate_domain_item_records: tuple[CandidateDomainItemRecord, ...] = (),
    protection_declaration: ProtectionDeclaration | None = None,
    mis_compilation_result: MISCompilationResult | None = None,
    mis_execution_result: MISBackendResult | None = None,
    metrics: Mapping[str, object] | None = None,
) -> SinglePassRunResult:
    return SinglePassRunResult(
        run_result=RunResult(
            run_id=config.run_identity.run_id,
            run_status=RunStatus.FAILED,
            stage=stage,
            terminal_reason=terminal_reason or TerminalReason.ADAPTER_FAILURE,
            classical_solver_status=(
                classical_result.classical_solver_status
                if classical_result is not None
                else ClassicalSolverStatus.NOT_RUN
            ),
            postcheck_status=PostcheckStatus.NOT_RUN,
            adoption_status=AdoptionStatus.NOT_ADOPTED,
            diagnostic_message=diagnostic_message,
            config_hash=config.config_hash(),
        ),
        resolved_config=config,
        retained_item_ids=retained_item_ids,
        fixing_manifest=fixing_manifest,
        selected_mis_samples=selected_mis_samples,
        candidate_records=candidate_records,
        candidate_domain_item_records=candidate_domain_item_records,
        protection_declaration=protection_declaration,
        mis_compilation_result=mis_compilation_result,
        mis_execution_result=mis_execution_result,
        classical_result=classical_result,
        metrics=metrics or {},
    )


def _issues_message(validation: object) -> str:
    issues = getattr(validation, "issues", ())
    return "; ".join(issue.message for issue in issues)


def _select_problem_form(supported_forms: frozenset[ProblemForm]) -> ProblemForm | None:
    """Choose the first canonical form accepted by the selected MIS backend."""

    for problem_form in (
        ProblemForm.MIS_GRAPH,
        ProblemForm.QUBO,
        ProblemForm.BQM,
        ProblemForm.ISING,
    ):
        if problem_form in supported_forms:
            return problem_form
    return None


def _resolved_lambda_edge(config: ResolvedRunConfig) -> float:
    """Return the validated effective edge penalty from the explicit value or policy."""

    if config.lambda_edge is not None:
        return config.lambda_edge
    assert config.lambda_edge_policy is not None
    assert config.lambda_edge_policy.effective_lambda_edge is not None
    return config.lambda_edge_policy.effective_lambda_edge


def _remaining_budget_seconds(
    config: ResolvedRunConfig, started_at: float
) -> float | None:
    """Return the positive end-to-end budget available at the current pipeline stage."""

    remaining = config.reduction.max_end_to_end_runtime_seconds - (
        perf_counter() - started_at
    )
    return remaining if remaining > 0 else None


def _remaining_budget_or_zero(config: ResolvedRunConfig, started_at: float) -> float:
    """Return the remaining end-to-end budget for timeout clamping helpers."""

    return config.reduction.max_end_to_end_runtime_seconds - (perf_counter() - started_at)


def _budget_exhausted(
    config: ResolvedRunConfig,
    stage: PipelineStage,
    retained_item_ids: tuple[str, ...] = (),
    **result_context: object,
) -> SinglePassRunResult:
    """Produce the normalized result used when no positive backend budget remains."""

    return _failed(
        config,
        stage,
        TerminalReason.END_TO_END_TIME_BUDGET_EXHAUSTED,
        "The end-to-end time budget was exhausted before the next backend invocation.",
        retained_item_ids,
        **result_context,
    )


def _candidate_metrics(
    started_at: float,
    execution: MISBackendResult,
    compilation: MISCompilationResult,
    unique_samples: tuple[RawMISSample, ...],
    valid_samples: tuple[RawMISSample, ...],
    selected_samples: tuple[RawMISSample, ...],
    retained_item_ids: tuple[str, ...],
    classical_result: ClassicalSolveResult | None = None,
    postcheck_result: FinalSolutionValidationResult | None = None,
) -> dict[str, object]:
    """Build the common in-memory observability summary after candidate selection."""

    return _run_metrics(
        started_at,
        raw_sample_count=len(execution.samples),
        unique_sample_count=len(unique_samples),
        valid_candidate_count=len(valid_samples),
        selected_candidate_count=len(selected_samples),
        candidate_domain_size=len(retained_item_ids),
        mis_compilation_result=compilation,
        mis_execution_result=execution,
        classical_result=classical_result,
        postcheck_result=postcheck_result,
    )


def _run_metrics(
    started_at: float,
    *,
    raw_sample_count: int | None = None,
    unique_sample_count: int | None = None,
    valid_candidate_count: int | None = None,
    selected_candidate_count: int | None = None,
    candidate_domain_size: int | None = None,
    mis_compilation_result: MISCompilationResult | None = None,
    mis_execution_result: MISBackendResult | None = None,
    classical_result: ClassicalSolveResult | None = None,
    postcheck_result: FinalSolutionValidationResult | None = None,
) -> dict[str, object]:
    """Build metrics that callers may inspect or persist without filesystem side effects."""

    metrics: dict[str, object] = {
        "end_to_end_runtime_seconds": perf_counter() - started_at
    }
    if raw_sample_count is not None:
        metrics["raw_sample_count"] = raw_sample_count
    if unique_sample_count is not None:
        metrics["unique_sample_count"] = unique_sample_count
    if valid_candidate_count is not None:
        metrics["valid_candidate_count"] = valid_candidate_count
    if selected_candidate_count is not None:
        metrics["selected_candidate_count"] = selected_candidate_count
    if candidate_domain_size is not None:
        metrics["candidate_domain_size"] = candidate_domain_size
    if mis_compilation_result is not None:
        metrics["mis_compilation_runtime_seconds"] = (
            mis_compilation_result.runtime_seconds
        )
    if mis_execution_result is not None:
        metrics["mis_execution_runtime_seconds"] = mis_execution_result.runtime_seconds
        metrics["mis_runtime_seconds"] = (
            mis_compilation_result.runtime_seconds
            if mis_compilation_result is not None
            else 0.0
        ) + mis_execution_result.runtime_seconds
        metrics["mis_provider_id"] = mis_execution_result.effective_provider_id
        metrics["mis_backend_id"] = mis_execution_result.effective_backend_id
        metrics["mis_backend_family"] = mis_execution_result.backend_family
        metrics["mis_execution_mode"] = mis_execution_result.execution_mode
        metrics["mis_device_id"] = mis_execution_result.effective_device_id
    if classical_result is not None:
        metrics["classical_runtime_seconds"] = classical_result.runtime_seconds
        metrics["classical_solver_claimed_feasible"] = (
            classical_result.solver_claimed_feasible
        )
        metrics["objective_value"] = classical_result.objective_value
        metrics["best_bound"] = classical_result.best_bound
        metrics["solver_gap"] = classical_result.gap
    if postcheck_result is not None:
        metrics["postcheck_feasible"] = postcheck_result.postcheck_feasible
        metrics["postcheck_failure_reasons"] = postcheck_result.failure_reasons
        if postcheck_result.objective_recomputed is not None:
            metrics["objective_recomputed"] = postcheck_result.objective_recomputed
    return metrics


def _valid_or_repaired_samples(
    problem: CanonicalMWISProblem,
    samples: tuple[RawMISSample, ...],
    config: ResolvedRunConfig,
) -> tuple[RawMISSample, ...]:
    """Return structurally valid samples, repairing invalid samples only when enabled."""

    valid_samples: list[RawMISSample] = []
    for sample in samples:
        if sample.is_independent_set:
            valid_samples.append(sample)
        elif config.mis_execution.repair_enabled:
            repaired = _repair_sample(
                problem, sample, config.mis_execution.repair_max_iterations
            )
            if repaired is not None:
                valid_samples.append(repaired)
    return tuple(valid_samples)


def _candidate_records(
    problem: CanonicalMWISProblem,
    unique_samples: tuple[RawMISSample, ...],
    discarded_samples: tuple[RawMISSample, ...],
    valid_samples: tuple[RawMISSample, ...],
    selected_samples: tuple[RawMISSample, ...],
    selection_rejection_reasons: Mapping[str, str],
    config: ResolvedRunConfig,
) -> tuple[CandidateRecord, ...]:
    """Describe every deduplicated sample, including invalid and non-selected outcomes."""

    valid_by_id = {sample.raw_sample_id: sample for sample in valid_samples}
    selected_ids = {sample.raw_sample_id for sample in selected_samples}
    records: list[CandidateRecord] = []
    for index, sample in enumerate(unique_samples):
        processed = valid_by_id.get(sample.raw_sample_id)
        records.append(
            _candidate_record(
                f"candidate:{index:04d}",
                problem,
                sample,
                processed,
                config,
                selection_status=(
                    "selected" if sample.raw_sample_id in selected_ids else "not_selected"
                ),
                rejection_reason=_candidate_rejection_reason(
                    processed, selection_rejection_reasons, config
                ),
            )
        )
    offset = len(records)
    for index, sample in enumerate(discarded_samples, start=offset):
        records.append(
            _candidate_record(
                f"candidate:{index:04d}",
                problem,
                sample,
                None,
                config,
                selection_status="discarded",
                rejection_reason="max_distinct_samples_limit",
            )
        )
    return tuple(records)


def _candidate_record(
    candidate_id: str,
    problem: CanonicalMWISProblem,
    raw_sample: RawMISSample,
    processed_sample: RawMISSample | None,
    config: ResolvedRunConfig,
    *,
    selection_status: str,
    rejection_reason: str | None,
) -> CandidateRecord:
    """Build one audit record without treating a sample as a certified MWIS optimum."""

    selected_item_ids = (
        tuple(
            node_id
            for node_id, value in zip(
                problem.graph.node_ids, processed_sample.delta, strict=True
            )
            if value == 1
        )
        if processed_sample is not None
        else ()
    )
    was_repaired = processed_sample is not None and processed_sample.delta != raw_sample.delta
    repair_actions = (
        tuple(
            f"removed_item:{node_id}"
            for node_id, raw_value, processed_value in zip(
                problem.graph.node_ids,
                raw_sample.delta,
                processed_sample.delta,
                strict=True,
            )
            if raw_value == 1 and processed_value == 0
        )
        if was_repaired
        else ()
    )
    repair_status = (
        "not_processed_after_deduplication"
        if selection_status == "discarded"
        else "repaired"
        if was_repaired
        else "valid_without_repair"
        if processed_sample is not None
        else "repair_disabled"
        if not config.mis_execution.repair_enabled
        else "repair_failed"
    )
    return CandidateRecord(
        candidate_id=candidate_id,
        raw_sample_id=raw_sample.raw_sample_id,
        selected_item_ids=selected_item_ids,
        raw_energy=raw_sample.canonical_qubo_energy,
        energy_recomputed_after_repair=(
            processed_sample.canonical_qubo_energy if was_repaired else None
        ),
        selection_weight=(
            processed_sample.selection_weight if processed_sample is not None else None
        ),
        num_selected=(processed_sample.num_selected if processed_sample is not None else None),
        num_violated_edges_before_repair=raw_sample.num_violated_edges or 0,
        repair_status=repair_status,
        repair_actions=repair_actions,
        candidate_rank_key=(
            _candidate_rank_key(processed_sample) if processed_sample is not None else None
        ),
        selection_status=selection_status,
        rejection_reason=rejection_reason,
    )


def _candidate_rejection_reason(
    processed_sample: RawMISSample | None,
    selection_rejection_reasons: Mapping[str, str],
    config: ResolvedRunConfig,
) -> str | None:
    """Expose why a candidate did not reach the selected source-candidate set."""

    if processed_sample is None:
        return (
            "invalid_independent_set"
            if not config.mis_execution.repair_enabled
            else "repair_failed"
        )
    return selection_rejection_reasons.get(processed_sample.raw_sample_id)


def _candidate_rank_key(sample: RawMISSample) -> tuple[object, ...]:
    """Return the standard declared lexicographic ranking key for one valid sample."""

    return (
        -(sample.selection_weight or 0.0),
        -(sample.num_selected or 0),
        sample.canonical_qubo_energy
        if sample.canonical_qubo_energy is not None
        else float("inf"),
        sample.raw_sample_id,
    )


def _normalize_protection_declaration(
    declaration: tuple[str, ...] | ProtectionDeclaration,
) -> ProtectionDeclaration:
    """Accept the legacy mandatory tuple while making categorized protections explicit."""

    if isinstance(declaration, ProtectionDeclaration):
        return declaration
    return ProtectionDeclaration(mandatory_item_ids=tuple(declaration))


def _repair_sample(
    problem: CanonicalMWISProblem,
    sample: RawMISSample,
    repair_max_iterations: int,
) -> RawMISSample | None:
    """Repair conflicts by the mandatory deterministic endpoint-removal policy."""

    delta = list(sample.delta)
    for _ in range(repair_max_iterations):
        validation = validate_binary_selection(problem.graph, delta)
        if validation.is_independent_set:
            return _recomputed_sample(problem, sample, tuple(delta))
        left, right = min(validation.violated_edges)
        remove_node_id = _repair_endpoint_to_remove(problem, tuple(delta), left, right)
        delta[problem.graph.node_ids.index(remove_node_id)] = 0
    validation = validate_binary_selection(problem.graph, delta)
    if not validation.is_independent_set:
        return None
    return _recomputed_sample(problem, sample, tuple(delta))


def _repair_endpoint_to_remove(
    problem: CanonicalMWISProblem,
    delta: tuple[int, ...],
    left: str,
    right: str,
) -> str:
    """Choose an endpoint by weight, induced degree, then descending item ID."""

    selected = {
        node_id
        for node_id, value in zip(problem.graph.node_ids, delta, strict=True)
        if value == 1
    }
    induced_degree = {
        node_id: sum(
            1
            for edge_left, edge_right in problem.graph.edges
            if node_id in (edge_left, edge_right)
            and edge_left in selected
            and edge_right in selected
        )
        for node_id in (left, right)
    }
    return min(
        (left, right),
        key=lambda node_id: (
            problem.graph.node_weights[node_id],
            -induced_degree[node_id],
            _descending_lexical_key(node_id),
        ),
    )


def _descending_lexical_key(value: str) -> tuple[int, ...]:
    """Sort lexically larger IDs first while retaining a normal ascending key API."""

    return tuple(-ord(character) for character in value)


def _recomputed_sample(
    problem: CanonicalMWISProblem,
    sample: RawMISSample,
    delta: tuple[int, ...],
) -> RawMISSample:
    """Preserve raw provenance while recomputing canonical facts after repair."""

    validation = validate_binary_selection(problem.graph, delta)
    return replace(
        sample,
        delta=delta,
        canonical_qubo_energy=qubo_energy(problem.qubo, delta),
        selection_weight=validation.selection_weight,
        num_selected=validation.num_selected,
        is_independent_set=validation.is_independent_set,
        violated_edges=validation.violated_edges,
        num_violated_edges=validation.num_violated_edges,
    )


def _select_diverse_samples(
    samples: tuple[RawMISSample, ...], config: ResolvedRunConfig
) -> tuple[RawMISSample, ...]:
    """Rank valid samples and retain up to the configured number under Jaccard diversity."""

    selected_samples, _ = _select_diverse_samples_with_audit(samples, config)
    return selected_samples


def _select_diverse_samples_with_audit(
    samples: tuple[RawMISSample, ...], config: ResolvedRunConfig
) -> tuple[tuple[RawMISSample, ...], Mapping[str, str]]:
    """Apply diversity selection while retaining deterministic reasons for every rejection."""

    ranked_samples = sorted(samples, key=_candidate_rank_key)
    selected: list[RawMISSample] = []
    rejection_reasons: dict[str, str] = {}
    for sample in ranked_samples:
        if len(selected) == config.reduction.num_source_mis_candidates:
            rejection_reasons[sample.raw_sample_id] = "candidate_limit_reached"
        elif all(
            _jaccard_distance(sample.delta, accepted.delta)
            >= config.mis_execution.minimum_candidate_jaccard_distance
            for accepted in selected
        ):
            selected.append(sample)
        else:
            rejection_reasons[sample.raw_sample_id] = "insufficient_jaccard_distance"
    return tuple(selected), MappingProxyType(rejection_reasons)


def _jaccard_distance(
    left_delta: tuple[int, ...], right_delta: tuple[int, ...]
) -> float:
    """Return set Jaccard distance, defining two empty selections as distance zero."""

    left = {index for index, value in enumerate(left_delta) if value == 1}
    right = {index for index, value in enumerate(right_delta) if value == 1}
    union = left | right
    return 0.0 if not union else 1.0 - len(left & right) / len(union)


def _candidate_domain_item_ids(
    node_ids: tuple[str, ...],
    node_weights: Mapping[str, float],
    selected_samples: tuple[RawMISSample, ...],
    config: ResolvedRunConfig,
    *,
    protected_item_ids: tuple[str, ...] = (),
    best_effort_item_ids: tuple[str, ...] = (),
    apply_cap: bool = True,
) -> tuple[str, ...]:
    """Aggregate candidate votes and apply declared protection before the domain cap."""

    frequencies = {node_id: 0 for node_id in node_ids}
    quality_sums = {node_id: 0.0 for node_id in node_ids}
    for sample in selected_samples:
        quality = sample.selection_weight or 0.0
        for node_id, value in zip(node_ids, sample.delta, strict=True):
            if value == 1:
                frequencies[node_id] += 1
                quality_sums[node_id] += quality
    best_effort_item_id_set = set(best_effort_item_ids)
    ranked_item_ids = tuple(sorted(
        (
            node_id
            for node_id in node_ids
            if frequencies[node_id] > 0 or node_id in best_effort_item_id_set
        ),
        key=lambda node_id: (
            -frequencies[node_id],
            -(
                quality_sums[node_id] / frequencies[node_id]
                if frequencies[node_id] > 0
                else 0.0
            ),
            -node_weights[node_id],
            node_id,
        ),
    ))
    if not apply_cap:
        return ranked_item_ids
    protected_item_id_set = set(protected_item_ids)
    protected_in_canonical_order = tuple(
        node_id for node_id in node_ids if node_id in protected_item_id_set
    )
    ranked_unprotected_item_ids = tuple(
        node_id for node_id in ranked_item_ids if node_id not in protected_item_id_set
    )
    remaining_capacity = (
        config.reduction.candidate_domain_max_items - len(protected_in_canonical_order)
    )
    return protected_in_canonical_order + ranked_unprotected_item_ids[:remaining_capacity]


def _candidate_domain_item_records(
    node_ids: tuple[str, ...],
    selected_samples: tuple[RawMISSample, ...],
    retained_item_ids: tuple[str, ...],
    protection_declaration: ProtectionDeclaration,
) -> tuple[CandidateDomainItemRecord, ...]:
    """Record the policy reason for every retained or excluded graph item."""

    frequencies = {node_id: 0 for node_id in node_ids}
    quality_sums = {node_id: 0.0 for node_id in node_ids}
    for sample in selected_samples:
        quality = sample.selection_weight or 0.0
        for node_id, value in zip(node_ids, sample.delta, strict=True):
            if value == 1:
                frequencies[node_id] += 1
                quality_sums[node_id] += quality
    retained_item_id_set = set(retained_item_ids)
    required_item_id_set = set(protection_declaration.required_item_ids)
    best_effort_item_id_set = set(protection_declaration.best_effort_item_ids)
    records: list[CandidateDomainItemRecord] = []
    for node_id in node_ids:
        frequency = frequencies[node_id]
        mean_quality = quality_sums[node_id] / frequency if frequency else None
        if node_id in retained_item_id_set:
            reason = (
                "required_protection"
                if node_id in required_item_id_set
                else "best_effort_protection"
                if node_id in best_effort_item_id_set
                else "selected_candidate_aggregation"
            )
            decision = "retained"
        else:
            reason = (
                "best_effort_protection_excluded_by_cap"
                if node_id in best_effort_item_id_set
                else "candidate_domain_cap"
                if frequency > 0
                else "not_present_in_selected_candidates"
            )
            decision = "excluded"
        records.append(
            CandidateDomainItemRecord(
                item_id=node_id,
                selection_frequency=frequency,
                mean_candidate_quality=mean_quality,
                decision=decision,
                reason=reason,
            )
        )
    return tuple(records)


def _fixing_manifest_matches_candidate_domain(
    fixing_manifest: FixingManifest,
    graph_node_ids: tuple[str, ...],
    retained_item_ids: tuple[str, ...],
) -> bool:
    """Ensure an adapter fixes exactly the graph items outside the requested domain."""

    retained_item_id_set = set(retained_item_ids)
    expected_excluded_item_ids = tuple(
        node_id for node_id in graph_node_ids if node_id not in retained_item_id_set
    )
    return (
        fixing_manifest.retained_item_ids == retained_item_ids
        and fixing_manifest.excluded_item_ids == expected_excluded_item_ids
    )
