"""Strict geometric diagnostics for one-atom-per-node neutral-atom layouts.

The geometric threshold is a modelling approximation, not a physical guarantee.
"""

import math
import random
from collections.abc import Callable, Mapping, Sequence
from itertools import combinations

from qreduce.mwis.graph import ReductionGraph


def diagnose_layout(
    graph: ReductionGraph,
    coordinates: Mapping[str, Sequence[float]],
    radius: float,
    margin: float,
) -> dict[str, object]:
    """Compare every canonical pair against the threshold and strict margin."""
    if not (math.isfinite(radius) and math.isfinite(margin) and 0 < margin < radius):
        raise ValueError("Require finite 0 < margin < radius.")
    if set(coordinates) != set(graph.node_ids):
        raise ValueError("Coordinates must cover exactly the canonical node IDs.")
    points = {}
    for node in graph.node_ids:
        point = coordinates[node]
        if len(point) != 2 or any(
            isinstance(v, bool)
            or not isinstance(v, (int, float))
            or not math.isfinite(v)
            for v in point
        ):
            raise ValueError("Each coordinate must contain two finite numbers.")
        points[node] = point
    target = {tuple(sorted(edge)) for edge in graph.edges}
    geometric, missing, extra, margin_pairs = [], [], [], []
    valid = True
    for a, b in combinations(graph.node_ids, 2):
        edge = tuple(sorted((a, b)))
        d = math.dist(points[a], points[b])
        if (edge in target and d > radius - margin) or (
            edge not in target and d < radius + margin
        ):
            valid = False
        if d <= radius:
            geometric.append(edge)
        if edge in target and d > radius:
            missing.append(edge)
        if edge not in target and d <= radius:
            extra.append(edge)
        if radius - margin < d < radius + margin:
            margin_pairs.append(edge)
    return {
        "target_edges": sorted(target),
        "geometric_edges": sorted(geometric),
        "missing_edges": sorted(missing),
        "extra_edges": sorted(extra),
        "margin_pairs": sorted(margin_pairs),
        "valid": valid,
        "radius": radius,
        "margin": margin,
    }


def search_layout(
    graph: ReductionGraph,
    radius: float,
    margin: float,
    *,
    attempts: int = 1000,
    seed: int = 0,
    min_distance: float = 0.0,
    accept: Callable[[dict[str, tuple[float, float]]], bool] | None = None,
    before_attempt: Callable[[], None] | None = None,
) -> tuple[dict[str, tuple[float, float]], dict[str, object]]:
    """Place nodes next to already placed neighbors, with bounded random restarts."""
    if isinstance(attempts, bool) or not isinstance(attempts, int) or attempts < 1:
        raise ValueError("attempts must be a positive integer")
    if not (math.isfinite(radius) and math.isfinite(margin) and 0 < margin < radius):
        raise ValueError("Require finite 0 < margin < radius.")
    if not math.isfinite(min_distance) or min_distance < 0:
        raise ValueError("min_distance must be finite and nonnegative.")
    rng = random.Random(seed)
    neighbors: dict[str, set[str]] = {node: set() for node in graph.node_ids}
    for a, b in graph.edges:
        neighbors[a].add(b)
        neighbors[b].add(a)
    edge_max, nonedge_min = radius - margin, radius + margin
    if graph.edges and min_distance > edge_max:
        raise ValueError("target_minimum_spacing_exceeds_edge_limit")
    width = max(1.0, len(graph.node_ids) ** 0.5) * nonedge_min
    for attempt in range(attempts):
        if before_attempt is not None:
            before_attempt()
        remaining = list(graph.node_ids)
        rng.shuffle(remaining)
        coords: dict[str, tuple[float, float]] = {}
        while remaining:
            node = max(
                remaining,
                key=lambda n: (len(neighbors[n] & coords.keys()), len(neighbors[n])),
            )
            remaining.remove(node)
            anchor = next((n for n in coords if n in neighbors[node]), None)
            for _ in range(32):
                if not coords:
                    point = (0.0, 0.0)
                elif anchor is None:
                    point = (rng.uniform(-width, width), rng.uniform(-width, width))
                else:
                    angle = rng.uniform(0.0, math.tau)
                    distance = rng.uniform(min_distance, edge_max)
                    x, y = coords[anchor]
                    point = (
                        x + distance * math.cos(angle),
                        y + distance * math.sin(angle),
                    )
                if all(
                    min_distance <= math.dist(point, p) <= edge_max
                    if n in neighbors[node]
                    else math.dist(point, p) >= max(min_distance, nonedge_min)
                    for n, p in coords.items()
                ):
                    coords[node] = point
                    break
            else:
                break
        if len(coords) != len(graph.node_ids):
            continue
        if coords:
            cx = sum(x for x, _ in coords.values()) / len(coords)
            cy = sum(y for _, y in coords.values()) / len(coords)
            coords = {n: (x - cx, y - cy) for n, (x, y) in coords.items()}
        diagnostic = diagnose_layout(graph, coords, radius, margin)
        if diagnostic["valid"] and (accept is None or accept(coords)):
            diagnostic.update(
                {
                    "method": "neighbor_guided",
                    "seed": seed,
                    "attempts_used": attempt + 1,
                }
            )
            return coords, diagnostic
    raise ValueError("layout_search_exhausted")
