"""Classical completion for MWIS candidates.

This module implements optional greedy completion to transform independent
sets into maximal independent sets. The completion is a post-processing
step that adds nodes to a valid independent set without violating
independence constraints.

Key principles:
1. Completion is SEPARATE from repair (repair fixes violations, completion adds nodes)
2. Completion preserves independence (never adds a node with an edge to selected nodes)
3. Completion is deterministic (same input always produces same output)
4. Completion is optional and configurable (default: disabled)
5. Completion produces maximality, NOT optimality (greedy, not optimal MWIS)
6. All additions are tracked for audit transparency

The completion does NOT:
- Guarantee optimal weight (it's greedy, not globally optimal)
- Replace backend quality (a poor backend still produces poor candidates)
- Hide backend limitations (audit shows what came from backend vs completion)
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from time import perf_counter
from types import MappingProxyType

from qreduce.artifacts.metadata import redact_metadata, to_primitive
from qreduce.mwis.graph import ReductionGraph
from qreduce.mwis.validation import validate_binary_selection


class CompletionPolicyId(StrEnum):
    """Identifier for completion policies."""

    DISABLED = "disabled"  # No completion (default)
    GREEDY_BY_WEIGHT = "greedy_by_weight"  # Add nodes by descending weight
    GREEDY_BY_DEGREE = "greedy_by_degree"  # Add nodes with fewer neighbors first
    GREEDY_WEIGHT_DEGREE = "greedy_weight_degree"  # Weight / (degree + 1)


@dataclass(frozen=True, slots=True)
class CompletionPolicy:
    """Configuration for classical completion.

    Attributes:
        policy_id: Which completion algorithm to use.
        enabled: Whether completion is active.
        tie_breaker: How to break ties (by node_id for determinism).
        max_additions: Maximum nodes to add (None = unlimited).
    """

    policy_id: CompletionPolicyId
    enabled: bool = False
    tie_breaker: str = "node_id"  # "node_id" for determinism, "weight" for quality
    max_additions: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "policy_id", CompletionPolicyId(self.policy_id))
        if not isinstance(self.enabled, bool):
            raise TypeError("enabled must be a boolean")
        if self.enabled == (self.policy_id == CompletionPolicyId.DISABLED):
            raise ValueError("enabled and policy_id must agree")
        if self.tie_breaker != "node_id":
            raise ValueError("Only node_id tie-breaking is supported")
        if self.max_additions is not None and (
            isinstance(self.max_additions, bool)
            or not isinstance(self.max_additions, int)
            or self.max_additions < 0
        ):
            raise ValueError("max_additions must be a nonnegative integer or None")

    def to_dict(self) -> dict[str, object]:
        return {
            "policy_id": self.policy_id.value,
            "enabled": self.enabled,
            "tie_breaker": self.tie_breaker,
            "max_additions": self.max_additions,
        }


def default_completion_policy() -> CompletionPolicy:
    """Return the default completion policy (disabled).

    Completion is disabled by default to ensure that:
    1. Backend quality is measured accurately
    2. No hidden transformations alter MWIS results
    3. Users must explicitly opt-in to classical enhancement
    """
    return CompletionPolicy(
        policy_id=CompletionPolicyId.DISABLED,
        enabled=False,
    )


def greedy_weight_completion_policy() -> CompletionPolicy:
    """Return a greedy completion policy that adds nodes by weight.

    This policy adds compatible nodes in descending weight order,
    which typically produces good (but not optimal) MWIS solutions.
    """
    return CompletionPolicy(
        policy_id=CompletionPolicyId.GREEDY_BY_WEIGHT,
        enabled=True,
        tie_breaker="node_id",
    )


@dataclass(frozen=True, slots=True)
class CompletionResult:
    """Result of classical completion on a candidate.

    Attributes:
        original_delta: The input selection before completion.
        completed_delta: The output selection after completion.
        original_weight: Total weight before completion.
        completed_weight: Total weight after completion.
        original_size: Number of selected nodes before completion.
        completed_size: Number of selected nodes after completion.
        nodes_added: Nodes added during completion.
        is_maximal: Whether the result is a maximal independent set.
        was_already_maximal: Whether input was already maximal.
        policy_id: The completion policy used.
        runtime_seconds: Time spent on completion.
        provenance: Audit metadata.
    """

    original_delta: tuple[int, ...]
    completed_delta: tuple[int, ...]
    original_weight: float
    completed_weight: float
    original_size: int
    completed_size: int
    nodes_added: tuple[str, ...]
    is_maximal: bool
    was_already_maximal: bool
    policy_id: CompletionPolicyId
    runtime_seconds: float
    provenance: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "nodes_added", tuple(self.nodes_added))
        object.__setattr__(
            self, "provenance", MappingProxyType(dict(self.provenance))
        )

    def to_dict(self) -> dict[str, object]:
        return redact_metadata(to_primitive(self))  # type: ignore[return-value]

    @property
    def weight_improvement(self) -> float:
        """Weight gained from completion."""
        return self.completed_weight - self.original_weight

    @property
    def size_improvement(self) -> int:
        """Nodes added by completion."""
        return self.completed_size - self.original_size


def complete_candidate(
    graph: ReductionGraph,
    delta: tuple[int, ...],
    policy: CompletionPolicy,
) -> CompletionResult:
    """Apply classical completion to an independent set candidate.

    Given a valid independent set (delta), greedily add nodes that do not
    violate independence until no more nodes can be added (maximal) or
    the max_additions limit is reached.

    Args:
        graph: The reduction graph defining conflicts.
        delta: Binary selection vector (1 = selected, 0 = not selected).
        policy: The completion policy to apply.

    Returns:
        CompletionResult with the completed selection and audit information.

    Raises:
        ValueError: If delta is not a valid independent set.
    """
    start = perf_counter()

    validate_binary_selection(graph, delta)

    if len(delta) != len(graph.node_ids):
        raise ValueError(
            f"Delta length {len(delta)} does not match graph nodes {len(graph.node_ids)}"
        )

    # Build adjacency list for efficient neighbor lookup
    adjacency: dict[str, set[str]] = {node_id: set() for node_id in graph.node_ids}
    for left, right in graph.edges:
        adjacency[left].add(right)
        adjacency[right].add(left)

    # Verify input is an independent set
    selected = {graph.node_ids[i] for i, val in enumerate(delta) if val == 1}
    for node_id in selected:
        if any(neighbor in selected for neighbor in adjacency[node_id]):
            raise ValueError(
                f"Input is not an independent set: {node_id} has selected neighbor"
            )

    # Calculate original metrics
    original_weight = sum(
        graph.node_weights[node_id] for node_id in selected
    )
    original_size = len(selected)

    # If disabled, return immediately
    if not policy.enabled or policy.policy_id == CompletionPolicyId.DISABLED:
        is_maximal = _is_maximal(selected, adjacency, graph.node_ids)
        return CompletionResult(
            original_delta=delta,
            completed_delta=delta,
            original_weight=original_weight,
            completed_weight=original_weight,
            original_size=original_size,
            completed_size=original_size,
            nodes_added=(),
            is_maximal=is_maximal,
            was_already_maximal=is_maximal,
            policy_id=policy.policy_id,
            runtime_seconds=perf_counter() - start,
            provenance={"completion_enabled": False},
        )

    # Check if already maximal
    was_already_maximal = _is_maximal(selected, adjacency, graph.node_ids)
    if was_already_maximal:
        return CompletionResult(
            original_delta=delta,
            completed_delta=delta,
            original_weight=original_weight,
            completed_weight=original_weight,
            original_size=original_size,
            completed_size=original_size,
            nodes_added=(),
            is_maximal=True,
            was_already_maximal=True,
            policy_id=policy.policy_id,
            runtime_seconds=perf_counter() - start,
            provenance={"already_maximal": True},
        )

    # Find candidates: nodes not selected and not adjacent to selected
    candidates = [
        node_id
        for node_id in graph.node_ids
        if node_id not in selected and not any(n in selected for n in adjacency[node_id])
    ]

    # Sort candidates according to policy
    candidates = _sort_candidates(
        candidates, graph, adjacency, policy
    )

    # Greedily add nodes
    nodes_added = []
    completed_selected = set(selected)
    max_to_add = policy.max_additions if policy.max_additions is not None else len(candidates)

    for candidate in candidates:
        if len(nodes_added) >= max_to_add:
            break

        # Check if candidate is still compatible
        if any(n in completed_selected for n in adjacency[candidate]):
            continue

        # Add the candidate
        completed_selected.add(candidate)
        nodes_added.append(candidate)

    # Build completed delta
    completed_delta = tuple(
        1 if graph.node_ids[i] in completed_selected else 0
        for i in range(len(graph.node_ids))
    )

    # Calculate completed metrics
    completed_weight = sum(
        graph.node_weights[node_id] for node_id in completed_selected
    )
    completed_size = len(completed_selected)
    is_maximal = _is_maximal(completed_selected, adjacency, graph.node_ids)

    return CompletionResult(
        original_delta=delta,
        completed_delta=completed_delta,
        original_weight=original_weight,
        completed_weight=completed_weight,
        original_size=original_size,
        completed_size=completed_size,
        nodes_added=tuple(nodes_added),
        is_maximal=is_maximal,
        was_already_maximal=was_already_maximal,
        policy_id=policy.policy_id,
        runtime_seconds=perf_counter() - start,
        provenance={
            "candidates_considered": len(candidates),
            "max_additions": max_to_add,
        },
    )


def _is_maximal(
    selected: set[str],
    adjacency: dict[str, set[str]],
    node_ids: tuple[str, ...],
) -> bool:
    """Check if the selected set is a maximal independent set.

    A set is maximal if no unselected node can be added without
    violating independence (i.e., every unselected node has at least
    one selected neighbor).
    """
    for node_id in node_ids:
        if node_id in selected:
            continue
        # If this unselected node has no selected neighbors, it could be added
        if not any(n in selected for n in adjacency[node_id]):
            return False
    return True


def _sort_candidates(
    candidates: list[str],
    graph: ReductionGraph,
    adjacency: dict[str, set[str]],
    policy: CompletionPolicy,
) -> list[str]:
    """Sort candidates according to the completion policy."""

    def weight_key(node_id: str) -> tuple[float, str]:
        # Descending weight, then ascending node_id for determinism
        return (-graph.node_weights[node_id], node_id)

    def degree_key(node_id: str) -> tuple[int, str]:
        # Ascending degree, then ascending node_id for determinism
        return (len(adjacency[node_id]), node_id)

    def weight_degree_key(node_id: str) -> tuple[float, str]:
        # Descending weight/(degree+1), then ascending node_id
        degree = len(adjacency[node_id])
        score = graph.node_weights[node_id] / (degree + 1)
        return (-score, node_id)

    if policy.policy_id == CompletionPolicyId.GREEDY_BY_WEIGHT:
        return sorted(candidates, key=weight_key)
    elif policy.policy_id == CompletionPolicyId.GREEDY_BY_DEGREE:
        return sorted(candidates, key=degree_key)
    elif policy.policy_id == CompletionPolicyId.GREEDY_WEIGHT_DEGREE:
        return sorted(candidates, key=weight_degree_key)
    else:
        # Default: sort by node_id for determinism
        return sorted(candidates)


def compute_maximality_gap(
    graph: ReductionGraph,
    delta: tuple[int, ...],
) -> dict[str, object]:
    """Compute metrics about how far a selection is from maximal.

    Args:
        graph: The reduction graph.
        delta: Binary selection vector.

    Returns:
        Dictionary with:
        - is_maximal: Whether the selection is maximal.
        - addable_nodes: Nodes that could be added.
        - addable_weight: Total weight of addable nodes.
        - addable_count: Number of addable nodes.
    """
    validation = validate_binary_selection(graph, delta)
    if not validation.is_independent_set:
        raise ValueError("Maximality requires an independent set")
    if len(delta) != len(graph.node_ids):
        raise ValueError("Delta length mismatch")

    # Build adjacency
    adjacency: dict[str, set[str]] = {node_id: set() for node_id in graph.node_ids}
    for left, right in graph.edges:
        adjacency[left].add(right)
        adjacency[right].add(left)

    selected = {graph.node_ids[i] for i, val in enumerate(delta) if val == 1}

    # Find addable nodes
    addable = []
    for node_id in graph.node_ids:
        if node_id in selected:
            continue
        if not any(n in selected for n in adjacency[node_id]):
            addable.append(node_id)

    addable_weight = sum(graph.node_weights[n] for n in addable)

    return {
        "is_maximal": len(addable) == 0,
        "addable_nodes": tuple(sorted(addable)),
        "addable_weight": addable_weight,
        "addable_count": len(addable),
    }
