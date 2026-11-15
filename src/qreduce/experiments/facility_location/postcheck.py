"""Independent arithmetic validation of a facility-location solution."""

import math
from collections.abc import Mapping
from dataclasses import dataclass

from .formulation import delta_name, x_name
from .models import FacilityLocationProblem


@dataclass(frozen=True, slots=True)
class PostcheckResult:
    feasible: bool
    objective: float | None
    violations: tuple[str, ...]


def validate_solution(
    problem: FacilityLocationProblem,
    values: Mapping[str, float],
    *,
    excluded: tuple[int, ...] = (),
    objective: float | None = None,
    tolerance: float = 1e-6,
    integrality_tolerance: float | None = None,
) -> PostcheckResult:
    if not math.isfinite(tolerance) or tolerance < 0:
        raise ValueError("tolerance must be finite and nonnegative")
    if integrality_tolerance is None:
        integrality_tolerance = tolerance
    if not math.isfinite(integrality_tolerance) or integrality_tolerance < 0:
        raise ValueError("integrality_tolerance must be finite and nonnegative")
    m, n = len(problem.capacities), len(problem.demands)
    if len(set(excluded)) != len(excluded) or any(not isinstance(i, int) or isinstance(i, bool) or i < 0 or i >= m for i in excluded):
        raise ValueError("Invalid excluded facilities")
    names = [delta_name(i) for i in range(m)] + [x_name(i, j) for i in range(m) for j in range(n)]
    if any(name not in values or not isinstance(values[name], int | float) or isinstance(values[name], bool) or not math.isfinite(values[name]) for name in names):
        return PostcheckResult(False, None, ("missing or non-finite variable",))
    failures = []
    for i in range(m):
        delta = values[delta_name(i)]
        if min(abs(delta), abs(delta - 1)) > integrality_tolerance:
            failures.append(f"binary:{i}")
        if sum(problem.demands[j] * values[x_name(i, j)] for j in range(n)) > problem.capacities[i] * delta + tolerance:
            failures.append(f"capacity:{i}")
        if i in excluded and abs(delta) > tolerance:
            failures.append(f"fixing:{delta_name(i)}")
        for j in range(n):
            x = values[x_name(i, j)]
            if x < -tolerance or x > 1 + tolerance:
                failures.append(f"bounds:{i}:{j}")
            if x > delta + tolerance:
                failures.append(f"link:{i}:{j}")
            if i in excluded and abs(x) > tolerance:
                failures.append(f"fixing:{x_name(i, j)}")
    for j in range(n):
        if abs(sum(values[x_name(i, j)] for i in range(m)) - 1) > tolerance:
            failures.append(f"demand:{j}")
    calculated = sum(problem.fixed_costs[i] * values[delta_name(i)] for i in range(m))
    calculated += sum(problem.allocation_costs[j][i] * values[x_name(i, j)] for i in range(m) for j in range(n))
    if objective is not None and (not math.isfinite(objective) or abs(calculated - objective) > tolerance * max(1, abs(calculated), abs(objective))):
        failures.append("objective")
    return PostcheckResult(not failures, calculated, tuple(failures))