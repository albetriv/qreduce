"""Deterministic examples and presentation data for the visualization notebooks.

These examples are illustrative, not a benchmark or a policy recommendation.
"""

from itertools import product

from qreduce.domains.portfolio import (
    MeanVariancePortfolioAdapter,
    PortfolioGraphPolicy,
    PortfolioProblem,
)
from qreduce.models import (
    ArtifactOptions,
    ClassicalSolveOptions,
    LambdaEdgePolicy,
    MISExecutionOptions,
    ReductionPolicy,
    ResolvedRunConfig,
)
from qreduce.mwis.energy import ising_energy, qubo_energy
from qreduce.mwis.exact import solve_exact_mwis
from qreduce.mwis.graph import ReductionGraph
from qreduce.mwis.ising import delta_to_spin, qubo_to_ising
from qreduce.mwis.qubo import build_mwis_qubo
from qreduce.mwis.validation import validate_binary_selection
from qreduce.pipeline import run_single_pass
from qreduce.status import PostcheckMode


def graph_example() -> dict[str, object]:
    """Build a tiny graph and its certified, bounded exact diagnostic."""
    graph = ReductionGraph(
        node_ids=("a", "b", "c"),
        node_weights={"a": 2.0, "b": 1.0, "c": 3.0},
        edges=(("a", "b"), ("b", "c")),
        edge_reasons={("a", "b"): "conflict", ("b", "c"): "conflict"},
        graph_policy_id="notebook-example", graph_policy_version="1",
    )
    qubo = build_mwis_qubo(graph, 4.0)
    exact = solve_exact_mwis(graph, qubo, exact_solver_max_variables=3)
    nodes = [
        {"node": node, "weight": graph.node_weights[node], "delta_selected": selected}
        for node, selected in zip(graph.node_ids, exact.delta, strict=True)
    ]
    edges = [{"source": a, "target": b, "reason": graph.edge_reasons[(a, b)]} for a, b in graph.edges]
    selected_ids = [node for node, selected in zip(graph.node_ids, exact.delta, strict=True) if selected]
    return {"graph": graph, "qubo": qubo, "exact": exact, "nodes": nodes, "edges": edges,
            "selected_ids": selected_ids}


def energy_example() -> dict[str, object]:
    """Return canonical terms and all energies for the bounded example graph."""
    example = graph_example()
    graph, qubo = example["graph"], example["qubo"]
    ising = qubo_to_ising(qubo)
    energies = []
    for delta in product((0, 1), repeat=len(graph.node_ids)):
        z_spin = delta_to_spin(delta)
        validation = validate_binary_selection(graph, delta)
        energies.append({
            "delta": delta, "z_spin": z_spin,
            "qubo_energy": qubo_energy(qubo, delta),
            "ising_energy": ising_energy(ising, z_spin),
            "independent": validation.is_independent_set,
        })
    return {"graph": graph, "qubo": qubo.to_dict(), "ising": ising.to_dict(), "energies": energies}


def portfolio_example() -> dict[str, object]:
    """Run the real single-pass pipeline, retaining failures and partial output."""
    problem = PortfolioProblem(
        asset_ids=("asset-a", "asset-b", "asset-c"),
        expected_returns={"asset-a": 0.10, "asset-b": 0.08, "asset-c": 0.06},
        covariance=((0.04, 0.018, 0.002), (0.018, 0.09, 0.003), (0.002, 0.003, 0.01)),
        lower_bounds={"asset-a": 0.0, "asset-b": 0.0, "asset-c": 0.0},
        upper_bounds={"asset-a": 0.7, "asset-b": 0.7, "asset-c": 0.7},
        retention_scores={"asset-a": 0.9, "asset-b": 0.7, "asset-c": 0.6},
        risk_aversion=1.0,
    )
    config = ResolvedRunConfig(
        schema_version="1.0", reduction=ReductionPolicy(1, 1, 3, 1, 0.1, 3, 60.0),
        lambda_edge=2.0, lambda_edge_policy=LambdaEdgePolicy("standard", "1", 2.0),
        allow_noncertifying_penalty=False, mis_solver_id="local_greedy",
        mis_execution=MISExecutionOptions(1, 17, 1, False, 0, 0.0, 20),
        classical_solve=ClassicalSolveOptions(
            classical_solver_id="cplex", time_limit_seconds=10.0, mip_gap_tolerance=None,
            threads=1, model_export_enabled=False, primal_feasibility_tolerance=1e-6,
            integrality_tolerance=1e-6, objective_recomputation_absolute_tolerance=1e-6,
            objective_recomputation_relative_tolerance=1e-6, postcheck_mode=PostcheckMode.STRICT,
            random_seed=7,
        ),
        artifacts=ArtifactOptions("notebook-portfolio", "1.0", "0.1.0", "caller_supplied", True),
    )
    adapter = MeanVariancePortfolioAdapter(PortfolioGraphPolicy("notebook-policy", "1", 0.25))
    graph = adapter.build_conflict_graph(problem)
    result = run_single_pass(problem, adapter, config)
    retained = list(result.retained_item_ids) if result.fixing_manifest is not None else None
    nodes = [{"asset": node, "retention_score": graph.node_weights[node]} for node in graph.node_ids]
    edges = [{"source": left, "target": right, "reason": graph.edge_reasons[(left, right)]}
             for left, right in graph.edges]
    domain = [{"asset": node, "retained": None if retained is None else node in retained}
              for node in graph.node_ids]
    return {"assets": list(problem.asset_ids), "graph": graph, "result": result.to_dict(),
            "retained_ids": retained, "nodes": nodes, "edges": edges, "domain": domain}