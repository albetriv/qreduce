"""Tests for repository-internal experiment persistence and filesystem loading."""

import json
from pathlib import Path

import pytest

from qreduce.domains.portfolio import (
    MeanVariancePortfolioAdapter,
    PortfolioGraphPolicy,
    PortfolioProblem,
)
from qreduce.experiments import (
    ExperimentArtifactError,
    load_experiment_run,
    run_experiment,
)
from qreduce.models import (
    ClassicalSolveOptions,
    LambdaEdgePolicy,
    MISExecutionOptions,
    ReductionPolicy,
    ResolvedRunConfig,
    RunIdentity,
)
from qreduce.status import PostcheckMode, RunStatus


def _config(run_id: str) -> ResolvedRunConfig:
    return ResolvedRunConfig(
        schema_version="1.0",
        reduction=ReductionPolicy(1, 1, 3, 1, 0.1, 3, 60.0),
        lambda_edge=2.0,
        lambda_edge_policy=LambdaEdgePolicy("standard", "1", 2.0),
        allow_noncertifying_penalty=False,
        mis_solver_id="local_greedy",
        mis_execution=MISExecutionOptions(1, 17, 1, False, 0, 0.0, 20),
        classical_solve=ClassicalSolveOptions(
            "cplex",
            10.0,
            None,
            1,
            False,
            1e-6,
            1e-6,
            1e-6,
            1e-6,
            PostcheckMode.STRICT,
            7,
        ),
        run_identity=RunIdentity(run_id),
    )


def _problem() -> PortfolioProblem:
    asset_ids = ("asset-a", "asset-b", "asset-c")
    return PortfolioProblem(
        asset_ids=asset_ids,
        expected_returns={"asset-a": 0.1, "asset-b": 0.08, "asset-c": 0.06},
        covariance=((0.04, 0.016, 0.0), (0.016, 0.04, -0.012), (0.0, -0.012, 0.04)),
        lower_bounds={asset_id: 0.0 for asset_id in asset_ids},
        upper_bounds={asset_id: 0.7 for asset_id in asset_ids},
        retention_scores={"asset-a": 0.9, "asset-b": 0.7, "asset-c": 0.8},
        risk_aversion=1.0,
    )


def test_runner_persists_normalized_failure_for_notebook_analysis(
    monkeypatch, tmp_path: Path
) -> None:
    """A QReduce failure remains inspectable without rerunning the pipeline."""

    def missing_cplex(module_name: str):
        raise ModuleNotFoundError(module_name)

    monkeypatch.setattr("qreduce.classical.cplex_backend._import_module", missing_cplex)
    run = run_experiment(
        "portfolio-reference",
        _problem(),
        MeanVariancePortfolioAdapter(PortfolioGraphPolicy("test-policy", "1", 0.25)),
        _config("run-001"),
        output_root=tmp_path,
    )

    assert run.result.run_result.run_status is RunStatus.FAILED
    assert run.run_directory == tmp_path / "portfolio-reference" / "run-001"
    loaded = load_experiment_run(run.run_directory)
    assert loaded.manifest["experiment_id"] == "portfolio-reference"
    assert loaded.manifest["run_id"] == "run-001"
    assert loaded.result["run_result"]["run_status"] == "failed"
    assert loaded.canonical_mwis_problem is not None
    assert loaded.canonical_mwis_problem["graph"]["node_ids"] == [
        "asset-a",
        "asset-b",
        "asset-c",
    ]


def test_runner_refuses_to_overwrite_a_published_experiment(
    monkeypatch, tmp_path: Path
) -> None:
    """A run ID identifies one immutable published artifact directory."""

    def missing_cplex(module_name: str):
        raise ModuleNotFoundError(module_name)

    monkeypatch.setattr("qreduce.classical.cplex_backend._import_module", missing_cplex)
    arguments = (
        "portfolio-reference",
        _problem(),
        MeanVariancePortfolioAdapter(PortfolioGraphPolicy("test-policy", "1", 0.25)),
        _config("run-001"),
    )
    run_experiment(*arguments, output_root=tmp_path)

    with pytest.raises(FileExistsError, match="already exists"):
        run_experiment(*arguments, output_root=tmp_path)


def test_loader_rejects_incomplete_directories(tmp_path: Path) -> None:
    """Notebooks cannot mistake an incomplete directory for a published experiment."""

    incomplete_directory = tmp_path / "incomplete"
    incomplete_directory.mkdir()

    with pytest.raises(ExperimentArtifactError, match="incomplete"):
        load_experiment_run(incomplete_directory)


def test_loader_rejects_artifacts_changed_after_publication(
    monkeypatch, tmp_path: Path
) -> None:
    """The manifest prevents notebooks from analyzing changed experiment data."""

    def missing_cplex(module_name: str):
        raise ModuleNotFoundError(module_name)

    monkeypatch.setattr("qreduce.classical.cplex_backend._import_module", missing_cplex)
    run = run_experiment(
        "portfolio-reference",
        _problem(),
        MeanVariancePortfolioAdapter(PortfolioGraphPolicy("test-policy", "1", 0.25)),
        _config("run-001"),
        output_root=tmp_path,
    )
    result_path = run.run_directory / "run_result.json"
    contents = json.loads(result_path.read_text(encoding="utf-8"))
    contents["metrics"]["candidate_domain_size"] = 999
    result_path.write_text(json.dumps(contents), encoding="utf-8")

    with pytest.raises(ExperimentArtifactError, match="Content hash mismatch"):
        load_experiment_run(run.run_directory)
