"""Tests for the classical-only baseline (max_reduction_rounds=0).

These tests verify that when max_reduction_rounds=0, the pipeline:
1. Does NOT invoke any MIS components (solver, registry, graph building)
2. Solves the full original problem classically
3. Produces correct manifest with origin="no_reduction"
4. Has original_variable_counts == residual_variable_counts
5. Returns is_classical_only=True and round_count=0
"""

import pytest

from qreduce.domains import (
    DomainValidationResult,
    FinalSolutionValidationResult,
    FixingManifest,
    LogicalVariableCounts,
    ProtectionDeclaration,
)
from qreduce.models import (
    ClassicalSolveOptions,
    LambdaEdgePolicy,
    MISExecutionOptions,
    PolicyProvenance,
    ReductionPolicy,
    ResolvedRunConfig,
    RunIdentity,
)
from qreduce.mwis import ReductionGraph
from qreduce.pipeline import PipelineRunResult, run_pipeline
from qreduce.solving.mwis import MISSolverRegistry
from qreduce.solving.residual import (
    ClassicalModelProvider,
    ClassicalOptimizationModel,
    ClassicalSolveResult,
    ClassicalSolverRegistry,
    ClassicalVariable,
    ClassicalVariableType,
    LinearConstraint,
    LinearConstraintSense,
)
from qreduce.status import (
    ClassicalSolverStatus,
    PostcheckMode,
    RunStatus,
    TerminalReason,
)

# --- Test fixtures and helpers ---


class SimpleItem:
    """A reducible item for testing."""

    def __init__(self, item_id: str, weight: float = 1.0):
        self.item_id = item_id
        self.weight = weight


class SimpleProblem:
    """A minimal problem for testing classical-only baseline."""

    def __init__(self, items: list[SimpleItem], conflicts: list[tuple[str, str]] | None = None):
        self.items = {item.item_id: item for item in items}
        self.conflicts = conflicts or []


class SimpleResidualProblem(ClassicalModelProvider):
    """A restricted problem that provides a classical model."""

    def __init__(self, original: SimpleProblem, retained_ids: tuple[str, ...], manifest: FixingManifest):
        self.original = original
        self.retained_ids = retained_ids
        self.manifest = manifest

    def build_classical_model(self) -> ClassicalOptimizationModel:
        """Build a trivial LP: minimize sum of x_i, with x_i >= 0."""
        variables = tuple(
            ClassicalVariable(
                name=f"x_{item_id}",
                variable_type=ClassicalVariableType.CONTINUOUS,
                lower_bound=0.0,
                upper_bound=1.0,
            )
            for item_id in self.retained_ids
        )
        linear_objective = {f"x_{item_id}": 1.0 for item_id in self.retained_ids}
        # Add a simple constraint: sum >= 0.5 (to make it non-trivial)
        constraint = LinearConstraint(
            name="sum_constraint",
            coefficients={f"x_{item_id}": 1.0 for item_id in self.retained_ids},
            sense=LinearConstraintSense.GREATER_EQUAL,
            right_hand_side=0.5,
        )
        return ClassicalOptimizationModel(
            variables=variables,
            linear_objective=linear_objective,
            quadratic_objective=(),
            linear_constraints=(constraint,),
            objective_offset=0.0,
        )


