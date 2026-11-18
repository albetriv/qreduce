"""Unified CLI for synthetic portfolio experiments.

Usage:
    poetry run python -m qreduce.experiments.portfolio --run-id <id> [options]

The execution mode is controlled by --max-reduction-rounds:
    0: Classical-only baseline (no MIS, no reduction)
    1: Single reduction round (default)
   >1: Iterative reduction with optional recovery
"""

import argparse
import sys
from dataclasses import replace

from qreduce.config import validate_timeout_value
from qreduce.experiments.portfolio.execution import (
    DEFAULT_PORTFOLIO_OUTPUT_ROOT,
    run_portfolio_experiment,
)
from qreduce.experiments.portfolio.generator import default_generation_policy
from qreduce.experiments.portfolio.inputs import (
    default_graph_policy,
    default_reduction_policy,
)
from qreduce.logging_config import (
    LoggingConfigError,
    configure_logging,
    get_default_config_path,
)
from qreduce.models import ReductionPolicy

# Valid recovery policy values from the configuration validator
_VALID_RECOVERY_POLICIES = ("fail", "retry_with_larger_domain")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a synthetic portfolio QReduce experiment.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Single-pass (default)
  python -m qreduce.experiments.portfolio --run-id run001

  # Classical-only baseline
  python -m qreduce.experiments.portfolio --run-id baseline001 --max-reduction-rounds 0

  # Multi-round with 3 rounds
  python -m qreduce.experiments.portfolio --run-id multi001 --max-reduction-rounds 3

  # Multi-round with recovery on infeasibility
  python -m qreduce.experiments.portfolio --run-id recovery001 \\
      --max-reduction-rounds 3 \\
      --recovery-policy-on-infeasible retry_with_larger_domain \\
      --max-recovery-attempts 2

  # With positive minimum investment and cardinality constraints
  python -m qreduce.experiments.portfolio --run-id cardinality001 \\
      --lower-bound 0.05 --upper-bound 0.30 \\
      --min-selected-assets 5 --max-selected-assets 10

  # Exact cardinality (select exactly 8 assets)
  python -m qreduce.experiments.portfolio --run-id exact001 \\
      --min-selected-assets 8 --max-selected-assets 8
