"""Unit tests for formulation.py and postcheck.py."""

import math

import numpy as np

from qreduce.domains.contracts import FixingEntry, FixingManifest
from qreduce.experiments.portfolio_sr.formulation import (
    PortfolioMetrics,
    compute_portfolio_metrics,
    compute_retention_scores,
    compute_transformed_objective,
    reconstruct_solution,
    sharpe_from_objective,
    validate_cardinality_constraint,
    validate_sector_constraints,
    validate_x_scale_bounds,
)
from qreduce.experiments.portfolio_sr.models import (
    SectorConstraints,
    SharpePortfolioProblem,
    SharpeVariableMapping,
)
from qreduce.experiments.portfolio_sr.postcheck import (
    extract_solution_summary,
    validate_sharpe_solution,
)
from qreduce.models import ClassicalSolveOptions, PostcheckMode


def _make_test_options() -> ClassicalSolveOptions:
    """Create default ClassicalSolveOptions for tests."""
    return ClassicalSolveOptions(
        classical_solver_id="scip",
        time_limit_seconds=60.0,
        mip_gap_tolerance=None,
        threads=None,
        model_export_enabled=False,
        primal_feasibility_tolerance=1e-6,
        integrality_tolerance=1e-6,
        objective_recomputation_absolute_tolerance=1e-6,
        objective_recomputation_relative_tolerance=1e-4,
        postcheck_mode=PostcheckMode.STRICT,
    )


def _make_simple_problem() -> SharpePortfolioProblem:
    """Create a simple test problem."""
    return SharpePortfolioProblem(
        tickers=("A", "B", "C"),
        mean_returns={"A": 0.10, "B": 0.15, "C": 0.12},
        covariance=(
            (0.04, 0.01, 0.005),
            (0.01, 0.09, 0.02),
            (0.005, 0.02, 0.0625),
        ),
        sectors={"A": "Tech", "B": "Health", "C": "Tech"},
        upper_bounds={"A": 1.0, "B": 1.0, "C": 1.0},
        _covariance_validated=True,
    )


def _make_cardinality_problem() -> SharpePortfolioProblem:
    """Create a problem with cardinality constraint."""
    return SharpePortfolioProblem(
        tickers=("A", "B", "C", "D"),
        mean_returns={"A": 0.10, "B": 0.15, "C": 0.12, "D": 0.08},
        covariance=(
            (0.04, 0.01, 0.005, 0.003),
            (0.01, 0.09, 0.02, 0.01),
            (0.005, 0.02, 0.0625, 0.008),
            (0.003, 0.01, 0.008, 0.0361),
        ),
        sectors={"A": "Tech", "B": "Health", "C": "Tech", "D": "Finance"},
        upper_bounds={"A": 0.5, "B": 0.5, "C": 0.5, "D": 0.5},
        max_positions=2,
        _covariance_validated=True,
    )


def _make_sector_constrained_problem() -> SharpePortfolioProblem:
    """Create a problem with sector constraints."""
    return SharpePortfolioProblem(
        tickers=("A", "B", "C"),
        mean_returns={"A": 0.10, "B": 0.15, "C": 0.12},
        covariance=(
            (0.04, 0.01, 0.005),
            (0.01, 0.09, 0.02),
            (0.005, 0.02, 0.0625),
        ),
        sectors={"A": "Tech", "B": "Health", "C": "Tech"},
        upper_bounds={"A": 1.0, "B": 1.0, "C": 1.0},
        sector_constraints=SectorConstraints(
            sector_min={"Tech": 0.20, "Health": 0.10},
            sector_max={"Tech": 0.60, "Health": 0.50},
        ),
        _covariance_validated=True,
    )


