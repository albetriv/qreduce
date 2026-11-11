"""Tests for bounded diagnostic exact MWIS/QUBO enumeration."""

from itertools import product

import pytest

from qreduce.mwis.energy import qubo_energy
from qreduce.mwis.exact import ExactMWISResult, solve_exact_mwis
from qreduce.mwis.graph import ReductionGraph
from qreduce.mwis.qubo import build_mwis_qubo
from qreduce.mwis.validation import MWISValidationError, validate_binary_selection


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


def test_every_global_standard_qubo_minimizer_is_an_mwis() -> None:
    """The structural penalty guarantee applies to all tied global minimizers."""

    graph = ReductionGraph(
        node_ids=("a", "b", "c"),
        node_weights={"a": 2.0, "b": 2.0, "c": 1.0},
        edges=(("a", "b"),),
        edge_reasons={("a", "b"): "conflict"},
        graph_policy_id="test-policy",
        graph_policy_version="1",
    )
    qubo = build_mwis_qubo(graph, 3.0)
    assignments = tuple(product((0, 1), repeat=len(graph.node_ids)))
    minimum_energy = min(qubo_energy(qubo, delta) for delta in assignments)
    minimizers = tuple(delta for delta in assignments if qubo_energy(qubo, delta) == minimum_energy)

    assert len(minimizers) == 2
    assert {
        validate_binary_selection(graph, delta).selected_node_ids for delta in minimizers
    } == {("a", "c"), ("b", "c")}
    for delta in minimizers:
        validation = validate_binary_selection(graph, delta)
        assert validation.is_independent_set is True
        assert validation.selection_weight == 3.0


def test_exact_solver_rejects_instances_above_explicit_limit() -> None:
    """Diagnostic enumeration cannot silently exceed its configured variable limit."""

    graph = make_graph()
    with pytest.raises(MWISValidationError) as error:
        solve_exact_mwis(graph, build_mwis_qubo(graph, 4.0), exact_solver_max_variables=2)

    assert error.value.code == "exact_solver_variable_limit_exceeded"