""",
    )

    # Required arguments
    parser.add_argument(
        "--run-id",
        required=True,
        help="Unique run identifier used under the experiment output directory.",
    )

    # Logging configuration
    parser.add_argument(
        "--log-config",
        metavar="PATH",
        help="Path to YAML logging configuration file. "
        "Overrides QREDUCE_LOG_CONFIG environment variable. "
        "If not specified and env var is unset, uses repository default if available.",
    )

    # Output and export
    parser.add_argument(
        "--output-root",
        default=DEFAULT_PORTFOLIO_OUTPUT_ROOT,
        help=f"Root directory for experiment artifacts. Default: {DEFAULT_PORTFOLIO_OUTPUT_ROOT}",
    )
    parser.add_argument(
        "--model-export",
        action="store_true",
        help="Export the residual model.",
    )
    parser.add_argument(
        "--model-export-path",
        help="Optional .lp or .mps export file path.",
    )

    # Generation options
    gen_group = parser.add_argument_group("Generation options")
    gen_group.add_argument(
        "--asset-count",
        type=int,
        default=30,
        help="Number of assets in the synthetic portfolio. Must be >= 6. Default: 30.",
    )
    gen_group.add_argument(
        "--generation-seed",
        type=int,
        default=42,
        help="Random seed for generation policy. Default: 42.",
    )
    gen_group.add_argument(
        "--observation-count",
        type=int,
        help="Number of historical observations. Default: 10 * asset_count.",
    )

    # Investment bounds and cardinality options
    bounds_group = parser.add_argument_group("Investment bounds and cardinality options")
    bounds_group.add_argument(
        "--lower-bound",
        type=float,
        default=0.0,
        help="Minimum investment per selected asset (conditional on delta=1). Default: 0.0.",
    )
    bounds_group.add_argument(
        "--upper-bound",
        type=float,
        default=0.7,
        help="Maximum investment per selected asset (conditional on delta=1). Default: 0.7.",
    )
    bounds_group.add_argument(
        "--min-selected-assets",
        type=int,
        help="Minimum number of assets to select (cardinality constraint). Optional.",
    )
    bounds_group.add_argument(
        "--max-selected-assets",
        type=int,
        help="Maximum number of assets to select (cardinality constraint). Optional.",
    )

    # Graph options
    graph_group = parser.add_argument_group("Graph options")
    graph_group.add_argument(
        "--graph-edge-mode",
        choices=("correlation_only", "near_duplicate"),
        default="near_duplicate",
        help="Graph edge semantics. Default: near_duplicate.",
    )
    graph_group.add_argument(
        "--correlation-threshold",
        type=float,
        default=0.90,
        help="Absolute correlation threshold for edges. Default: 0.90.",
    )
    graph_group.add_argument(
        "--near-duplicate-max-relative-return-difference",
        type=float,
        default=0.10,
        help="Max relative return difference for near_duplicate edges. Default: 0.10.",
    )
    graph_group.add_argument(
        "--near-duplicate-max-relative-variance-difference",
        type=float,
        default=0.10,
        help="Max relative variance difference for near_duplicate edges. Default: 0.10.",
    )

    # Solver options
    solver_group = parser.add_argument_group("Solver options")
    solver_group.add_argument(
        "--mis-solver-id",
        choices=("local_greedy", "dwave_simulated_annealing"),
        default="local_greedy",
        help="MIS solver ID. Default: local_greedy.",
    )
    solver_group.add_argument(
        "--classical-solver-id",
        choices=("cplex", "scip"),
        default="scip",
        help="Classical solver ID. Default: scip.",
    )
    solver_group.add_argument(
        "--classical-time-limit-seconds",
        type=float,
        help="Maximum time per classical solve invocation in seconds. "
        "A value of 0 means no per-solve limit (solver runs until completion "
        "or end-to-end budget exhaustion). Default: 60.0.",
    )
    solver_group.add_argument(
        "--mis-num-reads",
        type=int,
        help="D-Wave simulated-annealing num_reads parameter.",
    )
    solver_group.add_argument(
        "--mis-num-sweeps",
        type=int,
        help="D-Wave simulated-annealing num_sweeps parameter.",
    )
    solver_group.add_argument(
        "--mis-embedding-profile",
        choices=("none", "pegasus_p16", "zephyr_z12"),
        default=None,
        help=(
            "Local embedding profile for D-Wave simulated annealing. "
            "Constrains sampling to hardware-like topology without QPU access. "
            "none = direct logical BQM sampling (default), "
            "pegasus_p16 = Pegasus m=16 topology, "
            "zephyr_z12 = Zephyr m=12 topology. "
            "Requires --mis-solver-id=dwave_simulated_annealing and reduction active."
        ),
    )

    # Reduction policy options
    reduction_group = parser.add_argument_group("Reduction policy options")
    reduction_group.add_argument(
        "--max-reduction-rounds",
        type=int,
        help="Maximum reduction rounds: 0=baseline, 1=single-pass (default), >1=multi-round.",
    )
    reduction_group.add_argument(
        "--candidate-domain-min-items",
        type=int,
        help="Minimum items in candidate domain. Default: 1.",
    )
    reduction_group.add_argument(
        "--candidate-domain-max-items",
        type=int,
        help="Maximum items in candidate domain. Default: 60%% of asset_count.",
    )
    reduction_group.add_argument(
        "--num-source-mis-candidates",
        type=int,
        help="Number of MIS candidates. Default: 1.",
    )
    reduction_group.add_argument(
        "--min-reduction-ratio",
        type=float,
        help="Minimum reduction ratio. Default: 0.1.",
    )
    reduction_group.add_argument(
        "--target-binary-variables",
        type=int,
        help="Target binary variables. Default: 3.",
    )
    reduction_group.add_argument(
        "--max-end-to-end-runtime-seconds",
        type=float,
        help="Maximum end-to-end runtime in seconds. A value of 0 means no "
        "global time limit. Default: 60.0.",
    )
    reduction_group.add_argument(
        "--recovery-policy-on-domain-too-small",
        choices=_VALID_RECOVERY_POLICIES,
        help="Recovery policy when domain is too small. Default: fail.",
    )
    reduction_group.add_argument(
        "--recovery-policy-on-infeasible",
        choices=_VALID_RECOVERY_POLICIES,
        help="Recovery policy when problem is infeasible. Default: fail.",
    )
    reduction_group.add_argument(
        "--max-recovery-attempts",
        type=int,
        help="Maximum recovery attempts. Default: 0.",
    )

    return parser


def _validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    """Validate argument combinations."""
    if args.model_export_path and not args.model_export:
        parser.error("--model-export-path requires --model-export")

    if args.asset_count < 6:
        parser.error("--asset-count must be at least 6")

    if args.max_reduction_rounds is not None and args.max_reduction_rounds < 0:
        parser.error("--max-reduction-rounds must be non-negative")

    # D-Wave parameters require D-Wave solver
    if (args.mis_num_reads is not None or args.mis_num_sweeps is not None) and args.mis_solver_id != "dwave_simulated_annealing":
        parser.error("--mis-num-reads and --mis-num-sweeps require --mis-solver-id=dwave_simulated_annealing")

    # Embedding profile validation
    if args.mis_embedding_profile is not None and args.mis_embedding_profile != "none":
        if args.mis_solver_id != "dwave_simulated_annealing":
            parser.error(
                f"--mis-embedding-profile={args.mis_embedding_profile} requires "
                "--mis-solver-id=dwave_simulated_annealing"
            )
        if args.max_reduction_rounds is not None and args.max_reduction_rounds == 0:
            parser.error(
                f"--mis-embedding-profile={args.mis_embedding_profile} requires "
                "reduction to be enabled (--max-reduction-rounds > 0)"
            )

    # Time limit validation - reject booleans, NaN, infinity
    if args.classical_time_limit_seconds is not None:
        error = validate_timeout_value(args.classical_time_limit_seconds, "--classical-time-limit-seconds")
        if error:
            parser.error(error)

    if args.max_end_to_end_runtime_seconds is not None:
        error = validate_timeout_value(args.max_end_to_end_runtime_seconds, "--max-end-to-end-runtime-seconds")
        if error:
            parser.error(error)

    # Investment bounds validation
    if args.lower_bound < 0:
        parser.error("--lower-bound must be non-negative")
    if args.upper_bound < args.lower_bound:
        parser.error("--upper-bound must be at least equal to --lower-bound")

    # Cardinality validation
    if args.min_selected_assets is not None:
        if args.min_selected_assets < 0:
            parser.error("--min-selected-assets must be non-negative")
        if args.min_selected_assets > args.asset_count:
            parser.error("--min-selected-assets cannot exceed --asset-count")

    if args.max_selected_assets is not None:
        if args.max_selected_assets < 1:
            parser.error("--max-selected-assets must be at least 1")
        if args.max_selected_assets > args.asset_count:
            parser.error("--max-selected-assets cannot exceed --asset-count")

    if args.min_selected_assets is not None and args.max_selected_assets is not None and args.min_selected_assets > args.max_selected_assets:
        parser.error("--min-selected-assets cannot exceed --max-selected-assets")


def _build_reduction_policy(args: argparse.Namespace) -> ReductionPolicy | None:
    """Build reduction policy from CLI arguments, or None to use defaults.

    Uses the shared factory's default policy as base, applying only the
    explicitly provided CLI arguments as overrides.
    """
    # Check if any reduction policy option was explicitly provided
    has_explicit_policy = any([
        args.max_reduction_rounds is not None,
        args.candidate_domain_min_items is not None,
        args.candidate_domain_max_items is not None,
        args.num_source_mis_candidates is not None,
        args.min_reduction_ratio is not None,
        args.target_binary_variables is not None,
        args.max_end_to_end_runtime_seconds is not None,
        args.recovery_policy_on_domain_too_small is not None,
        args.recovery_policy_on_infeasible is not None,
        args.max_recovery_attempts is not None,
    ])

    if not has_explicit_policy:
        # Use default policy from inputs builder
        return None

    # Get the default policy from the shared lightweight factory
    base_policy = default_reduction_policy(args.asset_count)

    # Build overrides dict with only explicitly provided values
    overrides: dict[str, object] = {}

    if args.max_reduction_rounds is not None:
        overrides["max_reduction_rounds"] = args.max_reduction_rounds
    if args.candidate_domain_min_items is not None:
        overrides["candidate_domain_min_items"] = args.candidate_domain_min_items
    if args.candidate_domain_max_items is not None:
        overrides["candidate_domain_max_items"] = args.candidate_domain_max_items
    if args.num_source_mis_candidates is not None:
        overrides["num_source_mis_candidates"] = args.num_source_mis_candidates
    if args.min_reduction_ratio is not None:
        overrides["min_reduction_ratio"] = args.min_reduction_ratio
    if args.target_binary_variables is not None:
        overrides["target_binary_variables"] = args.target_binary_variables
    if args.max_end_to_end_runtime_seconds is not None:
        overrides["max_end_to_end_runtime_seconds"] = args.max_end_to_end_runtime_seconds
    if args.recovery_policy_on_domain_too_small is not None:
        overrides["recovery_policy_on_domain_too_small"] = args.recovery_policy_on_domain_too_small
    if args.recovery_policy_on_infeasible is not None:
        overrides["recovery_policy_on_infeasible"] = args.recovery_policy_on_infeasible
    if args.max_recovery_attempts is not None:
        overrides["max_recovery_attempts"] = args.max_recovery_attempts

    return replace(base_policy, **overrides)


def main() -> int:
    """CLI entry point."""
    parser = _build_parser()
    args = parser.parse_args()
    _validate_args(parser, args)

    # Configure logging
    # Precedence: 1) --log-config, 2) QREDUCE_LOG_CONFIG env var, 3) repository default
    try:
        if args.log_config:
            # Explicit CLI argument takes precedence
            configure_logging(args.log_config)
        else:
            # Let configure_logging handle env var and default
            config_path = configure_logging()
            if config_path is None:
                # No env var set; try repository default
                default_path = get_default_config_path()
                if default_path:
                    configure_logging(default_path)
    except (FileNotFoundError, LoggingConfigError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    # Build generation policy
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

    # Build reduction policy (or None to use defaults)
    reduction_policy = _build_reduction_policy(args)

    # Run experiment
    run = run_portfolio_experiment(
        args.run_id,
        output_root=args.output_root,
        asset_count=args.asset_count,
        generation_policy=generation_policy,
        graph_policy=graph_policy,
        reduction_policy=reduction_policy,
        mis_solver_id=args.mis_solver_id,
        classical_solver_id=args.classical_solver_id,
        classical_time_limit_seconds=args.classical_time_limit_seconds,
        mis_num_reads=args.mis_num_reads,
        mis_num_sweeps=args.mis_num_sweeps,
        mis_embedding_profile=args.mis_embedding_profile,
        model_export_enabled=args.model_export,
        model_export_path=args.model_export_path,
        lower_bound=args.lower_bound,
        upper_bound=args.upper_bound,
        min_selected_assets=args.min_selected_assets,
        max_selected_assets=args.max_selected_assets,
    )

    print(run.run_directory)
    return 0


if __name__ == "__main__":
    sys.exit(main())
