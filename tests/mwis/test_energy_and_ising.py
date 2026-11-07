"""Tests for local QUBO energy and declared QUBO-Ising equivalence."""

from itertools import product

import pytest

from qreduce.mwis.energy import ising_energy, qubo_energy
from qreduce.mwis.graph import CanonicalMWISProblem, ReductionGraph
from qreduce.mwis.ising import delta_to_spin, qubo_to_ising, spin_to_delta
from qreduce.mwis.qubo import build_mwis_qubo
from qreduce.mwis.validation import MWISValidationError


def make_qubo():
    """Create a nontrivial two-variable QUBO from a one-edge MWIS graph."""

    graph = ReductionGraph(
        node_ids=("a", "b"),
        node_weights={"a": 1.0, "b": 2.0},
        edges=(("a", "b"),),
        edge_reasons={("a", "b"): "conflict"},
        graph_policy_id="test-policy",
        graph_policy_version="1",
    )
    return build_mwis_qubo(graph, 3.0)


def test_local_qubo_energy_matches_expected_polynomial_value() -> None:
    """Local energy includes the explicit offset, linear terms and edge term once."""

    qubo = make_qubo()

    assert qubo_energy(qubo, (1, 1)) == 0.0
    assert qubo_energy(qubo, (0, 1)) == -2.0
    with pytest.raises(MWISValidationError, match="invalid_binary_value"):
        qubo_energy(qubo, (1, 2))


def test_qubo_ising_conversion_preserves_all_energies_and_argmin() -> None:
    """The declared delta-to-spin conversion preserves energy including offset."""

    qubo = make_qubo()
    ising = qubo_to_ising(qubo)
    qubo_energies = {}
    ising_energies = {}
    for delta in product((0, 1), repeat=2):
        z_spin = delta_to_spin(delta)
        assert spin_to_delta(z_spin) == delta
        qubo_energies[delta] = qubo_energy(qubo, delta)
        ising_energies[delta] = ising_energy(ising, z_spin)
        assert qubo_energies[delta] == ising_energies[delta]

    minimum_qubo_energy = min(qubo_energies.values())
    minimum_ising_energy = min(ising_energies.values())
    assert {delta for delta, energy in qubo_energies.items() if energy == minimum_qubo_energy} == {
        delta for delta, energy in ising_energies.items() if energy == minimum_ising_energy
    }
    assert ising.to_dict()["binary_to_spin_convention"] == "delta_i = (1 + z_i) / 2; z_i = 2 * delta_i - 1"


def test_canonical_problem_serializes_graph_qubo_and_ising_with_one_node_order() -> None:
    """The backend-facing aggregate contains only serializable canonical forms."""

    qubo = make_qubo()
    problem = CanonicalMWISProblem(
        graph=ReductionGraph(
            node_ids=("a", "b"),
            node_weights={"a": 1.0, "b": 2.0},
            edges=(("a", "b"),),
            edge_reasons={("a", "b"): "conflict"},
            graph_policy_id="test-policy",
            graph_policy_version="1",
        ),
        qubo=qubo,
        ising=qubo_to_ising(qubo),
    )

    assert problem.to_dict()["qubo"]["node_order"] == ["a", "b"]
    assert problem.to_dict()["ising"]["node_order"] == ["a", "b"]