"""Execution orchestration for Sharpe portfolio experiments.

This module provides:
- run_sharpe_portfolio_experiment: main entry point
- run_sharpe_portfolio_from_inputs: entry point from pre-built inputs
- Integration with QReduce runner and pipeline
- Metadata and provenance management
- Model export configuration

The execution flow:
1. Build inputs (load data, compute stats, create problem)
2. Configure pipeline (policies, solvers, tolerances)
3. Execute via shared experiment runner
4. Persist artifacts for later analysis
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path

from qreduce.config import (
    DEFAULT_CLASSICAL_TIME_LIMIT_SECONDS,
    validate_timeout_value,
)
from qreduce.experiments.portfolio_sr.inputs import (
    DEFAULT_OUTPUT_ROOT,
    DEFAULT_SP500_CSV,
    SharpePortfolioInputs,
    build_sharpe_portfolio_inputs,
    default_reduction_policy,
)
from qreduce.experiments.portfolio_sr.models import (
    SectorConstraints,
    SharpeGraphPolicy,
)
from qreduce.experiments.runner import ExperimentRun, run_experiment
from qreduce.models import (
    ClassicalSolveOptions,
    LambdaEdgePolicy,
    MISExecutionOptions,
    PolicyProvenance,
    ReductionPolicy,
    ResolvedRunConfig,
    RunIdentity,
)
from qreduce.solving.mwis import builtin_mis_solver_registry
from qreduce.solving.residual import builtin_classical_solver_registry
from qreduce.status import PostcheckMode

logger = logging.getLogger(__name__)

# Experiment identifier
EXPERIMENT_ID = "sharpe_portfolio"


def _build_mis_execution_options(
    *,
    mis_num_reads: int | None = None,
    pasqal_shots: int | None = None,
    mis_num_sweeps: int | None = None,
    mis_embedding_profile: str | None = None,
    mis_solver_id: str = "local_greedy",
) -> MISExecutionOptions:
    """Build MISExecutionOptions with correct structure.

    The solver_id goes in ResolvedRunConfig, not here.
    Provider-specific parameters go in provider_parameters.
    Embedding profile goes in compilation_parameters.
    """
    provider_parameters: dict[str, object] = {}
    compilation_parameters: dict[str, object] = {}

    # D-Wave specific parameters
    if mis_num_reads is not None:
        if mis_solver_id != "dwave_simulated_annealing":
            raise ValueError(
                "mis_num_reads requires mis_solver_id='dwave_simulated_annealing'"
            )
        if not isinstance(mis_num_reads, int) or mis_num_reads <= 0:
            raise ValueError("mis_num_reads must be a positive integer")
        provider_parameters["num_reads"] = mis_num_reads

    if mis_num_sweeps is not None:
        if mis_solver_id != "dwave_simulated_annealing":
            raise ValueError(
                "mis_num_sweeps requires mis_solver_id='dwave_simulated_annealing'"
            )
        if not isinstance(mis_num_sweeps, int) or mis_num_sweeps <= 0:
            raise ValueError("mis_num_sweeps must be a positive integer")
        provider_parameters["num_sweeps"] = mis_num_sweeps

    if mis_embedding_profile is not None and mis_embedding_profile != "none":
        if mis_solver_id != "dwave_simulated_annealing":
            raise ValueError(
                f"mis_embedding_profile='{mis_embedding_profile}' requires "
                "mis_solver_id='dwave_simulated_annealing'"
            )
        valid_profiles = ("none", "pegasus_p16", "zephyr_z12")
        if mis_embedding_profile not in valid_profiles:
            raise ValueError(
                f"Invalid mis_embedding_profile: {mis_embedding_profile!r}. "
                f"Valid values: {', '.join(valid_profiles)}"
            )
        compilation_parameters["embedding_profile"] = mis_embedding_profile

    max_distinct_samples = 1
    if pasqal_shots is not None and mis_solver_id != "pasqal_local":
        raise ValueError("pasqal_shots requires mis_solver_id='pasqal_local'.")
    if mis_solver_id == "pasqal_local":
        shots = 100 if pasqal_shots is None else pasqal_shots
        if isinstance(shots, bool) or not isinstance(shots, int) or shots < 1:
            raise ValueError("pasqal_shots must be a positive integer.")
        provider_parameters["shots"] = shots
        max_distinct_samples = shots

    return MISExecutionOptions(
        requested_solution_count=1,
        random_seed=None if mis_solver_id == "pasqal_local" else 17,
        max_distinct_samples=max_distinct_samples,
        repair_enabled=False,
        repair_max_iterations=0,
        minimum_candidate_jaccard_distance=0.0,
        exact_solver_max_variables=20,
        provider_parameters=provider_parameters,
        compilation_parameters=compilation_parameters,
    )


def _build_classical_solve_options(
    *,
    classical_solver_id: str = "scip",
    classical_time_limit_seconds: float | None = None,
    model_export_enabled: bool = False,
    model_export_path: str | None = None,
    random_seed: int | None = 7,
) -> ClassicalSolveOptions:
    """Build ClassicalSolveOptions with correct structure.

    Handles the time_limit_seconds semantics:
    - None -> use default (60s)
    - 0 -> no per-solve limit
    - >0 -> that many seconds
    """
    # Validate and resolve time limit
    if classical_time_limit_seconds is None:
        resolved_time_limit = DEFAULT_CLASSICAL_TIME_LIMIT_SECONDS
    else:
        error = validate_timeout_value(
            classical_time_limit_seconds, "classical_time_limit_seconds"
        )
        if error:
            raise ValueError(error)
        resolved_time_limit = classical_time_limit_seconds

    return ClassicalSolveOptions(
        classical_solver_id=classical_solver_id,
        time_limit_seconds=resolved_time_limit,
        mip_gap_tolerance=None,
        threads=1,
        model_export_enabled=model_export_enabled,
        primal_feasibility_tolerance=1e-6,
        integrality_tolerance=1e-6,
        objective_recomputation_absolute_tolerance=1e-6,
        objective_recomputation_relative_tolerance=1e-4,
        postcheck_mode=PostcheckMode.STRICT,
        random_seed=random_seed,
        model_export_path=model_export_path,
    )


def _build_resolved_run_config(
    run_id: str,
    *,
    reduction_policy: ReductionPolicy,
    mis_solver_id: str,
    mis_execution: MISExecutionOptions,
    classical_solve: ClassicalSolveOptions,
    policy_source: str = "sharpe_portfolio_experiment",
) -> ResolvedRunConfig:
    """Build complete ResolvedRunConfig with correct structure."""
    return ResolvedRunConfig(
        schema_version="1.0",
        reduction=reduction_policy,
        lambda_edge=2.0,
        lambda_edge_policy=LambdaEdgePolicy("standard", "1", 2.0),
        allow_noncertifying_penalty=False,
        mis_solver_id=mis_solver_id,
        mis_execution=mis_execution,
        classical_solve=classical_solve,
        run_identity=RunIdentity(run_id),
        policy_provenance=PolicyProvenance(
            policy_source=policy_source,
            policy_id=EXPERIMENT_ID,
            policy_version="1",
        ),
    )


def run_sharpe_portfolio_experiment(
    run_id: str,
    *,
    # Data configuration
    csv_path: str | Path = DEFAULT_SP500_CSV,
    asset_count: int | None = None,
    explicit_tickers: Sequence[str] | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    return_convention: str = "log",
    annualization_factor: int = 252,
    # Problem configuration
    risk_free_rate: float = 0.0,
    upper_bound: float = 1.0,
    lower_bound: float = 0.0,
    sector_constraints: SectorConstraints | None = None,
    max_positions: int | None = None,
    min_selected_assets: int | None = None,
    lower_bounds: Mapping[str, float] | None = None,
    # Graph configuration
    graph_policy: SharpeGraphPolicy | None = None,
    # Solver configuration
    mis_solver_id: str = "local_greedy",
    classical_solver_id: str = "scip",
    classical_time_limit_seconds: float | None = None,
    mis_num_reads: int | None = None,
    pasqal_shots: int | None = None,
    mis_num_sweeps: int | None = None,
    mis_embedding_profile: str | None = None,
    # Reduction configuration
    reduction_policy: ReductionPolicy | None = None,
    # Export configuration
    model_export_enabled: bool = False,
    model_export_path: str | None = None,
    # Output configuration
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    # Universe selection
    selection_order: str = "alphabetical",
    random_seed: int | None = None,
) -> ExperimentRun:
    """Run a Sharpe portfolio experiment with QReduce.

    Args:
        run_id: Unique identifier for this run.
        csv_path: Path to S&P500 price CSV file.
        asset_count: Number of assets to select.
        explicit_tickers: Specific tickers to include.
        start_date: Optional start date for price data.
        end_date: Optional end date for price data.
        return_convention: "simple" or "log".
        annualization_factor: Trading days per year.
        risk_free_rate: Risk-free rate. Must be 0.0 in current version.
        upper_bound: Maximum weight per asset.
        lower_bound: Minimum weight per selected asset.
        sector_constraints: Optional sector diversification constraints.
        max_positions: Optional cardinality constraint.
        min_selected_assets: Optional minimum number of selected assets.
        lower_bounds: Optional per-ticker minimum weights instead of a positive scalar.
        graph_policy: MWIS graph construction policy.
        mis_solver_id: MIS solver ID ("local_greedy" or "dwave_simulated_annealing").
        classical_solver_id: Classical solver ID ("scip" or "cplex").
        classical_time_limit_seconds: Per-solve time limit. None=default (60s), 0=no limit.
        mis_num_reads: D-Wave num_reads parameter.
        pasqal_shots: Local Pasqal shot count.
        mis_num_sweeps: D-Wave num_sweeps parameter.
        mis_embedding_profile: D-Wave embedding profile.
        reduction_policy: Reduction policy configuration.
        model_export_enabled: Whether to export the classical model.
        model_export_path: Custom export path for model.
        output_root: Root directory for artifacts.
        selection_order: Ticker selection order.
        random_seed: Random seed for reproducibility.

    Returns:
        ExperimentRun with result and artifact directory.

    Raises:
        ValueError: If risk_free_rate != 0.0, or if D-Wave parameters
            are used with non-D-Wave solver.
    """
    # Validate risk-free rate (must be 0 in current version)
    if risk_free_rate != 0.0:
        raise ValueError(
            "risk_free_rate must be 0.0 in current version. "
            "Non-zero risk-free rate requires coordinated changes to "
            "return filtering, normalization, scale bounds, and metrics."
        )

    logger.info("Building Sharpe portfolio inputs for run_id=%s", run_id)

    # Build inputs
    inputs = build_sharpe_portfolio_inputs(
        csv_path=csv_path,
        asset_count=asset_count,
        explicit_tickers=explicit_tickers,
        start_date=start_date,
        end_date=end_date,
        return_convention=return_convention,
        annualization_factor=annualization_factor,
        risk_free_rate=risk_free_rate,
        upper_bound=upper_bound,
        lower_bound=lower_bound,
        sector_constraints=sector_constraints,
        max_positions=max_positions,
        min_selected_assets=min_selected_assets,
        lower_bounds=lower_bounds,
        graph_policy=graph_policy,
        selection_order=selection_order,
        random_seed=random_seed,
    )

    # Use default reduction policy if not provided
    if reduction_policy is None:
        reduction_policy = default_reduction_policy(
            inputs.problem.ticker_count,
            has_cardinality=inputs.problem.has_selection_binaries,
            min_selected_assets=inputs.problem.min_selected_assets,
        )
    _validate_reduction_cardinality(reduction_policy, inputs.problem.min_selected_assets)

    # Build execution options
    mis_execution = _build_mis_execution_options(
        mis_num_reads=mis_num_reads,
        pasqal_shots=pasqal_shots,
        mis_num_sweeps=mis_num_sweeps,
        mis_embedding_profile=mis_embedding_profile,
        mis_solver_id=mis_solver_id,
    )

    classical_solve = _build_classical_solve_options(
        classical_solver_id=classical_solver_id,
        classical_time_limit_seconds=classical_time_limit_seconds,
        model_export_enabled=model_export_enabled,
        model_export_path=model_export_path,
    )

    # Build run config
    config = _build_resolved_run_config(
        run_id,
        reduction_policy=reduction_policy,
        mis_solver_id=mis_solver_id,
        mis_execution=mis_execution,
        classical_solve=classical_solve,
    )

    # Build experiment metadata
    metadata: dict[str, object] = {
        "experiment_type": EXPERIMENT_ID,
        "source_dataset": inputs.source_dataset.to_dict(),
        "return_statistics": inputs.return_statistics.to_dict(),
        "preprocessing_config": dict(inputs.preprocessing_config),
        "graph_policy": inputs.graph_policy.to_dict(),
        "universe_selection": {
            "method": inputs.universe_selection.method,
            "asset_count": inputs.universe_selection.asset_count,
            "explicit_tickers": list(inputs.universe_selection.explicit_tickers or []),
            "random_seed": inputs.universe_selection.random_seed,
            "selection_order": inputs.universe_selection.selection_order,
        },
        "problem_summary": {
            "ticker_count": inputs.problem.ticker_count,
            "sector_count": len(set(inputs.problem.sectors.values())),
            "max_positions": inputs.problem.max_positions,
            "min_selected_assets": inputs.problem.min_selected_assets,
            "lower_bound": inputs.problem.lower_bound,
            "has_sector_constraints": inputs.problem.sector_constraints is not None,
        },
    }

    logger.info(
        "Running Sharpe portfolio experiment: tickers=%d, max_rounds=%d",
        inputs.problem.ticker_count,
        reduction_policy.max_reduction_rounds,
    )

    # Run experiment via shared runner
    return run_experiment(
        EXPERIMENT_ID,
        inputs.problem,
        inputs.adapter,
        config,
        mis_solver_registry=builtin_mis_solver_registry(),
        classical_solver_registry=builtin_classical_solver_registry(),
        output_root=output_root,
        experiment_metadata=metadata,
    )


def _validate_reduction_cardinality(policy: ReductionPolicy, minimum: int | None) -> None:
    if policy.max_reduction_rounds > 0 and policy.candidate_domain_max_items < (minimum or 0):
        raise ValueError("candidate_domain_max_items must be at least min_selected_assets.")


def run_sharpe_portfolio_from_inputs(
    run_id: str,
    inputs: SharpePortfolioInputs,
    *,
    reduction_policy: ReductionPolicy | None = None,
    mis_solver_id: str = "local_greedy",
    classical_solver_id: str = "scip",
    classical_time_limit_seconds: float | None = None,
    mis_num_reads: int | None = None,
    pasqal_shots: int | None = None,
    mis_num_sweeps: int | None = None,
    mis_embedding_profile: str | None = None,
    model_export_enabled: bool = False,
    model_export_path: str | None = None,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
) -> ExperimentRun:
    """Run experiment from pre-built inputs.

    This is useful for benchmark comparisons where you want to reuse
    the same inputs across multiple configurations.

    Args:
        run_id: Unique identifier for this run.
        inputs: Pre-built SharpePortfolioInputs.
        reduction_policy: Reduction policy configuration.
        mis_solver_id: MIS solver ID.
        classical_solver_id: Classical solver ID.
        classical_time_limit_seconds: Per-solve time limit. None=default, 0=no limit.
        mis_num_reads: D-Wave num_reads parameter.
        pasqal_shots: Local Pasqal shot count.
        mis_num_sweeps: D-Wave num_sweeps parameter.
        mis_embedding_profile: D-Wave embedding profile.
        model_export_enabled: Whether to export the classical model.
        model_export_path: Custom export path for model.
        output_root: Root directory for artifacts.

    Returns:
        ExperimentRun with result and artifact directory.
    """
    # Use default reduction policy if not provided
    if reduction_policy is None:
        reduction_policy = default_reduction_policy(
            inputs.problem.ticker_count,
            has_cardinality=inputs.problem.has_selection_binaries,
            min_selected_assets=inputs.problem.min_selected_assets,
        )
    _validate_reduction_cardinality(reduction_policy, inputs.problem.min_selected_assets)

    # Build execution options
    mis_execution = _build_mis_execution_options(
        mis_num_reads=mis_num_reads,
        pasqal_shots=pasqal_shots,
        mis_num_sweeps=mis_num_sweeps,
        mis_embedding_profile=mis_embedding_profile,
        mis_solver_id=mis_solver_id,
    )

    classical_solve = _build_classical_solve_options(
        classical_solver_id=classical_solver_id,
        classical_time_limit_seconds=classical_time_limit_seconds,
        model_export_enabled=model_export_enabled,
        model_export_path=model_export_path,
    )

    # Build run config
    config = _build_resolved_run_config(
        run_id,
        reduction_policy=reduction_policy,
        mis_solver_id=mis_solver_id,
        mis_execution=mis_execution,
        classical_solve=classical_solve,
        policy_source="sharpe_portfolio_from_inputs",
    )

    # Build metadata
    metadata: dict[str, object] = {
        "experiment_type": EXPERIMENT_ID,
        "source_dataset": inputs.source_dataset.to_dict(),
        "return_statistics": inputs.return_statistics.to_dict(),
        "graph_policy": inputs.graph_policy.to_dict(),
    }

    return run_experiment(
        EXPERIMENT_ID,
        inputs.problem,
        inputs.adapter,
        config,
        mis_solver_registry=builtin_mis_solver_registry(),
        classical_solver_registry=builtin_classical_solver_registry(),
        output_root=output_root,
        experiment_metadata=metadata,
    )
