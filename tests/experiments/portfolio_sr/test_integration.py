"""Integration tests for portfolio_sr pipeline execution."""



from qreduce.domains.contracts import FixingManifest
from qreduce.experiments.portfolio_sr.adapter import SharpePortfolioAdapter
from qreduce.experiments.portfolio_sr.graph_policy import (
    default_sharpe_graph_policy,
)
from qreduce.experiments.portfolio_sr.models import (
    SectorConstraints,
    SharpeGraphPolicy,
    SharpePortfolioProblem,
    SharpeVariableMapping,
    TransformedSharpeProblem,
)


def _make_test_problem(n_tickers: int = 6) -> SharpePortfolioProblem:
    """Create a test problem with specified number of tickers."""
    import numpy as np

    tickers = tuple(f"T{i:02d}" for i in range(n_tickers))

    # Generate positive returns
    np.random.seed(42)
    mean_returns = {t: 0.05 + 0.10 * np.random.random() for t in tickers}

    # Generate valid covariance matrix
    A = np.random.randn(n_tickers, n_tickers) * 0.1
    cov = A @ A.T + 0.01 * np.eye(n_tickers)
    covariance = tuple(tuple(float(cov[i, j]) for j in range(n_tickers)) for i in range(n_tickers))

    # Assign sectors
    sectors = {t: ["Tech", "Health", "Finance"][i % 3] for i, t in enumerate(tickers)}

    return SharpePortfolioProblem(
        tickers=tickers,
        mean_returns=mean_returns,
        covariance=covariance,
        sectors=sectors,
        upper_bounds={t: 1.0 for t in tickers},
        _covariance_validated=True,
    )


class TestAdapterGraphBuilding:
    """Tests for adapter graph building functionality."""

    def test_adapter_builds_valid_graph(self) -> None:
        """Adapter builds a valid reduction graph."""
        problem = _make_test_problem()
        policy = default_sharpe_graph_policy()
        adapter = SharpePortfolioAdapter(policy)

        graph = adapter.build_conflict_graph(problem)

        assert len(graph.node_ids) == problem.ticker_count
        assert all(w >= 0 for w in graph.node_weights.values())

    def test_graph_edges_respect_correlation_threshold(self) -> None:
        """Graph edges only connect tickers with high positive correlation."""
        problem = _make_test_problem()
        policy = SharpeGraphPolicy(
            policy_id="test",
            policy_version="1",
            correlation_threshold=0.95,  # Very high threshold
            edge_mode="correlation_only",
        )
        adapter = SharpePortfolioAdapter(policy)

        graph = adapter.build_conflict_graph(problem)

        # Check that any edges have correlation >= threshold
        for a, b in graph.edges:
            corr = problem.correlation(a, b)
            assert corr >= 0.95


class TestAdapterDomainValidation:
    """Tests for adapter candidate domain validation."""

    def test_valid_domain_accepted(self) -> None:
        """Valid candidate domain passes validation."""
        problem = _make_test_problem()
        policy = default_sharpe_graph_policy()
        adapter = SharpePortfolioAdapter(policy)

        result = adapter.validate_candidate_domain(problem, problem.tickers)

        assert result.is_valid

    def test_empty_domain_rejected(self) -> None:
        """Empty candidate domain is rejected."""
        problem = _make_test_problem()
        policy = default_sharpe_graph_policy()
        adapter = SharpePortfolioAdapter(policy)

        result = adapter.validate_candidate_domain(problem, ())

        assert not result.is_valid

    def test_unknown_ticker_rejected(self) -> None:
        """Unknown ticker in candidate domain is rejected."""
        problem = _make_test_problem()
        policy = default_sharpe_graph_policy()
        adapter = SharpePortfolioAdapter(policy)

        result = adapter.validate_candidate_domain(problem, ("T00", "UNKNOWN"))

        assert not result.is_valid
        assert "unknown" in str(result.failure_reasons).lower()


