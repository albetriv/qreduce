"""CLI for Sharpe portfolio experiment.

Usage:
    poetry run python -m qreduce.experiments.portfolio_sr --run-id <id> [options]

Execution modes (controlled by --max-reduction-rounds):
    0: Classical-only baseline (no MWIS, no reduction)
    1: Single reduction round (default)
   >1: Multi-round with optional recovery
"""

import argparse
import math
import sys
from dataclasses import replace
from datetime import date

from qreduce.config import validate_timeout_value
from qreduce.experiments._cli_logging import log_run_command
from qreduce.experiments.portfolio_sr.execution import run_sharpe_portfolio_experiment
from qreduce.experiments.portfolio_sr.graph_policy import default_sharpe_graph_policy
from qreduce.experiments.portfolio_sr.inputs import (
    DEFAULT_OUTPUT_ROOT,
    DEFAULT_SP500_CSV,
    default_reduction_policy,
)
from qreduce.experiments.portfolio_sr.models import SectorConstraints
from qreduce.logging_config import (
    LoggingConfigError,
    configure_logging,
    get_default_config_path,
)
from qreduce.models import ReductionPolicy

_VALID_RECOVERY_POLICIES = ("fail", "retry_with_larger_domain")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run Sharpe portfolio optimization with QReduce domain reduction.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Single-pass with 50 assets (default)
  python -m qreduce.experiments.portfolio_sr --run-id run001

  # Classical-only baseline (no reduction)
  python -m qreduce.experiments.portfolio_sr --run-id baseline001 --max-reduction-rounds 0

  # With cardinality constraint
  python -m qreduce.experiments.portfolio_sr --run-id card001 --min-selected-assets 5 --max-selected-assets 15

  # Custom date range and asset count
  python -m qreduce.experiments.portfolio_sr --run-id custom001 \\
      --asset-count 100 \\
      --start-date 2022-01-01 \\
      --end-date 2024-12-31

  # With sector constraints
  python -m qreduce.experiments.portfolio_sr --run-id sector001 \\
      --sector-min "Technology=0.10,Health Care=0.05" \\
      --sector-max "Technology=0.30,Health Care=0.20"
