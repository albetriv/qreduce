"""Facility location adapter for the shared QReduce pipeline."""

import math
from time import perf_counter

from qreduce.domains.contracts import (
    DomainEvaluationMetric,
    DomainValidationResult,
    FinalSolutionValidationResult,
    FixingEntry,
    FixingManifest,
    LogicalVariableCounts,
)

from .formulation import FacilityLocationResidualProblem, delta_name, x_name
from .graph_policy import FacilityLocationGraphPolicy
from .postcheck import validate_solution


def _id(i):
    return f"facility_{i:08d}"


def _validate_manifest(problem, manifest, available, retained):
    """Require exactly the domain's complete, zero-valued linked fixings."""
    if set(manifest.retained_item_ids) != set(retained):
        raise ValueError("Manifest retained items do not match candidate domain")
    if not set(retained) <= set(available):
        raise ValueError("Manifest contains unknown retained items")
    expected_excluded = set(available) - set(retained)
    if set(manifest.excluded_item_ids) != expected_excluded:
        raise ValueError("Manifest exclusions do not match candidate domain")
    indices = {_id(i): i for i in range(len(problem.capacities))}
    for entry in manifest.entries:
        if entry.item_id not in indices:
            raise ValueError("Manifest contains unknown facility")
        i = indices[entry.item_id]
        expected = {delta_name(i), *(x_name(i, j) for j in range(len(problem.demands)))}
        if set(entry.variable_values) != expected or any(value != 0 for value in entry.variable_values.values()):
            raise ValueError("Manifest must fix each excluded facility and all linked allocations to zero")


