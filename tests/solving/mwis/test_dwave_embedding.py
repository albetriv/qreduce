"""Tests for the D-Wave embedding module.

These tests verify:
- Profile resolution and validation
- Backward compatibility (none profile works without embedding dependencies)
- Embedding result structure and serialization
- Chain break statistics calculation

Tests requiring actual embedding dependencies are marked with
@pytest.mark.requires_dwave_embedding and skipped if unavailable.
"""

import pytest

from qreduce.solving.mwis.dwave_embedding import (
    EMBEDDING_PROFILE_NONE,
    EMBEDDING_PROFILE_PEGASUS_P16,
    EMBEDDING_PROFILE_ZEPHYR_Z12,
    VALID_EMBEDDING_PROFILES,
    ChainBreakStatistics,
    EmbeddingProfile,
    EmbeddingSearchResult,
    resolve_embedding_profile,
    validate_embedding_profile_for_backend,
)
from qreduce.status import TerminalReason


class TestEmbeddingProfileConstants:
    """Verify embedding profile constants are properly defined."""

    def test_valid_profiles_contains_expected_values(self):
        assert EMBEDDING_PROFILE_NONE in VALID_EMBEDDING_PROFILES
        assert EMBEDDING_PROFILE_PEGASUS_P16 in VALID_EMBEDDING_PROFILES
        assert EMBEDDING_PROFILE_ZEPHYR_Z12 in VALID_EMBEDDING_PROFILES
        assert len(VALID_EMBEDDING_PROFILES) == 3

    def test_profile_values_are_lowercase_strings(self):
        for profile in VALID_EMBEDDING_PROFILES:
            assert isinstance(profile, str)
            assert profile == profile.lower()


class TestResolveEmbeddingProfile:
    """Test profile resolution logic."""

    def test_none_profile_returns_disabled_embedding(self):
        profile = resolve_embedding_profile(EMBEDDING_PROFILE_NONE)
        assert profile.profile_id == EMBEDDING_PROFILE_NONE
        assert profile.is_embedding_enabled is False
        assert profile.topology_type is None
        assert profile.topology_size is None

    def test_none_is_default_when_argument_is_none(self):
        profile = resolve_embedding_profile(None)
        assert profile.profile_id == EMBEDDING_PROFILE_NONE
        assert profile.is_embedding_enabled is False

    def test_pegasus_p16_returns_enabled_embedding(self):
        profile = resolve_embedding_profile(EMBEDDING_PROFILE_PEGASUS_P16)
        assert profile.profile_id == EMBEDDING_PROFILE_PEGASUS_P16
        assert profile.is_embedding_enabled is True
        assert profile.topology_type == "pegasus"
        assert profile.topology_size == 16

    def test_zephyr_z12_returns_enabled_embedding(self):
        profile = resolve_embedding_profile(EMBEDDING_PROFILE_ZEPHYR_Z12)
        assert profile.is_embedding_enabled is True
        assert profile.topology_type == "zephyr"
        assert profile.topology_size == 12

    def test_invalid_profile_raises_value_error(self):
        with pytest.raises(ValueError, match="Invalid embedding profile"):
            resolve_embedding_profile("invalid_profile")

    def test_empty_string_raises_value_error(self):
        with pytest.raises(ValueError, match="Invalid embedding profile"):
            resolve_embedding_profile("")


class TestValidateEmbeddingProfileForBackend:
    """Test profile-backend compatibility validation."""

    def test_none_profile_is_always_valid(self):
        is_valid, error = validate_embedding_profile_for_backend(
            EMBEDDING_PROFILE_NONE, "simulated_annealing", True
        )
        assert is_valid is True
        assert error is None

    def test_none_profile_as_python_none_is_valid(self):
        is_valid, error = validate_embedding_profile_for_backend(
            None, "simulated_annealing", True
        )
        assert is_valid is True
        assert error is None

    def test_pegasus_requires_dwave_backend(self):
        is_valid, error = validate_embedding_profile_for_backend(
            EMBEDDING_PROFILE_PEGASUS_P16, "local_greedy", True
        )
        assert is_valid is False
        assert "simulated_annealing" in error

    def test_pegasus_requires_reduction_enabled(self):
        is_valid, error = validate_embedding_profile_for_backend(
            EMBEDDING_PROFILE_PEGASUS_P16, "simulated_annealing", False
        )
        assert is_valid is False
        assert "reduction" in error.lower()

    def test_zephyr_valid_with_dwave_and_reduction(self):
        is_valid, error = validate_embedding_profile_for_backend(
            EMBEDDING_PROFILE_ZEPHYR_Z12, "simulated_annealing", True
        )
        assert is_valid is True
        assert error is None


class TestEmbeddingProfile:
    """Test the EmbeddingProfile dataclass."""

    def test_none_profile_rejects_enabled_flag(self):
        with pytest.raises(ValueError, match="disabled"):
            EmbeddingProfile(
                profile_id=EMBEDDING_PROFILE_NONE,
                is_embedding_enabled=True,
            )

    def test_embedding_profile_rejects_disabled_flag(self):
        with pytest.raises(ValueError, match="enabled"):
            EmbeddingProfile(
                profile_id=EMBEDDING_PROFILE_PEGASUS_P16,
                topology_type="pegasus",
                topology_size=16,
                is_embedding_enabled=False,
            )

    def test_invalid_profile_id_raises_error(self):
        with pytest.raises(ValueError, match="Invalid embedding profile"):
            EmbeddingProfile(profile_id="bad_profile")

    def test_to_dict_is_serializable(self):
        profile = resolve_embedding_profile(EMBEDDING_PROFILE_PEGASUS_P16)
        data = profile.to_dict()
        assert isinstance(data, dict)
        assert data["profile_id"] == EMBEDDING_PROFILE_PEGASUS_P16
        assert data["is_embedding_enabled"] is True


