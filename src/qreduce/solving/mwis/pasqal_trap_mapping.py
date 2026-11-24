"""Discrete trap mapping for Pasqal QPU with pre-calibrated layouts.

This module maps MIS graph nodes to calibrated trap positions using constraint
propagation and backtracking. Unlike the continuous coordinate search in
pasqal_mapping.py (used by emulators), this searches over discrete trap
assignments that satisfy the geometric constraints of the graph.

The geometric threshold classifies pairs for mapping purposes:
- Edge pairs must be within (threshold - margin) µm to enable Rydberg blockade
- Non-edge pairs must be at least (threshold + margin) µm apart to avoid interaction
- Both bounds are inclusive

The mapper:
1. Precomputes trap pair compatibility based on distance constraints
2. Uses backtracking with constraint propagation (MRV heuristic)
3. Searches across multiple layouts with fair budget allocation
4. Returns the first valid assignment or exhaustive failure diagnostic
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from time import perf_counter
from typing import Any

from qreduce.mwis.graph import ReductionGraph


class TrapMappingOutcome(StrEnum):
    """Outcome of a trap mapping search."""

    FOUND = "found"  # Valid mapping found
    EXHAUSTED = "exhausted"  # All layouts searched, no valid mapping exists
    BUDGET_EXCEEDED = "budget_exceeded"  # State budget exhausted before completion
    TIMEOUT = "timeout"  # Deadline reached before completion
    CAPACITY_INSUFFICIENT = "capacity_insufficient"  # No layout has enough traps
    NO_LAYOUTS = "no_layouts"  # No layouts available to search
    INVALID_INPUT = "invalid_input"  # Invalid graph or layout data


@dataclass(frozen=True, slots=True)
class TrapLayout:
    """A calibrated trap layout with positions.

    Attributes:
        layout_id: Unique identifier for the layout
        trap_positions: Dict mapping trap_id -> (x, y) coordinates in µm
    """

    layout_id: str
    trap_positions: dict[int, tuple[float, float]]

    @property
    def num_traps(self) -> int:
        """Return the number of traps in this layout."""
        return len(self.trap_positions)

    @property
    def trap_ids(self) -> tuple[int, ...]:
        """Return sorted tuple of trap IDs."""
        return tuple(sorted(self.trap_positions.keys()))


@dataclass(slots=True)
class LayoutSearchState:
    """State of search within a single layout."""

    layout_id: str
    states_visited: int = 0
    max_depth_reached: int = 0
    outcome: TrapMappingOutcome | None = None
    assignment: dict[str, int] | None = None  # node -> trap_id


@dataclass(frozen=True, slots=True)
class TrapMappingResult:
    """Result of trap mapping search across layouts.

    Attributes:
        outcome: Overall search outcome
        layout_id: ID of layout where mapping was found (if any)
        assignment: Dict mapping node_id -> trap_id (if found)
        coordinates: Dict mapping node_id -> (x, y) coordinates (if found)
        layout_attempts: Search state for each attempted layout
        total_states_visited: Total states explored across all layouts
        elapsed_seconds: Time spent in search
        diagnostic: Additional diagnostic information
    """

    outcome: TrapMappingOutcome
    layout_id: str | None = None
    assignment: dict[str, int] | None = None
    coordinates: dict[str, tuple[float, float]] | None = None
    layout_attempts: tuple[LayoutSearchState, ...] = ()
    total_states_visited: int = 0
    elapsed_seconds: float = 0.0
    diagnostic: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""
        return {
            "outcome": self.outcome.value,
            "layout_id": self.layout_id,
            "assignment": self.assignment,
            "coordinates": (
                {k: list(v) for k, v in self.coordinates.items()}
                if self.coordinates
                else None
            ),
            "layout_attempts": [
                {
                    "layout_id": la.layout_id,
                    "states_visited": la.states_visited,
                    "max_depth_reached": la.max_depth_reached,
                    "outcome": la.outcome.value if la.outcome else None,
                }
                for la in self.layout_attempts
            ],
            "total_states_visited": self.total_states_visited,
            "elapsed_seconds": self.elapsed_seconds,
            "diagnostic": self.diagnostic,
        }


def _compute_trap_distances(
    trap_positions: dict[int, tuple[float, float]],
) -> dict[tuple[int, int], float]:
    """Compute pairwise distances between all traps.

    Returns dict mapping (trap_a, trap_b) -> distance where trap_a < trap_b.
    """
    distances = {}
    trap_ids = sorted(trap_positions.keys())
    for i, t1 in enumerate(trap_ids):
        p1 = trap_positions[t1]
        for t2 in trap_ids[i + 1 :]:
            p2 = trap_positions[t2]
            d = math.sqrt((p1[0] - p2[0]) ** 2 + (p1[1] - p2[1]) ** 2)
            distances[(t1, t2)] = d
    return distances


def _get_distance(
    distances: dict[tuple[int, int], float], trap_a: int, trap_b: int
) -> float:
    """Get distance between two traps from precomputed distances."""
    if trap_a == trap_b:
        return 0.0
    key = (min(trap_a, trap_b), max(trap_a, trap_b))
    return distances[key]


def _compute_compatibility_matrix(
    trap_positions: dict[int, tuple[float, float]],
    edge_max: float,  # radius - margin: max distance for edges
    nonedge_min: float,  # radius + margin: min distance for non-edges
    min_atom_distance: float,
) -> tuple[set[tuple[int, int]], set[tuple[int, int]]]:
    """Compute which trap pairs are compatible for edges and non-edges.

    Returns:
        (edge_compatible, nonedge_compatible): Sets of trap pairs (t1, t2) where t1 < t2
        that satisfy the respective distance constraints.
    """
    distances = _compute_trap_distances(trap_positions)
    edge_compatible: set[tuple[int, int]] = set()
    nonedge_compatible: set[tuple[int, int]] = set()

    for pair, d in distances.items():
        # Must satisfy min atom distance for both
        if d < min_atom_distance:
            continue
        # Edge: must be within edge_max (inclusive)
        if d <= edge_max:
            edge_compatible.add(pair)
        # Non-edge: must be at least nonedge_min (inclusive)
        if d >= nonedge_min:
            nonedge_compatible.add(pair)

    return edge_compatible, nonedge_compatible


def _is_pair_compatible(pair: tuple[int, int], trap_a: int, trap_b: int) -> bool:
    """Check if two trap assignments are in a compatibility set."""
    if trap_a == trap_b:
        return False  # Same trap cannot be assigned to two nodes
    key = (min(trap_a, trap_b), max(trap_a, trap_b))
    return key in {pair}


class _BacktrackingSearch:
    """Backtracking search with constraint propagation for trap assignment.

    Uses MRV (Minimum Remaining Values) heuristic: assign the node with
    fewest remaining valid traps first.
    """

    def __init__(
        self,
        graph: ReductionGraph,
        trap_positions: dict[int, tuple[float, float]],
        edge_compatible: set[tuple[int, int]],
        nonedge_compatible: set[tuple[int, int]],
        state_budget: int,
        deadline: float | None,
        accept: Callable[[dict[str, int]], bool] | None,
    ) -> None:
        self.graph = graph
        self.trap_positions = trap_positions
        self.edge_compatible = edge_compatible
        self.nonedge_compatible = nonedge_compatible
        self.state_budget = state_budget
        self.deadline = deadline
        self.accept = accept

        self.nodes = list(graph.node_ids)
        self.num_nodes = len(self.nodes)
        self.node_to_index = {n: i for i, n in enumerate(self.nodes)}

        # Build adjacency for fast lookup
        self.edges: set[tuple[int, int]] = set()
        for a, b in graph.edges:
            ia, ib = self.node_to_index[a], self.node_to_index[b]
            self.edges.add((min(ia, ib), max(ia, ib)))

        self.trap_ids = sorted(trap_positions.keys())
        self.num_traps = len(self.trap_ids)

        # Search state
        self.states_visited = 0
        self.max_depth_reached = 0
        self.assignment: list[int | None] = [None] * self.num_nodes
        self.domains: list[set[int]] = [set(self.trap_ids) for _ in range(self.num_nodes)]

    def _is_edge(self, node_i: int, node_j: int) -> bool:
        """Check if two node indices form an edge."""
        return (min(node_i, node_j), max(node_i, node_j)) in self.edges

    def _is_compatible(self, node_i: int, trap_i: int, node_j: int, trap_j: int) -> bool:
        """Check if assigning trap_i to node_i is compatible with trap_j on node_j."""
        if trap_i == trap_j:
            return False
        key = (min(trap_i, trap_j), max(trap_i, trap_j))
        if self._is_edge(node_i, node_j):
            return key in self.edge_compatible
        else:
            return key in self.nonedge_compatible

    def _select_unassigned(self) -> int | None:
        """Select next unassigned node using MRV heuristic.

        Returns node index with smallest domain, breaking ties by node order.
        """
        best_idx = None
        best_size = float("inf")
        for i in range(self.num_nodes):
            if self.assignment[i] is None:
                domain_size = len(self.domains[i])
                if domain_size < best_size or (
                    domain_size == best_size and (best_idx is None or i < best_idx)
                ):
                    best_size = domain_size
                    best_idx = i
        return best_idx

    def _propagate(self, node_i: int, trap_i: int) -> list[tuple[int, set[int]]] | None:
        """Propagate constraint: node_i is assigned trap_i.

        Returns list of (node_j, removed_traps) for rollback, or None if domain wipeout.
        """
        changes: list[tuple[int, set[int]]] = []

        for j in range(self.num_nodes):
            if j == node_i or self.assignment[j] is not None:
                continue

            removed: set[int] = set()
            for trap_j in list(self.domains[j]):
                if not self._is_compatible(node_i, trap_i, j, trap_j):
                    removed.add(trap_j)
                    self.domains[j].remove(trap_j)

            if removed:
                changes.append((j, removed))
                if not self.domains[j]:
                    # Domain wipeout - restore and return failure
                    for jj, removed_traps in changes:
                        self.domains[jj].update(removed_traps)
                    return None

        return changes

    def _restore(self, changes: list[tuple[int, set[int]]]) -> None:
        """Restore domains after backtracking."""
        for j, removed_traps in changes:
            self.domains[j].update(removed_traps)

    def search(self) -> TrapMappingOutcome:
        """Run backtracking search.

        Returns outcome. If FOUND, self.assignment contains the solution.
        """
        # Check budget and deadline BEFORE incrementing counter
        # This ensures states_visited never exceeds state_budget
        if self.states_visited >= self.state_budget:
            return TrapMappingOutcome.BUDGET_EXCEEDED
        if self.deadline is not None and perf_counter() > self.deadline:
            return TrapMappingOutcome.TIMEOUT

        self.states_visited += 1

        # Select next unassigned node
        node_i = self._select_unassigned()
        if node_i is None:
            assignment = self.get_assignment()
            assert assignment is not None
            if self.accept is not None and not self.accept(assignment):
                return TrapMappingOutcome.EXHAUSTED
            return TrapMappingOutcome.FOUND

        depth = sum(1 for a in self.assignment if a is not None) + 1
        self.max_depth_reached = max(self.max_depth_reached, depth)

        # Try each trap in domain (sorted for determinism)
        for trap_i in sorted(self.domains[node_i]):
            # Check budget/deadline before each attempt
            if self.states_visited >= self.state_budget:
                return TrapMappingOutcome.BUDGET_EXCEEDED
            if self.deadline is not None and perf_counter() > self.deadline:
                return TrapMappingOutcome.TIMEOUT

            # Assign and propagate
            self.assignment[node_i] = trap_i
            old_domain = self.domains[node_i].copy()
            self.domains[node_i] = {trap_i}

            changes = self._propagate(node_i, trap_i)
            if changes is not None:
                # Propagation succeeded, recurse
                result = self.search()
                if result == TrapMappingOutcome.FOUND:
                    return result
                if result in (
                    TrapMappingOutcome.BUDGET_EXCEEDED,
                    TrapMappingOutcome.TIMEOUT,
                ):
                    return result
                # Backtrack
                self._restore(changes)

            # Restore domain and assignment
            self.domains[node_i] = old_domain
            self.assignment[node_i] = None

        # All traps tried, no solution from this state
        return TrapMappingOutcome.EXHAUSTED

    def get_assignment(self) -> dict[str, int] | None:
        """Get the assignment as node_id -> trap_id dict."""
        if any(a is None for a in self.assignment):
            return None
        return {self.nodes[i]: self.assignment[i] for i in range(self.num_nodes)}  # type: ignore[misc]


def search_trap_mapping(
    graph: ReductionGraph,
    layouts: Sequence[TrapLayout],
    *,
    radius: float = 10.0,
    margin: float = 1.0,
    min_atom_distance: float = 4.0,
    state_budget_per_layout: int = 100_000,
    total_state_budget: int | None = None,
    deadline: float | None = None,
    required_layout_id: str | None = None,
    accept: Callable[[str, dict[str, int]], bool] | None = None,
) -> TrapMappingResult:
    """Search for valid trap assignment across calibrated layouts.

    Args:
        graph: MIS graph with node_ids and edges
        layouts: Sequence of TrapLayout objects to search
        radius: Blockade radius threshold in µm (default: 10.0)
        margin: Margin for strict geometric validation (default: 1.0)
        min_atom_distance: Minimum allowed distance between atoms in µm
        state_budget_per_layout: Max states to explore per layout
        total_state_budget: Optional total budget across all layouts
        deadline: Optional deadline (perf_counter timestamp)
        required_layout_id: If set, only search this layout (no fallback)
        accept: Optional validation of a complete candidate before accepting it

    Returns:
        TrapMappingResult with outcome and mapping if found
    """
    start = perf_counter()

    # Validate inputs
    if not graph.node_ids:
        return TrapMappingResult(
            outcome=TrapMappingOutcome.INVALID_INPUT,
            elapsed_seconds=perf_counter() - start,
            diagnostic={"error": "empty_graph"},
        )

    if not (math.isfinite(radius) and math.isfinite(margin) and 0 < margin < radius):
        return TrapMappingResult(
            outcome=TrapMappingOutcome.INVALID_INPUT,
            elapsed_seconds=perf_counter() - start,
            diagnostic={"error": "invalid_radius_or_margin"},
        )

    edge_max = radius - margin  # Max distance for edges (inclusive)
    nonedge_min = radius + margin  # Min distance for non-edges (inclusive)
    num_nodes = len(graph.node_ids)

    # Filter layouts
    if required_layout_id is not None:
        layouts = [l for l in layouts if l.layout_id == required_layout_id]
        if not layouts:
            return TrapMappingResult(
                outcome=TrapMappingOutcome.NO_LAYOUTS,
                elapsed_seconds=perf_counter() - start,
                diagnostic={"error": "required_layout_not_found", "layout_id": required_layout_id},
            )
    elif not layouts:
        return TrapMappingResult(
            outcome=TrapMappingOutcome.NO_LAYOUTS,
            elapsed_seconds=perf_counter() - start,
            diagnostic={"error": "no_layouts_provided"},
        )

    # Filter by capacity
    eligible_layouts = [l for l in layouts if l.num_traps >= num_nodes]
    if not eligible_layouts:
        return TrapMappingResult(
            outcome=TrapMappingOutcome.CAPACITY_INSUFFICIENT,
            elapsed_seconds=perf_counter() - start,
            diagnostic={
                "error": "no_layout_has_enough_traps",
                "required_traps": num_nodes,
                "max_available": max(l.num_traps for l in layouts) if layouts else 0,
            },
        )

    # Sort layouts deterministically (by ID)
    eligible_layouts = sorted(eligible_layouts, key=lambda l: l.layout_id)

    # Calculate per-layout budget
    if total_state_budget is not None:
        budget_per = max(1, total_state_budget // len(eligible_layouts))
    else:
        budget_per = state_budget_per_layout

    layout_attempts: list[LayoutSearchState] = []
    total_states = 0
    remaining_budget = total_state_budget

    for layout in eligible_layouts:
        # Check deadline
        if deadline is not None and perf_counter() > deadline:
            layout_state = LayoutSearchState(
                layout_id=layout.layout_id,
                outcome=TrapMappingOutcome.TIMEOUT,
            )
            layout_attempts.append(layout_state)
            break

        # Compute compatibility for this layout
        edge_compatible, nonedge_compatible = _compute_compatibility_matrix(
            layout.trap_positions, edge_max, nonedge_min, min_atom_distance
        )

        # Calculate budget for this layout
        if remaining_budget is not None:
            layout_budget = min(budget_per, remaining_budget)
        else:
            layout_budget = budget_per

        # Create and run search
        search = _BacktrackingSearch(
            graph=graph,
            trap_positions=layout.trap_positions,
            edge_compatible=edge_compatible,
            nonedge_compatible=nonedge_compatible,
            state_budget=layout_budget,
            deadline=deadline,
            accept=None if accept is None else lambda assignment, lid=layout.layout_id: accept(lid, assignment),
        )

        outcome = search.search()
        total_states += search.states_visited

        if remaining_budget is not None:
            remaining_budget = max(0, remaining_budget - search.states_visited)

        layout_state = LayoutSearchState(
            layout_id=layout.layout_id,
            states_visited=search.states_visited,
            max_depth_reached=search.max_depth_reached,
            outcome=outcome,
            assignment=search.get_assignment() if outcome == TrapMappingOutcome.FOUND else None,
        )
        layout_attempts.append(layout_state)

        if outcome == TrapMappingOutcome.FOUND:
            # Build coordinates from assignment
            assignment = search.get_assignment()
            assert assignment is not None
            coordinates = {
                node: layout.trap_positions[trap_id]
                for node, trap_id in assignment.items()
            }
            return TrapMappingResult(
                outcome=TrapMappingOutcome.FOUND,
                layout_id=layout.layout_id,
                assignment=assignment,
                coordinates=coordinates,
                layout_attempts=tuple(layout_attempts),
                total_states_visited=total_states,
                elapsed_seconds=perf_counter() - start,
                diagnostic={
                    "edge_max": edge_max,
                    "nonedge_min": nonedge_min,
                    "min_atom_distance": min_atom_distance,
                },
            )

        if outcome == TrapMappingOutcome.TIMEOUT:
            break

        if remaining_budget is not None and remaining_budget <= 0:
            break

    # Determine final outcome
    # EXHAUSTED only if ALL eligible layouts were fully searched and none had a solution
    # If some layouts were not searched (due to budget/timeout), it's BUDGET_EXCEEDED or TIMEOUT
    layouts_searched = len(layout_attempts)
    layouts_eligible = len(eligible_layouts)

    all_attempted_exhausted = all(
        la.outcome == TrapMappingOutcome.EXHAUSTED for la in layout_attempts
    )
    any_timeout = any(la.outcome == TrapMappingOutcome.TIMEOUT for la in layout_attempts)
    any_budget = any(
        la.outcome == TrapMappingOutcome.BUDGET_EXCEEDED for la in layout_attempts
    )

    # Only EXHAUSTED if we searched ALL eligible layouts AND all were exhausted
    if all_attempted_exhausted and layouts_searched == layouts_eligible:
        final_outcome = TrapMappingOutcome.EXHAUSTED
    elif any_timeout:
        final_outcome = TrapMappingOutcome.TIMEOUT
    elif any_budget or layouts_searched < layouts_eligible:
        # Budget exceeded OR we didn't search all layouts
        final_outcome = TrapMappingOutcome.BUDGET_EXCEEDED
    else:
        final_outcome = TrapMappingOutcome.BUDGET_EXCEEDED

    return TrapMappingResult(
        outcome=final_outcome,
        layout_attempts=tuple(layout_attempts),
        total_states_visited=total_states,
        elapsed_seconds=perf_counter() - start,
        diagnostic={
            "edge_max": edge_max,
            "nonedge_min": nonedge_min,
            "min_atom_distance": min_atom_distance,
            "layouts_searched": len(layout_attempts),
            "layouts_available": len(eligible_layouts),
        },
    )


def validate_trap_assignment(
    graph: ReductionGraph,
    layout: TrapLayout,
    assignment: Mapping[str, int],
    *,
    radius: float = 10.0,
    margin: float = 1.0,
    min_atom_distance: float = 4.0,
) -> dict[str, Any]:
    """Validate a trap assignment against graph constraints.

    Returns diagnostic dict with 'valid' key and details of any violations.
    """
    if set(assignment.keys()) != set(graph.node_ids):
        return {"valid": False, "error": "assignment_node_mismatch"}

    trap_ids = set(assignment.values())
    if len(trap_ids) != len(assignment):
        return {"valid": False, "error": "duplicate_trap_assignment"}

    missing_traps = trap_ids - set(layout.trap_positions.keys())
    if missing_traps:
        return {"valid": False, "error": "trap_not_in_layout", "missing": list(missing_traps)}

    # Build coordinates
    coordinates = {
        node: layout.trap_positions[trap_id]
        for node, trap_id in assignment.items()
    }

    # Use diagnose_layout for geometric validation
    from qreduce.solving.mwis.pasqal_mapping import diagnose_layout

    diagnostic = diagnose_layout(graph, coordinates, radius, margin)

    # Also check min_atom_distance
    distances = _compute_trap_distances(
        {assignment[n]: coordinates[n] for n in graph.node_ids}
    )
    too_close = [
        (t1, t2, d)
        for (t1, t2), d in distances.items()
        if d < min_atom_distance
    ]

    if too_close:
        diagnostic["valid"] = False
        diagnostic["min_distance_violations"] = too_close

    return diagnostic
