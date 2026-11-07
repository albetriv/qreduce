"""Shared deterministic fixtures for QReduce tests."""

import pytest

from qreduce.domains.portfolio import PortfolioProblem


@pytest.fixture
def portfolio_problem() -> PortfolioProblem:
    """Return a small synthetic portfolio feasible under the unit budget."""

    return PortfolioProblem(
        asset_ids=("asset-a", "asset-b", "asset-c"),
        expected_returns={"asset-a": 0.10, "asset-b": 0.08, "asset-c": 0.06},
        covariance=((0.04, 0.018, 0.002), (0.018, 0.09, 0.003), (0.002, 0.003, 0.01)),
        lower_bounds={"asset-a": 0.0, "asset-b": 0.0, "asset-c": 0.0},
        upper_bounds={"asset-a": 0.70, "asset-b": 0.70, "asset-c": 0.70},
        retention_scores={"asset-a": 0.9, "asset-b": 0.7, "asset-c": 0.6},
        risk_aversion=1.0,
    )