class SimpleAdapter:
    """A minimal adapter for testing classical-only baseline."""

    def __init__(self):
        self.graph_build_calls: list = []
        self.mis_calls: list = []

    def identify_reducible_items(self, problem: SimpleProblem | SimpleResidualProblem) -> list[str]:
        if isinstance(problem, SimpleResidualProblem):
            return list(problem.retained_ids)
        return list(problem.items.keys())

    def describe_logical_variables(self, problem: SimpleProblem | SimpleResidualProblem) -> LogicalVariableCounts:
        items = self.identify_reducible_items(problem)
        return LogicalVariableCounts(binary_free=0, integer_free=0, continuous_free=len(items))

    def build_conflict_graph(self, problem: SimpleProblem | SimpleResidualProblem, state: object | None = None) -> ReductionGraph:
        """Record that graph building was attempted (should NOT happen for classical-only)."""
        self.graph_build_calls.append(problem)
        if isinstance(problem, SimpleResidualProblem):
            original = problem.original
            node_ids = problem.retained_ids
        else:
            original = problem
            node_ids = tuple(problem.items.keys())

        return ReductionGraph(
            node_ids=node_ids,
            node_weights={item_id: original.items[item_id].weight for item_id in node_ids},
            edges=(),
            edge_reasons={},
            graph_policy_id="test",
            graph_policy_version="1",
        )

    def declare_protected_items(self, problem: SimpleProblem | SimpleResidualProblem) -> ProtectionDeclaration:
        return ProtectionDeclaration((), (), (), ())

    def validate_candidate_domain(self, problem: SimpleProblem | SimpleResidualProblem, retained: tuple[str, ...]) -> DomainValidationResult:
        return DomainValidationResult(True, 1)

    def build_fixing_manifest(self, problem: SimpleProblem | SimpleResidualProblem, retained: tuple[str, ...]) -> FixingManifest:
        """This should NOT be called for classical-only baseline."""
        raise AssertionError("build_fixing_manifest should not be called for classical-only baseline")

    def restrict_problem(
        self, problem: SimpleProblem | SimpleResidualProblem, retained: tuple[str, ...], manifest: FixingManifest
    ) -> SimpleResidualProblem:
        original = problem.original if isinstance(problem, SimpleResidualProblem) else problem
        return SimpleResidualProblem(original, retained, manifest)

    def build_residual_model(self, problem: SimpleResidualProblem, fixing_manifest: FixingManifest) -> ClassicalOptimizationModel:
        """Build the classical optimization model."""
        return problem.build_classical_model()

    def validate_final_solution(
        self,
        problem: SimpleProblem | SimpleResidualProblem,
        solution: object,
        fixing_manifest: FixingManifest,
        tolerances: object,
        solver_objective_value: float | None = None,
    ) -> FinalSolutionValidationResult:
        return FinalSolutionValidationResult(
            postcheck_feasible=True,
            fixed_variable_compliance=True,
            original_constraint_compliance=True,
            integrality_compliance=True,
            objective_recomputed=solver_objective_value or 0.5,
            solver_objective_compliance=True,
        )

    def evaluate_domain_metrics(self, problem: object, classical_result: object, postcheck_result: object) -> tuple:
        return ()


class RecordingClassicalSolver:
    """Records calls and returns configurable results."""

    def __init__(
        self,
        default_status: ClassicalSolverStatus = ClassicalSolverStatus.OPTIMAL,
    ):
        self._default_status = default_status
        self.calls: list[dict] = []

    def solve(self, problem, request) -> ClassicalSolveResult:
        self.calls.append({"round": request.round_index, "problem": problem})

        is_optimal = self._default_status == ClassicalSolverStatus.OPTIMAL
        is_feasible = self._default_status in (ClassicalSolverStatus.OPTIMAL, ClassicalSolverStatus.FEASIBLE)

        return ClassicalSolveResult(
            classical_solver_status=self._default_status,
            terminal_reason=None if is_feasible else TerminalReason.CLASSICAL_SOLVER_INFEASIBLE,
            solver_claimed_feasible=is_feasible,
            objective_value=0.5 if is_feasible else None,
            best_bound=0.5 if is_optimal else None,
            gap=0.0 if is_optimal else None,
            is_optimal=is_optimal,
            is_time_limited=False,
            runtime_seconds=0.1,
            variable_values={"x_a": 0.5} if is_feasible else {},
        )


class FailingMISSolver:
    """A MIS solver that fails if called - for testing that MIS is not invoked."""

    def solve(self, *args, **kwargs):
        raise AssertionError("MIS solver should not be called for classical-only baseline")


