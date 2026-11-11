"""Deterministic examples and presentation data for the visualization notebooks.

These examples are illustrative, not a benchmark or a policy recommendation.
"""

from itertools import product

from qreduce.mwis.energy import ising_energy, qubo_energy
from qreduce.mwis.exact import solve_exact_mwis
from qreduce.mwis.graph import ReductionGraph
from qreduce.mwis.ising import delta_to_spin, qubo_to_ising
from qreduce.mwis.qubo import build_mwis_qubo
from qreduce.mwis.validation import validate_binary_selection


def graph_example() -> dict[str, object]:
    """Build a tiny graph and its certified, bounded exact diagnostic."""
    graph = ReductionGraph(
        node_ids=("a", "b", "c"),
        node_weights={"a": 2.0, "b": 1.0, "c": 3.0},
        edges=(("a", "b"), ("b", "c")),
        edge_reasons={("a", "b"): "conflict", ("b", "c"): "conflict"},
        graph_policy_id="notebook-example",
        graph_policy_version="1",
    )
    qubo = build_mwis_qubo(graph, 4.0)
    exact = solve_exact_mwis(graph, qubo, exact_solver_max_variables=3)
    nodes = [
        {"node": node, "weight": graph.node_weights[node], "delta_selected": selected}
        for node, selected in zip(graph.node_ids, exact.delta, strict=True)
    ]
    edges = [
        {"source": a, "target": b, "reason": graph.edge_reasons[(a, b)]}
        for a, b in graph.edges
    ]
    selected_ids = [
        node
        for node, selected in zip(graph.node_ids, exact.delta, strict=True)
        if selected
    ]
    return {
        "graph": graph,
        "qubo": qubo,
        "exact": exact,
        "nodes": nodes,
        "edges": edges,
        "selected_ids": selected_ids,
    }


def energy_example() -> dict[str, object]:
    """Return canonical terms and all energies for the bounded example graph."""
    example = graph_example()
    graph, qubo = example["graph"], example["qubo"]
    ising = qubo_to_ising(qubo)
    energies = []
    for delta in product((0, 1), repeat=len(graph.node_ids)):
        z_spin = delta_to_spin(delta)
        validation = validate_binary_selection(graph, delta)
        energies.append(
            {
                "delta": delta,
                "z_spin": z_spin,
                "qubo_energy": qubo_energy(qubo, delta),
                "ising_energy": ising_energy(ising, z_spin),
                "independent": validation.is_independent_set,
            }
        )
    return {
        "graph": graph,
        "qubo": qubo.to_dict(),
        "ising": ising.to_dict(),
        "energies": energies,
    }