class TestTransformationFormulas:
    """Tests for the Sharpe transformation formulas."""

    def test_sharpe_from_objective_basic(self) -> None:
        """SR = 1/sqrt(objective)."""
        objective = 0.25
        sr = sharpe_from_objective(objective)
        assert abs(sr - 2.0) < 1e-10

    def test_sharpe_from_zero_objective_is_inf(self) -> None:
        """Zero objective gives infinite Sharpe."""
        sr = sharpe_from_objective(0.0)
        assert math.isinf(sr)

    def test_sharpe_from_negative_objective_is_nan(self) -> None:
        """Negative objective gives NaN."""
        sr = sharpe_from_objective(-1.0)
        assert math.isnan(sr)

    def test_compute_transformed_objective(self) -> None:
        """Objective is x_scaled^T Sigma x_scaled."""
        problem = _make_simple_problem()
        scaled_weights = {"A": 0.5, "B": 0.3, "C": 0.2}

        obj = compute_transformed_objective(problem, scaled_weights)

        # Manual calculation
        x = np.array([0.5, 0.3, 0.2])
        cov = np.array(problem.covariance)
        expected = float(x @ cov @ x)

        assert abs(obj - expected) < 1e-10


class TestXScaleBounds:
    """Tests for x_scale bounds validation."""

    def test_valid_x_scale(self) -> None:
        """x_scale within bounds passes."""
        problem = _make_simple_problem()
        _lb, _ub = problem.x_scale_bounds  # 1/0.15, 1/0.10 = 6.67, 10

        valid, msg = validate_x_scale_bounds(problem, 8.0)

        assert valid
        assert msg is None

    def test_x_scale_below_bound(self) -> None:
        """x_scale below lower bound fails."""
        problem = _make_simple_problem()

        valid, msg = validate_x_scale_bounds(problem, 5.0)  # < 1/mu_max = 6.67

        assert not valid
        assert "below lower bound" in msg

    def test_x_scale_above_bound(self) -> None:
        """x_scale above upper bound fails."""
        problem = _make_simple_problem()

        valid, msg = validate_x_scale_bounds(problem, 15.0)  # > 1/mu_min = 10

        assert not valid
        assert "above upper bound" in msg


class TestSectorConstraintValidation:
    """Tests for sector constraint validation."""

    def test_valid_sector_exposures(self) -> None:
        """Valid exposures pass validation."""
        problem = _make_sector_constrained_problem()
        weights = {"A": 0.3, "B": 0.4, "C": 0.3}  # Tech=0.6, Health=0.4

        valid, violations = validate_sector_constraints(problem, weights)

        assert valid
        assert len(violations) == 0

    def test_sector_below_minimum(self) -> None:
        """Exposure below minimum fails."""
        problem = _make_sector_constrained_problem()
        weights = {"A": 0.05, "B": 0.9, "C": 0.05}  # Tech=0.1 < min 0.2

        valid, violations = validate_sector_constraints(problem, weights)

        assert not valid
        assert any("Tech" in v and "below minimum" in v for v in violations)

    def test_sector_above_maximum(self) -> None:
        """Exposure above maximum fails."""
        problem = _make_sector_constrained_problem()
        weights = {"A": 0.4, "B": 0.1, "C": 0.5}  # Tech=0.9 > max 0.6

        valid, violations = validate_sector_constraints(problem, weights)

        assert not valid
        assert any("Tech" in v and "above maximum" in v for v in violations)


class TestCardinalityConstraintValidation:
    """Tests for cardinality constraint validation."""

    def test_valid_cardinality(self) -> None:
        """Within cardinality limit passes."""
        problem = _make_cardinality_problem()
        weights = {"A": 0.6, "B": 0.4, "C": 0.0, "D": 0.0}

        valid, msg = validate_cardinality_constraint(problem, weights, {"A": 1, "B": 1, "C": 0, "D": 0})

        assert valid
        assert msg is None

    def test_cardinality_exceeded(self) -> None:
        """Exceeding cardinality fails."""
        problem = _make_cardinality_problem()
        weights = {"A": 0.4, "B": 0.3, "C": 0.3, "D": 0.0}  # 3 positions > max 2

        valid, msg = validate_cardinality_constraint(problem, weights, {"A": 1, "B": 1, "C": 1, "D": 0})

        assert not valid
        assert "3 positions exceed maximum 2" in msg

    def test_delta_integrality_checked(self) -> None:
        """Non-integral delta values fail."""
        problem = _make_cardinality_problem()
        weights = {"A": 0.6, "B": 0.4, "C": 0.0, "D": 0.0}
        delta_values = {"A": 0.5, "B": 1.0, "C": 0.0, "D": 0.0}  # A is non-integral

        valid, msg = validate_cardinality_constraint(
            problem, weights, delta_values, integrality_tolerance=0.01
        )

        assert not valid
        assert "Non-integral delta" in msg


