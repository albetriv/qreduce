"""Coverage for the classical-only portfolio baseline using unified API."""

import pytest

from qreduce.experiments import load_experiment_run
from qreduce.experiments.portfolio.execution import run_portfolio_experiment
from qreduce.models import ReductionPolicy


def _classical_policy(asset_count: int) -> ReductionPolicy:
    """Create a classical-only reduction policy."""
    return ReductionPolicy(
        max_reduction_rounds=0,
        candidate_domain_min_items=1,
        candidate_domain_max_items=asset_count,
        num_source_mis_candidates=1,
        min_reduction_ratio=0.1,
        target_binary_variables=0,
        max_end_to_end_runtime_seconds=60.0,
    )


def _multi_round_policy(asset_count: int) -> ReductionPolicy:
    """Create a multi-round reduction policy."""
    return ReductionPolicy(
        max_reduction_rounds=3,
        candidate_domain_min_items=1,
        candidate_domain_max_items=asset_count,
        num_source_mis_candidates=1,
        min_reduction_ratio=0.1,
        target_binary_variables=0,
        max_end_to_end_runtime_seconds=60.0,
    )


def test_classical_baseline_matches_multi_round_problem(tmp_path):
    classical = run_portfolio_experiment(
        "baseline",
        output_root=tmp_path,
        reduction_policy=_classical_policy(30),
    )
    multi = run_portfolio_experiment(
        "multi",
        output_root=tmp_path,
        reduction_policy=_multi_round_policy(30),
    )
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
        run_portfolio_experiment(
            "invalid",
            output_root=tmp_path,
            asset_count=count,
            reduction_policy=_classical_policy(30),
        )