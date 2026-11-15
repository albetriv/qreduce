"""Deterministic, instance-normalized heuristic redundancy graph."""

from dataclasses import dataclass
from math import isfinite

from qreduce.mwis import ReductionGraph

from .models import FacilityLocationProblem


@dataclass(frozen=True, slots=True)
class FacilityLocationGraphPolicy:
    alpha: float = 0.5
    epsilon: float = 0.01
    profile_fraction: float = 0.5
    overlap_threshold: float = 0.5
    capacity_difference: float = 0.25
    policy_version: str = "1"

    def __post_init__(self):
        for name in ("alpha", "epsilon", "profile_fraction", "overlap_threshold", "capacity_difference"):
            value = getattr(self, name)
            if not isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f"{name} must be in [0, 1]")
        if self.epsilon == 0 or self.profile_fraction == 0:
            raise ValueError("epsilon and profile_fraction must be positive")

    def build(self, problem: FacilityLocationProblem, available: tuple[int, ...]) -> ReductionGraph:
        demand = sum(problem.demands)
        useful = [min(capacity, demand) for capacity in problem.capacities]
        proxy = [problem.fixed_costs[i] + useful[i] * sum(row[i] for row in problem.allocation_costs) / demand for i in range(len(useful))]
        max_proxy = max(proxy)
        weights = [self.epsilon + (1 - self.epsilon) * (self.alpha * useful[i] / max(useful) + (1 - self.alpha) * (1 - proxy[i] / max_proxy if max_proxy else 1)) for i in range(len(useful))]
        profiles = []
        for i in range(len(useful)):
            selected = set()
            accumulated = 0.0
            for j in sorted(range(len(problem.demands)), key=lambda j: (problem.allocation_costs[j][i] / problem.demands[j], j)):
                selected.add(j)
                accumulated += problem.demands[j]
                if accumulated >= self.profile_fraction * demand:
                    break
            profiles.append(selected)
        ids = tuple(f"facility_{i:08d}" for i in available)
        edges = []
        for position, i in enumerate(available):
            for k in available[position + 1:]:
                overlap = sum(problem.demands[j] for j in profiles[i] & profiles[k]) / sum(problem.demands[j] for j in profiles[i] | profiles[k])
                difference = abs(problem.capacities[i] - problem.capacities[k]) / max(problem.capacities[i], problem.capacities[k])
                if overlap >= self.overlap_threshold and difference <= self.capacity_difference:
                    edges.append(tuple(sorted((f"facility_{i:08d}", f"facility_{k:08d}"))))
        edges = tuple(sorted(edges))
        return ReductionGraph(ids, {node: weights[i] for node, i in zip(ids, available, strict=True)}, edges, {edge: "heuristic profile overlap and similar capacity" for edge in edges}, "facility-redundancy", self.policy_version)