"""Deterministic synthetic portfolio data generator using a factorial model.

This module provides a shared generator for creating synthetic portfolio problems
with deterministic, reproducible data derived from a single source: a synthetic
historical returns matrix generated using a factorial model.

The factorial model:
    R[t, i] = alpha_i + beta_market_i * market_factor[t]
              + beta_cluster_i * cluster_factor[cluster(i), t]
              + idiosyncratic_return[t, i]

From the returns matrix, the following are derived deterministically:
    - expected_returns: mean over time periods
    - covariance: sample covariance matrix
    - retention_scores: max(expected_return_i, 0) / variance_i, normalized by max

The generator validates:
    - Sufficient observations
    - All variances strictly positive
    - Covariance symmetric
    - All values finite
    - Correlations in [-1, 1]
    - Covariance matrix positive semi-definite within tolerance
    - Determinism: identical data for same policy and asset_count
"""

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
from numpy.random import PCG64, Generator

from qreduce.experiments.portfolio_domain import PortfolioProblem

if TYPE_CHECKING:
    from qreduce.experiments.portfolio_domain.models import (
        SyntheticPortfolioGenerationPolicy,
    )


@dataclass(frozen=True, slots=True)
class GeneratedPortfolioData:
    """Generated portfolio data with all problem inputs and provenance."""

    asset_ids: tuple[str, ...]
    expected_returns: dict[str, float]
    covariance: tuple[tuple[float, ...], ...]
    lower_bounds: dict[str, float]
    upper_bounds: dict[str, float]
    retention_scores: dict[str, float]
    risk_aversion: float
    # Provenance for auditability
    generation_policy_id: str
    generation_policy_version: str

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


def generate_portfolio_data(
    policy: "SyntheticPortfolioGenerationPolicy",
    *,
    risk_aversion: float = 1.0,
    lower_bound: float = 0.0,
    upper_bound: float = 0.7,
) -> GeneratedPortfolioData:
    """Generate deterministic synthetic portfolio data from a factorial model.

    The generation process:
    1. Create a deterministic RNG from the policy seed
    2. Generate market factor time series
    3. Generate cluster factor time series for each cluster
    4. Compute asset-specific alpha and beta parameters
    5. Generate idiosyncratic returns for each asset
    6. Combine into full returns matrix R[t, i]
    7. Derive expected_returns = mean(R, axis=0)
    8. Derive covariance = cov(R)
    9. Derive retention_scores from return/variance ratio

    Args:
        policy: Generation policy with all model parameters
        risk_aversion: Risk aversion coefficient for the optimization problem
        lower_bound: Lower bound for all asset allocations
        upper_bound: Upper bound for all asset allocations

    Returns:
        GeneratedPortfolioData with all problem inputs and provenance

    Raises:
        ValueError: If generated data fails validation checks
    """
    if not math.isfinite(risk_aversion) or risk_aversion <= 0:
        raise ValueError("risk_aversion must be finite and positive.")
    if not math.isfinite(lower_bound) or lower_bound < 0:
        raise ValueError("lower_bound must be finite and non-negative.")
    if not math.isfinite(upper_bound) or upper_bound <= lower_bound:
        raise ValueError("upper_bound must be finite and greater than lower_bound.")

    n_assets = policy.asset_count
    n_obs = policy.observation_count
    n_clusters = policy.cluster_count

    # Initialize deterministic RNG
    rng = Generator(PCG64(policy.random_seed))

    # Generate common factors
    market_factor = rng.normal(0, policy.market_factor_volatility, n_obs)
    cluster_factors = rng.normal(0, policy.cluster_factor_volatility, (n_clusters, n_obs))

    # Compute asset parameters
    alphas = np.zeros(n_assets)
    beta_markets = np.zeros(n_assets)
    beta_clusters = np.zeros(n_assets)
    cluster_assignments = np.zeros(n_assets, dtype=int)

    for i in range(n_assets):
        # Alpha varies linearly across assets
        if n_assets > 1:
            alphas[i] = policy.alpha_base + policy.alpha_spread * (i / (n_assets - 1))
        else:
            alphas[i] = policy.alpha_base + policy.alpha_spread * 0.5

        # Beta market varies linearly across assets
        if n_assets > 1:
            beta_markets[i] = policy.beta_market_base + policy.beta_market_spread * (i / (n_assets - 1))
        else:
            beta_markets[i] = policy.beta_market_base + policy.beta_market_spread * 0.5

        # Cluster assignment and beta cluster
        cluster_assignments[i] = i % n_clusters
        if n_clusters > 1:
            cluster_pos = cluster_assignments[i] / (n_clusters - 1)
        else:
            cluster_pos = 0.5
        beta_clusters[i] = policy.beta_cluster_base + policy.beta_cluster_spread * cluster_pos

    # Generate idiosyncratic returns
    idiosyncratic = rng.normal(0, policy.idiosyncratic_volatility, (n_obs, n_assets))

    # Build returns matrix: R[t, i]
    returns = np.zeros((n_obs, n_assets))
    for i in range(n_assets):
        returns[:, i] = (
            alphas[i]
            + beta_markets[i] * market_factor
            + beta_clusters[i] * cluster_factors[cluster_assignments[i]]
            + idiosyncratic[:, i]
        )

    # Derive expected returns (mean over time)
    expected_returns_array = np.mean(returns, axis=0)

    # Derive covariance matrix (sample covariance)
    covariance_matrix = np.cov(returns, rowvar=False, ddof=1)

    # Validate covariance matrix
    _validate_covariance(covariance_matrix, n_assets)

    # Derive retention scores: max(mu_i, 0) / sigma_ii, normalized
    variances = np.diag(covariance_matrix)
    raw_scores = np.maximum(expected_returns_array, 0.0) / variances

    epsilon = 1e-12
    max_score = np.max(raw_scores)
    if max_score <= epsilon:
        # Degenerate case: all non-positive returns, use uniform scores
        retention_scores_array = np.ones(n_assets)
    else:
        retention_scores_array = raw_scores / max_score

    # Build asset IDs
    asset_ids = tuple(f"asset-{i:03d}" for i in range(n_assets))

    # Convert to dictionaries
    expected_returns = {asset_ids[i]: float(expected_returns_array[i]) for i in range(n_assets)}
    retention_scores = {asset_ids[i]: float(retention_scores_array[i]) for i in range(n_assets)}
    lower_bounds = {asset_id: lower_bound for asset_id in asset_ids}
    upper_bounds = {asset_id: upper_bound for asset_id in asset_ids}

    # Convert covariance to nested tuple
    covariance = tuple(
        tuple(float(covariance_matrix[i, j]) for j in range(n_assets))
        for i in range(n_assets)
    )

    return GeneratedPortfolioData(
        asset_ids=asset_ids,
        expected_returns=expected_returns,
        covariance=covariance,
        lower_bounds=lower_bounds,
        upper_bounds=upper_bounds,
        retention_scores=retention_scores,
        risk_aversion=risk_aversion,
        generation_policy_id=policy.policy_id,
        generation_policy_version=policy.policy_version,
    )


