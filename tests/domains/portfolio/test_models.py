"""Tests for immutable mean-variance portfolio data contracts."""

import pytest

from qreduce.domains.portfolio import PortfolioProblem, PortfolioVariableMapping


def test_variable_mapping_is_stable_and_globally_unique(portfolio_problem: PortfolioProblem) -> None:
    """Each asset maps deterministically to one binary and one continuous variable."""

    mapping = PortfolioVariableMapping.for_problem(portfolio_problem)

    assert mapping.delta_variable_by_asset["asset-a"] == "delta__asset-a"
    assert mapping.x_variable_by_asset["asset-c"] == "x__asset-c"
    assert len(set(mapping.delta_variable_by_asset.values()) | set(mapping.x_variable_by_asset.values())) == 6


def test_problem_rejects_nonsymmetric_covariance() -> None:
    """Correlation graph construction requires symmetric covariance input."""

    with pytest.raises(ValueError, match="symmetric"):
        PortfolioProblem(
            asset_ids=("asset-a", "asset-b"),
            expected_returns={"asset-a": 0.1, "asset-b": 0.1},
            covariance=((0.1, 0.02), (0.01, 0.1)),
            lower_bounds={"asset-a": 0.0, "asset-b": 0.0},
            upper_bounds={"asset-a": 1.0, "asset-b": 1.0},
            retention_scores={"asset-a": 1.0, "asset-b": 1.0},
            risk_aversion=1.0,
        )