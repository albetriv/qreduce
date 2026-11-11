"""Synthetic portfolio experiment factory, runner and filesystem-backed analysis data."""

import argparse
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from qreduce.experiments.artifacts import (
    ExperimentArtifactError,
    ExperimentRunArtifacts,
    load_experiment_run,
)
from qreduce.experiments.portfolio_domain import (
    MeanVariancePortfolioAdapter,
    PortfolioGraphPolicy,
    PortfolioProblem,
)
from qreduce.experiments.runner import ExperimentRun, run_experiment
from qreduce.models import (
    ClassicalSolveOptions,
    LambdaEdgePolicy,
    MISExecutionOptions,
    ReductionPolicy,
    ResolvedRunConfig,
    RunIdentity,
)
from qreduce.mwis import ReductionGraph
from qreduce.status import PostcheckMode

SYNTHETIC_PORTFOLIO_EXPERIMENT_ID = "synthetic-portfolio-single-pass"


@dataclass(frozen=True, slots=True)
class SyntheticPortfolioInputs:
    """All domain and kernel inputs for the repository's synthetic portfolio experiment."""

    problem: PortfolioProblem
    graph_policy: PortfolioGraphPolicy
    adapter: MeanVariancePortfolioAdapter
    config: ResolvedRunConfig


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


def build_synthetic_portfolio_inputs(
    run_id: str,
    *,
    mis_solver_id: str = "local_greedy",
    classical_solver_id: str = "scip",
    mis_num_reads: int | None = None,
    mis_num_sweeps: int | None = None,
) -> SyntheticPortfolioInputs:
    """Build deterministic inputs with explicit optional solver selections."""

    asset_ids = ("asset-a", "asset-b", "asset-c", "asset-d", "asset-e")
    problem = PortfolioProblem(
        asset_ids=asset_ids,
        expected_returns={
            "asset-a": 0.10,
            "asset-b": 0.08,
            "asset-c": 0.06,
            "asset-d": 0.07,
            "asset-e": 0.05,
        },
        covariance=(
            (0.04, 0.016, 0.0, 0.0, 0.004),
            (0.016, 0.04, -0.012, 0.0, 0.0),
            (0.0, -0.012, 0.04, 0.014, 0.0),
            (0.0, 0.0, 0.014, 0.04, 0.012),
            (0.004, 0.0, 0.0, 0.012, 0.04),
        ),
        lower_bounds={asset_id: 0.0 for asset_id in asset_ids},
        upper_bounds={asset_id: 0.7 for asset_id in asset_ids},
        retention_scores={
            "asset-a": 0.9,
            "asset-b": 0.7,
            "asset-c": 0.8,
            "asset-d": 0.6,
            "asset-e": 0.5,
        },
        risk_aversion=1.0,
    )
    graph_policy = PortfolioGraphPolicy("synthetic-portfolio-policy", "1", 0.25)
    config = ResolvedRunConfig(
        schema_version="1.0",
        reduction=ReductionPolicy(1, 1, 3, 1, 0.1, 3, 60.0),
        lambda_edge=2.0,
        lambda_edge_policy=LambdaEdgePolicy("standard", "1", 2.0),
        allow_noncertifying_penalty=False,
        mis_solver_id=mis_solver_id,
        mis_execution=MISExecutionOptions(1, 17, 1, False, 0, 0.0, 20),
        classical_solve=ClassicalSolveOptions(
            classical_solver_id=classical_solver_id,
            time_limit_seconds=10.0,
            mip_gap_tolerance=None,
            threads=1,
            model_export_enabled=False,
            primal_feasibility_tolerance=1e-6,
            integrality_tolerance=1e-6,
            objective_recomputation_absolute_tolerance=1e-6,
            objective_recomputation_relative_tolerance=1e-6,
            postcheck_mode=PostcheckMode.STRICT,
            random_seed=7,
        ),
        run_identity=RunIdentity(run_id),
    )
    if mis_num_reads is not None or mis_num_sweeps is not None:
        if mis_solver_id != "dwave_simulated_annealing":
            raise ValueError(
                "mis_num_reads and mis_num_sweeps require "
                "mis_solver_id='dwave_simulated_annealing'."
            )
        provider_parameters: dict[str, object] = {}
        if mis_num_reads is not None:
            _require_positive_int(mis_num_reads, "mis_num_reads")
            provider_parameters["num_reads"] = mis_num_reads
        if mis_num_sweeps is not None:
            _require_positive_int(mis_num_sweeps, "mis_num_sweeps")
            provider_parameters["num_sweeps"] = mis_num_sweeps
        config = replace(
            config,
            mis_execution=replace(
                config.mis_execution,
                provider_parameters=provider_parameters,
            ),
        )
    return SyntheticPortfolioInputs(
        problem=problem,
        graph_policy=graph_policy,
        adapter=MeanVariancePortfolioAdapter(graph_policy),
        config=config,
    )


