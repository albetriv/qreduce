"""Core Sharpe portfolio selection and conditional floor regression tests."""

from dataclasses import replace

import pytest

from qreduce.artifacts.metadata import to_primitive
from qreduce.domains.contracts import FixingEntry, FixingManifest
from qreduce.experiments.portfolio_sr.adapter import SharpePortfolioAdapter
from qreduce.experiments.portfolio_sr.formulation import validate_cardinality_constraint
from qreduce.experiments.portfolio_sr.graph_policy import default_sharpe_graph_policy
from qreduce.experiments.portfolio_sr.models import (
    SectorConstraints,
    SharpePortfolioProblem,
    SharpeVariableMapping,
    TransformedSharpeProblem,
)
from qreduce.experiments.portfolio_sr.postcheck import (
    extract_solution_summary,
    validate_sharpe_solution,
)
from qreduce.models import ClassicalSolveOptions
from qreduce.solving.residual import ClassicalSolveResult, LinearConstraintSense
from qreduce.status import ClassicalSolverStatus, PostcheckMode


@pytest.fixture
def problem():
    return SharpePortfolioProblem(
        ("A", "B", "C"), {"A": 0.10, "B": 0.15, "C": 0.12},
        ((0.04, 0.0, 0.0), (0.0, 0.09, 0.0), (0.0, 0.0, 0.06)),
        {"A": "Tech", "B": "Health", "C": "Tech"}, {"A": 1.0, "B": 1.0, "C": 1.0},
    )


@pytest.mark.parametrize("values", [
    {"x_scaled__C": 0.0},
    {"delta__C": 0.0},
    {"x_scaled__C": 0.0, "delta__C": 1.0},
    {"x_scaled__C": 0.1, "delta__C": 0.0},
    {"x_scaled__C": 0.0, "delta__C": 0.0, "delta__A": 0.0},
])
def test_model_rejects_invalid_fixings(problem, values):
    retained = ("A", "B")
    manifest = FixingManifest(retained, ("C",), (FixingEntry("C", values, "test"),), "test")
    with pytest.raises(ValueError, match="Fixing for C must set exactly its scaled weight and selection binary to zero"):
        TransformedSharpeProblem(problem, retained, manifest, SharpeVariableMapping.for_problem(problem))


def test_model_requires_fixings_for_every_non_retained_ticker(problem):
    retained = ("A", "B")
    manifest = FixingManifest(retained, (), (), "test")
    with pytest.raises(ValueError, match="exclude exactly the non-retained tickers"):
        TransformedSharpeProblem(problem, retained, manifest, SharpeVariableMapping.for_problem(problem))


def test_constraint_count_matches_rows_without_building_objective(problem, monkeypatch):
    problem = replace(
        problem, lower_bounds={"A": 0.1}, min_selected_assets=1, max_positions=2,
        sector_constraints=SectorConstraints({"Tech": 0.2, "Health": 0.0}, {"Tech": 1.0, "Health": 0.8}),
    )
    retained = ("A", "B")
    adapter = SharpePortfolioAdapter(default_sharpe_graph_policy())
    manifest = adapter.build_fixing_manifest(problem, retained)
    transformed = TransformedSharpeProblem(problem, retained, manifest, SharpeVariableMapping.for_problem(problem))
    rows = transformed.build_classical_model().linear_constraints

    def unexpected_objective_term(*args, **kwargs):
        pytest.fail("Counting constraints must not build quadratic objective terms")

    monkeypatch.setattr("qreduce.experiments.portfolio_sr.models.QuadraticObjectiveTerm", unexpected_objective_term)
    assert len(rows) == transformed.constraint_count == transformed.to_dict()["constraint_count"]


