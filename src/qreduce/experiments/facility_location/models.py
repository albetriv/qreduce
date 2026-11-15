"""Immutable data for fractional capacitated facility location."""

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True, slots=True)
class FacilityLocationProblem:
    capacities: tuple[float, ...]
    fixed_costs: tuple[float, ...]
    demands: tuple[float, ...]
    # Indexed by customer first, then facility; costs cover the entire demand.
    allocation_costs: tuple[tuple[float, ...], ...]

    def __post_init__(self) -> None:
        for name in ("capacities", "fixed_costs", "demands"):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        object.__setattr__(self, "allocation_costs", tuple(tuple(row) for row in self.allocation_costs))
        m, n = len(self.capacities), len(self.demands)
        if not m or not n or len(self.fixed_costs) != m:
            raise ValueError("Facility and customer dimensions must be positive and consistent.")
        if len(self.allocation_costs) != n or any(len(row) != m for row in self.allocation_costs):
            raise ValueError("Allocation cost matrix dimensions are inconsistent.")
        for value in (*self.capacities, *self.demands):
            if isinstance(value, bool) or not isfinite(value) or value <= 0:
                raise ValueError("Capacities and demands must be finite and positive.")
        for value in (*self.fixed_costs, *(v for row in self.allocation_costs for v in row)):
            if isinstance(value, bool) or not isfinite(value) or value < 0:
                raise ValueError("Costs must be finite and nonnegative.")