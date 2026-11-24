"""Bounded custom QPU layout generation, independent of the experiment."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from hashlib import sha256
from math import hypot
from time import perf_counter
from typing import TYPE_CHECKING

from qreduce.artifacts.metadata import canonical_json
from qreduce.mwis.graph import ReductionGraph
from qreduce.solving.mwis.pasqal_mapping import diagnose_layout, search_layout

if TYPE_CHECKING:
    from pulser import Register
    from pulser.devices import Device


@dataclass(frozen=True, slots=True)
class CustomLayoutResult:
    register: Register | None
    details: dict[str, object]


def generate_custom_layout(
    graph: ReductionGraph, device: Device, *, radius: float, margin: float,
    deadline: float | None, attempts: int = 256, seed: int = 0,
) -> CustomLayoutResult:
    """Generate from new graph coordinates; let Pulser place the empty traps."""
    from pulser import Register

    qubits = tuple(f"q{i}" for i in range(len(graph.node_ids)))
    rejections: Counter[str] = Counter()
    attempted = 0
    accepted = None
    upper_radius = device.max_radial_distance

    def check_deadline() -> None:
        if deadline is not None and perf_counter() >= deadline:
            raise TimeoutError

    def before_attempt() -> None:
        nonlocal attempted
        check_deadline()
        attempted += 1

    def accept(coordinates: dict[str, tuple[float, float]]) -> bool:
        nonlocal accepted
        check_deadline()
        if upper_radius is not None and any(hypot(*p) > upper_radius for p in coordinates.values()):
            rejections["register_radius"] += 1
            return False
        bare = Register(dict(zip(qubits, (coordinates[n] for n in graph.node_ids), strict=True)))
        try:
            candidate = bare.with_automatic_layout(device, layout_slug="qreduce-custom")
        except (RuntimeError, ValueError) as error:
            rejections[f"layout_generation:{type(error).__name__}"] += 1
            return False
        check_deadline()
        try:
            device.validate_layout(candidate.layout)
            device.validate_layout_filling(candidate)
            device.validate_register(candidate)
        except ValueError as error:
            rejections[f"device_validation:{type(error).__name__}"] += 1
            return False
        final = {n: tuple(map(float, candidate.qubits[q]))
                 for n, q in zip(graph.node_ids, qubits, strict=True)}
        if not diagnose_layout(graph, final, radius, margin)["valid"]:
            rejections["final_geometry"] += 1
            return False
        accepted = candidate
        return True

    outcome = "found"
    try:
        check_deadline()
        if graph.edges and device.min_atom_distance > radius - margin:
            outcome = "incompatible_spacing"
        else:
            try:
                search_layout(graph, radius, margin, attempts=attempts, seed=seed,
                              min_distance=device.min_atom_distance, accept=accept,
                              before_attempt=before_attempt)
            except ValueError as error:
                if str(error) != "layout_search_exhausted":
                    raise
                outcome = "budget_exceeded"
        check_deadline()
    except TimeoutError:
        outcome, accepted = "timeout", None

    details: dict[str, object] = {
        "layout_mode": "custom", "outcome": outcome, "attempt_budget": attempts,
        "attempts_used": attempted, "seed": seed, "rejected_candidates": dict(rejections),
    }
    if accepted is not None:
        layout = accepted.layout
        assert layout is not None
        layout_hash = sha256(canonical_json(layout.coords.tolist()).encode()).hexdigest()
        assignment = dict(zip(graph.node_ids, layout.get_traps_from_coordinates(
            *(accepted.qubits[q] for q in qubits),
        ), strict=True))
        details.update(layout_id=f"custom:{layout_hash}", layout_sha256=layout_hash,
                       trap_count=layout.number_of_traps, assignment=assignment)
    return CustomLayoutResult(accepted, details)