"""Presolve strategies for trivially solvable MWIS graphs.

This module implements exact presolve for graphs that can be solved optimally
without invoking the backend. The primary case is edgeless graphs with
non-negative weights, where the optimal MWIS is simply all nodes.

The presolve is backend-agnostic and runs before any mapping or execution.
It produces audit-transparent results that clearly indicate the resolution
method was exact presolve, not backend execution.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from time import perf_counter
from types import MappingProxyType
from typing import TYPE_CHECKING

from qreduce.artifacts.metadata import redact_metadata, to_primitive
from qreduce.mwis.graph import ReductionGraph
from qreduce.mwis.validation import validate_binary_selection

if TYPE_CHECKING:
    from qreduce.solving.mwis.contracts import RawMISSample


class PresolveReason(StrEnum):
    """Reason why a graph was resolved by exact presolve."""

    EDGELESS_POSITIVE_WEIGHTS = "edgeless_positive_weights"
    EDGELESS_NONNEGATIVE_WEIGHTS = "edgeless_nonnegative_weights"
    EMPTY_GRAPH = "empty_graph"


class PresolveStatus(StrEnum):
    """Status of presolve attempt."""

    APPLIED = "applied"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True, slots=True)
class PresolveResult:
    """Result of attempting exact presolve on a graph.

    When status is APPLIED, the delta field contains the certified optimal
    solution. When NOT_APPLICABLE, delta is None and the graph requires
    backend execution.

    Attributes:
        status: Whether presolve was applied or graph requires backend.
        reason: Why presolve was or wasn't applicable.
        delta: The optimal selection vector (1 = selected, 0 = excluded).
        node_order: The canonical node order matching delta positions.
        selection_weight: Total weight of selected nodes.
        num_selected: Count of selected nodes.
        is_certified_optimal: True when solution is provably optimal.
        runtime_seconds: Time spent in presolve evaluation.
        requested_backend_id: Backend that would have been used.
        backend_bypassed: True when backend execution was skipped.
        diagnostic_message: Human-readable explanation.
        provenance: Audit metadata about the presolve decision.
    """

    status: PresolveStatus
    reason: PresolveReason | None
    delta: tuple[int, ...] | None
    node_order: tuple[str, ...] | None
    selection_weight: float | None
    num_selected: int | None
    is_certified_optimal: bool
    runtime_seconds: float
    requested_backend_id: str | None
    backend_bypassed: bool
    diagnostic_message: str | None = None
    provenance: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.provenance:
            object.__setattr__(
                self, "provenance", MappingProxyType(dict(self.provenance))
            )
        else:
            object.__setattr__(self, "provenance", MappingProxyType({}))

    def to_dict(self) -> dict[str, object]:
        """Return a serializable representation for artifacts."""
        return redact_metadata(to_primitive(self))  # type: ignore[return-value]


def try_presolve(
    graph: ReductionGraph,
    *,
    requested_backend_id: str | None = None,
    include_zero_weight_nodes: bool = True,
) -> PresolveResult:
    """Attempt exact presolve if the graph is trivially solvable.

    For edgeless graphs with non-negative weights, the optimal MWIS is to
    select all nodes (or all nodes with positive weight, depending on the
    include_zero_weight_nodes parameter).

    Convention for zero-weight nodes:
    - include_zero_weight_nodes=True (default): Select all nodes. This
      preserves the maximal independent set property and is consistent
      with the MWIS objective where ties are broken by including more nodes.
    - include_zero_weight_nodes=False: Exclude zero-weight nodes. The
      solution remains optimal but may not be maximal.

    Args:
        graph: The reduction graph to analyze.
        requested_backend_id: The backend that would have been used.
        include_zero_weight_nodes: Whether to include nodes with zero weight.

    Returns:
        PresolveResult indicating whether presolve was applied and the
        optimal solution if applicable.
    """
    start = perf_counter()

    # Empty graph case
    if not graph.node_ids:
        return PresolveResult(
            status=PresolveStatus.APPLIED,
            reason=PresolveReason.EMPTY_GRAPH,
            delta=(),
            node_order=(),
            selection_weight=0.0,
            num_selected=0,
            is_certified_optimal=True,
            runtime_seconds=perf_counter() - start,
            requested_backend_id=requested_backend_id,
            backend_bypassed=True,
            diagnostic_message="Empty graph: trivially optimal empty selection.",
            provenance={
                "presolve_version": 1,
                "include_zero_weight_nodes": include_zero_weight_nodes,
            },
        )

    # Check if graph has any edges
    if graph.edges:
        return PresolveResult(
            status=PresolveStatus.NOT_APPLICABLE,
            reason=None,
            delta=None,
            node_order=None,
            selection_weight=None,
            num_selected=None,
            is_certified_optimal=False,
            runtime_seconds=perf_counter() - start,
            requested_backend_id=requested_backend_id,
            backend_bypassed=False,
            diagnostic_message="Graph has edges; presolve not applicable.",
            provenance={
                "presolve_version": 1,
                "edge_count": len(graph.edges),
            },
        )

    # Edgeless graph: determine selection based on weights
    all_positive = all(w > 0 for w in graph.node_weights.values())
    all_nonnegative = all(w >= 0 for w in graph.node_weights.values())

    if not all_nonnegative:
        # Negative weights are not supported by the current contract
        return PresolveResult(
            status=PresolveStatus.NOT_APPLICABLE,
            reason=None,
            delta=None,
            node_order=None,
            selection_weight=None,
            num_selected=None,
            is_certified_optimal=False,
            runtime_seconds=perf_counter() - start,
            requested_backend_id=requested_backend_id,
            backend_bypassed=False,
            diagnostic_message="Graph contains negative weights; presolve not applicable.",
            provenance={
                "presolve_version": 1,
                "has_negative_weights": True,
            },
        )

    # Determine which nodes to select
    if include_zero_weight_nodes:
        # Select all nodes
        delta = tuple(1 for _ in graph.node_ids)
        reason = (
            PresolveReason.EDGELESS_POSITIVE_WEIGHTS
            if all_positive
            else PresolveReason.EDGELESS_NONNEGATIVE_WEIGHTS
        )
    else:
        # Select only positive-weight nodes
        delta = tuple(
            1 if graph.node_weights[node_id] > 0 else 0
            for node_id in graph.node_ids
        )
        reason = (
            PresolveReason.EDGELESS_POSITIVE_WEIGHTS
            if all_positive
            else PresolveReason.EDGELESS_NONNEGATIVE_WEIGHTS
        )

    # Validate the selection (should always pass for edgeless graph)
    validation = validate_binary_selection(graph, delta)

    num_selected = sum(delta)
    total_weight = validation.selection_weight

    elapsed = perf_counter() - start

    return PresolveResult(
        status=PresolveStatus.APPLIED,
        reason=reason,
        delta=delta,
        node_order=graph.node_ids,
        selection_weight=total_weight,
        num_selected=num_selected,
        is_certified_optimal=True,
        runtime_seconds=elapsed,
        requested_backend_id=requested_backend_id,
        backend_bypassed=True,
        diagnostic_message=(
            f"Edgeless graph with {len(graph.node_ids)} nodes: "
            f"selected {num_selected} nodes with total weight {total_weight:.6f}."
        ),
        provenance={
            "presolve_version": 1,
            "include_zero_weight_nodes": include_zero_weight_nodes,
            "all_weights_positive": all_positive,
            "node_count": len(graph.node_ids),
        },
    )


def presolve_to_raw_sample(
    presolve_result: PresolveResult,
    *,
    run_id: str,
    round_index: int,
) -> "RawMISSample":
    """Convert a successful presolve result to a RawMISSample for pipeline integration.

    This creates a sample that can be processed by the standard normalization
    and candidate selection pipeline, with clear provenance indicating it
    came from exact presolve rather than backend execution.

    Args:
        presolve_result: A PresolveResult with status APPLIED.
        run_id: The pipeline run identifier.
        round_index: The reduction round index.

    Returns:
        A RawMISSample suitable for pipeline processing.

    Raises:
        ValueError: If presolve_result.status is not APPLIED.
    """
    from qreduce.solving.mwis.contracts import (
        BackendReportedScoreKind,
        RawMISSample,
    )

    if presolve_result.status != PresolveStatus.APPLIED:
        raise ValueError("Cannot convert non-applied presolve to sample.")

    if presolve_result.delta is None or presolve_result.node_order is None:
        raise ValueError("Presolve result missing delta or node_order.")

    return RawMISSample(
        raw_sample_id=f"{run_id}:round:{round_index}:presolve:exact",
        node_order=presolve_result.node_order,
        delta=presolve_result.delta,
        occurrence_count=1,
        backend_reported_score=None,
        backend_reported_score_kind=BackendReportedScoreKind.UNAVAILABLE,
        canonical_qubo_energy=None,  # Will be computed by normalization
        canonical_ising_energy=None,
        selection_weight=presolve_result.selection_weight,
        num_selected=presolve_result.num_selected,
        is_independent_set=True,  # Guaranteed for edgeless graph
        violated_edges=(),
        num_violated_edges=0,
        source_provider_id="qreduce",
        source_backend_id="presolve_exact",
        execution_runtime_seconds=presolve_result.runtime_seconds,
        effective_compilation_parameters={},
        effective_execution_parameters={
            "presolve_reason": presolve_result.reason.value if presolve_result.reason else None,
            "is_certified_optimal": presolve_result.is_certified_optimal,
        },
        raw_backend_metadata={
            "presolve_provenance": dict(presolve_result.provenance),
        },
    )
