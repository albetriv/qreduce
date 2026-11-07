"""Optional live CPLEX integration test for the demonstrative residual MIQP."""

import importlib.util

import pytest

from qreduce.classical import ClassicalSolveRequest, CplexClassicalBackend
from qreduce.domains.portfolio import (
    MeanVariancePortfolioAdapter,
    PortfolioGraphPolicy,
    PortfolioProblem,
)
from qreduce.domains.portfolio.postcheck import validate_portfolio_solution
from qreduce.models import ClassicalSolveOptions
from qreduce.status import ClassicalSolverStatus, PostcheckMode

pytestmark = pytest.mark.skipif(importlib.util.find_spec("cplex") is None, reason="Optional CPLEX binding is not installed.")


def test_cplex_solves_and_postcheck_accepts_small_residual_portfolio(portfolio_problem: PortfolioProblem) -> None:
    """Run only where a CPLEX binding and usable local license are available."""

    adapter = MeanVariancePortfolioAdapter(PortfolioGraphPolicy("integration-policy", "1", 0.25))
    retained = ("asset-a", "asset-b")
    residual_problem = adapter.restrict_problem(
        portfolio_problem,
        retained,
        adapter.build_fixing_manifest(portfolio_problem, retained),
    )
    request = ClassicalSolveRequest("cplex-integration", 0, 10.0, 10.0, None, 7, 1, False)

    result = CplexClassicalBackend().solve(residual_problem, request)

    if result.classical_solver_status is ClassicalSolverStatus.UNAVAILABLE:
        pytest.skip(result.diagnostic_message or "CPLEX runtime is unavailable, likely due to licensing.")
    assert result.solver_claimed_feasible is True, result.diagnostic_message
    postcheck = validate_portfolio_solution(
        portfolio_problem,
        result.variable_values,
        residual_problem.fixing_manifest,
        ClassicalSolveOptions(
            backend_name="cplex",
            time_limit_seconds=10.0,
            mip_gap_tolerance=None,
            threads=1,
            model_export_enabled=False,
            primal_feasibility_tolerance=1e-6,
            integrality_tolerance=1e-6,
            objective_recomputation_absolute_tolerance=1e-6,
            objective_recomputation_relative_tolerance=1e-6,
            postcheck_mode=PostcheckMode.SOLVER_TOLERANCE_ALIGNED,
        ),
        solver_objective_value=result.objective_value,
    )
    assert postcheck.postcheck_feasible is True, postcheck.failure_reasons