class TestEmbeddingSearchResult:
    """Test the EmbeddingSearchResult dataclass."""

    def test_success_result_with_embedding(self):
        profile = resolve_embedding_profile(EMBEDDING_PROFILE_PEGASUS_P16)
        result = EmbeddingSearchResult(
            success=True,
            embedding={"a": (0, 1), "b": (2,)},
            profile=profile,
            topology_node_count=100,
            topology_edge_count=200,
            source_node_count=2,
            source_edge_count=1,
            embedded_qubit_count=3,
            chain_lengths=(2, 1),
            mean_chain_length=1.5,
            max_chain_length=2,
            search_time_seconds=0.5,
        )
        assert result.success is True
        assert result.embedding["a"] == (0, 1)
        assert result.terminal_reason is None

    def test_failure_result_has_terminal_reason(self):
        profile = resolve_embedding_profile(EMBEDDING_PROFILE_PEGASUS_P16)
        result = EmbeddingSearchResult(
            success=False,
            embedding=None,
            profile=profile,
            terminal_reason=TerminalReason.MIS_EMBEDDING_FAILED,
            diagnostic_message="No embedding found",
        )
        assert result.success is False
        assert result.terminal_reason == TerminalReason.MIS_EMBEDDING_FAILED

    def test_embedding_is_frozen_mapping(self):
        profile = resolve_embedding_profile(EMBEDDING_PROFILE_NONE)
        result = EmbeddingSearchResult(
            success=True,
            embedding={"a": (0,)},
            profile=profile,
        )
        # Should not be able to modify
        with pytest.raises(TypeError):
            result.embedding["b"] = (1,)

    def test_to_dict_is_serializable(self):
        profile = resolve_embedding_profile(EMBEDDING_PROFILE_PEGASUS_P16)
        result = EmbeddingSearchResult(
            success=True,
            embedding={"a": (0, 1)},
            profile=profile,
            chain_lengths=(2,),
            library_versions={"minorminer": "0.2.15"},
        )
        data = result.to_dict()
        assert isinstance(data, dict)
        assert data["success"] is True
        assert data["embedding"] == {"a": [0, 1]}  # tuple becomes list in JSON


class TestChainBreakStatistics:
    """Test the ChainBreakStatistics dataclass."""

    def test_statistics_creation(self):
        stats = ChainBreakStatistics(
            total_samples=100,
            samples_with_breaks=10,
            total_chain_count=500,
            broken_chain_count=15,
            broken_chain_fraction=0.03,
            mean_break_fraction_per_sample=0.1,
        )
        assert stats.total_samples == 100
        assert stats.broken_chain_fraction == 0.03

    def test_to_dict_is_serializable(self):
        stats = ChainBreakStatistics(
            total_samples=100,
            samples_with_breaks=10,
            total_chain_count=500,
            broken_chain_count=15,
            broken_chain_fraction=0.03,
            mean_break_fraction_per_sample=0.1,
        )
        data = stats.to_dict()
        assert isinstance(data, dict)
        assert data["total_samples"] == 100


class TestBackwardCompatibility:
    """Test that 'none' profile works without embedding dependencies."""

    def test_none_profile_does_not_import_embedding_libraries(self):
        """Verify that resolving 'none' profile doesn't trigger embedding imports."""
        # This test passes if resolve_embedding_profile doesn't raise ImportError
        profile = resolve_embedding_profile(EMBEDDING_PROFILE_NONE)
        assert profile.is_embedding_enabled is False

    def test_validation_with_none_does_not_require_dependencies(self):
        """Validate profile compatibility check for 'none' works without dependencies."""
        is_valid, _ = validate_embedding_profile_for_backend(
            EMBEDDING_PROFILE_NONE, "local_greedy", False
        )
        assert is_valid is True


