"""Tests for the synthetic portfolio experiment runner and filesystem analysis data."""

from pathlib import Path

import pytest

from qreduce.experiments import (
    ExperimentArtifactError,
)
from qreduce.experiments.portfolio import (
    SYNTHETIC_PORTFOLIO_EXPERIMENT_ID,
    build_synthetic_portfolio_inputs,
    load_synthetic_portfolio_analysis,
    run_synthetic_portfolio_experiment,
)
from qreduce.status import RunStatus


def test_synthetic_portfolio_factory_is_deterministic() -> None:
    """The reference experiment keeps its fixed five-asset data and run identity."""

    inputs = build_synthetic_portfolio_inputs("run-001")

    assert inputs.config.run_identity.run_id == "run-001"
    assert inputs.problem.asset_ids == (
        "asset-a",
        "asset-b",
        "asset-c",
        "asset-d",
        "asset-e",
    )
    assert inputs.graph_policy.correlation_absolute_threshold == pytest.approx(0.25)
    assert inputs.problem.correlation("asset-b", "asset-c") == pytest.approx(-0.3)


def test_synthetic_portfolio_analysis_uses_persisted_artifacts(monkeypatch, tmp_path: Path) -> None:
    """Notebook-facing data is reconstructed from the published run, not the pipeline."""

    def missing_cplex(module_name: str):
        raise ModuleNotFoundError(module_name)

    monkeypatch.setattr("qreduce.classical.cplex_backend._import_module", missing_cplex)
    run = run_synthetic_portfolio_experiment("run-001", output_root=tmp_path)
    analysis = load_synthetic_portfolio_analysis(run.run_directory)

    assert run.experiment_id == SYNTHETIC_PORTFOLIO_EXPERIMENT_ID
    assert run.result.run_result.run_status is RunStatus.FAILED
    assert analysis.asset_ids == analysis.graph.node_ids
    assert analysis.graph.edges == (
        ("asset-a", "asset-b"),
        ("asset-b", "asset-c"),
        ("asset-c", "asset-d"),
        ("asset-d", "asset-e"),
    )
    assert analysis.correlation[1][2] == pytest.approx(-0.3)
    assert analysis.correlation_threshold == pytest.approx(0.25)
    assert analysis.retained_item_ids is not None
    assert [row["asset"] for row in analysis.domain_rows() if row["retained"]] == list(
        analysis.retained_item_ids
    )


def test_synthetic_portfolio_analysis_rejects_a_different_experiment(monkeypatch, tmp_path: Path) -> None:
    """The portfolio analysis loader cannot silently interpret unrelated artifacts."""

    def missing_cplex(module_name: str):
        raise ModuleNotFoundError(module_name)

    monkeypatch.setattr("qreduce.classical.cplex_backend._import_module", missing_cplex)
    run = run_synthetic_portfolio_experiment("run-001", output_root=tmp_path)
    manifest_path = run.run_directory / "run_manifest.json"
    manifest_path.write_text(manifest_path.read_text(encoding="utf-8").replace(SYNTHETIC_PORTFOLIO_EXPERIMENT_ID, "other"), encoding="utf-8")

    with pytest.raises(ExperimentArtifactError, match="synthetic portfolio"):
        load_synthetic_portfolio_analysis(run.run_directory)