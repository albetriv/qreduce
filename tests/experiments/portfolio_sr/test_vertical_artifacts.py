"""Publish, reload and analyze real baseline and screened SCIP experiments."""

from dataclasses import replace
from pathlib import Path

import pytest

from qreduce.domains.contracts import FixingEntry, FixingManifest
from qreduce.experiments.artifacts import load_experiment_run
from qreduce.experiments.portfolio_sr.adapter import SharpePortfolioAdapter
from qreduce.experiments.portfolio_sr.analysis import (
    ComparisonSummary,
    TimingMetrics,
    extract_portfolio_weights,
    extract_sector_exposures,
    load_sharpe_portfolio_analysis,
)
from qreduce.experiments.portfolio_sr.execution import (
    _build_classical_solve_options,
    _build_mis_execution_options,
    _build_resolved_run_config,
)
from qreduce.experiments.portfolio_sr.graph_policy import default_sharpe_graph_policy
from qreduce.experiments.portfolio_sr.inputs import default_reduction_policy
from qreduce.experiments.portfolio_sr.models import (
    SectorConstraints,
    SharpePortfolioProblem,
    SharpeVariableMapping,
    TransformedSharpeProblem,
)
from qreduce.experiments.runner import run_experiment


@pytest.fixture
def published_runs(tmp_path: Path):
    """Use real disk I/O for valid and invalid initial fixing domains."""
    pytest.importorskip("pyscipopt")
    problem = SharpePortfolioProblem(
        tickers=("A", "B", "C", "D"),
        mean_returns={"A": .10, "B": .12, "C": .11, "D": .13},
        covariance=((.04, .005, 0., 0.), (.005, .05, 0., 0.),
                    (0., 0., .06, .005), (0., 0., .005, .07)),
        sectors={"A": "Tech", "B": "Tech", "C": "Health", "D": "Health"},
        upper_bounds={t: 1. for t in ("A", "B", "C", "D")},
        sector_constraints=SectorConstraints(
            {"Tech": .2, "Health": .2}, {"Tech": .8, "Health": .8},
        ),
        max_positions=3,
    )
    adapter = SharpePortfolioAdapter(default_sharpe_graph_policy())
    config = _build_resolved_run_config(
        "baseline",
        reduction_policy=default_reduction_policy(4, max_reduction_rounds=0, has_cardinality=True),
        mis_solver_id="local_greedy", mis_execution=_build_mis_execution_options(),
        classical_solve=_build_classical_solve_options(),
    )
    runs = {}
    mapping = SharpeVariableMapping.for_problem(problem)
    for name, selected in (("baseline", problem.tickers), ("screening", ("A", "C")),
                           ("invalid", ("A", "B"))):
        candidate = problem
        if name != "baseline":
            excluded = tuple(t for t in problem.tickers if t not in selected)
            entries = tuple(FixingEntry(
                item_id=ticker,
                variable_values={mapping.x_scaled_by_ticker[ticker]: 0.,
                                 mapping.delta_by_ticker[ticker]: 0.},
                reason="test_screening", fixing_origin="user_mandated",
                guarantee_level="user_imposed",
            ) for ticker in excluded)
            manifest = FixingManifest(
                retained_item_ids=selected, excluded_item_ids=excluded,
                entries=entries, origin="screening:test",
                provenance={"screening_method": "test", "seed": 42},
                source_candidate_ids=("screening-source",), policy_version="test-v1",
            )
            candidate = TransformedSharpeProblem(problem, selected, manifest, mapping)
        run_config = replace(config, run_identity=replace(config.run_identity, run_id=name))
        runs[name] = run_experiment(
            "portfolio_sr", candidate, adapter, run_config, output_root=tmp_path,
        )
    first = replace(
        adapter.build_fixing_manifest(problem, ("A", "B", "C")),
        source_candidate_ids=("first", "shared"), policy_version="v1",
    )
    restricted = adapter.restrict_problem(problem, ("A", "B", "C"), first)
    second = replace(
        adapter.build_fixing_manifest(restricted, ("A", "C")),
        source_candidate_ids=("shared", "second"), policy_version="v2",
    )
    merged = adapter.restrict_problem(restricted, ("A", "C"), second)
    run_config = replace(config, run_identity=replace(config.run_identity, run_id="merged"))
    runs["merged"] = run_experiment(
        "portfolio_sr", merged, adapter, run_config, output_root=tmp_path,
    )
    return problem, runs


