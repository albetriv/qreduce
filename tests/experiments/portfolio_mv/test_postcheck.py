"""Tests for independent mean-variance portfolio post-checking."""

from dataclasses import replace

import pytest

from qreduce.experiments.portfolio_mv import (
    MeanVariancePortfolioAdapter,
    PortfolioGraphPolicy,
    PortfolioProblem,
)
from qreduce.experiments.portfolio_mv.postcheck import validate_portfolio_solution
from qreduce.models import ClassicalSolveOptions
from qreduce.status import PostcheckMode


def make_tolerances() -> ClassicalSolveOptions:
    return ClassicalSolveOptions(
        classical_solver_id="cplex",
        time_limit_seconds=10.0,
        mip_gap_tolerance=None,
        threads=None,
        model_export_enabled=False,
        primal_feasibility_tolerance=1e-8,
        integrality_tolerance=1e-8,
        objective_recomputation_absolute_tolerance=1e-8,
        objective_recomputation_relative_tolerance=1e-8,
        postcheck_mode=PostcheckMode.STRICT,
    )


def make_manifest(problem: PortfolioProblem):
    adapter = MeanVariancePortfolioAdapter(PortfolioGraphPolicy("policy", "1", 0.25, edge_mode="correlation_only"))
    return adapter.build_fixing_manifest(problem, ("asset-a", "asset-b"))


def valid_values() -> dict[str, float]:
    return {
        "delta__asset-a": 1.0,
        "x__asset-a": 0.6,
        "delta__asset-b": 1.0,
        "x__asset-b": 0.4,
        "delta__asset-c": 0.0,
        "x__asset-c": 0.0,
    }


def test_valid_solution_passes_and_recomputes_objective(portfolio_problem: PortfolioProblem) -> None:
    """The solver may select a feasible subset inside the retained candidate domain."""
    result = validate_portfolio_solution(portfolio_problem, valid_values(), make_manifest(portfolio_problem), make_tolerances())

    assert result.postcheck_feasible is True
    assert result.fixed_variable_compliance is True
    assert result.original_constraint_compliance is True
    assert result.integrality_compliance is True
    assert result.objective_recomputed is not None


def test_nonunit_risk_aversion_recomputes_and_checks_solver_objective(portfolio_problem):
    """Use independent expanded arithmetic, including both covariance cross terms."""
    problem = replace(portfolio_problem, risk_aversion=2.5)
    variance = 0.6**2 * 0.04 + 2 * 0.6 * 0.4 * 0.018 + 0.4**2 * 0.09
    expected_return = 0.6 * 0.10 + 0.4 * 0.08
    expected = 2.5 * variance - expected_return
    for objective, compliant in [(expected, True), (variance - expected_return, False)]:
        result = validate_portfolio_solution(
            problem, valid_values(), make_manifest(problem), make_tolerances(),
            solver_objective_value=objective,
        )
        assert result.objective_recomputed == pytest.approx(expected)
        assert result.solver_objective_compliance is compliant
        assert result.postcheck_feasible is compliant


def test_fixing_integrality_and_budget_failures_are_independently_observable(portfolio_problem: PortfolioProblem) -> None:
    """No invalid residual solution is adopted merely because a solver reported one."""
    values = valid_values()
    values.update({"delta__asset-a": 0.5, "x__asset-b": 0.5, "x__asset-c": 0.1})
    result = validate_portfolio_solution(portfolio_problem, values, make_manifest(portfolio_problem), make_tolerances())

    assert result.postcheck_feasible is False
    assert result.fixed_variable_compliance is False
    assert result.integrality_compliance is False
    assert result.original_constraint_compliance is False
    assert "binary_integrality_violation:asset-a" in result.failure_reasons
    assert "fixing_violation:asset-c:x__asset-c" in result.failure_reasons
    assert "budget_violation" in result.failure_reasons


def test_solver_objective_mismatch_fails_postcheck(portfolio_problem: PortfolioProblem) -> None:
    """Objective recomputation uses the configured absolute and relative tolerances."""
    result = validate_portfolio_solution(
        portfolio_problem,
        valid_values(),
        make_manifest(portfolio_problem),
        replace(make_tolerances(), objective_recomputation_absolute_tolerance=0.0),
        solver_objective_value=999.0,
    )

    assert result.postcheck_feasible is False
    assert result.solver_objective_compliance is False
    assert "objective_recomputation_mismatch" in result.failure_reasons