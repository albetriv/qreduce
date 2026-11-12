"""Tests for repository-internal experiment persistence and filesystem loading."""

import importlib.util
import json
from dataclasses import replace
from pathlib import Path

import pytest

from qreduce.experiments import (
    ExperimentArtifactError,
    load_experiment_run,
    run_experiment,
)
from qreduce.experiments.portfolio_domain import (
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
from qreduce.pipeline import run_single_pass
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

    monkeypatch.setattr("qreduce.solving.residual.cplex_backend._import_module", missing_cplex)
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
    assert loaded.result["candidate_records"][0]["selection_status"] == "selected"
    assert loaded.result["candidate_domain_item_records"]
    assert loaded.result["protection_declaration"]["mandatory_item_ids"] == []
    assert "\n  \"run_result\":" in (run.run_directory / "run_result.json").read_text(
        encoding="utf-8"
    )
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

    monkeypatch.setattr("qreduce.solving.residual.cplex_backend._import_module", missing_cplex)
    arguments = (
        "portfolio-reference",
        _problem(),
        MeanVariancePortfolioAdapter(PortfolioGraphPolicy("test-policy", "1", 0.25)),
        _config("run-001"),
    )
    run_experiment(
        *arguments,
        output_root=tmp_path,
    )

    with pytest.raises(FileExistsError, match="already exists"):
        run_experiment(
            *arguments,
            output_root=tmp_path,
        )


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

    monkeypatch.setattr("qreduce.solving.residual.cplex_backend._import_module", missing_cplex)
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


def test_direct_pipeline_rejects_missing_export_path() -> None:
    config = _config("missing-path")
    config = replace(config, classical_solve=replace(config.classical_solve, model_export_enabled=True))
    result = run_single_pass(
        _problem(), MeanVariancePortfolioAdapter(PortfolioGraphPolicy("test", "1", 0.25)), config
    )
    assert result.run_result.terminal_reason.value == "invalid_configuration"
    assert "file path" in result.run_result.diagnostic_message


@pytest.mark.skipif(importlib.util.find_spec("pyscipopt") is None, reason="SCIP not installed")
def test_direct_pipeline_exports_to_requested_path_and_refuses_overwrite(tmp_path: Path) -> None:
    target = tmp_path / "direct.lp"
    config = _config("direct")
    config = replace(config, classical_solve=replace(
        config.classical_solve, classical_solver_id="scip", model_export_enabled=True,
        model_export_path=str(target),
    ))
    adapter = MeanVariancePortfolioAdapter(PortfolioGraphPolicy("test", "1", 0.25))
    result = run_single_pass(_problem(), adapter, config)
    assert target.is_file()
    assert result.classical_result.model_export_path == str(target)
    contents = target.read_bytes()
    second = run_single_pass(_problem(), adapter, config)
    assert second.run_result.terminal_reason.value == "invalid_configuration"
    assert target.read_bytes() == contents


def test_missing_backend_does_not_publish_model(monkeypatch, tmp_path: Path) -> None:
    def missing_cplex(module_name: str):
        raise ModuleNotFoundError(module_name)

    monkeypatch.setattr("qreduce.solving.residual.cplex_backend._import_module", missing_cplex)
    config = _config("missing-backend")
    config = replace(config, classical_solve=replace(config.classical_solve, model_export_enabled=True))
    run = run_experiment(
        "portfolio-reference", _problem(),
        MeanVariancePortfolioAdapter(PortfolioGraphPolicy("test", "1", 0.25)),
        config, output_root=tmp_path,
    )
    assert run.result.run_result.run_status is RunStatus.FAILED
    assert not (run.run_directory / "residual_model.lp").exists()
    assert load_experiment_run(run.run_directory).manifest["model_export"] is None


@pytest.mark.skipif(importlib.util.find_spec("pyscipopt") is None, reason="SCIP not installed")
@pytest.mark.parametrize("external", [False, True])
def test_model_export_is_published_and_auditable(tmp_path: Path, external: bool) -> None:
    config = _config("export-run")
    custom = tmp_path / "custom.lp" if external else None
    config = replace(config, classical_solve=replace(
        config.classical_solve, classical_solver_id="scip", model_export_enabled=True,
        model_export_path=str(custom) if custom else None,
    ))
    run = run_experiment(
        "portfolio-reference", _problem(),
        MeanVariancePortfolioAdapter(PortfolioGraphPolicy("test", "1", 0.25)),
        config, output_root=tmp_path,
    )
    model = custom or run.run_directory / "residual_model.lp"
    assert model.is_file()
    assert run.result.classical_result.model_export_path == str(model)
    assert run.result.resolved_config.classical_solve.model_export_path == str(model)
    loaded = load_experiment_run(run.run_directory)
    assert loaded.manifest["model_export"]["external"] is external
    assert loaded.manifest["model_export"]["format"] == "lp"
    if not external:
        model.write_text("tampered", encoding="utf-8")
        with pytest.raises(ExperimentArtifactError, match="Content hash mismatch"):
            load_experiment_run(run.run_directory)


def test_external_export_refuses_existing_file(tmp_path: Path) -> None:
    target = tmp_path / "existing.lp"
    target.write_text("keep", encoding="utf-8")
    config = _config("collision")
    config = replace(config, classical_solve=replace(
        config.classical_solve, model_export_enabled=True, model_export_path=str(target)
    ))
    with pytest.raises(FileExistsError):
        run_experiment(
            "portfolio-reference", _problem(),
            MeanVariancePortfolioAdapter(PortfolioGraphPolicy("test", "1", 0.25)),
            config, output_root=tmp_path,
        )
    assert target.read_text(encoding="utf-8") == "keep"
    assert not (tmp_path / "portfolio-reference" / "collision").exists()


@pytest.mark.skipif(importlib.util.find_spec("pyscipopt") is None, reason="SCIP not installed")
def test_export_cleanup_when_artifact_publication_fails(monkeypatch, tmp_path: Path) -> None:
    config = _config("write-failure")
    config = replace(config, classical_solve=replace(
        config.classical_solve, classical_solver_id="scip", model_export_enabled=True,
        model_export_path=str(tmp_path / "external.lp"),
    ))
    def fail_publication(*args, **kwargs):
        raise OSError("publication failed")

    monkeypatch.setattr("qreduce.experiments.runner.os.replace", fail_publication)
    with pytest.raises(OSError, match="publication failed"):
        run_experiment(
            "portfolio-reference", _problem(),
            MeanVariancePortfolioAdapter(PortfolioGraphPolicy("test", "1", 0.25)),
            config, output_root=tmp_path,
        )
    assert not (tmp_path / "external.lp").exists()
    assert not (tmp_path / "portfolio-reference" / "write-failure").exists()
    assert not list(tmp_path.glob(".qreduce-export.*"))
