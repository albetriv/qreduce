"""Tests for reduction graph, candidate validation and explicit portfolio fixing."""


import pytest

from qreduce.domains import LogicalVariableCounts
from qreduce.experiments.portfolio_domain import (
    MeanVariancePortfolioAdapter,
    PortfolioGraphPolicy,
    PortfolioProblem,
)


def make_adapter(
    edge_mode: str = "correlation_only",
    correlation_threshold: float = 0.25,
    near_duplicate_max_relative_return_difference: float = 0.10,
    near_duplicate_max_relative_variance_difference: float = 0.10,
) -> MeanVariancePortfolioAdapter:
    """Create adapter with specified graph policy."""
    return MeanVariancePortfolioAdapter(
        PortfolioGraphPolicy(
            policy_id=f"test-{edge_mode}",
            policy_version="1",
            correlation_absolute_threshold=correlation_threshold,
            edge_mode=edge_mode,  # type: ignore[arg-type]
            near_duplicate_max_relative_return_difference=near_duplicate_max_relative_return_difference,
            near_duplicate_max_relative_variance_difference=near_duplicate_max_relative_variance_difference,
        )
    )


class TestPortfolioGraphPolicyValidation:
    """Tests for PortfolioGraphPolicy validation."""

    def test_valid_correlation_only_policy(self):
        """Valid correlation_only policy is created successfully."""
        policy = PortfolioGraphPolicy(
            policy_id="test",
            policy_version="1",
            correlation_absolute_threshold=0.5,
            edge_mode="correlation_only",
        )
        assert policy.edge_mode == "correlation_only"

    def test_valid_near_duplicate_policy(self):
        """Valid near_duplicate policy is created successfully."""
        policy = PortfolioGraphPolicy(
            policy_id="test",
            policy_version="1",
            correlation_absolute_threshold=0.9,
            edge_mode="near_duplicate",
            near_duplicate_max_relative_return_difference=0.10,
            near_duplicate_max_relative_variance_difference=0.15,
        )
        assert policy.edge_mode == "near_duplicate"
        assert policy.near_duplicate_max_relative_return_difference == 0.10
        assert policy.near_duplicate_max_relative_variance_difference == 0.15

    def test_rejects_unknown_edge_mode(self):
        """Unknown edge_mode raises ValueError."""
        with pytest.raises(ValueError, match="'correlation_only' or 'near_duplicate'"):
            PortfolioGraphPolicy(
                policy_id="test",
                policy_version="1",
                correlation_absolute_threshold=0.5,
                edge_mode="unknown",  # type: ignore[arg-type]
            )

    def test_rejects_threshold_out_of_range(self):
        """Threshold outside [0, 1] raises ValueError."""
        with pytest.raises(ValueError, match="must be finite and in \\[0, 1\\]"):
            PortfolioGraphPolicy(
                policy_id="test",
                policy_version="1",
                correlation_absolute_threshold=1.5,
            )

    def test_rejects_negative_near_duplicate_return_diff(self):
        """Negative near_duplicate_max_relative_return_difference raises ValueError."""
        with pytest.raises(ValueError, match="non-negative"):
            PortfolioGraphPolicy(
                policy_id="test",
                policy_version="1",
                correlation_absolute_threshold=0.9,
                edge_mode="near_duplicate",
                near_duplicate_max_relative_return_difference=-0.1,
            )

    def test_rejects_missing_near_duplicate_params(self):
        """Missing near_duplicate parameters when edge_mode='near_duplicate' raises."""
        with pytest.raises(ValueError, match="required when edge_mode='near_duplicate'"):
            PortfolioGraphPolicy(
                policy_id="test",
                policy_version="1",
                correlation_absolute_threshold=0.9,
                edge_mode="near_duplicate",
                near_duplicate_max_relative_return_difference=None,
            )

    def test_rejects_non_finite_values(self):
        """Non-finite parameter values raise ValueError."""
        with pytest.raises(ValueError, match="finite"):
            PortfolioGraphPolicy(
                policy_id="test",
                policy_version="1",
                correlation_absolute_threshold=float("inf"),
            )

    def test_rejects_blank_policy_id(self):
        """Blank policy_id raises ValueError."""
        with pytest.raises(ValueError, match="cannot be blank"):
            PortfolioGraphPolicy(
                policy_id="",
                policy_version="1",
                correlation_absolute_threshold=0.5,
            )

    def test_rejects_blank_node_weight_policy_id(self):
        """Blank node_weight_policy_id raises ValueError."""
        with pytest.raises(ValueError, match="cannot be blank"):
            PortfolioGraphPolicy(
                policy_id="test",
                policy_version="1",
                correlation_absolute_threshold=0.5,
                node_weight_policy_id="",
            )