def make_classical_only_config(
    max_rounds: int = 0,
    classical_solver_id: str = "recording",
    mis_solver_id: str = "failing_mis",
) -> ResolvedRunConfig:
    """Create a test configuration for classical-only baseline."""
    reduction = ReductionPolicy(
        max_reduction_rounds=max_rounds,
        candidate_domain_min_items=1,
        candidate_domain_max_items=100,
        num_source_mis_candidates=3,
        min_reduction_ratio=0.0,
        target_binary_variables=0,
        max_end_to_end_runtime_seconds=60.0,
        recovery_policy_on_domain_too_small="fail",
        recovery_policy_on_infeasible="fail",
        max_recovery_attempts=0,
    )
    return ResolvedRunConfig(
        schema_version="1.0",
        reduction=reduction,
        lambda_edge=10.0,
        lambda_edge_policy=LambdaEdgePolicy("standard", "1", 10.0),
        allow_noncertifying_penalty=False,
        mis_solver_id=mis_solver_id,
        mis_execution=MISExecutionOptions(
            requested_solution_count=10,
            random_seed=42,
            max_distinct_samples=5,
            repair_enabled=True,
            repair_max_iterations=5,
            minimum_candidate_jaccard_distance=0.0,
            exact_solver_max_variables=0,
        ),
        classical_solve=ClassicalSolveOptions(
            classical_solver_id=classical_solver_id,
            time_limit_seconds=30.0,
            mip_gap_tolerance=0.01,
            threads=1,
            model_export_enabled=False,
            primal_feasibility_tolerance=1e-6,
            integrality_tolerance=1e-5,
            objective_recomputation_absolute_tolerance=1e-6,
            objective_recomputation_relative_tolerance=1e-4,
            postcheck_mode=PostcheckMode.STRICT,
        ),
        run_identity=RunIdentity("classical-only-test"),
        policy_provenance=PolicyProvenance(),
    )


# --- Tests ---


