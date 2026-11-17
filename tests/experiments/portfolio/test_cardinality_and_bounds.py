"""Tests for cardinality constraints and investment bounds in portfolio experiments."""

from dataclasses import replace

import pytest

from qreduce.domains.contracts import FixingManifest
from qreduce.experiments.portfolio import (
    MeanVariancePortfolioAdapter,
    PortfolioGraphPolicy,
    PortfolioProblem,
    PortfolioVariableMapping,
)
from qreduce.experiments.portfolio.generator import (
    default_generation_policy,
    generate_portfolio_data,
)
from qreduce.experiments.portfolio.postcheck import validate_portfolio_solution
from qreduce.models import ClassicalSolveOptions
from qreduce.status import PostcheckMode

# --- Fixtures ---


@pytest.fixture
def portfolio_with_cardinality() -> PortfolioProblem:
    """Return a portfolio with cardinality constraints."""
    return PortfolioProblem(
        asset_ids=("asset-a", "asset-b", "asset-c", "asset-d"),
        expected_returns={"asset-a": 0.10, "asset-b": 0.08, "asset-c": 0.06, "asset-d": 0.05},
        covariance=(
            (0.04, 0.018, 0.002, 0.001),
            (0.018, 0.09, 0.003, 0.002),
            (0.002, 0.003, 0.01, 0.001),
            (0.001, 0.002, 0.001, 0.02),
        ),
        lower_bounds={"asset-a": 0.0, "asset-b": 0.0, "asset-c": 0.0, "asset-d": 0.0},
        upper_bounds={"asset-a": 0.50, "asset-b": 0.50, "asset-c": 0.50, "asset-d": 0.50},
        retention_scores={"asset-a": 0.9, "asset-b": 0.7, "asset-c": 0.6, "asset-d": 0.5},
        risk_aversion=1.0,
        min_selected_assets=2,
        max_selected_assets=3,
    )


@pytest.fixture
def portfolio_with_positive_minimums() -> PortfolioProblem:
    """Return a portfolio with positive lower bounds (minimum investment per asset)."""
    return PortfolioProblem(
        asset_ids=("asset-a", "asset-b", "asset-c", "asset-d"),
        expected_returns={"asset-a": 0.10, "asset-b": 0.08, "asset-c": 0.06, "asset-d": 0.05},
        covariance=(
            (0.04, 0.018, 0.002, 0.001),
            (0.018, 0.09, 0.003, 0.002),
            (0.002, 0.003, 0.01, 0.001),
            (0.001, 0.002, 0.001, 0.02),
        ),
        lower_bounds={"asset-a": 0.10, "asset-b": 0.10, "asset-c": 0.10, "asset-d": 0.10},
        upper_bounds={"asset-a": 0.50, "asset-b": 0.50, "asset-c": 0.50, "asset-d": 0.50},
        retention_scores={"asset-a": 0.9, "asset-b": 0.7, "asset-c": 0.6, "asset-d": 0.5},
        risk_aversion=1.0,
    )


@pytest.fixture
def tolerances() -> ClassicalSolveOptions:
    return ClassicalSolveOptions(
        classical_solver_id="scip",
        time_limit_seconds=10.0,
        mip_gap_tolerance=None,
        threads=None,
        model_export_enabled=False,
        primal_feasibility_tolerance=1e-6,
        integrality_tolerance=1e-6,
        objective_recomputation_absolute_tolerance=1e-6,
        objective_recomputation_relative_tolerance=1e-6,
        postcheck_mode=PostcheckMode.STRICT,
    )


def make_adapter() -> MeanVariancePortfolioAdapter:
    return MeanVariancePortfolioAdapter(
        PortfolioGraphPolicy("policy", "1", 0.25, edge_mode="correlation_only")
    )


# --- PortfolioProblem validation tests ---