class TestComputePortfolioMetrics:
    """Tests for compute_portfolio_metrics function."""

    def test_metrics_computed_correctly(self) -> None:
        """All metrics are computed."""
        problem = _make_simple_problem()
        weights = {"A": 0.4, "B": 0.3, "C": 0.3}

        metrics = compute_portfolio_metrics(problem, weights)

        assert isinstance(metrics, PortfolioMetrics)
        assert math.isfinite(metrics.expected_return)
        assert math.isfinite(metrics.volatility)
        assert math.isfinite(metrics.sharpe_ratio)
        assert metrics.effective_positions == 3
        assert metrics.max_weight == 0.4

    def test_sector_exposures_computed(self) -> None:
        """Sector exposures are aggregated correctly."""
        problem = _make_simple_problem()
        weights = {"A": 0.4, "B": 0.3, "C": 0.3}  # Tech: A+C=0.7, Health: B=0.3

        metrics = compute_portfolio_metrics(problem, weights)

        assert abs(metrics.sector_exposures["Tech"] - 0.7) < 1e-10
        assert abs(metrics.sector_exposures["Health"] - 0.3) < 1e-10


class TestComputeRetentionScores:
    """Tests for compute_retention_scores function."""

    def test_sharpe_scores_positive(self) -> None:
        """Sharpe scores are non-negative."""
        problem = _make_simple_problem()

        scores = compute_retention_scores(problem, score_type="individual_sharpe")

        assert all(s >= 0 for s in scores.values())

    def test_uniform_scores(self) -> None:
        """Uniform scores are all equal."""
        problem = _make_simple_problem()

        scores = compute_retention_scores(problem, score_type="uniform")

        assert all(s == 1.0 for s in scores.values())

    def test_normalized_by_max(self) -> None:
        """Scores are normalized so max is 1.0."""
        problem = _make_simple_problem()

        scores = compute_retention_scores(problem, score_type="individual_sharpe", normalize=True)

        assert max(scores.values()) == 1.0


class TestReconstructSolution:
    """Tests for reconstruct_solution function."""

    def test_valid_reconstruction(self) -> None:
        """Valid solution reconstructs correctly."""
        problem = _make_simple_problem()

        # Create a valid solution
        # With mu = [0.10, 0.15, 0.12], need mu^T x_scaled = 1
        # Let's use x_scaled proportional to [0.4, 0.3, 0.3], scaled so mu^T x = 1
        # 0.10*a + 0.15*b + 0.12*c = 1 with a:b:c = 4:3:3
        # 0.10*4k + 0.15*3k + 0.12*3k = k(0.4 + 0.45 + 0.36) = 1.21k = 1 => k = 0.826
        k = 1 / (0.10 * 4 + 0.15 * 3 + 0.12 * 3)
        x_scaled_a = 4 * k
        x_scaled_b = 3 * k
        x_scaled_c = 3 * k
        x_scale = x_scaled_a + x_scaled_b + x_scaled_c

        variable_values = {
            "x_scale": x_scale,
            "x_scaled__A": x_scaled_a,
            "x_scaled__B": x_scaled_b,
            "x_scaled__C": x_scaled_c,
        }

        result = reconstruct_solution(problem, variable_values)

        assert result.is_valid
        assert abs(sum(result.original_weights.values()) - 1.0) < 1e-6

    def test_missing_x_scale_fails(self) -> None:
        """Missing x_scale variable fails."""
        problem = _make_simple_problem()
        variable_values = {
            "x_scaled__A": 0.5,
            "x_scaled__B": 0.3,
            "x_scaled__C": 0.2,
        }

        result = reconstruct_solution(problem, variable_values)

        assert not result.is_valid
        assert "Missing variable" in result.validation_messages[0]


