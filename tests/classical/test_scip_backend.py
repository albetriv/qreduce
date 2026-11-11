"""Tests for the lazy SCIP backend without requiring PySCIPOpt."""

from qreduce.classical import ClassicalSolveRequest, ScipClassicalBackend
from qreduce.status import ClassicalSolverStatus, TerminalReason


def make_request(*, remaining_budget: float = 10.0) -> ClassicalSolveRequest:
    """Create one SCIP request with a bounded residual time budget."""

    return ClassicalSolveRequest(
        "run-001",
        0,
        10.0,
        remaining_budget,
        None,
        7,
        1,
        False,
        requested_solver_id="scip",
    )


def test_missing_pyscipopt_binding_returns_explicit_unavailable(monkeypatch) -> None:
    """A known SCIP ID does not silently fall back when its optional binding is absent."""

    def raise_missing_binding(module_name: str):
        assert module_name == "pyscipopt"
        raise ModuleNotFoundError("No module named 'pyscipopt'", name="pyscipopt")

    monkeypatch.setattr("qreduce.classical.scip_backend._import_module", raise_missing_binding)

    class GenericResidualProblem:
        def build_classical_model(self):  # pragma: no cover - import must fail first.
            raise AssertionError("model construction must not happen without PySCIPOpt")

    result = ScipClassicalBackend().solve(GenericResidualProblem(), make_request())

    assert result.classical_solver_status is ClassicalSolverStatus.UNAVAILABLE
    assert result.terminal_reason is TerminalReason.CLASSICAL_BACKEND_UNAVAILABLE
    assert result.solver_claimed_feasible is False


def test_unsupported_problem_structure_skips_lazy_scip_import(monkeypatch) -> None:
    """An arbitrary opaque residual problem is rejected before importing PySCIPOpt."""

    def unexpected_import(module_name: str):
        raise AssertionError(f"unexpected optional import: {module_name}")

    monkeypatch.setattr("qreduce.classical.scip_backend._import_module", unexpected_import)

    result = ScipClassicalBackend().solve(object(), make_request())

    assert result.classical_solver_status is ClassicalSolverStatus.FAILED
    assert result.terminal_reason is TerminalReason.UNSUPPORTED_PROBLEM_STRUCTURE