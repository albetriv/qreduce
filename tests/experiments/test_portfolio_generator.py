"""Tests for the factorial portfolio data generator."""

import math

import numpy as np
import pytest

from qreduce.experiments.portfolio import build_synthetic_portfolio_inputs
from qreduce.experiments.portfolio_domain.models import (
    SyntheticPortfolioGenerationPolicy,
)
from qreduce.experiments.portfolio_generator import (
    default_generation_policy,
    generate_portfolio_data,
)


class TestSyntheticPortfolioGenerationPolicy:
    """Tests for generation policy validation."""

    def test_valid_policy_creation(self):
        """Policy with valid parameters is created successfully."""
        policy = SyntheticPortfolioGenerationPolicy(
            policy_id="test",
            policy_version="1",
            random_seed=42,
            observation_count=100,
            asset_count=10,
            cluster_count=2,
            market_factor_volatility=0.15,
            cluster_factor_volatility=0.10,
            idiosyncratic_volatility=0.05,
        )
        assert policy.asset_count == 10
        assert policy.random_seed == 42

    def test_rejects_blank_policy_id(self):
        """Blank policy_id raises ValueError."""
        with pytest.raises(ValueError, match="cannot be blank"):
            SyntheticPortfolioGenerationPolicy(
                policy_id="",
                policy_version="1",
                random_seed=42,
                observation_count=100,
                asset_count=10,
                cluster_count=2,
                market_factor_volatility=0.15,
                cluster_factor_volatility=0.10,
                idiosyncratic_volatility=0.05,
            )

    def test_rejects_asset_count_below_2(self):
        """asset_count < 2 raises ValueError."""
        with pytest.raises(ValueError, match="at least 2"):
            SyntheticPortfolioGenerationPolicy(
                policy_id="test",
                policy_version="1",
                random_seed=42,
                observation_count=100,
                asset_count=1,
                cluster_count=1,
                market_factor_volatility=0.15,
                cluster_factor_volatility=0.10,
                idiosyncratic_volatility=0.05,
            )

    def test_rejects_insufficient_observations(self):
        """observation_count too small for asset_count raises ValueError."""
        with pytest.raises(ValueError, match="observation_count must be at least"):
            SyntheticPortfolioGenerationPolicy(
                policy_id="test",
                policy_version="1",
                random_seed=42,
                observation_count=50,  # 10 assets * 10 = 100 required
                asset_count=10,
                cluster_count=2,
                market_factor_volatility=0.15,
                cluster_factor_volatility=0.10,
                idiosyncratic_volatility=0.05,
            )

    def test_rejects_cluster_count_exceeding_assets(self):
        """cluster_count > asset_count raises ValueError."""
        with pytest.raises(ValueError, match="cannot exceed asset_count"):
            SyntheticPortfolioGenerationPolicy(
                policy_id="test",
                policy_version="1",
                random_seed=42,
                observation_count=100,
                asset_count=5,
                cluster_count=10,
                market_factor_volatility=0.15,
                cluster_factor_volatility=0.10,
                idiosyncratic_volatility=0.05,
            )

    def test_rejects_non_positive_volatility(self):
        """Non-positive volatilities raise ValueError."""
        with pytest.raises(ValueError, match="market_factor_volatility"):
            SyntheticPortfolioGenerationPolicy(
                policy_id="test",
                policy_version="1",
                random_seed=42,
                observation_count=100,
                asset_count=10,
                cluster_count=2,
                market_factor_volatility=0.0,  # Invalid
                cluster_factor_volatility=0.10,
                idiosyncratic_volatility=0.05,
            )

    def test_rejects_non_integer_seed(self):
        """Non-integer random_seed raises TypeError."""
        with pytest.raises(TypeError, match="must be an integer"):
            SyntheticPortfolioGenerationPolicy(
                policy_id="test",
                policy_version="1",
                random_seed=42.0,  # type: ignore[arg-type]
                observation_count=100,
                asset_count=10,
                cluster_count=2,
                market_factor_volatility=0.15,
                cluster_factor_volatility=0.10,
                idiosyncratic_volatility=0.05,
            )


class TestDefaultGenerationPolicy:
    """Tests for default_generation_policy function."""

    def test_creates_valid_policy(self):
        """Creates a valid policy with default parameters."""
        policy = default_generation_policy(30)
        assert policy.asset_count == 30
        assert policy.random_seed == 42
        assert policy.observation_count >= 30 * 10

    def test_respects_custom_seed(self):
        """Custom random_seed is applied."""
        policy = default_generation_policy(10, random_seed=123)
        assert policy.random_seed == 123

    def test_respects_custom_observation_count(self):
        """Custom observation_count is applied."""
        policy = default_generation_policy(10, observation_count=500)
        assert policy.observation_count == 500

    def test_cluster_count_scales_with_assets(self):
        """cluster_count scales appropriately with asset_count."""
        policy_10 = default_generation_policy(10)
        policy_30 = default_generation_policy(30)
        policy_60 = default_generation_policy(60)
        # cluster_count = max(1, asset_count // 5)
        assert policy_10.cluster_count == 2
        assert policy_30.cluster_count == 6
        assert policy_60.cluster_count == 12


