"""Tests for Pasqal trap mapping with pre-calibrated layouts.

These tests verify the discrete backtracking search over calibrated trap positions.
"""

import math
from itertools import combinations, permutations

import pytest

from qreduce.mwis import ReductionGraph
from qreduce.solving.mwis.pasqal_mapping import diagnose_layout
from qreduce.solving.mwis.pasqal_trap_mapping import (
    TrapLayout,
    TrapMappingOutcome,
    search_trap_mapping,
    validate_trap_assignment,
)


def make_graph(node_ids: tuple[str, ...], edges: tuple[tuple[str, str], ...]) -> ReductionGraph:
    """Create a simple test graph."""
    weights = {n: 1.0 for n in node_ids}
    edge_data = {e: "conflict" for e in edges}
    return ReductionGraph(node_ids, weights, edges, edge_data, "test", "1")


def make_layout(layout_id: str, positions: dict[int, tuple[float, float]]) -> TrapLayout:
    """Create a test layout."""
    return TrapLayout(layout_id=layout_id, trap_positions=positions)


def _pair_is_valid(edge, left, right):
    distance = math.dist(left, right)
    return distance >= 4 and (distance <= 9 if edge else distance >= 11)


def _assignment_is_valid(edges, nodes, traps, positions):
    return len(set(traps)) == len(nodes) and all(
        _pair_is_valid((nodes[i], nodes[j]) in edges, positions[traps[i]], positions[traps[j]])
        for i, j in combinations(range(len(nodes)), 2)
    )


@pytest.mark.parametrize("node_count", [2, 3, 4])
@pytest.mark.parametrize("positions", [
    {0: (0, 0), 1: (4, 0), 2: (9, 0), 3: (20, 0), 4: (23, 0)},
    {8: (0, 0), 4: (8, 0), 3: (0, 8), 6: (8, 8), 2: (18, 8)},
])
def test_search_matches_independent_exhaustive_oracle(node_count, positions):
    nodes = tuple("abcd"[:node_count])
    pairs = tuple(combinations(nodes, 2))
    layout = make_layout("oracle", positions)
    for mask in range(1 << len(pairs)):
        edges = tuple(pair for i, pair in enumerate(pairs) if mask & (1 << i))
        feasible = any(
            _assignment_is_valid(edges, nodes, traps, positions)
            for traps in permutations(positions, node_count)
        )
        result = search_trap_mapping(make_graph(nodes, edges), [layout])
        assert result.outcome == (TrapMappingOutcome.FOUND if feasible else TrapMappingOutcome.EXHAUSTED), edges
        if feasible:
            assert tuple(result.assignment) == nodes
            assert _assignment_is_valid(edges, nodes, tuple(result.assignment.values()), positions), edges


def test_backtracking_recovers_from_a_first_fit_greedy_dead_end():
    nodes = ("a", "b", "c")
    edges = (("a", "b"), ("a", "c"))
    positions = {0: (40, 0), 1: (0, 0), 2: (8, 0), 3: (16, 0)}
    greedy = {}
    for node in nodes:
        trap = next((
            trap for trap in sorted(positions) if trap not in greedy.values() and all(
                _pair_is_valid((previous, node) in edges, positions[assigned], positions[trap])
                for previous, assigned in greedy.items()
            )
        ), None)
        if trap is None:
            break
        greedy[node] = trap
    assert greedy == {"a": 0}

    result = search_trap_mapping(make_graph(nodes, edges), [make_layout("greedy-trap", positions)])
    assert result.outcome == TrapMappingOutcome.FOUND
    assert result.assignment["a"] == 2
    assert _assignment_is_valid(edges, nodes, tuple(result.assignment.values()), positions)


