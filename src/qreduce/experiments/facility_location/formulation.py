"""Provider-neutral fractional facility location MILP."""

from dataclasses import dataclass

from qreduce.solving.residual import (
    ClassicalOptimizationModel,
    ClassicalVariable,
    ClassicalVariableType,
    LinearConstraint,
    LinearConstraintSense,
)

from .models import FacilityLocationProblem


def delta_name(i: int) -> str:
    return f"delta_{i}"


def x_name(i: int, j: int) -> str:
    return f"x_{i}_{j}"


@dataclass(frozen=True, slots=True)
class FacilityLocationResidualProblem:
    original_problem: FacilityLocationProblem
    excluded_facilities: tuple[int, ...] = ()

    def build_classical_model(self) -> ClassicalOptimizationModel:
        p = self.original_problem
        m, n = len(p.capacities), len(p.demands)
        excluded = tuple(self.excluded_facilities)
        if len(set(excluded)) != len(excluded) or any(i < 0 or i >= m for i in excluded):
            raise ValueError("Invalid excluded facilities.")
        variables = tuple(ClassicalVariable(delta_name(i), ClassicalVariableType.BINARY, 0, 1) for i in range(m))
        variables += tuple(ClassicalVariable(x_name(i, j), ClassicalVariableType.CONTINUOUS, 0, 1) for i in range(m) for j in range(n))
        objective = {delta_name(i): p.fixed_costs[i] for i in range(m)}
        objective.update({x_name(i, j): p.allocation_costs[j][i] for i in range(m) for j in range(n)})
        constraints = [LinearConstraint(f"demand_{j}", {x_name(i, j): 1 for i in range(m)}, LinearConstraintSense.EQUAL, 1) for j in range(n)]
        for i in range(m):
            coefficients = {x_name(i, j): p.demands[j] for j in range(n)}
            coefficients[delta_name(i)] = -p.capacities[i]
            constraints.append(LinearConstraint(f"capacity_{i}", coefficients, LinearConstraintSense.LESS_EQUAL, 0))
            for j in range(n):
                constraints.append(LinearConstraint(f"link_{i}_{j}", {x_name(i, j): 1, delta_name(i): -1}, LinearConstraintSense.LESS_EQUAL, 0))
        for i in excluded:
            for name in (delta_name(i), *(x_name(i, j) for j in range(n))):
                constraints.append(LinearConstraint(f"fix_{name}", {name: 1}, LinearConstraintSense.EQUAL, 0))
        return ClassicalOptimizationModel(variables, objective, linear_constraints=tuple(constraints))