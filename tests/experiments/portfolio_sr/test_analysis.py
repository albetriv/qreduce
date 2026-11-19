"""Validate artifact reconstruction without publishing misleading partial weights."""

from copy import deepcopy
from pathlib import Path

import pytest

from qreduce.experiments.artifacts import ExperimentRunArtifacts
from qreduce.experiments.portfolio_sr.analysis import (
    extract_portfolio_weights,
    extract_sector_exposures,
)


def _artifacts(*, transformed=False):
    problem = {"tickers": ["A", "B"], "sectors": {"A": "Tech", "B": "Health"}}
    if transformed:
        problem = {"original_problem": problem, "retained_tickers": ["A"]}
    result = {
        "run_result": {"run_status": "success", "adoption_status": "adopted"},
        "postcheck_result": {"postcheck_feasible": True},
        "classical_result": {"variable_values": {
            "x_scale": 10., "x_scaled__A": 10., "x_scaled__B": 0.,
        }},
    }
    return ExperimentRunArtifacts(Path("/not-written"), {}, {}, {}, problem, result, None)


@pytest.mark.parametrize("transformed", [False, True])
def test_original_and_transformed_use_same_reconstruction(transformed):
    artifacts = _artifacts(transformed=transformed)
    assert extract_portfolio_weights(artifacts) == {"A": 1.}
    assert extract_portfolio_weights(artifacts, weight_tolerance=0) == {"A": 1., "B": 0.}
    assert extract_sector_exposures(artifacts) == {"Tech": 1., "Health": 0.}


@pytest.mark.parametrize("variable,value", [
    ("x_scale", float("nan")), ("x_scale", float("inf")), ("x_scale", 0.),
    ("x_scaled__B", float("nan")), ("x_scaled__A", float("inf")),
    ("x_scaled__B", None), ("x_scale", True),
])
def test_invalid_or_missing_values_do_not_produce_partial_distributions(variable, value):
    artifacts = _artifacts()
    values = artifacts.result["classical_result"]["variable_values"]
    if value is None:
        del values[variable]
    else:
        values[variable] = value
    assert extract_portfolio_weights(artifacts) == {}
    assert extract_sector_exposures(artifacts) == {}


@pytest.mark.parametrize("section,field,value", [
    ("run_result", "run_status", "failed"),
    ("run_result", "adoption_status", "not_adopted"),
    ("postcheck_result", "postcheck_feasible", False),
])
def test_diagnostic_solutions_are_not_presented_as_portfolios(section, field, value):
    artifacts = deepcopy(_artifacts())
    artifacts.result[section][field] = value
    assert extract_portfolio_weights(artifacts) == {}
    assert extract_sector_exposures(artifacts) == {}


@pytest.mark.parametrize("tolerance", [-1., float("nan"), float("inf")])
def test_invalid_display_threshold_rejected(tolerance):
    with pytest.raises(ValueError, match="weight_tolerance"):
        extract_portfolio_weights(_artifacts(), weight_tolerance=tolerance)