class TestCardinalityValidation:
    """Tests for cardinality constraint validation in PortfolioProblem."""

    def test_valid_cardinality_constraints(self) -> None:
        """Valid min/max cardinality constraints are accepted."""
        problem = PortfolioProblem(
            asset_ids=("a", "b", "c"),
            expected_returns={"a": 0.1, "b": 0.1, "c": 0.1},
            covariance=((0.1, 0, 0), (0, 0.1, 0), (0, 0, 0.1)),
            lower_bounds={"a": 0.0, "b": 0.0, "c": 0.0},
            upper_bounds={"a": 0.5, "b": 0.5, "c": 0.5},
            retention_scores={"a": 1, "b": 1, "c": 1},
            risk_aversion=1.0,
            min_selected_assets=1,
            max_selected_assets=2,
        )
        assert problem.min_selected_assets == 1
        assert problem.max_selected_assets == 2

    def test_exact_cardinality(self) -> None:
        """Exact cardinality (min == max) is valid."""
        problem = PortfolioProblem(
            asset_ids=("a", "b", "c"),
            expected_returns={"a": 0.1, "b": 0.1, "c": 0.1},
            covariance=((0.1, 0, 0), (0, 0.1, 0), (0, 0, 0.1)),
            lower_bounds={"a": 0.0, "b": 0.0, "c": 0.0},
            upper_bounds={"a": 0.5, "b": 0.5, "c": 0.5},
            retention_scores={"a": 1, "b": 1, "c": 1},
            risk_aversion=1.0,
            min_selected_assets=2,
            max_selected_assets=2,
        )
        assert problem.min_selected_assets == problem.max_selected_assets == 2

    def test_rejects_min_exceeds_max(self) -> None:
        """min_selected_assets cannot exceed max_selected_assets."""
        with pytest.raises(ValueError, match="cannot exceed max_selected_assets"):
            PortfolioProblem(
                asset_ids=("a", "b", "c"),
                expected_returns={"a": 0.1, "b": 0.1, "c": 0.1},
                covariance=((0.1, 0, 0), (0, 0.1, 0), (0, 0, 0.1)),
                lower_bounds={"a": 0.0, "b": 0.0, "c": 0.0},
                upper_bounds={"a": 0.5, "b": 0.5, "c": 0.5},
                retention_scores={"a": 1, "b": 1, "c": 1},
                risk_aversion=1.0,
                min_selected_assets=3,
                max_selected_assets=1,
            )

    def test_rejects_negative_min_cardinality(self) -> None:
        """min_selected_assets must be non-negative."""
        with pytest.raises(ValueError, match="non-negative"):
            PortfolioProblem(
                asset_ids=("a", "b", "c"),
                expected_returns={"a": 0.1, "b": 0.1, "c": 0.1},
                covariance=((0.1, 0, 0), (0, 0.1, 0), (0, 0, 0.1)),
                lower_bounds={"a": 0.0, "b": 0.0, "c": 0.0},
                upper_bounds={"a": 0.5, "b": 0.5, "c": 0.5},
                retention_scores={"a": 1, "b": 1, "c": 1},
                risk_aversion=1.0,
                min_selected_assets=-1,
            )

    def test_rejects_max_cardinality_zero(self) -> None:
        """max_selected_assets must be at least 1."""
        with pytest.raises(ValueError, match="at least 1"):
            PortfolioProblem(
                asset_ids=("a", "b", "c"),
                expected_returns={"a": 0.1, "b": 0.1, "c": 0.1},
                covariance=((0.1, 0, 0), (0, 0.1, 0), (0, 0, 0.1)),
                lower_bounds={"a": 0.0, "b": 0.0, "c": 0.0},
                upper_bounds={"a": 0.5, "b": 0.5, "c": 0.5},
                retention_scores={"a": 1, "b": 1, "c": 1},
                risk_aversion=1.0,
                max_selected_assets=0,
            )

    def test_rejects_min_exceeds_asset_count(self) -> None:
        """min_selected_assets cannot exceed number of assets."""
        with pytest.raises(ValueError, match="cannot exceed asset count"):
            PortfolioProblem(
                asset_ids=("a", "b", "c"),
                expected_returns={"a": 0.1, "b": 0.1, "c": 0.1},
                covariance=((0.1, 0, 0), (0, 0.1, 0), (0, 0, 0.1)),
                lower_bounds={"a": 0.0, "b": 0.0, "c": 0.0},
                upper_bounds={"a": 0.5, "b": 0.5, "c": 0.5},
                retention_scores={"a": 1, "b": 1, "c": 1},
                risk_aversion=1.0,
                min_selected_assets=5,
            )

    def test_rejects_boolean_cardinality(self) -> None:
        """Boolean values are not valid cardinality constraints."""
        with pytest.raises(TypeError, match="integer"):
            PortfolioProblem(
                asset_ids=("a", "b", "c"),
                expected_returns={"a": 0.1, "b": 0.1, "c": 0.1},
                covariance=((0.1, 0, 0), (0, 0.1, 0), (0, 0, 0.1)),
                lower_bounds={"a": 0.0, "b": 0.0, "c": 0.0},
                upper_bounds={"a": 0.5, "b": 0.5, "c": 0.5},
                retention_scores={"a": 1, "b": 1, "c": 1},
                risk_aversion=1.0,
                min_selected_assets=True,  # type: ignore[arg-type]
            )

    def test_rejects_infeasible_max_cardinality_budget(self) -> None:
        """Rejects max_selected_assets when upper bounds can't satisfy budget."""
        with pytest.raises(ValueError, match="cannot satisfy the unit budget"):
            PortfolioProblem(
                asset_ids=("a", "b", "c", "d"),
                expected_returns={"a": 0.1, "b": 0.1, "c": 0.1, "d": 0.1},
                covariance=(
                    (0.1, 0, 0, 0),
                    (0, 0.1, 0, 0),
                    (0, 0, 0.1, 0),
                    (0, 0, 0, 0.1),
                ),
                lower_bounds={"a": 0.0, "b": 0.0, "c": 0.0, "d": 0.0},
                upper_bounds={"a": 0.20, "b": 0.20, "c": 0.20, "d": 0.20},
                retention_scores={"a": 1, "b": 1, "c": 1, "d": 1},
                risk_aversion=1.0,
                max_selected_assets=2,  # 2 * 0.20 = 0.40 < 1.0
            )