class TestAdapterFixingManifest:
    """Tests for adapter fixing manifest building."""

    def test_manifest_excludes_non_retained(self) -> None:
        """Fixing manifest excludes non-retained tickers."""
        problem = _make_test_problem(6)
        policy = default_sharpe_graph_policy()
        adapter = SharpePortfolioAdapter(policy)

        retained = problem.tickers[:3]
        manifest = adapter.build_fixing_manifest(problem, retained)

        assert set(manifest.retained_item_ids) == set(retained)
        assert set(manifest.excluded_item_ids) == set(problem.tickers[3:])

    def test_manifest_entries_fix_to_zero(self) -> None:
        """Manifest entries fix excluded variables to zero."""
        problem = _make_test_problem(4)
        policy = default_sharpe_graph_policy()
        adapter = SharpePortfolioAdapter(policy)

        retained = problem.tickers[:2]
        manifest = adapter.build_fixing_manifest(problem, retained)

        for entry in manifest.entries:
            for value in entry.variable_values.values():
                assert value == 0.0


class TestAdapterRestrictProblem:
    """Tests for adapter problem restriction."""

    def test_restrict_creates_transformed_problem(self) -> None:
        """restrict_problem creates a TransformedSharpeProblem."""
        problem = _make_test_problem(4)
        policy = default_sharpe_graph_policy()
        adapter = SharpePortfolioAdapter(policy)

        retained = problem.tickers[:2]
        manifest = adapter.build_fixing_manifest(problem, retained)
        restricted = adapter.restrict_problem(problem, retained, manifest)

        assert isinstance(restricted, TransformedSharpeProblem)
        assert restricted.retained_tickers == retained

    def test_restricted_problem_builds_classical_model(self) -> None:
        """Restricted problem can build a classical optimization model."""
        problem = _make_test_problem(4)
        policy = default_sharpe_graph_policy()
        adapter = SharpePortfolioAdapter(policy)

        retained = problem.tickers[:2]
        manifest = adapter.build_fixing_manifest(problem, retained)
        restricted = adapter.restrict_problem(problem, retained, manifest)

        model = restricted.build_classical_model()

        assert model.variables is not None
        assert model.linear_constraints is not None
        assert model.quadratic_objective is not None


class TestTransformedProblemModel:
    """Tests for TransformedSharpeProblem classical model."""

    def test_model_has_x_scale_variable(self) -> None:
        """Classical model includes x_scale variable."""
        problem = _make_test_problem(3)
        manifest = FixingManifest(
            retained_item_ids=problem.tickers,
            excluded_item_ids=(),
            entries=(),
            origin="test",
        )
        mapping = SharpeVariableMapping.for_problem(problem)
        transformed = TransformedSharpeProblem(
            original_problem=problem,
            retained_tickers=problem.tickers,
            fixing_manifest=manifest,
            variable_mapping=mapping,
        )

        model = transformed.build_classical_model()

        var_names = [v.name for v in model.variables]
        assert "x_scale" in var_names

    def test_model_has_return_normalization_constraint(self) -> None:
        """Classical model includes mu^T x_scaled = 1 constraint."""
        problem = _make_test_problem(3)
        manifest = FixingManifest(
            retained_item_ids=problem.tickers,
            excluded_item_ids=(),
            entries=(),
            origin="test",
        )
        mapping = SharpeVariableMapping.for_problem(problem)
        transformed = TransformedSharpeProblem(
            original_problem=problem,
            retained_tickers=problem.tickers,
            fixing_manifest=manifest,
            variable_mapping=mapping,
        )

        model = transformed.build_classical_model()

        constraint_names = [c.name for c in model.linear_constraints]
        assert "return_normalization" in constraint_names

    def test_model_has_budget_scale_link(self) -> None:
        """Classical model includes sum(x_scaled) = x_scale constraint."""
        problem = _make_test_problem(3)
        manifest = FixingManifest(
            retained_item_ids=problem.tickers,
            excluded_item_ids=(),
            entries=(),
            origin="test",
        )
        mapping = SharpeVariableMapping.for_problem(problem)
        transformed = TransformedSharpeProblem(
            original_problem=problem,
            retained_tickers=problem.tickers,
            fixing_manifest=manifest,
            variable_mapping=mapping,
        )

        model = transformed.build_classical_model()

        constraint_names = [c.name for c in model.linear_constraints]
        assert "budget_scale_link" in constraint_names


