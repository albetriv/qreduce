"""Tests for the lazy SCIP backend without requiring PySCIPOpt."""

from qreduce.solving.residual import ClassicalSolveRequest, ScipClassicalBackend
from qreduce.status import ClassicalSolverStatus, TerminalReason


def make_request(*, remaining_budget: float = 10.0, configured_budget: float = 60.0, time_limit: float = 10.0) -> ClassicalSolveRequest:
    """Create one SCIP request with a bounded residual time budget."""
    return ClassicalSolveRequest(
        run_id="run-001",
        round_index=0,
        time_limit_seconds=time_limit,
        remaining_end_to_end_seconds=remaining_budget,
        configured_end_to_end_budget_seconds=configured_budget,
        mip_gap_tolerance=None,
        random_seed=7,
        threads=1,
        model_export_enabled=False,
        requested_solver_id="scip",
    )


def test_missing_pyscipopt_binding_returns_explicit_unavailable(monkeypatch) -> None:
    """A known SCIP ID does not silently fall back when its optional binding is absent."""

    def raise_missing_binding(module_name: str):
        assert module_name == "pyscipopt"
        raise ModuleNotFoundError("No module named 'pyscipopt'", name="pyscipopt")

    monkeypatch.setattr("qreduce.solving.residual.scip_backend._import_module", raise_missing_binding)

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

    monkeypatch.setattr("qreduce.solving.residual.scip_backend._import_module", unexpected_import)

    result = ScipClassicalBackend().solve(object(), make_request())

    assert result.classical_solver_status is ClassicalSolverStatus.FAILED
    assert result.terminal_reason is TerminalReason.UNSUPPORTED_PROBLEM_STRUCTURE


def test_unlimited_budget_skips_time_limit_parameter(monkeypatch) -> None:
    """With unlimited budget (both timeout=0 and budget=0), backend should not set time limit."""
    # Track setParam calls
    set_param_calls = []

    class MockModel:
        """Mock SCIP model that records setParam calls."""
        def setParam(self, name: str, value: object) -> None:
            set_param_calls.append((name, value))

        def setMinimize(self) -> None:
            pass

        def optimize(self) -> None:
            pass

        def getStatus(self) -> str:
            return "optimal"

        def getNSols(self) -> int:
            return 1

        def getBestSol(self) -> object:
            return object()

        def getVal(self, sol: object, var: object) -> float:
            return 0.5

        def getObjVal(self) -> float:
            return 1.0

        def getDualbound(self) -> float:
            return 1.0

        def getGap(self) -> float:
            return 0.0

        def getNVars(self) -> int:
            return 1

        def getNConss(self) -> int:
            return 1

    class MockScipModule:
        class Model:
            def __init__(self):
                pass

            def __new__(cls):
                return MockModel()

    # Patch the import
    monkeypatch.setattr("qreduce.solving.residual.scip_backend._import_module", lambda name: MockScipModule)

    # Create a minimal problem that provides a model
    class MinimalProblem:
        def build_classical_model(self):
            from qreduce.solving.residual.model import (
                ClassicalOptimizationModel,
            )
            return ClassicalOptimizationModel(
                variables=[],
                objective_coefficients={},
                objective_sense="minimize",
                constraints=[],
            )

    # Request with unlimited timeout and budget
    request = make_request(time_limit=0.0, remaining_budget=0.0, configured_budget=0.0)

    assert request.is_unlimited is True

    ScipClassicalBackend().solve(MinimalProblem(), request)

    # Verify no "limits/time" was set
    time_param_calls = [call for call in set_param_calls if call[0] == "limits/time"]
    assert len(time_param_calls) == 0, f"Should not set time limit when unlimited, but got: {time_param_calls}"


def test_exhausted_budget_prevents_solver_invocation(monkeypatch) -> None:
    """With exhausted budget (remaining <= 0 but configured > 0), backend should not run."""
    import_called = []

    def track_import(name: str):
        import_called.append(name)
        raise ModuleNotFoundError("tracking import")

    # Patch import to detect if it's called
    monkeypatch.setattr("qreduce.solving.residual.scip_backend._import_module", track_import)

    # Request with exhausted budget
    request = make_request(time_limit=10.0, remaining_budget=0.0, configured_budget=60.0)

    assert request.is_budget_exhausted is True
    assert request.is_unlimited is False

    result = ScipClassicalBackend().solve(object(), request)

    # Should return not-run result without importing pyscipopt
    assert result.classical_solver_status is ClassicalSolverStatus.NOT_RUN
    assert result.terminal_reason is TerminalReason.END_TO_END_TIME_BUDGET_EXHAUSTED
    assert "pyscipopt" not in import_called, "Should not import pyscipopt when budget is exhausted"