class TestInvestmentBoundsValidation:
    """Tests for investment bounds validation."""

    def test_positive_lower_bounds_allowed(
        self, portfolio_with_positive_minimums: PortfolioProblem
    ) -> None:
        """Positive lower bounds are valid when budget is feasible."""
        # With 4 assets at lower_bound=0.10, selecting 4 uses 0.40 <= 1.0
        assert portfolio_with_positive_minimums.lower_bounds["asset-a"] == 0.10

    def test_sum_of_all_lower_bounds_can_exceed_one(self) -> None:
        """Sum of ALL lower bounds can exceed 1 since not all must be selected.

        This was the incorrect validation that was removed.
        """
        # 10 assets, each with lower_bound=0.15, sum=1.5 > 1
        # But selecting only 5 uses 0.75 < 1
        problem = PortfolioProblem(
            asset_ids=tuple(f"a{i}" for i in range(10)),
            expected_returns={f"a{i}": 0.1 for i in range(10)},
            covariance=tuple(
                tuple(0.1 if i == j else 0.0 for j in range(10)) for i in range(10)
            ),
            lower_bounds={f"a{i}": 0.15 for i in range(10)},
            upper_bounds={f"a{i}": 0.5 for i in range(10)},
            retention_scores={f"a{i}": 1.0 for i in range(10)},
            risk_aversion=1.0,
            max_selected_assets=5,  # Only 5 assets need to be selected
        )
        # Should not raise - sum of lower_bounds = 1.5 but only 5 selected uses 0.75
        assert sum(problem.lower_bounds.values()) == 1.5

    def test_rejects_lower_exceeds_upper(self, portfolio_problem: PortfolioProblem) -> None:
        """Each asset's lower_bound must not exceed upper_bound."""
        with pytest.raises(ValueError, match="lower bound must not exceed"):
            replace(
                portfolio_problem,
                lower_bounds={"asset-a": 0.8, "asset-b": 0.0, "asset-c": 0.0},
                upper_bounds={"asset-a": 0.5, "asset-b": 0.5, "asset-c": 0.5},
            )


