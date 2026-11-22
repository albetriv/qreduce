"""Read-only, artifact-backed MWIS and Pasqal diagnostics for portfolio notebooks."""

import ast
import math
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path

from qreduce.experiments.portfolio_mv.analysis import (
    PortfolioSolutionAnalysis,
    load_portfolio_solution_analysis,
)
from qreduce.mwis import ReductionGraph, build_mwis_qubo
from qreduce.mwis.exact import solve_exact_mwis
from qreduce.mwis.validation import validate_binary_selection


def find_repository_root(start: str | Path | None = None) -> Path:
    """Find QReduce from the notebook working directory without changing cwd."""
    start = Path(start or Path.cwd()).resolve()
    for directory in (start, *start.parents):
        if (directory / "pyproject.toml").is_file() and (directory / "src/qreduce").is_dir():
            return directory
    raise FileNotFoundError("QReduce repository root not found; set REPOSITORY_ROOT explicitly.")


def available_runs(output_root: str | Path) -> list[str]:
    """List saved run directories; loading subsequently validates their artifacts."""
    return sorted(path.name for path in Path(output_root).iterdir()
                  if path.is_dir() and (path / "run_manifest.json").is_file())


@dataclass
class PortfolioRunView:
    """Presentation data for one saved round, never executing a backend."""

    analysis: PortfolioSolutionAnalysis
    round_result: dict
    graph: ReductionGraph | None
    payload: dict

    @property
    def selected_ids(self) -> tuple[str, ...]:
        """Return the union of selected source candidates, before the domain cap."""
        return tuple(dict.fromkeys(node for sample in self.round_result.get("selected_mis_samples", [])
                                   for node, bit in zip(sample["node_order"], sample["delta"], strict=True) if bit))


def load_run_view(output_root: str | Path, run_id: str, round_index: int = 0) -> PortfolioRunView:
    """Load hash-validated artifacts and the persisted graph, not a regenerated graph."""
    if not run_id or Path(run_id).name != run_id or run_id in {".", ".."}:
        raise ValueError("run_id must identify a direct output subdirectory.")
    analysis = load_portfolio_solution_analysis(Path(output_root) / run_id)
    if analysis.artifacts.manifest["run_id"] != run_id:
        raise ValueError("Directory and manifest run IDs differ.")
    rounds = analysis.artifacts.round_results
    matches = [r for r in rounds if r.get("round_index") == round_index]
    if rounds and not matches:
        raise ValueError(f"Round {round_index} not recorded.")
    result = dict(matches[0]) if matches else {}
    job = (result.get("mis_compilation_result") or {}).get("compiled_job") or {}
    data = (job.get("compiled_problem") or {}).get("graph")
    graph = None
    if data:
        raw_reasons = data["edge_reasons"]
        reasons = ({tuple(ast.literal_eval(key)): value for key, value in raw_reasons.items()}
                   if isinstance(raw_reasons, dict) else
                   {tuple(record["edge"]): record["reason"] for record in raw_reasons})
        graph = ReductionGraph(tuple(data["node_ids"]), data["node_weights"],
                               tuple(tuple(edge) for edge in data["edges"]), reasons,
                               data["graph_policy_id"], data["graph_policy_version"])
    return PortfolioRunView(analysis, result, graph, job.get("provider_payload") or {})


def run_summary(view: PortfolioRunView) -> dict:
    """Distinguish original assets, MWIS candidates, retained domain and investments."""
    artifacts = view.analysis.artifacts
    result = artifacts.result
    return {
        "run_id": artifacts.manifest["run_id"],
        "stato": artifacts.manifest["run_status"],
        "diagnostica": result.get("run_result", {}).get("diagnostic_message"),
        "round": view.round_result.get("round_index"),
        "asset_originali": len(view.analysis.asset_ids),
        "nodi_grafo": len(view.graph.node_ids) if view.graph else None,
        "archi_grafo": len(view.graph.edges) if view.graph else None,
        "asset_unione_candidati_MWIS": len(view.selected_ids) if view.round_result else None,
        "cap_dominio": artifacts.config.get("reduction", {}).get("candidate_domain_max_items"),
        "asset_dominio_finale": len(view.analysis.retained_item_ids) if view.analysis.retained_item_ids is not None else None,
        "presolve": view.payload.get("presolve_applied"),
        "codifica_pesi": view.payload.get("weight_encoding_mode"),
        "ambito_verifica_fisica": view.payload.get("physical_validation_scope"),
        "soluzione": view.analysis.solution_summary(),
    }


