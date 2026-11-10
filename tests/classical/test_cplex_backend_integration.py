"""Optional live end-to-end test for portfolio, local greedy MWIS, and CPLEX."""

import importlib.util

import pytest

from qreduce.domains.portfolio import (
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
    """Build the deterministic configuration for the reference live integration path."""

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
            PortfolioGraphPolicy("integration-policy", "1", 0.25)
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
