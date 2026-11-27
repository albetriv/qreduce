"""Post-check validation for Sharpe portfolio solutions.

This module validates final solutions from the classical solver:
- Value integrity: finite, positive scale, proper bounds
- Return normalization: mu^T x_scaled = 1
- Budget constraint: sum x = 1
- Upper bounds: x_i <= upper_i
- Sector constraints: min_s <= sum_{i in s} x_i <= max_s
- Selection: binary domain, cardinality limits, conditional investment floors
- Fixing compliance: excluded tickers have zero weight
- Objective verification: recomputed vs solver-reported

The post-check does NOT:
- Rinormalize or correct weights silently
- Hide constraint violations
- Certify optimality (only feasibility)
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

from qreduce.domains.contracts import (
    FinalSolutionValidationResult,
    FixingManifest,
)
from qreduce.experiments.portfolio_sr.formulation import (
    compute_portfolio_metrics,
    compute_transformed_objective,
    sharpe_from_objective,
    validate_sector_constraints,
    validate_x_scale_bounds,
)
from qreduce.experiments.portfolio_sr.models import (
    SharpePortfolioProblem,
    SharpeVariableMapping,
    TransformedSharpeProblem,
)
from qreduce.models import ClassicalSolveOptions
from qreduce.status import PostcheckMode


@dataclass(frozen=True, slots=True)
class PostcheckResult:
    """Detailed post-check validation result."""

    is_valid: bool
    messages: tuple[str, ...]
    original_weights: Mapping[str, float] | None
    scaled_weights: Mapping[str, float] | None
    x_scale: float | None
    objective_value: float | None
    sharpe_ratio: float | None
    expected_return: float | None
    volatility: float | None
    position_count: int | None
    sector_exposures: Mapping[str, float] | None


def _validate_binary_variable(
    value: float,
    ticker: str,
    integrality_tolerance: float,
) -> tuple[bool, str | None]:
    """Validate that a binary variable is in {0, 1}.

    Checks:
    1. Value is finite
    2. Value rounds to either 0 or 1
    3. Value is within integrality tolerance of 0 or 1

    Returns:
        (is_valid, error_message)
    """
    if not math.isfinite(value):
        return False, f"delta_{ticker}={value} is not finite"

    rounded = round(value)
    if rounded not in (0, 1):
        return False, f"delta_{ticker}={value} rounds to {rounded}, not in {{0, 1}}"

    distance = abs(value - rounded)
    if distance > integrality_tolerance:
        return False, f"delta_{ticker}={value} violates integrality (distance={distance:.6g})"

    return True, None


def _validate_cardinality_constraint_strict(
    problem: SharpePortfolioProblem,
    original_weights: Mapping[str, float],
    delta_values: Mapping[str, float],
    weight_tolerance: float,
    integrality_tolerance: float,
) -> tuple[bool, list[str], int | None]:
    """Return binary compliance, constraint messages, and the count when known."""
    messages: list[str] = []

    # Validate each delta is binary
    selected_count = 0
    integrality_compliant = True
    for ticker in problem.tickers:
        if ticker not in delta_values:
            messages.append(f"missing_delta:{ticker}")
            integrality_compliant = False
            continue

        delta = delta_values[ticker]
        valid, error = _validate_binary_variable(delta, ticker, integrality_tolerance)
        if not valid:
            messages.append(error or f"invalid_delta:{ticker}")
            integrality_compliant = False
            continue

        delta_rounded = round(delta)
        weight = original_weights.get(ticker, 0.0)

        # A zero-weight asset can be selected if its floor is zero.
        if delta_rounded == 1:
            selected_count += 1
            if weight < problem.effective_lower_bound(ticker) - weight_tolerance:
                messages.append(f"lower_bound_violated:{ticker}:weight={weight:.6g}")

        # Consistency checks
        if weight > weight_tolerance and delta_rounded == 0:
            messages.append(
                f"weight_delta_inconsistent:{ticker} has weight={weight:.6g} but delta=0"
            )
        if delta_rounded == 0 and weight > weight_tolerance:
            messages.append(
                f"delta_zero_with_weight:{ticker} has delta=0 but weight={weight:.6g}"
            )

    if (integrality_compliant and problem.min_selected_assets is not None
            and selected_count < problem.min_selected_assets):
        messages.append(
            f"min_cardinality_violation:selected={selected_count}<min={problem.min_selected_assets}"
        )
    if problem.max_positions is not None and selected_count > problem.max_positions:
        messages.append(
            f"cardinality_exceeded:active={selected_count}>max={problem.max_positions}"
        )

    return integrality_compliant, messages, selected_count if integrality_compliant else None


def validate_sharpe_solution(
    problem: SharpePortfolioProblem | TransformedSharpeProblem,
    variable_values: Mapping[str, float],
    fixing_manifest: FixingManifest,
    tolerances: ClassicalSolveOptions,
    solver_objective_value: float | None = None,
) -> FinalSolutionValidationResult:
    """Validate a Sharpe portfolio solution.

    Performs comprehensive validation in phases:
    1. Variable presence - all required variables exist
    2. Value finiteness - no NaN/Inf
    3. Binary domain - delta variables in {0, 1}
    4. Transformed constraints - return normalization, scale bounds
    5. Original constraints - budget, bounds, sectors, cardinality
    6. Fixing compliance - excluded variables are fixed
    7. Objective verification - recomputed vs solver

    Args:
        problem: The original Sharpe portfolio problem, or TransformedSharpeProblem.
        variable_values: Solution variable values from solver.
        fixing_manifest: Cumulative fixing manifest.
        tolerances: Tolerance settings for validation.
        solver_objective_value: Objective value reported by solver.

    Returns:
        FinalSolutionValidationResult with compliance flags and diagnostics.
    """
    # Extract original problem if transformed
    if isinstance(problem, TransformedSharpeProblem):
        original_problem = problem.original_problem
    else:
        original_problem = problem

    messages: list[str] = []
    is_valid = True
    fixing_compliant = True
    constraint_compliant = True
    integrality_compliant = True

    mapping = SharpeVariableMapping.for_problem(original_problem)
    tol = tolerances.primal_feasibility_tolerance
    int_tol = tolerances.integrality_tolerance

    # Phase 1: Variable presence - x_scale
    x_scale_name = mapping.x_scale_variable
    if x_scale_name not in variable_values:
        return FinalSolutionValidationResult(
            postcheck_feasible=False,
            fixed_variable_compliance=True,
            original_constraint_compliance=False,
            integrality_compliance=True,
            objective_recomputed=None,
            solver_objective_compliance=None,
            failure_reasons=(f"missing_variable:{x_scale_name}",),
            tolerances_used=_build_tolerances_map(tolerances),
        )

    x_scale = variable_values[x_scale_name]

    # Phase 2: Finiteness - x_scale
    if not math.isfinite(x_scale):
        return FinalSolutionValidationResult(
            postcheck_feasible=False,
            fixed_variable_compliance=True,
            original_constraint_compliance=False,
            integrality_compliance=True,
            objective_recomputed=None,
            solver_objective_compliance=None,
            failure_reasons=(f"non_finite_x_scale:{x_scale}",),
            tolerances_used=_build_tolerances_map(tolerances),
        )

    if x_scale <= 0:
        return FinalSolutionValidationResult(
            postcheck_feasible=False,
            fixed_variable_compliance=True,
            original_constraint_compliance=False,
            integrality_compliance=True,
            objective_recomputed=None,
            solver_objective_compliance=None,
            failure_reasons=(f"non_positive_x_scale:{x_scale}",),
            tolerances_used=_build_tolerances_map(tolerances),
        )

    # Phase 1: Variable presence - scaled weights
    scaled_weights: dict[str, float] = {}
    for ticker in original_problem.tickers:
        var_name = mapping.x_scaled_by_ticker[ticker]
        if var_name not in variable_values:
            return FinalSolutionValidationResult(
                postcheck_feasible=False,
                fixed_variable_compliance=True,
                original_constraint_compliance=False,
                integrality_compliance=True,
                objective_recomputed=None,
                solver_objective_compliance=None,
                failure_reasons=(f"missing_variable:{var_name}",),
                tolerances_used=_build_tolerances_map(tolerances),
            )
        scaled_weights[ticker] = variable_values[var_name]

    # Phase 2: Finiteness - scaled weights
    for ticker, value in scaled_weights.items():
        if not math.isfinite(value):
            messages.append(f"non_finite_weight:{ticker}={value}")
            is_valid = False
            constraint_compliant = False

    if not is_valid:
        return FinalSolutionValidationResult(
            postcheck_feasible=False,
            fixed_variable_compliance=True,
            original_constraint_compliance=False,
            integrality_compliance=True,
            objective_recomputed=None,
            solver_objective_compliance=None,
            failure_reasons=tuple(messages),
            tolerances_used=_build_tolerances_map(tolerances),
        )

    # Reconstruct original weights
    original_weights = {t: scaled_weights[t] / x_scale for t in original_problem.tickers}

    # Phase 3: Selection binaries.
    delta_values: dict[str, float] = {}
    deltas = mapping.require_deltas()
    for ticker in original_problem.tickers:
        delta_name = deltas[ticker]
        if delta_name in variable_values:
            delta_values[ticker] = variable_values[delta_name]

    integrality_compliant, card_messages, selected_count = _validate_cardinality_constraint_strict(
        original_problem, original_weights, delta_values, tol, int_tol
    )
    if card_messages:
        messages.extend(card_messages)
        is_valid = False
        if any(m.startswith(("cardinality_exceeded:", "weight_delta_inconsistent:",
                             "delta_zero_with_weight:", "lower_bound_violated:",
                             "min_cardinality_violation:"))
               for m in card_messages):
            constraint_compliant = False

    # Phase 4: Transformed constraints
    # Validate x_scale bounds
    bounds_valid, bounds_message = validate_x_scale_bounds(original_problem, x_scale, tolerance=tol)
    if not bounds_valid:
        messages.append(bounds_message or "x_scale_bounds_violation")
        is_valid = False
        constraint_compliant = False

    # Validate return normalization: mu^T x_scaled = 1
    return_sum = sum(
        original_problem.mean_returns[t] * scaled_weights[t]
        for t in original_problem.tickers
    )
    if abs(return_sum - 1.0) > tol:
        messages.append(f"return_normalization_violated:mu_x_scaled={return_sum:.6g}")
        is_valid = False
        constraint_compliant = False

    # Phase 5: Original constraints
    # Validate budget: sum x = 1
    budget_sum = sum(original_weights.values())
    if abs(budget_sum - 1.0) > tol:
        messages.append(f"budget_violated:sum_x={budget_sum:.6g}")
        is_valid = False
        constraint_compliant = False

    # Validate non-negativity
    for ticker, weight in original_weights.items():
        if weight < -tol:
            messages.append(f"negative_weight:{ticker}={weight:.6g}")
            is_valid = False
            constraint_compliant = False

    # Validate upper bounds
    for ticker in original_problem.tickers:
        weight = original_weights[ticker]
        upper = original_problem.upper_bounds[ticker]
        if weight > upper + tol:
            messages.append(f"upper_bound_violated:{ticker}={weight:.6g}>upper={upper:.6g}")
            is_valid = False
            constraint_compliant = False

    # Validate sector constraints
    if original_problem.sector_constraints is not None:
        sectors_valid, sector_violations = validate_sector_constraints(
            original_problem, original_weights, tolerance=tol
        )
        if not sectors_valid:
            messages.extend(sector_violations)
            is_valid = False
            constraint_compliant = False

    # Phase 6: Fixing compliance
    for entry in fixing_manifest.entries:
        ticker = entry.item_id

        # Check scaled weight is fixed to zero
        x_scaled_name = mapping.x_scaled_by_ticker.get(ticker)
        if x_scaled_name and x_scaled_name in entry.variable_values:
            expected = entry.variable_values[x_scaled_name]
            actual = scaled_weights.get(ticker, 0.0)
            if abs(actual - expected) > tol:
                messages.append(
                    f"fixing_violated:{ticker}:x_scaled={actual:.6g}!=expected={expected:.6g}"
                )
                is_valid = False
                fixing_compliant = False

        # Check any recorded fixing for the selection variable.
        delta_name = deltas.get(ticker)
        if delta_name and delta_name in entry.variable_values:
            expected = entry.variable_values[delta_name]
            actual = delta_values.get(ticker, 0.0)
            if abs(actual - expected) > int_tol:
                messages.append(
                    f"fixing_violated:{ticker}:delta={actual:.6g}!=expected={expected:.6g}"
                )
                is_valid = False
                fixing_compliant = False

    # Phase 7: Objective verification
    objective_value = compute_transformed_objective(original_problem, scaled_weights)
    sharpe_ratio = sharpe_from_objective(objective_value)

    # Compare with solver objective using configured tolerances
    solver_obj_compliant: bool | None = None
    if solver_objective_value is not None:
        abs_diff = abs(objective_value - solver_objective_value)
        rel_diff = abs_diff / max(abs(solver_objective_value), 1e-10)

        abs_ok = abs_diff <= tolerances.objective_recomputation_absolute_tolerance
        rel_ok = rel_diff <= tolerances.objective_recomputation_relative_tolerance

        solver_obj_compliant = abs_ok or rel_ok

        if not solver_obj_compliant:
            messages.append(
                f"objective_mismatch:computed={objective_value:.6g},"
                f"solver={solver_objective_value:.6g},"
                f"abs_diff={abs_diff:.6g},rel_diff={rel_diff:.4%}"
            )
            # In STRICT mode, objective mismatch fails the postcheck
            # In SOLVER_TOLERANCE_ALIGNED mode, it's a warning only
            if tolerances.postcheck_mode == PostcheckMode.STRICT:
                is_valid = False

    # Compute metrics for diagnostics (but don't put in result - use domain_evaluation_metrics)
    metrics = compute_portfolio_metrics(original_problem, original_weights, weight_tolerance=tol)

    # Build tolerances map
    tolerances_map = _build_tolerances_map(tolerances)
    tolerances_map["budget_sum"] = budget_sum
    tolerances_map["return_normalization"] = return_sum
    tolerances_map["objective_recomputed"] = objective_value
    tolerances_map["sharpe_ratio"] = sharpe_ratio
    tolerances_map["x_scale"] = x_scale
    tolerances_map["position_count"] = metrics.effective_positions
    if selected_count is not None:
        tolerances_map["selected_count"] = selected_count

    return FinalSolutionValidationResult(
        postcheck_feasible=is_valid,
        fixed_variable_compliance=fixing_compliant,
        original_constraint_compliance=constraint_compliant,
        integrality_compliance=integrality_compliant,
        objective_recomputed=objective_value,
        solver_objective_compliance=solver_obj_compliant,
        failure_reasons=tuple(messages) if not is_valid else (),
        tolerances_used=tolerances_map,
    )


def _build_tolerances_map(tolerances: ClassicalSolveOptions) -> dict[str, float | str]:
    """Build the tolerances_used map for FinalSolutionValidationResult."""
    return {
        "primal_feasibility": tolerances.primal_feasibility_tolerance,
        "integrality": tolerances.integrality_tolerance,
        "objective_absolute": tolerances.objective_recomputation_absolute_tolerance,
        "objective_relative": tolerances.objective_recomputation_relative_tolerance,
        "postcheck_mode": tolerances.postcheck_mode.value,
    }


def extract_solution_summary(
    problem: SharpePortfolioProblem,
    variable_values: Mapping[str, float],
    *,
    weight_tolerance: float = 1e-9,
    integrality_tolerance: float = 1e-6,
) -> dict[str, object]:
    """Extract summary statistics from a solution.

    Args:
        problem: The original problem.
        variable_values: Solution variable values.
        weight_tolerance: Minimum weight to count as invested.
        integrality_tolerance: Tolerance for counting binary selections.

    Returns:
        Dictionary with key metrics.
    """
    mapping = SharpeVariableMapping.for_problem(problem)

    # Extract x_scale
    x_scale = variable_values.get(mapping.x_scale_variable, 0.0)
    if not math.isfinite(x_scale) or x_scale <= 0:
        return {"error": "invalid_x_scale", "x_scale": x_scale}

    # Extract weights
    scaled_weights: dict[str, float] = {}
    for ticker in problem.tickers:
        var_name = mapping.x_scaled_by_ticker[ticker]
        scaled_weights[ticker] = variable_values.get(var_name, 0.0)

    original_weights = {t: scaled_weights[t] / x_scale for t in problem.tickers}

    # Compute objective
    objective = compute_transformed_objective(problem, scaled_weights)
    sharpe = sharpe_from_objective(objective)

    # Compute metrics
    metrics = compute_portfolio_metrics(
        problem, original_weights, weight_tolerance=weight_tolerance
    )

    # Get invested assets (by weight > tolerance)
    invested_tickers = [
        t for t in problem.tickers
        if original_weights[t] > weight_tolerance
    ]

    summary: dict[str, object] = {
        "x_scale": x_scale,
        "objective_value": objective,
        "sharpe_ratio": sharpe,
        "expected_return": metrics.expected_return,
        "volatility": metrics.volatility,
        "position_count": len(invested_tickers),
        "invested_tickers": invested_tickers,
        "weights": original_weights,
        "sector_exposures": dict(metrics.sector_exposures),
    }
    delta_values = {t: variable_values[var] for t, var in mapping.require_deltas().items()
                    if var in variable_values}
    _, _, selected_count = _validate_cardinality_constraint_strict(
        problem, original_weights, delta_values, weight_tolerance, integrality_tolerance,
    )
    if selected_count is not None:
        summary["selected_count"] = selected_count
    return summary