class TestCorrelationOnlyEdgeMode:
    """Tests for correlation_only edge mode."""

    def test_creates_edge_above_threshold(self, portfolio_problem: PortfolioProblem):
        """Edge is created when correlation >= threshold."""
        # asset-a and asset-b have correlation ~0.3
        adapter = make_adapter(edge_mode="correlation_only", correlation_threshold=0.25)
        graph = adapter.build_conflict_graph(portfolio_problem)
        assert ("asset-a", "asset-b") in graph.edges

    def test_no_edge_below_threshold(self, portfolio_problem: PortfolioProblem):
        """No edge when correlation < threshold."""
        # Raise threshold above the actual correlations
        adapter = make_adapter(edge_mode="correlation_only", correlation_threshold=0.5)
        graph = adapter.build_conflict_graph(portfolio_problem)
        # Only asset-a and asset-b have correlation ~0.3, below 0.5
        assert ("asset-a", "asset-b") not in graph.edges

    def test_reason_code_format(self, portfolio_problem: PortfolioProblem):
        """Edge reason contains edge_mode and correlation values."""
        adapter = make_adapter(edge_mode="correlation_only", correlation_threshold=0.25)
        graph = adapter.build_conflict_graph(portfolio_problem)
        reason = graph.edge_reasons[("asset-a", "asset-b")]
        assert "edge_mode=correlation_only" in reason
        assert "abs_correlation=" in reason
        assert "threshold=" in reason


