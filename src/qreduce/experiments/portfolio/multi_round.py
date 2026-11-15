"""Larger deterministic portfolio experiment using the multi-round runner."""

import argparse
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from qreduce.experiments.portfolio.inputs import (
    DEFAULT_PORTFOLIO_OUTPUT_ROOT,
    build_synthetic_portfolio_inputs,
    default_graph_policy,
)
from qreduce.experiments.portfolio.models import PortfolioGraphPolicy
from qreduce.experiments.runner import ExperimentRun, run_experiment

if TYPE_CHECKING:
    from qreduce.experiments.portfolio.models import (
        SyntheticPortfolioGenerationPolicy,
    )


def run_portfolio_multi_round_experiment(
    run_id: str,
    *,
    output_root: str | Path = DEFAULT_PORTFOLIO_OUTPUT_ROOT,
    asset_count: int = 30,
    generation_policy: "SyntheticPortfolioGenerationPolicy | None" = None,
    graph_policy: PortfolioGraphPolicy | None = None,
) -> ExperimentRun:
    """Publish a reproducible larger portfolio run with at most three rounds.

    Args:
        run_id: Unique identifier for the run.
        output_root: Root directory for experiment artifacts.
        asset_count: Number of assets. Must be >= 6.
        generation_policy: Optional generation policy. If None, uses default.
        graph_policy: Optional graph policy. If None, uses near_duplicate default.

    Returns:
        ExperimentRun with the run directory and result.
    """
    if isinstance(asset_count, bool) or not isinstance(asset_count, int) or asset_count < 6:
        raise ValueError("asset_count must be an integer greater than or equal to 6.")

    # Use the shared inputs builder
    if graph_policy is None:
        graph_policy = default_graph_policy()

    inputs = build_synthetic_portfolio_inputs(
        run_id,
        asset_count=asset_count,
        generation_policy=generation_policy,
        graph_policy=graph_policy,
    )

    # Override config for multi-round
    config = replace(
        inputs.config,
        reduction=replace(
            inputs.config.reduction,
            max_reduction_rounds=3,
            candidate_domain_max_items=asset_count,
            target_binary_variables=0,
        ),
    )

    experiment_metadata: dict[str, object] = {
        "portfolio_graph_policy": inputs.graph_policy,
    }
    if inputs.generation_policy is not None:
        experiment_metadata["generation_policy"] = inputs.generation_policy

    return run_experiment(
        "synthetic-portfolio-multi-round",
        inputs.problem,
        inputs.adapter,
        config,
        output_root=output_root,
        experiment_metadata=experiment_metadata,
    )


def _main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output-root", default=DEFAULT_PORTFOLIO_OUTPUT_ROOT)
    parser.add_argument("--asset-count", type=int, default=30)
    # Graph edge mode options
    parser.add_argument(
        "--graph-edge-mode",
        choices=("correlation_only", "near_duplicate"),
        default="near_duplicate",
        help="Graph edge semantics. Default: near_duplicate.",
    )
    parser.add_argument("--correlation-threshold", type=float, default=0.90)
    parser.add_argument("--near-duplicate-max-relative-return-difference", type=float, default=0.10)
    parser.add_argument("--near-duplicate-max-relative-variance-difference", type=float, default=0.10)
    # Generation policy options
    parser.add_argument("--generation-seed", type=int, default=42)
    parser.add_argument("--observation-count", type=int)
    args = parser.parse_args()

    if args.asset_count < 6:
        parser.error("--asset-count must be at least 6")

    # Build generation policy
    from qreduce.experiments.portfolio.generator import default_generation_policy
    generation_policy = default_generation_policy(
        args.asset_count,
        random_seed=args.generation_seed,
        observation_count=args.observation_count,
    )

    # Build graph policy
    graph_policy = default_graph_policy(
        edge_mode=args.graph_edge_mode,
        correlation_threshold=args.correlation_threshold,
        near_duplicate_max_relative_return_difference=args.near_duplicate_max_relative_return_difference,
        near_duplicate_max_relative_variance_difference=args.near_duplicate_max_relative_variance_difference,
    )

    run = run_portfolio_multi_round_experiment(
        args.run_id,
        output_root=args.output_root,
        asset_count=args.asset_count,
        generation_policy=generation_policy,
        graph_policy=graph_policy,
    )
    print(run.run_directory)


if __name__ == "__main__":
    _main()
