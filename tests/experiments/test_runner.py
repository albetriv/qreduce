"""Tests for repository-internal experiment persistence and filesystem loading."""

import importlib.util
import json
from dataclasses import replace
from pathlib import Path

import pytest

from qreduce.domains import DomainEvaluationMetric, FinalSolutionValidationResult
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
    PolicyProvenance,
    ReductionPolicy,
    ResolvedRunConfig,
    RunIdentity,
    RunResult,
)
from qreduce.pipeline import SinglePassRunResult, run_single_pass
from qreduce.solving.residual import ClassicalSolveResult
from qreduce.status import (
    AdoptionStatus,
    ClassicalSolverStatus,
    PipelineStage,
    PostcheckMode,
    PostcheckStatus,
    RunStatus,
    TerminalReason,
)


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


def _postchecked_result(problem, adapter, config, **kwargs):
    del problem, adapter, kwargs
    return SinglePassRunResult(
        resolved_config=config,
        run_result=RunResult(config.run_identity.run_id, RunStatus.SUCCESS,
                             PipelineStage.POSTCHECK, None, ClassicalSolverStatus.OPTIMAL,
                             PostcheckStatus.PASSED, AdoptionStatus.ADOPTED),
        classical_result=ClassicalSolveResult(
            ClassicalSolverStatus.OPTIMAL, None, True, 1.0, 1.0, 0.0, True, False, 0.1
        ),
        postcheck_result=FinalSolutionValidationResult(True, True, True, True, 1.0, True),
    )


