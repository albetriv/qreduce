"""Optional live test for the portfolio experiment's local MIS and CPLEX choices."""

import importlib.util
from dataclasses import replace

import pytest

from qreduce.experiments.portfolio_domain import (
    MeanVariancePortfolioAdapter,
    PortfolioGraphPolicy,
    PortfolioProblem,
)
from qreduce.models import (
    ClassicalSolveOptions,
    LambdaEdgePolicy,
    MISExecutionOptions,
    ReductionPolicy,
    ResolvedRunConfig,
    RunIdentity,
)
from qreduce.pipeline import run_single_pass
from qreduce.status import (
    ClassicalSolverStatus,
    PostcheckMode,
    RunStatus,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.requires_cplex,
    pytest.mark.skipif(
        importlib.util.find_spec("cplex") is None,
        reason="Optional CPLEX binding is not installed.",
    ),
]


def make_live_config() -> ResolvedRunConfig:
    """Build the deterministic configuration for this live experiment path."""

    return ResolvedRunConfig(
        schema_version="1.0",
        reduction=ReductionPolicy(1, 1, 3, 1, 0.1, 3, 60.0),
        lambda_edge=2.0,
        lambda_edge_policy=LambdaEdgePolicy("standard", "1", 2.0),
        allow_noncertifying_penalty=False,
        mis_solver_id="local_greedy",
        mis_execution=MISExecutionOptions(1, 17, 1, False, 0, 0.0, 20),
        classical_solve=ClassicalSolveOptions(
            classical_solver_id="cplex",
            time_limit_seconds=10.0,
            mip_gap_tolerance=None,
            threads=1,
            model_export_enabled=False,
            primal_feasibility_tolerance=1e-6,
            integrality_tolerance=1e-6,
            objective_recomputation_absolute_tolerance=1e-6,
            objective_recomputation_relative_tolerance=1e-6,
            postcheck_mode=PostcheckMode.SOLVER_TOLERANCE_ALIGNED,
            random_seed=7,
        ),
        run_identity=RunIdentity("cplex-integration"),
    )


def test_cplex_solves_portfolio_after_local_greedy_reduction(
    portfolio_problem: PortfolioProblem,
) -> None:
    """Run only where a CPLEX binding and usable local license are available."""

    result = run_single_pass(
        portfolio_problem,
        MeanVariancePortfolioAdapter(
            PortfolioGraphPolicy("integration-policy", "1", 0.25, edge_mode="correlation_only")
        ),
        make_live_config(),
    )

    if (
        result.classical_result is not None
        and result.classical_result.classical_solver_status
        is ClassicalSolverStatus.UNAVAILABLE
    ):
        pytest.skip(
            result.classical_result.diagnostic_message
            or "CPLEX runtime is unavailable, likely due to licensing."
        )
    assert result.run_result.run_status in {
        RunStatus.SUCCESS,
        RunStatus.PARTIAL_SUCCESS,
    }
    assert result.run_result.adoption_status.value == "adopted"
    assert result.retained_item_ids
    assert result.classical_result is not None
    assert result.classical_result.requested_solver_id == "cplex"
    assert result.classical_result.effective_solver_id == "cplex"


def test_cplex_exports_residual_model(portfolio_problem, tmp_path) -> None:
    path = tmp_path / "residual.lp"
    config = make_live_config()
    config = replace(config, classical_solve=replace(
        config.classical_solve, model_export_enabled=True, model_export_path=str(path)
    ))
    result = run_single_pass(
        portfolio_problem,
        MeanVariancePortfolioAdapter(PortfolioGraphPolicy("integration-policy", "1", 0.25, edge_mode="correlation_only")),
        config,
    )
    if result.classical_result and result.classical_result.classical_solver_status is ClassicalSolverStatus.UNAVAILABLE:
        pytest.skip(result.classical_result.diagnostic_message or "CPLEX runtime unavailable")
    assert result.classical_result is not None
    assert result.classical_result.model_export_path == str(path)
    assert path.is_file() and path.stat().st_size > 0
