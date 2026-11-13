"""Tests for the portfolio data generator and parametric asset counts."""


import pytest

from qreduce.experiments.portfolio import build_synthetic_portfolio_inputs
from qreduce.experiments.portfolio_generator import (
    generate_portfolio_data,
)


class TestGeneratePortfolioData:
    """Tests for generate_portfolio_data function."""

    def test_default_returns_5_assets(self):
        """Default call returns the canonical 5-asset dataset."""
        data = generate_portfolio_data()
        assert len(data.asset_ids) == 5
        assert data.asset_ids == ("asset-a", "asset-b", "asset-c", "asset-d", "asset-e")

    def test_5_assets_returns_canonical_dataset(self):
        """Explicit 5 assets returns the same canonical dataset."""
        data = generate_portfolio_data(5)
        assert data.asset_ids == ("asset-a", "asset-b", "asset-c", "asset-d", "asset-e")
        # Verify canonical expected returns
        assert data.expected_returns["asset-a"] == 0.10
        assert data.expected_returns["asset-b"] == 0.08
        # Verify canonical retention scores
        assert data.retention_scores["asset-a"] == 0.9
        assert data.retention_scores["asset-e"] == 0.5

    def test_6_assets_returns_generated_dataset(self):
        """6 assets triggers the deterministic generator."""
        data = generate_portfolio_data(6)
        assert len(data.asset_ids) == 6
        # Generated asset IDs use numeric format
        assert data.asset_ids[0] == "asset-000"
        assert data.asset_ids[5] == "asset-005"

    def test_12_assets_returns_correct_dimensions(self):
        """Larger dataset has correct dimensions."""
        data = generate_portfolio_data(12)
        assert len(data.asset_ids) == 12
        assert len(data.expected_returns) == 12
        assert len(data.covariance) == 12
        assert all(len(row) == 12 for row in data.covariance)
        assert len(data.lower_bounds) == 12
        assert len(data.upper_bounds) == 12
        assert len(data.retention_scores) == 12

    def test_covariance_is_symmetric_with_positive_diagonal(self):
        """Generated covariance matrix is symmetric with positive diagonal."""
        for asset_count in [6, 12, 30]:
            data = generate_portfolio_data(asset_count)
            # Check diagonal is positive
            for i in range(asset_count):
                assert data.covariance[i][i] > 0, f"Diagonal {i} not positive"
            # Check symmetry
            for i in range(asset_count):
                for j in range(asset_count):
                    assert data.covariance[i][j] == data.covariance[j][i], \
                        f"Not symmetric at ({i}, {j})"

    def test_bounds_are_valid(self):
        """All bounds are in valid range."""
        for asset_count in [5, 6, 12]:
            data = generate_portfolio_data(asset_count)
            for asset in data.asset_ids:
                assert data.lower_bounds[asset] == 0.0
                assert data.upper_bounds[asset] == 0.7

    def test_retention_scores_in_range(self):
        """Retention scores are in (0, 1] range."""
        for asset_count in [5, 6, 12, 30]:
            data = generate_portfolio_data(asset_count)
            for asset in data.asset_ids:
                assert 0 < data.retention_scores[asset] <= 1.0

    def test_expected_returns_are_positive(self):
        """Expected returns are positive."""
        for asset_count in [5, 6, 12]:
            data = generate_portfolio_data(asset_count)
            for asset in data.asset_ids:
                assert data.expected_returns[asset] > 0

    def test_to_problem_creates_valid_problem(self):
        """GeneratedPortfolioData.to_problem() creates a PortfolioProblem."""
        data = generate_portfolio_data(6)
        problem = data.to_problem()
        assert problem.asset_ids == data.asset_ids
        assert problem.expected_returns == data.expected_returns
        assert problem.covariance == data.covariance

    def test_rejects_asset_count_below_5(self):
        """asset_count < 5 raises ValueError."""
        with pytest.raises(ValueError, match="at least 5"):
            generate_portfolio_data(4)
        with pytest.raises(ValueError, match="at least 5"):
            generate_portfolio_data(0)
        with pytest.raises(ValueError, match="at least 5"):
            generate_portfolio_data(-1)

    def test_rejects_non_integer_asset_count(self):
        """Non-integer asset_count raises TypeError."""
        with pytest.raises(TypeError, match="must be an integer"):
            generate_portfolio_data(5.0)  # type: ignore[arg-type]
        with pytest.raises(TypeError, match="must be an integer"):
            generate_portfolio_data("5")  # type: ignore[arg-type]

    def test_rejects_boolean_asset_count(self):
        """Boolean asset_count raises TypeError (bool is subclass of int)."""
        with pytest.raises(TypeError, match="must be an integer"):
            generate_portfolio_data(True)  # type: ignore[arg-type]


class TestBuildSyntheticPortfolioInputs:
    """Tests for build_synthetic_portfolio_inputs with asset_count."""

    def test_default_returns_5_asset_config(self):
        """Default call returns config for 5 assets."""
        inputs = build_synthetic_portfolio_inputs("test-run")
        assert len(inputs.problem.asset_ids) == 5
        assert inputs.config.reduction.candidate_domain_max_items == 3

    def test_6_assets_scales_candidate_domain(self):
        """6 assets scales candidate_domain_max_items proportionally."""
        inputs = build_synthetic_portfolio_inputs("test-run", asset_count=6)
        assert len(inputs.problem.asset_ids) == 6
        # (6 * 3) // 5 = 3, but max(3, 3) = 3
        assert inputs.config.reduction.candidate_domain_max_items == 3

    def test_10_assets_scales_candidate_domain(self):
        """10 assets scales candidate_domain_max_items to 6."""
        inputs = build_synthetic_portfolio_inputs("test-run", asset_count=10)
        assert len(inputs.problem.asset_ids) == 10
        # (10 * 3) // 5 = 6
        assert inputs.config.reduction.candidate_domain_max_items == 6

    def test_15_assets_scales_candidate_domain(self):
        """15 assets scales candidate_domain_max_items to 9."""
        inputs = build_synthetic_portfolio_inputs("test-run", asset_count=15)
        assert len(inputs.problem.asset_ids) == 15
        # (15 * 3) // 5 = 9
        assert inputs.config.reduction.candidate_domain_max_items == 9

    def test_adapter_is_configured(self):
        """Adapter is properly configured for any asset count."""
        inputs = build_synthetic_portfolio_inputs("test-run", asset_count=8)
        assert inputs.adapter is not None
        assert inputs.graph_policy.correlation_absolute_threshold == 0.25

    def test_config_has_single_round(self):
        """Config always has max_reduction_rounds=1 for single-pass."""
        for asset_count in [5, 6, 10, 15]:
            inputs = build_synthetic_portfolio_inputs("test-run", asset_count=asset_count)
            assert inputs.config.reduction.max_reduction_rounds == 1
