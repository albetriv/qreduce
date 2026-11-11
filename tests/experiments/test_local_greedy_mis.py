"""Tests for the dependency-free local greedy MIS backend."""

from dataclasses import replace

from qreduce.mwis import (
    CanonicalMWISProblem,
    ReductionGraph,
    build_mwis_qubo,
    qubo_to_ising,
)
from qreduce.solving.mwis.compilation import validate_compilation_request
from qreduce.solving.mwis.contracts import (
    MISBackendRequest,
    MISCompilationRequest,
    MISCompletionStatus,
)
from qreduce.solving.mwis.local_backend import LocalGreedyMISBackend
from qreduce.status import BackendFamily, ExecutionMode, ProblemForm, TerminalReason


def make_problem() -> CanonicalMWISProblem:
    """Build a graph with multiple valid greedy tie-break outcomes."""

    graph = ReductionGraph(
        node_ids=("a", "b", "c", "d"),
        node_weights={"a": 3.0, "b": 2.0, "c": 2.0, "d": 1.0},
        edges=(("a", "b"), ("a", "c"), ("b", "d"), ("c", "d")),
        edge_reasons={
            ("a", "b"): "conflict",
            ("a", "c"): "conflict",
            ("b", "d"): "conflict",
            ("c", "d"): "conflict",
        },
        graph_policy_id="test",
        graph_policy_version="1",
    )
    qubo = build_mwis_qubo(graph, 4.0)
    return CanonicalMWISProblem(graph, qubo, qubo_to_ising(qubo))


def make_compilation_request(problem: CanonicalMWISProblem) -> MISCompilationRequest:
    """Build a request matching the local backend's declared capability."""

    return MISCompilationRequest(
        run_id="run-001",
        round_index=0,
        node_order=problem.graph.node_ids,
        residual_time_budget_seconds=5.0,
        requested_provider_id="local",
        requested_backend_id="greedy_mis",
        requested_backend_family=BackendFamily.CLASSICAL_HEURISTIC,
        requested_execution_mode=ExecutionMode.LOCAL,
        required_problem_form=ProblemForm.MIS_GRAPH,
    )


def test_local_backend_compiles_and_returns_seeded_binary_samples_in_canonical_order() -> None:
    """The local implementation respects the separate compile/solve contracts."""

    backend = LocalGreedyMISBackend()
    problem = make_problem()
    compilation = backend.compile(problem, make_compilation_request(problem))
    assert compilation.compiled_job is not None
    assert compilation.completion_status is MISCompletionStatus.COMPLETED
    request = MISBackendRequest(
        run_id="run-001",
        round_index=0,
        compiled_job_id=compilation.compiled_job.compiled_job_id,
        node_order=problem.graph.node_ids,
        random_seed=19,
        requested_solution_count=3,
        residual_time_budget_seconds=5.0,
    )

    first_result = backend.solve(compilation.compiled_job, request)
    second_result = backend.solve(compilation.compiled_job, request)

    assert first_result.completion_status is MISCompletionStatus.COMPLETED
    assert tuple(sample.delta for sample in first_result.samples) == tuple(sample.delta for sample in second_result.samples)
    assert len(first_result.samples) == 3
    assert all(sample.node_order == problem.graph.node_ids for sample in first_result.samples)
    assert all(value in (0, 1) for sample in first_result.samples for value in sample.delta)


def test_local_backend_rejects_unsupported_problem_form_before_compilation() -> None:
    """The backend does not silently substitute QUBO or Ising for its graph input."""

    backend = LocalGreedyMISBackend()
    problem = make_problem()
    request = MISCompilationRequest(
        run_id="run-001",
        round_index=0,
        node_order=problem.graph.node_ids,
        residual_time_budget_seconds=5.0,
        requested_provider_id="local",
        requested_backend_id="greedy_mis",
        requested_backend_family=BackendFamily.CLASSICAL_HEURISTIC,
        requested_execution_mode=ExecutionMode.LOCAL,
        required_problem_form=ProblemForm.QUBO,
    )

    result = backend.compile(problem, request)

    assert result.compiled_job is None
    assert result.terminal_reason is TerminalReason.MIS_PROBLEM_REPRESENTATION_UNSUPPORTED


def test_compilation_rejects_the_actual_problem_size_above_backend_limit() -> None:
    """The operational size check uses graph variables, not the exact diagnostic cap."""

    backend = LocalGreedyMISBackend()
    problem = make_problem()
    limited_capabilities = replace(backend.capabilities(), maximum_variables=3)

    validation = validate_compilation_request(problem, make_compilation_request(problem), limited_capabilities)

    assert validation.is_valid is False
    assert validation.terminal_reason is TerminalReason.MIS_BACKEND_CAPABILITY_MISMATCH
    assert validation.issues[0].field == "maximum_variables"


def test_local_backend_returns_explicit_time_limited_result_when_budget_is_exhausted() -> None:
    """Budget exhaustion is reported rather than triggering a fallback algorithm."""

    backend = LocalGreedyMISBackend()
    problem = make_problem()
    compilation = backend.compile(problem, make_compilation_request(problem))
    assert compilation.compiled_job is not None
    result = backend.solve(
        compilation.compiled_job,
        MISBackendRequest(
            run_id="run-001",
            round_index=0,
            compiled_job_id=compilation.compiled_job.compiled_job_id,
            node_order=problem.graph.node_ids,
            random_seed=1,
            requested_solution_count=2,
            residual_time_budget_seconds=1e-12,
        ),
    )

    assert result.completion_status is MISCompletionStatus.TIME_LIMITED
    assert result.terminal_reason is TerminalReason.MIS_EXECUTION_TIME_BUDGET_EXHAUSTED


def test_local_backend_returns_time_limited_compilation_when_budget_expires(monkeypatch) -> None:
    """The declared compilation timeout is enforced before a job is returned."""

    import qreduce.solving.mwis.local_backend as local_backend_module

    timestamps = iter((0.0, 0.1))
    monkeypatch.setattr(local_backend_module, "perf_counter", lambda: next(timestamps))
    request = replace(make_compilation_request(make_problem()), residual_time_budget_seconds=0.05)

    result = LocalGreedyMISBackend().compile(make_problem(), request)

    assert result.compiled_job is None
    assert result.completion_status is MISCompletionStatus.TIME_LIMITED
    assert result.terminal_reason is TerminalReason.MIS_EXECUTION_TIME_BUDGET_EXHAUSTED