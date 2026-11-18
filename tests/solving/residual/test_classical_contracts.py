"""Tests for uniform residual classical-solver contracts."""

import pytest

from qreduce.solving.residual import ClassicalSolveRequest, ClassicalSolveResult
from qreduce.status import ClassicalSolverStatus, TerminalReason


def test_effective_time_limit_is_clamped_to_remaining_budget() -> None:
    """The solver cannot consume more than the end-to-end budget still available."""
    # Both finite: use minimum (5.0 < 30.0)
    request = ClassicalSolveRequest(
        run_id="run-001",
        round_index=0,
        time_limit_seconds=30.0,
        remaining_end_to_end_seconds=5.0,
        configured_end_to_end_budget_seconds=60.0,
        mip_gap_tolerance=None,
        random_seed=None,
        threads=None,
        model_export_enabled=False,
        requested_solver_id="test",
    )

    assert request.effective_time_limit_seconds == 5.0
    assert request.is_unlimited is False
    assert request.is_budget_exhausted is False


def test_no_remaining_budget_forbids_backend_invocation() -> None:
    """A non-positive residual budget (with configured budget) forbids invocation."""
    # Budget was configured (60.0) but is exhausted (remaining=0.0)
    request = ClassicalSolveRequest(
        run_id="run-001",
        round_index=0,
        time_limit_seconds=30.0,
        remaining_end_to_end_seconds=0.0,
        configured_end_to_end_budget_seconds=60.0,
        mip_gap_tolerance=None,
        random_seed=None,
        threads=None,
        model_export_enabled=False,
        requested_solver_id="test",
    )

    assert request.effective_time_limit_seconds is None
    assert request.is_budget_exhausted is True
    assert request.is_unlimited is False


def test_unlimited_when_both_timeout_and_budget_are_zero() -> None:
    """When both timeout and budget are 0, the request is unlimited."""
    request = ClassicalSolveRequest(
        run_id="run-001",
        round_index=0,
        time_limit_seconds=0.0,
        remaining_end_to_end_seconds=0.0,
        configured_end_to_end_budget_seconds=0.0,
        mip_gap_tolerance=None,
        random_seed=None,
        threads=None,
        model_export_enabled=False,
        requested_solver_id="test",
    )

    assert request.effective_time_limit_seconds is None
    assert request.is_unlimited is True
    assert request.is_budget_exhausted is False


def test_timeout_used_when_budget_unlimited() -> None:
    """When budget is unlimited (0) but timeout is finite, use timeout."""
    request = ClassicalSolveRequest(
        run_id="run-001",
        round_index=0,
        time_limit_seconds=10.0,
        remaining_end_to_end_seconds=0.0,
        configured_end_to_end_budget_seconds=0.0,
        mip_gap_tolerance=None,
        random_seed=None,
        threads=None,
        model_export_enabled=False,
        requested_solver_id="test",
    )

    assert request.effective_time_limit_seconds == 10.0
    assert request.is_unlimited is False


def test_remaining_budget_used_when_timeout_unlimited() -> None:
    """When timeout is unlimited (0) but budget is finite, use remaining budget."""
    request = ClassicalSolveRequest(
        run_id="run-001",
        round_index=0,
        time_limit_seconds=0.0,
        remaining_end_to_end_seconds=30.0,
        configured_end_to_end_budget_seconds=60.0,
        mip_gap_tolerance=None,
        random_seed=None,
        threads=None,
        model_export_enabled=False,
        requested_solver_id="test",
    )

    assert request.effective_time_limit_seconds == 30.0
    assert request.is_unlimited is False


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
            requested_solver_id="test",
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
        requested_solver_id="test",
    )
    assert result.to_dict()["terminal_reason"] == "classical_solver_infeasible"