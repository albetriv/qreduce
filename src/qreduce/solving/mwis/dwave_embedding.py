"""Local D-Wave embedding utilities for Pegasus and Zephyr topologies.

This module provides utilities for minor-embedding BQM problems onto
hardware-like graph topologies without requiring a real QPU or credentials.
All operations are local and deterministic given a seed.

Supported profiles:
- none: No embedding, direct logical BQM sampling (default)
- pegasus_p16: Ideal Pegasus graph with size parameter m=16
- zephyr_z12: Ideal Zephyr graph with size parameter m=12

The embedding models connectivity constraints and chain overhead, not quantum
dynamics or actual QPU timing. These are classical samplers constrained to
hardware-like topologies, not quantum simulations.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from importlib import import_module as _import_module
from time import perf_counter
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from qreduce.artifacts.metadata import redact_metadata, to_primitive
from qreduce.status import TerminalReason

if TYPE_CHECKING:
    import networkx as nx


# Valid embedding profile values
EMBEDDING_PROFILE_NONE = "none"
EMBEDDING_PROFILE_PEGASUS_P16 = "pegasus_p16"
EMBEDDING_PROFILE_ZEPHYR_Z12 = "zephyr_z12"

VALID_EMBEDDING_PROFILES = frozenset({
    EMBEDDING_PROFILE_NONE,
    EMBEDDING_PROFILE_PEGASUS_P16,
    EMBEDDING_PROFILE_ZEPHYR_Z12,
})

# Profile definition version - increment when profile semantics change
EMBEDDING_PROFILE_DEFINITION_VERSION = "1.0"

# Default timeout for embedding search (seconds)
DEFAULT_EMBEDDING_TIMEOUT_SECONDS = 60.0

# Topology size parameters
PEGASUS_P16_SIZE = 16
ZEPHYR_Z12_SIZE = 12

# Chain strength policy constants
CHAIN_STRENGTH_POLICY_UNIFORM_TORQUE = "uniform_torque_compensation"
# Prefactor for uniform_torque_compensation (sqrt(2), matching dwave.embedding default)
CHAIN_STRENGTH_UNIFORM_TORQUE_PREFACTOR = 1.414

# Chain break resolution method constants
CHAIN_BREAK_METHOD_MAJORITY_VOTE = "majority_vote"


@dataclass(frozen=True, slots=True)
class EmbeddingProfile:
    """Resolved embedding profile configuration."""

    profile_id: str
    topology_type: str | None = None
    topology_size: int | None = None
    is_embedding_enabled: bool = False

    def __post_init__(self) -> None:
        """Validate profile configuration."""
        if self.profile_id not in VALID_EMBEDDING_PROFILES:
            raise ValueError(f"Invalid embedding profile: {self.profile_id!r}")
        if self.profile_id == EMBEDDING_PROFILE_NONE:
            if self.is_embedding_enabled:
                raise ValueError("Embedding must be disabled for profile 'none'")
        else:
            if not self.is_embedding_enabled:
                raise ValueError(f"Embedding must be enabled for profile {self.profile_id!r}")

    def to_dict(self) -> dict[str, object]:
        """Return a serialization-ready representation."""
        return redact_metadata(to_primitive(self))  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class EmbeddingSearchResult:
    """Result of an embedding search operation."""

    success: bool
    embedding: Mapping[str, tuple[int, ...]] | None
    profile: EmbeddingProfile
    topology_node_count: int | None = None
    topology_edge_count: int | None = None
    source_node_count: int = 0
    source_edge_count: int = 0
    embedded_qubit_count: int | None = None
    chain_lengths: tuple[int, ...] = ()
    mean_chain_length: float | None = None
    max_chain_length: int | None = None
    search_time_seconds: float = 0.0
    search_timeout_seconds: float | None = None
    seed_used: int | None = None
    terminal_reason: TerminalReason | None = None
    diagnostic_message: str | None = None
    library_versions: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Freeze mutable fields."""
        if self.embedding is not None:
            object.__setattr__(
                self, "embedding", MappingProxyType(dict(self.embedding))
            )
        object.__setattr__(self, "chain_lengths", tuple(self.chain_lengths))
        object.__setattr__(
            self, "library_versions", MappingProxyType(dict(self.library_versions))
        )

    def to_dict(self) -> dict[str, object]:
        """Return a serialization-ready representation."""
        return redact_metadata(to_primitive(self))  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class ChainBreakStatistics:
    """Statistics about chain breaks during decoding."""

    total_samples: int
    samples_with_breaks: int
    total_chain_count: int
    broken_chain_count: int
    broken_chain_fraction: float
    mean_break_fraction_per_sample: float

    def to_dict(self) -> dict[str, object]:
        """Return a serialization-ready representation."""
        return redact_metadata(to_primitive(self))  # type: ignore[return-value]


