"""Diagnostics for geometry-dynamics fidelity in neutral-atom MIS.

This module provides tools to analyze whether the physical Hamiltonian
implemented by a neutral-atom device accurately represents the MWIS problem.

Key questions this module helps answer:
1. Do connected pairs (edges) have strong repulsive interactions?
2. Do non-connected pairs have negligible interactions?
3. Is the final Hamiltonian ground state the MWIS optimum?
4. What is the dominant error source (mapping, evolution, or sampling)?

The diagnostics are independent of the pulse strategy and focus on
the static geometry-to-Hamiltonian mapping.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType

from qreduce.artifacts.metadata import redact_metadata, to_primitive
from qreduce.mwis.graph import Edge, ReductionGraph


class InteractionClassification(StrEnum):
    """Classification of pairwise interactions."""

    STRONG_EDGE = "strong_edge"  # Edge pair with strong interaction (correct)
    WEAK_EDGE = "weak_edge"  # Edge pair with weak interaction (problem)
    STRONG_NON_EDGE = "strong_non_edge"  # Non-edge with strong interaction (problem)
    WEAK_NON_EDGE = "weak_non_edge"  # Non-edge with weak interaction (correct)


@dataclass(frozen=True, slots=True)
class PairInteraction:
    """Detailed interaction information for one pair of atoms.

    Attributes:
        node_i: First node identifier.
        node_j: Second node identifier.
        distance_um: Inter-atom distance in micrometers.
        interaction_strength: U_ij = C6/r^6 in rad/µs.
        is_graph_edge: Whether this pair is an edge in the problem graph.
        classification: How well the interaction matches the graph structure.
        ratio_to_threshold: interaction_strength / threshold.
    """

    node_i: str
    node_j: str
    distance_um: float
    interaction_strength: float
    is_graph_edge: bool
    classification: InteractionClassification
    ratio_to_threshold: float

    def to_dict(self) -> dict[str, object]:
        return redact_metadata(to_primitive(self))  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class GeometryDiagnostics:
    """Complete diagnostics of geometry-Hamiltonian correspondence.

    Attributes:
        graph_edge_count: Number of edges in the problem graph.
        pair_count: Total number of atom pairs.
        correct_edge_count: Edges with appropriate strong interaction.
        weak_edge_count: Edges with insufficient interaction.
        spurious_interaction_count: Non-edges with significant interaction.
        correct_non_edge_count: Non-edges with negligible interaction.

        min_edge_interaction: Weakest interaction among edges.
        max_non_edge_interaction: Strongest interaction among non-edges.
        edge_non_edge_gap: Ratio of min_edge to max_non_edge (larger = better).

        threshold_used: Interaction threshold for classification.
        c6_coefficient: Van der Waals coefficient used.

        is_valid: Whether all edges are correct and no spurious interactions.
        fidelity_score: Quality score from 0 to 1.
        warnings: Issues detected in the mapping.
        pair_details: Full list of pair interactions (for detailed analysis).
    """

    graph_edge_count: int
    pair_count: int
    correct_edge_count: int
    weak_edge_count: int
    spurious_interaction_count: int
    correct_non_edge_count: int

    min_edge_interaction: float | None
    max_non_edge_interaction: float | None
    edge_non_edge_gap: float | None

    threshold_used: float
    c6_coefficient: float

    is_valid: bool
    fidelity_score: float
    warnings: tuple[str, ...]
    pair_details: tuple[PairInteraction, ...] = ()

    provenance: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "warnings", tuple(self.warnings))
        object.__setattr__(self, "pair_details", tuple(self.pair_details))
        object.__setattr__(
            self, "provenance", MappingProxyType(dict(self.provenance))
        )

    def to_dict(self) -> dict[str, object]:
        return redact_metadata(to_primitive(self))  # type: ignore[return-value]


def diagnose_geometry_fidelity(
    graph: ReductionGraph,
    coordinates: dict[str, tuple[float, float]],
    *,
    interaction_threshold: float = 1.0,  # rad/µs threshold for "significant"
    c6_coefficient: float = 862690.0,  # Default C6 for Rb in rad·µs·µm^6
    include_pair_details: bool = False,
) -> GeometryDiagnostics:
    """Analyze how well physical geometry represents the problem graph.

    For MIS on neutral atoms, the mapping should satisfy:
    - Graph edges → strong repulsive interaction (U >> detuning scale)
    - Non-edges → weak/negligible interaction (U << detuning scale)

    If edges have weak interaction or non-edges have strong interaction,
    the physical evolution may find states that don't correspond to
    valid independent sets or may miss the optimal solution.

    Args:
        graph: The MWIS problem graph.
        coordinates: Atom positions {node_id: (x, y)} in micrometers.
        interaction_threshold: Threshold to classify strong vs weak interaction.
        c6_coefficient: Van der Waals C6 coefficient.
        include_pair_details: Whether to include full pair list in result.

    Returns:
        GeometryDiagnostics with analysis results.
    """
    import math

    # Validate inputs
    if set(coordinates.keys()) != set(graph.node_ids):
        missing = set(graph.node_ids) - set(coordinates.keys())
        extra = set(coordinates.keys()) - set(graph.node_ids)
        raise ValueError(
            f"Coordinate keys don't match graph nodes. "
            f"Missing: {missing}, Extra: {extra}"
        )

    # Build edge set for quick lookup
    edge_set: set[Edge] = set(graph.edges)

    # Compute all pairwise interactions
    pairs: list[PairInteraction] = []
    edge_interactions: list[float] = []
    non_edge_interactions: list[float] = []

    nodes = list(graph.node_ids)
    for i, node_i in enumerate(nodes):
        for j, node_j in enumerate(nodes):
            if j <= i:
                continue

            # Calculate distance
            x_i, y_i = coordinates[node_i]
            x_j, y_j = coordinates[node_j]
            distance = math.sqrt((x_i - x_j) ** 2 + (y_i - y_j) ** 2)

            # Calculate interaction (avoid division by zero)
            if distance < 1e-10:
                interaction = float("inf")
            else:
                interaction = c6_coefficient / (distance**6)

            # Determine if this is a graph edge
            canonical_edge = (node_i, node_j) if node_i < node_j else (node_j, node_i)
            is_edge = canonical_edge in edge_set

            # Classify the interaction
            is_strong = interaction >= interaction_threshold
            if is_edge:
                if is_strong:
                    classification = InteractionClassification.STRONG_EDGE
                else:
                    classification = InteractionClassification.WEAK_EDGE
                edge_interactions.append(interaction)
            else:
                if is_strong:
                    classification = InteractionClassification.STRONG_NON_EDGE
                else:
                    classification = InteractionClassification.WEAK_NON_EDGE
                non_edge_interactions.append(interaction)

            ratio = interaction / interaction_threshold if interaction_threshold > 0 else float("inf")

            pairs.append(
                PairInteraction(
                    node_i=node_i,
                    node_j=node_j,
                    distance_um=distance,
                    interaction_strength=interaction,
                    is_graph_edge=is_edge,
                    classification=classification,
                    ratio_to_threshold=ratio,
                )
            )

    # Aggregate statistics
    correct_edge_count = sum(
        1 for p in pairs if p.classification == InteractionClassification.STRONG_EDGE
    )
    weak_edge_count = sum(
        1 for p in pairs if p.classification == InteractionClassification.WEAK_EDGE
    )
    spurious_count = sum(
        1 for p in pairs if p.classification == InteractionClassification.STRONG_NON_EDGE
    )
    correct_non_edge_count = sum(
        1 for p in pairs if p.classification == InteractionClassification.WEAK_NON_EDGE
    )

    min_edge = min(edge_interactions) if edge_interactions else None
    max_non_edge = max(non_edge_interactions) if non_edge_interactions else None

    # Compute edge/non-edge gap
    gap = None
    if min_edge is not None and max_non_edge is not None and max_non_edge > 0:
        gap = min_edge / max_non_edge

    # Build warnings
    warnings = []
    if weak_edge_count > 0:
        warnings.append(
            f"{weak_edge_count} graph edges have weak interaction; "
            "independence constraint may not be enforced"
        )
    if spurious_count > 0:
        warnings.append(
            f"{spurious_count} non-edge pairs have strong interaction; "
            "may incorrectly block simultaneous selection"
        )
    if gap is not None and gap < 10:
        warnings.append(
            f"Small edge/non-edge gap ({gap:.1f}x); "
            "distinguishing edges from non-edges may be unreliable"
        )

    # Compute fidelity score (0 to 1)
    # Perfect: all edges correct, no spurious
    total_edges = correct_edge_count + weak_edge_count
    total_non_edges = spurious_count + correct_non_edge_count

    edge_fidelity = correct_edge_count / total_edges if total_edges > 0 else 1.0
    non_edge_fidelity = correct_non_edge_count / total_non_edges if total_non_edges > 0 else 1.0
    fidelity = (edge_fidelity + non_edge_fidelity) / 2

    is_valid = weak_edge_count == 0 and spurious_count == 0

    return GeometryDiagnostics(
        graph_edge_count=len(graph.edges),
        pair_count=len(pairs),
        correct_edge_count=correct_edge_count,
        weak_edge_count=weak_edge_count,
        spurious_interaction_count=spurious_count,
        correct_non_edge_count=correct_non_edge_count,
        min_edge_interaction=min_edge,
        max_non_edge_interaction=max_non_edge,
        edge_non_edge_gap=gap,
        threshold_used=interaction_threshold,
        c6_coefficient=c6_coefficient,
        is_valid=is_valid,
        fidelity_score=fidelity,
        warnings=tuple(warnings),
        pair_details=tuple(pairs) if include_pair_details else (),
        provenance={
            "node_count": len(graph.node_ids),
            "threshold_method": "fixed",
        },
    )


@dataclass(frozen=True, slots=True)
class EnergyComparison:
    """Comparison of physical Hamiltonian minimum vs canonical MWIS optimum.

    This helps diagnose whether the physical evolution can find the
    correct solution even with perfect adiabatic evolution.
    """

    # Physical Hamiltonian analysis
    physical_ground_state: tuple[int, ...]
    physical_ground_energy: float
    physical_is_independent: bool

    # Canonical MWIS optimum
    canonical_optimum: tuple[int, ...]
    canonical_optimum_weight: float
    canonical_optimum_energy: float

    # Comparison
    ground_state_matches_optimum: bool
    energy_gap_to_optimum: float
    num_degenerate_ground_states: int
    all_ground_states_independent: bool = False
    any_ground_state_optimal: bool = False
    all_ground_states_optimal: bool = False

    provenance: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "provenance", MappingProxyType(dict(self.provenance))
        )

    def to_dict(self) -> dict[str, object]:
        return redact_metadata(to_primitive(self))  # type: ignore[return-value]


def compare_physical_vs_canonical(
    graph: ReductionGraph,
    coordinates: dict[str, tuple[float, float]],
    final_detuning: float,
    *,
    c6_coefficient: float = 862690.0,
    max_enumeration_size: int = 20,
) -> EnergyComparison | None:
    """Compare physical Hamiltonian ground state with canonical MWIS optimum.

    For small graphs, this enumerates all states to find:
    1. The physical Hamiltonian ground state at the final detuning
    2. The canonical MWIS optimum

    If they differ, there's a fundamental mapping problem: even perfect
    adiabatic evolution would find the wrong answer.

    Args:
        graph: The MWIS problem graph.
        coordinates: Atom positions in micrometers.
        final_detuning: The detuning at the end of evolution (rad/µs).
        c6_coefficient: Van der Waals coefficient.
        max_enumeration_size: Maximum nodes for exhaustive enumeration.

    Returns:
        EnergyComparison if graph is small enough to enumerate, else None.
    """
    import math
    from itertools import product

    if len(graph.node_ids) > max_enumeration_size:
        return None

    n = len(graph.node_ids)
    nodes = list(graph.node_ids)

    # Precompute interactions
    interactions = {}
    for i, node_i in enumerate(nodes):
        for j, node_j in enumerate(nodes):
            if j <= i:
                continue
            x_i, y_i = coordinates[node_i]
            x_j, y_j = coordinates[node_j]
            d = math.sqrt((x_i - x_j) ** 2 + (y_i - y_j) ** 2)
            u = c6_coefficient / (d**6) if d > 0 else float("inf")
            interactions[(i, j)] = u

    # Build edge set
    edge_indices = set()
    for left, right in graph.edges:
        i = nodes.index(left)
        j = nodes.index(right)
        edge_indices.add((min(i, j), max(i, j)))

    def physical_energy(state: tuple[int, ...]) -> float:
        """Compute H = -Δ Σ n_i + Σ U_ij n_i n_j for Rydberg state."""
        single = -final_detuning * sum(state)
        pair = sum(
            interactions[(i, j)] * state[i] * state[j]
            for i in range(n)
            for j in range(i + 1, n)
        )
        return single + pair

    def is_independent(state: tuple[int, ...]) -> bool:
        """Check if state is an independent set."""
        for i, j in edge_indices:
            if state[i] == 1 and state[j] == 1:
                return False
        return True

    def canonical_weight(state: tuple[int, ...]) -> float:
        """MWIS weight of the state."""
        return sum(
            graph.node_weights[nodes[i]] * state[i] for i in range(n)
        )

    # Enumerate all states
    all_states = list(product((0, 1), repeat=n))

    # Find physical ground state
    state_energies = [(state, physical_energy(state)) for state in all_states]
    state_energies.sort(key=lambda x: x[1])
    ground_state, ground_energy = state_energies[0]
    num_degenerate = sum(1 for _, e in state_energies if abs(e - ground_energy) < 1e-10)

    # Find canonical MWIS optimum
    independent_states = [(s, canonical_weight(s)) for s in all_states if is_independent(s)]
    independent_states.sort(key=lambda x: -x[1])  # Descending weight
    optimum_state, optimum_weight = independent_states[0]

    optimum_energy = min(physical_energy(state) for state, weight in independent_states
                         if math.isclose(weight, optimum_weight, rel_tol=0, abs_tol=1e-10))
    energy_gap = optimum_energy - ground_energy
    ground_states = [state for state, energy in state_energies
                     if math.isclose(energy, ground_energy, rel_tol=0, abs_tol=1e-10)]
    optimal_ground_states = [state for state in ground_states if is_independent(state)
                             and math.isclose(canonical_weight(state), optimum_weight,
                                              rel_tol=0, abs_tol=1e-10)]

    return EnergyComparison(
        physical_ground_state=ground_state,
        physical_ground_energy=ground_energy,
        physical_is_independent=is_independent(ground_state),
        canonical_optimum=optimum_state,
        canonical_optimum_weight=optimum_weight,
        canonical_optimum_energy=optimum_energy,
        ground_state_matches_optimum=bool(optimal_ground_states),
        energy_gap_to_optimum=energy_gap,
        num_degenerate_ground_states=num_degenerate,
        all_ground_states_independent=all(is_independent(state) for state in ground_states),
        any_ground_state_optimal=bool(optimal_ground_states),
        all_ground_states_optimal=len(optimal_ground_states) == len(ground_states),
        provenance={
            "node_count": n,
            "final_detuning": final_detuning,
            "c6_coefficient": c6_coefficient,
        },
    )
