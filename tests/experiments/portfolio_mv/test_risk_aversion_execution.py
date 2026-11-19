"""Verify non-unit risk aversion across actual round and recovery execution."""

from dataclasses import replace

import pytest

from qreduce.experiments import load_experiment_run
from qreduce.experiments.portfolio_mv import execution
from qreduce.experiments.portfolio_mv.inputs import (
    default_graph_policy,
    default_reduction_policy,
)
from qreduce.experiments.runner import run_experiment
from qreduce.solving.residual import ClassicalSolverRegistry
from qreduce.solving.residual.contracts import ClassicalSolveResult
from qreduce.status import ClassicalSolverStatus, TerminalReason


@pytest.mark.parametrize("recover", [False, True], ids=["distinct-rounds", "expanded-recovery"])
def test_risk_aversion_reaches_every_classical_solve(monkeypatch, tmp_path, recover):
    """A deterministic infeasible backend forces real iteration without an SDK."""
    calls = []
    observed_models = []

    class RecordingSolver:
        def solve(self, residual, request):
            model = residual.build_classical_model()
            problem = residual.original_problem
            calls.append((request.round_index, residual.retained_item_ids, problem.risk_aversion))
            observed_models.append((model, problem))
            return ClassicalSolveResult(
                classical_solver_status=ClassicalSolverStatus.INFEASIBLE,
                terminal_reason=TerminalReason.CLASSICAL_SOLVER_INFEASIBLE,
                solver_claimed_feasible=False, objective_value=None, best_bound=None,
                gap=None, is_optimal=False, is_time_limited=False, runtime_seconds=0.0,
                requested_solver_id=request.requested_solver_id,
            )

    registry = ClassicalSolverRegistry(include_builtins=False)
    registry.register("recording", RecordingSolver)

    def run_with_registry(*args, **kwargs):
        return run_experiment(*args, **kwargs, classical_solver_registry=registry)

    monkeypatch.setattr(execution, "run_experiment", run_with_registry)
    policy = replace(
        default_reduction_policy(12), max_reduction_rounds=2,
        candidate_domain_max_items=10, min_reduction_ratio=0.0,
        target_binary_variables=0, max_recovery_attempts=1 if recover else 0,
        recovery_policy_on_infeasible="retry_with_larger_domain",
    )
    run = execution.run_portfolio_experiment(
        "recording-risk", output_root=tmp_path, asset_count=12, risk_aversion=2.5,
        graph_policy=default_graph_policy("correlation_only", correlation_threshold=0.8 if recover else 1.0),
        reduction_policy=policy, classical_solver_id="recording",
    )
    assert len(calls) >= 2, run.result.run_result
    assert all(value == 2.5 for _, _, value in calls)
    # Assert outside solve: backend exceptions are deliberately normalized by the pipeline.
    assert len(observed_models) == len(calls)
    for model, problem in observed_models:
        assert model.quadratic_objective
        for term in model.quadratic_objective:
            left = model.variable_names.index(term.left_variable) - len(problem.asset_ids)
            right = model.variable_names.index(term.right_variable) - len(problem.asset_ids)
            expected = 2.5 * problem.covariance[left][right] * (1 if left == right else 2)
            assert term.coefficient == pytest.approx(expected)
    artifacts = load_experiment_run(run.run_directory)
    assert artifacts.problem["risk_aversion"] == 2.5
    if recover:
        assert [index for index, _, _ in calls[:2]] == [0, 0]
        assert set(calls[0][1]) < set(calls[1][1])
        assert any(attempt.outcome == "retry" for attempt in run.result.recovery_attempts)
    else:
        assert [index for index, _, _ in calls] == [0, 1]
        assert len(run.result.round_results) == 2