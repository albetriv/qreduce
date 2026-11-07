"""Tests for canonical ReductionGraph invariants and serialization."""

import json

import pytest

from qreduce.mwis.graph import ReductionGraph
from qreduce.mwis.validation import MWISValidationError, validate_binary_selection


def make_graph(**changes: object) -> ReductionGraph:
    """Build a small valid graph with intentionally non-lexicographic node order."""

    values: dict[str, object] = {
        "node_ids": ("b", "a", "c"),
        "node_weights": {"b": 2.0, "a": 1.0, "c": 3.0},
        "edges": (("a", "b"), ("a", "c")),
        "edge_reasons": {("a", "b"): "overlap", ("a", "c"): "resource"},
        "graph_policy_id": "test-policy",
        "graph_policy_version": "1",
    }
    values.update(changes)
    return ReductionGraph(**values)  # type: ignore[arg-type]


def test_graph_preserves_declared_node_order_and_serializes_edges_explicitly() -> None:
    """The adapter's node order is retained as the sole delta-vector order."""

    graph = make_graph()
    serialized = json.loads(graph.to_canonical_json())

    assert graph.node_ids == ("b", "a", "c")
    assert serialized["node_ids"] == ["b", "a", "c"]
    assert serialized["edge_reasons"] == [
        {"edge": ["a", "b"], "reason": "overlap"},
        {"edge": ["a", "c"], "reason": "resource"},
    ]
    with pytest.raises(TypeError):
        graph.node_weights["a"] = 4.0


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"node_ids": ("a", "a")}, "duplicate_node_id"),
        ({"node_weights": {"b": float("nan"), "a": 1.0, "c": 3.0}}, "invalid_node_weight"),
        ({"edges": (("a", "missing"),)}, "unknown_edge_endpoint"),
        ({"edges": (("a", "a"),)}, "self_loop"),
        ({"edges": (("b", "a"),)}, "noncanonical_edge"),
        ({"edges": (("a", "b"), ("a", "b"))}, "duplicate_edge"),
        ({"edge_reasons": {("a", "b"): "overlap"}}, "edge_reason_keys_mismatch"),
        ({"edge_reasons": {("a", "b"): "", ("a", "c"): "resource"}}, "missing_edge_reason"),
    ],
)
def test_invalid_graph_invariants_fail_explicitly(changes: dict[str, object], code: str) -> None:
    """Invalid graphs expose stable validation error codes rather than normalizing silently."""

    with pytest.raises(MWISValidationError) as error:
        make_graph(**changes)

    assert error.value.code == code


def test_selection_validation_reports_conflicts_weight_and_selected_nodes() -> None:
    """Structural validation is computed against the graph's declared node order."""

    result = validate_binary_selection(make_graph(), (1, 1, 0))

    assert result.is_independent_set is False
    assert result.violated_edges == (("a", "b"),)
    assert result.selection_weight == 3.0
    assert result.selected_node_ids == ("b", "a")