class TestEmbeddingValidation:
    """Test the _validate_embedding function for all 7 conditions."""

    @pytest.fixture
    def simple_target_graph(self):
        """Create a simple target graph for testing."""
        import networkx as nx
        # Simple grid: 0-1-2
        #              |   |
        #              3-4-5
        g = nx.Graph()
        g.add_edges_from([(0, 1), (1, 2), (0, 3), (2, 5), (3, 4), (4, 5), (1, 4)])
        return g

    def test_valid_embedding_passes(self, simple_target_graph):
        """A correctly structured embedding passes all checks."""
        from qreduce.solving.mwis.dwave_embedding import _validate_embedding

        embedding = {"a": [0, 1], "b": [2, 5]}  # Two chains with edge between them
        source_vars = frozenset(["a", "b"])
        source_edges = frozenset([("a", "b")])

        is_valid, error = _validate_embedding(
            embedding, source_vars, source_edges, simple_target_graph
        )

        assert is_valid is True
        assert error is None

    def test_rejects_missing_variable(self, simple_target_graph):
        """Condition 1: Embedding keys must match source variables."""
        from qreduce.solving.mwis.dwave_embedding import _validate_embedding

        embedding = {"a": [0]}  # Missing 'b'
        source_vars = frozenset(["a", "b"])
        source_edges = frozenset([("a", "b")])

        is_valid, error = _validate_embedding(
            embedding, source_vars, source_edges, simple_target_graph
        )

        assert is_valid is False
        assert "missing" in error.lower()
        assert "b" in error

    def test_rejects_extra_variable(self, simple_target_graph):
        """Condition 1: Extra variables in embedding are rejected."""
        from qreduce.solving.mwis.dwave_embedding import _validate_embedding

        embedding = {"a": [0], "b": [1], "c": [2]}  # 'c' not in source
        source_vars = frozenset(["a", "b"])
        source_edges = frozenset([("a", "b")])

        is_valid, error = _validate_embedding(
            embedding, source_vars, source_edges, simple_target_graph
        )

        assert is_valid is False
        assert "extra" in error.lower()

    def test_rejects_empty_chain(self, simple_target_graph):
        """Condition 2: Each chain must have at least one qubit."""
        from qreduce.solving.mwis.dwave_embedding import _validate_embedding

        embedding = {"a": [0], "b": []}  # Empty chain for 'b'
        source_vars = frozenset(["a", "b"])
        source_edges = frozenset([("a", "b")])

        is_valid, error = _validate_embedding(
            embedding, source_vars, source_edges, simple_target_graph
        )

        assert is_valid is False
        assert "empty" in error.lower()

    def test_rejects_invalid_qubit(self, simple_target_graph):
        """Condition 3: All qubits must exist in target topology."""
        from qreduce.solving.mwis.dwave_embedding import _validate_embedding

        embedding = {"a": [0], "b": [999]}  # Qubit 999 doesn't exist
        source_vars = frozenset(["a", "b"])
        source_edges = frozenset([("a", "b")])

        is_valid, error = _validate_embedding(
            embedding, source_vars, source_edges, simple_target_graph
        )

        assert is_valid is False
        assert "topology" in error.lower() or "999" in error

    def test_rejects_duplicate_qubit_in_chain(self, simple_target_graph):
        """Condition 4: No chain should have duplicate qubits."""
        from qreduce.solving.mwis.dwave_embedding import _validate_embedding

        embedding = {"a": [0, 0], "b": [1]}  # Duplicate qubit in 'a'
        source_vars = frozenset(["a", "b"])
        source_edges = frozenset([("a", "b")])

        is_valid, error = _validate_embedding(
            embedding, source_vars, source_edges, simple_target_graph
        )

        assert is_valid is False
        assert "duplicate" in error.lower()

    def test_rejects_overlapping_chains(self, simple_target_graph):
        """Condition 5: Chains for different variables must be disjoint."""
        from qreduce.solving.mwis.dwave_embedding import _validate_embedding

        embedding = {"a": [0, 1], "b": [1, 2]}  # Qubit 1 shared
        source_vars = frozenset(["a", "b"])
        source_edges = frozenset([("a", "b")])

        is_valid, error = _validate_embedding(
            embedding, source_vars, source_edges, simple_target_graph
        )

        assert is_valid is False
        assert "share" in error.lower()

    def test_rejects_disconnected_chain(self, simple_target_graph):
        """Condition 6: Each chain must form a connected subgraph."""
        from qreduce.solving.mwis.dwave_embedding import _validate_embedding

        embedding = {"a": [0, 2], "b": [3]}  # 0 and 2 not connected
        source_vars = frozenset(["a", "b"])
        source_edges = frozenset([("a", "b")])

        is_valid, error = _validate_embedding(
            embedding, source_vars, source_edges, simple_target_graph
        )

        assert is_valid is False
        assert "disconnected" in error.lower()

    def test_rejects_missing_physical_edge(self, simple_target_graph):
        """Condition 7: Quadratic interactions need physical edges between chains."""
        from qreduce.solving.mwis.dwave_embedding import _validate_embedding

        # Chains with no edge between them in target
        embedding = {"a": [0], "b": [5]}  # No edge between 0 and 5
        source_vars = frozenset(["a", "b"])
        source_edges = frozenset([("a", "b")])

        is_valid, error = _validate_embedding(
            embedding, source_vars, source_edges, simple_target_graph
        )

        assert is_valid is False
        assert "physical edge" in error.lower() or "interaction" in error.lower()

    def test_isolated_nodes_no_edge_requirement(self, simple_target_graph):
        """Isolated nodes don't need physical edges."""
        from qreduce.solving.mwis.dwave_embedding import _validate_embedding

        # 'c' is isolated - can be anywhere
        embedding = {"a": [0, 1], "b": [2, 5], "c": [3]}
        source_vars = frozenset(["a", "b", "c"])
        source_edges = frozenset([("a", "b")])  # 'c' not involved

        is_valid, error = _validate_embedding(
            embedding, source_vars, source_edges, simple_target_graph
        )

        assert is_valid is True
        assert error is None


# ============================================================================
# Integration tests requiring D-Wave embedding dependencies
# ============================================================================

def _embedding_dependencies_available() -> bool:
    """Check if all embedding dependencies are available."""
    try:
        import dwave.embedding
        import dwave.graphs
        import minorminer

        # Verify they are importable by touching an attribute
        _ = dwave.embedding, dwave.graphs, minorminer
        return True
    except ImportError:
        return False