# --- Generator tests ---


class TestGeneratorCardinality:
    """Tests for cardinality in portfolio data generation."""

    def test_generate_with_cardinality(self) -> None:
        """Generator propagates cardinality constraints to problem."""
        policy = default_generation_policy(10)
        data = generate_portfolio_data(
            policy,
            lower_bound=0.05,
            upper_bound=0.40,
            min_selected_assets=3,
            max_selected_assets=5,
        )
        problem = data.to_problem()

        assert problem.min_selected_assets == 3
        assert problem.max_selected_assets == 5
        assert all(lb == 0.05 for lb in problem.lower_bounds.values())
        assert all(ub == 0.40 for ub in problem.upper_bounds.values())

    def test_generate_rejects_invalid_cardinality(self) -> None:
        """Generator validates cardinality constraints."""
        policy = default_generation_policy(10)
        with pytest.raises(ValueError, match="cannot exceed max_selected_assets"):
            generate_portfolio_data(
                policy,
                min_selected_assets=8,
                max_selected_assets=3,
            )

    def test_generate_rejects_boolean_cardinality(self) -> None:
        """Generator rejects boolean cardinality values."""
        policy = default_generation_policy(10)
        with pytest.raises(TypeError, match="integer"):
            generate_portfolio_data(
                policy,
                min_selected_assets=True,  # type: ignore[arg-type]
            )

    def test_generate_accepts_equal_bounds(self) -> None:
        """Generator accepts lower_bound == upper_bound for fixed investment."""
        policy = default_generation_policy(10)
        data = generate_portfolio_data(
            policy,
            lower_bound=0.10,
            upper_bound=0.10,  # Equal to lower_bound
            max_selected_assets=10,  # With equal bounds, need exactly 10 assets
        )
        problem = data.to_problem()

        assert all(lb == 0.10 for lb in problem.lower_bounds.values())
        assert all(ub == 0.10 for ub in problem.upper_bounds.values())


# --- Model constraints tests ---


class TestClassicalModelCardinality:
    """Tests for cardinality constraints in the classical model."""

    def test_model_includes_cardinality_constraints(
        self, portfolio_with_cardinality: PortfolioProblem
    ) -> None:
        """Build classical model includes min/max cardinality constraints."""
        adapter = make_adapter()
        retained = tuple(portfolio_with_cardinality.asset_ids)
        manifest = adapter.build_fixing_manifest(portfolio_with_cardinality, retained)
        residual = adapter.restrict_problem(portfolio_with_cardinality, retained, manifest)
        model = residual.build_classical_model()

        constraint_names = {c.name for c in model.linear_constraints}
        assert "min_cardinality" in constraint_names
        assert "max_cardinality" in constraint_names

    def test_model_without_cardinality(self, portfolio_problem: PortfolioProblem) -> None:
        """Model without cardinality constraints omits those constraints."""
        adapter = make_adapter()
        retained = tuple(portfolio_problem.asset_ids)
        manifest = adapter.build_fixing_manifest(portfolio_problem, retained)
        residual = adapter.restrict_problem(portfolio_problem, retained, manifest)
        model = residual.build_classical_model()

        constraint_names = {c.name for c in model.linear_constraints}
        assert "min_cardinality" not in constraint_names
        assert "max_cardinality" not in constraint_names

    def test_constraint_count_includes_cardinality(
        self, portfolio_with_cardinality: PortfolioProblem
    ) -> None:
        """Constraint count property includes cardinality constraints."""
        adapter = make_adapter()
        retained = tuple(portfolio_with_cardinality.asset_ids)
        manifest = adapter.build_fixing_manifest(portfolio_with_cardinality, retained)
        residual = adapter.restrict_problem(portfolio_with_cardinality, retained, manifest)

        # With 4 assets and no fixing: 1 budget + 8 linking + 2 cardinality = 11
        # The manifest has no entries since all are retained
        expected = 1 + 2 * 4 + 2  # budget + linking + cardinality
        assert residual.constraint_count == expected


