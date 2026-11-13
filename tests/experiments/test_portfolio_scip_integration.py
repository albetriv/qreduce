"""Optional live test for the portfolio experiment's default SCIP solver."""

import importlib.util

import pytest

from qreduce.experiments.portfolio import run_synthetic_portfolio_experiment
from qreduce.status import ClassicalSolverStatus, RunStatus

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        importlib.util.find_spec("pyscipopt") is None,
        reason="Optional PySCIPOpt binding is not installed.",
    ),
]


def test_default_portfolio_path_solves_with_scip(tmp_path) -> None:
    """The default local-MIS portfolio run translates its MIQP for SCIP."""

    run = run_synthetic_portfolio_experiment("scip-integration", output_root=tmp_path)

    assert run.result.run_result.run_status in {
        RunStatus.SUCCESS,
        RunStatus.PARTIAL_SUCCESS,
    }
    assert run.result.run_result.adoption_status.value == "adopted"
    assert run.result.original_problem_optimality_claim == "none"
    assert run.result.original_dual_bound is None
    assert run.result.original_primal_bound is not None
    assert run.result.residual_problem_optimality_claim == "certified_optimal"
    assert run.result.classical_result is not None
    assert run.result.classical_result.requested_solver_id == "scip"
    assert run.result.classical_result.effective_solver_id == "scip"
    assert run.result.classical_result.classical_solver_status is ClassicalSolverStatus.OPTIMAL
    assert run.result.original_variable_counts.binary_free == 5
    assert run.result.residual_variable_counts.binary_free == len(run.result.final_retained_item_ids)
    assert run.result.residual_variable_counts.continuous_free == len(run.result.final_retained_item_ids)