"""Synthetic portfolio single-pass experiment and CLI."""

import argparse
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from qreduce.experiments.portfolio.inputs import (
    DEFAULT_PORTFOLIO_OUTPUT_ROOT,
    SYNTHETIC_PORTFOLIO_EXPERIMENT_ID,
    build_synthetic_portfolio_inputs,
    default_graph_policy,
)
from qreduce.experiments.portfolio.models import PortfolioGraphPolicy
from qreduce.experiments.runner import ExperimentRun, run_experiment

if TYPE_CHECKING:
    from qreduce.experiments.portfolio.models import SyntheticPortfolioGenerationPolicy

def run_synthetic_portfolio_experiment(
    run_id: str,
    *,
    output_root: str | Path = DEFAULT_PORTFOLIO_OUTPUT_ROOT,
    asset_count: int = 30,
    generation_policy: "SyntheticPortfolioGenerationPolicy | None" = None,
    graph_policy: PortfolioGraphPolicy | None = None,
    mis_solver_id: str = "local_greedy",
    classical_solver_id: str = "scip",
    mis_num_reads: int | None = None,
    mis_num_sweeps: int | None = None,
    model_export_enabled: bool = False,
    model_export_path: str | None = None,
) -> ExperimentRun:
    """Run and persist the deterministic synthetic portfolio experiment.

    Args:
        run_id: Unique identifier for the run.
        output_root: Root directory for experiment artifacts.
        asset_count: Number of assets in the synthetic portfolio. Must be >= 6.
            Default is 30 for meaningful reduction experiments.
        generation_policy: Optional generation policy. If None, uses default.
        graph_policy: Optional graph policy. If None, uses near_duplicate default.
        mis_solver_id: MIS solver to use.
        classical_solver_id: Classical solver to use.
        mis_num_reads: Optional D-Wave num_reads parameter.
        mis_num_sweeps: Optional D-Wave num_sweeps parameter.
        model_export_enabled: Whether to export the residual model.
        model_export_path: Optional path for model export.

    Returns:
        ExperimentRun with the run directory and result.
    """
    inputs = build_synthetic_portfolio_inputs(
        run_id,
        asset_count=asset_count,
        generation_policy=generation_policy,
        graph_policy=graph_policy,
        mis_solver_id=mis_solver_id,
        classical_solver_id=classical_solver_id,
        mis_num_reads=mis_num_reads,
        mis_num_sweeps=mis_num_sweeps,
    )
    experiment_metadata: dict[str, object] = {
        "portfolio_graph_policy": inputs.graph_policy,
    }
    if inputs.generation_policy is not None:
        experiment_metadata["generation_policy"] = inputs.generation_policy

    return run_experiment(
        SYNTHETIC_PORTFOLIO_EXPERIMENT_ID,
        inputs.problem,
        inputs.adapter,
        replace(inputs.config, classical_solve=replace(
            inputs.config.classical_solve,
            model_export_enabled=model_export_enabled,
            model_export_path=model_export_path,
        )),
        output_root=output_root,
        experiment_metadata=experiment_metadata,
    )


def _main() -> None:
    parser = argparse.ArgumentParser(description="Run the synthetic portfolio QReduce experiment.")
    parser.add_argument("--run-id", required=True, help="Unique run identifier used under the experiment output directory.")
    parser.add_argument("--output-root", default=DEFAULT_PORTFOLIO_OUTPUT_ROOT, help="Root directory for repository experiment artifacts.")
    parser.add_argument("--model-export", action="store_true", help="Export the residual model.")
    parser.add_argument("--model-export-path", help="Optional .lp or .mps export file path.")
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
    parser.add_argument(
        "--asset-count",
        type=int,
        default=30,
        help="Number of assets in the synthetic portfolio. Must be >= 6. Default: 30.",
    )
    # Graph edge mode options
    parser.add_argument(
        "--graph-edge-mode",
        choices=("correlation_only", "near_duplicate"),
        default="near_duplicate",
        help="Graph edge semantics: correlation_only or near_duplicate. Default: near_duplicate.",
    )
    parser.add_argument(
        "--correlation-threshold",
        type=float,
        default=0.90,
        help="Absolute correlation threshold for edges. Default: 0.90.",
    )
    parser.add_argument(
        "--near-duplicate-max-relative-return-difference",
        type=float,
        default=0.10,
        help="Max relative return difference for near_duplicate edges. Default: 0.10.",
    )
    parser.add_argument(
        "--near-duplicate-max-relative-variance-difference",
        type=float,
        default=0.10,
        help="Max relative variance difference for near_duplicate edges. Default: 0.10.",
    )
    # Generation policy options
    parser.add_argument(
        "--generation-seed",
        type=int,
        default=42,
        help="Random seed for generation policy. Default: 42.",
    )
    parser.add_argument(
        "--observation-count",
        type=int,
        help="Number of historical observations. Default: 10 * asset_count.",
    )
    arguments = parser.parse_args()
    if arguments.model_export_path and not arguments.model_export:
        parser.error("--model-export-path requires --model-export")
    if arguments.asset_count < 6:
        parser.error("--asset-count must be at least 6")

    # Build generation policy
    from qreduce.experiments.portfolio.generator import default_generation_policy
    generation_policy = default_generation_policy(
        arguments.asset_count,
        random_seed=arguments.generation_seed,
        observation_count=arguments.observation_count,
    )

    # Build graph policy
    graph_policy = default_graph_policy(
        edge_mode=arguments.graph_edge_mode,
        correlation_threshold=arguments.correlation_threshold,
        near_duplicate_max_relative_return_difference=arguments.near_duplicate_max_relative_return_difference,
        near_duplicate_max_relative_variance_difference=arguments.near_duplicate_max_relative_variance_difference,
    )

    run = run_synthetic_portfolio_experiment(
        arguments.run_id,
        output_root=arguments.output_root,
        asset_count=arguments.asset_count,
        generation_policy=generation_policy,
        graph_policy=graph_policy,
        mis_solver_id=arguments.mis_solver_id,
        classical_solver_id=arguments.classical_solver_id,
        mis_num_reads=arguments.mis_num_reads,
        mis_num_sweeps=arguments.mis_num_sweeps,
        model_export_enabled=arguments.model_export,
        model_export_path=arguments.model_export_path,
    )
    print(run.run_directory)


if __name__ == "__main__":
    _main()