class TestClassicalOnlyBaseline:
    """Tests for max_reduction_rounds=0 classical-only baseline."""

    def test_classical_only_succeeds_without_mis(self):
        """Classical-only baseline completes successfully without MIS."""
        problem = SimpleProblem([
            SimpleItem("a", 1.0),
            SimpleItem("b", 2.0),
            SimpleItem("c", 3.0),
        ])
        adapter = SimpleAdapter()
        config = make_classical_only_config(max_rounds=0)

        classical_registry = ClassicalSolverRegistry(include_builtins=False)
        classical_registry.register("recording", RecordingClassicalSolver)

        # Do NOT register any MIS solver - should not matter
        mis_registry = MISSolverRegistry(include_builtins=False)
        mis_registry.register("failing_mis", FailingMISSolver)

        result = run_pipeline(
            problem, adapter, config,
            classical_solver_registry=classical_registry,
            mis_solver_registry=mis_registry,
        )

        assert isinstance(result, PipelineRunResult)
        assert result.run_result.run_status == RunStatus.SUCCESS
        assert result.is_classical_only is True
        assert result.reduction_round_count == 0

    def test_classical_only_does_not_invoke_mis_solver(self):
        """With max_reduction_rounds=0, MIS solver is never called."""
        problem = SimpleProblem([
            SimpleItem("a", 1.0),
            SimpleItem("b", 2.0),
        ])
        adapter = SimpleAdapter()
        config = make_classical_only_config(max_rounds=0)

        classical_registry = ClassicalSolverRegistry(include_builtins=False)
        classical_registry.register("recording", RecordingClassicalSolver)

        # Register a MIS solver that will fail if called
        mis_registry = MISSolverRegistry(include_builtins=False)
        mis_registry.register("failing_mis", FailingMISSolver)

        # This should succeed because MIS is never invoked
        result = run_pipeline(
            problem, adapter, config,
            classical_solver_registry=classical_registry,
            mis_solver_registry=mis_registry,
        )

        assert result.run_result.run_status == RunStatus.SUCCESS

    def test_classical_only_does_not_build_conflict_graph(self):
        """With max_reduction_rounds=0, conflict graph is never built."""
        problem = SimpleProblem([
            SimpleItem("a", 1.0),
            SimpleItem("b", 2.0),
        ])
        adapter = SimpleAdapter()
        config = make_classical_only_config(max_rounds=0)

        classical_registry = ClassicalSolverRegistry(include_builtins=False)
        classical_registry.register("recording", RecordingClassicalSolver)
        mis_registry = MISSolverRegistry(include_builtins=False)
        mis_registry.register("failing_mis", FailingMISSolver)

        run_pipeline(
            problem, adapter, config,
            classical_solver_registry=classical_registry,
            mis_solver_registry=mis_registry,
        )

        # Adapter should not have received any graph-building calls
        assert len(adapter.graph_build_calls) == 0

    def test_classical_only_manifest_is_no_reduction(self):
        """Classical-only manifest has origin='no_reduction' and retains all items."""
        problem = SimpleProblem([
            SimpleItem("a", 1.0),
            SimpleItem("b", 2.0),
            SimpleItem("c", 3.0),
        ])
        adapter = SimpleAdapter()
        config = make_classical_only_config(max_rounds=0)

        classical_registry = ClassicalSolverRegistry(include_builtins=False)
        classical_registry.register("recording", RecordingClassicalSolver)
        mis_registry = MISSolverRegistry(include_builtins=False)
        mis_registry.register("failing_mis", FailingMISSolver)

        result = run_pipeline(
            problem, adapter, config,
            classical_solver_registry=classical_registry,
            mis_solver_registry=mis_registry,
        )

        manifest = result.cumulative_fixing_manifest
        assert manifest is not None
        assert manifest.origin == "no_reduction"
        assert set(manifest.retained_item_ids) == {"a", "b", "c"}
        assert manifest.excluded_item_ids == ()
        assert manifest.entries == ()

    def test_classical_only_retains_all_items(self):
        """Classical-only baseline retains all reducible items."""
        items = [SimpleItem(f"item_{i}", i + 1.0) for i in range(5)]
        problem = SimpleProblem(items)
        adapter = SimpleAdapter()
        config = make_classical_only_config(max_rounds=0)

        classical_registry = ClassicalSolverRegistry(include_builtins=False)
        classical_registry.register("recording", RecordingClassicalSolver)
        mis_registry = MISSolverRegistry(include_builtins=False)
        mis_registry.register("failing_mis", FailingMISSolver)

        result = run_pipeline(
            problem, adapter, config,
            classical_solver_registry=classical_registry,
            mis_solver_registry=mis_registry,
        )

        assert len(result.final_retained_item_ids) == 5
        assert set(result.final_retained_item_ids) == {f"item_{i}" for i in range(5)}

    def test_classical_only_variable_counts_match(self):
        """Original and residual variable counts should match for classical-only."""
        problem = SimpleProblem([
            SimpleItem("a", 1.0),
            SimpleItem("b", 2.0),
            SimpleItem("c", 3.0),
        ])
        adapter = SimpleAdapter()
        config = make_classical_only_config(max_rounds=0)

        classical_registry = ClassicalSolverRegistry(include_builtins=False)
        classical_registry.register("recording", RecordingClassicalSolver)
        mis_registry = MISSolverRegistry(include_builtins=False)
        mis_registry.register("failing_mis", FailingMISSolver)

        result = run_pipeline(
            problem, adapter, config,
            classical_solver_registry=classical_registry,
            mis_solver_registry=mis_registry,
        )

        assert result.original_variable_counts is not None
        assert result.residual_variable_counts is not None
        assert result.original_variable_counts == result.residual_variable_counts

    def test_classical_only_round_results_is_empty(self):
        """Classical-only baseline has no round results."""
        problem = SimpleProblem([SimpleItem("a", 1.0)])
        adapter = SimpleAdapter()
        config = make_classical_only_config(max_rounds=0)

        classical_registry = ClassicalSolverRegistry(include_builtins=False)
        classical_registry.register("recording", RecordingClassicalSolver)
        mis_registry = MISSolverRegistry(include_builtins=False)
        mis_registry.register("failing_mis", FailingMISSolver)

        result = run_pipeline(
            problem, adapter, config,
            classical_solver_registry=classical_registry,
            mis_solver_registry=mis_registry,
        )

        assert result.round_results == ()

    def test_classical_only_solver_receives_full_problem(self):
        """Classical solver receives the full problem (all items retained)."""
        problem = SimpleProblem([
            SimpleItem("a", 1.0),
            SimpleItem("b", 2.0),
            SimpleItem("c", 3.0),
        ])
        adapter = SimpleAdapter()
        config = make_classical_only_config(max_rounds=0)

        recording_solver = RecordingClassicalSolver()
        classical_registry = ClassicalSolverRegistry(include_builtins=False)
        classical_registry.register("recording", lambda: recording_solver)
        mis_registry = MISSolverRegistry(include_builtins=False)
        mis_registry.register("failing_mis", FailingMISSolver)

        run_pipeline(
            problem, adapter, config,
            classical_solver_registry=classical_registry,
            mis_solver_registry=mis_registry,
        )

        # Verify solver was called once with round_index=0
        assert len(recording_solver.calls) == 1
        assert recording_solver.calls[0]["round"] == 0
        
        # Verify the problem contains all items
        solved_problem = recording_solver.calls[0]["problem"]
        assert isinstance(solved_problem, SimpleResidualProblem)
        assert set(solved_problem.retained_ids) == {"a", "b", "c"}