class TestValidateSharpeSolution:
    """Tests for validate_sharpe_solution function."""

    def _make_valid_solution(self, problem: SharpePortfolioProblem) -> dict[str, float]:
        """Create a valid solution for testing."""
        # Simple approach: equal weights in scaled space, then adjust for return normalization
        n = len(problem.tickers)
        mu = np.array([problem.mean_returns[t] for t in problem.tickers])

        # x_scaled proportional to 1/n each, scaled so mu^T x_scaled = 1
        k = 1 / np.sum(mu / n)
        x_scaled = {t: k / n for t in problem.tickers}
        x_scale = sum(x_scaled.values())

        mapping = SharpeVariableMapping.for_problem(problem)
        solution = {mapping.x_scale_variable: x_scale}
        for t in problem.tickers:
            solution[mapping.x_scaled_by_ticker[t]] = x_scaled[t]
            solution[mapping.delta_by_ticker[t]] = 1.0

        return solution

    def test_valid_solution_passes(self) -> None:
        """A valid solution passes postcheck."""
        problem = _make_simple_problem()
        solution = self._make_valid_solution(problem)
        manifest = FixingManifest(
            retained_item_ids=problem.tickers,
            excluded_item_ids=(),
            entries=(),
            origin="test",
        )
        tolerances = _make_test_options()

        result = validate_sharpe_solution(
            problem, solution, manifest, tolerances
        )

        assert result.postcheck_feasible

    def test_budget_violation_detected(self) -> None:
        """Budget constraint violation is detected."""
        problem = _make_simple_problem()
        mapping = SharpeVariableMapping.for_problem(problem)

        # Manually create invalid solution with sum(x) != 1
        solution = {
            mapping.x_scale_variable: 8.0,
            mapping.x_scaled_by_ticker["A"]: 4.0,  # x_A = 0.5
            mapping.x_scaled_by_ticker["B"]: 4.0,  # x_B = 0.5
            mapping.x_scaled_by_ticker["C"]: 4.0,  # x_C = 0.5 => sum = 1.5 != 1
        }
        manifest = FixingManifest(
            retained_item_ids=problem.tickers,
            excluded_item_ids=(),
            entries=(),
            origin="test",
        )
        tolerances = _make_test_options()

        result = validate_sharpe_solution(
            problem, solution, manifest, tolerances
        )

        assert not result.postcheck_feasible
        assert any("budget" in r.lower() for r in result.failure_reasons)

    def test_fixing_manifest_compliance(self) -> None:
        """Fixing manifest compliance is checked."""
        problem = _make_simple_problem()
        mapping = SharpeVariableMapping.for_problem(problem)

        # Create solution where excluded ticker has non-zero weight
        k = 1 / (0.10 * 5 + 0.15 * 5)  # Only A and B
        solution = {
            mapping.x_scale_variable: 10 * k,
            mapping.x_scaled_by_ticker["A"]: 5 * k,
            mapping.x_scaled_by_ticker["B"]: 5 * k,
            mapping.x_scaled_by_ticker["C"]: 0.1,  # Should be 0
        }
        manifest = FixingManifest(
            retained_item_ids=("A", "B"),
            excluded_item_ids=("C",),
            entries=(
                FixingEntry(
                    item_id="C",
                    variable_values={mapping.x_scaled_by_ticker["C"]: 0.0},
                    reason="excluded",
                ),
            ),
            origin="test",
        )
        tolerances = _make_test_options()

        result = validate_sharpe_solution(
            problem, solution, manifest, tolerances
        )

        assert not result.postcheck_feasible
        assert any("fixing" in r.lower() for r in result.failure_reasons)


class TestExtractSolutionSummary:
    """Tests for extract_solution_summary function."""

    def test_summary_extraction(self) -> None:
        """Summary extracts key metrics."""
        problem = _make_simple_problem()
        mapping = SharpeVariableMapping.for_problem(problem)

        k = 1 / (0.10 / 3 + 0.15 / 3 + 0.12 / 3)
        x_scale = k
        solution = {
            mapping.x_scale_variable: x_scale,
            mapping.x_scaled_by_ticker["A"]: k / 3,
            mapping.x_scaled_by_ticker["B"]: k / 3,
            mapping.x_scaled_by_ticker["C"]: k / 3,
        }

        summary = extract_solution_summary(problem, solution)

        assert "x_scale" in summary
        assert "sharpe_ratio" in summary
        assert "expected_return" in summary
        assert "volatility" in summary
        assert "position_count" in summary

    def test_invalid_x_scale_returns_error(self) -> None:
        """Invalid x_scale returns error in summary."""
        problem = _make_simple_problem()
        solution = {"x_scale": -1.0}  # Invalid

        summary = extract_solution_summary(problem, solution)

        assert "error" in summary