def resolve_embedding_profile(profile_id: str | None) -> EmbeddingProfile:
    """Resolve an embedding profile ID to a complete profile configuration.

    Args:
        profile_id: Profile identifier, one of 'none', 'pegasus_p16', 'zephyr_z12'.
            If None, defaults to 'none'.

    Returns:
        Resolved EmbeddingProfile with topology details.

    Raises:
        ValueError: If profile_id is not one of the valid profiles.
    """
    if profile_id is None:
        profile_id = EMBEDDING_PROFILE_NONE

    if profile_id == EMBEDDING_PROFILE_NONE:
        return EmbeddingProfile(
            profile_id=EMBEDDING_PROFILE_NONE,
            is_embedding_enabled=False,
        )
    if profile_id == EMBEDDING_PROFILE_PEGASUS_P16:
        return EmbeddingProfile(
            profile_id=EMBEDDING_PROFILE_PEGASUS_P16,
            topology_type="pegasus",
            topology_size=PEGASUS_P16_SIZE,
            is_embedding_enabled=True,
        )
    if profile_id == EMBEDDING_PROFILE_ZEPHYR_Z12:
        return EmbeddingProfile(
            profile_id=EMBEDDING_PROFILE_ZEPHYR_Z12,
            topology_type="zephyr",
            topology_size=ZEPHYR_Z12_SIZE,
            is_embedding_enabled=True,
        )
    raise ValueError(
        f"Invalid embedding profile: {profile_id!r}. "
        f"Valid profiles: {', '.join(sorted(VALID_EMBEDDING_PROFILES))}"
    )


def validate_embedding_profile_for_backend(
    profile_id: str | None,
    backend_id: str,
    reduction_enabled: bool,
) -> tuple[bool, str | None]:
    """Validate that an embedding profile is compatible with the backend.

    Args:
        profile_id: Embedding profile ID or None.
        backend_id: Backend ID (e.g., 'simulated_annealing').
        reduction_enabled: Whether reduction is enabled (max_rounds > 0).

    Returns:
        Tuple of (is_valid, error_message). error_message is None if valid.
    """
    if profile_id is None or profile_id == EMBEDDING_PROFILE_NONE:
        return True, None

    if backend_id != "simulated_annealing":
        return False, (
            f"Embedding profile '{profile_id}' requires backend 'simulated_annealing', "
            f"got '{backend_id}'."
        )

    if not reduction_enabled:
        return False, (
            f"Embedding profile '{profile_id}' requires reduction to be enabled "
            "(max_reduction_rounds > 0)."
        )

    return True, None


def _load_embedding_dependencies() -> tuple[Any, Any, Any]:
    """Lazily load embedding dependencies.

    Returns:
        Tuple of (dwave_graphs_module, minorminer_module, dwave_embedding_module).

    Raises:
        ImportError: If required packages are not installed.
    """
    try:
        dwave_graphs = _import_module("dwave.system.composites")
        # dwave.system includes the embedding utilities
        dwave_embedding = _import_module("dwave.embedding")
        minorminer = _import_module("minorminer")
    except ImportError as error:
        raise ImportError(
            "Embedding profiles require the optional 'dwave-embedding' dependency group. "
            "Install with: poetry install --with dwave-embedding"
        ) from error
    return dwave_graphs, minorminer, dwave_embedding


def _load_topology_generator() -> Any:
    """Load the topology graph generator module.

    Returns:
        The dwave.graphs module containing pegasus_graph and zephyr_graph.

    Raises:
        ImportError: If dwave-system is not installed.
    """
    try:
        # Topology generators are in dwave.graphs (part of dwave-system)
        return _import_module("dwave.graphs")
    except ImportError as error:
        raise ImportError(
            "Topology generation requires the optional 'dwave-embedding' dependency group. "
            "Install with: poetry install --with dwave-embedding"
        ) from error