def incompatibility_rows(view: PortfolioRunView) -> list[dict]:
    """Expose saved edge reasons and node weights without interpreting correlations again."""
    if view.graph is None:
        return []
    return [{"asset_a": a, "asset_b": b, "motivo": view.graph.edge_reasons[(a, b)]}
            for a, b in view.graph.edges]


def geometry_report(view: PortfolioRunView) -> dict:
    """Recompute threshold edges from saved coordinates and report missing/extra edges."""
    graph, payload = view.graph, view.payload
    mapping = payload.get("mapping") or {}
    if graph is None or not payload.get("coordinates") or "radius" not in mapping:
        return {"disponibile": False, "motivo": "Layout Pasqal non registrato (baseline, presolve o compilazione fallita)."}
    order = tuple(payload.get("node_order", ()))
    coordinates = payload["coordinates"]
    if order != graph.node_ids or len(coordinates) != len(order):
        raise ValueError("Layout node order does not match the saved graph.")
    coords = dict(zip(order, coordinates, strict=True))
    if any(len(pair) != 2 or any(not math.isfinite(v) for v in pair) for pair in coords.values()):
        raise ValueError("Invalid saved 2D coordinates.")
    radius = mapping["radius"]
    if not isinstance(radius, (int, float)) or not math.isfinite(radius) or radius <= 0:
        raise ValueError("Invalid geometric radius.")
    geometric = {tuple(sorted((a, b))) for a, b in combinations(order, 2)
                 if math.dist(coords[a], coords[b]) <= radius}
    target = set(graph.edges)
    recorded = mapping.get("geometric_edges")
    return {"disponibile": True, "radius_um": radius, "coordinates": coords,
            "target_edges": sorted(target), "geometric_edges": sorted(geometric),
            "missing_edges": sorted(target - geometric), "extra_edges": sorted(geometric - target),
            "congruenti": target == geometric,
            "coerente_con_archi_persistiti": None if recorded is None else geometric == {tuple(e) for e in recorded},
            "geometry_diagnostics": payload.get("geometry_diagnostics"),
            "physical_vs_canonical": payload.get("physical_vs_canonical")}


def sampling_rows(view: PortfolioRunView) -> list[dict]:
    """Recompute independence and MWIS weights for every raw bitstring in node order."""
    if view.graph is None:
        return []
    rows = []
    execution = view.round_result.get("mis_execution_result") or {}
    for sample in execution.get("samples", []):
        if tuple(sample["node_order"]) != view.graph.node_ids:
            raise ValueError("Raw sample node order differs from the graph.")
        validation = validate_binary_selection(view.graph, sample["delta"])
        rows.append({"raw_sample_id": sample["raw_sample_id"],
                     "bitstring": "".join(str(bit) for bit in sample["delta"]),
                     "occorrenze": sample["occurrence_count"],
                     "indipendente": validation.is_independent_set,
                     "archi_violati": validation.num_violated_edges,
                     "asset_selezionati": validation.num_selected,
                     "peso_MWIS": validation.selection_weight,
                     "provider": sample.get("source_provider_id"),
                     "backend": sample.get("source_backend_id")})
    return sorted(rows, key=lambda row: (-row["occorrenze"], row["bitstring"]))


def sampling_summary(view: PortfolioRunView) -> dict:
    """Report raw occurrence statistics separately from candidate post-processing."""
    rows = sampling_rows(view)
    total = sum(row["occorrenze"] for row in rows)
    valid = sum(row["occorrenze"] for row in rows if row["indipendente"])
    return {"bitstring_distinti": len(rows), "occorrenze_raw": total,
            "occorrenze_indipendenti": valid, "occorrenze_non_indipendenti": total - valid,
            "frazione_indipendente": valid / total if total else None,
            "nota": "Presolve: occorrenze deterministiche, non shot fisici." if view.payload.get("presolve_applied") else "Campioni raw prima di repair/completamento."}


