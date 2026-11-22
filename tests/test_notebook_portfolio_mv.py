"""Artifact-backed portfolio notebook regression tests without solver execution."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from qreduce.mwis import ReductionGraph
from qreduce.notebooks.portfolio_mv import (
    PortfolioRunView,
    allocation_rows,
    exact_diagnostic,
    geometry_report,
    load_run_view,
    plot_allocations,
    plot_mwis_graph,
    plot_pasqal_geometry,
    plot_sampling,
    sampling_rows,
    sampling_summary,
)


def make_view():
    graph = ReductionGraph(("a", "b", "c"), {"a": 2., "b": 1., "c": 3.},
                           (("a", "b"),), {("a", "b"): "test"}, "test", "1")
    result = {"mis_execution_result": {"samples": [
        {"raw_sample_id": "valid", "node_order": ["a", "b", "c"], "delta": [1, 0, 1], "occurrence_count": 8},
        {"raw_sample_id": "invalid", "node_order": ["a", "b", "c"], "delta": [1, 1, 0], "occurrence_count": 2},
    ]}, "selected_mis_samples": [{"node_order": ["a", "b", "c"], "delta": [1, 0, 1]}]}
    analysis = SimpleNamespace(asset_ids=("a", "b", "c"), artifacts=SimpleNamespace(
        manifest={"run_id": "example"}, problem={"asset_ids": ["a", "b", "c"]},
        result={"run_result": {"adoption_status": "adopted"}, "postcheck_result": {"postcheck_feasible": True},
                "classical_result": {"variable_values": {"x__a": .4, "x__b": 0., "x__c": .6}}}))
    return PortfolioRunView(analysis, result, graph,
                            {"node_order": ["a", "b", "c"], "coordinates": [[0., 0.], [5., 0.], [25., 0.]],
                             "mapping": {"radius": 10., "geometric_edges": [["a", "b"]]}})


def test_geometry_recomputed_and_mismatches_exposed():
    view = make_view()
    report = geometry_report(view)
    assert report["congruenti"]
    assert report["coerente_con_archi_persistiti"]
    view.payload["coordinates"][2] = [5., 1.]
    report = geometry_report(view)
    assert not report["congruenti"]
    assert set(report["extra_edges"]) == {("a", "c"), ("b", "c")}
    view.payload["coordinates"][1] = [50., 0.]
    assert ("a", "b") in geometry_report(view)["missing_edges"]


def test_sample_statistics_use_all_raw_occurrences():
    view = make_view()
    assert sampling_summary(view)["frazione_indipendente"] == .8
    assert sampling_rows(view)[0]["peso_MWIS"] == 5.
    assert sampling_rows(view)[1]["archi_violati"] == 1
    view.round_result["mis_execution_result"]["samples"][0]["node_order"] = ["b", "a", "c"]
    with pytest.raises(ValueError, match="order"):
        sampling_rows(view)


def test_exact_is_bounded_and_matches_candidate():
    view = make_view()
    assert exact_diagnostic(view)["selected_ids"] == ["a", "c"]
    assert not exact_diagnostic(view, max_nodes=2)["disponibile"]


def test_baseline_and_missing_layout_are_not_fabricated():
    view = make_view()
    view.graph = None
    view.payload = {}
    assert not geometry_report(view)["disponibile"]
    assert not exact_diagnostic(view)["disponibile"]
    assert sampling_rows(view) == []


def test_allocations_refuse_unadopted_different_and_incomplete_results():
    view, baseline = make_view(), make_view()
    assert sum(row["run"] for row in allocation_rows(view, baseline)) == 1.
    baseline.analysis.artifacts.problem = {"other": True}
    with pytest.raises(ValueError, match="different"):
        allocation_rows(view, baseline)
    view.analysis.artifacts.result["run_result"]["adoption_status"] = "rejected"
    with pytest.raises(ValueError, match="adopted"):
        allocation_rows(view)
    view.analysis.artifacts.result["run_result"]["adoption_status"] = "adopted"
    del view.analysis.artifacts.result["classical_result"]["variable_values"]["x__a"]
    with pytest.raises(ValueError, match="incomplete"):
        allocation_rows(view)


def test_all_plots_without_display_or_backend():
    matplotlib = pytest.importorskip("matplotlib")
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    view = make_view()
    try:
        assert plot_mwis_graph(view) is not None
        assert plot_pasqal_geometry(view) is not None
        _, axes = plot_sampling(view, 2)
        assert [text.get_text() for text in axes[0].texts] == ["2 asset", "2 asset"]
        assert [bar.get_height() for bar in axes[0].patches] == [8, 2]
        assert plot_allocations(view) is not None
    finally:
        plt.close("all")


def test_notebook_code_is_presentation_only():
    import ast

    root = Path(__file__).resolve().parents[1]
    notebook = root / "notebooks/experiments/portfolio_mv/001_mwis_pasqal_2d.ipynb"
    data = json.loads(notebook.read_text())
    for cell in data["cells"]:
        if cell["cell_type"] == "code":
            tree = ast.parse("".join(cell["source"]))
            assert not any(isinstance(node, (ast.FunctionDef, ast.ClassDef)) for node in ast.walk(tree))
            # Saved tables and plots are presentation, not business logic.
            assert not any(output["output_type"] == "error" for output in cell["outputs"])


def test_loader_rejects_traversal(tmp_path):
    with pytest.raises(ValueError, match="subdirectory"):
        load_run_view(tmp_path, "../another")


@pytest.mark.parametrize("reasons", [{"('a', 'b')": "test"}, [{"edge": ["a", "b"], "reason": "test"}]])
def test_loader_accepts_saved_reason_formats(monkeypatch, tmp_path, reasons):
    from qreduce.notebooks import portfolio_mv as module

    analysis = make_view().analysis
    data = make_view().graph.to_dict()
    data["edge_reasons"] = reasons
    analysis.artifacts.round_results = ({"round_index": 0, "mis_compilation_result": {
        "compiled_job": {"compiled_problem": {"graph": data}}}},)
    monkeypatch.setattr(module, "load_portfolio_solution_analysis", lambda _: analysis)
    view = load_run_view(tmp_path, "example")
    assert view.graph.edge_reasons[("a", "b")] == "test"
    with pytest.raises(ValueError, match="not recorded"):
        load_run_view(tmp_path, "example", round_index=1)