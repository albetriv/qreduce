"""Shared synthetic portfolio inputs and experiment configuration."""

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from qreduce.config import (
    DEFAULT_CLASSICAL_TIME_LIMIT_SECONDS,
    DEFAULT_END_TO_END_BUDGET_SECONDS,
    validate_timeout_value,
)
from qreduce.experiments.portfolio_mv.adapter import MeanVariancePortfolioAdapter
from qreduce.experiments.portfolio_mv.models import (
    PortfolioGraphPolicy,
    PortfolioProblem,
)
from qreduce.experiments.portfolio_mv.validation import validate_risk_aversion
from qreduce.models import (
    ClassicalSolveOptions,
    LambdaEdgePolicy,
    MISExecutionOptions,
    ReductionPolicy,
    ResolvedRunConfig,
    RunIdentity,
)
from qreduce.status import PostcheckMode

if TYPE_CHECKING:
    from qreduce.experiments.portfolio_mv.models import (
        SyntheticPortfolioGenerationPolicy,
    )

SYNTHETIC_PORTFOLIO_EXPERIMENT_ID = "synthetic-portfolio-single-pass"
DEFAULT_PORTFOLIO_OUTPUT_ROOT = "outputs/portfolio_mv"


# Re-export for backward compatibility and convenience
__all__ = [
    "DEFAULT_PORTFOLIO_OUTPUT_ROOT",
    "SYNTHETIC_PORTFOLIO_EXPERIMENT_ID",
    "SyntheticPortfolioInputs",
    "build_synthetic_portfolio_inputs",
    "default_graph_policy",
    "default_reduction_policy",
    "validate_risk_aversion",
]


