"""Unified synthetic portfolio experiment execution.

This module exposes a single function, `run_portfolio_experiment`, that unifies
the baseline, single-pass, and multi-round experiments. The execution mode is
controlled by the `reduction_policy` parameter:

- `max_reduction_rounds=0`: Classical-only baseline (no MIS, no reduction)
- `max_reduction_rounds=1`: Single reduction round
- `max_reduction_rounds>1`: Iterative reduction with optional recovery

When no `reduction_policy` is provided, the default from `build_synthetic_portfolio_inputs`
is used (single-pass with `max_reduction_rounds=1`).
"""

from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from qreduce.experiments.portfolio_mv.inputs import (
    DEFAULT_PORTFOLIO_OUTPUT_ROOT,
    build_synthetic_portfolio_inputs,
    default_graph_policy,
)
from qreduce.experiments.portfolio_mv.models import PortfolioGraphPolicy
from qreduce.experiments.runner import ExperimentRun, run_experiment
from qreduce.models import ReductionPolicy

if TYPE_CHECKING:
    from qreduce.experiments.portfolio_mv.models import (
        SyntheticPortfolioGenerationPolicy,
    )


UNIFIED_EXPERIMENT_ID = "synthetic-portfolio"


def run_portfolio_experiment(
    run_id: str,
    *,
    output_root: str | Path = DEFAULT_PORTFOLIO_OUTPUT_ROOT,
    asset_count: int = 30,
    risk_aversion: float = 1.0,
    generation_policy: "SyntheticPortfolioGenerationPolicy | None" = None,
    graph_policy: PortfolioGraphPolicy | None = None,
    reduction_policy: ReductionPolicy | None = None,
    mis_solver_id: str = "local_greedy",
    classical_solver_id: str = "scip",
    classical_time_limit_seconds: float | None = None,
    mis_num_reads: int | None = None,
    pasqal_shots: int | None = None,
    pasqal_emulator_service: str | None = None,
    pasqal_device_id: str | None = None,
    pasqal_cost_consent: bool = False,
    mis_num_sweeps: int | None = None,
    mis_embedding_profile: str | None = None,
    mis_chain_strength: float | None = None,
    model_export_enabled: bool = False,
    model_export_path: str | None = None,
    lower_bound: float = 0.0,
    upper_bound: float = 0.7,
    min_selected_assets: int | None = None,
    max_selected_assets: int | None = None,
) -> ExperimentRun:
    """Run and persist a synthetic portfolio experiment.

    This unified function replaces the previous separate wrappers for
    classical-only, single-pass, and multi-round experiments. The execution
    mode is determined by `reduction_policy.max_reduction_rounds`:

    - 0: Classical-only baseline (no graph, no MIS execution)
    - 1: Single reduction round
    - >1: Iterative reduction with early termination on success

    When `reduction_policy` is None, the default policy from the inputs builder
    is used (single-pass with `max_reduction_rounds=1`).

    Args:
        run_id: Unique identifier for the run.
        output_root: Root directory for experiment artifacts.
        asset_count: Number of assets in the synthetic portfolio. Must be >= 6.
        risk_aversion: Risk aversion coefficient for the mean-variance objective.
            Controls the trade-off between expected return and variance.
            Must be finite and strictly positive. Default is 1.0.
        generation_policy: Optional generation policy. If None, uses default.
        graph_policy: Optional graph policy. If None, uses near_duplicate default.
        reduction_policy: Optional reduction policy controlling max rounds, domain
            limits, target variables, and recovery behavior. If None, uses the
            default single-pass policy from the inputs builder.
        mis_solver_id: MIS solver to use.
        classical_solver_id: Classical solver to use.
        classical_time_limit_seconds: Maximum time per classical solve invocation.
            A value of 0 means no per-solve time limit (solver runs until
            completion or end-to-end budget exhaustion). If None, uses the
            default of 60 seconds. The limit restarts for each solve.
        mis_num_reads: Optional D-Wave num_reads parameter.
        pasqal_shots: Local Pasqal shot count.
        mis_num_sweeps: Optional D-Wave num_sweeps parameter.
        mis_embedding_profile: Local embedding profile for D-Wave simulated annealing.
            Constrains sampling to hardware-like topology without QPU access.
            Valid values: 'none' (default), 'pegasus_p16', 'zephyr_z12'.
            Requires mis_solver_id='dwave_simulated_annealing' and reduction active.
        mis_chain_strength: Optional positive override for local embedding chain couplings.
        model_export_enabled: Whether to export the residual model.
        model_export_path: Optional path for model export.
        lower_bound: Minimum investment per selected asset. Default 0.0.
        upper_bound: Maximum investment per selected asset. Default 0.7.
        min_selected_assets: Optional minimum number of assets to select (cardinality).
        max_selected_assets: Optional maximum number of assets to select (cardinality).

    Returns:
        ExperimentRun with the run directory and result.

    Raises:
        ValueError: If asset_count < 6, if risk_aversion is invalid, or if D-Wave
            parameters are used with a non-D-Wave solver, or if cardinality/bound
            constraints are invalid, or if classical_time_limit_seconds is negative,
            or if embedding profile is incompatible with the solver.
    """
    # Validate asset_count early
    if isinstance(asset_count, bool) or not isinstance(asset_count, int) or asset_count < 6:
        raise ValueError("asset_count must be an integer greater than or equal to 6.")

    # Use shared inputs builder for generation and graph policies
    if graph_policy is None:
        graph_policy = default_graph_policy()

    inputs = build_synthetic_portfolio_inputs(
        run_id,
        asset_count=asset_count,
        risk_aversion=risk_aversion,
        generation_policy=generation_policy,
        graph_policy=graph_policy,
        mis_solver_id=mis_solver_id,
        classical_solver_id=classical_solver_id,
        classical_time_limit_seconds=classical_time_limit_seconds,
        mis_num_reads=mis_num_reads,
        pasqal_shots=pasqal_shots,
        pasqal_emulator_service=pasqal_emulator_service,
        pasqal_device_id=pasqal_device_id,
        pasqal_cost_consent=pasqal_cost_consent,
        mis_num_sweeps=mis_num_sweeps,
        mis_embedding_profile=mis_embedding_profile,
        mis_chain_strength=mis_chain_strength,
        lower_bound=lower_bound,
        upper_bound=upper_bound,
        min_selected_assets=min_selected_assets,
        max_selected_assets=max_selected_assets,
    )

    # Apply reduction policy if provided, otherwise keep the default from inputs
    config = inputs.config
    if reduction_policy is not None:
        config = replace(config, reduction=reduction_policy)
    if mis_chain_strength is not None and config.reduction.max_reduction_rounds <= 0:
        raise ValueError("mis_chain_strength requires active reduction.")
    if mis_solver_id == "pasqal_qpu" and config.reduction.max_reduction_rounds != 1:
        raise ValueError("pasqal_qpu requires exactly one reduction round.")

    # Apply model export options
    if model_export_enabled or model_export_path is not None:
        config = replace(
            config,
            classical_solve=replace(
                config.classical_solve,
                model_export_enabled=model_export_enabled,
                model_export_path=model_export_path,
            ),
        )

    # Determine execution mode for metadata
    max_rounds = config.reduction.max_reduction_rounds
    if max_rounds == 0:
        execution_mode = "classical_only"
    elif max_rounds == 1:
        execution_mode = "single_pass"
    else:
        execution_mode = "multi_round"

    experiment_metadata: dict[str, object] = {
        "portfolio_graph_policy": inputs.graph_policy,
        "execution_mode": execution_mode,
    }
    if inputs.generation_policy is not None:
        experiment_metadata["generation_policy"] = inputs.generation_policy

    return run_experiment(
        UNIFIED_EXPERIMENT_ID,
        inputs.problem,
        inputs.adapter,
        config,
        output_root=output_root,
        experiment_metadata=experiment_metadata,
    )
