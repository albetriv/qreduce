"""Minimal domain-neutral single-pass MWIS reduction and residual solve orchestration."""

from dataclasses import dataclass

from qreduce.capabilities import validate_backend_compatibility
from qreduce.classical import (
    ClassicalSolveRequest,
    ClassicalSolveResult,
    UnknownClassicalSolverError,
    builtin_classical_solver_registry,
)
from qreduce.config import validate_resolved_run_config
from qreduce.domains import FinalSolutionValidationResult, ReducibleProblemAdapter
from qreduce.mis import (
    MISBackendRequest,
    MISCompilationRequest,
    MISCompletionStatus,
    UnknownMISSolverError,
    builtin_mis_solver_registry,
    deduplicate_raw_mis_samples,
    normalize_backend_result,
)
from qreduce.models import ResolvedRunConfig, RunResult
from qreduce.mwis import CanonicalMWISProblem, build_mwis_qubo, qubo_to_ising
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
    """Observable output of the v1 single-pass orchestration path."""

    run_result: RunResult
    retained_item_ids: tuple[str, ...] = ()
    classical_result: ClassicalSolveResult | None = None
    postcheck_result: FinalSolutionValidationResult | None = None


def run_single_pass(
    problem: object,
    adapter: ReducibleProblemAdapter,
    config: ResolvedRunConfig,
) -> SinglePassRunResult:
    """Run one MWIS reduction, one residual classical solve, and one post-check."""

    validation = validate_resolved_run_config(config)
    if not validation.is_valid:
        return _failed(config, PipelineStage.VALIDATION, validation.terminal_reason, _issues_message(validation))
    try:
        mis_solver = builtin_mis_solver_registry().create(config.mis_solver_id)
    except UnknownMISSolverError as error:
        return _failed(config, PipelineStage.VALIDATION, TerminalReason.INVALID_CONFIGURATION, str(error))
    try:
        graph = adapter.build_conflict_graph(problem)
        qubo = build_mwis_qubo(graph, config.lambda_edge or 0.0, allow_noncertifying_penalty=config.allow_noncertifying_penalty)
        canonical_problem = CanonicalMWISProblem(graph, qubo, qubo_to_ising(qubo))
    except Exception as error:  # noqa: BLE001 - Domain errors become normalized outcomes.
        return _failed(config, PipelineStage.GRAPH, TerminalReason.GRAPH_CONSTRUCTION_FAILED, str(error))

    capabilities = mis_solver.capabilities()
    capability_validation = validate_backend_compatibility(config.mis_execution, capabilities, ProblemForm.MIS_GRAPH)
    if not capability_validation.is_valid:
        return _failed(
            config,
            PipelineStage.MIS,
            capability_validation.terminal_reason,
            _issues_message(capability_validation),
        )
    compilation = mis_solver.compile(
        canonical_problem,
        MISCompilationRequest(
            run_id=config.artifacts.run_id,
            round_index=0,
            node_order=graph.node_ids,
            residual_time_budget_seconds=config.reduction.max_end_to_end_runtime_seconds,
            requested_provider_id=capabilities.provider_id,
            requested_backend_id=capabilities.backend_id,
            requested_backend_family=capabilities.backend_family,
            requested_execution_mode=capabilities.execution_mode,
            required_problem_form=ProblemForm.MIS_GRAPH,
        ),
    )
    if compilation.compiled_job is None:
        return _failed(config, PipelineStage.MIS, compilation.terminal_reason, compilation.diagnostic_message)
    execution = mis_solver.solve(
        compilation.compiled_job,
        MISBackendRequest(
            run_id=config.artifacts.run_id,
            round_index=0,
            compiled_job_id=compilation.compiled_job.compiled_job_id,
            node_order=graph.node_ids,
            random_seed=config.mis_execution.random_seed,
            requested_solution_count=config.mis_execution.requested_solution_count,
            residual_time_budget_seconds=config.reduction.max_end_to_end_runtime_seconds,
        ),
    )
    if execution.completion_status not in {MISCompletionStatus.COMPLETED, MISCompletionStatus.TIME_LIMITED}:
        return _failed(config, PipelineStage.MIS, execution.terminal_reason, execution.diagnostic_message)
    normalized = normalize_backend_result(canonical_problem, execution)
    if normalized.terminal_reason is not None:
        return _failed(config, PipelineStage.MIS, normalized.terminal_reason, normalized.diagnostic_message)
    deduplicated = deduplicate_raw_mis_samples(normalized.samples, config.mis_execution.max_distinct_samples)
    selected_samples = deduplicated.samples[: config.reduction.num_source_mis_candidates]
    if not selected_samples:
        return _failed(config, PipelineStage.CANDIDATE_DOMAIN, TerminalReason.NO_VALID_MIS_CANDIDATE, "The MIS solver produced no candidate samples.")
    retained_item_ids = tuple(
        node_id
        for node_index, node_id in enumerate(graph.node_ids)
        if any(sample.delta[node_index] == 1 for sample in selected_samples)
    )
    domain_validation = adapter.validate_candidate_domain(problem, retained_item_ids)
    if not domain_validation.is_valid:
        return _failed(
            config,
            PipelineStage.CANDIDATE_DOMAIN,
            TerminalReason.CANDIDATE_DOMAIN_TOO_SMALL,
            "; ".join(domain_validation.failure_reasons),
            retained_item_ids,
        )
    try:
        fixing_manifest = adapter.build_fixing_manifest(problem, retained_item_ids)  # type: ignore[attr-defined]
        reduced_problem = adapter.restrict_problem(problem, retained_item_ids, fixing_manifest)
    except Exception as error:  # noqa: BLE001 - Adapter restriction failures are normalized.
        return _failed(config, PipelineStage.RESTRICTION, TerminalReason.ADAPTER_FAILURE, str(error), retained_item_ids)
    try:
        classical_solver = builtin_classical_solver_registry().create(config.classical_solve.classical_solver_id)
    except UnknownClassicalSolverError as error:
        return _failed(config, PipelineStage.CLASSICAL, TerminalReason.INVALID_CONFIGURATION, str(error), retained_item_ids)
    classical_result = classical_solver.solve(
        reduced_problem,
        ClassicalSolveRequest(
            run_id=config.artifacts.run_id,
            round_index=0,
            time_limit_seconds=config.classical_solve.time_limit_seconds,
            remaining_end_to_end_seconds=config.reduction.max_end_to_end_runtime_seconds,
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
        )
    postcheck = adapter.validate_final_solution(
        problem,
        dict(classical_result.variable_values),
        fixing_manifest,
        config.classical_solve,
    )
    if not postcheck.postcheck_feasible:
        return SinglePassRunResult(
            run_result=RunResult(
                run_id=config.artifacts.run_id,
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
            classical_result=classical_result,
            postcheck_result=postcheck,
        )
    run_status = RunStatus.PARTIAL_SUCCESS if classical_result.is_time_limited else RunStatus.SUCCESS
    return SinglePassRunResult(
        run_result=RunResult(
            run_id=config.artifacts.run_id,
            run_status=run_status,
            stage=PipelineStage.POSTCHECK,
            terminal_reason=classical_result.terminal_reason,
            classical_solver_status=classical_result.classical_solver_status,
            postcheck_status=PostcheckStatus.PASSED,
            adoption_status=AdoptionStatus.ADOPTED,
            config_hash=config.config_hash(),
        ),
        retained_item_ids=retained_item_ids,
        classical_result=classical_result,
        postcheck_result=postcheck,
    )


def _failed(
    config: ResolvedRunConfig,
    stage: PipelineStage,
    terminal_reason: TerminalReason | None,
    diagnostic_message: str | None,
    retained_item_ids: tuple[str, ...] = (),
    classical_result: ClassicalSolveResult | None = None,
) -> SinglePassRunResult:
    return SinglePassRunResult(
        run_result=RunResult(
            run_id=config.artifacts.run_id,
            run_status=RunStatus.FAILED,
            stage=stage,
            terminal_reason=terminal_reason or TerminalReason.ADAPTER_FAILURE,
            classical_solver_status=(
                classical_result.classical_solver_status if classical_result is not None else ClassicalSolverStatus.NOT_RUN
            ),
            postcheck_status=PostcheckStatus.NOT_RUN,
            adoption_status=AdoptionStatus.NOT_ADOPTED,
            diagnostic_message=diagnostic_message,
            config_hash=config.config_hash(),
        ),
        retained_item_ids=retained_item_ids,
        classical_result=classical_result,
    )


def _issues_message(validation: object) -> str:
    issues = getattr(validation, "issues", ())
    return "; ".join(issue.message for issue in issues)