def default_reduction_policy(asset_count: int = 30) -> ReductionPolicy:
    """Create the default reduction policy for portfolio experiments.

    This is a lightweight factory that does not generate portfolio data.
    Use this when you only need the policy defaults without building
    the full experiment inputs.

    Args:
        asset_count: Number of assets, used to scale candidate_domain_max_items.
            Must be >= 6. Default is 30.

    Returns:
        ReductionPolicy with default parameters for portfolio experiments.

    Raises:
        ValueError: If asset_count < 6.
    """
    if asset_count < 6:
        raise ValueError("asset_count must be at least 6 for meaningful experiments.")

    # Scale candidate_domain_max_items proportionally to asset_count
    # For 30 assets: max_items = 18 (60%)
    # Minimum is 3 to allow meaningful reduction
    candidate_domain_max_items = max(3, (asset_count * 3) // 5)

    return ReductionPolicy(
        max_reduction_rounds=1,
        candidate_domain_min_items=1,
        candidate_domain_max_items=candidate_domain_max_items,
        num_source_mis_candidates=1,
        min_reduction_ratio=0.1,
        target_binary_variables=3,
        max_end_to_end_runtime_seconds=DEFAULT_END_TO_END_BUDGET_SECONDS,
    )


def default_graph_policy(
    edge_mode: str = "near_duplicate",
    *,
    correlation_threshold: float = 0.90,
    near_duplicate_max_relative_return_difference: float = 0.10,
    near_duplicate_max_relative_variance_difference: float = 0.10,
) -> PortfolioGraphPolicy:
    """Create a default graph policy with the specified edge mode.

    Args:
        edge_mode: Either "correlation_only" or "near_duplicate"
        correlation_threshold: Absolute correlation threshold for edges
        near_duplicate_max_relative_return_difference: Max relative return diff (near_duplicate only)
        near_duplicate_max_relative_variance_difference: Max relative variance diff (near_duplicate only)

    Returns:
        PortfolioGraphPolicy configured with the specified parameters
    """
    return PortfolioGraphPolicy(
        policy_id=f"synthetic-portfolio-{edge_mode}",
        policy_version="1",
        correlation_absolute_threshold=correlation_threshold,
        edge_mode=edge_mode,  # type: ignore[arg-type]
        near_duplicate_max_relative_return_difference=near_duplicate_max_relative_return_difference,
        near_duplicate_max_relative_variance_difference=near_duplicate_max_relative_variance_difference,
    )


@dataclass(frozen=True, slots=True)
class SyntheticPortfolioInputs:
    """All domain and kernel inputs for the repository's synthetic portfolio experiment."""

    problem: PortfolioProblem
    graph_policy: PortfolioGraphPolicy
    adapter: MeanVariancePortfolioAdapter
    config: ResolvedRunConfig
    generation_policy: "SyntheticPortfolioGenerationPolicy | None" = None


def build_synthetic_portfolio_inputs(
    run_id: str,
    *,
    asset_count: int = 30,
    risk_aversion: float = 1.0,
    generation_policy: "SyntheticPortfolioGenerationPolicy | None" = None,
    graph_policy: PortfolioGraphPolicy | None = None,
    mis_solver_id: str = "local_greedy",
    classical_solver_id: str = "scip",
    classical_time_limit_seconds: float | None = None,
    mis_num_reads: int | None = None,
    pasqal_shots: int | None = None,
    pasqal_emulator_service: str | None = None,
    mis_num_sweeps: int | None = None,
    mis_embedding_profile: str | None = None,
    lower_bound: float = 0.0,
    upper_bound: float = 0.7,
    min_selected_assets: int | None = None,
    max_selected_assets: int | None = None,
) -> SyntheticPortfolioInputs:
    """Build deterministic inputs with explicit optional solver selections.

    Args:
        run_id: Unique identifier for the run.
        asset_count: Number of assets in the synthetic portfolio. Must be >= 6.
            Default is 30 for meaningful reduction experiments.
        risk_aversion: Risk aversion coefficient for the mean-variance objective.
            Controls the trade-off between expected return and variance.
            Must be finite and strictly positive. Default is 1.0.
        generation_policy: Optional generation policy. If None, uses default_generation_policy().
        graph_policy: Optional graph policy. If None, uses default_graph_policy() with near_duplicate.
        mis_solver_id: MIS solver to use.
        classical_solver_id: Classical solver to use.
        classical_time_limit_seconds: Maximum time per classical solve invocation.
            A value of 0 means no per-solve time limit (solver runs until
            completion or end-to-end budget exhaustion). If None, uses the
            default of 60 seconds. The limit restarts for each solve.
        mis_num_reads: Optional D-Wave num_reads parameter.
        pasqal_shots: Local Pasqal shot count; defaults to 100 for Pasqal.
        pasqal_emulator_service: Cloud emulator service for pasqal_cloud_emulator.
            Currently only 'emu_free' is supported. Requires explicit consent
            for potential costs.
        mis_num_sweeps: Optional D-Wave num_sweeps parameter.
        mis_embedding_profile: Local embedding profile for D-Wave simulated annealing.
            Constrains sampling to hardware-like topology without QPU access.
            Valid values: 'none' (default), 'pegasus_p16', 'zephyr_z12'.
            Requires mis_solver_id='dwave_simulated_annealing'.
        lower_bound: Minimum investment per selected asset. Default 0.0.
        upper_bound: Maximum investment per selected asset. Default 0.7.
        min_selected_assets: Optional minimum number of assets to select (cardinality).
        max_selected_assets: Optional maximum number of assets to select (cardinality).

    Returns:
        SyntheticPortfolioInputs with problem, adapter, and configuration.

    Raises:
        TypeError: If risk_aversion is None, boolean, or non-numeric type.
        ValueError: If asset_count < 6, if risk_aversion is NaN, infinity,
            zero, or negative, if D-Wave parameters are used with a non-D-Wave
            solver, if classical_time_limit_seconds is negative, or if embedding
            profile is incompatible with the solver.
    """
    from qreduce.experiments.portfolio_mv.generator import (
        default_generation_policy,
        generate_portfolio_data,
    )

    if asset_count < 6:
        raise ValueError("asset_count must be at least 6 for meaningful experiments.")

    # Validate risk_aversion - raises TypeError for invalid types, ValueError for invalid values
    validate_risk_aversion(risk_aversion)

    # Validate and resolve classical time limit - reject booleans, NaN, infinity
    if classical_time_limit_seconds is None:
        resolved_time_limit = DEFAULT_CLASSICAL_TIME_LIMIT_SECONDS
    else:
        error = validate_timeout_value(classical_time_limit_seconds, "classical_time_limit_seconds")
        if error:
            raise ValueError(error)
        resolved_time_limit = classical_time_limit_seconds

    # Use provided policies or defaults
    if generation_policy is None:
        generation_policy = default_generation_policy(asset_count)
    elif generation_policy.asset_count != asset_count:
        raise ValueError(
            f"generation_policy.asset_count ({generation_policy.asset_count}) "
            f"does not match asset_count ({asset_count})."
        )

    if graph_policy is None:
        graph_policy = default_graph_policy()

    portfolio_data = generate_portfolio_data(
        generation_policy,
        risk_aversion=risk_aversion,
        lower_bound=lower_bound,
        upper_bound=upper_bound,
        min_selected_assets=min_selected_assets,
        max_selected_assets=max_selected_assets,
    )
    problem = portfolio_data.to_problem()

    # Use the shared lightweight factory for reduction policy defaults
    reduction = default_reduction_policy(asset_count)

    config = ResolvedRunConfig(
        schema_version="1.0",
        reduction=reduction,
        lambda_edge=2.0,
        lambda_edge_policy=LambdaEdgePolicy("standard", "1", 2.0),
        allow_noncertifying_penalty=False,
        mis_solver_id=mis_solver_id,
        mis_execution=MISExecutionOptions(
            1,
            # Pasqal backends don't support random_seed
            None if mis_solver_id in {"pasqal_local", "pasqal_cloud_emulator"} else 17,
            1, False, 0, 0.0, 20
        ),
        classical_solve=ClassicalSolveOptions(
            classical_solver_id=classical_solver_id,
            time_limit_seconds=resolved_time_limit,
            mip_gap_tolerance=None,
            threads=1,
            model_export_enabled=False,
            primal_feasibility_tolerance=1e-6,
            integrality_tolerance=1e-6,
            objective_recomputation_absolute_tolerance=1e-6,
            objective_recomputation_relative_tolerance=1e-6,
            postcheck_mode=PostcheckMode.STRICT,
            random_seed=7,
        ),
        run_identity=RunIdentity(run_id),
    )
    # Handle pasqal_shots for Pasqal backends (local and cloud)
    if pasqal_shots is not None and mis_solver_id not in {"pasqal_local", "pasqal_cloud_emulator"}:
        raise ValueError("pasqal_shots requires mis_solver_id='pasqal_local' or 'pasqal_cloud_emulator'.")
    if mis_solver_id == "pasqal_local":
        shots = 100 if pasqal_shots is None else pasqal_shots
        _require_positive_int(shots, "pasqal_shots")
        config = replace(config, mis_execution=replace(
            config.mis_execution, max_distinct_samples=shots, provider_parameters={"shots": shots}
        ))

    # Handle Pasqal Cloud emulator
    if pasqal_emulator_service is not None:
        if mis_solver_id != "pasqal_cloud_emulator":
            raise ValueError(
                "pasqal_emulator_service requires mis_solver_id='pasqal_cloud_emulator'."
            )
        valid_services = ("emu_free",)
        if pasqal_emulator_service not in valid_services:
            raise ValueError(
                f"Invalid pasqal_emulator_service: {pasqal_emulator_service!r}. "
                f"Valid values: {', '.join(valid_services)}"
            )
        # Explicit selection of the only supported (free) service.
        compilation_params: dict[str, object] = {
            "_emulator_service": pasqal_emulator_service,
        }
        shots = pasqal_shots if pasqal_shots is not None else 100
        _require_positive_int(shots, "pasqal_shots")
        config = replace(
            config,
            mis_execution=replace(
                config.mis_execution,
                max_distinct_samples=shots,
                provider_parameters={"shots": shots},
                compilation_parameters=compilation_params,
            ),
        )
    elif mis_solver_id == "pasqal_cloud_emulator":
        raise ValueError(
            "pasqal_cloud_emulator requires explicit --pasqal-emulator-service selection."
        )

    if mis_num_reads is not None or mis_num_sweeps is not None:
        if mis_solver_id != "dwave_simulated_annealing":
            raise ValueError(
                "mis_num_reads and mis_num_sweeps require "
                "mis_solver_id='dwave_simulated_annealing'."
            )
        provider_parameters: dict[str, object] = {}
        if mis_num_reads is not None:
            _require_positive_int(mis_num_reads, "mis_num_reads")
            provider_parameters["num_reads"] = mis_num_reads
        if mis_num_sweeps is not None:
            _require_positive_int(mis_num_sweeps, "mis_num_sweeps")
            provider_parameters["num_sweeps"] = mis_num_sweeps
        config = replace(
            config,
            mis_execution=replace(
                config.mis_execution,
                provider_parameters=provider_parameters,
            ),
        )

    # Handle embedding profile for D-Wave simulated annealing
    if mis_embedding_profile is not None and mis_embedding_profile != "none":
        if mis_solver_id != "dwave_simulated_annealing":
            raise ValueError(
                f"mis_embedding_profile='{mis_embedding_profile}' requires "
                "mis_solver_id='dwave_simulated_annealing'."
            )
        valid_profiles = ("none", "pegasus_p16", "zephyr_z12")
        if mis_embedding_profile not in valid_profiles:
            raise ValueError(
                f"Invalid mis_embedding_profile: {mis_embedding_profile!r}. "
                f"Valid values: {', '.join(valid_profiles)}"
            )
        compilation_parameters: dict[str, object] = {"embedding_profile": mis_embedding_profile}
        config = replace(
            config,
            mis_execution=replace(
                config.mis_execution,
                compilation_parameters=compilation_parameters,
            ),
        )

    return SyntheticPortfolioInputs(
        problem=problem,
        graph_policy=graph_policy,
        adapter=MeanVariancePortfolioAdapter(graph_policy),
        config=config,
        generation_policy=generation_policy,
    )


def _require_positive_int(value: int, field: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{field} must be an integer greater than zero.")