def _get_library_versions() -> dict[str, str]:
    """Get versions of embedding-related libraries.

    Returns:
        Dictionary mapping library names to version strings.
    """
    versions: dict[str, str] = {}
    for lib_name in ("dwave_system", "minorminer", "dimod"):
        try:
            lib = _import_module(lib_name.replace("_", "."))
            versions[lib_name] = getattr(lib, "__version__", "unknown")
        except ImportError:
            pass
    return versions


def build_target_topology(profile: EmbeddingProfile) -> "nx.Graph":
    """Build the target topology graph for embedding.

    Args:
        profile: Resolved embedding profile.

    Returns:
        NetworkX graph representing the target topology.

    Raises:
        ValueError: If profile does not support embedding.
        ImportError: If required packages are not installed.
    """
    if not profile.is_embedding_enabled:
        raise ValueError("Cannot build topology for non-embedding profile 'none'")

    dwave_graphs = _load_topology_generator()

    if profile.topology_type == "pegasus":
        return dwave_graphs.pegasus_graph(profile.topology_size)
    if profile.topology_type == "zephyr":
        return dwave_graphs.zephyr_graph(profile.topology_size)

    raise ValueError(f"Unknown topology type: {profile.topology_type}")


def _validate_embedding(
    embedding: Mapping[Any, Any],
    source_variables: frozenset[Any],
    source_edges: frozenset[tuple[Any, Any]],
    target_graph: "nx.Graph",
) -> tuple[bool, str | None]:
    """Validate embedding against all required conditions.

    Conditions checked:
    1. Keys match source variables exactly
    2. Each chain contains at least one qubit
    3. All qubits exist in the target topology
    4. No chain contains duplicate qubits
    5. Chains for different variables are disjoint
    6. Each chain forms a connected subgraph
    7. Each quadratic interaction has at least one physical edge between chains

    Args:
        embedding: Mapping from logical variables to qubit chains.
        source_variables: Set of all logical variable names.
        source_edges: Set of (u, v) pairs for quadratic interactions.
        target_graph: NetworkX graph of target topology.

    Returns:
        Tuple of (is_valid, error_message). If valid, error_message is None.
    """
    # 1. Keys match source variables exactly
    embedding_keys = set(embedding.keys())
    if embedding_keys != source_variables:
        missing = source_variables - embedding_keys
        extra = embedding_keys - source_variables
        parts = []
        if missing:
            parts.append(f"missing={sorted(missing)}")
        if extra:
            parts.append(f"extra={sorted(extra)}")
        return False, f"Embedding keys do not match source variables: {'; '.join(parts)}"

    all_qubits_used: set[Any] = set()
    target_nodes = set(target_graph.nodes())

    for var, chain in embedding.items():
        chain_set = set(chain)

        # 2. Each chain contains at least one qubit
        if len(chain) == 0:
            return False, f"Variable {var!r} has empty chain"

        # 3. All qubits exist in target topology
        invalid_qubits = chain_set - target_nodes
        if invalid_qubits:
            return False, f"Variable {var!r} uses qubits not in topology: {sorted(invalid_qubits)}"

        # 4. No chain contains duplicate qubits
        if len(chain) != len(chain_set):
            return False, f"Variable {var!r} has duplicate qubits in chain"

        # 5. Chains are disjoint
        overlap = chain_set & all_qubits_used
        if overlap:
            return False, f"Variable {var!r} shares qubits with another chain: {sorted(overlap)}"
        all_qubits_used.update(chain_set)

        # 6. Each chain forms a connected subgraph
        if len(chain) > 1:
            # Build induced subgraph and check connectivity
            chain_edges = [
                (q1, q2) for q1 in chain_set for q2 in chain_set
                if q1 < q2 and target_graph.has_edge(q1, q2)
            ]
            # Use simple BFS to check connectivity
            if not _is_chain_connected(chain_set, chain_edges):
                return False, f"Variable {var!r} has disconnected chain"

    # 7. Each quadratic interaction has at least one physical edge
    for u, v in source_edges:
        if u not in embedding or v not in embedding:
            # This should be caught by condition 1, but defensive check
            continue
        chain_u = set(embedding[u])
        chain_v = set(embedding[v])
        # Check if any qubit in chain_u is connected to any qubit in chain_v
        has_edge = any(
            target_graph.has_edge(qu, qv)
            for qu in chain_u
            for qv in chain_v
        )
        if not has_edge:
            return False, f"Interaction ({u!r}, {v!r}) has no physical edge between chains"

    return True, None


