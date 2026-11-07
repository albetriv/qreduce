"""Local energy evaluation for canonical binary QUBO and spin Ising models."""

from qreduce.mwis.ising import CanonicalIsing
from qreduce.mwis.qubo import CanonicalQubo
from qreduce.mwis.validation import MWISValidationError, normalize_binary_vector


def qubo_energy(qubo: CanonicalQubo, delta: tuple[int, ...] | list[int]) -> float:
    """Evaluate QUBO energy for a binary vector in qubo.node_order."""

    normalized_delta = normalize_binary_vector(delta)
    if len(normalized_delta) != len(qubo.node_order):
        raise MWISValidationError("selection_length_mismatch", "delta", "delta length must equal QUBO node_order.")
    values = dict(zip(qubo.node_order, normalized_delta, strict=True))
    return qubo.offset + sum(qubo.linear[node_id] * values[node_id] for node_id in qubo.node_order) + sum(
        coefficient * values[left] * values[right]
        for (left, right), coefficient in qubo.quadratic.items()
    )


def ising_energy(ising: CanonicalIsing, z_spin: tuple[int, ...] | list[int]) -> float:
    """Evaluate Ising energy for a spin vector in ising.node_order."""

    normalized_spins = normalize_spin_vector(z_spin)
    if len(normalized_spins) != len(ising.node_order):
        raise MWISValidationError("selection_length_mismatch", "z_spin", "z_spin length must equal Ising node_order.")
    values = dict(zip(ising.node_order, normalized_spins, strict=True))
    return ising.offset + sum(ising.linear[node_id] * values[node_id] for node_id in ising.node_order) + sum(
        coefficient * values[left] * values[right]
        for (left, right), coefficient in ising.quadratic.items()
    )


def normalize_spin_vector(z_spin: tuple[int, ...] | list[int]) -> tuple[int, ...]:
    """Return a validated Ising spin vector without accepting booleans implicitly."""

    if not isinstance(z_spin, tuple | list):
        raise MWISValidationError("invalid_spin_vector", "z_spin", "Vector must be a tuple or list.")
    normalized_values: list[int] = []
    for index, value in enumerate(z_spin):
        if not isinstance(value, int) or isinstance(value, bool) or value not in (-1, 1):
            raise MWISValidationError(
                "invalid_spin_value",
                f"z_spin[{index}]",
                "Each spin must be the integer -1 or 1.",
            )
        normalized_values.append(value)
    return tuple(normalized_values)