class TestGeneratePortfolioData:
    """Tests for generate_portfolio_data with factorial model."""

    def test_generates_correct_dimensions(self):
        """Generated data has correct dimensions for various asset counts."""
        for asset_count in [6, 12, 30, 60]:
            policy = default_generation_policy(asset_count)
            data = generate_portfolio_data(policy)
            assert len(data.asset_ids) == asset_count
            assert len(data.expected_returns) == asset_count
            assert len(data.covariance) == asset_count
            assert all(len(row) == asset_count for row in data.covariance)
            assert len(data.lower_bounds) == asset_count
            assert len(data.upper_bounds) == asset_count
            assert len(data.retention_scores) == asset_count

    def test_determinism_same_seed(self):
        """Same policy produces identical data."""
        policy = default_generation_policy(20, random_seed=42)
        data1 = generate_portfolio_data(policy)
        data2 = generate_portfolio_data(policy)
        assert data1.asset_ids == data2.asset_ids
        assert data1.expected_returns == data2.expected_returns
        assert data1.covariance == data2.covariance
        assert data1.retention_scores == data2.retention_scores

    def test_different_seed_produces_different_data(self):
        """Different seeds produce different data."""
        policy1 = default_generation_policy(20, random_seed=42)
        policy2 = default_generation_policy(20, random_seed=123)
        data1 = generate_portfolio_data(policy1)
        data2 = generate_portfolio_data(policy2)
        # Expected returns should differ
        assert data1.expected_returns != data2.expected_returns

    def test_covariance_is_symmetric(self):
        """Covariance matrix is symmetric."""
        policy = default_generation_policy(30)
        data = generate_portfolio_data(policy)
        cov = np.array(data.covariance)
        np.testing.assert_allclose(cov, cov.T, atol=1e-10)

    def test_covariance_has_positive_diagonal(self):
        """Covariance diagonal (variances) is strictly positive."""
        policy = default_generation_policy(30)
        data = generate_portfolio_data(policy)
        for i in range(30):
            assert data.covariance[i][i] > 0

    def test_covariance_is_positive_semidefinite(self):
        """Covariance matrix is positive semi-definite."""
        policy = default_generation_policy(30)
        data = generate_portfolio_data(policy)
        cov = np.array(data.covariance)
        eigenvalues = np.linalg.eigvalsh(cov)
        # All eigenvalues should be >= -tolerance
        assert np.all(eigenvalues >= -1e-8)

    def test_correlations_in_valid_range(self):
        """Correlations are in [-1, 1]."""
        policy = default_generation_policy(30)
        data = generate_portfolio_data(policy)
        problem = data.to_problem()
        for i, asset_i in enumerate(data.asset_ids):
            for j, asset_j in enumerate(data.asset_ids[i:], start=i):
                corr = problem.correlation(asset_i, asset_j)
                assert -1 - 1e-6 <= corr <= 1 + 1e-6, f"Correlation ({i},{j}) = {corr}"

    def test_all_values_finite(self):
        """All generated values are finite."""
        policy = default_generation_policy(30)
        data = generate_portfolio_data(policy)
        for asset in data.asset_ids:
            assert math.isfinite(data.expected_returns[asset])
            assert math.isfinite(data.retention_scores[asset])
            assert math.isfinite(data.lower_bounds[asset])
            assert math.isfinite(data.upper_bounds[asset])
        for row in data.covariance:
            for value in row:
                assert math.isfinite(value)

    def test_retention_scores_follow_formula(self):
        """Retention scores follow max(mu, 0) / variance, normalized."""
        policy = default_generation_policy(20)
        data = generate_portfolio_data(policy)

        # Compute expected scores
        raw_scores = {}
        for i, asset in enumerate(data.asset_ids):
            mu = data.expected_returns[asset]
            var = data.covariance[i][i]
            raw_scores[asset] = max(mu, 0.0) / var

        max_raw = max(raw_scores.values())
        if max_raw > 1e-12:
            expected_scores = {a: raw_scores[a] / max_raw for a in data.asset_ids}
        else:
            expected_scores = {a: 1.0 for a in data.asset_ids}

        for asset in data.asset_ids:
            assert abs(data.retention_scores[asset] - expected_scores[asset]) < 1e-10

    def test_retention_scores_in_valid_range(self):
        """Retention scores are in (0, 1]."""
        for asset_count in [6, 12, 30]:
            policy = default_generation_policy(asset_count)
            data = generate_portfolio_data(policy)
            for asset in data.asset_ids:
                assert 0 < data.retention_scores[asset] <= 1.0

    def test_retention_scores_have_at_least_one_at_max(self):
        """At least one retention score equals 1.0 (the maximum)."""
        policy = default_generation_policy(30)
        data = generate_portfolio_data(policy)
        max_score = max(data.retention_scores.values())
        assert abs(max_score - 1.0) < 1e-10

    def test_bounds_are_default_values(self):
        """Bounds use default values [0.0, 0.7]."""
        policy = default_generation_policy(20)
        data = generate_portfolio_data(policy)
        for asset in data.asset_ids:
            assert data.lower_bounds[asset] == 0.0
            assert data.upper_bounds[asset] == 0.7

    def test_custom_bounds(self):
        """Custom bounds are applied."""
        policy = default_generation_policy(10)
        data = generate_portfolio_data(policy, lower_bound=0.05, upper_bound=0.5)
        for asset in data.asset_ids:
            assert data.lower_bounds[asset] == 0.05
            assert data.upper_bounds[asset] == 0.5

    def test_custom_risk_aversion(self):
        """Custom risk_aversion is applied."""
        policy = default_generation_policy(10)
        data = generate_portfolio_data(policy, risk_aversion=2.5)
        assert data.risk_aversion == 2.5

    def test_to_problem_creates_valid_problem(self):
        """GeneratedPortfolioData.to_problem() creates a valid PortfolioProblem."""
        policy = default_generation_policy(15)
        data = generate_portfolio_data(policy)
        problem = data.to_problem()
        assert problem.asset_ids == data.asset_ids
        assert problem.expected_returns == data.expected_returns
        assert problem.covariance == data.covariance
        assert problem.risk_aversion == data.risk_aversion

    def test_provenance_is_recorded(self):
        """Generation policy provenance is recorded in data."""
        policy = default_generation_policy(10)
        data = generate_portfolio_data(policy)
        assert data.generation_policy_id == policy.policy_id
        assert data.generation_policy_version == policy.policy_version


