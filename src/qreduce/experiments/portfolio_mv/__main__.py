"""Unified CLI for synthetic portfolio mean-variance experiments.

Usage:
    poetry run python -m qreduce.experiments.portfolio_mv --run-id <id> [options]

The execution mode is controlled by --max-reduction-rounds:
    0: Classical-only baseline (no MIS, no reduction)
    1: Single reduction round (default)
   >1: Iterative reduction with optional recovery
"""

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

from qreduce.config import validate_chain_strength, validate_timeout_value
from qreduce.experiments._cli_logging import log_run_command
from qreduce.experiments.portfolio_mv.execution import (
    DEFAULT_PORTFOLIO_OUTPUT_ROOT,
    run_portfolio_experiment,
)
from qreduce.experiments.portfolio_mv.generator import default_generation_policy
from qreduce.experiments.portfolio_mv.inputs import (
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
  python -m qreduce.experiments.portfolio_mv --run-id run001

  # Classical-only baseline
  python -m qreduce.experiments.portfolio_mv --run-id baseline001 --max-reduction-rounds 0

  # Multi-round with 3 rounds
  python -m qreduce.experiments.portfolio_mv --run-id multi001 --max-reduction-rounds 3

  # With custom risk aversion coefficient
  python -m qreduce.experiments.portfolio_mv --run-id ra_high \\
      --risk-aversion 2.5

  # Multi-round with recovery on infeasibility
  python -m qreduce.experiments.portfolio_mv --run-id recovery001 \\
      --max-reduction-rounds 3 \\
      --recovery-policy-on-infeasible retry_with_larger_domain \\
      --max-recovery-attempts 2

  # With positive minimum investment and cardinality constraints
  python -m qreduce.experiments.portfolio_mv --run-id cardinality001 \\
      --lower-bound 0.05 --upper-bound 0.30 \\
      --min-selected-assets 5 --max-selected-assets 10

  # Exact cardinality (select exactly 8 assets)
  python -m qreduce.experiments.portfolio_mv --run-id exact001 \\
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
        "--risk-aversion",
        type=float,
        default=1.0,
        help="Risk aversion coefficient for the mean-variance objective. "
        "Controls the trade-off between expected return and variance. "
        "Must be finite and strictly positive. Default: 1.0.",
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
        choices=("local_greedy", "dwave_simulated_annealing", "pasqal_local", "pasqal_cloud_emulator", "pasqal_qpu"),
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
    solver_group.add_argument("--pasqal-shots", type=int, help="Pasqal local/cloud shots (default: 100).")
    solver_group.add_argument(
        "--pasqal-emulator-service",
        choices=("emu_free",),
        default=None,
        help=(
            "Cloud emulator service for pasqal_cloud_emulator. "
            "Currently only 'emu_free' is supported. "
            "Requires --mis-solver-id=pasqal_cloud_emulator. "
            "EMU_FREE does not require credits. No paid backend is selected automatically."
        ),
    )
    solver_group.add_argument(
        "--pasqal-device-id",
        default=None,
        help=(
            "QPU device ID for pasqal_qpu (e.g., 'FRESNEL'). "
            "Required for --mis-solver-id=pasqal_qpu. "
            "Use 'preflight' subcommand to discover available devices."
        ),
    )
    solver_group.add_argument(
        "--pasqal-cost-consent",
        action="store_true",
        help=(
            "Acknowledge that QPU execution may incur costs. "
            "Required for --mis-solver-id=pasqal_qpu."
        ),
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

    solver_group.add_argument(
        "--mis-chain-strength",
        type=float,
        help=("Positive finite chain strength for local Pegasus/Zephyr embedding with reduction active. "
              "If omitted: 0.375 * effective lambda_edge."),
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
    # Pasqal local validation
    if args.pasqal_shots is not None and args.mis_solver_id not in ("pasqal_local", "pasqal_cloud_emulator", "pasqal_qpu"):
        parser.error("--pasqal-shots requires pasqal_local, pasqal_cloud_emulator, or pasqal_qpu")
    if args.pasqal_shots is not None and args.pasqal_shots < 1:
        parser.error("--pasqal-shots must be a positive integer")
    if (args.mis_solver_id == "pasqal_local" and args.max_reduction_rounds != 0
            and args.max_end_to_end_runtime_seconds != 0):
        parser.error("pasqal_local requires --max-end-to-end-runtime-seconds=0; "
                     "the local emulator cannot enforce a deadline")

    # Pasqal cloud emulator validation
    if args.pasqal_emulator_service is not None and args.mis_solver_id != "pasqal_cloud_emulator":
        parser.error("--pasqal-emulator-service requires --mis-solver-id=pasqal_cloud_emulator")
    if args.mis_solver_id == "pasqal_cloud_emulator" and args.pasqal_emulator_service is None:
        parser.error("--mis-solver-id=pasqal_cloud_emulator requires explicit --pasqal-emulator-service selection")
    if args.mis_solver_id == "pasqal_cloud_emulator" and args.max_reduction_rounds == 0:
        parser.error("pasqal_cloud_emulator requires reduction to be enabled (--max-reduction-rounds > 0)")

    # Pasqal QPU validation
    if args.pasqal_device_id is not None and args.mis_solver_id != "pasqal_qpu":
        parser.error("--pasqal-device-id requires --mis-solver-id=pasqal_qpu")
    if args.pasqal_cost_consent and args.mis_solver_id != "pasqal_qpu":
        parser.error("--pasqal-cost-consent requires --mis-solver-id=pasqal_qpu")
    if args.mis_solver_id == "pasqal_qpu":
        if args.pasqal_device_id is None:
            parser.error("--mis-solver-id=pasqal_qpu requires --pasqal-device-id")
        if not args.pasqal_cost_consent:
            parser.error("--mis-solver-id=pasqal_qpu requires --pasqal-cost-consent to acknowledge potential costs")
        if args.pasqal_shots is None:
            parser.error("--mis-solver-id=pasqal_qpu requires explicit --pasqal-shots")
        if args.max_reduction_rounds == 0:
            parser.error("pasqal_qpu requires reduction to be enabled (--max-reduction-rounds > 0)")
        if args.max_reduction_rounds is not None and args.max_reduction_rounds > 1:
            parser.error("pasqal_qpu supports at most one reduction round (--max-reduction-rounds=1)")

    if args.model_export_path and not args.model_export:
        parser.error("--model-export-path requires --model-export")

    if args.asset_count < 6:
        parser.error("--asset-count must be at least 6")

    # risk_aversion validation - must be finite and strictly positive
    import math
    if not math.isfinite(args.risk_aversion):
        parser.error("--risk-aversion must be finite (not NaN or infinity)")
    if args.risk_aversion <= 0:
        parser.error("--risk-aversion must be strictly positive")

    if args.max_reduction_rounds is not None and args.max_reduction_rounds < 0:
        parser.error("--max-reduction-rounds must be non-negative")

    # D-Wave parameters require D-Wave solver
    if (args.mis_num_reads is not None or args.mis_num_sweeps is not None) and args.mis_solver_id != "dwave_simulated_annealing":
        parser.error("--mis-num-reads and --mis-num-sweeps require --mis-solver-id=dwave_simulated_annealing")

    if args.mis_chain_strength is not None:
        error = validate_chain_strength(
            args.mis_chain_strength,
            embedding_profile=args.mis_embedding_profile,
            solver_id=args.mis_solver_id,
            reduction_active=args.max_reduction_rounds is None or args.max_reduction_rounds > 0,
        )
        if error:
            parser.error(f"--mis-chain-strength: {error}")

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


def _recover_pasqal_main(argv: list[str]) -> int:
    from qreduce.solving.mwis.pasqal_cloud_persistence import (
        PasqalCloudJobPersistenceError,
        PasqalCloudJobRecoveryError,
        load_job_reference,
        recover_batch_counts,
        recover_job_to_samples,
    )

    parser = argparse.ArgumentParser(prog="portfolio_mv recover-pasqal", description="Read an existing Pasqal batch without submitting jobs.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--reference", type=Path)
    source.add_argument("--batch-id")
    parser.add_argument("--project-id", help="Original project; required with --batch-id.")
    parser.add_argument("--profile")
    parser.add_argument("--timeout-seconds", type=float, default=0.0, help="Wait budget (0: check once).")
    args = parser.parse_args(argv)
    if bool(args.batch_id) != bool(args.project_id):
        parser.error("--batch-id and --project-id must be supplied together")
    try:
        if args.reference is not None:
            reference = load_job_reference(args.reference)
            samples, recovery = recover_job_to_samples(
                reference, compiled_job_id=reference.compiled_job_id, compilation_params={},
                weight_encoding_mode="classical_ranking", profile=args.profile, timeout_seconds=args.timeout_seconds,
            )
        else:
            samples = []
            recovery = recover_batch_counts(
                args.batch_id, project_id=args.project_id, profile=args.profile or "default",
                timeout_seconds=args.timeout_seconds,
            )
    except (PasqalCloudJobPersistenceError, PasqalCloudJobRecoveryError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    print(json.dumps({
        "batch_id": recovery.batch_id,
        "status": recovery.status,
        "shots_requested": recovery.shots_requested,
        "shots_received": recovery.shots_received,
        "atom_order": recovery.atom_order,
        "counts": recovery.results,
        "node_order": recovery.node_order,
        "samples": [{"delta": sample.delta, "occurrence_count": sample.occurrence_count} for sample in samples],
        "error": recovery.error_message,
    }))
    return 0 if recovery.is_success else (1 if recovery.is_terminal or recovery.error_message else 2)


def _preflight_main(argv: list[str]) -> int:
    """Preflight check: discover devices and optionally compile without submission.

    This validates QPU configuration and compilation without creating any batch.
    """
    parser = argparse.ArgumentParser(
        prog="portfolio_mv preflight",
        description="Discover QPU devices and optionally compile without submission.",
    )

    # Mode selection
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument(
        "--discover",
        action="store_true",
        help="List available QPU devices from Pasqal Cloud.",
    )
    mode_group.add_argument(
        "--compile",
        action="store_true",
        help="Compile a synthetic test graph for the specified device without submission.",
    )
    mode_group.add_argument(
        "--from-artifacts",
        metavar="PATH",
        help="Compile the graph from existing artifacts (output directory of a previous run).",
    )

    # Common options
    parser.add_argument("--profile", default="default", help="Pasqal credentials profile.")

    # Compile options (also used with --from-artifacts)
    parser.add_argument("--device-id", help="Target QPU device ID (required for --compile and --from-artifacts).")
    parser.add_argument("--layout-mode", choices=("calibrated", "custom"), default="calibrated",
                        help="Use calibrated traps (default) or explicitly generate a custom layout.")
    parser.add_argument("--sequence-output", type=Path, metavar="PATH",
                        help="Save the exact validated sequence to a new file without submitting it.")
    parser.add_argument("--compilation-time-limit-seconds", type=float, default=0.0,
                        help="Cooperative compilation deadline (0: no time limit).")
    parser.add_argument("--asset-count", type=int, default=6, help="Asset count for test graph. Default: 6. (--compile only)")
    parser.add_argument(
        "--graph-edge-mode",
        choices=("correlation_only", "near_duplicate"),
        default="near_duplicate",
        help="Graph edge semantics for test. Default: near_duplicate. (--compile only)",
    )
    parser.add_argument(
        "--correlation-threshold",
        type=float,
        default=0.90,
        help="Correlation threshold for test graph. Default: 0.90. (--compile only)",
    )

    args = parser.parse_args(argv)

    if args.compile and not args.device_id:
        parser.error("--compile requires --device-id")
    if args.from_artifacts and not args.device_id:
        parser.error("--from-artifacts requires --device-id")
    timeout_error = validate_timeout_value(args.compilation_time_limit_seconds,
                                           "--compilation-time-limit-seconds")
    if timeout_error:
        parser.error(timeout_error)

    try:
        from qreduce.solving.mwis.pasqal_qpu_backend import PasqalQPUMISBackend

        backend = PasqalQPUMISBackend()

        if args.discover:
            if args.layout_mode != "calibrated" or args.sequence_output is not None:
                parser.error("--layout-mode custom and --sequence-output require --compile or --from-artifacts.")
            # Discovery mode
            devices, error = backend.discover_devices(profile=args.profile)
            if error:
                print(f"Error: {error}", file=sys.stderr)
                return 1

            if not devices:
                print(json.dumps({"devices": [], "message": "No QPU devices available."}))
                return 0

            result = {
                "devices": [
                    {
                        "device_id": d.device_id,
                        "name": d.name,
                        "max_atoms": d.max_atoms,
                        "min_atom_distance": d.min_atom_distance,
                        "has_calibrated_layouts": d.has_calibrated_layouts,
                        "available_layouts": list(d.available_layouts),
                        "requires_layout": d.requires_layout,
                        "accepts_new_layouts": d.accepts_new_layouts,
                        "max_runs": d.max_runs,
                        "status": d.status,
                    }
                    for d in devices
                ]
            }
            print(json.dumps(result, indent=2))
            return 0

        from hashlib import sha256

        from qreduce.artifacts.metadata import sha256_hex
        from qreduce.solving.mwis.contracts import MISCompilationRequest
        from qreduce.status import BackendFamily, ExecutionMode, ProblemForm

        context = {"source": "synthetic"}
        if args.from_artifacts:
            from qreduce.experiments.portfolio_mv.preflight_artifacts import load_preflight_problem

            artifact_path = Path(args.from_artifacts)
            original_run_id, problem = load_preflight_problem(artifact_path)
            context = {"source": "artifacts", "artifact_path": str(artifact_path),
                       "original_run_id": original_run_id}
            run_id = f"preflight-{original_run_id}"
        else:
            from qreduce.experiments.portfolio_mv.inputs import build_synthetic_portfolio_inputs
            from qreduce.pipeline.single_pass import build_canonical_mwis_problem

            run_id = "preflight-test"
            policy = default_graph_policy(edge_mode=args.graph_edge_mode,
                                          correlation_threshold=args.correlation_threshold)
            inputs = build_synthetic_portfolio_inputs(run_id, asset_count=args.asset_count, graph_policy=policy)
            problem = build_canonical_mwis_problem(inputs.problem, inputs.adapter, inputs.config)

        result = backend.compile(problem, MISCompilationRequest(
            run_id=run_id, round_index=0, node_order=problem.graph.node_ids,
            residual_time_budget_seconds=args.compilation_time_limit_seconds,
            requested_provider_id="pasqal", requested_backend_id="pasqal_qpu",
            requested_backend_family=BackendFamily.NEUTRAL_ATOM,
            requested_execution_mode=ExecutionMode.REMOTE,
            required_problem_form=ProblemForm.MIS_GRAPH, requested_device_id=args.device_id,
            compilation_parameters={"pasqal_profile": args.profile, "layout_mode": args.layout_mode},
        ))
        job = result.compiled_job
        payload = (job.provider_payload or {}) if job else {}
        presolve = payload.get("presolve_applied", False)
        diagnostic = payload.get("mapping_diagnostic")
        outcome = "presolve_only" if presolve else "qpu_sequence_validated" if job else "compilation_failed"
        sequence_output = None
        if outcome == "qpu_sequence_validated" and args.sequence_output is not None:
            with args.sequence_output.open("xb") as output:
                output.write(payload["sequence_abstract_repr"].encode("utf-8"))
            sequence_output = str(args.sequence_output)
        print(json.dumps({
            **context,
            "success": job is not None, "outcome": outcome,
            "qpu_sequence_validated": outcome == "qpu_sequence_validated",
            "graph_hash": sha256(problem.graph.to_canonical_json().encode()).hexdigest(),
            "problem_sha256": sha256_hex(problem),
            "project_id_sha256": sha256(payload["project_id"].encode()).hexdigest() if payload.get("project_id") else None,
            "node_count": len(problem.graph.node_ids), "edge_count": len(problem.graph.edges),
            "presolve_applied": presolve, "compilation_time_seconds": result.runtime_seconds,
            "compiled_job_id": job.compiled_job_id if job else None,
            "device_id": payload.get("device_id"), "layout_id": payload.get("layout_id"),
            "layout_mode": args.layout_mode, "layout_sha256": payload.get("layout_sha256"),
            "device_spec_sha256": payload.get("device_spec_sha256"),
            "sequence_sha256": payload.get("sequence_sha256"),
            "sequence_output": sequence_output,
            "mapping_diagnostic": diagnostic,
            "mapping_result": payload.get("mapping_result") if job else result.to_dict().get("diagnostic_details"),
            "terminal_reason": result.terminal_reason.value if result.terminal_reason else None,
            "diagnostic_message": result.diagnostic_message,
        }, indent=2))
        return 0 if job else 1

    except Exception as error:  # noqa: BLE001
        print(f"Error: {error}", file=sys.stderr)
        return 1


def main() -> int:
    """CLI entry point."""
    if sys.argv[1:2] == ["submit-preflight"]:
        from qreduce.experiments.portfolio_mv.preflight_submission import submit_preflight_main

        return submit_preflight_main(sys.argv[2:], default_output_root=Path(DEFAULT_PORTFOLIO_OUTPUT_ROOT))
    if sys.argv[1:2] == ["recover-pasqal"]:
        return _recover_pasqal_main(sys.argv[2:])
    if sys.argv[1:2] == ["preflight"]:
        return _preflight_main(sys.argv[2:])
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

    log_run_command(args.run_id)

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
        risk_aversion=args.risk_aversion,
        generation_policy=generation_policy,
        graph_policy=graph_policy,
        reduction_policy=reduction_policy,
        mis_solver_id=args.mis_solver_id,
        classical_solver_id=args.classical_solver_id,
        classical_time_limit_seconds=args.classical_time_limit_seconds,
        mis_num_reads=args.mis_num_reads,
        pasqal_shots=args.pasqal_shots,
        pasqal_emulator_service=args.pasqal_emulator_service,
        pasqal_device_id=args.pasqal_device_id,
        pasqal_cost_consent=args.pasqal_cost_consent,
        mis_num_sweeps=args.mis_num_sweeps,
        mis_embedding_profile=args.mis_embedding_profile,
        mis_chain_strength=args.mis_chain_strength,
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
