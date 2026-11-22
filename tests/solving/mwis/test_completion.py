"""Tests for classical completion of MWIS candidates."""

import pytest

from qreduce.mwis import ReductionGraph
from qreduce.solving.mwis.completion import (
    CompletionPolicy,
    CompletionPolicyId,
    complete_candidate,
    compute_maximality_gap,
    default_completion_policy,
    greedy_weight_completion_policy,
)


def make_graph(node_weights: dict[str, float], edges: list[tuple[str, str]]) -> ReductionGraph:
    """Create a test graph."""
    node_ids = tuple(sorted(node_weights.keys()))
    canonical_edges = tuple(
        (min(a, b), max(a, b)) for a, b in edges
    )
    edge_reasons = {e: "conflict" for e in canonical_edges}
    return ReductionGraph(
        node_ids=node_ids,
        node_weights=node_weights,
        edges=canonical_edges,
        edge_reasons=edge_reasons,
        graph_policy_id="test",
        graph_policy_version="1.0",
    )


class TestCompletionPolicy:
    """Tests for completion policy configuration."""

    def test_default_policy_is_disabled(self):
        """Default completion policy should be disabled."""
        policy = default_completion_policy()
        assert policy.policy_id == CompletionPolicyId.DISABLED
        assert not policy.enabled

    def test_greedy_weight_policy(self):
        """Greedy weight policy should be enabled with proper settings."""
        policy = greedy_weight_completion_policy()
        assert policy.policy_id == CompletionPolicyId.GREEDY_BY_WEIGHT
        assert policy.enabled
        assert policy.tie_breaker == "node_id"


class TestCompletionDisabled:
    """Tests when completion is disabled."""

    def test_disabled_returns_original(self):
        """Disabled completion should return the original delta unchanged."""
        graph = make_graph({"a": 1.0, "b": 2.0, "c": 3.0}, [("a", "b")])
        delta = (0, 0, 1)  # Only c selected
        policy = default_completion_policy()

        result = complete_candidate(graph, delta, policy)

        assert result.completed_delta == delta
        assert result.original_delta == delta
        assert result.nodes_added == ()
        assert result.size_improvement == 0
        assert result.weight_improvement == 0.0


class TestGreedyCompletion:
    """Tests for greedy completion algorithms."""

    def test_complete_non_maximal_set(self):
        """Completion should add compatible nodes to non-maximal set."""
        # Graph: a--b, c is isolated
        graph = make_graph({"a": 1.0, "b": 2.0, "c": 3.0}, [("a", "b")])
        delta = (1, 0, 0)  # Only a selected (non-maximal: c can be added)
        policy = greedy_weight_completion_policy()

        result = complete_candidate(graph, delta, policy)

        assert result.completed_delta == (1, 0, 1)  # a and c selected
        assert "c" in result.nodes_added
        assert result.is_maximal
        assert not result.was_already_maximal
        assert result.completed_weight == 4.0  # a(1) + c(3)
        assert result.weight_improvement == 3.0

    def test_already_maximal_unchanged(self):
        """Already maximal set should not be modified."""
        # Graph: a--b
        graph = make_graph({"a": 1.0, "b": 2.0}, [("a", "b")])
        delta = (1, 0)  # Only a selected (maximal: b is neighbor)
        policy = greedy_weight_completion_policy()

        result = complete_candidate(graph, delta, policy)

        assert result.completed_delta == delta
        assert result.nodes_added == ()
        assert result.is_maximal
        assert result.was_already_maximal

    def test_greedy_prefers_higher_weight(self):
        """Greedy by weight should add higher weight nodes first."""
        # Graph: star with center a connected to b,c,d (all isolated from each other)
        # Actually let's use isolated nodes for clearer test
        graph = make_graph({"a": 1.0, "b": 10.0, "c": 5.0}, [])  # No edges
        delta = (0, 0, 0)  # Empty selection
        policy = CompletionPolicy(
            policy_id=CompletionPolicyId.GREEDY_BY_WEIGHT,
            enabled=True,
            max_additions=1  # Only add one
        )

        result = complete_candidate(graph, delta, policy)

        # Should add b (highest weight)
        assert result.completed_delta[1] == 1  # b added
        assert "b" in result.nodes_added
        assert result.completed_weight == 10.0

    def test_max_additions_limit(self):
        """Completion should respect max_additions limit."""
        graph = make_graph({"a": 1.0, "b": 2.0, "c": 3.0, "d": 4.0}, [])  # No edges
        delta = (0, 0, 0, 0)
        policy = CompletionPolicy(
            policy_id=CompletionPolicyId.GREEDY_BY_WEIGHT,
            enabled=True,
            max_additions=2
        )

        result = complete_candidate(graph, delta, policy)

        assert result.size_improvement == 2
        # Should add d(4) and c(3), the two highest
        assert "c" in result.nodes_added
        assert "d" in result.nodes_added


