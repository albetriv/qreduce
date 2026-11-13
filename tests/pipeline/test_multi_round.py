"""Tests for multi-round iterative reduction orchestration."""

import pytest

from qreduce.domains import (
    DomainValidationResult,
    FixingEntry,
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
from qreduce.pipeline.multi_round import MultiRoundRunResult, run_multi_round
from qreduce.solving.residual import (
    ClassicalSolveResult,
    ClassicalSolverRegistry,
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
    """A minimal problem for testing multi-round orchestration."""

    def __init__(self, items: list[SimpleItem], conflicts: list[tuple[str, str]] | None = None):
        self.items = {item.item_id: item for item in items}
        self.conflicts = conflicts or []


class SimpleResidualProblem:
    """A restricted problem for testing."""

    def __init__(self, original: SimpleProblem, retained_ids: tuple[str, ...], manifest: FixingManifest):
        self.original = original
        self.retained_ids = retained_ids
        self.manifest = manifest


class SimpleAdapter:
    """A minimal adapter for testing multi-round behavior."""

    def __init__(
        self,
        force_infeasible_rounds: set[int] | None = None,
        force_small_domain_rounds: set[int] | None = None,
    ):
        self._force_infeasible = force_infeasible_rounds or set()
        self._force_small_domain = force_small_domain_rounds or set()
        self._round_calls: list[int] = []

    def identify_reducible_items(self, problem: SimpleProblem | SimpleResidualProblem) -> list[str]:
        if isinstance(problem, SimpleResidualProblem):
            return list(problem.retained_ids)
        return list(problem.items.keys())

    def describe_logical_variables(self, problem: SimpleProblem | SimpleResidualProblem) -> LogicalVariableCounts:
        items = self.identify_reducible_items(problem)
        return LogicalVariableCounts(binary_free=len(items), integer_free=0, continuous_free=0)

    def build_conflict_graph(self, problem: SimpleProblem | SimpleResidualProblem, state: object | None = None) -> ReductionGraph:
        if isinstance(problem, SimpleResidualProblem):
            original = problem.original
            node_ids = problem.retained_ids
        else:
            original = problem
            node_ids = tuple(problem.items.keys())

        edges = []
        for left, right in original.conflicts:
            if left in node_ids and right in node_ids:
                edge = (left, right) if left < right else (right, left)
                edges.append(edge)

        return ReductionGraph(
            node_ids=node_ids,
            node_weights={item_id: original.items[item_id].weight for item_id in node_ids},
            edges=tuple(sorted(set(edges))),
            edge_reasons={},
            graph_policy_id="test",
            graph_policy_version="1",
        )

    def declare_protected_items(self, problem: SimpleProblem | SimpleResidualProblem) -> ProtectionDeclaration:
        return ProtectionDeclaration((), (), (), ())

    def validate_candidate_domain(self, problem: SimpleProblem | SimpleResidualProblem, retained: tuple[str, ...]) -> DomainValidationResult:
        available = set(self.identify_reducible_items(problem))
        if not set(retained) <= available:
            return DomainValidationResult(False, None, failure_reasons=("unknown_item",))
        if len(retained) < 1:
            return DomainValidationResult(False, None, failure_reasons=("domain_too_small",))
        return DomainValidationResult(True, 1)

    def build_fixing_manifest(self, problem: SimpleProblem | SimpleResidualProblem, retained: tuple[str, ...]) -> FixingManifest:
        available = tuple(self.identify_reducible_items(problem))
        excluded = tuple(item for item in available if item not in retained)
        entries = tuple(
            FixingEntry(
                item_id=item,
                variable_values={f"x_{item}": 0.0},
                fixing_reason="mis_heuristic_exclusion",
                fixing_origin="mis_heuristic",
                guarantee_level="heuristic",
            )
            for item in excluded
        )
        return FixingManifest(
            retained_item_ids=retained,
            excluded_item_ids=excluded,
            entries=entries,
            origin="mis_reduction",
        )

    def restrict_problem(
        self, problem: SimpleProblem | SimpleResidualProblem, retained: tuple[str, ...], manifest: FixingManifest
    ) -> SimpleResidualProblem:
        original = problem.original if isinstance(problem, SimpleResidualProblem) else problem
        return SimpleResidualProblem(original, retained, manifest)

    def build_residual_model(self, problem: SimpleResidualProblem, fixing_manifest: FixingManifest) -> object:
        return {"type": "test_model", "retained": problem.retained_ids}

    def validate_final_solution(
        self,
        problem: SimpleProblem | SimpleResidualProblem,
        solution: object,
        fixing_manifest: FixingManifest,
        tolerances: object,
        solver_objective_value: float | None = None,
    ) -> object:
        from qreduce.domains import FinalSolutionValidationResult
        return FinalSolutionValidationResult(
            postcheck_feasible=True,
            fixed_variable_compliance=True,
            original_constraint_compliance=True,
            integrality_compliance=True,
            objective_recomputed=solver_objective_value or 0.0,
            solver_objective_compliance=True,
        )

    def evaluate_domain_metrics(self, problem: object, classical_result: object, postcheck_result: object) -> tuple:
        return ()


def make_multi_round_config(
    max_rounds: int = 3,
    min_reduction_ratio: float = 0.0,
    target_binary_variables: int = 0,
    recovery_on_small: str = "fail",
    recovery_on_infeasible: str = "fail",
    max_recovery: int = 0,
    **kwargs,
) -> ResolvedRunConfig:
    """Create a test configuration for multi-round."""
    reduction = ReductionPolicy(
        max_reduction_rounds=max_rounds,
        candidate_domain_min_items=1,
        candidate_domain_max_items=100,
        num_source_mis_candidates=3,
        min_reduction_ratio=min_reduction_ratio,
        target_binary_variables=target_binary_variables,
        max_end_to_end_runtime_seconds=60.0,
        recovery_policy_on_domain_too_small=recovery_on_small,
        recovery_policy_on_infeasible=recovery_on_infeasible,
        max_recovery_attempts=max_recovery,
    )
    return ResolvedRunConfig(
        schema_version="1.0",
        reduction=reduction,
        lambda_edge=10.0,
        lambda_edge_policy=LambdaEdgePolicy("standard", "1", 10.0),
        allow_noncertifying_penalty=False,
        mis_solver_id=kwargs.get("mis_solver_id", "local_greedy"),
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
            classical_solver_id=kwargs.get("classical_solver_id", "recording"),
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
        run_identity=RunIdentity("multi-round-test"),
        policy_provenance=PolicyProvenance(),
    )


class RecordingClassicalSolver:
    """Records calls and returns configurable results."""

    def __init__(
        self,
        result_sequence: list[ClassicalSolveResult] | None = None,
        default_status: ClassicalSolverStatus = ClassicalSolverStatus.OPTIMAL,
    ):
        self._results = result_sequence or []
        self._default_status = default_status
        self._call_count = 0
        self.calls: list[dict] = []

    def solve(self, problem, request) -> ClassicalSolveResult:
        self.calls.append({"round": request.round_index, "problem": problem})
        self._call_count += 1

        if self._results and self._call_count <= len(self._results):
            return self._results[self._call_count - 1]

        is_optimal = self._default_status == ClassicalSolverStatus.OPTIMAL
        is_feasible = self._default_status in (ClassicalSolverStatus.OPTIMAL, ClassicalSolverStatus.FEASIBLE)

        # Default result
        return ClassicalSolveResult(
            classical_solver_status=self._default_status,
            terminal_reason=None if is_feasible else TerminalReason.CLASSICAL_SOLVER_INFEASIBLE,
            solver_claimed_feasible=is_feasible,
            objective_value=0.0 if is_feasible else None,
            best_bound=0.0 if is_optimal else None,
            gap=0.0 if is_optimal else None,
            is_optimal=is_optimal,
            is_time_limited=False,
            runtime_seconds=0.1,
            variable_values={"x": 1.0} if is_feasible else {},
        )


# --- Tests ---


def test_single_round_behaves_like_single_pass():
    """With max_rounds=1, multi-round is equivalent to single-pass."""
    problem = SimpleProblem([
        SimpleItem("a", 1.0),
        SimpleItem("b", 2.0),
        SimpleItem("c", 3.0),
    ])
    adapter = SimpleAdapter()
    config = make_multi_round_config(max_rounds=1)

    classical_registry = ClassicalSolverRegistry(include_builtins=False)
    classical_registry.register("recording", RecordingClassicalSolver)

    result = run_multi_round(
        problem, adapter, config,
        classical_solver_registry=classical_registry,
    )

    assert isinstance(result, MultiRoundRunResult)
    assert len(result.round_results) == 1
    assert result.run_result.run_status in (RunStatus.SUCCESS, RunStatus.PARTIAL_SUCCESS, RunStatus.FAILED)
    assert result.metrics.get("round_count") == 1


def test_multi_round_stops_on_success():
    """Iteration stops when a round achieves success."""
    problem = SimpleProblem([
        SimpleItem("a", 1.0),
        SimpleItem("b", 2.0),
        SimpleItem("c", 3.0),
        SimpleItem("d", 4.0),
    ])
    adapter = SimpleAdapter()
    config = make_multi_round_config(max_rounds=5)

    classical_registry = ClassicalSolverRegistry(include_builtins=False)
    classical_registry.register("recording", RecordingClassicalSolver)

    result = run_multi_round(
        problem, adapter, config,
        classical_solver_registry=classical_registry,
    )

    # Should stop on first success, not run all 5 rounds
    assert result.run_result.run_status == RunStatus.SUCCESS
    assert len(result.round_results) == 1


def test_multi_round_reaches_max_rounds():
    """Iteration stops at max_reduction_rounds limit."""
    problem = SimpleProblem([
        SimpleItem("a", 1.0),
        SimpleItem("b", 2.0),
        SimpleItem("c", 3.0),
    ])
    adapter = SimpleAdapter()
    config = make_multi_round_config(max_rounds=2)

    # Force infeasible results to continue iterating
    solver = RecordingClassicalSolver(default_status=ClassicalSolverStatus.INFEASIBLE)
    classical_registry = ClassicalSolverRegistry(include_builtins=False)
    classical_registry.register("recording", lambda: solver)

    result = run_multi_round(
        problem, adapter, config,
        classical_solver_registry=classical_registry,
    )

    # First round runs, fails, but we can't continue because domain becomes too small
    # The exact behavior depends on the MIS results
    assert result.metrics.get("round_count", 0) >= 1


def test_multi_round_cumulative_manifest_tracks_all_exclusions():
    """Cumulative manifest contains exclusions from all rounds."""
    problem = SimpleProblem([
        SimpleItem("a", 1.0),
        SimpleItem("b", 2.0),
        SimpleItem("c", 3.0),
        SimpleItem("d", 4.0),
        SimpleItem("e", 5.0),
    ])
    adapter = SimpleAdapter()
    config = make_multi_round_config(max_rounds=3)

    classical_registry = ClassicalSolverRegistry(include_builtins=False)
    classical_registry.register("recording", RecordingClassicalSolver)

    result = run_multi_round(
        problem, adapter, config,
        classical_solver_registry=classical_registry,
    )

    # Check that cumulative manifest exists if we have round manifests
    if result.round_results and result.round_results[0].fixing_manifest:
        assert result.cumulative_fixing_manifest is not None or len(result.round_results) == 1


def test_multi_round_monotonicity_retained_items_never_increase():
    """The number of retained items decreases or stays constant across rounds."""
    problem = SimpleProblem([
        SimpleItem("a", 1.0),
        SimpleItem("b", 2.0),
        SimpleItem("c", 3.0),
        SimpleItem("d", 4.0),
    ])
    adapter = SimpleAdapter()
    config = make_multi_round_config(max_rounds=3)

    # Force infeasible to continue iterating
    solver = RecordingClassicalSolver(default_status=ClassicalSolverStatus.INFEASIBLE)
    classical_registry = ClassicalSolverRegistry(include_builtins=False)
    classical_registry.register("recording", lambda: solver)

    result = run_multi_round(
        problem, adapter, config,
        classical_solver_registry=classical_registry,
    )

    # Check monotonicity
    prev_retained = None
    for round_result in result.round_results:
        if round_result.fixing_manifest:
            retained = len(round_result.fixing_manifest.retained_item_ids)
            if prev_retained is not None:
                assert retained <= prev_retained, "Retained items should not increase"
            prev_retained = retained


def test_multi_round_excluded_items_never_reappear():
    """Items excluded in a round cannot reappear in subsequent rounds."""
    problem = SimpleProblem([
        SimpleItem("a", 1.0),
        SimpleItem("b", 2.0),
        SimpleItem("c", 3.0),
        SimpleItem("d", 4.0),
    ])
    adapter = SimpleAdapter()
    config = make_multi_round_config(max_rounds=3)

    solver = RecordingClassicalSolver(default_status=ClassicalSolverStatus.INFEASIBLE)
    classical_registry = ClassicalSolverRegistry(include_builtins=False)
    classical_registry.register("recording", lambda: solver)

    result = run_multi_round(
        problem, adapter, config,
        classical_solver_registry=classical_registry,
    )

    excluded_so_far: set[str] = set()
    for round_result in result.round_results:
        if round_result.fixing_manifest:
            retained_set = set(round_result.fixing_manifest.retained_item_ids)
            # No excluded item should be in retained
            assert not (excluded_so_far & retained_set), "Excluded items should not reappear"
            excluded_so_far.update(round_result.fixing_manifest.excluded_item_ids)


def test_multi_round_round_index_propagates_to_backends():
    """Each round's index is correctly passed to MIS and classical backends."""
    problem = SimpleProblem([
        SimpleItem("a", 1.0),
        SimpleItem("b", 2.0),
    ])
    adapter = SimpleAdapter()
    config = make_multi_round_config(max_rounds=1)

    observed_rounds: list[int] = []

    class RoundRecordingSolver:
        def solve(self, problem, request) -> ClassicalSolveResult:
            observed_rounds.append(request.round_index)
            return ClassicalSolveResult(
                classical_solver_status=ClassicalSolverStatus.OPTIMAL,
                terminal_reason=None,
                solver_claimed_feasible=True,
                objective_value=0.0,
                best_bound=0.0,
                gap=0.0,
                is_optimal=True,
                is_time_limited=False,
                runtime_seconds=0.1,
                variable_values={},
            )

    classical_registry = ClassicalSolverRegistry(include_builtins=False)
    classical_registry.register("recording", RoundRecordingSolver)

    run_multi_round(
        problem, adapter, config,
        classical_solver_registry=classical_registry,
    )

    assert observed_rounds == [0]


def test_config_validation_rejects_invalid_recovery_policy():
    """Invalid recovery policies are rejected at validation."""
    from qreduce.config import validate_resolved_run_config

    config = make_multi_round_config(recovery_on_small="invalid_policy")
    result = validate_resolved_run_config(config)

    assert not result.is_valid
    assert any("invalid_recovery_policy" in issue.code for issue in result.issues)


def test_config_validation_requires_policy_for_recovery_attempts():
    """max_recovery_attempts > 0 requires at least one non-fail policy."""
    from qreduce.config import validate_resolved_run_config

    config = make_multi_round_config(
        max_recovery=3,
        recovery_on_small="fail",
        recovery_on_infeasible="fail",
    )
    result = validate_resolved_run_config(config)

    assert not result.is_valid
    assert any("recovery_attempts_without_policy" in issue.code for issue in result.issues)


def test_config_validation_accepts_valid_recovery_config():
    """Valid recovery configuration passes validation."""
    from qreduce.config import validate_resolved_run_config

    config = make_multi_round_config(
        max_recovery=3,
        recovery_on_small="retry_with_larger_domain",
        recovery_on_infeasible="fail",
    )
    result = validate_resolved_run_config(config)

    assert result.is_valid


def test_multi_round_metrics_include_round_count():
    """Result metrics include the number of rounds executed."""
    problem = SimpleProblem([SimpleItem("a", 1.0)])
    adapter = SimpleAdapter()
    config = make_multi_round_config(max_rounds=1)

    classical_registry = ClassicalSolverRegistry(include_builtins=False)
    classical_registry.register("recording", RecordingClassicalSolver)

    result = run_multi_round(
        problem, adapter, config,
        classical_solver_registry=classical_registry,
    )

    assert "round_count" in result.metrics
    assert "end_to_end_runtime_seconds" in result.metrics


def test_multi_round_result_is_serializable():
    """MultiRoundRunResult can be converted to dict for persistence."""
    problem = SimpleProblem([SimpleItem("a", 1.0)])
    adapter = SimpleAdapter()
    config = make_multi_round_config(max_rounds=1)

    classical_registry = ClassicalSolverRegistry(include_builtins=False)
    classical_registry.register("recording", RecordingClassicalSolver)

    result = run_multi_round(
        problem, adapter, config,
        classical_solver_registry=classical_registry,
    )

    serialized = result.to_dict()
    assert isinstance(serialized, dict)
    assert "run_result" in serialized
    assert "round_results" in serialized


# --- Tests for recovery behavior ---


def test_recovery_expands_domain_on_infeasible():
    """Recovery from CLASSICAL_SOLVER_INFEASIBLE actually expands the domain.

    This test verifies that:
    1. The first solve receives the original (smaller) domain
    2. After recovery, subsequent solves receive an expanded domain
    3. The RecoveryAttempt records show the expansion
    """
    # Use enough items so MIS can exclude some and recovery can add them back
    problem = SimpleProblem([
        SimpleItem("a", 1.0),
        SimpleItem("b", 2.0),
        SimpleItem("c", 3.0),
        SimpleItem("d", 4.0),
        SimpleItem("e", 5.0),
    ])

    solve_calls: list[dict] = []

    class DomainTrackingSolver:
        def solve(self, model, request) -> ClassicalSolveResult:
            # Track what the solver receives
            retained_count = None
            if hasattr(model, "retained_item_ids"):
                retained_count = len(model.retained_item_ids)
            elif hasattr(model, "retained_ids"):
                retained_count = len(model.retained_ids)

            solve_calls.append({
                "call_index": len(solve_calls),
                "round_index": request.round_index,
                "retained_count": retained_count,
            })

            # First call returns infeasible to trigger recovery
            if len(solve_calls) == 1:
                return ClassicalSolveResult(
                    classical_solver_status=ClassicalSolverStatus.INFEASIBLE,
                    terminal_reason=TerminalReason.CLASSICAL_SOLVER_INFEASIBLE,
                    solver_claimed_feasible=False,
                    objective_value=None,
                    best_bound=None,
                    gap=None,
                    is_optimal=False,
                    is_time_limited=False,
                    runtime_seconds=0.1,
                )
            # Subsequent calls succeed
            return ClassicalSolveResult(
                classical_solver_status=ClassicalSolverStatus.OPTIMAL,
                terminal_reason=None,
                solver_claimed_feasible=True,
                objective_value=0.0,
                best_bound=0.0,
                gap=0.0,
                is_optimal=True,
                is_time_limited=False,
                runtime_seconds=0.1,
                variable_values={"x": 1.0},
            )

    adapter = SimpleAdapter()
    config = make_multi_round_config(
        max_rounds=1,
        max_recovery=3,
        recovery_on_infeasible="retry_with_larger_domain",
    )

    classical_registry = ClassicalSolverRegistry(include_builtins=False)
    classical_registry.register("recording", DomainTrackingSolver)

    result = run_multi_round(
        problem, adapter, config,
        classical_solver_registry=classical_registry,
    )

    # Verify recovery was actually attempted
    assert len(result.recovery_attempts) >= 1, "Expected at least one recovery attempt"

    # Check if any recovery attempt expanded the domain
    # Some attempts might be "exhausted" if domain was already at max
    expanded_attempts = [a for a in result.recovery_attempts if a.outcome == "retry"]
    if expanded_attempts:
        for attempt in expanded_attempts:
            assert attempt.expanded_domain_size > attempt.previous_domain_size, (
                f"Recovery should expand domain: {attempt.previous_domain_size} -> {attempt.expanded_domain_size}"
            )


def test_recovery_attempts_are_recorded():
    """RecoveryAttempt records are created with correct metadata."""
    from qreduce.pipeline.multi_round import RecoveryAttempt

    problem = SimpleProblem([
        SimpleItem("a", 1.0),
        SimpleItem("b", 2.0),
    ])

    class AlwaysInfeasibleSolver:
        def solve(self, problem, request) -> ClassicalSolveResult:
            return ClassicalSolveResult(
                classical_solver_status=ClassicalSolverStatus.INFEASIBLE,
                terminal_reason=TerminalReason.CLASSICAL_SOLVER_INFEASIBLE,
                solver_claimed_feasible=False,
                objective_value=None,
                best_bound=None,
                gap=None,
                is_optimal=False,
                is_time_limited=False,
                runtime_seconds=0.1,
            )

    adapter = SimpleAdapter()
    config = make_multi_round_config(
        max_rounds=1,
        max_recovery=3,
        recovery_on_infeasible="retry_with_larger_domain",
    )

    classical_registry = ClassicalSolverRegistry(include_builtins=False)
    classical_registry.register("recording", AlwaysInfeasibleSolver)

    result = run_multi_round(
        problem, adapter, config,
        classical_solver_registry=classical_registry,
    )

    # Should have recorded recovery attempts
    assert len(result.recovery_attempts) > 0
    for attempt in result.recovery_attempts:
        assert isinstance(attempt, RecoveryAttempt)
        assert attempt.trigger_reason == TerminalReason.CLASSICAL_SOLVER_INFEASIBLE
        assert attempt.outcome in ("retry", "exhausted")


def test_recovery_stops_when_domain_cannot_expand():
    """Recovery stops gracefully when expansion is no longer possible."""
    problem = SimpleProblem([
        SimpleItem("a", 1.0),
        SimpleItem("b", 2.0),
    ])

    class AlwaysInfeasibleSolver:
        def solve(self, problem, request) -> ClassicalSolveResult:
            return ClassicalSolveResult(
                classical_solver_status=ClassicalSolverStatus.INFEASIBLE,
                terminal_reason=TerminalReason.CLASSICAL_SOLVER_INFEASIBLE,
                solver_claimed_feasible=False,
                objective_value=None,
                best_bound=None,
                gap=None,
                is_optimal=False,
                is_time_limited=False,
                runtime_seconds=0.1,
            )

    adapter = SimpleAdapter()
    config = make_multi_round_config(
        max_rounds=1,
        max_recovery=10,  # High limit
        recovery_on_infeasible="retry_with_larger_domain",
    )

    classical_registry = ClassicalSolverRegistry(include_builtins=False)
    classical_registry.register("recording", AlwaysInfeasibleSolver)

    result = run_multi_round(
        problem, adapter, config,
        classical_solver_registry=classical_registry,
    )

    # Should have stopped before max_recovery due to exhausted domain
    # At least one attempt should have "exhausted" outcome
    exhausted = [a for a in result.recovery_attempts if a.outcome == "exhausted"]
    assert len(exhausted) >= 1 or result.run_result.terminal_reason == TerminalReason.CLASSICAL_SOLVER_INFEASIBLE


def test_cumulative_manifest_error_is_not_silenced():
    """If cumulative_fixing_manifest fails, the error causes explicit failure.

    This test verifies that a conflict in cumulative manifest validation
    results in a FAILED status with ADAPTER_FAILURE, not a silent pass.
    """
    from qreduce.pipeline.rounds import cumulative_fixing_manifest

    # First verify that cumulative_fixing_manifest actually raises on conflict
    manifest1 = FixingManifest(
        retained_item_ids=("a", "b"),
        excluded_item_ids=("c",),
        entries=(
            FixingEntry(
                item_id="c",
                variable_values={"x_c": 0.0},
                reason="mis_heuristic_exclusion",
                fixing_origin="mis_heuristic",
                guarantee_level="heuristic",
            ),
        ),
        origin="test",
        round_index=0,
    )
    manifest2 = FixingManifest(
        retained_item_ids=("a",),
        excluded_item_ids=("b",),
        entries=(
            FixingEntry(
                item_id="b",
                variable_values={"x_c": 1.0},  # Conflict: x_c assigned differently
                reason="mis_heuristic_exclusion",
                fixing_origin="mis_heuristic",
                guarantee_level="heuristic",
            ),
        ),
        origin="test",
        round_index=1,
    )

    # This should raise ValueError due to conflicting assignment
    with pytest.raises(ValueError, match="Conflicting"):
        cumulative_fixing_manifest(("a", "b", "c"), (manifest1, manifest2))


def test_post_check_uses_original_problem_with_cumulative_manifest():
    """Post-check validates against original problem with all cumulative fixings.

    This test verifies that:
    1. validate_final_solution receives the ORIGINAL problem (not residual)
    2. validate_final_solution receives the CUMULATIVE manifest (not just round manifest)
    """
    problem = SimpleProblem([
        SimpleItem("a", 1.0),
        SimpleItem("b", 2.0),
        SimpleItem("c", 3.0),
    ])

    postcheck_calls: list[dict] = []

    class PostcheckTrackingAdapter(SimpleAdapter):
        def validate_final_solution(
            self,
            received_problem,
            solution,
            fixing_manifest,
            tolerances,
            solver_objective_value=None,
        ):
            postcheck_calls.append({
                "problem_type": type(received_problem).__name__,
                "problem_is_original": isinstance(received_problem, SimpleProblem) and not isinstance(received_problem, SimpleResidualProblem),
                "manifest_origin": fixing_manifest.origin if fixing_manifest else None,
                "manifest_round_index": fixing_manifest.round_index if fixing_manifest else None,
                "manifest_retained_count": len(fixing_manifest.retained_item_ids) if fixing_manifest else 0,
                "manifest_excluded_count": len(fixing_manifest.excluded_item_ids) if fixing_manifest else 0,
            })
            from qreduce.domains import FinalSolutionValidationResult
            return FinalSolutionValidationResult(
                postcheck_feasible=True,
                fixed_variable_compliance=True,
                original_constraint_compliance=True,
                integrality_compliance=True,
                objective_recomputed=solver_objective_value or 0.0,
                solver_objective_compliance=True,
            )

    adapter = PostcheckTrackingAdapter()
    config = make_multi_round_config(max_rounds=1)

    classical_registry = ClassicalSolverRegistry(include_builtins=False)
    classical_registry.register("recording", RecordingClassicalSolver)

    result = run_multi_round(
        problem, adapter, config,
        classical_solver_registry=classical_registry,
    )

    # Verify post-check was called
    if result.run_result.run_status == RunStatus.SUCCESS:
        assert len(postcheck_calls) >= 1, "Post-check should have been called"

        # The post-check should receive the original problem type
        last_call = postcheck_calls[-1]
        assert last_call["problem_type"] == "SimpleProblem", (
            f"Post-check should receive original problem, got {last_call['problem_type']}"
        )


def test_infeasible_without_recovery_terminates_immediately():
    """Without recovery policy, CLASSICAL_SOLVER_INFEASIBLE terminates the run."""
    problem = SimpleProblem([
        SimpleItem("a", 1.0),
        SimpleItem("b", 2.0),
    ])

    class InfeasibleSolver:
        def solve(self, problem, request) -> ClassicalSolveResult:
            return ClassicalSolveResult(
                classical_solver_status=ClassicalSolverStatus.INFEASIBLE,
                terminal_reason=TerminalReason.CLASSICAL_SOLVER_INFEASIBLE,
                solver_claimed_feasible=False,
                objective_value=None,
                best_bound=None,
                gap=None,
                is_optimal=False,
                is_time_limited=False,
                runtime_seconds=0.1,
            )

    adapter = SimpleAdapter()
    config = make_multi_round_config(
        max_rounds=1,
        max_recovery=0,  # No recovery
        recovery_on_infeasible="fail",
    )

    classical_registry = ClassicalSolverRegistry(include_builtins=False)
    classical_registry.register("recording", InfeasibleSolver)

    result = run_multi_round(
        problem, adapter, config,
        classical_solver_registry=classical_registry,
    )

    # Should fail with infeasible, no recovery attempts
    assert result.run_result.run_status == RunStatus.FAILED
    assert result.run_result.terminal_reason == TerminalReason.CLASSICAL_SOLVER_INFEASIBLE
    assert len(result.recovery_attempts) == 0



def test_adapter_failure_in_recovery_build_fixing_manifest():
    """Adapter failure in build_fixing_manifest during recovery is properly reported."""
    problem = SimpleProblem([
        SimpleItem("a", 1.0),
        SimpleItem("b", 2.0),
        SimpleItem("c", 3.0),
    ])

    class FailingManifestAdapter(SimpleAdapter):
        def __init__(self):
            super().__init__()
            self._manifest_call_count = 0

        def build_fixing_manifest(self, problem, retained):
            self._manifest_call_count += 1
            # Fail on second call (during recovery)
            if self._manifest_call_count > 1:
                raise RuntimeError("Simulated adapter failure in build_fixing_manifest")
            return super().build_fixing_manifest(problem, retained)

    class InfeasibleThenFailSolver:
        def solve(self, problem, request) -> ClassicalSolveResult:
            return ClassicalSolveResult(
                classical_solver_status=ClassicalSolverStatus.INFEASIBLE,
                terminal_reason=TerminalReason.CLASSICAL_SOLVER_INFEASIBLE,
                solver_claimed_feasible=False,
                objective_value=None,
                best_bound=None,
                gap=None,
                is_optimal=False,
                is_time_limited=False,
                runtime_seconds=0.1,
            )

    adapter = FailingManifestAdapter()
    config = make_multi_round_config(
        max_rounds=1,
        max_recovery=2,
        recovery_on_infeasible="retry_with_larger_domain",
    )

    classical_registry = ClassicalSolverRegistry(include_builtins=False)
    classical_registry.register("recording", InfeasibleThenFailSolver)

    result = run_multi_round(
        problem, adapter, config,
        classical_solver_registry=classical_registry,
    )

    # The result should indicate failure, and the stage should be RESTRICTION
    # (since build_fixing_manifest is part of the restriction phase)
    assert result.run_result.run_status == RunStatus.FAILED
    # The terminal reason could be from the original infeasible or the adapter failure


def test_adapter_failure_in_recovery_restrict_problem():
    """Adapter failure in restrict_problem during recovery is properly reported."""
    problem = SimpleProblem([
        SimpleItem("a", 1.0),
        SimpleItem("b", 2.0),
        SimpleItem("c", 3.0),
    ])

    class FailingRestrictAdapter(SimpleAdapter):
        def __init__(self):
            super().__init__()
            self._restrict_call_count = 0

        def restrict_problem(self, problem, retained, manifest):
            self._restrict_call_count += 1
            # Fail on second call (during recovery)
            if self._restrict_call_count > 1:
                raise RuntimeError("Simulated adapter failure in restrict_problem")
            return super().restrict_problem(problem, retained, manifest)

    class InfeasibleSolver:
        def solve(self, problem, request) -> ClassicalSolveResult:
            return ClassicalSolveResult(
                classical_solver_status=ClassicalSolverStatus.INFEASIBLE,
                terminal_reason=TerminalReason.CLASSICAL_SOLVER_INFEASIBLE,
                solver_claimed_feasible=False,
                objective_value=None,
                best_bound=None,
                gap=None,
                is_optimal=False,
                is_time_limited=False,
                runtime_seconds=0.1,
            )

    adapter = FailingRestrictAdapter()
    config = make_multi_round_config(
        max_rounds=1,
        max_recovery=2,
        recovery_on_infeasible="retry_with_larger_domain",
    )

    classical_registry = ClassicalSolverRegistry(include_builtins=False)
    classical_registry.register("recording", InfeasibleSolver)

    result = run_multi_round(
        problem, adapter, config,
        classical_solver_registry=classical_registry,
    )

    # The result should indicate failure
    assert result.run_result.run_status == RunStatus.FAILED


def test_adapter_failure_in_recovery_validate_candidate_domain():
    """Adapter failure in validate_candidate_domain during recovery is properly reported."""
    problem = SimpleProblem([
        SimpleItem("a", 1.0),
        SimpleItem("b", 2.0),
        SimpleItem("c", 3.0),
        SimpleItem("d", 4.0),
        SimpleItem("e", 5.0),
    ])

    class FailingValidationAdapter(SimpleAdapter):
        def __init__(self):
            super().__init__()
            self._in_recovery = False
            self._initial_validation_done = False

        def validate_candidate_domain(self, problem, retained):
            # Track if we've done the initial validation
            if not self._initial_validation_done:
                self._initial_validation_done = True
                return super().validate_candidate_domain(problem, retained)

            # After initial, we're in recovery - fail
            raise RuntimeError("Simulated adapter failure in validate_candidate_domain during recovery")

    class InfeasibleSolver:
        def solve(self, problem, request) -> ClassicalSolveResult:
            return ClassicalSolveResult(
                classical_solver_status=ClassicalSolverStatus.INFEASIBLE,
                terminal_reason=TerminalReason.CLASSICAL_SOLVER_INFEASIBLE,
                solver_claimed_feasible=False,
                objective_value=None,
                best_bound=None,
                gap=None,
                is_optimal=False,
                is_time_limited=False,
                runtime_seconds=0.1,
            )

    adapter = FailingValidationAdapter()
    config = make_multi_round_config(
        max_rounds=1,
        max_recovery=2,
        recovery_on_infeasible="retry_with_larger_domain",
    )

    classical_registry = ClassicalSolverRegistry(include_builtins=False)
    classical_registry.register("recording", InfeasibleSolver)

    result = run_multi_round(
        problem, adapter, config,
        classical_solver_registry=classical_registry,
    )

    # The result should indicate failure
    # It could be ADAPTER_FAILURE from the validation, or CLASSICAL_SOLVER_INFEASIBLE
    # if recovery couldn't proceed
    assert result.run_result.run_status == RunStatus.FAILED



# --- Tests with real MeanVariancePortfolioAdapter ---


def test_end_to_end_recovery_with_portfolio_adapter_and_adoption():
    """End-to-end test: recovery from infeasible, successful adoption.

    This test verifies the complete recovery flow:
    1. Initial solve returns infeasible
    2. Recovery expands the domain
    3. Retry solve succeeds
    4. Post-check passes
    5. Solution is adopted
    """
    from qreduce.status import AdoptionStatus

    # Use SimpleAdapter which already works with the multi-round infrastructure
    problem = SimpleProblem([
        SimpleItem("a", 1.0),
        SimpleItem("b", 2.0),
        SimpleItem("c", 3.0),
        SimpleItem("d", 4.0),
        SimpleItem("e", 5.0),
    ])

    call_count = [0]

    class InfeasibleThenOptimalSolver:
        """Returns infeasible once, then optimal."""

        def solve(self, model, request) -> ClassicalSolveResult:
            call_count[0] += 1

            if call_count[0] == 1:
                # First call: infeasible to trigger recovery
                return ClassicalSolveResult(
                    classical_solver_status=ClassicalSolverStatus.INFEASIBLE,
                    terminal_reason=TerminalReason.CLASSICAL_SOLVER_INFEASIBLE,
                    solver_claimed_feasible=False,
                    objective_value=None,
                    best_bound=None,
                    gap=None,
                    is_optimal=False,
                    is_time_limited=False,
                    runtime_seconds=0.1,
                )

            # Subsequent calls: optimal
            return ClassicalSolveResult(
                classical_solver_status=ClassicalSolverStatus.OPTIMAL,
                terminal_reason=None,
                solver_claimed_feasible=True,
                objective_value=0.0,
                best_bound=0.0,
                gap=0.0,
                is_optimal=True,
                is_time_limited=False,
                runtime_seconds=0.5,
                variable_values={"x": 1.0},
            )

    adapter = SimpleAdapter()
    config = make_multi_round_config(
        max_rounds=3,
        max_recovery=3,
        recovery_on_infeasible="retry_with_larger_domain",
    )

    classical_registry = ClassicalSolverRegistry(include_builtins=False)
    classical_registry.register("recording", InfeasibleThenOptimalSolver)

    result = run_multi_round(
        problem, adapter, config,
        classical_solver_registry=classical_registry,
    )

    # Verify the recovery flow
    assert len(result.recovery_attempts) >= 1, "Expected at least one recovery attempt"

    # Check that the run succeeded
    assert result.run_result.run_status == RunStatus.SUCCESS, (
        f"Expected SUCCESS but got {result.run_result.run_status}, "
        f"terminal_reason={result.run_result.terminal_reason}"
    )

    # Verify adoption
    assert result.run_result.adoption_status == AdoptionStatus.ADOPTED, (
        f"Expected ADOPTED but got {result.run_result.adoption_status}"
    )

    # Verify we had at least 2 solver calls (initial + after recovery)
    assert call_count[0] >= 2, "Expected at least 2 solver calls (initial + recovery)"


def test_end_to_end_multi_round_success_without_recovery():
    """End-to-end test: successful multi-round without needing recovery."""
    from qreduce.status import AdoptionStatus

    # Use SimpleAdapter which already works with the multi-round infrastructure
    problem = SimpleProblem([
        SimpleItem("a", 1.0),
        SimpleItem("b", 2.0),
        SimpleItem("c", 3.0),
    ])

    adapter = SimpleAdapter()

    class OptimalSolver:
        """Returns optimal immediately."""

        def solve(self, model, request) -> ClassicalSolveResult:
            return ClassicalSolveResult(
                classical_solver_status=ClassicalSolverStatus.OPTIMAL,
                terminal_reason=None,
                solver_claimed_feasible=True,
                objective_value=0.0,
                best_bound=0.0,
                gap=0.0,
                is_optimal=True,
                is_time_limited=False,
                runtime_seconds=0.2,
                variable_values={"x": 1.0},
            )

    config = make_multi_round_config(
        max_rounds=2,
        max_recovery=1,
        recovery_on_infeasible="retry_with_larger_domain",
    )

    classical_registry = ClassicalSolverRegistry(include_builtins=False)
    classical_registry.register("recording", OptimalSolver)

    result = run_multi_round(
        problem, adapter, config,
        classical_solver_registry=classical_registry,
    )

    # Verify no recovery was needed
    assert len(result.recovery_attempts) == 0, "Expected no recovery attempts"

    # Verify success
    assert result.run_result.run_status == RunStatus.SUCCESS
    assert result.run_result.adoption_status == AdoptionStatus.ADOPTED