@pytest.mark.parametrize("name", ["baseline", "screening"])
def test_adopted_solution_roundtrip(published_runs, name):
    problem, runs = published_runs
    run = runs[name]
    assert run.result.run_result.run_status == "success"
    artifacts = load_experiment_run(run.run_directory)
    analysis = load_sharpe_portfolio_analysis(run.run_directory)
    assert analysis.is_success and analysis.is_classical_only
    assert analysis.reduction_round_count == 0
    assert analysis.problem_summary["original_ticker_count"] == 4
    assert analysis.problem_summary["retained_ticker_count"] == (4 if name == "baseline" else 2)
    assert analysis.problem_summary["max_positions"] == 3
    assert analysis.problem_summary["sector_count"] == 2
    assert analysis.problem_summary["has_sector_constraints"]
    assert analysis.solution is not None
    assert analysis.solution.sharpe_ratio is not None
    assert analysis.solution.objective_value is not None
    assert run.result.postcheck_result is not None
    assert analysis.solution.objective_value == pytest.approx(
        run.result.postcheck_result.objective_recomputed, abs=1e-8,
    )
    assert run.result.classical_result is not None
    assert analysis.solution.objective_value == pytest.approx(
        run.result.classical_result.objective_value, rel=1e-4, abs=1e-6,
    )
    for metric in run.result.domain_evaluation_metrics:
        assert getattr(analysis.solution, metric.metric_id) == pytest.approx(metric.value)
    weights = extract_portfolio_weights(artifacts, weight_tolerance=0)
    assert set(weights) == set(problem.tickers)
    assert sum(weights.values()) == pytest.approx(1., abs=1e-6)
    exposures = extract_sector_exposures(artifacts)
    assert set(exposures) == {"Tech", "Health"}
    assert sum(exposures.values()) == pytest.approx(1., abs=1e-6)
    for sector, exposure in exposures.items():
        assert .2 - 1e-6 <= exposure <= .8 + 1e-6
        assert exposure == pytest.approx(sum(
            w for ticker, w in weights.items() if problem.sectors[ticker] == sector
        ))
    assert artifacts.fixing_manifest == run.result.cumulative_fixing_manifest.to_dict()
    if name == "screening":
        assert weights["B"] == pytest.approx(0., abs=1e-9)
        assert weights["D"] == pytest.approx(0., abs=1e-9)
        assert artifacts.fixing_manifest["source_candidate_ids"] == ["screening-source"]
        assert artifacts.fixing_manifest["policy_version"] == "test-v1"
        assert analysis.reduction is not None
        assert analysis.reduction.retained_ticker_count == 2
        assert analysis.reduction.excluded_ticker_count == 2
        assert analysis.reduction.reduction_ratio == .5
    for filename in ("run_manifest.json", "run_result.json", "problem.json",
                     "config_used.json", "experiment_metadata.json"):
        assert (run.run_directory / filename).is_file()


def test_invalid_screening_roundtrip(published_runs):
    _, runs = published_runs
    run = runs["invalid"]
    artifacts = load_experiment_run(run.run_directory)
    analysis = load_sharpe_portfolio_analysis(run.run_directory)
    assert not analysis.is_success
    assert analysis.solution is None
    assert run.result.run_result.terminal_reason == "candidate_domain_too_small"
    assert "sector_Health_no_retained_tickers" in run.result.run_result.diagnostic_message
    assert artifacts.result["run_result"]["diagnostic_message"] == run.result.run_result.diagnostic_message
    assert artifacts.fixing_manifest == run.result.cumulative_fixing_manifest.to_dict()
    assert artifacts.fixing_manifest["excluded_item_ids"] == ["C", "D"]
    assert extract_portfolio_weights(artifacts) == {}
    assert extract_sector_exposures(artifacts) == {}
    assert analysis.reduction.excluded_ticker_count == 2


def test_rankings_exclude_failed_runs_and_preserve_zero_time(published_runs):
    _, runs = published_runs
    valid = load_sharpe_portfolio_analysis(runs["baseline"].run_directory)
    failed = load_sharpe_portfolio_analysis(runs["invalid"].run_directory)
    valid = replace(valid, timing=TimingMetrics(0., None, None, None))
    slower = replace(valid, run_id="slower", timing=TimingMetrics(1., None, None, None))
    failed = replace(failed, solution=replace(valid.solution, sharpe_ratio=999.),
                     timing=TimingMetrics(0., None, None, None))
    comparison = ComparisonSummary((failed, slower, valid))
    assert comparison.fastest is valid
    assert comparison.best_sharpe is not failed


def test_merged_provenance_survives_publication(published_runs):
    _, runs = published_runs
    run = runs["merged"]
    assert run.result.run_result.run_status == "success"
    artifacts = load_experiment_run(run.run_directory)
    manifest = artifacts.fixing_manifest
    assert manifest == run.result.cumulative_fixing_manifest.to_dict()
    assert manifest["source_candidate_ids"] == ["first", "shared", "second"]
    assert manifest["policy_version"] == "v1+v2"
    assert set(manifest["excluded_item_ids"]) == {"B", "D"}
    assert manifest["retained_item_ids"] == ["A", "C"]
    assert manifest["provenance"]["previous"]["graph_policy_id"]
    assert manifest["provenance"]["current"]["graph_policy_id"]
