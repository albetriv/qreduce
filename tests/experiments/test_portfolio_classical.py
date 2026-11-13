"""Coverage for the classical-only portfolio baseline."""

import pytest

from qreduce.experiments import load_experiment_run
from qreduce.experiments.portfolio_classical import run_portfolio_classical_experiment
from qreduce.experiments.portfolio_multi_round import (
    run_portfolio_multi_round_experiment,
)


def test_classical_baseline_matches_multi_round_problem(tmp_path):
    classical = run_portfolio_classical_experiment("baseline", output_root=tmp_path)
    multi = run_portfolio_multi_round_experiment("multi", output_root=tmp_path)
    baseline = load_experiment_run(classical.run_directory)
    reduced = load_experiment_run(multi.run_directory)

    assert baseline.problem == reduced.problem
    assert len(baseline.problem["asset_ids"]) == 30
    assert baseline.config["classical_solve"] == reduced.config["classical_solve"]
    assert baseline.config["classical_solve"]["classical_solver_id"] == "scip"
    assert baseline.config["reduction"]["max_reduction_rounds"] == 0
    assert baseline.is_classical_only and not baseline.has_reduction
    assert not baseline.round_results and not baseline.recovery_attempts
    assert not list(classical.run_directory.glob("round_*_result.json"))
    assert baseline.result["original_variable_counts"] == baseline.result["residual_variable_counts"]


@pytest.mark.parametrize("count", [True, 5, 3.5])
def test_classical_baseline_rejects_invalid_size(tmp_path, count):
    with pytest.raises(ValueError, match="asset_count"):
        run_portfolio_classical_experiment("invalid", output_root=tmp_path, asset_count=count)