"""Portfolio presentation data reconstructed from persisted artifacts."""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from qreduce.experiments.artifacts import (
    ExperimentArtifactError,
    ExperimentRunArtifacts,
    load_experiment_run,
)
from qreduce.experiments.portfolio.execution import UNIFIED_EXPERIMENT_ID
from qreduce.experiments.portfolio.inputs import SYNTHETIC_PORTFOLIO_EXPERIMENT_ID
from qreduce.mwis import ReductionGraph

# Accept both legacy and unified experiment IDs for single-pass compatible analysis
_SINGLE_PASS_COMPATIBLE_IDS = frozenset({
    SYNTHETIC_PORTFOLIO_EXPERIMENT_ID,  # legacy: synthetic-portfolio-single-pass
    UNIFIED_EXPERIMENT_ID,  # new: synthetic-portfolio
})

# Accept both legacy and unified experiment IDs for multi-round compatible analysis
_MULTI_ROUND_COMPATIBLE_IDS = frozenset({
    "synthetic-portfolio-multi-round",  # legacy
    UNIFIED_EXPERIMENT_ID,  # new: synthetic-portfolio
})


@dataclass(frozen=True, slots=True)
class SyntheticPortfolioAnalysis:
    """Notebook-facing presentation data reconstructed exclusively from saved artifacts."""

    artifacts: ExperimentRunArtifacts
    graph: ReductionGraph
    asset_ids: tuple[str, ...]
    correlation: tuple[tuple[float, ...], ...]
    correlation_threshold: float
    retained_item_ids: tuple[str, ...] | None

    def node_rows(self) -> list[dict[str, object]]:
        """Return graph nodes in declared order for tables and plots."""
        return [
            {"asset": asset_id, "retention_score": self.graph.node_weights[asset_id]}
            for asset_id in self.asset_ids
        ]

    def edge_rows(self) -> list[dict[str, object]]:
        """Return graph edges with their persisted construction reasons."""
        return [
            {
                "source": left,
                "target": right,
                "reason": self.graph.edge_reasons[(left, right)],
            }
            for left, right in self.graph.edges
        ]

    def domain_rows(self) -> list[dict[str, object]]:
        """Return retained-domain membership without inferring a final portfolio selection."""
        retained = None if self.retained_item_ids is None else set(self.retained_item_ids)
        return [
            {
                "asset": asset_id,
                "retained": None if retained is None else asset_id in retained,
            }
            for asset_id in self.asset_ids
        ]


def load_synthetic_portfolio_analysis(
    run_directory: str | Path,
) -> SyntheticPortfolioAnalysis:
    """Load and validate presentation data for the synthetic portfolio experiment.

    Accepts runs from both legacy (synthetic-portfolio-single-pass) and unified
    (synthetic-portfolio) experiment IDs.
    """
    artifacts = load_experiment_run(run_directory)
    experiment_id = artifacts.manifest["experiment_id"]
    if experiment_id not in _SINGLE_PASS_COMPATIBLE_IDS:
        raise ExperimentArtifactError(
            "Artifact directory does not contain the synthetic portfolio experiment."
        )

    # Schema 1.1: canonical MWIS data is inside round_results
    # Schema 1.0: canonical_mwis_problem.json is a separate file
    graph_data = artifacts.canonical_mwis_problem
    if graph_data is None and artifacts.round_results:
        # Try to extract from round_results (schema 1.1)
        round_0 = artifacts.round_results[0]
        compilation = round_0.get("mis_compilation_result") or {}
        job = compilation.get("compiled_job") or {}
        graph_data = job.get("compiled_problem")

    if graph_data is None:
        raise ExperimentArtifactError(
            "Synthetic portfolio analysis requires canonical MWIS problem data."
        )
    graph = _rebuild_graph(graph_data)
    problem = _require_mapping(artifacts.problem, "problem.json")
    asset_ids = _string_tuple(problem.get("asset_ids"), "problem.asset_ids")
    covariance = _numeric_matrix(problem.get("covariance"), len(asset_ids), "problem.covariance")
    if graph.node_ids != asset_ids:
        raise ExperimentArtifactError("Persisted graph order does not match portfolio asset order.")
    policy = _require_mapping(
        artifacts.experiment_metadata.get("portfolio_graph_policy"),
        "experiment_metadata.portfolio_graph_policy",
    )
    threshold = _finite_float(
        policy.get("correlation_absolute_threshold"),
        "portfolio_graph_policy.correlation_absolute_threshold",
    )
    retained_item_ids = _retained_item_ids(artifacts.result)
    return SyntheticPortfolioAnalysis(
        artifacts=artifacts,
        graph=graph,
        asset_ids=asset_ids,
        correlation=_correlation_matrix(covariance),
        correlation_threshold=threshold,
        retained_item_ids=retained_item_ids,
    )