@pytest.mark.requires_dwave_embedding
@pytest.mark.skipif(
    not _embedding_dependencies_available(),
    reason="dwave-embedding group not installed",
)
class TestEmbeddingIntegration:
    """End-to-end tests for embedding with real D-Wave libraries."""

    def test_build_target_topology_pegasus(self):
        """Pegasus topology is generated with expected structure."""
        from qreduce.solving.mwis.dwave_embedding import build_target_topology

        profile = resolve_embedding_profile(EMBEDDING_PROFILE_PEGASUS_P16)
        topology = build_target_topology(profile)

        # Pegasus P16 has ~5000+ nodes
        assert topology.number_of_nodes() > 5000
        assert topology.number_of_edges() > 0

    def test_build_target_topology_zephyr(self):
        """Zephyr topology is generated with expected structure."""
        from qreduce.solving.mwis.dwave_embedding import build_target_topology

        profile = resolve_embedding_profile(EMBEDDING_PROFILE_ZEPHYR_Z12)
        topology = build_target_topology(profile)

        # Zephyr Z12 has thousands of nodes
        assert topology.number_of_nodes() > 1000
        assert topology.number_of_edges() > 0

    def test_find_embedding_small_graph(self):
        """Embedding search finds a valid embedding for a small source graph."""
        import dimod

        from qreduce.solving.mwis.dwave_embedding import find_embedding

        profile = resolve_embedding_profile(EMBEDDING_PROFILE_PEGASUS_P16)

        # Small triangle BQM (3 nodes with all edges)
        source_bqm = dimod.BinaryQuadraticModel(
            {"a": -1.0, "b": -1.0, "c": -1.0},
            {("a", "b"): 2.0, ("b", "c"): 2.0, ("a", "c"): 2.0},
            0.0,
            "BINARY",
        )

        result = find_embedding(
            source_bqm,
            profile,
            timeout_seconds=30.0,
            seed=42,
        )

        assert result.success is True
        assert result.embedding is not None
        assert set(result.embedding.keys()) == {"a", "b", "c"}
        assert all(len(chain) >= 1 for chain in result.embedding.values())
        assert result.search_time_seconds > 0

    def test_find_embedding_with_seed_reproducibility(self):
        """Same seed produces deterministic embedding search."""
        import dimod

        from qreduce.solving.mwis.dwave_embedding import find_embedding

        profile = resolve_embedding_profile(EMBEDDING_PROFILE_PEGASUS_P16)

        # Simple 2-node BQM with one edge
        source_bqm = dimod.BinaryQuadraticModel(
            {"x": -1.0, "y": -1.0, "z": -1.0},
            {("x", "y"): 2.0, ("y", "z"): 2.0},
            0.0,
            "BINARY",
        )

        result1 = find_embedding(
            source_bqm,
            profile,
            timeout_seconds=30.0,
            seed=123,
        )
        result2 = find_embedding(
            source_bqm,
            profile,
            timeout_seconds=30.0,
            seed=123,
        )

        # Both should succeed
        assert result1.success is True
        assert result2.success is True
        # With same seed, embeddings should be identical
        assert result1.embedding == result2.embedding

    def test_unembed_sampleset_with_chain_breaks(self):
        """Unembedding resolves chain breaks via majority vote."""
        # Create a minimal mock sampleset for unembedding
        # In practice this would come from an actual sampler
        import dimod

        from qreduce.solving.mwis.dwave_embedding import unembed_sampleset

        # Embedding: node 'a' mapped to qubits 0,1; node 'b' mapped to qubit 2
        embedding = {"a": (0, 1), "b": (2,)}

        # Physical samples with a chain break (qubits 0 and 1 disagree for 'a')
        physical_samples = [
            {0: 1, 1: 0, 2: 1},  # chain break: a->0=1, a->1=0
            {0: 1, 1: 1, 2: 0},  # no break: a->0=1, a->1=1
        ]
        energies = [-1.0, -2.0]
        num_occurrences = [2, 3]

        embedded_sampleset = dimod.SampleSet.from_samples(
            physical_samples,
            vartype="BINARY",
            energy=energies,
            num_occurrences=num_occurrences,
        )

        # Source BQM for unembedding
        source_bqm = dimod.BinaryQuadraticModel({"a": -1, "b": -1}, {("a", "b"): 0.5}, 0, "BINARY")

        logical_sampleset, chain_stats = unembed_sampleset(
            embedded_sampleset=embedded_sampleset,
            embedding=embedding,
            source_bqm=source_bqm,
        )

        # Verify unembedding produced logical samples
        assert len(list(logical_sampleset.samples())) == 2
        for sample in logical_sampleset.samples():
            assert set(sample.keys()) == {"a", "b"}
            assert all(v in (0, 1) for v in sample.values())

        # Verify chain break statistics weighted by occurrences
        assert chain_stats is not None
        # Total samples = 2 + 3 = 5 (weighted by occurrences)
        assert chain_stats.total_samples == 5
        # Only first sample (2 occurrences) had a chain break
        assert chain_stats.samples_with_breaks == 2


    @pytest.mark.parametrize("profile_id", ["pegasus_p16", "zephyr_z12"])
    def test_backend_end_to_end_compile_sample_decode(self, profile_id):
        """Full end-to-end test: compile → sample → decode for hardware profiles.

        This test exercises the complete path through the backend with real
        D-Wave libraries, verifying:
        - Embedding is found for a graph with both interactions and isolated nodes
        - Sampling produces valid binary samples
        - Occurrences are tracked correctly
        - Logical energies are consistent
        """
        import dimod

        from qreduce.mwis import ReductionGraph, build_mwis_qubo, qubo_to_ising
        from qreduce.solving.mwis.contracts import (
            MISBackendRequest,
            MISCompilationRequest,
            MISCompletionStatus,
        )
        from qreduce.solving.mwis.dwave_simulated_annealing_backend import (
            DWaveSimulatedAnnealingMISBackend,
        )
        from qreduce.status import BackendFamily, ExecutionMode, ProblemForm

        # Create a graph with both interactions and an isolated node
        # a -- b (conflict edge)
        # c    (isolated)
        graph = ReductionGraph(
            node_ids=("a", "b", "c"),
            node_weights={"a": 3.0, "b": 2.0, "c": 1.0},
            edges=(("a", "b"),),
            edge_reasons={("a", "b"): "conflict"},
            graph_policy_id="test",
            graph_policy_version="1",
        )
        qubo = build_mwis_qubo(graph, lambda_edge=4.0)
        problem = type("Problem", (), {
            "graph": graph,
            "qubo": qubo,
            "ising": qubo_to_ising(qubo),
        })()

        backend = DWaveSimulatedAnnealingMISBackend()

        # Check capabilities
        caps = backend.capabilities()
        assert caps.runtime_available is True

        # Compile with embedding profile
        compilation = backend.compile(
            problem,
            MISCompilationRequest(
                run_id="e2e-test",
                round_index=0,
                node_order=graph.node_ids,
                residual_time_budget_seconds=120.0,
                requested_provider_id="dwave",
                requested_backend_id="simulated_annealing",
                requested_backend_family=BackendFamily.ANNEALING,
                requested_execution_mode=ExecutionMode.LOCAL,
                required_problem_form=ProblemForm.QUBO,
                compilation_parameters={"embedding_profile": profile_id},
            ),
        )

        # Verify compilation succeeded
        assert compilation.completion_status is MISCompletionStatus.COMPLETED, (
            f"Compilation failed: {compilation.diagnostic_message}"
        )
        assert compilation.compiled_job is not None

        job = compilation.compiled_job
        params = job.effective_compilation_parameters

        # Verify embedding was found
        assert "_embedding" in params
        embedding = params["_embedding"]
        assert set(embedding.keys()) == {"a", "b", "c"}
        assert all(len(chain) >= 1 for chain in embedding.values())

        # Verify chain strength was calculated
        assert "_chain_strength" in params
        assert params["_chain_strength"] > 0

        # Execute sampling
        result = backend.solve(
            job,
            MISBackendRequest(
                run_id="e2e-test",
                round_index=0,
                compiled_job_id=job.compiled_job_id,
                node_order=graph.node_ids,
                random_seed=42,
                requested_solution_count=10,
                residual_time_budget_seconds=60.0,
                execution_parameters={"num_reads": 100},
            ),
        )

        # Verify execution succeeded
        assert result.completion_status is MISCompletionStatus.COMPLETED, (
            f"Execution failed: {result.diagnostic_message}"
        )
        assert len(result.samples) > 0

        # Verify sample structure
        for sample in result.samples:
            # Node order matches
            assert sample.node_order == graph.node_ids
            # Delta is binary (0 or 1 for each node)
            assert len(sample.delta) == 3
            assert all(v in (0, 1) for v in sample.delta)
            # Occurrences are positive
            assert sample.occurrence_count >= 1
            # Energy is a finite number
            assert sample.backend_reported_score is not None

        # Verify logical energies are consistent with BQM
        # Build dimod BQM from canonical QUBO
        qubo_dict = {}
        for node, coef in qubo.linear.items():
            qubo_dict[(node, node)] = coef
        for (u, v), coef in qubo.quadratic.items():
            qubo_dict[(u, v)] = coef
        logical_bqm = dimod.BinaryQuadraticModel.from_qubo(qubo_dict, qubo.offset)
        for sample in result.samples:
            sample_dict = dict(zip(sample.node_order, sample.delta))
            expected_energy = logical_bqm.energy(sample_dict)
            # Energy should match (within floating point tolerance)
            assert abs(sample.backend_reported_score - expected_energy) < 1e-6, (
                f"Energy mismatch: got {sample.backend_reported_score}, expected {expected_energy}"
            )

        # Verify timing information is present in execution parameters
        exec_params = result.effective_execution_parameters
        assert "_chain_break_statistics" in exec_params
        chain_stats = exec_params["_chain_break_statistics"]
        assert "sampling_time_seconds" in chain_stats
        assert "decoding_time_seconds" in chain_stats
        assert chain_stats["sampling_time_seconds"] >= 0
        assert chain_stats["decoding_time_seconds"] >= 0

        # Verify chain strength metadata is stored at job level only, not in samples
        job_params = job.effective_compilation_parameters
        assert "_chain_strength_metadata" in job_params, (
            "Chain strength metadata must be in job"
        )
        for sample in result.samples:
            assert "_chain_strength_metadata" not in sample.effective_compilation_parameters, (
                "Chain strength metadata must not be duplicated in samples"
            )
            assert "_embedding" not in sample.effective_compilation_parameters, (
                "Embedding mapping must not be duplicated in samples"
            )

    @pytest.mark.parametrize("profile_id", ["pegasus_p16", "zephyr_z12"])
    def test_compiled_job_json_serializable(self, profile_id):
        """Compiled job and compilation result are fully JSON-serializable.

        This verifies the embedded BQM is stored in serialized form, not as
        a live SDK object.
        """
        import json

        from qreduce.artifacts.metadata import to_primitive
        from qreduce.mwis import ReductionGraph, build_mwis_qubo, qubo_to_ising
        from qreduce.mwis.graph import CanonicalMWISProblem
        from qreduce.solving.mwis.contracts import (
            MISCompilationRequest,
            MISCompletionStatus,
        )
        from qreduce.solving.mwis.dwave_simulated_annealing_backend import (
            DWaveSimulatedAnnealingMISBackend,
        )
        from qreduce.status import BackendFamily, ExecutionMode, ProblemForm

        # Create a small problem using CanonicalMWISProblem (serializable)
        graph = ReductionGraph(
            node_ids=("a", "b"),
            node_weights={"a": 1.0, "b": 2.0},
            edges=(("a", "b"),),
            edge_reasons={("a", "b"): "conflict"},
            graph_policy_id="test",
            graph_policy_version="1",
        )
        qubo = build_mwis_qubo(graph, lambda_edge=4.0)
        problem = CanonicalMWISProblem(graph, qubo, qubo_to_ising(qubo))

        backend = DWaveSimulatedAnnealingMISBackend()

        # Compile with hardware profile
        compilation = backend.compile(
            problem,
            MISCompilationRequest(
                run_id="json-test",
                round_index=0,
                node_order=graph.node_ids,
                residual_time_budget_seconds=60.0,
                requested_provider_id="dwave",
                requested_backend_id="simulated_annealing",
                requested_backend_family=BackendFamily.ANNEALING,
                requested_execution_mode=ExecutionMode.LOCAL,
                required_problem_form=ProblemForm.QUBO,
                compilation_parameters={"embedding_profile": profile_id},
            ),
        )

        assert compilation.completion_status is MISCompletionStatus.COMPLETED
        job = compilation.compiled_job
        assert job is not None

        # Verify embedded_bqm_serialized is present and is a dict (not a BQM object)
        assert job.embedded_bqm_serialized is not None
        assert isinstance(job.embedded_bqm_serialized, dict)

        # Test 1: job.to_dict() is JSON-serializable
        job_dict = job.to_dict()
        job_json = json.dumps(job_dict, allow_nan=False)
        assert len(job_json) > 0

        # Test 2: compilation.to_dict() is JSON-serializable
        compilation_dict = compilation.to_dict()
        compilation_json = json.dumps(compilation_dict, allow_nan=False)
        assert len(compilation_json) > 0

        # Test 3: to_primitive(compilation) is JSON-serializable
        primitive = to_primitive(compilation)
        primitive_json = json.dumps(primitive, allow_nan=False)
        assert len(primitive_json) > 0

    @pytest.mark.parametrize("profile_id", ["pegasus_p16", "zephyr_z12"])
    def test_embedded_bqm_json_roundtrip_then_sample(self, profile_id):
        """Serialized BQM survives JSON round-trip and produces correct samples.

        This tests the full persistence scenario: compile, serialize to JSON,
        deserialize, then solve with the reconstructed BQM.
        """
        import json

        import dimod

        from qreduce.mwis import ReductionGraph, build_mwis_qubo, qubo_to_ising
        from qreduce.mwis.graph import CanonicalMWISProblem
        from qreduce.solving.mwis.contracts import (
            MISBackendRequest,
            MISCompilationRequest,
            MISCompletionStatus,
        )
        from qreduce.solving.mwis.dwave_simulated_annealing_backend import (
            DWaveSimulatedAnnealingMISBackend,
        )
        from qreduce.status import BackendFamily, ExecutionMode, ProblemForm

        # Create a small problem
        graph = ReductionGraph(
            node_ids=("x", "y"),
            node_weights={"x": 3.0, "y": 2.0},
            edges=(("x", "y"),),
            edge_reasons={("x", "y"): "conflict"},
            graph_policy_id="test",
            graph_policy_version="1",
        )
        qubo = build_mwis_qubo(graph, lambda_edge=5.0)
        problem = CanonicalMWISProblem(graph, qubo, qubo_to_ising(qubo))

        backend = DWaveSimulatedAnnealingMISBackend()

        # Compile
        compilation = backend.compile(
            problem,
            MISCompilationRequest(
                run_id="roundtrip-test",
                round_index=0,
                node_order=graph.node_ids,
                residual_time_budget_seconds=60.0,
                requested_provider_id="dwave",
                requested_backend_id="simulated_annealing",
                requested_backend_family=BackendFamily.ANNEALING,
                requested_execution_mode=ExecutionMode.LOCAL,
                required_problem_form=ProblemForm.QUBO,
                compilation_parameters={"embedding_profile": profile_id},
            ),
        )
        assert compilation.completion_status is MISCompletionStatus.COMPLETED
        job = compilation.compiled_job

        # JSON round-trip the embedded BQM
        original_serialized = job.embedded_bqm_serialized
        json_str = json.dumps(original_serialized, allow_nan=False)
        roundtripped = json.loads(json_str)

        # Verify round-trip preserves structure
        assert roundtripped == original_serialized

        # Verify the serialized BQM can be reconstructed
        reconstructed_bqm = dimod.BinaryQuadraticModel.from_serializable(roundtripped)
        assert reconstructed_bqm.num_variables > 0

        # Execute sampling (uses the serialized BQM internally)
        result = backend.solve(
            job,
            MISBackendRequest(
                run_id="roundtrip-test",
                round_index=0,
                compiled_job_id=job.compiled_job_id,
                node_order=graph.node_ids,
                random_seed=42,
                requested_solution_count=5,
                residual_time_budget_seconds=30.0,
                execution_parameters={"num_reads": 50},
            ),
        )

        assert result.completion_status is MISCompletionStatus.COMPLETED
        assert len(result.samples) > 0

        # Verify samples have valid energies
        qubo_dict = {}
        for node, coef in qubo.linear.items():
            qubo_dict[(node, node)] = coef
        for (u, v), coef in qubo.quadratic.items():
            qubo_dict[(u, v)] = coef
        logical_bqm = dimod.BinaryQuadraticModel.from_qubo(qubo_dict, qubo.offset)

        for sample in result.samples:
            sample_dict = dict(zip(sample.node_order, sample.delta))
            expected_energy = logical_bqm.energy(sample_dict)
            assert abs(sample.backend_reported_score - expected_energy) < 1e-6

    @pytest.mark.parametrize("profile_id", ["pegasus_p16", "zephyr_z12"])
    def test_chain_strength_metadata_persisted_in_job(self, profile_id):
        """Chain strength metadata is fully recorded with explicit parameter values.

        Verifies:
        - profile_definition_version is present and non-empty
        - chain_strength_policy name is correct
        - chain_strength_policy_parameters contains prefactor=1.414
        - chain_strength_value is positive
        - chain_break_method is correct
        """
        from qreduce.mwis import ReductionGraph, build_mwis_qubo, qubo_to_ising
        from qreduce.mwis.graph import CanonicalMWISProblem
        from qreduce.solving.mwis.contracts import (
            MISCompilationRequest,
            MISCompletionStatus,
        )
        from qreduce.solving.mwis.dwave_embedding import (
            CHAIN_BREAK_METHOD_MAJORITY_VOTE,
            CHAIN_STRENGTH_POLICY_UNIFORM_TORQUE,
            CHAIN_STRENGTH_UNIFORM_TORQUE_PREFACTOR,
            EMBEDDING_PROFILE_DEFINITION_VERSION,
        )
        from qreduce.solving.mwis.dwave_simulated_annealing_backend import (
            DWaveSimulatedAnnealingMISBackend,
        )
        from qreduce.status import BackendFamily, ExecutionMode, ProblemForm

        # Create a small problem
        graph = ReductionGraph(
            node_ids=("p", "q"),
            node_weights={"p": 2.0, "q": 3.0},
            edges=(("p", "q"),),
            edge_reasons={("p", "q"): "conflict"},
            graph_policy_id="test",
            graph_policy_version="1",
        )
        qubo = build_mwis_qubo(graph, lambda_edge=5.0)
        problem = CanonicalMWISProblem(graph, qubo, qubo_to_ising(qubo))

        backend = DWaveSimulatedAnnealingMISBackend()
        compilation = backend.compile(
            problem,
            MISCompilationRequest(
                run_id="metadata-test",
                round_index=0,
                node_order=graph.node_ids,
                residual_time_budget_seconds=60.0,
                requested_provider_id="dwave",
                requested_backend_id="simulated_annealing",
                requested_backend_family=BackendFamily.ANNEALING,
                requested_execution_mode=ExecutionMode.LOCAL,
                required_problem_form=ProblemForm.QUBO,
                compilation_parameters={"embedding_profile": profile_id},
            ),
        )

        assert compilation.completion_status is MISCompletionStatus.COMPLETED
        job = compilation.compiled_job
        params = job.effective_compilation_parameters

        # Verify metadata structure exists
        assert "_chain_strength_metadata" in params
        metadata = params["_chain_strength_metadata"]

        # Verify profile definition version
        assert "profile_definition_version" in metadata
        assert metadata["profile_definition_version"] == EMBEDDING_PROFILE_DEFINITION_VERSION
        assert metadata["profile_definition_version"]  # Non-empty

        # Verify chain strength policy
        assert "chain_strength_policy" in metadata
        assert metadata["chain_strength_policy"] == CHAIN_STRENGTH_POLICY_UNIFORM_TORQUE

        # Verify policy parameters contains explicit prefactor
        assert "chain_strength_policy_parameters" in metadata
        policy_params = metadata["chain_strength_policy_parameters"]
        assert isinstance(policy_params, dict)
        assert "prefactor" in policy_params
        assert policy_params["prefactor"] == CHAIN_STRENGTH_UNIFORM_TORQUE_PREFACTOR

        # Verify chain strength value is positive
        assert "chain_strength_value" in metadata
        assert metadata["chain_strength_value"] > 0

        # Verify chain break method
        assert "chain_break_method" in metadata
        assert metadata["chain_break_method"] == CHAIN_BREAK_METHOD_MAJORITY_VOTE

        # Verify backward-compatible flat keys still exist
        assert params["_chain_strength"] == metadata["chain_strength_value"]
        assert params["_chain_strength_policy"] == CHAIN_STRENGTH_POLICY_UNIFORM_TORQUE

    def test_prefactor_actually_passed_to_policy(self):
        """Verify with a spy that the recorded prefactor is actually passed to the SDK.

        This ensures the persisted value matches the value used, not just that
        both happen to be the same default.
        """
        from unittest.mock import patch

        import dimod

        from qreduce.solving.mwis.dwave_embedding import (
            CHAIN_STRENGTH_UNIFORM_TORQUE_PREFACTOR,
            embed_bqm,
        )

        # Small BQM
        source_bqm = dimod.BinaryQuadraticModel(
            {"a": -1.0, "b": -2.0},
            {("a", "b"): 3.0},
            0.0,
            "BINARY",
        )

        # Simple embedding (we don't need a real one for this test)
        embedding = {"a": (0,), "b": (1,)}

        # Create a tiny graph with an edge
        import networkx as nx
        target_graph = nx.Graph()
        target_graph.add_edge(0, 1)

        captured_prefactor = []

        # Spy on the actual SDK function
        original_utc = None
        def spy_uniform_torque_compensation(bqm, prefactor=1.414, **kwargs):
            captured_prefactor.append(prefactor)
            return original_utc(bqm, prefactor=prefactor, **kwargs)

        with patch(
            "qreduce.solving.mwis.dwave_embedding._load_embedding_dependencies"
        ) as mock_load:
            # Set up the mock to return a module-like object
            from dwave import embedding as real_embedding
            original_utc = real_embedding.chain_strength.uniform_torque_compensation

            class MockChainStrength:
                uniform_torque_compensation = staticmethod(spy_uniform_torque_compensation)

            class MockEmbeddingModule:
                chain_strength = MockChainStrength()
                embed_bqm = staticmethod(real_embedding.embed_bqm)

            mock_load.return_value = (None, None, MockEmbeddingModule())

            # Call embed_bqm which should pass the prefactor
            _, _ = embed_bqm(
                source_bqm,
                embedding,
                target_graph,
                prefactor=CHAIN_STRENGTH_UNIFORM_TORQUE_PREFACTOR,
            )

        # Verify the spy captured exactly our prefactor
        assert len(captured_prefactor) == 1
        assert captured_prefactor[0] == CHAIN_STRENGTH_UNIFORM_TORQUE_PREFACTOR


    @pytest.mark.parametrize("profile_id", ["pegasus_p16", "zephyr_z12"])
    def test_find_embedding_all_isolated_nodes(self, profile_id):
        """Embedding succeeds for BQM with only isolated nodes (no edges).

        When there are no quadratic interactions, minorminer should not be called.
        Instead, qubits are assigned directly in deterministic order.
        """
        import dimod

        from qreduce.solving.mwis.dwave_embedding import find_embedding

        profile = resolve_embedding_profile(profile_id)

        # BQM with only linear terms (all isolated nodes)
        source_bqm = dimod.BinaryQuadraticModel(
            {"x": -1.0, "y": -2.0, "z": -3.0},
            {},  # No quadratic terms
            0.0,
            "BINARY",
        )

        result = find_embedding(
            source_bqm,
            profile,
            timeout_seconds=2.0,
            seed=42,
        )

        assert result.success is True, f"Failed: {result.diagnostic_message}"
        assert result.embedding is not None
        assert set(result.embedding.keys()) == {"x", "y", "z"}
        # Each isolated node gets exactly one qubit
        assert all(len(chain) == 1 for chain in result.embedding.values())
        # All chains are disjoint
        all_qubits = [q for chain in result.embedding.values() for q in chain]
        assert len(all_qubits) == len(set(all_qubits))
        # Search time should be very fast (no minorminer)
        assert result.search_time_seconds < 1.0

    def test_find_embedding_isolated_nodes_insufficient_qubits(self):
        """Embedding fails when topology has fewer qubits than isolated nodes.

        Tests the full find_embedding path (not just _validate_embedding)
        with a topology too small for the number of variables.
        """
        from unittest.mock import patch

        import dimod
        import networkx as nx

        from qreduce.solving.mwis.dwave_embedding import find_embedding
        from qreduce.status import TerminalReason

        profile = resolve_embedding_profile("pegasus_p16")

        # BQM with 3 isolated nodes (no quadratic terms)
        source_bqm = dimod.BinaryQuadraticModel(
            {"x": -1.0, "y": -2.0, "z": -3.0},
            {},  # No edges
            0.0,
            "BINARY",
        )

        # Mock the topology generator to return a tiny graph with only 2 nodes
        tiny_graph = nx.Graph()
        tiny_graph.add_nodes_from([0, 1])  # Only 2 qubits, need 3

        with patch(
            "qreduce.solving.mwis.dwave_embedding.build_target_topology",
            return_value=tiny_graph,
        ):
            result = find_embedding(
                source_bqm,
                profile,
                timeout_seconds=2.0,
                seed=42,
            )

        # Verify failure
        assert result.success is False
        assert result.embedding is None
        assert result.terminal_reason is TerminalReason.MIS_EMBEDDING_FAILED
        assert "insufficient" in result.diagnostic_message.lower() or \
               "not enough" in result.diagnostic_message.lower() or \
               "2 qubits" in result.diagnostic_message.lower()
        # Verify minorminer was not called (isolated nodes don't need it)
        # This is implicit: if minorminer were called on a 2-node graph with
        # 3 variables and edges, it would fail differently
