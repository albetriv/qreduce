"""Tests for bounded diagnostic exact MWIS/QUBO enumeration."""

import pytest

from qreduce.mwis.exact import ExactMWISResult, solve_exact_mwis
from qreduce.mwis.graph import ReductionGraph
from qreduce.mwis.qubo import build_mwis_qubo
from qreduce.mwis.validation import MWISValidationError


def make_graph() -> ReductionGraph:
    """Build a graph whose unique maximum-weight independent set is a and c."""

    return ReductionGraph(
        node_ids=("a", "b", "c"),
        node_weights={"a": 2.0, "b": 1.0, "c": 3.0},
        edges=(("a", "b"), ("b", "c")),
        edge_reasons={("a", "b"): "conflict", ("b", "c"): "conflict"},
        graph_policy_id="test-policy",
        graph_policy_version="1",
    )


def test_exact_solver_certifies_qubo_and_mwis_optimum_for_small_standard_instance() -> None:
    """Full enumeration yields a distinct certified diagnostic result."""

    graph = make_graph()
    result = solve_exact_mwis(graph, build_mwis_qubo(graph, 4.0), exact_solver_max_variables=3)

    assert isinstance(result, ExactMWISResult)
    assert result.delta == (1, 0, 1)
    assert result.is_independent_set is True
    assert result.selection_weight == 5.0
    assert result.is_certified_qubo_optimum is True
    assert result.is_certified_mwis_optimum is True
    assert result.enumerated_assignment_count == 8


def test_exact_solver_rejects_instances_above_explicit_limit() -> None:
    """Diagnostic enumeration cannot silently exceed its configured variable limit."""

    graph = make_graph()
    with pytest.raises(MWISValidationError) as error:
        solve_exact_mwis(graph, build_mwis_qubo(graph, 4.0), exact_solver_max_variables=2)

    assert error.value.code == "exact_solver_variable_limit_exceeded"