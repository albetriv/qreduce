"""Tests for immutable mean-variance portfolio data contracts."""

import pytest

from qreduce.experiments.portfolio_domain import (
    MeanVariancePortfolioAdapter,
    PortfolioGraphPolicy,
    PortfolioProblem,
    PortfolioVariableMapping,
)


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


def test_residual_problem_compiles_a_solver_agnostic_miqp(
    portfolio_problem: PortfolioProblem,
) -> None:
    """The portfolio experiment supplies math, not a CPLEX- or SCIP-specific model."""

    adapter = MeanVariancePortfolioAdapter(PortfolioGraphPolicy("policy", "1", 0.25, edge_mode="correlation_only"))
    retained = ("asset-a", "asset-b")
    residual_problem = adapter.restrict_problem(
        portfolio_problem,
        retained,
        adapter.build_fixing_manifest(portfolio_problem, retained),
    )

    model = residual_problem.build_classical_model()

    assert model.variable_names == (
        "delta__asset-a",
        "delta__asset-b",
        "delta__asset-c",
        "x__asset-a",
        "x__asset-b",
        "x__asset-c",
    )
    assert model.linear_objective["x__asset-a"] == -portfolio_problem.expected_returns["asset-a"]
    assert model.quadratic_objective[0].coefficient == (
        portfolio_problem.risk_aversion * portfolio_problem.covariance[0][0]
    )
    assert {constraint.name for constraint in model.linear_constraints} >= {
        "budget",
        "fix__asset-c__delta__asset-c",
        "fix__asset-c__x__asset-c",
    }