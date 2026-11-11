"""Tests for deterministic notebook examples and partial pipeline outcomes."""

import pytest

from qreduce.notebook_examples import energy_example, graph_example


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