# --- Postcheck tests ---


class TestPostcheckCardinality:
    """Tests for cardinality validation in postcheck."""

    def test_postcheck_validates_min_cardinality(
        self, portfolio_with_cardinality: PortfolioProblem,
        tolerances: ClassicalSolveOptions,
    ) -> None:
        """Postcheck fails when fewer than min_selected_assets are selected."""
        mapping = PortfolioVariableMapping.for_problem(portfolio_with_cardinality)
        # Select only 1 asset (min is 2)
        values = {
            mapping.delta_variable_by_asset["asset-a"]: 1.0,
            mapping.x_variable_by_asset["asset-a"]: 1.0,
            mapping.delta_variable_by_asset["asset-b"]: 0.0,
            mapping.x_variable_by_asset["asset-b"]: 0.0,
            mapping.delta_variable_by_asset["asset-c"]: 0.0,
            mapping.x_variable_by_asset["asset-c"]: 0.0,
            mapping.delta_variable_by_asset["asset-d"]: 0.0,
            mapping.x_variable_by_asset["asset-d"]: 0.0,
        }
        manifest = FixingManifest(
            retained_item_ids=tuple(portfolio_with_cardinality.asset_ids),
            excluded_item_ids=(),
            entries=(),
            origin="test",
        )
        result = validate_portfolio_solution(
            portfolio_with_cardinality, values, manifest, tolerances
        )

        assert result.postcheck_feasible is False
        assert any("min_cardinality_violation" in r for r in result.failure_reasons)

    def test_postcheck_validates_max_cardinality(
        self, portfolio_with_cardinality: PortfolioProblem,
        tolerances: ClassicalSolveOptions,
    ) -> None:
        """Postcheck fails when more than max_selected_assets are selected."""
        mapping = PortfolioVariableMapping.for_problem(portfolio_with_cardinality)
        # Select 4 assets (max is 3)
        values = {
            mapping.delta_variable_by_asset["asset-a"]: 1.0,
            mapping.x_variable_by_asset["asset-a"]: 0.25,
            mapping.delta_variable_by_asset["asset-b"]: 1.0,
            mapping.x_variable_by_asset["asset-b"]: 0.25,
            mapping.delta_variable_by_asset["asset-c"]: 1.0,
            mapping.x_variable_by_asset["asset-c"]: 0.25,
            mapping.delta_variable_by_asset["asset-d"]: 1.0,
            mapping.x_variable_by_asset["asset-d"]: 0.25,
        }
        manifest = FixingManifest(
            retained_item_ids=tuple(portfolio_with_cardinality.asset_ids),
            excluded_item_ids=(),
            entries=(),
            origin="test",
        )
        result = validate_portfolio_solution(
            portfolio_with_cardinality, values, manifest, tolerances
        )

        assert result.postcheck_feasible is False
        assert any("max_cardinality_violation" in r for r in result.failure_reasons)

    def test_postcheck_passes_valid_cardinality(
        self, portfolio_with_cardinality: PortfolioProblem,
        tolerances: ClassicalSolveOptions,
    ) -> None:
        """Postcheck passes when cardinality is within bounds."""
        mapping = PortfolioVariableMapping.for_problem(portfolio_with_cardinality)
        # Select 2 assets (min=2, max=3)
        values = {
            mapping.delta_variable_by_asset["asset-a"]: 1.0,
            mapping.x_variable_by_asset["asset-a"]: 0.5,
            mapping.delta_variable_by_asset["asset-b"]: 1.0,
            mapping.x_variable_by_asset["asset-b"]: 0.5,
            mapping.delta_variable_by_asset["asset-c"]: 0.0,
            mapping.x_variable_by_asset["asset-c"]: 0.0,
            mapping.delta_variable_by_asset["asset-d"]: 0.0,
            mapping.x_variable_by_asset["asset-d"]: 0.0,
        }
        manifest = FixingManifest(
            retained_item_ids=tuple(portfolio_with_cardinality.asset_ids),
            excluded_item_ids=(),
            entries=(),
            origin="test",
        )
        result = validate_portfolio_solution(
            portfolio_with_cardinality, values, manifest, tolerances
        )

        assert result.postcheck_feasible is True
        assert not any("cardinality" in r for r in result.failure_reasons)