class TestCompletionWithConflicts:
    """Tests for completion respecting graph conflicts."""

    def test_completion_respects_edges(self):
        """Completion should not add nodes connected to selected nodes."""
        # Path graph: a--b--c--d
        graph = make_graph(
            {"a": 1.0, "b": 2.0, "c": 3.0, "d": 4.0},
            [("a", "b"), ("b", "c"), ("c", "d")]
        )
        delta = (0, 1, 0, 0)  # Only b selected
        policy = greedy_weight_completion_policy()

        result = complete_candidate(graph, delta, policy)

        # a and c are neighbors of b, cannot add them
        # d is not a neighbor, should be added
        assert result.completed_delta == (0, 1, 0, 1)
        assert "d" in result.nodes_added
        assert "a" not in result.nodes_added
        assert "c" not in result.nodes_added

    def test_completion_maintains_independence(self):
        """Completed set should always be independent."""
        graph = make_graph(
            {"a": 1.0, "b": 2.0, "c": 3.0, "d": 4.0, "e": 5.0},
            [("a", "b"), ("b", "c"), ("c", "d"), ("d", "e")]
        )
        delta = (0, 0, 0, 0, 0)  # Empty
        policy = greedy_weight_completion_policy()

        result = complete_candidate(graph, delta, policy)

        # Verify independence
        selected_indices = [i for i, v in enumerate(result.completed_delta) if v == 1]
        nodes = list(graph.node_ids)
        selected_nodes = [nodes[i] for i in selected_indices]

        for a, b in graph.edges:
            assert not (a in selected_nodes and b in selected_nodes), \
                f"Violation: both {a} and {b} selected"


class TestCompletionValidation:
    """Tests for input validation."""

    def test_invalid_delta_length_raises(self):
        """Delta length mismatch should raise ValueError."""
        graph = make_graph({"a": 1.0, "b": 2.0}, [])
        delta = (1, 0, 1)  # Wrong length
        policy = greedy_weight_completion_policy()

        with pytest.raises(ValueError, match="length"):
            complete_candidate(graph, delta, policy)

    def test_non_independent_input_raises(self):
        """Non-independent input should raise ValueError."""
        graph = make_graph({"a": 1.0, "b": 2.0}, [("a", "b")])
        delta = (1, 1)  # Both selected, but they're connected!
        policy = greedy_weight_completion_policy()

        with pytest.raises(ValueError, match="not an independent set"):
            complete_candidate(graph, delta, policy)


class TestMaximalityGap:
    """Tests for maximality gap computation."""

    def test_maximal_has_no_addable_nodes(self):
        """Maximal set should have no addable nodes."""
        graph = make_graph({"a": 1.0, "b": 2.0}, [("a", "b")])
        delta = (1, 0)  # a selected, b is neighbor

        gap = compute_maximality_gap(graph, delta)

        assert gap["is_maximal"]
        assert gap["addable_count"] == 0
        assert gap["addable_nodes"] == ()

    def test_non_maximal_identifies_addable(self):
        """Non-maximal set should identify addable nodes."""
        graph = make_graph({"a": 1.0, "b": 2.0, "c": 3.0}, [("a", "b")])
        delta = (1, 0, 0)  # Only a, but c could be added

        gap = compute_maximality_gap(graph, delta)

        assert not gap["is_maximal"]
        assert gap["addable_count"] == 1
        assert "c" in gap["addable_nodes"]
        assert gap["addable_weight"] == 3.0