class TestNearDuplicateEdgeMode:
    """Tests for near_duplicate edge mode."""

    def test_creates_edge_when_all_criteria_met(self):
        """Edge is created when correlation high AND returns/variances similar."""
        # Create problem with two nearly identical assets
        problem = PortfolioProblem(
            asset_ids=("a", "b", "c"),
            expected_returns={"a": 0.10, "b": 0.105, "c": 0.05},  # a,b similar
            covariance=(
                (0.04, 0.038, 0.001),  # a-b highly correlated
                (0.038, 0.041, 0.001),  # b variance similar to a
                (0.001, 0.001, 0.02),   # c different
            ),
            lower_bounds={"a": 0.0, "b": 0.0, "c": 0.0},
            upper_bounds={"a": 0.7, "b": 0.7, "c": 0.7},
            retention_scores={"a": 0.9, "b": 0.85, "c": 0.6},
            risk_aversion=1.0,
        )
        # correlation(a,b) = 0.038 / sqrt(0.04 * 0.041) ≈ 0.94
        # relative_return_diff = |0.10 - 0.105| / 0.105 ≈ 0.048
        # relative_variance_diff = |0.04 - 0.041| / 0.041 ≈ 0.024
        adapter = make_adapter(
            edge_mode="near_duplicate",
            correlation_threshold=0.90,
            near_duplicate_max_relative_return_difference=0.10,
            near_duplicate_max_relative_variance_difference=0.10,
        )
        graph = adapter.build_conflict_graph(problem)
        assert ("a", "b") in graph.edges

    def test_no_edge_when_returns_too_different(self):
        """No edge when returns differ too much despite high correlation."""
        problem = PortfolioProblem(
            asset_ids=("a", "b"),
            expected_returns={"a": 0.10, "b": 0.20},  # 100% difference
            covariance=(
                (0.04, 0.038),  # highly correlated
                (0.038, 0.04),
            ),
            lower_bounds={"a": 0.0, "b": 0.0},
            upper_bounds={"a": 0.7, "b": 0.7},
            retention_scores={"a": 0.9, "b": 0.9},
            risk_aversion=1.0,
        )
        adapter = make_adapter(
            edge_mode="near_duplicate",
            correlation_threshold=0.90,
            near_duplicate_max_relative_return_difference=0.10,
            near_duplicate_max_relative_variance_difference=0.10,
        )
        graph = adapter.build_conflict_graph(problem)
        # Should NOT have edge because returns differ too much
        assert ("a", "b") not in graph.edges

    def test_no_edge_when_variances_too_different(self):
        """No edge when variances differ too much despite high correlation and similar returns."""
        problem = PortfolioProblem(
            asset_ids=("a", "b"),
            expected_returns={"a": 0.10, "b": 0.10},  # identical returns
            covariance=(
                (0.04, 0.05),  # high correlation but very different variances
                (0.05, 0.10),  # b has 2.5x variance of a
            ),
            lower_bounds={"a": 0.0, "b": 0.0},
            upper_bounds={"a": 0.7, "b": 0.7},
            retention_scores={"a": 0.9, "b": 0.9},
            risk_aversion=1.0,
        )
        # correlation = 0.05 / sqrt(0.04 * 0.10) = 0.79 < 0.90
        # But even if we lower threshold, variance diff = 0.06 / 0.10 = 0.6 > 0.10
        adapter = make_adapter(
            edge_mode="near_duplicate",
            correlation_threshold=0.70,
            near_duplicate_max_relative_return_difference=0.10,
            near_duplicate_max_relative_variance_difference=0.10,
        )
        graph = adapter.build_conflict_graph(problem)
        assert ("a", "b") not in graph.edges

    def test_no_edge_when_correlation_below_threshold(self):
        """No edge when correlation is below threshold even if returns/variances match."""
        problem = PortfolioProblem(
            asset_ids=("a", "b"),
            expected_returns={"a": 0.10, "b": 0.10},
            covariance=(
                (0.04, 0.010),  # low correlation
                (0.010, 0.04),
            ),
            lower_bounds={"a": 0.0, "b": 0.0},
            upper_bounds={"a": 0.7, "b": 0.7},
            retention_scores={"a": 0.9, "b": 0.9},
            risk_aversion=1.0,
        )
        # correlation = 0.010 / 0.04 = 0.25
        adapter = make_adapter(
            edge_mode="near_duplicate",
            correlation_threshold=0.90,
            near_duplicate_max_relative_return_difference=0.50,
            near_duplicate_max_relative_variance_difference=0.50,
        )
        graph = adapter.build_conflict_graph(problem)
        assert ("a", "b") not in graph.edges

    def test_reason_code_contains_all_criteria(self):
        """Edge reason contains all checked criteria values."""
        problem = PortfolioProblem(
            asset_ids=("a", "b"),
            expected_returns={"a": 0.10, "b": 0.10},
            covariance=(
                (0.04, 0.038),
                (0.038, 0.04),
            ),
            lower_bounds={"a": 0.0, "b": 0.0},
            upper_bounds={"a": 0.7, "b": 0.7},
            retention_scores={"a": 0.9, "b": 0.9},
            risk_aversion=1.0,
        )
        adapter = make_adapter(
            edge_mode="near_duplicate",
            correlation_threshold=0.90,
        )
        graph = adapter.build_conflict_graph(problem)
        reason = graph.edge_reasons[("a", "b")]
        assert "edge_mode=near_duplicate" in reason
        assert "abs_correlation=" in reason
        assert "relative_return_difference=" in reason
        assert "relative_variance_difference=" in reason


class TestAdapterGraphBuilding:
    """General tests for adapter graph building."""

    def test_builds_auditable_graph(self, portfolio_problem: PortfolioProblem):
        """Graph has correct structure and metadata."""
        adapter = make_adapter(edge_mode="correlation_only", correlation_threshold=0.25)
        graph = adapter.build_conflict_graph(portfolio_problem)
        assert graph.node_ids == ("asset-a", "asset-b", "asset-c")
        assert graph.node_weights["asset-a"] == 0.9
        assert graph.graph_policy_id == "test-correlation_only"
        assert graph.graph_policy_version == "1"

    def test_node_weights_match_retention_scores(self, portfolio_problem: PortfolioProblem):
        """Node weights equal retention scores from problem."""
        adapter = make_adapter()
        graph = adapter.build_conflict_graph(portfolio_problem)
        for asset in portfolio_problem.asset_ids:
            assert graph.node_weights[asset] == portfolio_problem.retention_scores[asset]