# --- Adapter validation tests ---


class TestAdapterCardinalityValidation:
    """Tests for cardinality validation in adapter's candidate domain check."""

    def test_rejects_domain_below_min_cardinality(self) -> None:
        """Adapter rejects candidate domain with fewer items than min_cardinality."""
        # Use a problem where 1 asset can satisfy the budget (upper_bound=1.0)
        # but min_selected_assets=2 requires at least 2 assets
        problem = PortfolioProblem(
            asset_ids=("asset-a", "asset-b", "asset-c"),
            expected_returns={"asset-a": 0.1, "asset-b": 0.08, "asset-c": 0.06},
            covariance=(
                (0.04, 0.018, 0.002),
                (0.018, 0.09, 0.003),
                (0.002, 0.003, 0.01),
            ),
            lower_bounds={"asset-a": 0.0, "asset-b": 0.0, "asset-c": 0.0},
            upper_bounds={"asset-a": 1.0, "asset-b": 1.0, "asset-c": 1.0},
            retention_scores={"asset-a": 0.9, "asset-b": 0.7, "asset-c": 0.6},
            risk_aversion=1.0,
            min_selected_assets=2,
        )
        adapter = make_adapter()
        # Try to retain only 1 item when min_selected_assets=2
        result = adapter.validate_candidate_domain(problem, ("asset-a",))

        assert result.is_valid is False
        assert any("min_cardinality" in r for r in result.failure_reasons)

    def test_accepts_domain_where_subset_is_feasible(self) -> None:
        """Adapter accepts domain where selecting fewer than all assets is feasible.

        This is the bug case from the review:
        - 3 assets with lower=0.40, upper=0.70
        - max_selected_assets=3 (at most 3, not exactly 3)
        - Solution x=(0.50, 0.50, 0), delta=(1, 1, 0) is valid

        The old code rejected this because sum of 3 lower bounds = 1.20 > 1.
        But we can select only 2 assets, using 0.80 of budget.
        """
        problem = PortfolioProblem(
            asset_ids=("asset-a", "asset-b", "asset-c"),
            expected_returns={"asset-a": 0.1, "asset-b": 0.08, "asset-c": 0.06},
            covariance=(
                (0.04, 0.018, 0.002),
                (0.018, 0.09, 0.003),
                (0.002, 0.003, 0.01),
            ),
            lower_bounds={"asset-a": 0.40, "asset-b": 0.40, "asset-c": 0.40},
            upper_bounds={"asset-a": 0.70, "asset-b": 0.70, "asset-c": 0.70},
            retention_scores={"asset-a": 0.9, "asset-b": 0.7, "asset-c": 0.6},
            risk_aversion=1.0,
            max_selected_assets=3,  # At most 3, can select fewer
        )
        adapter = make_adapter()
        result = adapter.validate_candidate_domain(
            problem, ("asset-a", "asset-b", "asset-c")
        )

        # Domain should be valid - we can select 2 assets
        assert result.is_valid is True

    def test_rejects_domain_where_max_capacity_insufficient(self) -> None:
        """Adapter rejects domain where max_selected upper bounds can't reach budget.

        Setup: 4 assets, max_selected=2
        - Assets a,b have upper=0.60
        - Assets c,d have upper=0.40
        - Full problem: top 2 uppers = 1.20 > 1 ✓

        Now reduce to domain {c, d} only:
        - Capacity = 2 * 0.40 = 0.80 < 1.0 ✗

        The adapter should reject this reduced domain.
        """
        problem = PortfolioProblem(
            asset_ids=("asset-a", "asset-b", "asset-c", "asset-d"),
            expected_returns={"asset-a": 0.1, "asset-b": 0.08, "asset-c": 0.06, "asset-d": 0.05},
            covariance=(
                (0.04, 0.018, 0.002, 0.001),
                (0.018, 0.09, 0.003, 0.002),
                (0.002, 0.003, 0.01, 0.001),
                (0.001, 0.002, 0.001, 0.02),
            ),
            lower_bounds={"asset-a": 0.0, "asset-b": 0.0, "asset-c": 0.0, "asset-d": 0.0},
            upper_bounds={"asset-a": 0.60, "asset-b": 0.60, "asset-c": 0.40, "asset-d": 0.40},
            retention_scores={"asset-a": 0.9, "asset-b": 0.7, "asset-c": 0.6, "asset-d": 0.5},
            risk_aversion=1.0,
            max_selected_assets=2,  # Can only select 2
        )
        adapter = make_adapter()
        # Restrict to only assets c and d, which have lower capacity
        result = adapter.validate_candidate_domain(
            problem, ("asset-c", "asset-d")
        )

        # Domain should be invalid - max capacity is 0.80 < 1.0
        assert result.is_valid is False
        assert any("cannot_satisfy_unit_budget" in r for r in result.failure_reasons)

    def test_accepts_domain_at_min_cardinality(
        self, portfolio_with_cardinality: PortfolioProblem
    ) -> None:
        """Adapter accepts candidate domain with exactly min_cardinality items."""
        adapter = make_adapter()
        result = adapter.validate_candidate_domain(
            portfolio_with_cardinality, ("asset-a", "asset-b")
        )

        assert result.is_valid is True


