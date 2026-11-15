import pytest

from qreduce.domains.contracts import FixingEntry, FixingManifest
from qreduce.experiments.facility_location.adapter import FacilityLocationAdapter
from qreduce.experiments.facility_location.datasets import parse_or_library
from qreduce.experiments.facility_location.graph_policy import (
    FacilityLocationGraphPolicy,
)


def test_graph_fixing_and_capacity():
    problem = parse_or_library("3 1 5 0 5 0 5 0 8 0 0 0")
    adapter = FacilityLocationAdapter(FacilityLocationGraphPolicy())
    ids = adapter.identify_reducible_items(problem)
    assert not adapter.validate_candidate_domain(problem, (ids[0],)).is_valid
    assert adapter.validate_candidate_domain(problem, tuple(ids[:2])).is_valid
    assert adapter.build_conflict_graph(problem).to_dict() == adapter.build_conflict_graph(problem).to_dict()
    manifest = adapter.build_fixing_manifest(problem, tuple(ids[:2]))
    assert set(manifest.entries[0].variable_values) == {"delta_2", "x_2_0"}
    residual = adapter.restrict_problem(problem, tuple(ids[:2]), manifest)
    assert adapter.describe_logical_variables(residual).binary_free == 2


def test_pipeline_recovery_and_artifacts(tmp_path):
    pytest.importorskip("pyscipopt")
    from qreduce.experiments.facility_location.analysis import summary
    from qreduce.experiments.facility_location.run import run

    instance = tmp_path / "instance.txt"
    instance.write_text("3 1 5 0 5 0 5 0 8 0 0 0", encoding="ascii")
    baseline = run(instance, "baseline", output_root=tmp_path, rounds=0)
    recovered = run(instance, "recovery", output_root=tmp_path, rounds=1, recovery_attempts=5)
    control = run(instance, "control", output_root=tmp_path, rounds=1, protect_all=True)
    multi = run(instance, "multi", output_root=tmp_path, rounds=3, recovery_attempts=5)
    assert summary(baseline.run_directory)["status"] == "success"
    assert summary(recovered.run_directory)["status"] == "success"
    assert recovered.result.recovery_attempts
    assert recovered.result.recovery_attempts[-1].outcome == "retry"
    assert recovered.result.recovery_attempts[-1].expanded_domain_size > recovered.result.recovery_attempts[-1].previous_domain_size
    assert summary(recovered.run_directory)["postcheck"]["postcheck_feasible"]
    assert summary(control.run_directory)["objective"] == pytest.approx(summary(baseline.run_directory)["objective"])
    assert summary(multi.run_directory)["status"] == "success"


def test_recovery_cap_incompatible(tmp_path):
    pytest.importorskip("pyscipopt")
    from qreduce.experiments.facility_location.run import run

    instance = tmp_path / "cap.txt"
    instance.write_text("3 1 5 0 5 0 5 0 8 0 0 0", encoding="ascii")
    result = run(instance, "cap", output_root=tmp_path, rounds=1, cap=1, recovery_attempts=3)
    assert result.result.run_result.run_status.value == "failed"
    assert result.result.classical_result is None


def test_manifest_is_authoritative():
    from qreduce.models import ClassicalSolveOptions
    from qreduce.status import PostcheckMode

    problem = parse_or_library("3 1 5 0 5 0 5 0 8 0 0 0")
    adapter = FacilityLocationAdapter()
    ids = adapter.identify_reducible_items(problem)
    good = adapter.build_fixing_manifest(problem, tuple(ids[:2]))
    wrong_domain = FixingManifest(tuple(ids), (), (), "test")
    with pytest.raises(ValueError, match="retained"):
        adapter.restrict_problem(problem, tuple(ids[:2]), wrong_domain)
    invalid = FixingManifest(tuple(ids[:2]), (ids[2],), (FixingEntry(ids[2], {"delta_2": 1, "x_2_0": 0}, "test"),), "test")
    with pytest.raises(ValueError, match="zero"):
        adapter.restrict_problem(problem, tuple(ids[:2]), invalid)
    options = ClassicalSolveOptions("scip", 10, None, 1, False, 1e-6, 1e-6, 1e-6, 1e-6, PostcheckMode.STRICT)
    values = {"delta_0": 1, "delta_1": 1, "delta_2": 0, "x_0_0": 0.5, "x_1_0": 0.5, "x_2_0": 0}
    assert not adapter.validate_final_solution(problem, values, invalid, options).fixed_variable_compliance
    assert adapter.validate_final_solution(problem, values, good, options).postcheck_feasible
    unknown = FixingManifest(tuple(ids) + ("unknown_facility",), (), (), "test")
    assert not adapter.validate_final_solution(problem, values, unknown, options).postcheck_feasible
    missing = FixingManifest(tuple(ids[:2]), (), (), "test")
    assert not adapter.validate_final_solution(problem, values, missing, options).postcheck_feasible


