"""Tests for independent mean-variance portfolio post-checking."""

from dataclasses import replace

from qreduce.domains.portfolio import (
    MeanVariancePortfolioAdapter,
    PortfolioGraphPolicy,
    PortfolioProblem,
)
from qreduce.domains.portfolio.postcheck import validate_portfolio_solution
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
    adapter = MeanVariancePortfolioAdapter(PortfolioGraphPolicy("policy", "1", 0.25))
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