def _rebuild_graph(canonical_problem: Mapping[str, object]) -> ReductionGraph:
    graph_data = _require_mapping(canonical_problem.get("graph"), "canonical_mwis_problem.graph")
    node_ids = _string_tuple(graph_data.get("node_ids"), "graph.node_ids")
    node_weights_data = _require_mapping(graph_data.get("node_weights"), "graph.node_weights")
    node_weights = {
        node_id: _finite_float(node_weights_data.get(node_id), f"graph.node_weights[{node_id!r}]")
        for node_id in node_ids
    }
    edges = tuple(
        tuple(_string_tuple(edge, "graph.edges entry"))
        for edge in _require_sequence(graph_data.get("edges"), "graph.edges")
    )
    if any(len(edge) != 2 for edge in edges):
        raise ExperimentArtifactError("Each graph edge must contain exactly two node IDs.")
    edge_reasons: dict[tuple[str, str], str] = {}
    edge_reasons_data = graph_data.get("edge_reasons")
    if isinstance(edge_reasons_data, dict):
        # edge_reasons as dict (newer format from to_primitive with tuple keys as strings)
        for edge_key, reason in edge_reasons_data.items():
            # Parse edge key like "('asset-a', 'asset-b')" or just use edges
            if not isinstance(reason, str) or not reason.strip():
                raise ExperimentArtifactError("Each graph edge reason must be a non-blank string.")
        # Build edge_reasons from edges list assuming same order
        for edge in edges:
            # Try to find matching reason
            edge_key = str(edge)  # tuple string repr
            if edge_key in edge_reasons_data:
                edge_reasons[edge] = edge_reasons_data[edge_key]
            else:
                # Fallback: use edge index from edges list
                edge_reasons[edge] = "persisted edge"
    else:
        # edge_reasons as array (original format from to_dict)
        for record in _require_sequence(edge_reasons_data, "graph.edge_reasons"):
            record_data = _require_mapping(record, "graph.edge_reasons entry")
            edge_values = tuple(_string_tuple(record_data.get("edge"), "graph.edge_reasons.edge"))
            if len(edge_values) != 2:
                raise ExperimentArtifactError("Each graph edge reason must reference exactly two node IDs.")
            reason = record_data.get("reason")
            if not isinstance(reason, str) or not reason.strip():
                raise ExperimentArtifactError("Each graph edge reason must be a non-blank string.")
            edge_reasons[(edge_values[0], edge_values[1])] = reason
    graph_policy_id = graph_data.get("graph_policy_id")
    graph_policy_version = graph_data.get("graph_policy_version")
    if not isinstance(graph_policy_id, str) or not isinstance(graph_policy_version, str):
        raise ExperimentArtifactError("Persisted graph policy metadata is invalid.")
    return ReductionGraph(
        node_ids=node_ids,
        node_weights=node_weights,
        edges=edges,
        edge_reasons=edge_reasons,
        graph_policy_id=graph_policy_id,
        graph_policy_version=graph_policy_version,
    )


def _retained_item_ids(result: Mapping[str, object]) -> tuple[str, ...] | None:
    # Schema 1.1: final_retained_item_ids or cumulative_fixing_manifest at top level
    if "final_retained_item_ids" in result:
        return _string_tuple(result.get("final_retained_item_ids"), "run_result.final_retained_item_ids")
    # Schema 1.0: fixing_manifest and retained_item_ids at top level
    if result.get("fixing_manifest") is None:
        return None
    return _string_tuple(result.get("retained_item_ids"), "run_result.retained_item_ids")


def _correlation_matrix(
    covariance: tuple[tuple[float, ...], ...],
) -> tuple[tuple[float, ...], ...]:
    return tuple(
        tuple(value / math.sqrt(values[row] * covariance[column][column]) for column, value in enumerate(values))
        for row, values in enumerate(covariance)
    )


