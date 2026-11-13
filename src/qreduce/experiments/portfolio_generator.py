"""Deterministic synthetic portfolio data generator.

This module provides a shared generator for creating synthetic portfolio problems
with deterministic, reproducible data. It is used by both the single-pass and
multi-round portfolio experiments.

The generator produces:
- Asset IDs with a consistent naming scheme
- Expected returns following a deterministic pattern
- A positive definite covariance matrix with block equicorrelation structure
- Retention scores for MWIS node weights
- Standard bounds (0.0 to 0.7 per asset)
"""

from dataclasses import dataclass

from qreduce.experiments.portfolio_domain import PortfolioProblem

# The canonical 5-asset dataset used by experiments 01 and 02
_CANONICAL_5_ASSET_IDS = ("asset-a", "asset-b", "asset-c", "asset-d", "asset-e")
_CANONICAL_5_EXPECTED_RETURNS = {
    "asset-a": 0.10,
    "asset-b": 0.08,
    "asset-c": 0.06,
    "asset-d": 0.07,
    "asset-e": 0.05,
}
_CANONICAL_5_COVARIANCE = (
    (0.04, 0.016, 0.0, 0.0, 0.004),
    (0.016, 0.04, -0.012, 0.0, 0.0),
    (0.0, -0.012, 0.04, 0.014, 0.0),
    (0.0, 0.0, 0.014, 0.04, 0.012),
    (0.004, 0.0, 0.0, 0.012, 0.04),
)
_CANONICAL_5_RETENTION_SCORES = {
    "asset-a": 0.9,
    "asset-b": 0.7,
    "asset-c": 0.8,
    "asset-d": 0.6,
    "asset-e": 0.5,
}


@dataclass(frozen=True, slots=True)
class GeneratedPortfolioData:
    """Generated portfolio data with all problem inputs."""

    asset_ids: tuple[str, ...]
    expected_returns: dict[str, float]
    covariance: tuple[tuple[float, ...], ...]
    lower_bounds: dict[str, float]
    upper_bounds: dict[str, float]
    retention_scores: dict[str, float]
    risk_aversion: float = 1.0

    def to_problem(self) -> PortfolioProblem:
        """Convert to a PortfolioProblem instance."""
        return PortfolioProblem(
            asset_ids=self.asset_ids,
            expected_returns=self.expected_returns,
            covariance=self.covariance,
            lower_bounds=self.lower_bounds,
            upper_bounds=self.upper_bounds,
            retention_scores=self.retention_scores,
            risk_aversion=self.risk_aversion,
        )


def generate_portfolio_data(asset_count: int = 5) -> GeneratedPortfolioData:
    """Generate deterministic synthetic portfolio data.

    For asset_count=5, returns the canonical 5-asset dataset used by the original
    experiments. This ensures exact backward compatibility with existing tests,
    notebooks, and reference artifacts.

    For asset_count > 5, generates a larger dataset using a deterministic algorithm:
    - Asset IDs: asset-000, asset-001, ..., asset-{N-1}
    - Expected returns: 0.05 + 0.002 * (i % 20) for diversity
    - Covariance: Block equicorrelation structure with 0.04 variance,
      0.016 correlation within blocks of 3 assets, 0.0 between blocks
    - Retention scores: 1.0 - 0.005 * (i % 100) for MWIS diversity
    - Bounds: [0.0, 0.7] for all assets

    Args:
        asset_count: Number of assets to generate. Must be >= 5.

    Returns:
        GeneratedPortfolioData with all problem inputs.

    Raises:
        ValueError: If asset_count < 5.
    """
    if isinstance(asset_count, bool) or not isinstance(asset_count, int):
        raise TypeError("asset_count must be an integer.")
    if asset_count < 5:
        raise ValueError("asset_count must be at least 5.")

    # For 5 assets, return the canonical dataset exactly
    if asset_count == 5:
        return GeneratedPortfolioData(
            asset_ids=_CANONICAL_5_ASSET_IDS,
            expected_returns=dict(_CANONICAL_5_EXPECTED_RETURNS),
            covariance=_CANONICAL_5_COVARIANCE,
            lower_bounds={asset_id: 0.0 for asset_id in _CANONICAL_5_ASSET_IDS},
            upper_bounds={asset_id: 0.7 for asset_id in _CANONICAL_5_ASSET_IDS},
            retention_scores=dict(_CANONICAL_5_RETENTION_SCORES),
            risk_aversion=1.0,
        )

    # For larger datasets, use the deterministic generator
    asset_ids = tuple(f"asset-{index:03d}" for index in range(asset_count))

    # Expected returns: vary by position for diversity
    expected_returns = {
        asset: 0.05 + 0.002 * (i % 20)
        for i, asset in enumerate(asset_ids)
    }

    # Covariance: block equicorrelation structure
    # - 0.04 on diagonal (variance)
    # - 0.016 for assets in the same block of 3 (positive correlation)
    # - 0.0 for assets in different blocks (independence)
    # This ensures positive definiteness
    covariance = tuple(
        tuple(
            0.04 if i == j else 0.016 if i // 3 == j // 3 else 0.0
            for j in range(asset_count)
        )
        for i in range(asset_count)
    )

    # Bounds: standard [0, 0.7] range
    lower_bounds = {asset: 0.0 for asset in asset_ids}
    upper_bounds = {asset: 0.7 for asset in asset_ids}

    # Retention scores: vary by position for MWIS diversity
    retention_scores = {
        asset: 1.0 - 0.005 * (i % 100)
        for i, asset in enumerate(asset_ids)
    }

    return GeneratedPortfolioData(
        asset_ids=asset_ids,
        expected_returns=expected_returns,
        covariance=covariance,
        lower_bounds=lower_bounds,
        upper_bounds=upper_bounds,
        retention_scores=retention_scores,
        risk_aversion=1.0,
    )