@pytest.mark.parametrize(("node_count", "width"), [(6, 3), (9, 3), (12, 4), (16, 4)])
@pytest.mark.parametrize("spacing", [4, 8, 12])
def test_default_budget_on_geometric_fixture(node_count, width, spacing):
    nodes = tuple(f"n{i:02}" for i in range(node_count))
    witness = [(i % width * spacing, i // width * spacing) for i in range(node_count)]
    edges = tuple((nodes[i], nodes[j]) for i, j in combinations(range(node_count), 2)
                  if math.dist(witness[i], witness[j]) <= 9)
    positions = {i: (i % 6 * spacing, i // 6 * spacing) for i in range(36)}
    result = search_trap_mapping(make_graph(nodes, edges), [make_layout("grid", positions)])
    print(f"nodes={node_count} edges={len(edges)} spacing={spacing} outcome={result.outcome.value} "
          f"states={result.total_states_visited} ms={result.elapsed_seconds * 1000:.2f}")
    assert result.outcome == TrapMappingOutcome.FOUND
    assert _assignment_is_valid(edges, nodes, tuple(result.assignment.values()), positions)


def test_default_budget_stops_when_candidate_validator_keeps_rejecting():
    nodes = tuple("abcdef")
    positions = {i: (i % 6 * 12, i // 6 * 12) for i in range(36)}
    result = search_trap_mapping(make_graph(nodes, ()), [make_layout("grid", positions)],
                                 accept=lambda _layout, _assignment: False)
    print(f"all candidates rejected: outcome={result.outcome.value} "
          f"states={result.total_states_visited} ms={result.elapsed_seconds * 1000:.2f}")
    assert result.outcome == TrapMappingOutcome.BUDGET_EXCEEDED
    assert result.total_states_visited == 100_000


class TestTrapLayoutBasics:
    """Test TrapLayout dataclass."""

    def test_num_traps(self):
        layout = make_layout("test", {0: (0, 0), 1: (5, 0), 2: (10, 0)})
        assert layout.num_traps == 3

    def test_trap_ids_sorted(self):
        layout = make_layout("test", {5: (0, 0), 1: (5, 0), 3: (10, 0)})
        assert layout.trap_ids == (1, 3, 5)


class TestSimpleGraphs:
    """Test mapping of simple graphs."""

    def test_single_node_graph(self):
        """Single node should map to any trap."""
        graph = make_graph(("a",), ())
        layout = make_layout("L1", {0: (0.0, 0.0), 1: (5.0, 0.0)})

        result = search_trap_mapping(graph, [layout])

        assert result.outcome == TrapMappingOutcome.FOUND
        assert result.layout_id == "L1"
        assert result.assignment is not None
        assert "a" in result.assignment
        assert result.assignment["a"] in {0, 1}

    def test_two_nodes_no_edge(self):
        """Two unconnected nodes need traps >= 11µm apart (radius + margin)."""
        graph = make_graph(("a", "b"), ())
        # Traps 15µm apart - ok for non-edge
        layout = make_layout("L1", {0: (0.0, 0.0), 1: (15.0, 0.0)})

        result = search_trap_mapping(graph, [layout], radius=10.0, margin=1.0)

        assert result.outcome == TrapMappingOutcome.FOUND
        assert result.assignment is not None
        assert len(result.assignment) == 2
        assert result.assignment["a"] != result.assignment["b"]

    def test_two_nodes_no_edge_too_close(self):
        """Non-edge with traps too close should fail."""
        graph = make_graph(("a", "b"), ())
        # Traps only 8µm apart - too close for non-edge (need >= 11µm)
        layout = make_layout("L1", {0: (0.0, 0.0), 1: (8.0, 0.0)})

        result = search_trap_mapping(graph, [layout], radius=10.0, margin=1.0)

        assert result.outcome == TrapMappingOutcome.EXHAUSTED

    def test_two_nodes_with_edge(self):
        """Two connected nodes need traps <= 9µm apart (radius - margin)."""
        graph = make_graph(("a", "b"), (("a", "b"),))
        # Traps 8µm apart - ok for edge
        layout = make_layout("L1", {0: (0.0, 0.0), 1: (8.0, 0.0)})

        result = search_trap_mapping(graph, [layout], radius=10.0, margin=1.0)

        assert result.outcome == TrapMappingOutcome.FOUND

    def test_two_nodes_with_edge_too_far(self):
        """Edge with traps too far apart should fail."""
        graph = make_graph(("a", "b"), (("a", "b"),))
        # Traps 12µm apart - too far for edge (need <= 9µm)
        layout = make_layout("L1", {0: (0.0, 0.0), 1: (12.0, 0.0)})

        result = search_trap_mapping(graph, [layout], radius=10.0, margin=1.0)

        assert result.outcome == TrapMappingOutcome.EXHAUSTED


class TestTriangleGraphs:
    """Test mapping of triangle-shaped graphs."""

    def test_triangle_all_edges(self):
        """Complete triangle needs all pairs within edge distance."""
        graph = make_graph(("a", "b", "c"), (("a", "b"), ("b", "c"), ("a", "c")))
        # Equilateral triangle with side 7µm (all edges)
        s = 7.0
        layout = make_layout("L1", {
            0: (0.0, 0.0),
            1: (s, 0.0),
            2: (s / 2, s * math.sqrt(3) / 2),
        })

        result = search_trap_mapping(graph, [layout], radius=10.0, margin=1.0)

        assert result.outcome == TrapMappingOutcome.FOUND
        assert len(result.assignment) == 3

    def test_independent_set_three_nodes(self):
        """Three unconnected nodes need all pairs far apart."""
        graph = make_graph(("a", "b", "c"), ())
        # Triangle with side 15µm (all non-edges)
        s = 15.0
        layout = make_layout("L1", {
            0: (0.0, 0.0),
            1: (s, 0.0),
            2: (s / 2, s * math.sqrt(3) / 2),
        })

        result = search_trap_mapping(graph, [layout], radius=10.0, margin=1.0)

        assert result.outcome == TrapMappingOutcome.FOUND

    def test_path_graph(self):
        """Path a-b-c needs edge pairs close, non-edge far."""
        graph = make_graph(("a", "b", "c"), (("a", "b"), ("b", "c")))
        # Linear layout: 0 -- 7µm -- 1 -- 7µm -- 2 (total 14µm)
        # a-b and b-c are edges (7µm <= 9µm ok)
        # a-c is non-edge (14µm >= 11µm ok)
        layout = make_layout("L1", {
            0: (0.0, 0.0),
            1: (7.0, 0.0),
            2: (14.0, 0.0),
        })

        result = search_trap_mapping(graph, [layout], radius=10.0, margin=1.0)

        assert result.outcome == TrapMappingOutcome.FOUND
        # Verify a and c are assigned to endpoints
        assert result.assignment is not None
        # The assignment should be a->0, b->1, c->2 or a->2, b->1, c->0
        b_trap = result.assignment["b"]
        a_trap = result.assignment["a"]
        c_trap = result.assignment["c"]
        # b must be in the middle (trap 1)
        assert b_trap == 1
        # a and c at endpoints
        assert {a_trap, c_trap} == {0, 2}


class TestMultipleLayouts:
    """Test search across multiple layouts."""

    def test_first_layout_found(self):
        """Should stop at first successful layout."""
        graph = make_graph(("a", "b"), (("a", "b"),))
        layout1 = make_layout("L1", {0: (0, 0), 1: (7, 0)})  # Valid
        layout2 = make_layout("L2", {0: (0, 0), 1: (8, 0)})  # Also valid

        result = search_trap_mapping(graph, [layout1, layout2])

        assert result.outcome == TrapMappingOutcome.FOUND
        assert result.layout_id == "L1"  # First one (sorted by ID)

    def test_fallback_to_second_layout(self):
        """Should try second layout if first fails."""
        graph = make_graph(("a", "b"), (("a", "b"),))
        layout1 = make_layout("L1", {0: (0, 0), 1: (15, 0)})  # Too far for edge
        layout2 = make_layout("L2", {0: (0, 0), 1: (7, 0)})   # Valid

        result = search_trap_mapping(graph, [layout1, layout2])

        assert result.outcome == TrapMappingOutcome.FOUND
        assert result.layout_id == "L2"
        assert len(result.layout_attempts) == 2
        assert result.layout_attempts[0].outcome == TrapMappingOutcome.EXHAUSTED
        assert result.layout_attempts[1].outcome == TrapMappingOutcome.FOUND

    def test_required_layout_no_fallback(self):
        """Should not fall back when layout is explicitly required."""
        graph = make_graph(("a", "b"), (("a", "b"),))
        layout1 = make_layout("L1", {0: (0, 0), 1: (15, 0)})  # Too far for edge
        layout2 = make_layout("L2", {0: (0, 0), 1: (7, 0)})   # Valid

        result = search_trap_mapping(
            graph, [layout1, layout2], required_layout_id="L1"
        )

        assert result.outcome == TrapMappingOutcome.EXHAUSTED
        assert len(result.layout_attempts) == 1
        assert result.layout_attempts[0].layout_id == "L1"

    def test_required_layout_not_found(self):
        """Should fail if required layout doesn't exist."""
        graph = make_graph(("a",), ())
        layout = make_layout("L1", {0: (0, 0)})

        result = search_trap_mapping(graph, [layout], required_layout_id="L99")

        assert result.outcome == TrapMappingOutcome.NO_LAYOUTS
        assert "required_layout_not_found" in str(result.diagnostic)


class TestCapacity:
    """Test capacity checking."""

    def test_insufficient_traps(self):
        """Should fail if no layout has enough traps."""
        graph = make_graph(("a", "b", "c"), ())
        layout = make_layout("L1", {0: (0, 0), 1: (15, 0)})  # Only 2 traps

        result = search_trap_mapping(graph, [layout])

        assert result.outcome == TrapMappingOutcome.CAPACITY_INSUFFICIENT
        assert result.diagnostic.get("required_traps") == 3
        assert result.diagnostic.get("max_available") == 2

    def test_no_layouts(self):
        """Should fail with no layouts."""
        graph = make_graph(("a",), ())

        result = search_trap_mapping(graph, [])

        assert result.outcome == TrapMappingOutcome.NO_LAYOUTS


class TestBudgetAndTimeout:
    """Test budget and timeout handling."""

    def test_state_budget_per_layout(self):
        """Should respect state budget per layout."""
        # Create a hard instance - 5 nodes, all edges (complete graph)
        # requires traps all within 9µm but that's geometrically impossible
        # for 5+ nodes, so this will exhaust the search
        graph = make_graph(
            ("a", "b", "c", "d", "e"),
            (("a", "b"), ("a", "c"), ("a", "d"), ("a", "e"),
             ("b", "c"), ("b", "d"), ("b", "e"),
             ("c", "d"), ("c", "e"), ("d", "e"))
        )
        # Layout with traps not all within 9µm of each other
        layout = make_layout("L1", {i: (i * 5.0, 0.0) for i in range(10)})

        result = search_trap_mapping(
            graph, [layout], state_budget_per_layout=50
        )

        # This should exhaust or hit budget - no valid mapping exists
        assert result.outcome in {
            TrapMappingOutcome.BUDGET_EXCEEDED,
            TrapMappingOutcome.EXHAUSTED,
        }

    def test_total_state_budget(self):
        """Should respect total state budget across layouts."""
        graph = make_graph(("a", "b"), (("a", "b"),))
        layout1 = make_layout("L1", {0: (0, 0), 1: (15, 0)})  # Fail
        layout2 = make_layout("L2", {0: (0, 0), 1: (15, 0)})  # Fail

        result = search_trap_mapping(
            graph, [layout1, layout2], total_state_budget=5
        )

        assert result.total_states_visited <= 10  # Allow overhead

    def test_budget_1_visits_exactly_1_state(self):
        """Budget of 1 should visit exactly 1 state, not 2."""
        graph = make_graph(("a",), ())
        layout = make_layout("L1", {0: (0, 0), 1: (15, 0)})

        result = search_trap_mapping(
            graph, [layout], state_budget_per_layout=1
        )

        # With budget 1, should visit exactly 1 state
        assert result.total_states_visited == 1

    def test_budget_exceeded_not_exhausted_when_layouts_unexplored(self):
        """Should return BUDGET_EXCEEDED when valid layouts remain unexplored.

        Reproduces the bug: first layout is impossible, second has a solution,
        but with total budget of 1, the mapper returned EXHAUSTED after only
        visiting the first layout. Should return BUDGET_EXCEEDED instead.
        """
        graph = make_graph(("a", "b"), (("a", "b"),))
        # First layout: traps too far apart for edge (15µm > 9µm)
        layout1 = make_layout("L1", {0: (0, 0), 1: (15, 0)})
        # Second layout: traps close enough for edge (7µm <= 9µm)
        layout2 = make_layout("L2", {0: (0, 0), 1: (7, 0)})

        # With budget of 1, we can only explore one state in the first layout
        result = search_trap_mapping(
            graph, [layout1, layout2], total_state_budget=1
        )

        # Must NOT be EXHAUSTED because we didn't explore layout2
        # Must be BUDGET_EXCEEDED
        assert result.outcome == TrapMappingOutcome.BUDGET_EXCEEDED
        assert result.diagnostic.get("layouts_searched", 0) < result.diagnostic.get("layouts_available", 0)

    def test_exhausted_only_when_all_layouts_searched(self):
        """EXHAUSTED should only be returned when ALL eligible layouts are fully searched."""
        graph = make_graph(("a", "b"), (("a", "b"),))
        # Both layouts impossible (traps too far apart)
        layout1 = make_layout("L1", {0: (0, 0), 1: (15, 0)})
        layout2 = make_layout("L2", {0: (0, 0), 1: (20, 0)})

        # Enough budget to fully search both
        result = search_trap_mapping(
            graph, [layout1, layout2], state_budget_per_layout=100
        )

        # Both were searched and exhausted, so EXHAUSTED is correct
        assert result.outcome == TrapMappingOutcome.EXHAUSTED
        assert result.diagnostic.get("layouts_searched") == result.diagnostic.get("layouts_available")


class TestBoundaryDistances:
    """Test edge cases at exact boundary distances."""

    def test_edge_at_exactly_9um(self):
        """Edge at exactly 9µm (radius - margin) should be valid."""
        graph = make_graph(("a", "b"), (("a", "b"),))
        layout = make_layout("L1", {0: (0, 0), 1: (9.0, 0)})

        result = search_trap_mapping(graph, [layout], radius=10.0, margin=1.0)

        assert result.outcome == TrapMappingOutcome.FOUND

    def test_edge_at_9_01um(self):
        """Edge at 9.01µm (just beyond radius - margin) should fail."""
        graph = make_graph(("a", "b"), (("a", "b"),))
        layout = make_layout("L1", {0: (0, 0), 1: (9.01, 0)})

        result = search_trap_mapping(graph, [layout], radius=10.0, margin=1.0)

        assert result.outcome == TrapMappingOutcome.EXHAUSTED

    def test_nonedge_at_exactly_11um(self):
        """Non-edge at exactly 11µm (radius + margin) should be valid."""
        graph = make_graph(("a", "b"), ())
        layout = make_layout("L1", {0: (0, 0), 1: (11.0, 0)})

        result = search_trap_mapping(graph, [layout], radius=10.0, margin=1.0)

        assert result.outcome == TrapMappingOutcome.FOUND

    def test_nonedge_at_10_99um(self):
        """Non-edge at 10.99µm (just below radius + margin) should fail."""
        graph = make_graph(("a", "b"), ())
        layout = make_layout("L1", {0: (0, 0), 1: (10.99, 0)})

        result = search_trap_mapping(graph, [layout], radius=10.0, margin=1.0)

        assert result.outcome == TrapMappingOutcome.EXHAUSTED


class TestMinAtomDistance:
    """Test minimum atom distance constraint."""

    def test_traps_below_min_distance_excluded(self):
        """Trap pairs below min_atom_distance should be excluded."""
        graph = make_graph(("a", "b"), (("a", "b"),))
        # Traps 3µm apart - below default min_atom_distance of 4µm
        layout = make_layout("L1", {0: (0, 0), 1: (3.0, 0)})

        result = search_trap_mapping(
            graph, [layout], radius=10.0, margin=1.0, min_atom_distance=4.0
        )

        assert result.outcome == TrapMappingOutcome.EXHAUSTED

    def test_traps_at_min_distance_allowed(self):
        """Trap pairs at exactly min_atom_distance should be allowed for edges."""
        graph = make_graph(("a", "b"), (("a", "b"),))
        layout = make_layout("L1", {0: (0, 0), 1: (4.0, 0)})

        result = search_trap_mapping(
            graph, [layout], radius=10.0, margin=1.0, min_atom_distance=4.0
        )

        assert result.outcome == TrapMappingOutcome.FOUND


class TestDeterminism:
    """Test that results are deterministic."""

    def test_same_result_multiple_runs(self):
        """Same input should produce same output."""
        graph = make_graph(("a", "b", "c"), (("a", "b"),))
        layout = make_layout("L1", {
            0: (0, 0),
            1: (7, 0),
            2: (14, 0),
        })

        result1 = search_trap_mapping(graph, [layout])
        result2 = search_trap_mapping(graph, [layout])

        assert result1.outcome == result2.outcome
        assert result1.assignment == result2.assignment
        assert result1.total_states_visited == result2.total_states_visited

    def test_node_order_preserved(self):
        """Assignment should map nodes in graph's original order."""
        graph = make_graph(("x", "a", "z"), ())  # Specific order
        layout = make_layout("L1", {
            0: (0, 0),
            1: (15, 0),
            2: (30, 0),
        })

        result = search_trap_mapping(graph, [layout])

        assert result.outcome == TrapMappingOutcome.FOUND
        assert list(result.coordinates.keys()) == ["x", "a", "z"]


class TestValidateAssignment:
    """Test validate_trap_assignment function."""

    def test_valid_assignment(self):
        graph = make_graph(("a", "b"), (("a", "b"),))
        layout = make_layout("L1", {0: (0, 0), 1: (7, 0)})
        assignment = {"a": 0, "b": 1}

        result = validate_trap_assignment(graph, layout, assignment)

        assert result["valid"] is True

    def test_invalid_duplicate_trap(self):
        graph = make_graph(("a", "b"), ())
        layout = make_layout("L1", {0: (0, 0), 1: (15, 0)})
        assignment = {"a": 0, "b": 0}  # Same trap!

        result = validate_trap_assignment(graph, layout, assignment)

        assert result["valid"] is False
        assert result["error"] == "duplicate_trap_assignment"

    def test_invalid_missing_node(self):
        graph = make_graph(("a", "b"), ())
        layout = make_layout("L1", {0: (0, 0), 1: (15, 0)})
        assignment = {"a": 0}  # Missing b

        result = validate_trap_assignment(graph, layout, assignment)

        assert result["valid"] is False


class TestResultDiagnostics:
    """Test diagnostic information in results."""

    def test_found_result_has_coordinates(self):
        graph = make_graph(("a",), ())
        layout = make_layout("L1", {0: (5.0, 10.0)})

        result = search_trap_mapping(graph, [layout])

        assert result.outcome == TrapMappingOutcome.FOUND
        assert result.coordinates is not None
        assert result.coordinates["a"] == (5.0, 10.0)

    def test_result_to_dict_serializable(self):
        import json

        graph = make_graph(("a", "b"), (("a", "b"),))
        layout = make_layout("L1", {0: (0, 0), 1: (7, 0)})

        result = search_trap_mapping(graph, [layout])
        d = result.to_dict()

        # Should be JSON-serializable
        json_str = json.dumps(d)
        assert json_str is not None
        assert d["outcome"] == "found"


class TestIntegrationWithDiagnoseLayout:
    """Test that mapper results pass diagnose_layout validation."""

    def test_found_mapping_passes_diagnose_layout(self):
        """A found mapping should pass the diagnose_layout validation."""
        graph = make_graph(("a", "b", "c"), (("a", "b"), ("b", "c")))
        # Path graph: a-b-c
        layout = make_layout("L1", {
            0: (0.0, 0.0),
            1: (7.0, 0.0),
            2: (14.0, 0.0),
        })

        result = search_trap_mapping(graph, [layout], radius=10.0, margin=1.0)

        assert result.outcome == TrapMappingOutcome.FOUND
        assert result.coordinates is not None

        # Verify with diagnose_layout
        diagnostic = diagnose_layout(graph, result.coordinates, 10.0, 1.0)
        assert diagnostic["valid"] is True
        assert diagnostic["missing_edges"] == []
        assert diagnostic["extra_edges"] == []
        assert diagnostic["margin_pairs"] == []
