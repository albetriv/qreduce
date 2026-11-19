"""Sharpe ratio transformation and solution reconstruction.

This module handles:
- Transformation from max-Sharpe to min-variance QP
- Solution recovery: x = x_scaled / x_scale
- Sharpe ratio calculation: SR = 1 / sqrt(objective)
- Portfolio metrics computation

Mathematical background:

Original problem:
    max SR(x) = (mu^T x - r_f) / sqrt(x^T Sigma x)
    s.t. sum_i x_i = 1, x_i >= 0

With r_f = 0 (or absorbed into mu), and all mu_i > 0:

Let x_scale = 1 / (mu^T x). Since all mu_i > 0 and sum x_i = 1,
we have mu^T x > 0, so x_scale is well-defined and positive.

Define x_scaled_i = x_scale * x_i. Then:
    mu^T x_scaled = mu^T (x_scale * x) = x_scale * mu^T x = 1
    sum_i x_scaled_i = x_scale * sum_i x_i = x_scale

The variance in scaled variables:
    x^T Sigma x = (x_scaled / x_scale)^T Sigma (x_scaled / x_scale)
                = x_scaled^T Sigma x_scaled / x_scale^2

The Sharpe ratio:
    SR = mu^T x / sqrt(x^T Sigma x)
       = (1/x_scale) / sqrt(x_scaled^T Sigma x_scaled / x_scale^2)
       = (1/x_scale) * x_scale / sqrt(x_scaled^T Sigma x_scaled)
       = 1 / sqrt(x_scaled^T Sigma x_scaled)

Therefore maximizing SR is equivalent to minimizing x_scaled^T Sigma x_scaled.

Bounds on x_scale:
    Since x_i >= 0 and sum x_i = 1, we have:
        mu_min <= mu^T x <= mu_max
    Therefore:
        1/mu_max <= x_scale <= 1/mu_min
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np

from qreduce.experiments.portfolio_sr.models import SharpePortfolioProblem


@dataclass(frozen=True, slots=True)
class PortfolioMetrics:
    """Computed portfolio metrics from weights."""

    expected_return: float
    volatility: float
    sharpe_ratio: float
    effective_positions: int
    max_weight: float
    sector_exposures: Mapping[str, float]


@dataclass(frozen=True, slots=True)
class SolutionReconstruction:
    """Reconstructed portfolio from transformed solution."""

    original_weights: Mapping[str, float]
    scaled_weights: Mapping[str, float]
    x_scale: float
    objective_value: float
    metrics: PortfolioMetrics
    reconstruction_tolerance: float
    is_valid: bool
    validation_messages: tuple[str, ...]


def compute_portfolio_metrics(
    problem: SharpePortfolioProblem,
    weights: Mapping[str, float],
    *,
    weight_tolerance: float = 1e-9,
) -> PortfolioMetrics:
    """Compute portfolio metrics from weights.

    Args:
        problem: The optimization problem.
        weights: Portfolio weights indexed by ticker.
        weight_tolerance: Minimum weight to count as a position.

    Returns:
        PortfolioMetrics with return, volatility, Sharpe, etc.
    """
    tickers = problem.tickers
    len(tickers)

    # Extract weight vector
    w = np.array([weights[t] for t in tickers])

    # Expected return
    mu = np.array([problem.mean_returns[t] for t in tickers])
    expected_return = float(np.dot(mu, w))

    # Volatility
    cov = np.array(problem.covariance)
    variance = float(w @ cov @ w)
    volatility = math.sqrt(variance) if variance > 0 else 0.0

    # Sharpe ratio (with risk-free rate)
    excess_return = expected_return - problem.risk_free_rate
    sharpe_ratio = excess_return / volatility if volatility > 0 else 0.0

    # Effective positions
    effective_positions = sum(1 for x in w if x > weight_tolerance)

    # Max weight
    max_weight = float(np.max(w))

    # Sector exposures
    sector_exposures: dict[str, float] = {}
    for ticker, weight in weights.items():
        sector = problem.sectors[ticker]
        sector_exposures[sector] = sector_exposures.get(sector, 0.0) + weight

    return PortfolioMetrics(
        expected_return=expected_return,
        volatility=volatility,
        sharpe_ratio=sharpe_ratio,
        effective_positions=effective_positions,
        max_weight=max_weight,
        sector_exposures=sector_exposures,
    )


def reconstruct_solution(
    problem: SharpePortfolioProblem,
    variable_values: Mapping[str, float],
    *,
    x_scale_name: str = "x_scale",
    x_scaled_prefix: str = "x_scaled__",
    tolerance: float = 1e-6,
) -> SolutionReconstruction:
    """Reconstruct original weights from transformed solution.

    Args:
        problem: The original Sharpe portfolio problem.
        variable_values: Solution values from the solver.
        x_scale_name: Name of the scale variable.
        x_scaled_prefix: Prefix for scaled weight variables.
        tolerance: Tolerance for validation checks.

    Returns:
        SolutionReconstruction with original weights and metrics.
    """
    messages: list[str] = []
    is_valid = True

    # Extract x_scale
    if x_scale_name not in variable_values:
        return SolutionReconstruction(
            original_weights={},
            scaled_weights={},
            x_scale=0.0,
            objective_value=float("nan"),
            metrics=PortfolioMetrics(0, 0, 0, 0, 0, {}),
            reconstruction_tolerance=tolerance,
            is_valid=False,
            validation_messages=(f"Missing variable: {x_scale_name}",),
        )

    x_scale = variable_values[x_scale_name]

    if not math.isfinite(x_scale) or x_scale <= 0:
        return SolutionReconstruction(
            original_weights={},
            scaled_weights={},
            x_scale=x_scale,
            objective_value=float("nan"),
            metrics=PortfolioMetrics(0, 0, 0, 0, 0, {}),
            reconstruction_tolerance=tolerance,
            is_valid=False,
            validation_messages=(f"Invalid x_scale: {x_scale}",),
        )

    # Extract scaled weights
    scaled_weights: dict[str, float] = {}
    original_weights: dict[str, float] = {}

    for ticker in problem.tickers:
        var_name = f"{x_scaled_prefix}{ticker}"
        if var_name not in variable_values:
            messages.append(f"Missing variable: {var_name}")
            is_valid = False
            continue

        x_scaled = variable_values[var_name]
        if not math.isfinite(x_scaled):
            messages.append(f"Non-finite value for {var_name}: {x_scaled}")
            is_valid = False
            x_scaled = 0.0

        scaled_weights[ticker] = x_scaled
        original_weights[ticker] = x_scaled / x_scale

    if not is_valid:
        return SolutionReconstruction(
            original_weights=original_weights,
            scaled_weights=scaled_weights,
            x_scale=x_scale,
            objective_value=float("nan"),
            metrics=PortfolioMetrics(0, 0, 0, 0, 0, {}),
            reconstruction_tolerance=tolerance,
            is_valid=False,
            validation_messages=tuple(messages),
        )

    # Validate return normalization: mu^T x_scaled = 1
    return_sum = sum(
        problem.mean_returns[t] * scaled_weights[t]
        for t in problem.tickers
    )
    if abs(return_sum - 1.0) > tolerance:
        messages.append(f"Return normalization violated: mu^T x_scaled = {return_sum:.6g} (expected 1)")
        is_valid = False

    # Validate budget: sum x_scaled = x_scale
    weight_sum = sum(scaled_weights.values())
    if abs(weight_sum - x_scale) > tolerance:
        messages.append(f"Budget link violated: sum(x_scaled) = {weight_sum:.6g}, x_scale = {x_scale:.6g}")
        is_valid = False

    # Validate original budget: sum x = 1
    original_sum = sum(original_weights.values())
    if abs(original_sum - 1.0) > tolerance:
        messages.append(f"Original budget violated: sum(x) = {original_sum:.6g} (expected 1)")
        is_valid = False

    # Validate non-negativity
    for ticker, weight in original_weights.items():
        if weight < -tolerance:
            messages.append(f"Negative weight for {ticker}: {weight:.6g}")
            is_valid = False

    # Compute objective value
    objective_value = compute_transformed_objective(problem, scaled_weights)

    # Compute metrics
    metrics = compute_portfolio_metrics(problem, original_weights)

    return SolutionReconstruction(
        original_weights=original_weights,
        scaled_weights=scaled_weights,
        x_scale=x_scale,
        objective_value=objective_value,
        metrics=metrics,
        reconstruction_tolerance=tolerance,
        is_valid=is_valid,
        validation_messages=tuple(messages),
    )


def compute_transformed_objective(
    problem: SharpePortfolioProblem,
    scaled_weights: Mapping[str, float],
) -> float:
    """Compute the transformed objective x_scaled^T Sigma x_scaled.

    Args:
        problem: The optimization problem.
        scaled_weights: Scaled weights indexed by ticker.

    Returns:
        The quadratic objective value.
    """
    tickers = problem.tickers
    len(tickers)

    x = np.array([scaled_weights[t] for t in tickers])
    cov = np.array(problem.covariance)

    return float(x @ cov @ x)


def sharpe_from_objective(objective_value: float) -> float:
    """Recover Sharpe ratio from transformed objective value.

    SR = 1 / sqrt(objective_value)

    Args:
        objective_value: The minimized quadratic objective.

    Returns:
        The Sharpe ratio.
    """
    if objective_value <= 0:
        return float("inf") if objective_value == 0 else float("nan")
    return 1.0 / math.sqrt(objective_value)


def validate_x_scale_bounds(
    problem: SharpePortfolioProblem,
    x_scale: float,
    *,
    tolerance: float = 1e-9,
) -> tuple[bool, str | None]:
    """Validate that x_scale is within theoretical bounds.

    Args:
        problem: The optimization problem.
        x_scale: The scale variable value.
        tolerance: Tolerance for bound checking.

    Returns:
        Tuple of (is_valid, error_message).
    """
    lb, ub = problem.x_scale_bounds

    if x_scale < lb - tolerance:
        return False, f"x_scale ({x_scale:.6g}) below lower bound ({lb:.6g})"
    if x_scale > ub + tolerance:
        return False, f"x_scale ({x_scale:.6g}) above upper bound ({ub:.6g})"

    return True, None


def validate_sector_constraints(
    problem: SharpePortfolioProblem,
    weights: Mapping[str, float],
    *,
    tolerance: float = 1e-6,
) -> tuple[bool, list[str]]:
    """Validate sector constraint satisfaction.

    Args:
        problem: The optimization problem with sector constraints.
        weights: Portfolio weights indexed by ticker.
        tolerance: Tolerance for constraint checking.

    Returns:
        Tuple of (all_satisfied, list_of_violations).
    """
    if problem.sector_constraints is None:
        return True, []

    violations: list[str] = []

    # Compute sector exposures
    sector_exposures: dict[str, float] = {}
    for ticker, weight in weights.items():
        sector = problem.sectors[ticker]
        sector_exposures[sector] = sector_exposures.get(sector, 0.0) + weight

    # Check constraints
    for sector in problem.sector_constraints.sectors:
        exposure = sector_exposures.get(sector, 0.0)
        min_val = problem.sector_constraints.sector_min[sector]
        max_val = problem.sector_constraints.sector_max[sector]

        if exposure < min_val - tolerance:
            violations.append(
                f"Sector {sector}: exposure {exposure:.4f} below minimum {min_val:.4f}"
            )
        if exposure > max_val + tolerance:
            violations.append(
                f"Sector {sector}: exposure {exposure:.4f} above maximum {max_val:.4f}"
            )

    return len(violations) == 0, violations


def validate_cardinality_constraint(
    problem: SharpePortfolioProblem,
    weights: Mapping[str, float],
    delta_values: Mapping[str, float] | None = None,
    *,
    weight_tolerance: float = 1e-9,
    integrality_tolerance: float = 1e-6,
) -> tuple[bool, str | None]:
    """Validate cardinality constraint satisfaction.

    Args:
        problem: The optimization problem.
        weights: Portfolio weights indexed by ticker.
        delta_values: Binary selection variables if available.
        weight_tolerance: Minimum weight to count as invested.
        integrality_tolerance: Tolerance for binary variable check.

    Returns:
        Tuple of (is_valid, error_message).
    """
    if problem.max_positions is None:
        return True, None

    # Count positions based on weights
    position_count = sum(1 for w in weights.values() if w > weight_tolerance)

    if position_count > problem.max_positions:
        return False, (
            f"Cardinality violation: {position_count} positions exceed "
            f"maximum {problem.max_positions}"
        )

    # If delta values provided, validate integrality and consistency
    if delta_values is not None:
        selected_count = 0
        for ticker in problem.tickers:
            if ticker not in delta_values:
                continue

            delta = delta_values[ticker]

            # Check integrality
            if abs(delta - round(delta)) > integrality_tolerance:
                return False, f"Non-integral delta for {ticker}: {delta:.6g}"

            is_selected = round(delta) == 1
            has_weight = weights.get(ticker, 0.0) > weight_tolerance

            if is_selected:
                selected_count += 1

            # If selected but not invested: allowed (delta=1, x=0)
            # If invested but not selected: violation
            if has_weight and not is_selected:
                return False, f"Weight without selection for {ticker}"

        if selected_count > problem.max_positions:
            return False, (
                f"Selection count {selected_count} exceeds maximum {problem.max_positions}"
            )

    return True, None


def compute_retention_scores(
    problem: SharpePortfolioProblem,
    *,
    score_type: str = "individual_sharpe",
    normalize: bool = True,
) -> dict[str, float]:
    """Compute node weights for MWIS graph.

    Args:
        problem: The Sharpe portfolio problem.
        score_type: Type of score to compute.
            - "individual_sharpe": mu_i / sigma_i
            - "uniform": equal weights
        normalize: Whether to normalize by maximum.

    Returns:
        Dictionary of ticker -> score.
    """
    scores: dict[str, float] = {}

    if score_type == "uniform":
        for ticker in problem.tickers:
            scores[ticker] = 1.0
    elif score_type == "individual_sharpe":
        for ticker in problem.tickers:
            sr = problem.sharpe_ratio(ticker)
            scores[ticker] = max(sr, 0.0)  # Ensure non-negative
    else:
        raise ValueError(f"Unknown score_type: {score_type}")

    # Normalize by maximum
    if normalize and scores:
        max_score = max(scores.values())
        if max_score > 0:
            scores = {t: s / max_score for t, s in scores.items()}

    return scores
