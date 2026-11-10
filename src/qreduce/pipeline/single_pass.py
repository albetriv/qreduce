"""Domain-neutral single-pass MWIS reduction and residual solve orchestration."""

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from time import perf_counter
from types import MappingProxyType

from qreduce.artifacts.metadata import redact_metadata, to_primitive
from qreduce.capabilities import validate_backend_compatibility
from qreduce.classical import (
    ClassicalSolveRequest,
    ClassicalSolveResult,
    UnknownClassicalSolverError,
    builtin_classical_solver_registry,
)
from qreduce.config import validate_resolved_run_config
from qreduce.domains import (
    FinalSolutionValidationResult,
    FixingManifest,
    ReducibleProblemAdapter,
)
from qreduce.mis import (
    MISBackendRequest,
    MISBackendResult,
    MISCompilationRequest,
    MISCompilationResult,
    MISCompletionStatus,
    RawMISSample,
    UnknownMISSolverError,
    builtin_mis_solver_registry,
    deduplicate_raw_mis_samples,
    normalize_backend_result,
)
from qreduce.models import ResolvedRunConfig, RunResult
from qreduce.mwis import CanonicalMWISProblem, build_mwis_qubo, qubo_to_ising
from qreduce.mwis.energy import qubo_energy
from qreduce.mwis.validation import validate_binary_selection
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
class SinglePassRunResult:
    """Complete in-memory, serializable output of one single-pass run."""

    run_result: RunResult
    resolved_config: ResolvedRunConfig
    retained_item_ids: tuple[str, ...] = ()
    fixing_manifest: FixingManifest | None = None
    selected_mis_samples: tuple[RawMISSample, ...] = ()
    mis_compilation_result: MISCompilationResult | None = None
    mis_execution_result: MISBackendResult | None = None
    classical_result: ClassicalSolveResult | None = None
    postcheck_result: FinalSolutionValidationResult | None = None
    metrics: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "retained_item_ids", tuple(self.retained_item_ids))
        object.__setattr__(
            self, "selected_mis_samples", tuple(self.selected_mis_samples)
        )
        object.__setattr__(self, "metrics", MappingProxyType(dict(self.metrics)))

    def to_dict(self) -> dict[str, object]:
        """Return the complete in-memory result for caller-owned persistence or transport."""

        return redact_metadata(to_primitive(self))  # type: ignore[return-value]


