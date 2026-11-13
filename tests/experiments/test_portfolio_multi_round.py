"""Coverage for the larger persisted portfolio experiment."""

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from qreduce.experiments import load_experiment_run
from qreduce.experiments.portfolio_multi_round import (
    load_multi_round_correlation_data,
    run_portfolio_multi_round_experiment,
)


def test_multi_round_portfolio_publishes_larger_instance(tmp_path):
    run = run_portfolio_multi_round_experiment("larger", output_root=tmp_path)
    artifacts = load_experiment_run(run.run_directory)
    # With unified pipeline, has_reduction is True for any run with rounds
    assert artifacts.has_reduction
    assert artifacts.reduction_round_count >= 1  # May stop at first successful round
    assert len(artifacts.problem["asset_ids"]) == 30
    assert artifacts.config["reduction"]["max_reduction_rounds"] == 3
    assert len(artifacts.round_results) == artifacts.manifest["round_count"]
    assert artifacts.round_results
    asset_ids, correlation, graph = load_multi_round_correlation_data(run.run_directory)
    assert len(asset_ids) == len(correlation) == 30
    # Diagonal should be 1.0
    assert correlation[0][0] == pytest.approx(1.0)
    # With factorial model, correlations exist but are not fixed values - just verify structure
    assert -1 <= correlation[0][1] <= 1
    assert -1 <= correlation[0][3] <= 1
    compilation = artifacts.round_results[0]["mis_compilation_result"]
    if compilation and compilation["compiled_job"]:
        assert graph is not None
        persisted = compilation["compiled_job"]["compiled_problem"]["graph"]["edges"]
        assert graph.edges == tuple(tuple(edge) for edge in persisted)
    else:
        assert graph is None


@pytest.mark.parametrize("count", [True, 5, 3.5])
def test_multi_round_portfolio_rejects_invalid_size(tmp_path, count):
    with pytest.raises(ValueError, match="asset_count"):
        run_portfolio_multi_round_experiment("invalid", output_root=tmp_path, asset_count=count)


def test_correlation_remains_available_without_compiled_graph(tmp_path, monkeypatch):
    run = run_portfolio_multi_round_experiment("no-graph", output_root=tmp_path, asset_count=6)
    artifacts = load_experiment_run(run.run_directory)
    monkeypatch.setattr(
        "qreduce.experiments.portfolio_multi_round.load_experiment_run",
        lambda _: replace(artifacts, round_results=()),
    )
    asset_ids, correlation, graph = load_multi_round_correlation_data(run.run_directory)
    assert len(asset_ids) == len(correlation) == 6
    assert graph is None


def test_notebook_displays_persisted_round_and_partial_failure(tmp_path):
    run = run_portfolio_multi_round_experiment("notebook", output_root=tmp_path, asset_count=6)
    artifacts = load_experiment_run(run.run_directory)
    notebook_path = (
        Path(__file__).resolve().parents[2]
        / "notebooks/experiments/004_synthetic_portfolio_multi_round.ipynb"
    )
    notebook = json.loads(notebook_path.read_text(encoding="utf-8"))
    cell = next(cell for cell in notebook["cells"] if cell.get("id") == "86396ca6")
    calls = []
    namespace = {
        "artifacts": SimpleNamespace(round_results=(artifacts.round_results[0], {"round_index": 1})),
        "display_vertical": lambda values, **kwargs: calls.append((values, kwargs)),
    }
    # Execute this repository-owned notebook cell against persisted and partial rounds.
    exec(compile("".join(cell["source"]), str(notebook_path), "exec"), namespace)  # noqa: S102
    assert calls[0][0]["run_status"] == artifacts.round_results[0]["run_status"]
    assert calls[2][0]["run_status"] is None