def _is_chain_connected(qubits: set[Any], edges: list[tuple[Any, Any]]) -> bool:
    """Check if qubits form a connected subgraph given the edges."""
    if len(qubits) <= 1:
        return True

    # Build adjacency for the subgraph
    adj: dict[Any, set[Any]] = {q: set() for q in qubits}
    for q1, q2 in edges:
        adj[q1].add(q2)
        adj[q2].add(q1)

    # BFS from arbitrary start
    start = next(iter(qubits))
    visited: set[Any] = {start}
    queue = [start]
    while queue:
        node = queue.pop(0)
        for neighbor in adj[node]:
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append(neighbor)

    return visited == qubits


def find_embedding(
    source_bqm: Any,
    profile: EmbeddingProfile,
    *,
    seed: int | None = None,
    timeout_seconds: float | None = None,
    deadline: float | None = None,
) -> EmbeddingSearchResult:
    """Find an embedding of a BQM onto the target topology.

    Args:
        source_bqm: The dimod BinaryQuadraticModel to embed.
        profile: Resolved embedding profile.
        seed: Random seed for reproducibility.
        timeout_seconds: Maximum search time (default: 60s). Ignored if deadline is set.
        deadline: Absolute monotonic deadline (from perf_counter). If set, the
            remaining budget is recalculated before each expensive operation.

    Returns:
        EmbeddingSearchResult with the embedding or failure information.
    """
    if not profile.is_embedding_enabled:
        return EmbeddingSearchResult(
            success=True,
            embedding=None,
            profile=profile,
            diagnostic_message="Embedding disabled for profile 'none'",
        )

    started_at = perf_counter()

    # Helper to calculate remaining budget from deadline
    def remaining_budget() -> float:
        if deadline is None:
            return float("inf")
        return deadline - perf_counter()

    # Check budget at entry
    if deadline is not None and remaining_budget() <= 0:
        return EmbeddingSearchResult(
            success=False,
            embedding=None,
            profile=profile,
            search_time_seconds=perf_counter() - started_at,
            terminal_reason=TerminalReason.MIS_COMPILATION_FAILED,
            diagnostic_message="Embedding search skipped: compilation time budget exhausted.",
        )

    # Legacy timeout_seconds support (when deadline is not provided)
    if deadline is None and timeout_seconds is not None and timeout_seconds <= 0:
        return EmbeddingSearchResult(
            success=False,
            embedding=None,
            profile=profile,
            search_time_seconds=perf_counter() - started_at,
            terminal_reason=TerminalReason.MIS_COMPILATION_FAILED,
            diagnostic_message="Embedding search skipped: compilation time budget exhausted.",
        )

    # Calculate effective timeout based on deadline or legacy timeout_seconds
    def calculate_effective_timeout() -> float:
        """Calculate timeout for minorminer, rechecking deadline if set."""
        if deadline is not None:
            remaining = remaining_budget()
            if remaining <= 0:
                return 0.0
            return min(DEFAULT_EMBEDDING_TIMEOUT_SECONDS, remaining)
        else:
            base = timeout_seconds if timeout_seconds is not None else DEFAULT_EMBEDDING_TIMEOUT_SECONDS
            return base

    # Load dependencies
    try:
        _, minorminer_module, _ = _load_embedding_dependencies()
    except ImportError as error:
        return EmbeddingSearchResult(
            success=False,
            embedding=None,
            profile=profile,
            search_time_seconds=perf_counter() - started_at,
            terminal_reason=TerminalReason.MIS_SDK_DEPENDENCY_UNAVAILABLE,
            diagnostic_message=str(error),
        )

    # Check budget after loading dependencies
    if deadline is not None and remaining_budget() <= 0:
        return EmbeddingSearchResult(
            success=False,
            embedding=None,
            profile=profile,
            search_time_seconds=perf_counter() - started_at,
            terminal_reason=TerminalReason.MIS_COMPILATION_FAILED,
            diagnostic_message="Compilation time budget exhausted after loading dependencies.",
        )

    # Build target topology
    try:
        target_graph = build_target_topology(profile)
    except Exception as error:  # noqa: BLE001
        return EmbeddingSearchResult(
            success=False,
            embedding=None,
            profile=profile,
            search_time_seconds=perf_counter() - started_at,
            terminal_reason=TerminalReason.MIS_EMBEDDING_FAILED,
            diagnostic_message=f"Failed to build target topology: {error}",
        )

    # Check budget after building topology
    if deadline is not None and remaining_budget() <= 0:
        return EmbeddingSearchResult(
            success=False,
            embedding=None,
            profile=profile,
            topology_node_count=target_graph.number_of_nodes(),
            topology_edge_count=target_graph.number_of_edges(),
            search_time_seconds=perf_counter() - started_at,
            terminal_reason=TerminalReason.MIS_COMPILATION_FAILED,
            diagnostic_message="Compilation time budget exhausted after building topology.",
        )

    # Extract source graph structure from BQM
    source_nodes = list(source_bqm.variables)
    source_edges = list(source_bqm.quadratic.keys())
    source_node_count = len(source_nodes)
    source_edge_count = len(source_edges)

    # Special case: all nodes are isolated (no edges)
    # Don't call minorminer - assign qubits directly in deterministic order
    if source_edge_count == 0:
        # Get available qubits in deterministic order
        available_qubits = sorted(target_graph.nodes())

        if len(available_qubits) < source_node_count:
            return EmbeddingSearchResult(
                success=False,
                embedding=None,
                profile=profile,
                topology_node_count=target_graph.number_of_nodes(),
                topology_edge_count=target_graph.number_of_edges(),
                source_node_count=source_node_count,
                source_edge_count=source_edge_count,
                search_time_seconds=perf_counter() - started_at,
                search_timeout_seconds=None,  # No minorminer for isolated nodes
                seed_used=seed,
                terminal_reason=TerminalReason.MIS_EMBEDDING_FAILED,
                diagnostic_message=(
                    f"Insufficient qubits for {source_node_count} isolated nodes: "
                    f"topology has {len(available_qubits)} qubits."
                ),
                library_versions=_get_library_versions(),
            )

        # Assign one qubit per node in canonical order
        embedding: dict[Any, list[Any]] = {}
        for i, node in enumerate(sorted(source_nodes)):
            embedding[node] = [available_qubits[i]]

        # Skip to validation (no minorminer search needed)
        search_time = perf_counter() - started_at

        # Convert to frozen format and validate
        frozen_embedding: dict[str, tuple[int, ...]] = {
            str(k): tuple(v) for k, v in embedding.items()
        }

        # Full validation (conditions 1-5 apply; 6-7 trivially satisfied for isolated nodes)
        is_valid, error_message = _validate_embedding(
            frozen_embedding,
            frozenset(source_nodes),
            frozenset(),  # No edges
            target_graph,
        )
        if not is_valid:
            return EmbeddingSearchResult(
                success=False,
                embedding=None,
                profile=profile,
                topology_node_count=target_graph.number_of_nodes(),
                topology_edge_count=target_graph.number_of_edges(),
                source_node_count=source_node_count,
                source_edge_count=source_edge_count,
                search_time_seconds=search_time,
                search_timeout_seconds=None,  # No minorminer for isolated nodes
                seed_used=seed,
                terminal_reason=TerminalReason.MIS_EMBEDDING_FAILED,
                diagnostic_message=f"Embedding validation failed: {error_message}",
                library_versions=_get_library_versions(),
            )

        # Compute chain statistics (all chains have length 1 for isolated nodes)
        chain_lengths = tuple(1 for _ in frozen_embedding)
        embedded_qubit_count = len(frozen_embedding)

        return EmbeddingSearchResult(
            success=True,
            embedding=frozen_embedding,
            profile=profile,
            topology_node_count=target_graph.number_of_nodes(),
            topology_edge_count=target_graph.number_of_edges(),
            source_node_count=source_node_count,
            source_edge_count=source_edge_count,
            embedded_qubit_count=embedded_qubit_count,
            chain_lengths=chain_lengths,
            mean_chain_length=1.0,
            max_chain_length=1,
            search_time_seconds=search_time,
            search_timeout_seconds=None,  # No minorminer timeout for isolated nodes
            seed_used=seed,
            library_versions=_get_library_versions(),
        )

    # Calculate effective timeout immediately before minorminer
    # This accounts for time spent in preparation (imports, topology building)
    effective_timeout = calculate_effective_timeout()
    if effective_timeout <= 0:
        return EmbeddingSearchResult(
            success=False,
            embedding=None,
            profile=profile,
            topology_node_count=target_graph.number_of_nodes(),
            topology_edge_count=target_graph.number_of_edges(),
            source_node_count=source_node_count,
            source_edge_count=source_edge_count,
            search_time_seconds=perf_counter() - started_at,
            search_timeout_seconds=0.0,
            seed_used=seed,
            terminal_reason=TerminalReason.MIS_COMPILATION_FAILED,
            diagnostic_message="Compilation time budget exhausted before embedding search.",
            library_versions=_get_library_versions(),
        )

    # Search for embedding using minorminer
    # minorminer.find_embedding expects S as iterable of (node, node) pairs
    try:
        embedding = minorminer_module.find_embedding(
            source_edges,  # List of (u, v) edge tuples
            target_graph,
            random_seed=seed,
            timeout=effective_timeout,
        )
    except Exception as error:  # noqa: BLE001
        return EmbeddingSearchResult(
            success=False,
            embedding=None,
            profile=profile,
            topology_node_count=target_graph.number_of_nodes(),
            topology_edge_count=target_graph.number_of_edges(),
            source_node_count=source_node_count,
            source_edge_count=source_edge_count,
            search_time_seconds=perf_counter() - started_at,
            search_timeout_seconds=effective_timeout,
            seed_used=seed,
            terminal_reason=TerminalReason.MIS_EMBEDDING_FAILED,
            diagnostic_message=f"Embedding search failed: {error}",
            library_versions=_get_library_versions(),
        )

    search_time = perf_counter() - started_at

    # Check if embedding was found
    if not embedding:
        return EmbeddingSearchResult(
            success=False,
            embedding=None,
            profile=profile,
            topology_node_count=target_graph.number_of_nodes(),
            topology_edge_count=target_graph.number_of_edges(),
            source_node_count=source_node_count,
            source_edge_count=source_edge_count,
            search_time_seconds=search_time,
            search_timeout_seconds=effective_timeout,
            seed_used=seed,
            terminal_reason=TerminalReason.MIS_EMBEDDING_FAILED,
            diagnostic_message=(
                f"No embedding found within {effective_timeout:.1f}s budget. "
                f"Source has {source_node_count} nodes and {source_edge_count} edges."
            ),
            library_versions=_get_library_versions(),
        )

    # Identify isolated nodes (no quadratic interactions)
    nodes_with_interactions: set[Any] = set()
    for u, v in source_edges:
        nodes_with_interactions.add(u)
        nodes_with_interactions.add(v)
    isolated_nodes = set(source_nodes) - nodes_with_interactions

    # Handle missing nodes: only isolated nodes can be auto-completed
    embedded_nodes = set(embedding.keys())
    missing_nodes = set(source_nodes) - embedded_nodes

    # Non-isolated missing nodes are a fatal error
    missing_non_isolated = missing_nodes - isolated_nodes
    if missing_non_isolated:
        return EmbeddingSearchResult(
            success=False,
            embedding=None,
            profile=profile,
            topology_node_count=target_graph.number_of_nodes(),
            topology_edge_count=target_graph.number_of_edges(),
            source_node_count=source_node_count,
            source_edge_count=source_edge_count,
            search_time_seconds=search_time,
            search_timeout_seconds=effective_timeout,
            seed_used=seed,
            terminal_reason=TerminalReason.MIS_EMBEDDING_FAILED,
            diagnostic_message=(
                f"Embedding missing non-isolated variable(s): {sorted(missing_non_isolated)}. "
                "These have quadratic interactions and cannot be auto-completed."
            ),
            library_versions=_get_library_versions(),
        )

    # Auto-complete isolated missing nodes using deterministic qubit assignment
    missing_isolated = missing_nodes & isolated_nodes
    if missing_isolated:
        # Collect used qubits
        used_qubits: set[Any] = set()
        for chain in embedding.values():
            used_qubits.update(chain)

        # Get available qubits in deterministic order
        available_qubits = sorted(set(target_graph.nodes()) - used_qubits)

        # Assign to missing isolated nodes in canonical variable order
        for node in sorted(missing_isolated):
            if not available_qubits:
                return EmbeddingSearchResult(
                    success=False,
                    embedding=None,
                    profile=profile,
                    topology_node_count=target_graph.number_of_nodes(),
                    topology_edge_count=target_graph.number_of_edges(),
                    source_node_count=source_node_count,
                    source_edge_count=source_edge_count,
                    search_time_seconds=search_time,
                    search_timeout_seconds=effective_timeout,
                    seed_used=seed,
                    terminal_reason=TerminalReason.MIS_EMBEDDING_FAILED,
                    diagnostic_message=(
                        f"Cannot embed isolated node {node!r}: no available qubits."
                    ),
                    library_versions=_get_library_versions(),
                )
            # Use first available qubit (deterministic)
            embedding[node] = [available_qubits.pop(0)]

    # Full validation of embedding against all 7 conditions
    source_edges_set = frozenset(source_edges)
    is_valid, error_message = _validate_embedding(
        embedding,
        frozenset(source_nodes),
        source_edges_set,
        target_graph,
    )
    if not is_valid:
        return EmbeddingSearchResult(
            success=False,
            embedding=None,
            profile=profile,
            topology_node_count=target_graph.number_of_nodes(),
            topology_edge_count=target_graph.number_of_edges(),
            source_node_count=source_node_count,
            source_edge_count=source_edge_count,
            search_time_seconds=search_time,
            search_timeout_seconds=effective_timeout,
            seed_used=seed,
            terminal_reason=TerminalReason.MIS_EMBEDDING_FAILED,
            diagnostic_message=f"Embedding validation failed: {error_message}",
            library_versions=_get_library_versions(),
        )

    # Convert embedding to frozen format
    frozen_embedding: dict[str, tuple[int, ...]] = {
        str(k): tuple(v) for k, v in embedding.items()
    }

    # Compute chain statistics
    chain_lengths = tuple(len(chain) for chain in frozen_embedding.values())
    embedded_qubit_count = sum(chain_lengths)
    mean_chain_length = sum(chain_lengths) / len(chain_lengths) if chain_lengths else 0.0
    max_chain_length = max(chain_lengths) if chain_lengths else 0

    return EmbeddingSearchResult(
        success=True,
        embedding=frozen_embedding,
        profile=profile,
        topology_node_count=target_graph.number_of_nodes(),
        topology_edge_count=target_graph.number_of_edges(),
        source_node_count=source_node_count,
        source_edge_count=source_edge_count,
        embedded_qubit_count=embedded_qubit_count,
        chain_lengths=chain_lengths,
        mean_chain_length=mean_chain_length,
        max_chain_length=max_chain_length,
        search_time_seconds=search_time,
        search_timeout_seconds=effective_timeout,
        seed_used=seed,
        library_versions=_get_library_versions(),
    )


