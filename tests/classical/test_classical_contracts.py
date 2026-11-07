"""Tests for uniform residual classical-solver contracts."""

import pytest

from qreduce.classical import ClassicalSolveRequest, ClassicalSolveResult
from qreduce.status import ClassicalSolverStatus, TerminalReason


def test_effective_time_limit_is_clamped_to_remaining_budget() -> None:
    """The solver cannot consume more than the end-to-end budget still available."""

    request = ClassicalSolveRequest("run-001", 0, 30.0, 5.0, None, None, None, False)

    assert request.effective_time_limit_seconds == 5.0


def test_no_remaining_budget_forbids_backend_invocation() -> None:
    """A non-positive residual budget produces no effective solver time limit."""

    request = ClassicalSolveRequest("run-001", 0, 30.0, 0.0, None, None, None, False)

    assert request.effective_time_limit_seconds is None


def test_failed_classical_result_requires_a_terminal_reason() -> None:
    """Failure states cannot omit the reason required by artifacts."""

    with pytest.raises(ValueError, match="requires a terminal reason"):
        ClassicalSolveResult(
            classical_solver_status=ClassicalSolverStatus.FAILED,
            terminal_reason=None,
            solver_claimed_feasible=False,
            objective_value=None,
            best_bound=None,
            gap=None,
            is_optimal=False,
            is_time_limited=False,
            runtime_seconds=0.0,
        )

    result = ClassicalSolveResult(
        classical_solver_status=ClassicalSolverStatus.INFEASIBLE,
        terminal_reason=TerminalReason.CLASSICAL_SOLVER_INFEASIBLE,
        solver_claimed_feasible=False,
        objective_value=None,
        best_bound=None,
        gap=None,
        is_optimal=False,
        is_time_limited=False,
        runtime_seconds=0.0,
    )
    assert result.to_dict()["terminal_reason"] == "classical_solver_infeasible"