class TestBuildSyntheticPortfolioInputs:
    """Tests for build_synthetic_portfolio_inputs with new policies."""

    def test_rejects_asset_count_below_6(self):
        """asset_count < 6 raises ValueError."""
        with pytest.raises(ValueError, match="at least 6"):
            build_synthetic_portfolio_inputs("test-run", asset_count=5)

    def test_default_uses_30_assets(self):
        """Default asset_count is 30."""
        inputs = build_synthetic_portfolio_inputs("test-run")
        assert len(inputs.problem.asset_ids) == 30

    def test_default_uses_near_duplicate_edge_mode(self):
        """Default graph policy uses near_duplicate edge mode."""
        inputs = build_synthetic_portfolio_inputs("test-run")
        assert inputs.graph_policy.edge_mode == "near_duplicate"

    def test_custom_generation_policy(self):
        """Custom generation policy is used."""
        policy = default_generation_policy(20, random_seed=999)
        inputs = build_synthetic_portfolio_inputs(
            "test-run",
            asset_count=20,
            generation_policy=policy,
        )
        assert inputs.generation_policy == policy
        assert inputs.generation_policy.random_seed == 999

    def test_mismatched_asset_count_raises(self):
        """Generation policy asset_count mismatch raises ValueError."""
        policy = default_generation_policy(15)
        with pytest.raises(ValueError, match="does not match"):
            build_synthetic_portfolio_inputs(
                "test-run",
                asset_count=20,  # Mismatch
                generation_policy=policy,
            )

    def test_candidate_domain_scales_with_assets(self):
        """candidate_domain_max_items scales with asset_count."""
        inputs_10 = build_synthetic_portfolio_inputs("test-run", asset_count=10)
        inputs_30 = build_synthetic_portfolio_inputs("test-run", asset_count=30)
        # (10 * 3) // 5 = 6, (30 * 3) // 5 = 18
        assert inputs_10.config.reduction.candidate_domain_max_items == 6
        assert inputs_30.config.reduction.candidate_domain_max_items == 18

    def test_adapter_is_configured_with_graph_policy(self):
        """Adapter uses the specified graph policy."""
        from qreduce.experiments.portfolio import default_graph_policy
        policy = default_graph_policy("correlation_only", correlation_threshold=0.5)
        inputs = build_synthetic_portfolio_inputs(
            "test-run",
            asset_count=10,
            graph_policy=policy,
        )
        assert inputs.graph_policy.edge_mode == "correlation_only"
        assert inputs.graph_policy.correlation_absolute_threshold == 0.5

    def test_config_has_single_round(self):
        """Config always has max_reduction_rounds=1 for single-pass."""
        inputs = build_synthetic_portfolio_inputs("test-run", asset_count=20)
        assert inputs.config.reduction.max_reduction_rounds == 1