def exact_diagnostic(view: PortfolioRunView, max_nodes: int = 16) -> dict:
    """Compute bounded exact MWIS diagnostics without calling a provider or solver SDK."""
    if isinstance(max_nodes, bool) or not isinstance(max_nodes, int) or not 0 <= max_nodes <= 20:
        raise ValueError("Exact diagnostic limit must be an integer between 0 and 20.")
    if view.graph is None or len(view.graph.node_ids) > max_nodes:
        return {"disponibile": False, "motivo": f"Grafo assente o oltre il limite esplicito di {max_nodes} nodi."}
    graph = view.graph
    qubo = build_mwis_qubo(graph, max(graph.node_weights.values(), default=0) + 1)
    exact = solve_exact_mwis(graph, qubo, exact_solver_max_variables=max_nodes)
    return {"disponibile": True, **exact.to_dict(),
            "selected_ids": [node for node, bit in zip(graph.node_ids, exact.delta, strict=True) if bit]}


def allocation_rows(view: PortfolioRunView, baseline: PortfolioRunView | None = None) -> list[dict]:
    """Extract adopted, postchecked allocations; refuse comparisons across problems."""
    if baseline is not None and view.analysis.artifacts.problem != baseline.analysis.artifacts.problem:
        raise ValueError("Cannot compare allocations from different original problems.")
    values = {}
    for label, run in (("run", view), ("baseline", baseline)):
        if run is None:
            continue
        result = run.analysis.artifacts.result
        status = result.get("run_result") or {}
        postcheck = result.get("postcheck_result") or {}
        if status.get("adoption_status") != "adopted" or postcheck.get("is_feasible", postcheck.get("postcheck_feasible")) is not True:
            raise ValueError(f"{label}: no adopted, postchecked allocation is available.")
        variables = (result.get("classical_result") or {}).get("variable_values") or {}
        values[label] = variables
        if any(isinstance(variables.get(f"x__{node}"), bool)
               or not isinstance(variables.get(f"x__{node}"), (int, float))
               or not math.isfinite(variables[f"x__{node}"]) for node in run.analysis.asset_ids):
            raise ValueError(f"{label}: incomplete allocation vector.")
    return [{"asset": node, **{label: variables[f"x__{node}"] for label, variables in values.items()}}
            for node in view.analysis.asset_ids]


def plot_incompatibilities(view: PortfolioRunView):
    """Plot full-portfolio correlations, marking only persisted round edges."""
    from qreduce.notebooks.plots import plot_correlation_matrix

    analysis = view.analysis
    if analysis.correlation is None:
        print("Correlazioni non disponibili.")
        return None
    graph = view.graph
    if graph is not None and graph.node_ids != analysis.asset_ids:
        indices = [analysis.asset_ids.index(node) for node in graph.node_ids]
        correlation = tuple(tuple(analysis.correlation[i][j] for j in indices) for i in indices)
        return plot_correlation_matrix(graph.node_ids, correlation, graph, analysis.correlation_threshold)
    return plot_correlation_matrix(analysis.asset_ids, analysis.correlation, graph, analysis.correlation_threshold)


def plot_mwis_graph(view: PortfolioRunView):
    """Highlight the selected candidate union on the saved logical graph."""
    from qreduce.notebooks.plots import plot_reduction_graph

    if view.graph is None:
        print("Grafo MWIS non registrato: nessun grafo inventato per la baseline.")
        return None
    return plot_reduction_graph(view.graph, view.selected_ids,
                                highlighted_label="Unione candidati scelti (prima del cap)",
                                title="Grafo MWIS target e selezione")


def plot_pasqal_geometry(view: PortfolioRunView):
    """Compare target and threshold graphs on the same saved physical coordinates."""
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

    report = geometry_report(view)
    if not report["disponibile"]:
        print(report["motivo"])
        return None
    coordinates = report["coordinates"]
    target, geometric = set(report["target_edges"]), set(report["geometric_edges"])
    fig, axes = plt.subplots(1, 2, figsize=(16, 7))
    for ax, edges, title in zip(axes, (target, geometric),
                                ("Archi target sulle coordinate salvate", "Grafo geometrico Pasqal a soglia"), strict=True):
        for a, b in sorted(edges | (target - geometric)):
            color = "tab:red" if (a, b) not in geometric else "tab:orange" if (a, b) not in target else "0.4"
            style = "--" if (a, b) not in geometric else "-"
            ax.plot([coordinates[a][0], coordinates[b][0]],
                    [coordinates[a][1], coordinates[b][1]], color=color, linestyle=style, zorder=1)
        for node, (x_pos, y_pos) in coordinates.items():
            ax.scatter(x_pos, y_pos, s=250, color="#b7e4c7" if node in view.selected_ids else "white",
                       edgecolor="tab:blue", zorder=2)
            ax.annotate(node, (x_pos, y_pos), xytext=(5, 8), textcoords="offset points", fontsize=8)
        ax.set(title=title, xlabel="Posizione orizzontale (um)", ylabel="Posizione verticale (um)")
        ax.set_aspect("equal")
        ax.grid(alpha=.2)
    axes[1].legend(handles=[Line2D([], [], color="0.4", label="Arco comune"),
                            Line2D([], [], color="tab:red", linestyle="--", label="Target mancante"),
                            Line2D([], [], color="tab:orange", label="Arco extra")])
    fig.suptitle(f"Raggio geometrico = {report['radius_um']:g} um; non è un cutoff fisico delle interazioni")
    fig.tight_layout()
    return fig, axes


