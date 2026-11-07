"""Canonical serializable graph and aggregate MWIS problem contracts."""

import math
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING

from qreduce.artifacts.metadata import canonical_json
from qreduce.mwis.validation import MWISValidationError

if TYPE_CHECKING:
    from qreduce.mwis.ising import CanonicalIsing
    from qreduce.mwis.qubo import CanonicalQubo


Edge = tuple[str, str]


@dataclass(frozen=True, slots=True)
class ReductionGraph:
    """Validated undirected reduction graph with a single canonical node order."""

    node_ids: tuple[str, ...]
    node_weights: Mapping[str, float]
    edges: tuple[Edge, ...]
    edge_reasons: Mapping[Edge, str]
    graph_policy_id: str
    graph_policy_version: str

    def __post_init__(self) -> None:
        """Validate graph invariants and freeze mappings at the kernel boundary."""

        node_ids = tuple(self.node_ids)
        if any(not isinstance(node_id, str) or not node_id.strip() for node_id in node_ids):
            raise MWISValidationError("invalid_node_id", "node_ids", "Each node ID must be a non-blank string.")
        if len(set(node_ids)) != len(node_ids):
            raise MWISValidationError("duplicate_node_id", "node_ids", "Each node ID must be unique.")
        if not isinstance(self.graph_policy_id, str) or not self.graph_policy_id.strip():
            raise MWISValidationError("blank_value", "graph_policy_id", "Value cannot be blank.")
        if not isinstance(self.graph_policy_version, str) or not self.graph_policy_version.strip():
            raise MWISValidationError("blank_value", "graph_policy_version", "Value cannot be blank.")

        node_weights = dict(self.node_weights)
        if set(node_weights) != set(node_ids):
            raise MWISValidationError(
                "node_weight_keys_mismatch",
                "node_weights",
                "node_weights keys must exactly match node_ids.",
            )
        for node_id, weight in node_weights.items():
            if not isinstance(weight, (int, float)) or isinstance(weight, bool) or not math.isfinite(weight) or weight < 0:
                raise MWISValidationError(
                    "invalid_node_weight",
                    f"node_weights[{node_id!r}]",
                    "Each node weight must be finite and non-negative.",
                )

        normalized_edges = tuple(tuple(edge) for edge in self.edges)
        seen_edges: set[Edge] = set()
        for edge in normalized_edges:
            if len(edge) != 2:
                raise MWISValidationError("invalid_edge", "edges", "Each edge must contain exactly two endpoints.")
            left, right = edge
            if left not in node_weights or right not in node_weights:
                raise MWISValidationError("unknown_edge_endpoint", "edges", "Each edge endpoint must exist in node_ids.")
            if left == right:
                raise MWISValidationError("self_loop", "edges", "Self-loop edges are not allowed.")
            if left >= right:
                raise MWISValidationError(
                    "noncanonical_edge",
                    "edges",
                    "Edge endpoints must be ordered lexicographically with left < right.",
                )
            if edge in seen_edges:
                raise MWISValidationError("duplicate_edge", "edges", "Duplicate edges are not allowed.")
            seen_edges.add(edge)

        edge_reasons = dict(self.edge_reasons)
        if set(edge_reasons) != seen_edges:
            raise MWISValidationError(
                "edge_reason_keys_mismatch",
                "edge_reasons",
                "Every edge must have exactly one reason and no orphan reasons are allowed.",
            )
        for edge, reason in edge_reasons.items():
            if not isinstance(reason, str) or not reason.strip():
                raise MWISValidationError(
                    "missing_edge_reason",
                    f"edge_reasons[{edge!r}]",
                    "Each edge reason must be a non-blank serializable string.",
                )

        object.__setattr__(self, "node_ids", node_ids)
        object.__setattr__(self, "node_weights", MappingProxyType(node_weights))
        object.__setattr__(self, "edges", normalized_edges)
        object.__setattr__(self, "edge_reasons", MappingProxyType(edge_reasons))

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible representation with explicit edge records."""

        return {
            "node_ids": list(self.node_ids),
            "node_weights": {node_id: self.node_weights[node_id] for node_id in self.node_ids},
            "edges": [list(edge) for edge in self.edges],
            "edge_reasons": [
                {"edge": list(edge), "reason": self.edge_reasons[edge]} for edge in self.edges
            ],
            "graph_policy_id": self.graph_policy_id,
            "graph_policy_version": self.graph_policy_version,
        }

    def to_canonical_json(self) -> str:
        """Return deterministic JSON suitable for graph artifacts and hashing."""

        return canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class CanonicalMWISProblem:
    """Canonical graph, QUBO and Ising forms ready for backend compilation."""

    graph: ReductionGraph
    qubo: "CanonicalQubo"
    ising: "CanonicalIsing"

    def __post_init__(self) -> None:
        """Ensure every canonical representation uses the graph node order."""

        if self.qubo.node_order != self.graph.node_ids:
            raise MWISValidationError("node_order_mismatch", "qubo.node_order", "QUBO order must match graph node_ids.")
        if self.ising.node_order != self.graph.node_ids:
            raise MWISValidationError("node_order_mismatch", "ising.node_order", "Ising order must match graph node_ids.")

    def to_dict(self) -> dict[str, object]:
        """Return a fully serializable canonical MWIS problem."""

        return {"graph": self.graph.to_dict(), "qubo": self.qubo.to_dict(), "ising": self.ising.to_dict()}