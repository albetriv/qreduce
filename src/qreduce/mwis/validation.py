"""Validation for canonical MWIS graphs, penalties and binary selections."""

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from qreduce.mwis.graph import ReductionGraph


class MWISValidationError(ValueError):
    """Explicit validation failure with a stable machine-readable code."""

    def __init__(self, code: str, field: str, message: str) -> None:
        super().__init__(f"{code} ({field}): {message}")
        self.code = code
        self.field = field


@dataclass(frozen=True, slots=True)
class PenaltyValidationResult:
    """Whether an edge penalty has the standard MWIS structural guarantee."""

    is_valid: bool
    proof_condition_satisfied: bool
    maximum_node_weight: float | None
    lambda_edge: float


@dataclass(frozen=True, slots=True)
class SelectionValidationResult:
    """Structural validation and summary statistics for one binary selection."""

    is_independent_set: bool
    violated_edges: tuple[tuple[str, str], ...]
    num_violated_edges: int
    selection_weight: float
    num_selected: int
    selected_node_ids: tuple[str, ...]


def validate_edge_penalty(graph: "ReductionGraph", lambda_edge: float) -> PenaltyValidationResult:
    """Validate the standard condition lambda_edge > max_i(w_i)."""

    if (
        not isinstance(lambda_edge, (int, float))
        or isinstance(lambda_edge, bool)
        or not math.isfinite(lambda_edge)
        or lambda_edge <= 0
    ):
        raise MWISValidationError(
            "invalid_lambda_edge",
            "lambda_edge",
            "lambda_edge must be a finite numeric value greater than zero.",
        )

    maximum_node_weight = max(graph.node_weights.values(), default=None)
    proof_condition_satisfied = maximum_node_weight is None or lambda_edge > maximum_node_weight
    return PenaltyValidationResult(
        is_valid=proof_condition_satisfied,
        proof_condition_satisfied=proof_condition_satisfied,
        maximum_node_weight=maximum_node_weight,
        lambda_edge=float(lambda_edge),
    )


def validate_binary_selection(
    graph: "ReductionGraph",
    delta: tuple[int, ...] | list[int],
) -> SelectionValidationResult:
    """Validate a delta vector in graph.node_ids order and report conflicts."""

    normalized_delta = _normalize_binary_vector(delta, "delta")
    if len(normalized_delta) != len(graph.node_ids):
        raise MWISValidationError(
            "selection_length_mismatch",
            "delta",
            "delta length must equal the graph node_ids length.",
        )

    selected_node_ids = tuple(
        node_id for node_id, value in zip(graph.node_ids, normalized_delta, strict=True) if value == 1
    )
    selected_nodes = frozenset(selected_node_ids)
    violated_edges = tuple(
        edge for edge in graph.edges if edge[0] in selected_nodes and edge[1] in selected_nodes
    )
    return SelectionValidationResult(
        is_independent_set=not violated_edges,
        violated_edges=violated_edges,
        num_violated_edges=len(violated_edges),
        selection_weight=sum(graph.node_weights[node_id] for node_id in selected_node_ids),
        num_selected=len(selected_node_ids),
        selected_node_ids=selected_node_ids,
    )


def normalize_binary_vector(delta: tuple[int, ...] | list[int], field: str = "delta") -> tuple[int, ...]:
    """Return a validated binary vector without accepting booleans implicitly."""

    if not isinstance(delta, tuple | list):
        raise MWISValidationError("invalid_binary_vector", field, "Vector must be a tuple or list.")
    normalized_values: list[int] = []
    for index, value in enumerate(delta):
        if not isinstance(value, int) or isinstance(value, bool) or value not in (0, 1):
            raise MWISValidationError(
                "invalid_binary_value",
                f"{field}[{index}]",
                "Each value must be the integer 0 or 1.",
            )
        normalized_values.append(value)
    return tuple(normalized_values)


_normalize_binary_vector = normalize_binary_vector