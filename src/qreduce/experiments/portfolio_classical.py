"""Classical-only baseline for the larger deterministic portfolio experiment."""

import argparse
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from qreduce.experiments.portfolio import (
    build_synthetic_portfolio_inputs,
    default_graph_policy,
)
from qreduce.experiments.runner import ExperimentRun, run_experiment

if TYPE_CHECKING:
    from qreduce.experiments.portfolio_domain.models import (
        SyntheticPortfolioGenerationPolicy,
    )


def run_portfolio_classical_experiment(
    run_id: str,
    *,
    output_root: str | Path = "outputs",
    asset_count: int = 30,
    generation_policy: "SyntheticPortfolioGenerationPolicy | None" = None,
) -> ExperimentRun:
    """Publish the portfolio solved by SCIP without reduction (classical baseline).

    Uses the same generation policy as the reduced experiments to ensure
    identical problem instances for fair comparison.

    Args:
        run_id: Unique identifier for the run.
        output_root: Root directory for experiment artifacts.
        asset_count: Number of assets. Must be >= 6.
        generation_policy: Optional generation policy. If None, uses default.

    Returns:
        ExperimentRun with the run directory and result.
    """
    if isinstance(asset_count, bool) or not isinstance(asset_count, int) or asset_count < 6:
        raise ValueError("asset_count must be an integer greater than or equal to 6.")

    # Use the shared inputs builder - it handles generation policy
    # For classical baseline, we don't need a real graph policy but include one for metadata
    graph_policy = default_graph_policy()  # Not used, but included for consistency

    inputs = build_synthetic_portfolio_inputs(
        run_id,
        asset_count=asset_count,
        generation_policy=generation_policy,
        graph_policy=graph_policy,
    )

    # Override config for classical-only (no reduction)
    config = replace(
        inputs.config,
        reduction=replace(
            inputs.config.reduction,
            max_reduction_rounds=0,
            candidate_domain_max_items=asset_count,
            target_binary_variables=0,
        ),
    )

    experiment_metadata: dict[str, object] = {
        "portfolio_graph_policy": inputs.graph_policy,
        "baseline_mode": "classical_only",
    }
    if inputs.generation_policy is not None:
        experiment_metadata["generation_policy"] = inputs.generation_policy

    return run_experiment(
        "synthetic-portfolio-classical",
        inputs.problem,
        inputs.adapter,
        config,
        output_root=output_root,
        experiment_metadata=experiment_metadata,
    )


def _main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output-root", default="outputs")
    parser.add_argument("--asset-count", type=int, default=30)
    parser.add_argument("--generation-seed", type=int, default=42, help="Random seed for generation.")
    parser.add_argument("--observation-count", type=int, help="Number of historical observations.")
    args = parser.parse_args()

    if args.asset_count < 6:
        parser.error("--asset-count must be at least 6")

    # Build generation policy to match reduced experiments
    from qreduce.experiments.portfolio_generator import default_generation_policy
    generation_policy = default_generation_policy(
        args.asset_count,
        random_seed=args.generation_seed,
        observation_count=args.observation_count,
    )

    run = run_portfolio_classical_experiment(
        args.run_id,
        output_root=args.output_root,
        asset_count=args.asset_count,
        generation_policy=generation_policy,
    )
    print(run.run_directory)


if __name__ == "__main__":
    _main()
