"""Tests for exact presolve of trivially solvable MWIS graphs."""

import pytest

from qreduce.mwis import (
    ReductionGraph,
)
from qreduce.solving.mwis.presolve import (
    PresolveReason,
    PresolveStatus,
    presolve_to_raw_sample,
    try_presolve,
)


def make_edgeless_graph(node_weights: dict[str, float]) -> ReductionGraph:
    """Create an edgeless graph with the given node weights."""
    node_ids = tuple(sorted(node_weights.keys()))
    return ReductionGraph(
        node_ids=node_ids,
        node_weights=node_weights,
        edges=(),
        edge_reasons={},
        graph_policy_id="test",
        graph_policy_version="1.0",
    )


def make_graph_with_edges(node_weights: dict[str, float], edges: list[tuple[str, str]]) -> ReductionGraph:
    """Create a graph with edges."""
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


class TestPresolveEdgelessGraphs:
    """Tests for edgeless graph presolve."""

    def test_edgeless_positive_weights_selects_all(self):
        """Edgeless graph with positive weights should select all nodes."""
        graph = make_edgeless_graph({"a": 1.0, "b": 2.0, "c": 3.0})
        result = try_presolve(graph, requested_backend_id="pasqal_local")

        assert result.status == PresolveStatus.APPLIED
        assert result.reason == PresolveReason.EDGELESS_POSITIVE_WEIGHTS
        assert result.delta == (1, 1, 1)  # All selected
        assert result.node_order == ("a", "b", "c")
        assert result.selection_weight == 6.0
        assert result.num_selected == 3
        assert result.is_certified_optimal
        assert result.backend_bypassed
        assert result.requested_backend_id == "pasqal_local"

    def test_edgeless_nonnegative_weights_includes_zero(self):
        """Edgeless graph with zero weights should include them by default."""
        graph = make_edgeless_graph({"a": 1.0, "b": 0.0, "c": 2.0})
        result = try_presolve(graph, include_zero_weight_nodes=True)

        assert result.status == PresolveStatus.APPLIED
        assert result.reason == PresolveReason.EDGELESS_NONNEGATIVE_WEIGHTS
        assert result.delta == (1, 1, 1)  # All selected including zero-weight
        assert result.selection_weight == 3.0
        assert result.num_selected == 3

    def test_edgeless_excludes_zero_weight_when_configured(self):
        """Zero-weight nodes can be excluded by configuration."""
        graph = make_edgeless_graph({"a": 1.0, "b": 0.0, "c": 2.0})
        result = try_presolve(graph, include_zero_weight_nodes=False)

        assert result.status == PresolveStatus.APPLIED
        # Still optimal (zero weight doesn't change objective)
        assert result.delta == (1, 0, 1)  # Zero-weight excluded
        assert result.selection_weight == 3.0
        assert result.num_selected == 2

    def test_empty_graph(self):
        """Empty graph should presolve to empty selection."""
        graph = make_edgeless_graph({})
        result = try_presolve(graph)

        assert result.status == PresolveStatus.APPLIED
        assert result.reason == PresolveReason.EMPTY_GRAPH
        assert result.delta == ()
        assert result.node_order == ()
        assert result.selection_weight == 0.0
        assert result.num_selected == 0
        assert result.is_certified_optimal

    def test_single_node(self):
        """Single node graph should select the node."""
        graph = make_edgeless_graph({"x": 5.0})
        result = try_presolve(graph)

        assert result.status == PresolveStatus.APPLIED
        assert result.delta == (1,)
        assert result.selection_weight == 5.0


