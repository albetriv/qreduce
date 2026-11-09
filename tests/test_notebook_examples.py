"""Tests for deterministic notebook examples and partial pipeline outcomes."""

import pytest

from qreduce.notebook_examples import energy_example, graph_example, portfolio_example


def test_graph_example_certifies_small_mwis() -> None:
    example = graph_example()
    assert example["exact"].delta == (1, 0, 1)
    assert example["exact"].is_certified_mwis_optimum
    assert len(example["edges"]) == 2


def test_energy_example_preserves_all_energies() -> None:
    energies = energy_example()["energies"]
    assert len(energies) == 8
    for row in energies:
        assert row["qubo_energy"] == pytest.approx(row["ising_energy"])


def test_portfolio_example_reports_missing_cplex_without_fallback(monkeypatch) -> None:
    def missing(name: str):
        raise ModuleNotFoundError(name)

    monkeypatch.setattr("qreduce.classical.cplex_backend._import_module", missing)
    example = portfolio_example()
    assert example["graph"].node_ids == tuple(example["assets"])
    assert example["graph"].edges == (("asset-a", "asset-b"),)
    assert [row["retention_score"] for row in example["nodes"]] == [0.9, 0.7, 0.6]
    assert [row["asset"] for row in example["domain"] if row["retained"]] == example["retained_ids"]
    result = example["result"]
    assert result["run_result"]["run_status"] == "failed"
    assert result["run_result"]["terminal_reason"] == "classical_backend_unavailable"
    assert result["retained_item_ids"]
    assert result["fixing_manifest"] is not None


def test_portfolio_example_distinguishes_unavailable_domain(monkeypatch) -> None:
    from types import SimpleNamespace

    monkeypatch.setattr(
        "qreduce.notebook_examples.run_single_pass",
        lambda *args: SimpleNamespace(retained_item_ids=(), fixing_manifest=None, to_dict=dict),
    )
    example = portfolio_example()
    assert example["retained_ids"] is None
    assert all(row["retained"] is None for row in example["domain"])


def test_plot_reduction_graph_renders_nodes_edges_and_selection() -> None:
    matplotlib = pytest.importorskip("matplotlib")
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from qreduce.notebook_plots import plot_reduction_graph

    graph = graph_example()["graph"]
    fig, ax = plot_reduction_graph(graph, ("a", "c"), highlighted_label="Selezionati")
    try:
        assert len(ax.lines) == len(graph.edges)
        assert len(ax.collections) == len(graph.node_ids)
        assert [label.get_text() for label in ax.get_legend().get_texts()] == ["Selezionati", "Altri nodi"]
        assert [text.get_text() for text in ax.texts] == ["a\nw=2", "b\nw=1", "c\nw=3"]
        with pytest.raises(ValueError, match="highlighted_ids"):
            plot_reduction_graph(graph, ("unknown",))
    finally:
        plt.close(fig)


def test_plot_unknown_selection_has_no_legend() -> None:
    pytest.importorskip("matplotlib")
    import matplotlib.pyplot as plt

    from qreduce.notebook_plots import plot_reduction_graph

    fig, ax = plot_reduction_graph(graph_example()["graph"])
    try:
        assert ax.get_legend() is None
    finally:
        plt.close(fig)