def test_pure_minimum_counts_zero_weight_selection(problem):
    problem = replace(problem, min_selected_assets=2)
    adapter = SharpePortfolioAdapter(default_sharpe_graph_policy())
    retained = ("A", "B")
    manifest = adapter.build_fixing_manifest(problem, retained)
    mapping = SharpeVariableMapping.for_problem(problem)
    assert mapping.delta_by_ticker is not None
    assert manifest.entries[0].variable_values == {"x_scaled__C": 0.0, "delta__C": 0.0}
    transformed = TransformedSharpeProblem(problem, retained, manifest, mapping)
    assert adapter.describe_logical_variables(transformed).binary_free == 2
    rows = {row.name: row for row in transformed.build_classical_model().linear_constraints}
    assert rows["min_cardinality"].coefficients == dict.fromkeys(mapping.delta_by_ticker.values(), 1.0)
    assert rows["min_cardinality"].sense == LinearConstraintSense.GREATER_EQUAL
    assert rows["min_cardinality"].right_hand_side == 2
    assert "max_cardinality" not in rows
    assert not any(name.startswith("lower_bound__") for name in rows)

    weights = {"A": 1.0, "B": 0.0, "C": 0.0}
    deltas = {"A": 1.0, "B": 1.0, "C": 0.0}
    values = {"x_scale": 10.0, **{f"x_scaled__{t}": w * 10 for t, w in weights.items()},
              **{f"delta__{t}": d for t, d in deltas.items()}}
    options = ClassicalSolveOptions(
        classical_solver_id="scip", time_limit_seconds=10.0, mip_gap_tolerance=None,
        threads=None, model_export_enabled=False, primal_feasibility_tolerance=1e-6,
        integrality_tolerance=1e-6, objective_recomputation_absolute_tolerance=1e-6,
        objective_recomputation_relative_tolerance=1e-4, postcheck_mode=PostcheckMode.STRICT,
    )
    accepted = validate_sharpe_solution(transformed, values, manifest, options)
    assert accepted.postcheck_feasible
    assert validate_cardinality_constraint(problem, weights, deltas) == (True, None)
    assert not validate_cardinality_constraint(problem, weights)[0]
    summary = extract_solution_summary(problem, values)
    assert (summary["selected_count"], summary["position_count"]) == (2, 1)
    solver_result = ClassicalSolveResult(
        classical_solver_status=ClassicalSolverStatus.OPTIMAL, terminal_reason=None,
        solver_claimed_feasible=True, objective_value=accepted.objective_recomputed, best_bound=None,
        gap=None, is_optimal=True, is_time_limited=False, runtime_seconds=0.0, variable_values=values,
    )
    metrics = {metric.metric_id: metric.value for metric in
               adapter.evaluate_domain_metrics(transformed, solver_result, accepted)}
    assert (metrics["selected_count"], metrics["position_count"]) == (2, 1)

    too_few = validate_sharpe_solution(transformed, {**values, "delta__B": 0.0}, manifest, options)
    assert too_few.integrality_compliance and not too_few.original_constraint_compliance
    assert any(reason.startswith("min_cardinality_violation:") for reason in too_few.failure_reasons)
    invalid = validate_sharpe_solution(transformed, {**values, "delta__B": 0.7}, manifest, options)
    assert not invalid.integrality_compliance
    assert "selected_count" not in invalid.tolerances_used
    assert "selected_count" not in extract_solution_summary(problem, {**values, "delta__B": 0.7})
    rejected = adapter.validate_candidate_domain(problem, ("A",))
    assert not rejected.is_valid and rejected.minimum_required_items == 2


def test_floors_validate_and_normalize(problem):
    floors = {"A": 0.4}
    sparse = replace(problem, lower_bounds=floors)
    floors["A"] = 0.6
    assert sparse.has_selection_binaries
    assert sparse.effective_lower_bound("A") == 0.4
    assert sparse.effective_lower_bound("B") == 0.0
    for kwargs in ({"min_selected_assets": 0}, {"lower_bounds": {"B": 0.0}}, {"lower_bounds": {}}):
        normalized = replace(problem, **kwargs)
        assert normalized.has_selection_binaries
        assert to_primitive(normalized) == to_primitive(problem)
        assert normalized.to_dict() == problem.to_dict()
    with pytest.raises(ValueError, match="cannot be combined"):
        replace(problem, lower_bounds={}, lower_bound=0.4)
    with pytest.raises(ValueError, match="unknown tickers"):
        replace(problem, lower_bounds={"X": 0.4})
    with pytest.raises(ValueError, match="upper bound"):
        replace(problem, lower_bounds={"A": 0.4}, upper_bounds={"A": 0.3, "B": 1.0, "C": 1.0})
    with pytest.raises(ValueError, match="minimum_selection_floors_exceed_budget"):
        replace(problem, min_selected_assets=2, lower_bounds=dict.fromkeys(problem.tickers, 0.6))
    with pytest.raises(ValueError, match="cannot exceed max_positions"):
        replace(problem, min_selected_assets=3, max_positions=2)


def test_baseline_requires_selection_and_reports_count(problem):
    adapter = SharpePortfolioAdapter(default_sharpe_graph_policy())
    manifest = adapter.build_fixing_manifest(problem, problem.tickers)
    mapping = SharpeVariableMapping.for_problem(problem)
    transformed = TransformedSharpeProblem(problem, problem.tickers, manifest, mapping)
    model = transformed.build_classical_model()
    assert transformed.variable_count == len(model.variables) == 7
    assert transformed.constraint_count == len(model.linear_constraints)
    assert all(f"cardinality_link__{t}" in {r.name for r in model.linear_constraints}
               for t in problem.tickers)
    values = {"x_scale": 10.0, "x_scaled__A": 10.0, "x_scaled__B": 0.0,
              "x_scaled__C": 0.0, "delta__A": 1.0, "delta__B": 1.0, "delta__C": 0.0}
    options = ClassicalSolveOptions(
        classical_solver_id="scip", time_limit_seconds=10.0, mip_gap_tolerance=None,
        threads=None, model_export_enabled=False, primal_feasibility_tolerance=1e-6,
        integrality_tolerance=1e-6, objective_recomputation_absolute_tolerance=1e-6,
        objective_recomputation_relative_tolerance=1e-4, postcheck_mode=PostcheckMode.STRICT,
    )
    result = validate_sharpe_solution(transformed, values, manifest, options)
    assert result.postcheck_feasible
    assert result.tolerances_used["selected_count"] == 2
    assert extract_solution_summary(problem, values)["selected_count"] == 2
    assert not validate_sharpe_solution(transformed, {k: v for k, v in values.items()
                                       if k != "delta__B"}, manifest, options).postcheck_feasible
    assert not validate_sharpe_solution(transformed, {**values, "delta__A": 0.0},
                                       manifest, options).postcheck_feasible
    assert not validate_cardinality_constraint(problem, {"A": 1.0}, {"A": 1.0})[0]