def test_domain_metrics_persist_and_redact(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("qreduce.pipeline.single_pass._run_single_pass", _postchecked_result)

    class EvaluatingAdapter(MeanVariancePortfolioAdapter):
        def evaluate_domain_metrics(self, problem, classical_result, postcheck_result):
            assert classical_result.solver_claimed_feasible and postcheck_result.postcheck_feasible
            return [DomainEvaluationMetric("quality", None, "unitless", "higher",
                                           "https://example.com/?token=secret")]

    run = run_experiment("metrics", _problem(), EvaluatingAdapter(
        PortfolioGraphPolicy("test", "1", 0.25)), _config("run"), output_root=tmp_path)
    assert run.result.domain_evaluation_metrics[0].value is None
    metric = load_experiment_run(run.run_directory).result["domain_evaluation_metrics"][0]
    assert metric["metric_id"] == "quality"
    assert "secret" not in metric["provenance"]


@pytest.mark.parametrize("mode", ["missing", "exception", "invalid", "duplicate"])
def test_domain_metric_failure_preserves_postcheck(monkeypatch, mode) -> None:
    monkeypatch.setattr("qreduce.pipeline.single_pass._run_single_pass", _postchecked_result)

    class EvaluatingAdapter(MeanVariancePortfolioAdapter):
        def evaluate_domain_metrics(self, problem, classical_result, postcheck_result):
            if mode == "exception":
                raise ValueError("evaluation failed")
            if mode == "invalid":
                return [object()]
            metric = DomainEvaluationMetric("quality", 1, "unitless", "higher", "test")
            return [metric, metric]

    adapter = EvaluatingAdapter(PortfolioGraphPolicy("test", "1", 0.25))
    if mode == "missing":
        adapter.evaluate_domain_metrics = None
    result = run_single_pass(_problem(), adapter, _config("run"))
    assert result.run_result.terminal_reason is TerminalReason.ADAPTER_FAILURE
    assert result.run_result.adoption_status is AdoptionStatus.NOT_ADOPTED
    assert result.classical_result is not None and result.postcheck_result is not None
    assert result.domain_evaluation_metrics is None


def test_metrics_run_after_failed_postcheck(monkeypatch) -> None:
    def failed_postcheck(problem, adapter, config, **kwargs):
        result = _postchecked_result(problem, adapter, config, **kwargs)
        return replace(result,
            run_result=replace(result.run_result, run_status=RunStatus.FAILED,
                               postcheck_status=PostcheckStatus.FAILED,
                               adoption_status=AdoptionStatus.NOT_ADOPTED,
                               terminal_reason=TerminalReason.POSTCHECK_FAILED),
            postcheck_result=FinalSolutionValidationResult(
                False, True, False, True, None, None, ("constraint",)))

    monkeypatch.setattr("qreduce.pipeline.single_pass._run_single_pass", failed_postcheck)
    adapter = MeanVariancePortfolioAdapter(PortfolioGraphPolicy("test", "1", 0.25))
    result = run_single_pass(_problem(), adapter, _config("run"))
    assert result.run_result.terminal_reason is TerminalReason.POSTCHECK_FAILED
    assert result.domain_evaluation_metrics == ()


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
    assert loaded.result["original_variable_counts"] == {
        "binary_free": 3, "integer_free": 0, "continuous_free": 3
    }
    assert loaded.result["residual_variable_counts"] == {
        "binary_free": 2, "integer_free": 0, "continuous_free": 2
    }
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


def test_manifest_preserves_redacted_policy_provenance(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("qreduce.pipeline.single_pass._run_single_pass", _postchecked_result)
    config = replace(_config("policy-run"), policy_provenance=PolicyProvenance(
        policy_id="policy-1", policy_version="v1", policy_hash="abc",
        policy_source="https://example.com/?token=secret",
    ))
    adapter = MeanVariancePortfolioAdapter(PortfolioGraphPolicy("test", "1", 0.25))
    run = run_experiment("policy", _problem(), adapter, config, output_root=tmp_path)
    loaded = load_experiment_run(run.run_directory)
    provenance = loaded.manifest["policy_provenance"]
    assert provenance == loaded.config["policy_provenance"]
    assert provenance["policy_id"] == "policy-1"
    assert run.result.run_result.policy_hash == "abc"
    assert "secret" not in provenance["policy_source"]


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


@pytest.mark.parametrize("scenario", [
    "success",
    "partial_success",
    "failed_postcheck",
    "failed_classical",
])
def test_terminal_outcomes_round_trip_through_artifact_serialization(
    monkeypatch, tmp_path: Path, scenario: str
) -> None:
    """Every terminal outcome is persisted and loaded with correct status fields."""

    expected = {
        "success": (RunStatus.SUCCESS, None, ClassicalSolverStatus.OPTIMAL,
                    PostcheckStatus.PASSED, AdoptionStatus.ADOPTED),
        "partial_success": (RunStatus.PARTIAL_SUCCESS, None,
                            ClassicalSolverStatus.TIME_LIMIT_WITH_FEASIBLE_INCUMBENT,
                            PostcheckStatus.PASSED, AdoptionStatus.ADOPTED),
        "failed_postcheck": (RunStatus.FAILED, TerminalReason.POSTCHECK_FAILED,
                             ClassicalSolverStatus.OPTIMAL, PostcheckStatus.FAILED,
                             AdoptionStatus.NOT_ADOPTED),
        "failed_classical": (RunStatus.FAILED, TerminalReason.CLASSICAL_SOLVER_FAILED,
                             ClassicalSolverStatus.NOT_RUN, PostcheckStatus.NOT_RUN,
                             AdoptionStatus.NOT_ADOPTED),
    }

    def make_result(problem, adapter, config, **kwargs):
        del problem, adapter, kwargs
        run_status, terminal, solver_status, postcheck, adoption = expected[scenario]
        return SinglePassRunResult(
            resolved_config=config,
            run_result=RunResult(
                config.run_identity.run_id, run_status, PipelineStage.POSTCHECK,
                terminal, solver_status, postcheck, adoption
            ),
            classical_result=ClassicalSolveResult(
                solver_status, terminal if scenario == "failed_classical" else None,
                solver_status not in (ClassicalSolverStatus.NOT_RUN, ClassicalSolverStatus.INFEASIBLE),
                1.0 if solver_status != ClassicalSolverStatus.NOT_RUN else None,
                1.0 if solver_status != ClassicalSolverStatus.NOT_RUN else None,
                0.1 if scenario == "partial_success" else 0.0,
                solver_status == ClassicalSolverStatus.OPTIMAL,
                scenario == "partial_success",
                0.1,
            ) if scenario != "failed_classical" else None,
            postcheck_result=FinalSolutionValidationResult(
                postcheck == PostcheckStatus.PASSED,
                True, postcheck == PostcheckStatus.PASSED, True,
                1.0 if postcheck == PostcheckStatus.PASSED else None,
                True if postcheck == PostcheckStatus.PASSED else None,
                () if postcheck == PostcheckStatus.PASSED else ("constraint_violation",),
            ) if scenario not in ("failed_classical",) else None,
        )

    monkeypatch.setattr("qreduce.pipeline.single_pass._run_single_pass", make_result)
    run = run_experiment(
        f"roundtrip-{scenario}", _problem(),
        MeanVariancePortfolioAdapter(PortfolioGraphPolicy("test", "1", 0.25)),
        _config(f"run-{scenario}"), output_root=tmp_path,
    )

    # Verify the in-memory result
    run_status, terminal, solver_status, postcheck, adoption = expected[scenario]
    assert run.result.run_result.run_status is run_status
    assert run.result.run_result.terminal_reason is terminal
    assert run.result.run_result.classical_solver_status is solver_status
    assert run.result.run_result.postcheck_status is postcheck
    assert run.result.run_result.adoption_status is adoption

    # Verify round-trip through filesystem
    loaded = load_experiment_run(run.run_directory)
    assert loaded.result["run_result"]["run_status"] == run_status.value
    assert loaded.result["run_result"]["terminal_reason"] == (terminal.value if terminal else None)
    assert loaded.result["run_result"]["classical_solver_status"] == solver_status.value
    assert loaded.result["run_result"]["postcheck_status"] == postcheck.value
    assert loaded.result["run_result"]["adoption_status"] == adoption.value
