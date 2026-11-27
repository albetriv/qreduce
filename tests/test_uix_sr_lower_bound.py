"""Exercise the SR minimum-investment controls in the real UI."""

import pytest
from test_uix_js_execution import run_js_generator


def test_minimum_and_target_for_reduction_and_baseline():
    fields = {"runId": "test", "lowerBound": "0.05", "targetBinary": "2"}
    reduced = run_js_generator("portfolio_sr", {**fields, "maxRounds": "1"})
    assert reduced["isValid"]
    assert "--lower-bound 0.05" in reduced["command"]
    assert "--target-binary-variables 2" in reduced["command"]
    baseline = run_js_generator("portfolio_sr", {**fields, "maxRounds": "0"})
    assert baseline["isValid"]
    assert "--lower-bound 0.05" in baseline["command"]
    assert "--target-binary-variables" not in baseline["command"]


def test_minimum_validation_default_and_reset():
    for value in ("-0.1", "1.1", ""):
        result = run_js_generator("portfolio_sr", {"runId": "test", "lowerBound": value})
        assert not result["isValid"]
        assert "lowerBound" in result["errors"]
    result = run_js_generator("portfolio_sr", {"runId": "test", "lowerBound": "0.6", "upperBound": "0.5"})
    assert not result["isValid"]
    default = run_js_generator("portfolio_sr", {"runId": "test", "targetBinary": "2"})
    assert "--lower-bound" not in default["command"]
    assert "--target-binary-variables 2" in default["command"]
    reset = run_js_generator("portfolio_sr", {"lowerBound": "0.2", "_action": "reset"})
    assert float(reset["currentValues"]["lowerBound"]) == 0


@pytest.mark.parametrize("minimum, maximum", [("2", ""), ("", "3"), ("2", "3"), ("0", "")])
@pytest.mark.parametrize("rounds", ["0", "1"])
def test_sr_cardinality_flags_and_binary_target(minimum, maximum, rounds):
    result = run_js_generator("portfolio_sr", {
        "runId": "test", "minSelectedAssets": minimum, "maxPositions": maximum,
        "targetBinary": "2", "maxRounds": rounds,
    })
    assert result["isValid"]
    command = result["command"]
    assert "--max-positions" not in command
    assert ("--min-selected-assets 2" in command) == (minimum == "2")
    assert ("--max-selected-assets 3" in command) == bool(maximum)
    assert ("--target-binary-variables 2" in command) == (rounds == "1")


@pytest.mark.parametrize("fields, error", [
    ({"minSelectedAssets": "-1"}, "minSelectedAssets"),
    ({"minSelectedAssets": "1.5"}, "minSelectedAssets"),
    ({"minSelectedAssets": "4", "assetCount": "3"}, "minSelectedAssets"),
    ({"minSelectedAssets": "3", "maxPositions": "2"}, "minSelectedAssets"),
    ({"maxPositions": "0"}, "maxPositions"),
    ({"maxPositions": "3", "selectionMode": "explicit", "explicitTickers": "A,B"}, "maxPositions"),
])
def test_sr_invalid_cardinality(fields, error):
    result = run_js_generator("portfolio_sr", {"runId": "test", **fields})
    assert not result["isValid"]
    assert error in result["errors"]


def test_sr_reset_cardinality():
    result = run_js_generator("portfolio_sr", {
        "minSelectedAssets": "2", "maxPositions": "3", "_action": "reset",
    })
    assert result["currentValues"]["minSelectedAssets"] == ""
    assert result["currentValues"]["maxPositions"] == ""


def test_sr_candidate_cap_must_allow_the_selection_minimum_when_reducing():
    fields = {"runId": "test", "minSelectedAssets": "3", "maxItems": "2"}
    reduced = run_js_generator("portfolio_sr", {**fields, "maxRounds": "1"})
    assert not reduced["isValid"]
    assert "maxItems" in reduced["errors"]
    baseline = run_js_generator("portfolio_sr", {**fields, "maxRounds": "0"})
    assert baseline["isValid"]
    assert "--min-selected-assets 3" in baseline["command"]
    assert "--candidate-domain-max-items" not in baseline["command"]