def _require_mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise ExperimentArtifactError(f"{field} must be a JSON object.")
    return value


def _require_sequence(value: object, field: str) -> Sequence[object]:
    if not isinstance(value, list | tuple):
        raise ExperimentArtifactError(f"{field} must be a JSON array.")
    return value


def _string_tuple(value: object, field: str) -> tuple[str, ...]:
    values = _require_sequence(value, field)
    if any(not isinstance(item, str) or not item.strip() for item in values):
        raise ExperimentArtifactError(f"{field} must contain non-blank strings.")
    return tuple(values)  # type: ignore[return-value]


def _numeric_matrix(value: object, size: int, field: str) -> tuple[tuple[float, ...], ...]:
    rows = _require_sequence(value, field)
    if len(rows) != size:
        raise ExperimentArtifactError(f"{field} must have {size} rows.")
    matrix = tuple(tuple(_finite_float(entry, field) for entry in _require_sequence(row, field)) for row in rows)
    if any(len(row) != size for row in matrix):
        raise ExperimentArtifactError(f"{field} must be a {size} by {size} matrix.")
    if any(row[index] <= 0 for index, row in enumerate(matrix)):
        raise ExperimentArtifactError(f"{field} must have strictly positive diagonal values.")
    return matrix


def _finite_float(value: object, field: str) -> float:
    if not isinstance(value, int | float) or isinstance(value, bool) or not math.isfinite(value):
        raise ExperimentArtifactError(f"{field} must be finite numeric data.")
    return float(value)


def load_multi_round_correlation_data(run_directory: str | Path):
    """Load input correlations and, when available, the persisted first-round graph.

    Accepts runs from both legacy (synthetic-portfolio-multi-round) and unified
    (synthetic-portfolio) experiment IDs. For unified experiments, only multi-round
    runs (max_reduction_rounds > 1) are accepted.

    Args:
        run_directory: Path to the experiment run directory.

    Returns:
        Tuple of (asset_ids, correlation_matrix, graph_or_none).

    Raises:
        ExperimentArtifactError: If the artifact is not a multi-round portfolio
            experiment, or if a unified run has max_reduction_rounds <= 1.
    """
    artifacts = load_experiment_run(run_directory)
    experiment_id = artifacts.manifest["experiment_id"]
    if experiment_id not in _MULTI_ROUND_COMPATIBLE_IDS:
        raise ExperimentArtifactError("Artifact directory is not a multi-round portfolio experiment.")

    # For unified experiment ID, verify this is actually a multi-round configuration
    if experiment_id == UNIFIED_EXPERIMENT_ID:
        max_rounds = artifacts.config.get("reduction", {}).get("max_reduction_rounds", 1)
        if max_rounds <= 1:
            raise ExperimentArtifactError(
                f"This loader requires a multi-round configuration (max_reduction_rounds > 1), "
                f"but the loaded run has max_reduction_rounds={max_rounds}. "
                f"Use load_synthetic_portfolio_analysis for single-pass runs."
            )

    problem = _require_mapping(artifacts.problem, "problem.json")
    asset_ids = _string_tuple(problem.get("asset_ids"), "problem.asset_ids")
    covariance = _numeric_matrix(problem.get("covariance"), len(asset_ids), "problem.covariance")
    graph = None
    if artifacts.round_results:
        compilation = artifacts.round_results[0].get("mis_compilation_result") or {}
        job = compilation.get("compiled_job") or {}
        compiled = job.get("compiled_problem") or {}
        graph_data = compiled.get("graph")
        if graph_data is not None:
            nodes = _string_tuple(graph_data.get("node_ids"), "graph.node_ids")
            if nodes != asset_ids:
                raise ExperimentArtifactError("First-round graph order does not match the portfolio.")
            edges = tuple(tuple(edge) for edge in graph_data["edges"])
            graph = ReductionGraph(
                node_ids=nodes,
                node_weights=graph_data["node_weights"],
                edges=edges,
                edge_reasons={edge: "persisted first-round edge" for edge in edges},
                graph_policy_id=graph_data["graph_policy_id"],
                graph_policy_version=graph_data["graph_policy_version"],
            )
    return asset_ids, _correlation_matrix(covariance), graph