# --- Integration tests ---


class TestIntegrationWithCardinality:
    """Integration tests for full workflow with cardinality constraints."""

    def test_baseline_with_cardinality_scip(self) -> None:
        """Baseline (classical-only) run with cardinality constraints using SCIP."""
        import tempfile

        from qreduce.experiments.portfolio.execution import run_portfolio_experiment
        from qreduce.models import ReductionPolicy, RunStatus

        with tempfile.TemporaryDirectory() as tmpdir:
            # max_reduction_rounds=0 means baseline (no reduction)
            reduction = ReductionPolicy(
                max_reduction_rounds=0,
                candidate_domain_min_items=1,
                candidate_domain_max_items=10,
                num_source_mis_candidates=1,
                min_reduction_ratio=0.1,
                target_binary_variables=3,
                max_end_to_end_runtime_seconds=30.0,
            )

            run = run_portfolio_experiment(
                "test-baseline-cardinality",
                output_root=tmpdir,
                asset_count=10,
                lower_bound=0.05,
                upper_bound=0.30,
                min_selected_assets=4,
                max_selected_assets=6,
                reduction_policy=reduction,
                classical_solver_id="scip",
            )

            # Verify run completed
            assert run.run_directory is not None
            assert run.result.run_result.run_status == RunStatus.SUCCESS

            # Verify solution respects cardinality
            classical_result = run.result.classical_result
            if classical_result and classical_result.variable_values:
                # Count selected assets
                selected = sum(
                    1 for k, v in classical_result.variable_values.items()
                    if k.startswith("delta__") and abs(v - 1.0) < 0.01
                )
                assert 4 <= selected <= 6, f"Expected 4-6 selected, got {selected}"

    def test_single_pass_with_positive_minimum_scip(self) -> None:
        """Single-pass reduction with positive minimum investment using SCIP.

        Uses parameters that guarantee a feasible solution exists:
        - 10 assets with lower=0.10, upper=0.50
        - min_selected=2, max_selected=5
        - Budget of 1.0 is easily satisfiable with 2-5 assets
        """
        import tempfile

        from qreduce.experiments.portfolio.execution import run_portfolio_experiment
        from qreduce.models import ReductionPolicy, RunStatus

        with tempfile.TemporaryDirectory() as tmpdir:
            # max_reduction_rounds=1 means single-pass
            # Use conservative domain limits to ensure reduction succeeds
            reduction = ReductionPolicy(
                max_reduction_rounds=1,
                candidate_domain_min_items=5,
                candidate_domain_max_items=8,
                num_source_mis_candidates=1,
                min_reduction_ratio=0.1,
                target_binary_variables=3,
                max_end_to_end_runtime_seconds=30.0,
            )

            run = run_portfolio_experiment(
                "test-single-pass-positive-min",
                output_root=tmpdir,
                asset_count=10,
                lower_bound=0.10,  # Positive minimum
                upper_bound=0.50,
                min_selected_assets=2,
                max_selected_assets=5,
                reduction_policy=reduction,
                classical_solver_id="scip",
            )

            # Verify run completed successfully
            assert run.run_directory is not None
            run_status = run.result.run_result.run_status
            assert run_status == RunStatus.SUCCESS, f"Expected SUCCESS, got {run_status}"

            # Verify postcheck passed
            postcheck = run.result.postcheck_result
            assert postcheck is not None
            assert postcheck.postcheck_feasible, f"Postcheck failed: {postcheck.failure_reasons}"

            # Verify solution respects cardinality and minimum investment
            classical_result = run.result.classical_result
            assert classical_result is not None
            assert classical_result.variable_values is not None

            # Count selected assets and verify investment bounds
            selected_count = 0
            for k, v in classical_result.variable_values.items():
                if k.startswith("delta__") and abs(v - 1.0) < 0.01:
                    selected_count += 1
                    # Verify corresponding x value respects lower bound
                    asset_id = k.replace("delta__", "")
                    x_key = f"x__{asset_id}"
                    x_value = classical_result.variable_values.get(x_key, 0.0)
                    assert x_value >= 0.10 - 1e-6, f"Asset {asset_id}: x={x_value} < lower_bound=0.10"

            assert 2 <= selected_count <= 5, f"Expected 2-5 selected, got {selected_count}"

    def test_cli_argument_parsing(self) -> None:
        """CLI correctly parses cardinality and bounds arguments."""
        from qreduce.experiments.portfolio.__main__ import _build_parser, _validate_args

        parser = _build_parser()

        # Valid arguments
        args = parser.parse_args([
            "--run-id", "test",
            "--lower-bound", "0.05",
            "--upper-bound", "0.25",
            "--min-selected-assets", "5",
            "--max-selected-assets", "10",
        ])
        _validate_args(parser, args)

        assert args.lower_bound == 0.05
        assert args.upper_bound == 0.25
        assert args.min_selected_assets == 5
        assert args.max_selected_assets == 10

    def test_cli_rejects_invalid_bounds(self) -> None:
        """CLI rejects invalid bounds combinations."""
        from qreduce.experiments.portfolio.__main__ import _build_parser, _validate_args

        parser = _build_parser()

        # upper_bound < lower_bound (now strictly less than)
        args = parser.parse_args([
            "--run-id", "test",
            "--lower-bound", "0.5",
            "--upper-bound", "0.3",
        ])
        with pytest.raises(SystemExit):
            _validate_args(parser, args)

    def test_cli_accepts_equal_bounds(self) -> None:
        """CLI accepts lower_bound == upper_bound for fixed investment."""
        from qreduce.experiments.portfolio.__main__ import _build_parser, _validate_args

        parser = _build_parser()

        # lower_bound == upper_bound is valid (fixed investment per selected asset)
        args = parser.parse_args([
            "--run-id", "test",
            "--lower-bound", "0.10",
            "--upper-bound", "0.10",
        ])
        _validate_args(parser, args)  # Should not raise

        assert args.lower_bound == 0.10
        assert args.upper_bound == 0.10

    def test_cli_rejects_invalid_cardinality(self) -> None:
        """CLI rejects invalid cardinality combinations."""
        from qreduce.experiments.portfolio.__main__ import _build_parser, _validate_args

        parser = _build_parser()

        # min > max
        args = parser.parse_args([
            "--run-id", "test",
            "--min-selected-assets", "10",
            "--max-selected-assets", "5",
        ])
        with pytest.raises(SystemExit):
            _validate_args(parser, args)