def test_induced_graph_protections_and_cumulative_fixings():
    problem = parse_or_library("4 1 5 0 5 0 5 0 5 0 8 0 0 0 0")
    adapter = FacilityLocationAdapter()
    ids = adapter.identify_reducible_items(problem)
    graph = adapter.build_conflict_graph(problem)
    assert set(graph.node_weights.values()) == {1.0}
    assert len(graph.edges) == 6
    first = adapter.build_fixing_manifest(problem, tuple(ids[:3]))
    residual = adapter.restrict_problem(problem, tuple(ids[:3]), first)
    induced = adapter.build_conflict_graph(residual)
    assert induced.edges == tuple(edge for edge in graph.edges if set(edge) <= set(ids[:3]))
    second = adapter.build_fixing_manifest(residual, tuple(ids[:2]))
    reduced = adapter.restrict_problem(residual, tuple(ids[:2]), second)
    assert reduced.excluded_facilities == (2, 3)
    assert adapter.describe_logical_variables(reduced).continuous_free == 2
    assert set(adapter.declare_protected_items(reduced)) == set(ids[:2])


def test_benchmark_persists_preparation_errors(tmp_path):
    import json

    from qreduce.experiments.facility_location.benchmark import benchmark

    report = benchmark(tmp_path / "missing.txt", "missing", output_root=tmp_path)
    assert "preparation_error" in report["results"]["baseline"]
    assert json.loads((tmp_path / "missing-benchmark.json").read_text())["results"] == report["results"]


@pytest.mark.parametrize("stage", ["execution", "analysis"])
def test_benchmark_classifies_errors(tmp_path, monkeypatch, stage):
    from types import SimpleNamespace

    from qreduce.experiments.facility_location import benchmark as module

    instance = tmp_path / "instance.txt"
    instance.write_text("1 1 5 0 5 0", encoding="ascii")
    def fail(*args, **kwargs):
        raise RuntimeError("injected")
    if stage == "execution":
        monkeypatch.setattr(module, "run", fail)
    else:
        monkeypatch.setattr(module, "run", lambda *args, **kwargs: SimpleNamespace(run_directory=tmp_path))
        monkeypatch.setattr(module, "summary", fail)
    report = module.benchmark(instance, stage, output_root=tmp_path)
    assert all(f"{stage}_error" in item for item in report["results"].values())


def test_benchmark_control_ignores_restrictive_cap(tmp_path):
    pytest.importorskip("pyscipopt")
    from qreduce.experiments.facility_location.benchmark import benchmark

    instance = tmp_path / "instance.txt"
    instance.write_text("3 1 5 0 5 0 5 0 8 0 0 0", encoding="ascii")
    report = benchmark(instance, "check", output_root=tmp_path, cap=1)
    results = report["results"]
    assert results["all_protected"]["status"] == "success"
    assert results["all_protected"]["objective"] == pytest.approx(results["baseline"]["objective"])
    assert results["all_protected"]["requested_cap"] is None
    assert results["single"]["requested_cap"] == 1
    assert results["single"]["graph_build_seconds"] is not None


def test_cli_failure_exit_code(tmp_path):
    import os
    import subprocess
    import sys

    pytest.importorskip("pyscipopt")
    instance = tmp_path / "instance.txt"
    instance.write_text("3 1 5 0 5 0 5 0 8 0 0 0", encoding="ascii")
    environment = dict(os.environ, PYTHONPATH=str(__import__("pathlib").Path(__file__).resolve().parents[3] / "src"))
    command = [sys.executable, "-m", "qreduce.experiments.facility_location.run", str(instance), "--run-id", "failed", "--output-root", str(tmp_path), "--rounds", "1", "--cap", "1"]
    result = subprocess.run(command, env=environment, capture_output=True, text=True, check=False)
    assert result.returncode == 1