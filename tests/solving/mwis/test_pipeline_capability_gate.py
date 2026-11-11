"""Integration tests for the MIS capability gate in the single-pass pipeline."""

from qreduce.capabilities import RuntimeCapabilities
from qreduce.models import (
    ClassicalSolveOptions,
    LambdaEdgePolicy,
    MISExecutionOptions,
    ReductionPolicy,
    ResolvedRunConfig,
    RunIdentity,
)
from qreduce.mwis import ReductionGraph
from qreduce.pipeline import run_single_pass
from qreduce.solving.mwis import MISSolverRegistry
from qreduce.solving.mwis.local_backend import LocalGreedyMISBackend
from qreduce.status import (
    BackendFamily,
    ExecutionMode,
    PipelineStage,
    PostcheckMode,
    ProblemForm,
    TerminalReason,
)


class GraphOnlyAdapter:
    """Adapter that supplies the graph needed before capability validation stops the run."""

    def build_conflict_graph(self, problem: object, state: object | None = None) -> ReductionGraph:
        del problem, state
        return ReductionGraph(
            node_ids=("a",),
            node_weights={"a": 1.0},
            edges=(),
            edge_reasons={},
            graph_policy_id="test",
            graph_policy_version="1",
        )


class CompileMustNotRunBackend:
    """Backend whose compilation proves whether the pipeline passed the capability gate."""

    compile_called = False

    def capabilities(self) -> RuntimeCapabilities:
        return RuntimeCapabilities(
            provider_id="test",
            backend_id="compile_must_not_run",
            backend_family=BackendFamily.CLASSICAL_HEURISTIC,
            execution_mode=ExecutionMode.LOCAL,
            runtime_available=True,
            supported_problem_forms=frozenset({ProblemForm.MIS_GRAPH}),
            supports_random_seed=True,
            supports_solution_count=True,
            supports_execution_time_limit=False,
            supports_compilation_time_limit=False,
            supports_async_execution=False,
            supports_cancellation=False,
        )

    def compile(self, problem: object, request: object) -> object:
        del problem, request
        type(self).compile_called = True
        raise AssertionError("compile must not run after a capability mismatch")

    def solve(self, compiled_job: object, request: object) -> object:
        del compiled_job, request
        raise AssertionError("solve must not run after a capability mismatch")


class RecordingTimeoutBackend(LocalGreedyMISBackend):
    """Use the concrete local backend while retaining phase budgets for assertions."""

    compile_budget_seconds: float | None = None
    execution_budget_seconds: float | None = None

    def compile(self, problem: object, request: object) -> object:
        type(self).compile_budget_seconds = request.residual_time_budget_seconds
        return super().compile(problem, request)

    def solve(self, compiled_job: object, request: object) -> object:
        type(self).execution_budget_seconds = request.residual_time_budget_seconds
        return super().solve(compiled_job, request)


def test_capability_mismatch_stops_pipeline_before_backend_compilation() -> None:
    """A requested unsupported limit is rejected before an adapter compilation call."""

    CompileMustNotRunBackend.compile_called = False
    registry = MISSolverRegistry(include_builtins=False)
    registry.register("compile_must_not_run", CompileMustNotRunBackend)
    config = ResolvedRunConfig(
        schema_version="1.0",
        reduction=ReductionPolicy(1, 0, 1, 1, 0.0, 0, 30.0),
        lambda_edge=2.0,
        lambda_edge_policy=LambdaEdgePolicy("test", "1", 2.0),
        allow_noncertifying_penalty=False,
        mis_solver_id="compile_must_not_run",
        mis_execution=MISExecutionOptions(
            requested_solution_count=1,
            random_seed=7,
            max_distinct_samples=1,
            repair_enabled=False,
            repair_max_iterations=0,
            minimum_candidate_jaccard_distance=0.0,
            exact_solver_max_variables=1,
            execution_time_limit_seconds=1.0,
        ),
        classical_solve=ClassicalSolveOptions(
            "unused",
            1.0,
            None,
            None,
            False,
            1e-6,
            1e-6,
            1e-6,
            1e-6,
            PostcheckMode.STRICT,
        ),
        run_identity=RunIdentity("capability-gate"),
    )

    result = run_single_pass(object(), GraphOnlyAdapter(), config, mis_solver_registry=registry)

    assert CompileMustNotRunBackend.compile_called is False
    assert result.run_result.stage is PipelineStage.MIS
    assert result.run_result.terminal_reason is TerminalReason.MIS_BACKEND_CAPABILITY_MISMATCH
    assert result.mis_compilation_result is None
    assert result.mis_execution_result is None


def test_pipeline_clamps_each_mis_phase_to_its_configured_timeout() -> None:
    """Compilation and execution receive their phase limit, never the larger run budget."""

    RecordingTimeoutBackend.compile_budget_seconds = None
    RecordingTimeoutBackend.execution_budget_seconds = None
    registry = MISSolverRegistry(include_builtins=False)
    registry.register("recording_timeout", RecordingTimeoutBackend)
    config = ResolvedRunConfig(
        schema_version="1.0",
        reduction=ReductionPolicy(1, 0, 1, 1, 0.0, 0, 30.0),
        lambda_edge=2.0,
        lambda_edge_policy=LambdaEdgePolicy("test", "1", 2.0),
        allow_noncertifying_penalty=False,
        mis_solver_id="recording_timeout",
        mis_execution=MISExecutionOptions(
            requested_solution_count=1,
            random_seed=7,
            max_distinct_samples=1,
            repair_enabled=False,
            repair_max_iterations=0,
            minimum_candidate_jaccard_distance=0.0,
            exact_solver_max_variables=1,
            execution_time_limit_seconds=0.25,
            compilation_time_limit_seconds=0.5,
        ),
        classical_solve=ClassicalSolveOptions(
            "unused",
            1.0,
            None,
            None,
            False,
            1e-6,
            1e-6,
            1e-6,
            1e-6,
            PostcheckMode.STRICT,
        ),
        run_identity=RunIdentity("timeout-clamping"),
    )

    run_single_pass(object(), GraphOnlyAdapter(), config, mis_solver_registry=registry)

    assert RecordingTimeoutBackend.compile_budget_seconds == 0.5
    assert RecordingTimeoutBackend.execution_budget_seconds == 0.25