def run_synthetic_portfolio_experiment(
    run_id: str,
    *,
    output_root: str | Path = "outputs",
    mis_solver_id: str = "local_greedy",
    classical_solver_id: str = "scip",
    mis_num_reads: int | None = None,
    mis_num_sweeps: int | None = None,
) -> ExperimentRun:
    """Run and persist the deterministic synthetic portfolio experiment."""

    inputs = build_synthetic_portfolio_inputs(
        run_id,
        mis_solver_id=mis_solver_id,
        classical_solver_id=classical_solver_id,
        mis_num_reads=mis_num_reads,
        mis_num_sweeps=mis_num_sweeps,
    )
    return run_experiment(
        SYNTHETIC_PORTFOLIO_EXPERIMENT_ID,
        inputs.problem,
        inputs.adapter,
        inputs.config,
        output_root=output_root,
        experiment_metadata={"portfolio_graph_policy": inputs.graph_policy},
    )


def load_synthetic_portfolio_analysis(
    run_directory: str | Path,
) -> SyntheticPortfolioAnalysis:
    """Load and validate presentation data for the synthetic portfolio experiment."""

    artifacts = load_experiment_run(run_directory)
    if artifacts.manifest["experiment_id"] != SYNTHETIC_PORTFOLIO_EXPERIMENT_ID:
        raise ExperimentArtifactError(
            "Artifact directory does not contain the synthetic portfolio experiment."
        )
    graph_data = artifacts.canonical_mwis_problem
    if graph_data is None:
        raise ExperimentArtifactError(
            "Synthetic portfolio analysis requires canonical_mwis_problem.json."
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
    for record in _require_sequence(graph_data.get("edge_reasons"), "graph.edge_reasons"):
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


def _require_positive_int(value: int, field: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{field} must be an integer greater than zero.")


def _main() -> None:
    parser = argparse.ArgumentParser(description="Run the synthetic portfolio QReduce experiment.")
    parser.add_argument("--run-id", required=True, help="Unique run identifier used under the experiment output directory.")
    parser.add_argument("--output-root", default="outputs", help="Root directory for repository experiment artifacts.")
    parser.add_argument(
        "--mis-solver-id",
        choices=("local_greedy", "dwave_simulated_annealing"),
        default="local_greedy",
        help="Built-in MIS solver ID.",
    )
    parser.add_argument(
        "--classical-solver-id",
        choices=("cplex", "scip"),
        default="scip",
        help="Built-in residual classical solver ID.",
    )
    parser.add_argument(
        "--mis-num-reads",
        type=int,
        help="Optional D-Wave simulated-annealing num_reads parameter.",
    )
    parser.add_argument(
        "--mis-num-sweeps",
        type=int,
        help="Optional D-Wave simulated-annealing num_sweeps parameter.",
    )
    arguments = parser.parse_args()
    run = run_synthetic_portfolio_experiment(
        arguments.run_id,
        output_root=arguments.output_root,
        mis_solver_id=arguments.mis_solver_id,
        classical_solver_id=arguments.classical_solver_id,
        mis_num_reads=arguments.mis_num_reads,
        mis_num_sweeps=arguments.mis_num_sweeps,
    )
    print(run.run_directory)


if __name__ == "__main__":
    _main()