class TestClassicalOnlyWithRealSolver:
    """Integration tests using real solver (SCIP)."""

    @pytest.fixture
    def scip_available(self):
        """Check if SCIP is available."""
        try:
            import pyscipopt  # noqa: F401
            return True
        except ImportError:
            return False

    def test_classical_only_with_scip(self, scip_available):
        """End-to-end test with real SCIP solver."""
        if not scip_available:
            pytest.skip("PySCIPOpt not available")

        from dataclasses import replace

        from qreduce.experiments.portfolio import build_synthetic_portfolio_inputs

        inputs = build_synthetic_portfolio_inputs("classical-only-integration")
        config = replace(
            inputs.config,
            reduction=replace(
                inputs.config.reduction,
                max_reduction_rounds=0,
                max_recovery_attempts=0,
                recovery_policy_on_domain_too_small="fail",
                recovery_policy_on_infeasible="fail",
            ),
        )

        result = run_pipeline(inputs.problem, inputs.adapter, config)

        assert result.run_result.run_status == RunStatus.SUCCESS
        assert result.is_classical_only is True
        assert result.reduction_round_count == 0
        assert result.cumulative_fixing_manifest.origin == "no_reduction"
        
        # All assets should be retained (synthetic portfolio has 5 assets)
        assert len(result.final_retained_item_ids) == 5
        assert len(result.cumulative_fixing_manifest.excluded_item_ids) == 0


class TestClassicalOnlyEdgeCases:
    """Edge cases for classical-only baseline."""

    def test_classical_only_with_classical_solver_failure(self):
        """Classical-only reports failure correctly when solver fails."""
        problem = SimpleProblem([SimpleItem("a", 1.0)])
        adapter = SimpleAdapter()
        config = make_classical_only_config(max_rounds=0)

        failing_solver = RecordingClassicalSolver(default_status=ClassicalSolverStatus.FAILED)
        classical_registry = ClassicalSolverRegistry(include_builtins=False)
        classical_registry.register("recording", lambda: failing_solver)
        mis_registry = MISSolverRegistry(include_builtins=False)
        mis_registry.register("failing_mis", FailingMISSolver)

        result = run_pipeline(
            problem, adapter, config,
            classical_solver_registry=classical_registry,
            mis_solver_registry=mis_registry,
        )

        assert result.run_result.run_status == RunStatus.FAILED
        assert result.is_classical_only is True

    def test_classical_only_with_infeasible_problem(self):
        """Classical-only correctly reports infeasible problems."""
        problem = SimpleProblem([SimpleItem("a", 1.0)])
        adapter = SimpleAdapter()
        config = make_classical_only_config(max_rounds=0)

        infeasible_solver = RecordingClassicalSolver(default_status=ClassicalSolverStatus.INFEASIBLE)
        classical_registry = ClassicalSolverRegistry(include_builtins=False)
        classical_registry.register("recording", lambda: infeasible_solver)
        mis_registry = MISSolverRegistry(include_builtins=False)
        mis_registry.register("failing_mis", FailingMISSolver)

        result = run_pipeline(
            problem, adapter, config,
            classical_solver_registry=classical_registry,
            mis_solver_registry=mis_registry,
        )

        assert result.run_result.run_status == RunStatus.FAILED
        # Still classical-only even if it fails
        assert result.is_classical_only is True
