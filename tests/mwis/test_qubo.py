"""Tests for mandatory standard MWIS QUBO construction."""

import pytest

from qreduce.mwis.graph import ReductionGraph
from qreduce.mwis.qubo import build_mwis_qubo
from qreduce.mwis.validation import MWISValidationError


def make_graph() -> ReductionGraph:
    """Build a three-node graph with two conflict edges."""

    return ReductionGraph(
        node_ids=("a", "b", "c"),
        node_weights={"a": 1.0, "b": 2.0, "c": 3.0},
        edges=(("a", "b"), ("b", "c")),
        edge_reasons={("a", "b"): "conflict", ("b", "c"): "conflict"},
        graph_policy_id="test-policy",
        graph_policy_version="1",
    )


def test_standard_qubo_has_one_linear_term_per_node_and_one_quadratic_term_per_edge() -> None:
    """The canonical builder emits exactly the required MWIS terms."""

    qubo = build_mwis_qubo(make_graph(), 4.0)

    assert dict(qubo.linear) == {"a": -1.0, "b": -2.0, "c": -3.0}
    assert dict(qubo.quadratic) == {("a", "b"): 4.0, ("b", "c"): 4.0}
    assert qubo.offset == 0.0
    assert len(qubo.linear) == 3
    assert len(qubo.quadratic) == 2
    assert qubo.proof_condition_satisfied is True


def test_standard_qubo_rejects_noncertifying_penalty_without_explicit_opt_in() -> None:
    """lambda_edge must exceed every node weight for the standard policy."""

    with pytest.raises(MWISValidationError, match="noncertifying_lambda_edge"):
        build_mwis_qubo(make_graph(), 3.0)


def test_noncertifying_penalty_requires_opt_in_and_is_marked_without_guarantee() -> None:
    """Experimental penalties remain explicit and never claim the standard proof."""

    qubo = build_mwis_qubo(make_graph(), 3.0, allow_noncertifying_penalty=True)

    assert qubo.proof_condition_satisfied is False


def test_nonpositive_penalty_is_rejected_even_with_noncertifying_opt_in() -> None:
    """Opt-in relaxes only the proof inequality, not the penalty's positivity."""

    with pytest.raises(MWISValidationError, match="invalid_lambda_edge"):
        build_mwis_qubo(make_graph(), 0.0, allow_noncertifying_penalty=True)