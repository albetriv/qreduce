"""Canonical Ising representation and exact conversion from canonical QUBO."""

import math
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from qreduce.artifacts.metadata import canonical_json
from qreduce.mwis.graph import Edge
from qreduce.mwis.qubo import CanonicalQubo
from qreduce.mwis.validation import MWISValidationError, normalize_binary_vector

_BINARY_TO_SPIN_CONVENTION = "delta_i = (1 + z_i) / 2; z_i = 2 * delta_i - 1"


@dataclass(frozen=True, slots=True)
class CanonicalIsing:
    """Spin model using z variables in {-1, +1} and declared binary convention."""

    node_order: tuple[str, ...]
    linear: Mapping[str, float]
    quadratic: Mapping[Edge, float]
    offset: float
    binary_to_spin_convention: str = _BINARY_TO_SPIN_CONVENTION

    def __post_init__(self) -> None:
        """Validate canonical Ising terms and freeze mappings."""

        node_order = tuple(self.node_order)
        if len(set(node_order)) != len(node_order):
            raise MWISValidationError("duplicate_node_id", "node_order", "Ising node order must be unique.")
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
        if not self.binary_to_spin_convention.strip():
            raise MWISValidationError("blank_value", "binary_to_spin_convention", "Convention cannot be blank.")
        object.__setattr__(self, "node_order", node_order)
        object.__setattr__(self, "linear", MappingProxyType(linear))
        object.__setattr__(self, "quadratic", MappingProxyType(quadratic))

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible Ising representation with explicit offset."""

        return {
            "variable_domain": "spin",
            "node_order": list(self.node_order),
            "linear": {node_id: self.linear[node_id] for node_id in self.node_order},
            "quadratic": [
                {"edge": list(edge), "coefficient": coefficient}
                for edge, coefficient in sorted(self.quadratic.items())
            ],
            "offset": self.offset,
            "binary_to_spin_convention": self.binary_to_spin_convention,
        }

    def to_canonical_json(self) -> str:
        """Return deterministic JSON suitable for Ising artifacts and hashing."""

        return canonical_json(self.to_dict())


def qubo_to_ising(qubo: CanonicalQubo) -> CanonicalIsing:
    """Convert a binary QUBO using delta_i = (1 + z_i) / 2 exactly."""

    linear = {node_id: 0.5 * qubo.linear[node_id] for node_id in qubo.node_order}
    offset = qubo.offset + 0.5 * sum(qubo.linear.values())
    quadratic: dict[Edge, float] = {}
    for edge, coefficient in qubo.quadratic.items():
        left, right = edge
        offset += 0.25 * coefficient
        linear[left] += 0.25 * coefficient
        linear[right] += 0.25 * coefficient
        quadratic[edge] = 0.25 * coefficient
    return CanonicalIsing(node_order=qubo.node_order, linear=linear, quadratic=quadratic, offset=offset)


def delta_to_spin(delta: tuple[int, ...] | list[int]) -> tuple[int, ...]:
    """Map binary delta values to spins with z = 2 * delta - 1."""

    return tuple(2 * value - 1 for value in normalize_binary_vector(delta))


def spin_to_delta(z_spin: tuple[int, ...] | list[int]) -> tuple[int, ...]:
    """Map Ising spins to binary values with delta = (1 + z) / 2."""

    from qreduce.mwis.energy import normalize_spin_vector

    return tuple((1 + value) // 2 for value in normalize_spin_vector(z_spin))


def _require_finite(value: float, field: str) -> None:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        raise MWISValidationError("invalid_numeric_value", field, "Value must be finite and numeric.")