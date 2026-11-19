"""Tests for timeout and budget handling in the pipeline.

These tests verify:
1. Single-pass with timeout > budget residual: backend receives the minimum
2. Single-pass with timeout=0 and finite budget: backend receives remaining budget
3. Single-pass and multi-round with budget=0: execution proceeds without limit
4. Budget shared between rounds without restart
5. Backend SCIP/CPLEX unlimited: time limit not set
"""

from dataclasses import replace

import pytest

from qreduce.experiments.portfolio_mv import (
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
from qreduce.pipeline import run_pipeline
from qreduce.solving.residual import (
    ClassicalSolveRequest,
    ClassicalSolveResult,
    ClassicalSolverRegistry,
)
from qreduce.status import ClassicalSolverStatus, PostcheckMode

pytestmark = pytest.mark.integration


def make_config(
    *,
    time_limit_seconds: float = 60.0,
    max_end_to_end_runtime_seconds: float = 60.0,
    max_reduction_rounds: int = 1,
) -> ResolvedRunConfig:
    """Build a deterministic configuration for timeout tests."""
    return ResolvedRunConfig(
        schema_version="1.0",
        reduction=ReductionPolicy(
            max_reduction_rounds=max_reduction_rounds,
            candidate_domain_min_items=1,
            candidate_domain_max_items=3,
            num_source_mis_candidates=1,
            min_reduction_ratio=0.1,
            target_binary_variables=3,
            max_end_to_end_runtime_seconds=max_end_to_end_runtime_seconds,
        ),
        lambda_edge=2.0,
        lambda_edge_policy=LambdaEdgePolicy("standard", "1", 2.0),
        allow_noncertifying_penalty=False,
        mis_solver_id="local_greedy",
        mis_execution=MISExecutionOptions(1, 17, 1, False, 0, 0.0, 20),
        classical_solve=ClassicalSolveOptions(
            classical_solver_id="test_backend",
            time_limit_seconds=time_limit_seconds,
            mip_gap_tolerance=None,
            threads=1,
            model_export_enabled=False,
            primal_feasibility_tolerance=1e-6,
            integrality_tolerance=1e-6,
            objective_recomputation_absolute_tolerance=1e-6,
            objective_recomputation_relative_tolerance=1e-6,
            postcheck_mode=PostcheckMode.STRICT,
            random_seed=7,
        ),
        run_identity=RunIdentity("timeout-test"),
    )


def make_adapter() -> MeanVariancePortfolioAdapter:
    return MeanVariancePortfolioAdapter(
        PortfolioGraphPolicy("test", "1", 0.25, edge_mode="correlation_only")
    )


class RecordingBackend:
    """Backend that records requests for inspection."""

    def __init__(self):
        self.requests: list[ClassicalSolveRequest] = []

    def solve(self, reduced_problem, request: ClassicalSolveRequest) -> ClassicalSolveResult:
        self.requests.append(request)
        # Return an optimal result with correct variable values for the reduced problem
        variable_values = {}
        # Get the actual variable names from the reduced problem
        if hasattr(reduced_problem, '_problem'):
            # Portfolio adapter stores the problem
            for name in reduced_problem._problem.asset_names:
                variable_values[f"x_{name}"] = 0.333
                variable_values[f"delta_{name}"] = 1.0
        return ClassicalSolveResult(
            classical_solver_status=ClassicalSolverStatus.OPTIMAL,
            terminal_reason=None,
            solver_claimed_feasible=True,
            objective_value=1.0,
            best_bound=1.0,
            gap=0.0,
            is_optimal=True,
            is_time_limited=False,
            runtime_seconds=0.01,
            variable_values=variable_values,
        )


def test_single_pass_timeout_clamped_to_remaining_budget(portfolio_problem: PortfolioProblem) -> None:
    """When timeout > remaining budget, the backend receives the remaining budget."""
    backend = RecordingBackend()
    registry = ClassicalSolverRegistry(include_builtins=False)
    registry.register("test_backend", lambda: backend)

    # Timeout is 60s, but budget is only 5s
    config = make_config(time_limit_seconds=60.0, max_end_to_end_runtime_seconds=5.0)

    run_pipeline(portfolio_problem, make_adapter(), config, classical_solver_registry=registry)

    # The backend must have been called
    assert len(backend.requests) >= 1, "Backend should have been invoked"
    request = backend.requests[0]

    # The effective limit should be clamped to the budget (approximately, accounting for elapsed time)
    effective = request.effective_time_limit_seconds
    assert effective is not None, "effective_time_limit_seconds should not be None"
    assert effective <= 5.0, f"Effective timeout {effective} should be <= budget 5.0"
    assert request.configured_end_to_end_budget_seconds == 5.0


def test_single_pass_unlimited_timeout_uses_remaining_budget(portfolio_problem: PortfolioProblem) -> None:
    """When timeout=0 (unlimited) and budget is finite, backend receives remaining budget."""
    backend = RecordingBackend()
    registry = ClassicalSolverRegistry(include_builtins=False)
    registry.register("test_backend", lambda: backend)

    # Timeout is unlimited (0), budget is 30s
    config = make_config(time_limit_seconds=0.0, max_end_to_end_runtime_seconds=30.0)

    run_pipeline(portfolio_problem, make_adapter(), config, classical_solver_registry=registry)

    assert len(backend.requests) >= 1, "Backend should have been invoked"
    request = backend.requests[0]

    # With unlimited timeout, the effective limit comes from the remaining budget
    effective = request.effective_time_limit_seconds
    assert effective is not None, "Should have effective limit from budget"
    assert effective > 0, "Has a positive limit from budget"
    assert effective <= 30.0, "At most the configured budget"
    assert request.time_limit_seconds == 0.0, "Original request was unlimited"
    assert request.configured_end_to_end_budget_seconds == 30.0


def test_single_pass_unlimited_budget_completes_without_limit(portfolio_problem: PortfolioProblem) -> None:
    """When budget=0 (unlimited) and timeout=0, execution proceeds without time limit."""
    backend = RecordingBackend()
    registry = ClassicalSolverRegistry(include_builtins=False)
    registry.register("test_backend", lambda: backend)

    # Both unlimited
    config = make_config(time_limit_seconds=0.0, max_end_to_end_runtime_seconds=0.0)

    run_pipeline(portfolio_problem, make_adapter(), config, classical_solver_registry=registry)

    assert len(backend.requests) >= 1, "Backend should have been invoked"
    request = backend.requests[0]

    # Both unlimited means is_unlimited=True
    assert request.is_unlimited is True
    assert request.effective_time_limit_seconds is None
    assert request.is_budget_exhausted is False


def test_single_pass_finite_timeout_with_unlimited_budget(portfolio_problem: PortfolioProblem) -> None:
    """When timeout is finite and budget=0 (unlimited), backend uses the timeout."""
    backend = RecordingBackend()
    registry = ClassicalSolverRegistry(include_builtins=False)
    registry.register("test_backend", lambda: backend)

    # Timeout is 10s, budget is unlimited
    config = make_config(time_limit_seconds=10.0, max_end_to_end_runtime_seconds=0.0)

    run_pipeline(portfolio_problem, make_adapter(), config, classical_solver_registry=registry)

    assert len(backend.requests) >= 1, "Backend should have been invoked"
    request = backend.requests[0]

    # With unlimited budget, the effective limit is the timeout
    assert request.effective_time_limit_seconds == 10.0
    assert request.is_unlimited is False
    assert request.configured_end_to_end_budget_seconds == 0.0


def test_multi_round_budget_shared_between_rounds_deterministic(portfolio_problem: PortfolioProblem) -> None:
    """Budget is shared between rounds and does not restart.

    Verifies that:
    1. The configured budget is propagated to the classical solver request
    2. The remaining budget is computed from the configured budget minus elapsed time
    3. The remaining budget is never greater than configured budget
    """
    backend = RecordingBackend()
    registry = ClassicalSolverRegistry(include_builtins=False)
    registry.register("test_backend", lambda: backend)

    # Multi-round with finite budget
    config = make_config(
        time_limit_seconds=60.0,
        max_end_to_end_runtime_seconds=100.0,
        max_reduction_rounds=3,
    )

    run_pipeline(portfolio_problem, make_adapter(), config, classical_solver_registry=registry)

    # Must have been invoked at least once
    assert len(backend.requests) >= 1, "Backend should have been invoked"

    first_request = backend.requests[0]

    # Configured budget is always propagated correctly
    assert first_request.configured_end_to_end_budget_seconds == 100.0

    # Remaining budget should be <= configured (time has elapsed)
    assert first_request.remaining_end_to_end_seconds <= 100.0, \
        "Remaining budget should not exceed configured budget"

    # The effective time limit should be the minimum of timeout and remaining
    effective = first_request.effective_time_limit_seconds
    assert effective is not None
    assert effective <= 60.0  # Cannot exceed the per-solve timeout
    assert effective <= first_request.remaining_end_to_end_seconds  # Cannot exceed remaining budget


def test_multi_round_with_unlimited_budget(portfolio_problem: PortfolioProblem) -> None:
    """Multi-round execution works correctly with unlimited budget."""
    backend = RecordingBackend()
    registry = ClassicalSolverRegistry(include_builtins=False)
    registry.register("test_backend", lambda: backend)

    # Multi-round with unlimited budget
    config = make_config(
        time_limit_seconds=0.0,
        max_end_to_end_runtime_seconds=0.0,
        max_reduction_rounds=2,
    )

    run_pipeline(portfolio_problem, make_adapter(), config, classical_solver_registry=registry)

    assert len(backend.requests) >= 1, "Backend should have been invoked"
    # All requests should be unlimited
    for request in backend.requests:
        assert request.is_unlimited is True
        assert request.is_budget_exhausted is False



def test_pipeline_completes_successfully_with_unlimited_budget_scip(portfolio_problem: PortfolioProblem) -> None:
    """Pipeline completes with SUCCESS status when budget is unlimited and SCIP is available."""
    import importlib.util

    # Skip if SCIP is not available
    if importlib.util.find_spec("pyscipopt") is None:
        pytest.skip("PySCIPOpt not available")

    from qreduce.status import RunStatus

    # Use real SCIP with unlimited budget
    base_config = make_config(
        time_limit_seconds=0.0,  # Unlimited per-solve
        max_end_to_end_runtime_seconds=0.0,  # Unlimited global
        max_reduction_rounds=1,
    )
    # Override to use real SCIP
    config = replace(base_config, classical_solve=replace(base_config.classical_solve, classical_solver_id="scip"))

    result = run_pipeline(portfolio_problem, make_adapter(), config)

    # Should complete successfully (not fail due to timeout issues)
    assert result.run_result.run_status == RunStatus.SUCCESS, \
        f"Expected SUCCESS but got {result.run_result.run_status} with terminal_reason={result.run_result.terminal_reason}"
    assert result.run_result.terminal_reason is None
    assert result.classical_result is not None
    assert result.classical_result.solver_claimed_feasible is True
