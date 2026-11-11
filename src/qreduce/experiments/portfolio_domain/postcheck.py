"""Independent arithmetic validation for portfolio experiment solutions."""

import math
from collections.abc import Mapping

from qreduce.domains.contracts import FinalSolutionValidationResult, FixingManifest
from qreduce.experiments.portfolio_domain.models import (
    PortfolioProblem,
    PortfolioVariableMapping,
)
from qreduce.models import ClassicalSolveOptions


def validate_portfolio_solution(
    problem: PortfolioProblem,
    variable_values: Mapping[str, float],
    fixing_manifest: FixingManifest,
    tolerances: ClassicalSolveOptions,
    solver_objective_value: float | None = None,
) -> FinalSolutionValidationResult:
    """Recompute feasibility and objective without trusting solver status alone."""

    mapping = PortfolioVariableMapping.for_problem(problem)
    values = dict(variable_values)
    reasons: list[str] = []
    fixed_variable_compliance = True
    integrality_compliance = True
    original_constraint_compliance = True
    x_values: dict[str, float] = {}
    for asset_id in problem.asset_ids:
        delta_name = mapping.delta_variable_by_asset[asset_id]
        x_name = mapping.x_variable_by_asset[asset_id]
        delta_value = values.get(delta_name)
        x_value = values.get(x_name)
        if delta_value is None or x_value is None or not math.isfinite(delta_value) or not math.isfinite(x_value):
            reasons.append(f"missing_or_nonfinite_variable:{asset_id}")
            fixed_variable_compliance = False
            integrality_compliance = False
            original_constraint_compliance = False
            continue
        x_values[asset_id] = x_value
        if min(abs(delta_value), abs(delta_value - 1.0)) > tolerances.integrality_tolerance:
            integrality_compliance = False
            reasons.append(f"binary_integrality_violation:{asset_id}")
        if x_value < -tolerances.primal_feasibility_tolerance:
            original_constraint_compliance = False
            reasons.append(f"negative_weight:{asset_id}")
        lower_bound = problem.lower_bounds[asset_id] * delta_value
        upper_bound = problem.upper_bounds[asset_id] * delta_value
        if x_value < lower_bound - tolerances.primal_feasibility_tolerance:
            original_constraint_compliance = False
            reasons.append(f"lower_linking_violation:{asset_id}")
        if x_value > upper_bound + tolerances.primal_feasibility_tolerance:
            original_constraint_compliance = False
            reasons.append(f"upper_linking_violation:{asset_id}")
    for entry in fixing_manifest.entries:
        for variable_name, fixed_value in entry.variable_values.items():
            actual_value = values.get(variable_name)
            if actual_value is None or not math.isfinite(actual_value) or abs(actual_value - fixed_value) > tolerances.primal_feasibility_tolerance:
                fixed_variable_compliance = False
                reasons.append(f"fixing_violation:{entry.item_id}:{variable_name}")
    if len(x_values) == len(problem.asset_ids):
        if abs(sum(x_values.values()) - 1.0) > tolerances.primal_feasibility_tolerance:
            original_constraint_compliance = False
            reasons.append("budget_violation")
        objective_recomputed = _mean_variance_objective(problem, x_values)
    else:
        objective_recomputed = None
    solver_objective_compliance: bool | None = None
    if solver_objective_value is not None:
        if objective_recomputed is None or not math.isfinite(solver_objective_value):
            solver_objective_compliance = False
            reasons.append("solver_objective_unavailable_or_nonfinite")
        else:
            allowed_difference = tolerances.objective_recomputation_absolute_tolerance + (
                tolerances.objective_recomputation_relative_tolerance * max(abs(solver_objective_value), abs(objective_recomputed))
            )
            solver_objective_compliance = abs(solver_objective_value - objective_recomputed) <= allowed_difference
            if not solver_objective_compliance:
                reasons.append("objective_recomputation_mismatch")
    postcheck_feasible = (
        fixed_variable_compliance
        and original_constraint_compliance
        and integrality_compliance
        and solver_objective_compliance is not False
    )
    return FinalSolutionValidationResult(
        postcheck_feasible=postcheck_feasible,
        fixed_variable_compliance=fixed_variable_compliance,
        original_constraint_compliance=original_constraint_compliance,
        integrality_compliance=integrality_compliance,
        objective_recomputed=objective_recomputed,
        solver_objective_compliance=solver_objective_compliance,
        failure_reasons=tuple(sorted(set(reasons))),
        tolerances_used={
            "primal_feasibility_tolerance": tolerances.primal_feasibility_tolerance,
            "integrality_tolerance": tolerances.integrality_tolerance,
            "objective_recomputation_absolute_tolerance": tolerances.objective_recomputation_absolute_tolerance,
            "objective_recomputation_relative_tolerance": tolerances.objective_recomputation_relative_tolerance,
            "postcheck_mode": tolerances.postcheck_mode.value,
        },
    )


def _mean_variance_objective(problem: PortfolioProblem, x_values: Mapping[str, float]) -> float:
    quadratic_term = 0.0
    for left_index, left_asset_id in enumerate(problem.asset_ids):
        for right_index, right_asset_id in enumerate(problem.asset_ids):
            quadratic_term += x_values[left_asset_id] * problem.covariance[left_index][right_index] * x_values[right_asset_id]
    return problem.risk_aversion * quadratic_term - sum(
        problem.expected_returns[asset_id] * x_values[asset_id] for asset_id in problem.asset_ids
    )