class FacilityLocationAdapter:
    def __init__(self, policy=None, *, protect_all=False, timing_metadata=None):
        self.policy = policy or FacilityLocationGraphPolicy()
        self.protect_all = protect_all
        self.graph_build_seconds = 0.0
        self.timing_metadata = timing_metadata

    def describe_input(self, problem):
        return problem

    def identify_reducible_items(self, problem):
        original = getattr(problem, "original_problem", problem)
        excluded = set(getattr(problem, "excluded_facilities", ()))
        return [_id(i) for i in range(len(original.capacities)) if i not in excluded]

    def describe_logical_variables(self, problem):
        original = getattr(problem, "original_problem", problem)
        count = len(self.identify_reducible_items(problem))
        return LogicalVariableCounts(count, 0, count * len(original.demands))

    def build_conflict_graph(self, problem, state=None):
        original = getattr(problem, "original_problem", problem)
        started = perf_counter()
        try:
            return self.policy.build(original, tuple(int(item[9:]) for item in self.identify_reducible_items(problem)))
        finally:
            self.graph_build_seconds += perf_counter() - started
            if self.timing_metadata is not None:
                self.timing_metadata["graph_build_seconds"] = self.graph_build_seconds

    def declare_protected_items(self, problem):
        original = getattr(problem, "original_problem", problem)
        available = self.identify_reducible_items(problem)
        total = sum(original.capacities[int(item[9:])] for item in available)
        demand = sum(original.demands)
        return tuple(item for item in available if self.protect_all or total - original.capacities[int(item[9:])] < demand - 1e-6)

    def validate_candidate_domain(self, problem, retained_item_ids):
        original = getattr(problem, "original_problem", problem)
        available = self.identify_reducible_items(problem)
        retained = tuple(retained_item_ids)
        if len(set(retained)) != len(retained) or not set(retained) <= set(available):
            return DomainValidationResult(False, None, ("invalid_retained_items",))
        demand = sum(original.demands)
        ordered = sorted((original.capacities[int(item[9:])] for item in available), reverse=True)
        cumulative = 0
        minimum = len(ordered)
        for count, capacity in enumerate(ordered, 1):
            cumulative += capacity
            if cumulative >= demand - 1e-6:
                minimum = count
                break
        if sum(original.capacities[int(item[9:])] for item in retained) < demand - 1e-6:
            return DomainValidationResult(False, minimum, ("insufficient_capacity",))
        return DomainValidationResult(True, minimum)

    def build_fixing_manifest(self, problem, retained_item_ids):
        if not self.validate_candidate_domain(problem, retained_item_ids).is_valid:
            raise ValueError("Invalid candidate domain")
        original = getattr(problem, "original_problem", problem)
        excluded = tuple(item for item in self.identify_reducible_items(problem) if item not in retained_item_ids)
        entries = []
        for item in excluded:
            i = int(item[9:])
            values = {delta_name(i): 0.0, **{x_name(i, j): 0.0 for j in range(len(original.demands))}}
            entries.append(FixingEntry(item, values, "mis_heuristic_exclusion"))
        return FixingManifest(tuple(retained_item_ids), excluded, tuple(entries), "heuristic_candidate_domain", {"optimality_preservation_claim": "none"}, policy_version=self.policy.policy_version)

    def restrict_problem(self, problem, retained_item_ids, fixing_manifest):
        if not self.validate_candidate_domain(problem, retained_item_ids).is_valid:
            raise ValueError("Invalid candidate domain")
        original = getattr(problem, "original_problem", problem)
        available = self.identify_reducible_items(problem)
        _validate_manifest(original, fixing_manifest, available, retained_item_ids)
        previously_excluded = set(getattr(problem, "excluded_facilities", ()))
        excluded = tuple(i for i in range(len(original.capacities)) if i in previously_excluded or _id(i) in fixing_manifest.excluded_item_ids)
        return FacilityLocationResidualProblem(original, excluded)

    def validate_final_solution(self, original_problem, solution, fixing_manifest, tolerances, solver_objective_value=None):
        available = tuple(_id(i) for i in range(len(original_problem.capacities)))
        try:
            _validate_manifest(original_problem, fixing_manifest, available, fixing_manifest.retained_item_ids)
        except ValueError as error:
            return FinalSolutionValidationResult(False, False, False, False, None, None, (f"invalid_manifest:{error}",))
        excluded = tuple(int(item[9:]) for item in fixing_manifest.excluded_item_ids)
        result = validate_solution(original_problem, solution, excluded=excluded, tolerance=tolerances.primal_feasibility_tolerance, integrality_tolerance=tolerances.integrality_tolerance)
        reasons = list(result.violations)
        for entry in fixing_manifest.entries:
            for name, expected in entry.variable_values.items():
                actual = solution.get(name)
                if not isinstance(actual, int | float) or isinstance(actual, bool) or not math.isfinite(actual) or abs(actual - expected) > tolerances.primal_feasibility_tolerance:
                    reasons.append(f"fixing:{name}")
        integral = not any(reason.startswith("binary:") for reason in reasons)
        fixed = not any(reason.startswith("fixing:") for reason in reasons)
        constraints = not any(not reason.startswith(("binary:", "fixing:")) for reason in reasons)
        if result.objective is None:
            integral = fixed = constraints = False
        objective_ok = None
        if solver_objective_value is not None:
            objective_ok = result.objective is not None and math.isfinite(solver_objective_value) and abs(result.objective - solver_objective_value) <= tolerances.objective_recomputation_absolute_tolerance + tolerances.objective_recomputation_relative_tolerance * max(abs(result.objective), abs(solver_objective_value))
            if not objective_ok:
                reasons.append("objective")
        return FinalSolutionValidationResult(not reasons, fixed, constraints, integral, result.objective, objective_ok, tuple(reasons))

    def evaluate_domain_metrics(self, problem, classical_result, postcheck_result):
        if not postcheck_result.postcheck_feasible:
            return ()
        values = classical_result.variable_values
        opened = [i for i in range(len(problem.capacities)) if values[delta_name(i)] > 0.5]
        fixed = sum(problem.fixed_costs[i] * values[delta_name(i)] for i in range(len(problem.capacities)))
        allocation = sum(problem.allocation_costs[j][i] * values[x_name(i, j)] for i in range(len(problem.capacities)) for j in range(len(problem.demands)))
        capacity = sum(problem.capacities[i] for i in opened)
        split = sum(sum(values[x_name(i, j)] > 1e-6 for i in range(len(problem.capacities))) > 1 for j in range(len(problem.demands)))
        data = {"open_facilities": len(opened), "fixed_cost": fixed, "allocation_cost": allocation, "open_capacity": capacity, "capacity_utilization": sum(problem.demands) / capacity if capacity else 0, "split_customers": split, "graph_build_seconds": self.graph_build_seconds}
        return tuple(DomainEvaluationMetric(name, value, "count" if name in {"open_facilities", "split_customers"} else "seconds" if name == "graph_build_seconds" else "value", "descriptive", "facility-location-v1") for name, value in data.items())