def _validate_covariance(cov: np.ndarray, n_assets: int) -> None:
    """Validate the generated covariance matrix.

    Raises:
        ValueError: If any validation check fails
    """
    # Check all values finite
    if not np.all(np.isfinite(cov)):
        raise ValueError("Covariance matrix contains non-finite values.")

    # Check symmetry
    symmetry_tolerance = 1e-10
    if not np.allclose(cov, cov.T, atol=symmetry_tolerance):
        raise ValueError("Covariance matrix is not symmetric within tolerance.")

    # Check positive diagonal (variances)
    diag = np.diag(cov)
    if not np.all(diag > 0):
        raise ValueError("Covariance diagonal (variances) must be strictly positive.")

    # Check correlations are in [-1, 1]
    std_devs = np.sqrt(diag)
    with np.errstate(divide="ignore", invalid="ignore"):
        correlation = cov / np.outer(std_devs, std_devs)
    # Set diagonal to 1 (avoid numerical issues)
    np.fill_diagonal(correlation, 1.0)

    correlation_tolerance = 1e-6
    if np.any(correlation < -1 - correlation_tolerance) or np.any(correlation > 1 + correlation_tolerance):
        raise ValueError("Correlations must be in [-1, 1] within tolerance.")

    # Check positive semi-definite (all eigenvalues >= -tolerance)
    psd_tolerance = -1e-8
    eigenvalues = np.linalg.eigvalsh(cov)
    if np.any(eigenvalues < psd_tolerance):
        min_eigenvalue = float(np.min(eigenvalues))
        raise ValueError(
            f"Covariance matrix is not positive semi-definite within tolerance. "
            f"Minimum eigenvalue: {min_eigenvalue}"
        )


def default_generation_policy(
    asset_count: int,
    *,
    random_seed: int = 42,
    observation_count: int | None = None,
    cluster_count: int | None = None,
) -> "SyntheticPortfolioGenerationPolicy":
    """Create a default generation policy with sensible parameters.

    Args:
        asset_count: Number of assets to generate
        random_seed: Random seed for reproducibility
        observation_count: Number of historical observations (default: 10 * asset_count)
        cluster_count: Number of asset clusters (default: max(1, asset_count // 5))

    Returns:
        A SyntheticPortfolioGenerationPolicy with default parameters
    """
    from qreduce.experiments.portfolio_domain.models import (
        SyntheticPortfolioGenerationPolicy,
    )

    if observation_count is None:
        observation_count = max(100, 10 * asset_count)
    if cluster_count is None:
        cluster_count = max(1, asset_count // 5)

    return SyntheticPortfolioGenerationPolicy(
        policy_id="synthetic_factor_model",
        policy_version="1",
        random_seed=random_seed,
        observation_count=observation_count,
        asset_count=asset_count,
        cluster_count=cluster_count,
        market_factor_volatility=0.15,
        cluster_factor_volatility=0.10,
        idiosyncratic_volatility=0.05,
    )
