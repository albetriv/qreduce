"""Tests for the synthetic portfolio experiment runner and filesystem analysis data."""

from dataclasses import replace
from pathlib import Path

import pytest

from qreduce.experiments import (
    ExperimentArtifactError,
)
from qreduce.experiments.portfolio import (
    SYNTHETIC_PORTFOLIO_EXPERIMENT_ID,
    build_synthetic_portfolio_inputs,
    default_graph_policy,
    load_synthetic_portfolio_analysis,
    run_synthetic_portfolio_experiment,
)
from qreduce.experiments.portfolio_generator import default_generation_policy
from qreduce.status import RunStatus


def test_synthetic_portfolio_factory_is_deterministic() -> None:
    """The reference experiment keeps its factorial-model data and run identity."""
    inputs = build_synthetic_portfolio_inputs("run-001")

    assert inputs.config.run_identity.run_id == "run-001"
    # Default is 30 assets with numeric format
    assert len(inputs.problem.asset_ids) == 30
    assert inputs.problem.asset_ids[0] == "asset-000"
    assert inputs.problem.asset_ids[29] == "asset-029"
    # Default graph policy uses near_duplicate with 0.90 threshold
    assert inputs.graph_policy.edge_mode == "near_duplicate"
    assert inputs.graph_policy.correlation_absolute_threshold == pytest.approx(0.90)
    assert inputs.config.mis_solver_id == "local_greedy"
    assert inputs.config.classical_solve.classical_solver_id == "scip"


def test_synthetic_portfolio_factory_with_custom_asset_count() -> None:
    """Asset count parameter creates correctly sized problem."""
    inputs = build_synthetic_portfolio_inputs("run-002", asset_count=12)

    assert len(inputs.problem.asset_ids) == 12
    assert inputs.problem.asset_ids == tuple(f"asset-{i:03d}" for i in range(12))


def test_synthetic_portfolio_factory_configures_dwave_and_cplex_explicitly() -> None:
    """The notebook run can select Ocean simulated annealing and CPLEX without notebook logic."""
    inputs = build_synthetic_portfolio_inputs(
        "dwave-cplex-001",
        asset_count=10,
        mis_solver_id="dwave_simulated_annealing",
        classical_solver_id="cplex",
        mis_num_reads=100,
        mis_num_sweeps=1_000,
    )

    assert inputs.config.mis_solver_id == "dwave_simulated_annealing"
    assert inputs.config.classical_solve.classical_solver_id == "cplex"
    assert dict(inputs.config.mis_execution.provider_parameters) == {
        "num_reads": 100,
        "num_sweeps": 1_000,
    }


def test_synthetic_portfolio_factory_rejects_dwave_parameters_for_other_mis_solvers() -> None:
    """Provider-specific Ocean parameters are not silently accepted by local_greedy."""
    with pytest.raises(ValueError, match="dwave_simulated_annealing"):
        build_synthetic_portfolio_inputs("run-001", mis_num_reads=100)


def test_synthetic_portfolio_factory_with_custom_policies() -> None:
    """Custom generation and graph policies are used."""
    gen_policy = default_generation_policy(15, random_seed=999)
    graph_policy = default_graph_policy("correlation_only", correlation_threshold=0.5)

    inputs = build_synthetic_portfolio_inputs(
        "run-custom",
        asset_count=15,
        generation_policy=gen_policy,
        graph_policy=graph_policy,
    )

    assert inputs.generation_policy == gen_policy
    assert inputs.graph_policy == graph_policy
    assert inputs.graph_policy.edge_mode == "correlation_only"
    assert inputs.graph_policy.correlation_absolute_threshold == 0.5


def test_synthetic_portfolio_analysis_uses_persisted_artifacts(monkeypatch, tmp_path: Path) -> None:
    """Notebook-facing data is reconstructed from the published run, not the pipeline."""

    def missing_scip(module_name: str):
        raise ModuleNotFoundError(module_name)

    monkeypatch.setattr("qreduce.solving.residual.scip_backend._import_module", missing_scip)

    # Use 10 assets for faster test, correlation_only for predictable edges
    graph_policy = default_graph_policy("correlation_only", correlation_threshold=0.5)
    run = run_synthetic_portfolio_experiment(
        "run-001",
        output_root=tmp_path,
        asset_count=10,
        graph_policy=graph_policy,
    )
    analysis = load_synthetic_portfolio_analysis(run.run_directory)

    assert analysis.single_pass_result == analysis.artifacts.round_results[0]
    legacy_artifacts = replace(analysis.artifacts, round_results=())
    assert replace(analysis, artifacts=legacy_artifacts).single_pass_result == legacy_artifacts.result

    assert run.experiment_id == SYNTHETIC_PORTFOLIO_EXPERIMENT_ID
    assert run.result.run_result.run_status is RunStatus.FAILED  # SCIP missing
    assert analysis.asset_ids == analysis.graph.node_ids
    assert len(analysis.asset_ids) == 10
    # Correlation threshold from policy
    assert analysis.correlation_threshold == pytest.approx(0.5)
    # Retained items should exist (from failed MIS phase or similar)
    assert analysis.retained_item_ids is not None
    assert [row["asset"] for row in analysis.domain_rows() if row["retained"]] == list(
        analysis.retained_item_ids
    )


def test_synthetic_portfolio_analysis_rejects_a_different_experiment(monkeypatch, tmp_path: Path) -> None:
    """The portfolio analysis loader cannot silently interpret unrelated artifacts."""

    def missing_scip(module_name: str):
        raise ModuleNotFoundError(module_name)

    monkeypatch.setattr("qreduce.solving.residual.scip_backend._import_module", missing_scip)
    run = run_synthetic_portfolio_experiment("run-001", output_root=tmp_path, asset_count=10)
    manifest_path = run.run_directory / "run_manifest.json"
    manifest_path.write_text(
        manifest_path.read_text(encoding="utf-8").replace(
            SYNTHETIC_PORTFOLIO_EXPERIMENT_ID, "other"
        ),
        encoding="utf-8",
    )

    with pytest.raises(ExperimentArtifactError, match="synthetic portfolio"):
        load_synthetic_portfolio_analysis(run.run_directory)


def test_synthetic_portfolio_analysis_parametric_asset_count(monkeypatch, tmp_path: Path) -> None:
    """End-to-end test with specific asset_count: artifacts are published and analysis is consistent."""

    def missing_scip(module_name: str):
        raise ModuleNotFoundError(module_name)

    monkeypatch.setattr("qreduce.solving.residual.scip_backend._import_module", missing_scip)

    run = run_synthetic_portfolio_experiment(
        "run-12",
        output_root=tmp_path,
        asset_count=12,
    )
    analysis = load_synthetic_portfolio_analysis(run.run_directory)

    assert len(analysis.asset_ids) == 12
    assert len(analysis.correlation) == 12
    assert all(len(row) == 12 for row in analysis.correlation)
    assert analysis.asset_ids == analysis.graph.node_ids
    # Default near_duplicate threshold
    assert analysis.correlation_threshold == pytest.approx(0.90)
