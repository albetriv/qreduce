"""Tests for immutable mean-variance portfolio data contracts."""

from dataclasses import replace

import pytest

from qreduce.experiments.portfolio_mv import (
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


@pytest.mark.parametrize("off_diagonal", [0.5, 1.0, 1.0 + 5e-9])
def test_explicit_covariance_accepts_singular_and_nearly_psd(portfolio_problem, off_diagonal):
    covariance = ((1.0, off_diagonal, 0.0), (off_diagonal, 1.0, 0.0), (0.0, 0.0, 1.0))
    assert replace(portfolio_problem, covariance=covariance).covariance == covariance


@pytest.mark.parametrize("off_diagonal", [1.0 + 2e-8, 2.0])
def test_explicit_covariance_rejects_indefinite(portfolio_problem, off_diagonal):
    covariance = ((1.0, off_diagonal, 0.0), (off_diagonal, 1.0, 0.0), (0.0, 0.0, 1.0))
    with pytest.raises(ValueError, match="positive semi-definite"):
        replace(portfolio_problem, covariance=covariance)


def test_explicit_covariance_rejects_indefinite_with_valid_pairwise_correlations(portfolio_problem):
    covariance = ((1.0, -0.6, -0.6), (-0.6, 1.0, -0.6), (-0.6, -0.6, 1.0))
    with pytest.raises(ValueError, match="positive semi-definite"):
        replace(portfolio_problem, covariance=covariance)


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



class TestPortfolioProblemRiskAversionValidation:
    """Tests for risk_aversion validation in PortfolioProblem constructor."""

    def _make_problem_kwargs(self, risk_aversion):
        """Create valid problem kwargs except for risk_aversion."""
        return {
            "asset_ids": ("A", "B"),
            "expected_returns": {"A": 0.1, "B": 0.2},
            "covariance": ((0.04, 0.01), (0.01, 0.09)),
            "lower_bounds": {"A": 0.0, "B": 0.0},
            "upper_bounds": {"A": 0.5, "B": 0.5},
            "retention_scores": {"A": 0.5, "B": 0.5},
            "risk_aversion": risk_aversion,
        }

    def test_rejects_none(self):
        """risk_aversion=None raises TypeError."""
        from qreduce.experiments.portfolio_mv import PortfolioProblem
        with pytest.raises(TypeError, match="cannot be None"):
            PortfolioProblem(**self._make_problem_kwargs(None))

    def test_rejects_boolean_true(self):
        """risk_aversion=True raises TypeError."""
        from qreduce.experiments.portfolio_mv import PortfolioProblem
        with pytest.raises(TypeError, match="not a boolean"):
            PortfolioProblem(**self._make_problem_kwargs(True))

    def test_rejects_boolean_false(self):
        """risk_aversion=False raises TypeError."""
        from qreduce.experiments.portfolio_mv import PortfolioProblem
        with pytest.raises(TypeError, match="not a boolean"):
            PortfolioProblem(**self._make_problem_kwargs(False))

    def test_rejects_nan(self):
        """risk_aversion=NaN raises ValueError."""
        from qreduce.experiments.portfolio_mv import PortfolioProblem
        with pytest.raises(ValueError, match="finite"):
            PortfolioProblem(**self._make_problem_kwargs(float("nan")))

    def test_rejects_infinity(self):
        """risk_aversion=inf raises ValueError."""
        from qreduce.experiments.portfolio_mv import PortfolioProblem
        with pytest.raises(ValueError, match="finite"):
            PortfolioProblem(**self._make_problem_kwargs(float("inf")))

    def test_rejects_zero(self):
        """risk_aversion=0 raises ValueError."""
        from qreduce.experiments.portfolio_mv import PortfolioProblem
        with pytest.raises(ValueError, match="strictly positive"):
            PortfolioProblem(**self._make_problem_kwargs(0))

    def test_rejects_negative(self):
        """risk_aversion=-1.0 raises ValueError."""
        from qreduce.experiments.portfolio_mv import PortfolioProblem
        with pytest.raises(ValueError, match="strictly positive"):
            PortfolioProblem(**self._make_problem_kwargs(-1.0))

    def test_accepts_valid_values(self):
        """risk_aversion accepts valid positive finite values."""
        from qreduce.experiments.portfolio_mv import PortfolioProblem
        for value in [0.001, 1.0, 2.5, 100]:
            problem = PortfolioProblem(**self._make_problem_kwargs(value))
            assert problem.risk_aversion == value



class TestRiskAversionScaling:
    """Test that risk_aversion correctly scales quadratic terms in the model."""

    def test_quadratic_terms_scale_with_risk_aversion(self):
        """Quadratic objective terms scale linearly with risk_aversion."""
        from qreduce.experiments.portfolio_mv import (
            MeanVariancePortfolioAdapter,
            PortfolioGraphPolicy,
            PortfolioProblem,
        )

        # Create two problems with different risk_aversion
        base_kwargs = {
            "asset_ids": ("A", "B"),
            "expected_returns": {"A": 0.1, "B": 0.2},
            "covariance": ((0.04, 0.01), (0.01, 0.09)),
            "lower_bounds": {"A": 0.0, "B": 0.0},
            "upper_bounds": {"A": 0.5, "B": 0.5},
            "retention_scores": {"A": 0.5, "B": 0.5},
        }

        problem_1 = PortfolioProblem(**base_kwargs, risk_aversion=1.0)
        problem_2 = PortfolioProblem(**base_kwargs, risk_aversion=2.5)

        # Build models using adapter (retain all assets)
        policy = PortfolioGraphPolicy("test", "1", 0.25, edge_mode="correlation_only")
        adapter = MeanVariancePortfolioAdapter(policy)
        retained = ("A", "B")

        residual_1 = adapter.restrict_problem(
            problem_1, retained, adapter.build_fixing_manifest(problem_1, retained)
        )
        residual_2 = adapter.restrict_problem(
            problem_2, retained, adapter.build_fixing_manifest(problem_2, retained)
        )

        model_1 = residual_1.build_classical_model()
        model_2 = residual_2.build_classical_model()

        # Extract quadratic coefficients
        quad_1 = {(t.left_variable, t.right_variable): t.coefficient for t in model_1.quadratic_objective}
        quad_2 = {(t.left_variable, t.right_variable): t.coefficient for t in model_2.quadratic_objective}

        # Verify quadratic terms scale with risk_aversion
        for key, coeff_1 in quad_1.items():
            assert quad_2[key] == pytest.approx(coeff_1 * 2.5), f"Term {key} should scale by 2.5"

    def test_linear_terms_invariant_to_risk_aversion(self):
        """Linear objective terms (from expected returns) are invariant to risk_aversion."""
        from qreduce.experiments.portfolio_mv import (
            MeanVariancePortfolioAdapter,
            PortfolioGraphPolicy,
            PortfolioProblem,
        )

        base_kwargs = {
            "asset_ids": ("A", "B"),
            "expected_returns": {"A": 0.1, "B": 0.2},
            "covariance": ((0.04, 0.01), (0.01, 0.09)),
            "lower_bounds": {"A": 0.0, "B": 0.0},
            "upper_bounds": {"A": 0.5, "B": 0.5},
            "retention_scores": {"A": 0.5, "B": 0.5},
        }

        problem_1 = PortfolioProblem(**base_kwargs, risk_aversion=1.0)
        problem_2 = PortfolioProblem(**base_kwargs, risk_aversion=2.5)

        policy = PortfolioGraphPolicy("test", "1", 0.25, edge_mode="correlation_only")
        adapter = MeanVariancePortfolioAdapter(policy)
        retained = ("A", "B")

        residual_1 = adapter.restrict_problem(
            problem_1, retained, adapter.build_fixing_manifest(problem_1, retained)
        )
        residual_2 = adapter.restrict_problem(
            problem_2, retained, adapter.build_fixing_manifest(problem_2, retained)
        )

        model_1 = residual_1.build_classical_model()
        model_2 = residual_2.build_classical_model()

        # Linear terms should be identical
        assert model_1.linear_objective == model_2.linear_objective, "Linear terms should not change with risk_aversion"

    def test_constraints_invariant_to_risk_aversion(self):
        """Constraints (budget, bounds) are invariant to risk_aversion."""
        from qreduce.experiments.portfolio_mv import (
            MeanVariancePortfolioAdapter,
            PortfolioGraphPolicy,
            PortfolioProblem,
        )

        base_kwargs = {
            "asset_ids": ("A", "B"),
            "expected_returns": {"A": 0.1, "B": 0.2},
            "covariance": ((0.04, 0.01), (0.01, 0.09)),
            "lower_bounds": {"A": 0.0, "B": 0.0},
            "upper_bounds": {"A": 0.5, "B": 0.5},
            "retention_scores": {"A": 0.5, "B": 0.5},
        }

        problem_1 = PortfolioProblem(**base_kwargs, risk_aversion=1.0)
        problem_2 = PortfolioProblem(**base_kwargs, risk_aversion=2.5)

        policy = PortfolioGraphPolicy("test", "1", 0.25, edge_mode="correlation_only")
        adapter = MeanVariancePortfolioAdapter(policy)
        retained = ("A", "B")

        residual_1 = adapter.restrict_problem(
            problem_1, retained, adapter.build_fixing_manifest(problem_1, retained)
        )
        residual_2 = adapter.restrict_problem(
            problem_2, retained, adapter.build_fixing_manifest(problem_2, retained)
        )

        model_1 = residual_1.build_classical_model()
        model_2 = residual_2.build_classical_model()

        # Constraints should be identical
        constraints_1 = sorted([(c.name, sorted(c.coefficients.items()), c.right_hand_side, c.sense) for c in model_1.linear_constraints])
        constraints_2 = sorted([(c.name, sorted(c.coefficients.items()), c.right_hand_side, c.sense) for c in model_2.linear_constraints])

        assert constraints_1 == constraints_2, "Constraints should not change with risk_aversion"
        assert model_1.variables == model_2.variables, "Variable domains and bounds should not change"