def embed_bqm(
    source_bqm: Any,
    embedding: Mapping[str, tuple[int, ...]],
    target_graph: "nx.Graph",
    *,
    chain_strength: float | None = None,
    prefactor: float = CHAIN_STRENGTH_UNIFORM_TORQUE_PREFACTOR,
) -> tuple[Any, float]:
    """Embed a BQM onto the target topology using the given embedding.

    Args:
        source_bqm: The dimod BinaryQuadraticModel to embed.
        embedding: Mapping from logical variables to physical qubit chains.
        target_graph: The target topology graph.
        chain_strength: Strength of chain couplings. If None, uses automatic selection
            via uniform_torque_compensation with the given prefactor.
        prefactor: Prefactor for uniform_torque_compensation policy (default: 1.414).
            Only used when chain_strength is None.

    Returns:
        Tuple of (embedded_bqm, effective_chain_strength).

    Raises:
        ImportError: If required packages are not installed.
    """
    _, _, embedding_module = _load_embedding_dependencies()

    # Use uniform_torque_compensation for automatic chain strength
    # Pass prefactor explicitly to avoid implicit dependency on SDK defaults
    if chain_strength is None:
        chain_strength = embedding_module.chain_strength.uniform_torque_compensation(
            source_bqm,
            prefactor=prefactor,
        )
        # Handle edge case of empty or trivial BQM
        if chain_strength == 0:
            # Use a small positive value for degenerate cases
            chain_strength = 1.0

    # Embed the BQM
    embedded_bqm = embedding_module.embed_bqm(
        source_bqm,
        embedding,
        target_graph,
        chain_strength=chain_strength,
    )

    return embedded_bqm, chain_strength