def run_single_pass(
    problem: object,
    adapter: ReducibleProblemAdapter,
    config: ResolvedRunConfig,
) -> SinglePassRunResult:
    """Run one MWIS reduction, one residual classical solve, and one post-check."""

    validation = validate_resolved_run_config(config)
    if not validation.is_valid:
        return _failed(
            config,
            PipelineStage.VALIDATION,
            validation.terminal_reason,
            _issues_message(validation),
        )
    started_at = perf_counter()
    try:
        mis_solver = builtin_mis_solver_registry().create(config.mis_solver_id)
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

    capabilities = mis_solver.capabilities()
    capability_validation = validate_backend_compatibility(
        config.mis_execution, capabilities, ProblemForm.MIS_GRAPH
    )
    if not capability_validation.is_valid:
        return _failed(
            config,
            PipelineStage.MIS,
            capability_validation.terminal_reason,
            _issues_message(capability_validation),
        )
    remaining_budget = _remaining_budget_seconds(config, started_at)
    if remaining_budget is None:
        return _budget_exhausted(config, PipelineStage.MIS)
    compilation = mis_solver.compile(
        canonical_problem,
        MISCompilationRequest(
            run_id=config.run_identity.run_id,
            round_index=0,
            node_order=graph.node_ids,
            residual_time_budget_seconds=remaining_budget,
            requested_provider_id=capabilities.provider_id,
            requested_backend_id=capabilities.backend_id,
            requested_backend_family=capabilities.backend_family,
            requested_execution_mode=capabilities.execution_mode,
            required_problem_form=ProblemForm.MIS_GRAPH,
        ),
    )
    if compilation.compiled_job is None:
        return _failed(
            config,
            PipelineStage.MIS,
            compilation.terminal_reason,
            compilation.diagnostic_message,
            mis_compilation_result=compilation,
            metrics=_run_metrics(started_at, mis_compilation_result=compilation),
        )
    remaining_budget = _remaining_budget_seconds(config, started_at)
    if remaining_budget is None:
        return _budget_exhausted(
            config, PipelineStage.MIS, mis_compilation_result=compilation
        )
    execution = mis_solver.solve(
        compilation.compiled_job,
        MISBackendRequest(
            run_id=config.run_identity.run_id,
            round_index=0,
            compiled_job_id=compilation.compiled_job.compiled_job_id,
            node_order=graph.node_ids,
            random_seed=config.mis_execution.random_seed,
            requested_solution_count=config.mis_execution.requested_solution_count,
            residual_time_budget_seconds=remaining_budget,
        ),
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
    selected_samples = _select_diverse_samples(valid_samples, config)
    if not selected_samples:
        return _failed(
            config,
            PipelineStage.CANDIDATE_DOMAIN,
            TerminalReason.NO_VALID_MIS_CANDIDATE,
            "The MIS solver produced no valid independent-set candidate samples.",
            mis_compilation_result=compilation,
            mis_execution_result=execution,
            metrics=_run_metrics(
                started_at,
                raw_sample_count=len(execution.samples),
                unique_sample_count=len(deduplicated.samples),
                valid_candidate_count=len(valid_samples),
                mis_compilation_result=compilation,
                mis_execution_result=execution,
            ),
        )
    retained_item_ids = _candidate_domain_item_ids(
        graph.node_ids, graph.node_weights, selected_samples, config
    )
    if len(retained_item_ids) < config.reduction.candidate_domain_min_items:
        return _failed(
            config,
            PipelineStage.CANDIDATE_DOMAIN,
            TerminalReason.CANDIDATE_DOMAIN_TOO_SMALL,
            "The capped candidate domain is smaller than candidate_domain_min_items.",
            retained_item_ids,
            selected_mis_samples=selected_samples,
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
    domain_validation = adapter.validate_candidate_domain(problem, retained_item_ids)
    if not domain_validation.is_valid:
        return _failed(
            config,
            PipelineStage.CANDIDATE_DOMAIN,
            TerminalReason.CANDIDATE_DOMAIN_TOO_SMALL,
            "; ".join(domain_validation.failure_reasons),
            retained_item_ids,
            selected_mis_samples=selected_samples,
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
            selected_mis_samples=selected_samples,
            fixing_manifest=fixing_manifest if "fixing_manifest" in locals() else None,
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
        classical_solver = builtin_classical_solver_registry().create(
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
    classical_result = classical_solver.solve(
        reduced_problem,
        ClassicalSolveRequest(
            run_id=config.run_identity.run_id,
            round_index=0,
            time_limit_seconds=config.classical_solve.time_limit_seconds,
            remaining_end_to_end_seconds=remaining_budget,
            mip_gap_tolerance=config.classical_solve.mip_gap_tolerance,
            random_seed=config.classical_solve.random_seed,
            threads=config.classical_solve.threads,
            model_export_enabled=config.classical_solve.model_export_enabled,
            requested_solver_id=config.classical_solve.classical_solver_id,
        ),
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
    postcheck = adapter.validate_final_solution(
        problem,
        dict(classical_result.variable_values),
        fixing_manifest,
        config.classical_solve,
        solver_objective_value=classical_result.objective_value,
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
        mis_compilation_result=mis_compilation_result,
        mis_execution_result=mis_execution_result,
        classical_result=classical_result,
        metrics=metrics or {},
    )


def _issues_message(validation: object) -> str:
    issues = getattr(validation, "issues", ())
    return "; ".join(issue.message for issue in issues)


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

    ranked_samples = sorted(
        samples,
        key=lambda sample: (
            -(sample.selection_weight or 0.0),
            -(sample.num_selected or 0),
            sample.canonical_qubo_energy
            if sample.canonical_qubo_energy is not None
            else float("inf"),
            sample.raw_sample_id,
        ),
    )
    selected: list[RawMISSample] = []
    for sample in ranked_samples:
        if all(
            _jaccard_distance(sample.delta, accepted.delta)
            >= config.mis_execution.minimum_candidate_jaccard_distance
            for accepted in selected
        ):
            selected.append(sample)
        if len(selected) == config.reduction.num_source_mis_candidates:
            break
    return tuple(selected)


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
) -> tuple[str, ...]:
    """Aggregate candidate votes, rank items, and enforce the configured domain cap."""

    frequencies = {node_id: 0 for node_id in node_ids}
    quality_sums = {node_id: 0.0 for node_id in node_ids}
    for sample in selected_samples:
        quality = sample.selection_weight or 0.0
        for node_id, value in zip(node_ids, sample.delta, strict=True):
            if value == 1:
                frequencies[node_id] += 1
                quality_sums[node_id] += quality
    ranked_item_ids = sorted(
        (node_id for node_id in node_ids if frequencies[node_id] > 0),
        key=lambda node_id: (
            -frequencies[node_id],
            -(quality_sums[node_id] / frequencies[node_id]),
            -node_weights[node_id],
            node_id,
        ),
    )
    return tuple(ranked_item_ids[: config.reduction.candidate_domain_max_items])
