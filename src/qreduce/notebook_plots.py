"""Optional Matplotlib visualizations for QReduce notebook examples."""

import math
from collections.abc import Iterable

from qreduce.mwis.graph import ReductionGraph


def plot_reduction_graph(
    graph: ReductionGraph,
    highlighted_ids: Iterable[str] | None = None,
    *,
    highlighted_label: str = "Nodi evidenziati",
    title: str = "Grafo di riduzione",
):
    """Plot the graph using a deterministic circular layout, returning figure and axes.

    None means no selection is available; an empty iterable is a known empty
    selection. Coordinates are illustrative and do not encode graph geometry.
    Matplotlib is imported only when this optional visualization is called.
    """
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

    selected = None if highlighted_ids is None else set(highlighted_ids)
    if selected is not None and selected - set(graph.node_ids):
        raise ValueError("highlighted_ids must contain only nodes in the graph")

    count = len(graph.node_ids)
    coordinates = {
        node: (math.cos(math.pi / 2 - 2 * math.pi * i / count),
               math.sin(math.pi / 2 - 2 * math.pi * i / count))
        for i, node in enumerate(graph.node_ids)
    }
    fig, ax = plt.subplots(figsize=(6.5, 6.5))
    for left, right in graph.edges:
        ax.plot(
            [coordinates[left][0], coordinates[right][0]],
            [coordinates[left][1], coordinates[right][1]],
            color="tab:red", linewidth=2, alpha=0.75, zorder=1,
        )
    for node in graph.node_ids:
        x_pos, y_pos = coordinates[node]
        color = "#b7e4c7" if selected is not None and node in selected else "white"
        ax.scatter(x_pos, y_pos, s=1800, color=color, edgecolor="tab:blue", linewidth=2, zorder=3)
        ax.text(x_pos, y_pos, f"{node}\nw={graph.node_weights[node]:g}",
                ha="center", va="center", color="tab:blue", weight="bold", zorder=4)
    if selected is not None:
        handles = [
            Line2D([0], [0], marker="o", color="none", markerfacecolor="#b7e4c7",
                   markeredgecolor="tab:blue", markersize=10, label=highlighted_label),
            Line2D([0], [0], marker="o", color="none", markerfacecolor="white",
                   markeredgecolor="tab:blue", markersize=10, label="Altri nodi"),
        ]
        ax.legend(handles=handles, loc="upper left", bbox_to_anchor=(1, 1))
    ax.set_title(title)
    ax.set_aspect("equal")
    ax.set_xlim(-1.4, 1.4)
    ax.set_ylim(-1.4, 1.4)
    ax.set_axis_off()
    fig.tight_layout()
    return fig, ax