class TestCardinalityConstraint:
    """Tests for cardinality constraint handling."""

    def test_model_includes_cardinality_when_configured(self) -> None:
        """Classical model includes cardinality constraint when max_positions set."""
        problem = SharpePortfolioProblem(
            tickers=("A", "B", "C", "D"),
            mean_returns={"A": 0.10, "B": 0.12, "C": 0.08, "D": 0.15},
            covariance=(
                (0.04, 0.01, 0.005, 0.002),
                (0.01, 0.05, 0.01, 0.003),
                (0.005, 0.01, 0.03, 0.001),
                (0.002, 0.003, 0.001, 0.06),
            ),
            sectors={"A": "Tech", "B": "Health", "C": "Tech", "D": "Finance"},
            upper_bounds={"A": 0.5, "B": 0.5, "C": 0.5, "D": 0.5},
            max_positions=2,
            _covariance_validated=True,
        )
        manifest = FixingManifest(
            retained_item_ids=problem.tickers,
            excluded_item_ids=(),
            entries=(),
            origin="test",
        )
        mapping = SharpeVariableMapping.for_problem(problem)
        transformed = TransformedSharpeProblem(
            original_problem=problem,
            retained_tickers=problem.tickers,
            fixing_manifest=manifest,
            variable_mapping=mapping,
        )

        model = transformed.build_classical_model()

        # Should have delta variables
        var_names = [v.name for v in model.variables]
        assert any("delta__" in name for name in var_names)

        # Should have cardinality constraint
        constraint_names = [c.name for c in model.linear_constraints]
        assert "max_cardinality" in constraint_names


class TestSectorConstraints:
    """Tests for sector constraint handling."""

    def test_model_includes_sector_constraints(self) -> None:
        """Classical model includes sector constraints when configured."""
        problem = SharpePortfolioProblem(
            tickers=("A", "B", "C"),
            mean_returns={"A": 0.10, "B": 0.12, "C": 0.08},
            covariance=(
                (0.04, 0.01, 0.005),
                (0.01, 0.05, 0.01),
                (0.005, 0.01, 0.03),
            ),
            sectors={"A": "Tech", "B": "Health", "C": "Tech"},
            upper_bounds={"A": 1.0, "B": 1.0, "C": 1.0},
            sector_constraints=SectorConstraints(
                sector_min={"Tech": 0.20, "Health": 0.10},
                sector_max={"Tech": 0.60, "Health": 0.50},
            ),
            _covariance_validated=True,
        )
        manifest = FixingManifest(
            retained_item_ids=problem.tickers,
            excluded_item_ids=(),
            entries=(),
            origin="test",
        )
        mapping = SharpeVariableMapping.for_problem(problem)
        transformed = TransformedSharpeProblem(
            original_problem=problem,
            retained_tickers=problem.tickers,
            fixing_manifest=manifest,
            variable_mapping=mapping,
        )

        model = transformed.build_classical_model()

        constraint_names = [c.name for c in model.linear_constraints]
        assert any("sector_min__" in name for name in constraint_names)
        assert any("sector_max__" in name for name in constraint_names)


class TestLogicalVariableCounts:
    """Tests for logical variable counting."""

    def test_counts_include_binaries_without_cardinality(self) -> None:
        """Selection variables are present even without cardinality."""
        problem = _make_test_problem(4)
        policy = default_sharpe_graph_policy()
        adapter = SharpePortfolioAdapter(policy)

        counts = adapter.describe_logical_variables(problem)

        assert counts.binary_free == 4
        assert counts.integer_free == 0
        assert counts.continuous_free == 4 + 1  # x_scaled + x_scale

    def test_counts_include_binaries_with_cardinality(self) -> None:
        """With cardinality, binary delta variables are counted."""
        problem = SharpePortfolioProblem(
            tickers=("A", "B", "C"),
            mean_returns={"A": 0.10, "B": 0.12, "C": 0.08},
            covariance=(
                (0.04, 0.01, 0.005),
                (0.01, 0.05, 0.01),
                (0.005, 0.01, 0.03),
            ),
            sectors={"A": "Tech", "B": "Health", "C": "Tech"},
            upper_bounds={"A": 0.5, "B": 0.5, "C": 0.5},
            max_positions=2,
            _covariance_validated=True,
        )
        policy = default_sharpe_graph_policy()
        adapter = SharpePortfolioAdapter(policy)

        counts = adapter.describe_logical_variables(problem)

        assert counts.binary_free == 3  # One delta per ticker
        assert counts.continuous_free == 3 + 1  # x_scaled + x_scale
