"""Tests for reduction graph, candidate validation and explicit portfolio fixing."""

import pytest

from qreduce.domains.portfolio import (
    MeanVariancePortfolioAdapter,
    PortfolioGraphPolicy,
    PortfolioProblem,
)


def make_adapter() -> MeanVariancePortfolioAdapter:
    return MeanVariancePortfolioAdapter(
        PortfolioGraphPolicy(
            policy_id="synthetic-correlation",
            policy_version="1",
            correlation_absolute_threshold=0.25,
        )
    )


def test_adapter_builds_auditable_correlation_graph(portfolio_problem: PortfolioProblem) -> None:
    """Only the highly correlated pair produces one canonical conflict edge."""

    graph = make_adapter().build_conflict_graph(portfolio_problem)

    assert graph.node_ids == ("asset-a", "asset-b", "asset-c")
    assert graph.node_weights["asset-a"] == 0.9
    assert graph.edges == (("asset-a", "asset-b"),)
    assert graph.edge_reasons[("asset-a", "asset-b")] == "abs_correlation=0.3 >= threshold=0.25"


def test_excluded_assets_have_both_delta_and_weight_fixings(portfolio_problem: PortfolioProblem) -> None:
    """Restriction explicitly fixes every linked variable for an excluded asset."""

    problem = portfolio_problem
    adapter = make_adapter()
    manifest = adapter.build_fixing_manifest(problem, ("asset-a", "asset-b"))
    residual_problem = adapter.restrict_problem(problem, ("asset-a", "asset-b"), manifest)

    assert manifest.excluded_item_ids == ("asset-c",)
    assert manifest.entries[0].variable_values == {"delta__asset-c": 0.0, "x__asset-c": 0.0}
    assert residual_problem.objective_description.startswith("risk_aversion")
    assert residual_problem.global_constraint_descriptions == ("sum_i x_i = 1",)
    assert residual_problem.variable_count == 6
    assert residual_problem.constraint_count == 9


def test_candidate_domain_must_retains_enough_upper_bound_capacity(portfolio_problem: PortfolioProblem) -> None:
    """The adapter refuses a candidate set that cannot fund the unit budget."""

    validation = make_adapter().validate_candidate_domain(portfolio_problem, ("asset-a",))

    assert validation.is_valid is False
    assert validation.minimum_required_items == 2
    assert validation.failure_reasons == ("retained_items_cannot_satisfy_unit_budget",)


def test_restrict_problem_refuses_an_invalid_manifest(portfolio_problem: PortfolioProblem) -> None:
    """A partial/invalid candidate domain cannot silently produce a residual model."""

    with pytest.raises(ValueError, match="invalid candidate domain"):
        make_adapter().restrict_problem(portfolio_problem, ("asset-a",), None)  # type: ignore[arg-type]