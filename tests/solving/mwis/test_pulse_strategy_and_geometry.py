"""Tests for pulse strategy configuration and geometry diagnostics."""

import pytest

from qreduce.mwis import ReductionGraph
from qreduce.solving.mwis.geometry_diagnostics import (
    compare_physical_vs_canonical,
    diagnose_geometry_fidelity,
)
from qreduce.solving.mwis.pulse_strategy import (
    PulseStrategyConfig,
    PulseStrategyId,
    default_linear_sweep_config,
    default_smoothed_annealing_config,
    diagnose_pulse_strategy,
    legacy_constant_config,
)


class TestPulseStrategyConfig:
    """Tests for pulse strategy configuration."""

    def test_default_smoothed_annealing(self):
        """Default smoothed annealing should have valid parameters."""
        config = default_smoothed_annealing_config()

        assert config.strategy_id == PulseStrategyId.SMOOTHED_ANNEALING
        assert config.strategy_version == 1
        assert config.total_duration_ns == 4000
        assert config.max_amplitude_rad_per_us > 0
        assert config.initial_detuning_rad_per_us < 0  # Negative start
        assert config.final_detuning_rad_per_us > 0  # Positive end
        assert config.ramp_up_fraction > 0
        assert config.ramp_down_fraction > 0

    def test_legacy_constant_config(self):
        """Legacy constant should match original values."""
        config = legacy_constant_config()

        assert config.strategy_id == PulseStrategyId.CONSTANT
        assert config.total_duration_ns == 1000
        assert config.max_amplitude_rad_per_us == 1.0
        assert config.ramp_up_fraction == 0.0
        assert config.ramp_down_fraction == 0.0

    def test_linear_sweep_config(self):
        """Linear sweep should have valid parameters."""
        config = default_linear_sweep_config()

        assert config.strategy_id == PulseStrategyId.LINEAR_SWEEP
        assert config.total_duration_ns > 0
        assert config.initial_detuning_rad_per_us < config.final_detuning_rad_per_us

    def test_config_validation_rejects_invalid(self):
        """Invalid configurations should raise ValueError."""
        with pytest.raises(ValueError, match="positive"):
            PulseStrategyConfig(
                strategy_id=PulseStrategyId.LINEAR_SWEEP,
                strategy_version=1,
                total_duration_ns=-100,  # Invalid
                max_amplitude_rad_per_us=10.0,
                initial_detuning_rad_per_us=-10.0,
                final_detuning_rad_per_us=10.0,
            )

        with pytest.raises(ValueError, match="ramp"):
            PulseStrategyConfig(
                strategy_id=PulseStrategyId.LINEAR_SWEEP,
                strategy_version=1,
                total_duration_ns=4000,
                max_amplitude_rad_per_us=10.0,
                initial_detuning_rad_per_us=-10.0,
                final_detuning_rad_per_us=10.0,
                ramp_up_fraction=0.6,  # Too large
                ramp_down_fraction=0.6,
            )

    def test_config_to_dict_serialization(self):
        """Config should serialize to dictionary."""
        config = default_smoothed_annealing_config()
        d = config.to_dict()

        assert d["strategy_id"] == "smoothed_annealing"
        assert "total_duration_ns" in d
        assert "max_amplitude_rad_per_us" in d


class TestPulseStrategyDiagnostics:
    """Tests for pulse strategy diagnostics."""

    def test_diagnose_without_distance(self):
        """Diagnostics should work without distance information."""
        config = default_smoothed_annealing_config()
        diag = diagnose_pulse_strategy(config)

        assert diag.strategy_id == PulseStrategyId.SMOOTHED_ANNEALING
        assert diag.detuning_range > 0
        assert diag.max_interaction_energy is None  # No distance provided

    def test_diagnose_with_distance(self):
        """Diagnostics should compute interactions with distance."""
        config = default_smoothed_annealing_config()
        diag = diagnose_pulse_strategy(config, min_distance_um=5.0)

        assert diag.max_interaction_energy is not None
        assert diag.amplitude_to_interaction_ratio is not None

    def test_constant_pulse_warns(self):
        """Constant pulse should generate warning."""
        config = legacy_constant_config()
        diag = diagnose_pulse_strategy(config)

        assert len(diag.warnings) > 0
        assert any("annealing" in w.lower() for w in diag.warnings)

    def test_short_duration_warns(self):
        """Very short duration should warn about adiabaticity."""
        config = PulseStrategyConfig(
            strategy_id=PulseStrategyId.LINEAR_SWEEP,
            strategy_version=1,
            total_duration_ns=100,  # Very short
            max_amplitude_rad_per_us=10.0,
            initial_detuning_rad_per_us=-10.0,
            final_detuning_rad_per_us=10.0,
        )
        diag = diagnose_pulse_strategy(config)

        assert any("adiabatic" in w.lower() for w in diag.warnings)


def make_graph(node_weights: dict[str, float], edges: list[tuple[str, str]]) -> ReductionGraph:
    """Create a test graph."""
    node_ids = tuple(sorted(node_weights.keys()))
    canonical_edges = tuple((min(a, b), max(a, b)) for a, b in edges)
    edge_reasons = {e: "conflict" for e in canonical_edges}
    return ReductionGraph(
        node_ids=node_ids,
        node_weights=node_weights,
        edges=canonical_edges,
        edge_reasons=edge_reasons,
        graph_policy_id="test",
        graph_policy_version="1.0",
    )


