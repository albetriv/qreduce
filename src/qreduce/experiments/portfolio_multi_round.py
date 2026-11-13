"""Larger deterministic portfolio experiment using the multi-round runner."""

import argparse
from dataclasses import replace
from pathlib import Path

from qreduce.experiments.artifacts import ExperimentArtifactError, load_experiment_run
from qreduce.experiments.portfolio import (
    _correlation_matrix,
    _numeric_matrix,
    _require_mapping,
    _string_tuple,
    build_synthetic_portfolio_inputs,
)
from qreduce.experiments.portfolio_domain import PortfolioProblem
from qreduce.experiments.runner import ExperimentRun, run_experiment
from qreduce.mwis import ReductionGraph


def load_multi_round_correlation_data(run_directory: str | Path):
    """Load input correlations and, when available, the persisted first-round graph."""
    artifacts = load_experiment_run(run_directory)
    if artifacts.manifest["experiment_id"] != "synthetic-portfolio-multi-round":
        raise ExperimentArtifactError("Artifact directory is not a multi-round portfolio experiment.")
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


def run_portfolio_multi_round_experiment(
    run_id: str, *, output_root: str | Path = "outputs", asset_count: int = 30
) -> ExperimentRun:
    """Publish a reproducible larger portfolio run with at most three rounds."""
    if isinstance(asset_count, bool) or not isinstance(asset_count, int) or asset_count < 6:
        raise ValueError("asset_count must be an integer greater than or equal to 6.")
    inputs = build_synthetic_portfolio_inputs(run_id)
    asset_ids = tuple(f"asset-{index:03d}" for index in range(asset_count))
    # Independent blocks have a positive definite equicorrelation covariance.
    covariance = tuple(
        tuple(0.04 if i == j else 0.016 if i // 3 == j // 3 else 0.0
              for j in range(asset_count))
        for i in range(asset_count)
    )
    problem = PortfolioProblem(
        asset_ids=asset_ids,
        expected_returns={asset: 0.05 + 0.002 * (i % 20) for i, asset in enumerate(asset_ids)},
        covariance=covariance,
        lower_bounds={asset: 0.0 for asset in asset_ids},
        upper_bounds={asset: 0.7 for asset in asset_ids},
        retention_scores={asset: 1.0 - 0.005 * (i % 100) for i, asset in enumerate(asset_ids)},
        risk_aversion=1.0,
    )
    config = replace(
        inputs.config,
        reduction=replace(
            inputs.config.reduction,
            max_reduction_rounds=3,
            candidate_domain_max_items=asset_count,
            target_binary_variables=0,
        ),
    )
    return run_experiment(
        "synthetic-portfolio-multi-round", problem, inputs.adapter, config,
        output_root=output_root,
    )


def _main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output-root", default="outputs")
    parser.add_argument("--asset-count", type=int, default=30)
    args = parser.parse_args()
    run = run_portfolio_multi_round_experiment(
        args.run_id, output_root=args.output_root, asset_count=args.asset_count
    )
    print(run.run_directory)


if __name__ == "__main__":
    _main()