def plot_sampling(view: PortfolioRunView, top_k: int = 20):
    """Plot frequent raw bitstrings and per-node excitation frequencies."""
    import matplotlib.pyplot as plt

    if not isinstance(top_k, int) or isinstance(top_k, bool) or top_k < 1:
        raise ValueError("top_k must be a positive integer.")
    rows = sampling_rows(view)
    if not rows:
        print("Nessun campione raw registrato.")
        return None
    total = sum(row["occorrenze"] for row in rows)
    top = rows[:top_k]
    fig, axes = plt.subplots(2, 1, figsize=(14, 10))
    axes[0].bar(range(len(top)), [row["occorrenze"] for row in top],
                color=["tab:green" if row["indipendente"] else "tab:red" for row in top])
    axes[0].set_xticks(range(len(top)), [row["bitstring"] for row in top], rotation=70)
    axes[0].set(title=f"Top {len(top)} campioni raw: verde indipendente, rosso con conflitti",
                ylabel="Occorrenze (non rinormalizzate sul top)")
    frequencies = [sum(row["occorrenze"] * int(row["bitstring"][i]) for row in rows) / total
                   for i in range(len(view.graph.node_ids))]
    axes[1].bar(view.graph.node_ids, frequencies, color="tab:blue")
    axes[1].tick_params(axis="x", rotation=65)
    axes[1].set(title="Frequenza raw di selezione per asset (tutti i campioni)", ylabel="Frequenza", ylim=(0, 1))
    fig.tight_layout()
    return fig, axes


def plot_allocations(view: PortfolioRunView, baseline: PortfolioRunView | None = None):
    """Plot complete final continuous allocations without renormalizing weights."""
    import matplotlib.pyplot as plt

    try:
        rows = allocation_rows(view, baseline)
    except ValueError as error:
        print(f"Allocazioni non confrontabili: {error}")
        return None
    fig, ax = plt.subplots(figsize=(14, 5))
    positions = list(range(len(rows)))
    width = .38 if baseline else .7
    ax.bar([i - width / 2 if baseline else i for i in positions], [r["run"] for r in rows],
           width, label=str(view.analysis.artifacts.manifest["run_id"]))
    if baseline:
        ax.bar([i + width / 2 for i in positions], [r["baseline"] for r in rows], width,
               label=str(baseline.analysis.artifacts.manifest["run_id"]))
    ax.set_xticks(positions, [r["asset"] for r in rows], rotation=60)
    ax.set(title="Allocazioni finali adottate e postchecked", ylabel="Peso continuo x")
    ax.legend()
    ax.grid(axis="y", alpha=.3)
    fig.tight_layout()
    return fig, ax


def comparison_summary(view: PortfolioRunView, baseline: PortfolioRunView | None = None) -> list[dict]:
    """Compare saved objectives only for identical problems and valid allocations."""
    try:
        allocation_rows(view, baseline)
    except ValueError as error:
        return [{"confrontabile": False, "motivo": str(error)}]
    rows = []
    for run in (view, baseline):
        if run is None:
            continue
        result = run.analysis.artifacts.result
        classical = result["classical_result"]
        rows.append({"run_id": run.analysis.artifacts.manifest["run_id"],
                     "obiettivo": classical.get("objective_value"),
                     "ottimalita_originale": result.get("original_problem_optimality_claim"),
                     "ottimalita_residuo": result.get("residual_problem_optimality_claim"),
                     "runtime_totale_s": result.get("metrics", {}).get("end_to_end_runtime_seconds"),
                     **run.analysis.solution_summary()})
    return rows