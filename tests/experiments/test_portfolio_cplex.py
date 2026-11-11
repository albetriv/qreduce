"""Tests for lazy CPLEX backend failure behavior without requiring CPLEX."""

from qreduce.classical import ClassicalSolveRequest, CplexClassicalBackend
from qreduce.experiments.portfolio_domain import (
    MeanVariancePortfolioAdapter,
    PortfolioGraphPolicy,
    PortfolioProblem,
)
from qreduce.status import ClassicalSolverStatus, TerminalReason


def make_request(*, remaining_budget: float = 10.0) -> ClassicalSolveRequest:
    return ClassicalSolveRequest("run-001", 0, 10.0, remaining_budget, None, 7, 1, False, requested_solver_id="cplex")


def make_residual_problem(problem: PortfolioProblem):
    adapter = MeanVariancePortfolioAdapter(PortfolioGraphPolicy("policy", "1", 0.25))
    retained = ("asset-a", "asset-b")
    return adapter.restrict_problem(problem, retained, adapter.build_fixing_manifest(problem, retained))


def test_missing_cplex_binding_returns_explicit_unavailable(monkeypatch, portfolio_problem: PortfolioProblem) -> None:
    """CPLEX absence is observable and never selects an alternate solver."""

    def raise_missing_binding(module_name: str):
        assert module_name == "cplex"
        raise ModuleNotFoundError("No module named 'cplex'", name="cplex")

    monkeypatch.setattr("qreduce.classical.cplex_backend._import_module", raise_missing_binding)

    result = CplexClassicalBackend().solve(make_residual_problem(portfolio_problem), make_request())

    assert result.classical_solver_status is ClassicalSolverStatus.UNAVAILABLE
    assert result.terminal_reason is TerminalReason.CLASSICAL_BACKEND_UNAVAILABLE
    assert result.solver_claimed_feasible is False


def test_nonpositive_budget_skips_even_the_lazy_cplex_import(monkeypatch, portfolio_problem: PortfolioProblem) -> None:
    """Budget exhaustion prevents model creation and optional runtime import."""

    def unexpected_import(module_name: str):
        raise AssertionError(f"unexpected optional import: {module_name}")

    monkeypatch.setattr("qreduce.classical.cplex_backend._import_module", unexpected_import)

    result = CplexClassicalBackend().solve(make_residual_problem(portfolio_problem), make_request(remaining_budget=0.0))

    assert result.classical_solver_status is ClassicalSolverStatus.NOT_RUN
    assert result.terminal_reason is TerminalReason.END_TO_END_TIME_BUDGET_EXHAUSTED


def test_unusable_cplex_license_returns_explicit_unavailable(monkeypatch, portfolio_problem: PortfolioProblem) -> None:
    """An importable binding without a usable license is not reported as a solver failure."""

    class LicenseFailingCplexModule:
        class Cplex:
            def __init__(self) -> None:
                raise RuntimeError("CPLEX license is unavailable")

    monkeypatch.setattr("qreduce.classical.cplex_backend._import_module", lambda _: LicenseFailingCplexModule)

    result = CplexClassicalBackend().solve(make_residual_problem(portfolio_problem), make_request())

    assert result.classical_solver_status is ClassicalSolverStatus.UNAVAILABLE
    assert result.terminal_reason is TerminalReason.CLASSICAL_BACKEND_UNAVAILABLE


def test_unsupported_problem_structure_fails_before_importing_cplex(monkeypatch) -> None:
    """The backend does not pass arbitrary opaque problems to the CPLEX binding."""

    def unexpected_import(module_name: str):
        raise AssertionError(f"unexpected optional import: {module_name}")

    monkeypatch.setattr("qreduce.classical.cplex_backend._import_module", unexpected_import)

    result = CplexClassicalBackend().solve(object(), make_request())

    assert result.classical_solver_status is ClassicalSolverStatus.FAILED
    assert result.terminal_reason is TerminalReason.UNSUPPORTED_PROBLEM_STRUCTURE