class TestCompletionDeterminism:
    """Tests for completion determinism."""

    def test_same_input_same_output(self):
        """Same inputs should always produce same output."""
        graph = make_graph({"a": 1.0, "b": 1.0, "c": 1.0}, [])
        delta = (0, 0, 0)
        policy = greedy_weight_completion_policy()

        results = [complete_candidate(graph, delta, policy) for _ in range(5)]

        # All results should be identical
        first = results[0].completed_delta
        for r in results[1:]:
            assert r.completed_delta == first

    def test_tie_breaker_by_node_id(self):
        """Ties should be broken by node_id for determinism."""
        # All weights equal
        graph = make_graph({"x": 1.0, "y": 1.0, "z": 1.0}, [])
        delta = (0, 0, 0)
        policy = CompletionPolicy(
            policy_id=CompletionPolicyId.GREEDY_BY_WEIGHT,
            enabled=True,
            max_additions=1
        )

        result = complete_candidate(graph, delta, policy)

        # Should pick 'x' first (lexicographically smallest)
        assert "x" in result.nodes_added


class TestCompletionInPipeline:
    """Tests for completion integration in the pipeline."""

    def test_completion_policy_builds_from_config(self):
        """The pipeline should correctly build a completion policy from config."""
        from qreduce.models import (
            ClassicalSolveOptions,
            MISExecutionOptions,
            ReductionPolicy,
            ResolvedRunConfig,
            RunIdentity,
        )
        from qreduce.pipeline.single_pass import _build_completion_policy
        from qreduce.status import PostcheckMode

        # Create a minimal resolved config with completion enabled
        mis_options = MISExecutionOptions(
            requested_solution_count=10,
            random_seed=None,
            max_distinct_samples=10,
            repair_enabled=True,
            repair_max_iterations=5,
            minimum_candidate_jaccard_distance=0.0,
            exact_solver_max_variables=20,
            completion_enabled=True,
            completion_policy_id="greedy_by_weight",
        )

        reduction_policy = ReductionPolicy(
            max_reduction_rounds=1,
            max_end_to_end_runtime_seconds=0,
            candidate_domain_max_items=100,
            candidate_domain_min_items=1,
            num_source_mis_candidates=1,
            min_reduction_ratio=0.0,
            target_binary_variables=0,
        )

        classical_options = ClassicalSolveOptions(
            classical_solver_id="scip",
            time_limit_seconds=60.0,
            mip_gap_tolerance=None,
            threads=None,
            model_export_enabled=False,
            primal_feasibility_tolerance=1e-6,
            integrality_tolerance=1e-6,
            objective_recomputation_absolute_tolerance=1e-6,
            objective_recomputation_relative_tolerance=1e-6,
            postcheck_mode=PostcheckMode.STRICT,
        )

        config = ResolvedRunConfig(
            schema_version="1.0",
            run_identity=RunIdentity(run_id="test"),
            mis_solver_id="local_greedy",
            reduction=reduction_policy,
            mis_execution=mis_options,
            classical_solve=classical_options,
            lambda_edge=3.0,
            lambda_edge_policy=None,
            allow_noncertifying_penalty=False,
        )

        policy = _build_completion_policy(config)

        assert policy.enabled is True
        assert policy.policy_id == CompletionPolicyId.GREEDY_BY_WEIGHT

    def test_completion_disabled_by_default(self):
        """Default MISExecutionOptions should have completion disabled."""
        from qreduce.models import MISExecutionOptions

        options = MISExecutionOptions(
            requested_solution_count=10,
            random_seed=None,
            max_distinct_samples=10,
            repair_enabled=True,
            repair_max_iterations=5,
            minimum_candidate_jaccard_distance=0.0,
            exact_solver_max_variables=20,
        )

        assert options.completion_enabled is False
        assert options.completion_policy_id == "disabled"