class TestAdapterCandidateDomainValidation:
    """Tests for candidate domain validation."""

    def test_baseline_declares_no_protected_assets(self, portfolio_problem: PortfolioProblem):
        """The baseline experiment declares no protected items."""
        assert make_adapter().declare_protected_items(portfolio_problem) == ()

    def test_domain_must_retain_budget_capacity(self, portfolio_problem: PortfolioProblem):
        """Adapter refuses a candidate set that cannot fund the unit budget."""
        validation = make_adapter().validate_candidate_domain(portfolio_problem, ("asset-a",))
        assert validation.is_valid is False
        assert validation.minimum_required_items == 2
        assert validation.failure_reasons == ("retained_items_cannot_satisfy_unit_budget",)


class TestAdapterFixingManifest:
    """Tests for fixing manifest and problem restriction."""

    def test_excluded_assets_have_both_variable_fixings(self, portfolio_problem: PortfolioProblem):
        """Excluded assets have both delta and x variables fixed to 0."""
        adapter = make_adapter()
        manifest = adapter.build_fixing_manifest(portfolio_problem, ("asset-a", "asset-b"))
        assert manifest.excluded_item_ids == ("asset-c",)
        assert manifest.entries[0].variable_values == {"delta__asset-c": 0.0, "x__asset-c": 0.0}

    def test_residual_problem_structure(self, portfolio_problem: PortfolioProblem):
        """Residual problem has correct structure."""
        adapter = make_adapter()
        manifest = adapter.build_fixing_manifest(portfolio_problem, ("asset-a", "asset-b"))
        residual = adapter.restrict_problem(portfolio_problem, ("asset-a", "asset-b"), manifest)
        assert residual.objective_description.startswith("risk_aversion")
        assert residual.global_constraint_descriptions == ("sum_i x_i = 1",)
        assert residual.variable_count == 6
        assert residual.constraint_count == 9

    def test_logical_variable_counts(self, portfolio_problem: PortfolioProblem):
        """Logical variable counts are correct for original and residual."""
        adapter = make_adapter()
        assert adapter.describe_logical_variables(portfolio_problem) == LogicalVariableCounts(3, 0, 3)
        manifest = adapter.build_fixing_manifest(portfolio_problem, ("asset-a", "asset-b"))
        residual = adapter.restrict_problem(portfolio_problem, ("asset-a", "asset-b"), manifest)
        assert adapter.describe_logical_variables(residual) == LogicalVariableCounts(2, 0, 2)

    def test_restrict_refuses_invalid_manifest(self, portfolio_problem: PortfolioProblem):
        """Cannot restrict with invalid candidate domain."""
        with pytest.raises(ValueError, match="invalid candidate domain"):
            make_adapter().restrict_problem(portfolio_problem, ("asset-a",), None)  # type: ignore[arg-type]

    def test_residual_graph_excludes_fixed_items(self, portfolio_problem: PortfolioProblem):
        """Residual problem graph only contains retained items."""
        adapter = make_adapter()
        first = adapter.build_fixing_manifest(portfolio_problem, ("asset-a", "asset-b"))
        residual = adapter.restrict_problem(portfolio_problem, ("asset-a", "asset-b"), first)
        assert adapter.identify_reducible_items(residual) == ["asset-a", "asset-b"]
        graph = adapter.build_conflict_graph(residual)
        assert graph.node_ids == ("asset-a", "asset-b")
        assert set(graph.node_weights) == {"asset-a", "asset-b"}

    def test_second_round_restriction_accumulates_fixings(self, portfolio_problem: PortfolioProblem):
        """Second round properly accumulates fixings from first round."""
        adapter = make_adapter()
        first = adapter.build_fixing_manifest(portfolio_problem, ("asset-a", "asset-b"))
        residual = adapter.restrict_problem(portfolio_problem, ("asset-a", "asset-b"), first)
        # Build second manifest keeping both assets (can't reduce further with budget constraint)
        second = adapter.build_fixing_manifest(residual, ("asset-a", "asset-b"))
        final = adapter.restrict_problem(residual, ("asset-a", "asset-b"), second)
        # Cumulative fixings should include asset-c from first round
        assert final.fixing_manifest.excluded_item_ids == ("asset-c",)
        assert final.fixing_manifest.entries == first.entries

    def test_cannot_validate_unknown_items(self, portfolio_problem: PortfolioProblem):
        """Cannot validate domain with unknown items."""
        validation = make_adapter().validate_candidate_domain(portfolio_problem, ("asset-a", "asset-z"))
        assert validation.is_valid is False
        assert "unknown_retained_item_id" in validation.failure_reasons