def unembed_sampleset(
    embedded_sampleset: Any,
    embedding: Mapping[str, tuple[int, ...]],
    source_bqm: Any,
    *,
    chain_break_method: str = "majority_vote",
) -> tuple[Any, ChainBreakStatistics]:
    """Decode embedded samples back to logical variables.

    Args:
        embedded_sampleset: SampleSet with physical qubit samples.
        embedding: Mapping from logical variables to physical qubit chains.
        source_bqm: Original logical BQM for energy recomputation.
        chain_break_method: Method for resolving broken chains ('majority_vote').

    Returns:
        Tuple of (logical_sampleset, chain_break_statistics).

    Raises:
        ImportError: If required packages are not installed.
        ValueError: If chain_break_method is not supported.
    """
    if chain_break_method != "majority_vote":
        raise ValueError(
            f"Unsupported chain_break_method: {chain_break_method!r}. "
            "Only 'majority_vote' is currently supported."
        )

    _, _, embedding_module = _load_embedding_dependencies()

    # Resolve the chain break method to the actual function
    # Ocean requires the function object, not a string
    chain_break_fn = embedding_module.chain_breaks.majority_vote

    # Unembed using majority_vote function
    logical_sampleset = embedding_module.unembed_sampleset(
        embedded_sampleset,
        embedding,
        source_bqm,
        chain_break_method=chain_break_fn,
    )

    # Compute chain break statistics from the embedded sampleset
    # IMPORTANT: Weight statistics by num_occurrences, not just unique rows
    total_weighted_samples = 0
    weighted_samples_with_breaks = 0
    total_weighted_chain_count = 0
    weighted_broken_chain_count = 0
    break_fractions_per_sample: list[float] = []

    # Check for chain breaks in each sample, weighted by occurrences
    for record in embedded_sampleset.data(fields=["sample", "num_occurrences"]):
        sample = record.sample
        occurrences = int(record.num_occurrences)
        total_weighted_samples += occurrences

        sample_broken_chains = 0
        sample_total_chains = 0

        for chain in embedding.values():
            sample_total_chains += 1
            if len(chain) > 1:
                chain_values = [sample[q] for q in chain]
                if len(set(chain_values)) > 1:
                    sample_broken_chains += 1

        total_weighted_chain_count += sample_total_chains * occurrences
        weighted_broken_chain_count += sample_broken_chains * occurrences

        if sample_broken_chains > 0:
            weighted_samples_with_breaks += occurrences

        # Track fraction of broken chains for this sample (for mean calculation)
        if sample_total_chains > 0:
            sample_break_fraction = sample_broken_chains / sample_total_chains
            # Add the fraction weighted by occurrences
            for _ in range(occurrences):
                break_fractions_per_sample.append(sample_break_fraction)

    broken_fraction = (
        weighted_broken_chain_count / total_weighted_chain_count
        if total_weighted_chain_count > 0 else 0.0
    )
    # Mean of per-sample break fractions (weighted by occurrences)
    mean_break_fraction = (
        sum(break_fractions_per_sample) / len(break_fractions_per_sample)
        if break_fractions_per_sample else 0.0
    )

    chain_stats = ChainBreakStatistics(
        total_samples=total_weighted_samples,
        samples_with_breaks=weighted_samples_with_breaks,
        total_chain_count=total_weighted_chain_count,
        broken_chain_count=weighted_broken_chain_count,
        broken_chain_fraction=broken_fraction,
        mean_break_fraction_per_sample=mean_break_fraction,
    )

    return logical_sampleset, chain_stats
