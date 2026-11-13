"""Classical-only baseline for the larger deterministic portfolio experiment."""

import argparse
from dataclasses import replace
from pathlib import Path

from qreduce.experiments.portfolio import build_synthetic_portfolio_inputs
from qreduce.experiments.portfolio_generator import generate_portfolio_data
from qreduce.experiments.runner import ExperimentRun, run_experiment


def run_portfolio_classical_experiment(
    run_id: str, *, output_root: str | Path = "outputs", asset_count: int = 30
) -> ExperimentRun:
    """Publish the multi-round portfolio solved by SCIP without reduction."""
    if isinstance(asset_count, bool) or not isinstance(asset_count, int) or asset_count < 6:
        raise ValueError("asset_count must be an integer greater than or equal to 6.")

    problem = generate_portfolio_data(asset_count).to_problem()
    inputs = build_synthetic_portfolio_inputs(run_id)
    config = replace(
        inputs.config,
        reduction=replace(
            inputs.config.reduction,
            max_reduction_rounds=0,
            candidate_domain_max_items=asset_count,
            target_binary_variables=0,
        ),
    )
    return run_experiment(
        "synthetic-portfolio-classical", problem, inputs.adapter, config,
        output_root=output_root,
    )


def _main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output-root", default="outputs")
    parser.add_argument("--asset-count", type=int, default=30)
    args = parser.parse_args()
    run = run_portfolio_classical_experiment(
        args.run_id, output_root=args.output_root, asset_count=args.asset_count
    )
    print(run.run_directory)


if __name__ == "__main__":
    _main()