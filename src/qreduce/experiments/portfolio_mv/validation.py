"""Shared validation utilities for portfolio_mv experiment parameters."""

import math


def validate_risk_aversion(value: object, *, context: str = "risk_aversion") -> float:
    """Validate risk_aversion parameter and return it as float.

    Args:
        value: The value to validate
        context: Name to use in error messages (default: "risk_aversion")

    Returns:
        The validated value as float

    Raises:
        TypeError: If value is None, bool, or non-numeric type
        ValueError: If value is NaN, infinity, zero, or negative
    """
    if value is None:
        raise TypeError(f"{context} cannot be None.")
    if isinstance(value, bool):
        raise TypeError(f"{context} must be a numeric value, not a boolean.")
    if not isinstance(value, (int, float)):
        raise TypeError(f"{context} must be a numeric value, got {type(value).__name__}.")
    if not math.isfinite(value):
        raise ValueError(f"{context} must be finite (not NaN or infinity).")
    if value <= 0:
        raise ValueError(f"{context} must be strictly positive.")
    return float(value)