class TestPresolveGraphsWithEdges:
    """Tests for graphs that cannot be presolved."""

    def test_graph_with_edges_not_applicable(self):
        """Graph with edges should not be presolved."""
        graph = make_graph_with_edges(
            {"a": 1.0, "b": 2.0, "c": 3.0},
            [("a", "b")]
        )
        result = try_presolve(graph)

        assert result.status == PresolveStatus.NOT_APPLICABLE
        assert result.reason is None
        assert result.delta is None
        assert not result.is_certified_optimal
        assert not result.backend_bypassed
        assert "has edges" in (result.diagnostic_message or "")

    def test_complete_graph(self):
        """Complete graph should not be presolved."""
        graph = make_graph_with_edges(
            {"a": 1.0, "b": 2.0, "c": 3.0},
            [("a", "b"), ("a", "c"), ("b", "c")]
        )
        result = try_presolve(graph)

        assert result.status == PresolveStatus.NOT_APPLICABLE


class TestPresolveToSample:
    """Tests for converting presolve result to RawMISSample."""

    def test_convert_applied_presolve_to_sample(self):
        """Successful presolve should convert to a valid sample."""
        graph = make_edgeless_graph({"a": 1.0, "b": 2.0})
        presolve_result = try_presolve(graph)

        sample = presolve_to_raw_sample(
            presolve_result, run_id="test-run", round_index=0
        )

        assert sample.node_order == ("a", "b")
        assert sample.delta == (1, 1)
        assert sample.occurrence_count == 1
        assert sample.source_provider_id == "qreduce"
        assert sample.source_backend_id == "presolve_exact"
        assert sample.is_independent_set is True
        assert "presolve" in sample.raw_sample_id

    def test_convert_not_applied_raises_error(self):
        """Non-applied presolve should raise ValueError."""
        graph = make_graph_with_edges({"a": 1.0, "b": 2.0}, [("a", "b")])
        presolve_result = try_presolve(graph)

        with pytest.raises(ValueError, match="non-applied"):
            presolve_to_raw_sample(presolve_result, run_id="test", round_index=0)


class TestPresolveProvenance:
    """Tests for presolve audit provenance."""

    def test_provenance_includes_version(self):
        """Presolve result should include version for reproducibility."""
        graph = make_edgeless_graph({"a": 1.0})
        result = try_presolve(graph)

        assert "presolve_version" in result.provenance
        assert result.provenance["presolve_version"] == 1

    def test_provenance_records_zero_weight_policy(self):
        """Presolve should record the zero-weight handling policy."""
        graph = make_edgeless_graph({"a": 1.0, "b": 0.0})

        result_include = try_presolve(graph, include_zero_weight_nodes=True)
        assert result_include.provenance["include_zero_weight_nodes"] is True

        result_exclude = try_presolve(graph, include_zero_weight_nodes=False)
        assert result_exclude.provenance["include_zero_weight_nodes"] is False

    def test_to_dict_serialization(self):
        """PresolveResult should serialize to dictionary."""
        graph = make_edgeless_graph({"a": 1.0, "b": 2.0})
        result = try_presolve(graph)

        d = result.to_dict()
        assert d["status"] == "applied"
        assert d["reason"] == "edgeless_positive_weights"
        assert d["delta"] == [1, 1]
        assert d["is_certified_optimal"] is True


class TestPresolveWithPortfolioGraph:
    """Tests simulating the portfolio problem scenario."""

    def test_12_node_edgeless_portfolio_graph(self):
        """Simulate the 12-asset portfolio case with no correlations."""
        # This recreates the scenario from the plan: 12 assets, no edges
        node_weights = {f"asset_{i}": 0.5 + i * 0.1 for i in range(12)}
        graph = make_edgeless_graph(node_weights)

        result = try_presolve(graph, requested_backend_id="pasqal_local")

        assert result.status == PresolveStatus.APPLIED
        assert result.num_selected == 12  # All 12 should be selected
        assert all(d == 1 for d in result.delta)  # All selected
        assert result.is_certified_optimal

        # Total weight should be sum of all weights
        expected_weight = sum(node_weights.values())
        assert abs(result.selection_weight - expected_weight) < 1e-10

        # This is exactly what was missing: Pasqal selected 8, should be 12
        assert result.diagnostic_message is not None
        assert "12 nodes" in result.diagnostic_message