def test_lower_bound_selection_model_and_postcheck() -> None:
    from dataclasses import replace

    from qreduce.experiments.portfolio_sr.models import TransformedSharpeProblem

    problem = replace(_make_simple_problem(), lower_bound=0.2)
    mapping = SharpeVariableMapping.for_problem(problem)
    manifest = FixingManifest(retained_item_ids=problem.tickers, excluded_item_ids=(), entries=(), origin="test")
    transformed = TransformedSharpeProblem(problem, problem.tickers, manifest, mapping)
    model = transformed.build_classical_model()
    assert problem.has_selection_binaries
    assert transformed.variable_count == len(model.variables)
    assert transformed.constraint_count == len(model.linear_constraints)
    assert not any(c.name == "max_cardinality" for c in model.linear_constraints)
    lower = next(c for c in model.linear_constraints if c.name == "lower_bound__A")
    assert lower.coefficients[mapping.x_scale_variable] == -0.2
    assert lower.coefficients[mapping.delta_by_ticker["A"]] == -0.2 * problem.x_scale_bounds[1]
    assert lower.right_hand_side == -0.2 * problem.x_scale_bounds[1]

    weights = {"A": 0.1, "B": 0.4, "C": 0.5}
    scale = 1 / sum(problem.mean_returns[t] * weights[t] for t in problem.tickers)
    solution = {mapping.x_scale_variable: scale}
    solution.update({mapping.x_scaled_by_ticker[t]: scale * weights[t] for t in problem.tickers})
    solution.update({mapping.delta_by_ticker[t]: 1.0 for t in problem.tickers})
    result = validate_sharpe_solution(problem, solution, manifest, _make_test_options())
    assert not result.original_constraint_compliance
    assert result.integrality_compliance
    assert any(m.startswith("lower_bound_violated:A") for m in result.failure_reasons)
    del solution[mapping.delta_by_ticker["A"]]
    result = validate_sharpe_solution(problem, solution, manifest, _make_test_options())
    assert not result.integrality_compliance


def test_lower_bound_feasibility_validation() -> None:
    from dataclasses import replace

    import pytest

    problem = _make_simple_problem()
    for value in (-0.1, 1.1, float("nan"), float("inf")):
        with pytest.raises(ValueError, match="lower_bound"):
            replace(problem, lower_bound=value)
    with pytest.raises(ValueError, match="insufficient_budget_capacity"):
        replace(problem, lower_bound=0.4, upper_bounds=dict.fromkeys(problem.tickers, 0.45))
    for value in (1e-310, math.ulp(0.0)):
        tiny_minimum = replace(problem, lower_bound=value)
        assert tiny_minimum.has_selection_binaries
        assert not tiny_minimum.selection_feasibility_issues(problem.tickers)
    assert "lower_bound" not in problem.to_dict()
    assert replace(problem, lower_bound=0.2).to_dict()["lower_bound"] == 0.2


def test_lower_bound_reduced_domain_and_fixings() -> None:
    from dataclasses import replace

    from qreduce.experiments.portfolio_sr.adapter import SharpePortfolioAdapter
    from qreduce.experiments.portfolio_sr.graph_policy import (
        default_sharpe_graph_policy,
    )

    problem = replace(_make_simple_problem(), lower_bound=0.3)
    adapter = SharpePortfolioAdapter(default_sharpe_graph_policy())
    assert adapter.describe_logical_variables(problem).binary_free == 3
    manifest = adapter.build_fixing_manifest(problem, ("A", "B"))
    assert manifest.entries[0].variable_values["delta__C"] == 0
    constrained = replace(problem, upper_bounds=dict.fromkeys(problem.tickers, 0.5), lower_bound=0.4)
    assert not adapter.validate_candidate_domain(constrained, ("A",)).is_valid
