"""Canonical QUBO representation and standard MWIS construction."""

import math
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from qreduce.artifacts.metadata import canonical_json
from qreduce.mwis.graph import Edge, ReductionGraph
from qreduce.mwis.validation import MWISValidationError, validate_edge_penalty


@dataclass(frozen=True, slots=True)
class CanonicalQubo:
    """Binary quadratic model using delta variables in the declared node order."""

    node_order: tuple[str, ...]
    linear: Mapping[str, float]
    quadratic: Mapping[Edge, float]
    offset: float
    lambda_edge: float
    proof_condition_satisfied: bool

    def __post_init__(self) -> None:
        """Validate canonical QUBO terms and freeze its mappings."""

        node_order = tuple(self.node_order)
        if len(set(node_order)) != len(node_order):
            raise MWISValidationError("duplicate_node_id", "node_order", "QUBO node order must be unique.")
        linear = dict(self.linear)
        if set(linear) != set(node_order):
            raise MWISValidationError("linear_keys_mismatch", "linear", "Linear terms must exactly match node_order.")
        quadratic = dict(self.quadratic)
        for edge, coefficient in quadratic.items():
            if len(edge) != 2 or edge[0] not in linear or edge[1] not in linear or edge[0] >= edge[1]:
                raise MWISValidationError("invalid_quadratic_edge", "quadratic", "Quadratic keys must be canonical node edges.")
            _require_finite(coefficient, f"quadratic[{edge!r}]")
        for node_id, coefficient in linear.items():
            _require_finite(coefficient, f"linear[{node_id!r}]")
        _require_finite(self.offset, "offset")
        _require_finite(self.lambda_edge, "lambda_edge")
        if self.lambda_edge <= 0:
            raise MWISValidationError(
                "invalid_lambda_edge",
                "lambda_edge",
                "lambda_edge must be greater than zero.",
            )
        object.__setattr__(self, "node_order", node_order)
        object.__setattr__(self, "linear", MappingProxyType(linear))
        object.__setattr__(self, "quadratic", MappingProxyType(quadratic))

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible QUBO with explicit quadratic-term records."""

        return {
            "variable_domain": "binary",
            "node_order": list(self.node_order),
            "linear": {node_id: self.linear[node_id] for node_id in self.node_order},
            "quadratic": [
                {"edge": list(edge), "coefficient": coefficient}
                for edge, coefficient in sorted(self.quadratic.items())
            ],
            "offset": self.offset,
            "lambda_edge": self.lambda_edge,
            "proof_condition_satisfied": self.proof_condition_satisfied,
        }

    def to_canonical_json(self) -> str:
        """Return deterministic JSON suitable for QUBO artifacts and hashing."""

        return canonical_json(self.to_dict())


def build_mwis_qubo(
    graph: ReductionGraph,
    lambda_edge: float,
    *,
    allow_noncertifying_penalty: bool = False,
) -> CanonicalQubo:
    """Build exactly the standard MWIS QUBO and no cardinality penalties."""

    penalty_validation = validate_edge_penalty(graph, lambda_edge)
    if not penalty_validation.proof_condition_satisfied and not allow_noncertifying_penalty:
        maximum_weight = penalty_validation.maximum_node_weight
        raise MWISValidationError(
            "noncertifying_lambda_edge",
            "lambda_edge",
            f"lambda_edge must be greater than maximum node weight {maximum_weight}.",
        )
    return CanonicalQubo(
        node_order=graph.node_ids,
        linear={node_id: -graph.node_weights[node_id] for node_id in graph.node_ids},
        quadratic={edge: float(lambda_edge) for edge in graph.edges},
        offset=0.0,
        lambda_edge=float(lambda_edge),
        proof_condition_satisfied=penalty_validation.proof_condition_satisfied,
    )


def _require_finite(value: float, field: str) -> None:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        raise MWISValidationError("invalid_numeric_value", field, "Value must be finite and numeric.")