"""Publish, reload and analyze real baseline and screened SCIP experiments."""

from dataclasses import replace
from pathlib import Path

import pytest

from qreduce.artifacts.metadata import pretty_json
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


@pytest.mark.parametrize(("rounds", "max_positions"), [(0, None), (1, None), (0, 2)])
def test_minimum_investment_scip_roundtrip(tmp_path: Path, rounds: int, max_positions: int | None):
    """The minimum is enforced in both baseline and local reduction runs."""
    pytest.importorskip("pyscipopt")
    tickers = ("A", "B", "C", "D")
    minimum = 0.30 if max_positions is not None else 0.15
    problem = SharpePortfolioProblem(
        tickers=tickers,
        mean_returns=dict.fromkeys(tickers, 0.1),
        covariance=((0.01, 0., 0., 0.), (0., 0.025, 0., 0.),
                    (0., 0., 0.03, 0.), (0., 0., 0., 1.0)),
        sectors=dict.fromkeys(tickers, "all"),
        upper_bounds=dict.fromkeys(tickers, 1.0),
        lower_bound=minimum,
        max_positions=max_positions,
    )
    adapter = SharpePortfolioAdapter(default_sharpe_graph_policy())
    policy = replace(default_reduction_policy(4, max_reduction_rounds=rounds, has_cardinality=True),
                     target_binary_variables=0, candidate_domain_max_items=3)
    config = _build_resolved_run_config(
        f"minimum-{rounds}", reduction_policy=policy,
        mis_solver_id="local_greedy", mis_execution=_build_mis_execution_options(),
        classical_solve=_build_classical_solve_options(),
    )
    run = run_experiment("portfolio_sr", problem, adapter, config, output_root=tmp_path)
    assert run.result.run_result.run_status == "success"
    artifacts = load_experiment_run(run.run_directory)
    weights = extract_portfolio_weights(artifacts, weight_tolerance=0)
    assert sum(weights.values()) == pytest.approx(1, abs=1e-6)
    assert all(w <= 1e-6 or w >= minimum - 1e-6 for w in weights.values())
    if max_positions is not None:
        assert sum(w > 1e-6 for w in weights.values()) == max_positions
        assert weights["B"] == pytest.approx(minimum, abs=1e-6)
    assert artifacts.problem["lower_bound"] == minimum
    assert load_sharpe_portfolio_analysis(run.run_directory).problem_summary["lower_bound"] == minimum
    if rounds == 0 and max_positions is None:
        # The legacy runner serialized the dataclass fields, not problem.to_dict().
        legacy_problem = {
            "tickers": tickers,
            "mean_returns": problem.mean_returns,
            "covariance": problem.covariance,
            "sectors": problem.sectors,
            "upper_bounds": problem.upper_bounds,
            "sector_constraints": None,
            "max_positions": None,
            "risk_free_rate": 0.0,
            "covariance_symmetry_tolerance": 1e-12,
        }
        original = replace(problem, lower_bound=0.0, min_selected_assets=0)
        original_config = replace(
            config, run_identity=replace(config.run_identity, run_id="no-minimum"),
            classical_solve=_build_classical_solve_options(model_export_enabled=True),
        )
        original_run = run_experiment("portfolio_sr", original, adapter, original_config, output_root=tmp_path)
        assert original_run.result.run_result.run_status == "success"
        assert (original_run.run_directory / "problem.json").read_bytes() == (
            pretty_json(legacy_problem) + "\n"
        ).encode("utf-8")
        original_weights = extract_portfolio_weights(load_experiment_run(original_run.run_directory), weight_tolerance=0)
        assert 1e-6 < original_weights["D"] < 0.15
        exported = (original_run.run_directory / "residual_model.lp").read_text()
        assert all(f"delta__{ticker}" in exported for ticker in tickers)
        assert all(f"cardinality_link__{ticker}" in exported for ticker in tickers)


def test_selection_minimum_roundtrip_and_screening_rejection(tmp_path: Path):
    """A minimum alone creates binaries, and an undersized fixing never reaches SCIP."""
    pytest.importorskip("pyscipopt")
    tickers = ("A", "B", "C")
    problem = SharpePortfolioProblem(
        tickers, dict.fromkeys(tickers, 0.1),
        ((0.1, 0.2, 0.2), (0.2, 1.0, 0.5), (0.2, 0.5, 1.0)),
        dict.fromkeys(tickers, "all"), dict.fromkeys(tickers, 1.0),
        min_selected_assets=2,
    )
    adapter = SharpePortfolioAdapter(default_sharpe_graph_policy())
    config = _build_resolved_run_config(
        "selection-minimum", reduction_policy=replace(
            default_reduction_policy(3, max_reduction_rounds=0), candidate_domain_max_items=1,
        ),
        mis_solver_id="local_greedy", mis_execution=_build_mis_execution_options(),
        classical_solve=_build_classical_solve_options(),
    )
    run = run_experiment("portfolio_sr", problem, adapter, config, output_root=tmp_path)
    assert run.result.run_result.run_status == "success"
    artifacts = load_experiment_run(run.run_directory)
    assert artifacts.problem["min_selected_assets"] == 2
    assert artifacts.problem["max_positions"] is None
    analysis = load_sharpe_portfolio_analysis(run.run_directory)
    assert analysis.solution is not None and analysis.solution.selected_count >= 2
    assert analysis.solution.position_count == 1

    manifest = FixingManifest(
        retained_item_ids=("A",), excluded_item_ids=("B", "C"),
        entries=tuple(FixingEntry(t, {f"x_scaled__{t}": 0.0, f"delta__{t}": 0.0}, "screening")
                      for t in ("B", "C")),
        origin="screening", round_index=0,
    )
    screened = TransformedSharpeProblem(problem, ("A",), manifest, SharpeVariableMapping.for_problem(problem))
    config = replace(config, run_identity=replace(config.run_identity, run_id="too-few-screened"))
    rejected = run_experiment("portfolio_sr", screened, adapter, config, output_root=tmp_path)
    assert rejected.result.run_result.terminal_reason == "candidate_domain_too_small"


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