""",
    )

    # Required arguments
    parser.add_argument(
        "--run-id",
        required=True,
        help="Unique run identifier for artifact directory.",
    )

    # Logging configuration
    parser.add_argument(
        "--log-config",
        metavar="PATH",
        help="Path to YAML logging configuration file.",
    )

    # Output configuration
    parser.add_argument(
        "--output-root",
        default=str(DEFAULT_OUTPUT_ROOT),
        help=f"Root directory for experiment artifacts. Default: {DEFAULT_OUTPUT_ROOT}",
    )
    parser.add_argument(
        "--model-export",
        action="store_true",
        help="Export the residual classical model.",
    )
    parser.add_argument(
        "--model-export-path",
        help="Custom export path for model (.lp or .mps).",
    )

    # Data configuration
    data_group = parser.add_argument_group("Data options")
    data_group.add_argument(
        "--csv-path",
        default=str(DEFAULT_SP500_CSV),
        help=f"Path to S&P500 CSV file. Default: {DEFAULT_SP500_CSV}",
    )
    data_group.add_argument(
        "--asset-count",
        type=int,
        default=None,
        help="Number of assets to select. Default: 50 (when --explicit-tickers is not used).",
    )
    data_group.add_argument(
        "--explicit-tickers",
        help="Comma-separated list of specific tickers to include.",
    )
    data_group.add_argument(
        "--start-date",
        type=_parse_date,
        help="Start date (YYYY-MM-DD) for price data.",
    )
    data_group.add_argument(
        "--end-date",
        type=_parse_date,
        help="End date (YYYY-MM-DD) for price data.",
    )
    data_group.add_argument(
        "--return-convention",
        choices=("simple", "log"),
        default="log",
        help="Return calculation method. Default: log.",
    )
    data_group.add_argument(
        "--annualization-factor",
        type=int,
        default=252,
        help="Trading days per year for annualization. Default: 252.",
    )
    data_group.add_argument(
        "--selection-order",
        choices=("alphabetical", "sharpe_descending", "random"),
        default="alphabetical",
        help="Ticker selection order. Default: alphabetical.",
    )
    data_group.add_argument(
        "--random-seed",
        type=int,
        help="Random seed for reproducible random selection.",
    )

    # Problem configuration
    problem_group = parser.add_argument_group("Problem options")
    problem_group.add_argument(
        "--lower-bound",
        type=float,
        default=0.0,
        help="Minimum weight per selected asset. Default: 0.0.",
    )
    problem_group.add_argument(
        "--upper-bound",
        type=float,
        default=1.0,
        help="Maximum weight per asset. Default: 1.0 (no constraint).",
    )
    problem_group.add_argument(
        "--min-selected-assets",
        type=int,
        help="Minimum number of selected assets (0 disables the constraint).",
    )
    problem_group.add_argument(
        "--max-selected-assets",
        type=int,
        help="Maximum number of selected assets.",
    )
    problem_group.add_argument(
        "--max-positions",
        type=int,
        help="Compatibility alias for --max-selected-assets.",
    )
    problem_group.add_argument(
        "--risk-free-rate",
        type=float,
        default=0.0,
        help="Risk-free rate for Sharpe calculation. Default: 0.0.",
    )
    problem_group.add_argument(
        "--sector-min",
        help="Minimum sector exposures (e.g., 'Technology=0.10,Health Care=0.05').",
    )
    problem_group.add_argument(
        "--sector-max",
        help="Maximum sector exposures (e.g., 'Technology=0.30,Health Care=0.20').",
    )

    # Graph policy configuration
    graph_group = parser.add_argument_group("Graph policy options")
    graph_group.add_argument(
        "--edge-mode",
        choices=("correlation_only", "near_duplicate"),
        default="near_duplicate",
        help="Edge semantics for MWIS graph. Default: near_duplicate.",
    )
    graph_group.add_argument(
        "--correlation-threshold",
        type=float,
        default=0.80,
        help="Minimum positive correlation for edges. Default: 0.80.",
    )
    graph_group.add_argument(
        "--near-duplicate-max-return-diff",
        type=float,
        default=0.15,
        help="Max relative return difference for near_duplicate edges. Default: 0.15.",
    )
    graph_group.add_argument(
        "--near-duplicate-max-variance-diff",
        type=float,
        default=0.15,
        help="Max relative variance difference for near_duplicate edges. Default: 0.15.",
    )

    # Solver configuration
    solver_group = parser.add_argument_group("Solver options")
    solver_group.add_argument(
        "--mis-solver-id",
        choices=("local_greedy", "dwave_simulated_annealing", "pasqal_local"),
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
        default=60.0,
        help="Time limit per classical solve. Default: 60.0.",
    )
    solver_group.add_argument("--pasqal-shots", type=int, help="Pasqal local shots (default: 100).")
    solver_group.add_argument(
        "--mis-num-reads",
        type=int,
        help="D-Wave num_reads parameter.",
    )
    solver_group.add_argument(
        "--mis-num-sweeps",
        type=int,
        help="D-Wave num_sweeps parameter.",
    )
    solver_group.add_argument(
        "--mis-embedding-profile",
        choices=("none", "pegasus_p16", "zephyr_z12"),
        default=None,
        help="D-Wave embedding profile for simulated annealing.",
    )

    # Reduction policy configuration
    reduction_group = parser.add_argument_group("Reduction policy options")
    reduction_group.add_argument(
        "--max-reduction-rounds",
        type=int,
        default=1,
        help="Maximum reduction rounds (0=baseline, 1=single, >1=multi). Default: 1.",
    )
    reduction_group.add_argument(
        "--candidate-domain-min-items",
        type=int,
        help="Minimum items in candidate domain.",
    )
    reduction_group.add_argument(
        "--candidate-domain-max-items",
        type=int,
        help="Maximum items in candidate domain.",
    )
    reduction_group.add_argument(
        "--num-source-mis-candidates",
        type=int,
        help="Number of MIS candidates to consider.",
    )
    reduction_group.add_argument(
        "--min-reduction-ratio",
        type=float,
        help="Minimum reduction ratio.",
    )
    reduction_group.add_argument(
        "--target-binary-variables",
        type=int,
        help="Target binary variables after reduction.",
    )
    reduction_group.add_argument(
        "--max-end-to-end-runtime-seconds",
        type=float,
        help="Maximum end-to-end runtime. Default: 120.0.",
    )
    reduction_group.add_argument(
        "--recovery-policy-on-domain-too-small",
        choices=_VALID_RECOVERY_POLICIES,
        help="Recovery policy when domain is too small.",
    )
    reduction_group.add_argument(
        "--recovery-policy-on-infeasible",
        choices=_VALID_RECOVERY_POLICIES,
        help="Recovery policy when problem is infeasible.",
    )
    reduction_group.add_argument(
        "--max-recovery-attempts",
        type=int,
        help="Maximum recovery attempts.",
    )

    return parser


def _parse_date(date_string: str) -> date:
    """Parse ISO date string."""
    try:
        return date.fromisoformat(date_string)
    except ValueError as e:
        raise argparse.ArgumentTypeError(f"Invalid date format: {date_string}") from e


def _parse_sector_constraints(
    min_str: str | None,
    max_str: str | None,
) -> SectorConstraints | None:
    """Parse sector constraint strings."""
    if min_str is None and max_str is None:
        return None

    def parse_constraints(s: str) -> dict[str, float]:
        result = {}
        for pair in s.split(","):
            pair = pair.strip()
            if not pair:
                continue
            if "=" not in pair:
                raise ValueError(f"Invalid sector constraint format: {pair}")
            sector, value = pair.split("=", 1)
            result[sector.strip()] = float(value.strip())
        return result

    sector_min = parse_constraints(min_str) if min_str else {}
    sector_max = parse_constraints(max_str) if max_str else {}

    # Ensure both have same sectors
    all_sectors = set(sector_min.keys()) | set(sector_max.keys())
    for sector in all_sectors:
        if sector not in sector_min:
            sector_min[sector] = 0.0
        if sector not in sector_max:
            sector_max[sector] = 1.0

    return SectorConstraints(sector_min=sector_min, sector_max=sector_max)


def _validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    """Validate argument combinations."""
    if args.pasqal_shots is not None and (args.mis_solver_id != "pasqal_local" or args.pasqal_shots < 1):
        parser.error("--pasqal-shots requires pasqal_local and a positive integer")
    if args.model_export_path and not args.model_export:
        parser.error("--model-export-path requires --model-export")

    if args.asset_count is not None and args.explicit_tickers is not None:
        parser.error("--asset-count and --explicit-tickers are mutually exclusive")

    if args.asset_count is not None and args.asset_count < 1:
        parser.error("--asset-count must be at least 1")

    if args.max_reduction_rounds < 0:
        parser.error("--max-reduction-rounds must be non-negative")

    if args.max_selected_assets is not None:
        if args.max_positions is not None and args.max_positions != args.max_selected_assets:
            parser.error("--max-selected-assets and --max-positions must agree")
        args.max_positions = args.max_selected_assets
    if args.max_positions is not None and args.max_positions < 1:
        parser.error("--max-selected-assets (or --max-positions) must be at least 1")
    if args.min_selected_assets is not None and args.min_selected_assets < 0:
        parser.error("--min-selected-assets must be non-negative")
    if args.max_positions is not None and (args.min_selected_assets or 0) > args.max_positions:
        parser.error("--min-selected-assets must not exceed --max-selected-assets")
    if (args.max_reduction_rounds > 0 and args.candidate_domain_max_items is not None
            and args.candidate_domain_max_items < (args.min_selected_assets or 0)):
        parser.error("--candidate-domain-max-items must be at least --min-selected-assets")

    if not math.isfinite(args.lower_bound) or not 0 <= args.lower_bound <= 1:
        parser.error("--lower-bound must be finite and between 0 and 1")
    if args.lower_bound > args.upper_bound:
        parser.error("--lower-bound must not exceed --upper-bound")

    # Risk-free rate must be zero in current version
    if args.risk_free_rate != 0.0:
        parser.error(
            "--risk-free-rate must be 0.0 in current version. "
            "Non-zero risk-free rate requires coordinated implementation changes."
        )

    if (args.mis_solver_id == "pasqal_local" and args.max_reduction_rounds != 0
            and args.max_end_to_end_runtime_seconds != 0):
        parser.error("pasqal_local requires --max-end-to-end-runtime-seconds=0; "
                     "the local emulator cannot enforce a deadline")

    # D-Wave parameters require D-Wave solver
    if (
        (args.mis_num_reads is not None or args.mis_num_sweeps is not None)
        and args.mis_solver_id != "dwave_simulated_annealing"
    ):
        parser.error("--mis-num-reads and --mis-num-sweeps require --mis-solver-id=dwave_simulated_annealing")

    # Embedding profile validation
    if args.mis_embedding_profile is not None and args.mis_embedding_profile != "none":
        if args.mis_solver_id != "dwave_simulated_annealing":
            parser.error("--mis-embedding-profile requires --mis-solver-id=dwave_simulated_annealing")
        if args.max_reduction_rounds == 0:
            parser.error("--mis-embedding-profile requires reduction enabled")

    # Time limit validation
    if args.classical_time_limit_seconds is not None:
        error = validate_timeout_value(args.classical_time_limit_seconds, "--classical-time-limit-seconds")
        if error:
            parser.error(error)

    if args.max_end_to_end_runtime_seconds is not None:
        error = validate_timeout_value(args.max_end_to_end_runtime_seconds, "--max-end-to-end-runtime-seconds")
        if error:
            parser.error(error)


def _build_reduction_policy(args: argparse.Namespace, asset_count: int) -> ReductionPolicy:
    """Build reduction policy from CLI arguments."""
    base = default_reduction_policy(
        asset_count,
        min_selected_assets=args.min_selected_assets if args.max_reduction_rounds > 0 else None,
    )

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

    return replace(base, **overrides) if overrides else base


def main() -> int:
    """CLI entry point."""
    parser = _build_parser()
    args = parser.parse_args()
    _validate_args(parser, args)

    # Configure logging
    try:
        if args.log_config:
            configure_logging(args.log_config)
        else:
            config_path = configure_logging()
            if config_path is None:
                default_path = get_default_config_path()
                if default_path:
                    configure_logging(default_path)
    except (FileNotFoundError, LoggingConfigError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    log_run_command(args.run_id)

    # Parse explicit tickers
    explicit_tickers = None
    if args.explicit_tickers:
        explicit_tickers = [t.strip() for t in args.explicit_tickers.split(",")]

    # Parse sector constraints
    try:
        sector_constraints = _parse_sector_constraints(args.sector_min, args.sector_max)
    except ValueError as e:
        print(f"Error parsing sector constraints: {e}", file=sys.stderr)
        return 1

    # Build graph policy
    graph_policy = default_sharpe_graph_policy(
        edge_mode=args.edge_mode,
        correlation_threshold=args.correlation_threshold,
        near_duplicate_max_return_diff=args.near_duplicate_max_return_diff,
        near_duplicate_max_variance_diff=args.near_duplicate_max_variance_diff,
    )

    # Compute effective asset count for reduction policy
    if explicit_tickers is not None:
        effective_asset_count_for_policy = len(explicit_tickers)
    elif args.asset_count is not None:
        effective_asset_count_for_policy = args.asset_count
    else:
        effective_asset_count_for_policy = 50  # default

    # Build reduction policy
    reduction_policy = _build_reduction_policy(args, effective_asset_count_for_policy)

    # Run experiment
    try:
        # Apply default asset_count=50 only when no explicit tickers are provided
        effective_asset_count = None
        if explicit_tickers is None:
            effective_asset_count = args.asset_count if args.asset_count is not None else 50
        run = run_sharpe_portfolio_experiment(
            args.run_id,
            csv_path=args.csv_path,
            asset_count=effective_asset_count,
            explicit_tickers=explicit_tickers,
            start_date=args.start_date,
            end_date=args.end_date,
            return_convention=args.return_convention,
            annualization_factor=args.annualization_factor,
            risk_free_rate=args.risk_free_rate,
            upper_bound=args.upper_bound,
            lower_bound=args.lower_bound,
            sector_constraints=sector_constraints,
            max_positions=args.max_positions,
            min_selected_assets=args.min_selected_assets,
            graph_policy=graph_policy,
            mis_solver_id=args.mis_solver_id,
            classical_solver_id=args.classical_solver_id,
            classical_time_limit_seconds=args.classical_time_limit_seconds,
            mis_num_reads=args.mis_num_reads,
            pasqal_shots=args.pasqal_shots,
            mis_num_sweeps=args.mis_num_sweeps,
            mis_embedding_profile=args.mis_embedding_profile,
            reduction_policy=reduction_policy,
            model_export_enabled=args.model_export,
            model_export_path=args.model_export_path,
            output_root=args.output_root,
            selection_order=args.selection_order,
            random_seed=args.random_seed,
        )

        print(run.run_directory)
        return 0

    except Exception as e:  # noqa: BLE001 - CLI catch-all for user-friendly errors
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
