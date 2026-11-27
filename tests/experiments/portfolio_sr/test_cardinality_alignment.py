"""Verify cardinality CLI and the compiled portfolio constraints."""

from dataclasses import replace

import pytest

from qreduce.config import validate_resolved_run_config
from qreduce.domains.contracts import FixingManifest
from qreduce.experiments.portfolio_sr.__main__ import (
    _build_parser,
    _build_reduction_policy,
    _validate_args,
)
from qreduce.experiments.portfolio_sr.execution import (
    _build_classical_solve_options,
    _build_mis_execution_options,
    _build_resolved_run_config,
    _validate_reduction_cardinality,
)
from qreduce.experiments.portfolio_sr.models import (
    SectorConstraints,
    SharpePortfolioProblem,
    SharpeVariableMapping,
    TransformedSharpeProblem,
)
from qreduce.solving.residual import (
    ClassicalSolveRequest,
    LinearConstraint,
    LinearConstraintSense,
    ScipClassicalBackend,
)


@pytest.mark.parametrize("flags", [
    ["--max-positions", "7"],
    ["--max-selected-assets", "7"],
    ["--max-positions", "7", "--max-selected-assets", "7"],
])
def test_alias_and_minimum_aware_default(flags):
    parser = _build_parser()
    args = parser.parse_args(["--run-id", "alignment", "--min-selected-assets", "7", *flags])
    _validate_args(parser, args)
    assert args.max_positions == 7
    policy = _build_reduction_policy(args, 10)
    assert (policy.candidate_domain_min_items, policy.candidate_domain_max_items) == (7, 7)
    assert policy.target_binary_variables == 3


@pytest.mark.parametrize("flags", [
    ["--max-selected-assets", "6", "--max-positions", "7"],
    ["--min-selected-assets", "7", "--max-selected-assets", "6"],
    ["--min-selected-assets", "7", "--candidate-domain-max-items", "6"],
])
def test_cli_rejects_conflicting_cardinality(flags):
    parser = _build_parser()
    with pytest.raises(SystemExit):
        _validate_args(parser, parser.parse_args(["--run-id", "alignment", *flags]))


def test_baseline_inactive_candidate_cap_does_not_conflict_with_minimum():
    parser = _build_parser()
    args = parser.parse_args([
        "--run-id", "alignment", "--max-reduction-rounds", "0",
        "--min-selected-assets", "7", "--candidate-domain-max-items", "2",
    ])
    _validate_args(parser, args)
    policy = _build_reduction_policy(args, 10)
    _validate_reduction_cardinality(policy, args.min_selected_assets)
    config = _build_resolved_run_config(
        "alignment", reduction_policy=policy, mis_solver_id="local_greedy",
        mis_execution=_build_mis_execution_options(), classical_solve=_build_classical_solve_options(),
    )
    assert validate_resolved_run_config(config).is_valid
    assert policy.candidate_domain_max_items == 2


def test_default_policy_enables_binary_target_without_cardinality():
    parser = _build_parser()
    args = parser.parse_args(["--run-id", "alignment"])
    _validate_args(parser, args)
    assert _build_reduction_policy(args, 10).target_binary_variables == 3


@pytest.mark.parametrize(("weights", "selections", "minimum", "maximum", "feasible"), [
    ((0.7, 0.3, 0.0), (1, 1, 0), 2, 2, True),
    ((0.8, 0.2, 0.0), (1, 1, 0), 2, 2, False),  # B below its minimum
    ((1.0, 0.0, 0.0), (1, 0, 0), 2, None, False),  # too few selections
    ((0.7, 0.3, 0.0), (1, 1, 1), None, 2, False),  # too many selections
    ((1.0, 0.0, 0.0), (1, 0, 1), 2, 2, True),  # zero-weight selection
    ((0.6, 0.3, 0.0), (1, 1, 0), None, None, False),  # budget short
    ((0.7, 0.3, 0.0), (0, 1, 1), None, None, False),  # positive weight unselected
    ((0.6, 0.4, 0.0), (1, 1, 0), None, None, False),  # only B's scaled cap is violated
])
def test_compiled_model_obeys_feasible_weights_and_selections(weights, selections, minimum, maximum, feasible):
    pytest.importorskip("pyscipopt")
    ids = ("A", "B", "C")
    returns = dict(zip(ids, (0.08, 0.12, 0.16), strict=True))
    covariance = ((0.1, 0., 0.), (0., 0.2, 0.), (0., 0., 0.3))
    floors = {"A": 0.2, "B": 0.25, "C": 0.0}
    caps = {"A": 1.0, "B": 0.35, "C": 0.0}
    sr = SharpePortfolioProblem(
        ids, returns, covariance, {"A": "one", "B": "other", "C": "other"}, caps,
        max_positions=maximum, min_selected_assets=minimum, lower_bounds=floors,
    )
    manifest = FixingManifest(retained_item_ids=ids, excluded_item_ids=(), entries=(), origin="test")
    sr_mapping = SharpeVariableMapping.for_problem(sr)
    scale = 1 / sum(weight * returns[t] for t, weight in zip(ids, weights, strict=True))
    deltas = {f"delta__{t}": float(d) for t, d in zip(ids, selections, strict=True)}
    sr_values = {**deltas, "x_scale": scale, **{
        f"x_scaled__{t}": w * scale for t, w in zip(ids, weights, strict=True)
    }}
    request = ClassicalSolveRequest(
        run_id="alignment", round_index=0, time_limit_seconds=10,
        remaining_end_to_end_seconds=10, configured_end_to_end_budget_seconds=10,
        mip_gap_tolerance=None, random_seed=0, threads=1, model_export_enabled=False,
        requested_solver_id="scip",
    )

    def solve_fixed(problem, values):
        class FixedModel:
            def build_classical_model(self):
                model = problem.build_classical_model()
                rows = tuple(LinearConstraint(f"test_fix__{name}", {name: 1.},
                                              LinearConstraintSense.EQUAL, value)
                             for name, value in values.items())
                return replace(model, linear_constraints=model.linear_constraints + rows)

        result = ScipClassicalBackend().solve(FixedModel(), request)
        return result.classical_solver_status.value

    expected = "optimal" if feasible else "infeasible"
    assert solve_fixed(TransformedSharpeProblem(sr, ids, manifest, sr_mapping), sr_values) == expected
    if weights[1] > caps["B"]:
        relaxed = replace(sr, upper_bounds={**caps, "B": 0.4})
        assert solve_fixed(TransformedSharpeProblem(relaxed, ids, manifest, sr_mapping), sr_values) == "optimal"
    if feasible:
        sector_limited = replace(sr, sector_constraints=SectorConstraints(
            {"one": 0.0, "other": 0.0}, {"one": 0.6, "other": 1.0},
        ))
        assert solve_fixed(TransformedSharpeProblem(sector_limited, ids, manifest, sr_mapping),
                           sr_values) == "infeasible"