class TestGeometryDiagnostics:
    """Tests for geometry-Hamiltonian correspondence diagnostics."""

    def test_perfect_geometry(self):
        """Graph edges at short distance, non-edges at long distance."""
        # Two nodes connected by an edge, placed close together
        graph = make_graph({"a": 1.0, "b": 1.0}, [("a", "b")])
        # Close together (strong interaction for edge)
        coordinates = {"a": (0.0, 0.0), "b": (5.0, 0.0)}

        diag = diagnose_geometry_fidelity(
            graph, coordinates, interaction_threshold=0.1
        )

        assert diag.correct_edge_count == 1
        assert diag.weak_edge_count == 0
        assert diag.spurious_interaction_count == 0
        assert diag.is_valid
        assert diag.fidelity_score == 1.0

    def test_weak_edge_detected(self):
        """Edge with atoms too far apart should be flagged."""
        graph = make_graph({"a": 1.0, "b": 1.0}, [("a", "b")])
        # Very far apart (weak interaction)
        coordinates = {"a": (0.0, 0.0), "b": (100.0, 0.0)}

        diag = diagnose_geometry_fidelity(
            graph, coordinates, interaction_threshold=1.0
        )

        assert diag.weak_edge_count == 1
        assert not diag.is_valid
        assert len(diag.warnings) > 0

    def test_spurious_interaction_detected(self):
        """Non-edge with atoms too close should be flagged."""
        # No edge between a and b
        graph = make_graph({"a": 1.0, "b": 1.0}, [])
        # But placed close together
        coordinates = {"a": (0.0, 0.0), "b": (5.0, 0.0)}

        diag = diagnose_geometry_fidelity(
            graph, coordinates, interaction_threshold=0.1
        )

        assert diag.spurious_interaction_count == 1
        assert not diag.is_valid

    def test_pair_details_optional(self):
        """Pair details should be included only when requested."""
        graph = make_graph({"a": 1.0, "b": 1.0}, [])
        coordinates = {"a": (0.0, 0.0), "b": (10.0, 0.0)}

        diag_no_details = diagnose_geometry_fidelity(
            graph, coordinates, include_pair_details=False
        )
        assert len(diag_no_details.pair_details) == 0

        diag_with_details = diagnose_geometry_fidelity(
            graph, coordinates, include_pair_details=True
        )
        assert len(diag_with_details.pair_details) == 1

    def test_coordinate_node_mismatch_raises(self):
        """Mismatched coordinates and graph nodes should raise."""
        graph = make_graph({"a": 1.0, "b": 1.0}, [])
        coordinates = {"a": (0.0, 0.0), "c": (10.0, 0.0)}  # c not in graph

        with pytest.raises(ValueError, match="nodes"):
            diagnose_geometry_fidelity(graph, coordinates)


class TestPhysicalVsCanonicalComparison:
    """Tests for comparing physical ground state with MWIS optimum."""

    def test_simple_graph_comparison(self):
        """Test comparison on a simple graph."""
        # Simple graph: a--b, both weight 1
        graph = make_graph({"a": 1.0, "b": 1.0}, [("a", "b")])
        coordinates = {"a": (0.0, 0.0), "b": (5.0, 0.0)}

        result = compare_physical_vs_canonical(
            graph, coordinates,
            final_detuning=10.0,
            max_enumeration_size=10
        )

        assert result is not None
        assert result.canonical_optimum_weight == 1.0  # Can only pick one
        # Physical ground state should also select one node

    def test_returns_none_for_large_graph(self):
        """Large graphs should return None (not enumerable)."""
        node_weights = {f"n{i}": 1.0 for i in range(25)}
        graph = make_graph(node_weights, [])
        coordinates = {f"n{i}": (i * 10.0, 0.0) for i in range(25)}

        result = compare_physical_vs_canonical(
            graph, coordinates,
            final_detuning=10.0,
            max_enumeration_size=20
        )

        assert result is None

    def test_edgeless_graph_all_selected(self):
        """Edgeless graph should select all in both physical and canonical."""
        graph = make_graph({"a": 1.0, "b": 2.0, "c": 3.0}, [])
        coordinates = {"a": (0.0, 0.0), "b": (100.0, 0.0), "c": (200.0, 0.0)}

        result = compare_physical_vs_canonical(
            graph, coordinates,
            final_detuning=10.0
        )

        assert result is not None
        assert result.canonical_optimum == (1, 1, 1)  # All selected
        assert result.canonical_optimum_weight == 6.0


def test_degenerate_optima_compare_objective_not_arbitrary_vector():
    graph = ReductionGraph(("a", "b"), {"a": 1, "b": 1}, (("a", "b"),),
                           {("a", "b"): "conflict"}, "test", "1")
    comparison = compare_physical_vs_canonical(graph, {"a": (0, 0), "b": (5, 0)}, 1.)
    assert comparison.num_degenerate_ground_states == 2
    assert comparison.all_ground_states_independent
    assert comparison.any_ground_state_optimal
    assert comparison.all_ground_states_optimal
    assert comparison.energy_gap_to_optimum == 0.
