"""Tests for UIX investment bounds and cardinality parameters.

These tests verify that the new portfolio parameters (lowerBound, upperBound,
minSelectedAssets, maxSelectedAssets) are correctly:
1. Generated in CLI commands
2. Validated (including equal bounds and exact cardinality)
3. Reset to defaults
4. Documented with tooltips
"""

import json
import shlex
import subprocess
from pathlib import Path

import pytest

from qreduce.experiments.portfolio_mv.__main__ import (
    _build_parser as build_portfolio_parser,
)


def run_js_generator(configurator: str, field_values: dict) -> dict:
    """Run the JavaScript command generator and return the result.

    Args:
        configurator: "portfolio" or "facility_location"
        field_values: Dict of field IDs to values to set

    Returns:
        Dict with keys: isValid, errors, command

    Raises:
        pytest.skip: If Node.js or jsdom is not available
    """
    runner_path = Path(__file__).parent / "uix_js_runner.js"
    if not runner_path.exists():
        pytest.skip("uix_js_runner.js not found")

    # Check if node is available
    try:
        subprocess.run(
            ["node", "--version"],
            capture_output=True,
            timeout=5,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        pytest.skip("Node.js not available")

    result = subprocess.run(
        ["node", str(runner_path), configurator, json.dumps(field_values)],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    if result.returncode != 0:
        if "Cannot find module" in result.stderr and "jsdom" in result.stderr:
            pytest.skip("jsdom not installed (run: npm install)")
        pytest.fail(f"JS runner failed: {result.stderr}")

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        pytest.fail(f"Invalid JSON output: {result.stdout}")


def extract_cli_args(command: str) -> list[str]:
    """Extract CLI arguments from a poetry run command."""
    command = command.replace("\\\n", " ")
    command = " ".join(command.split())
    command = command.removeprefix("poetry run python -m ")
    parts = shlex.split(command)
    if parts and "." in parts[0]:
        parts = parts[1:]
    return parts


@pytest.fixture
def portfolio_parser():
    """Return the portfolio CLI parser."""
    return build_portfolio_parser()


class TestInvestmentBoundsCLIGeneration:
    """Test CLI generation for investment bounds."""

    def test_lower_bound_included_when_changed(self):
        """Test that lower-bound is included when different from default (0.0)."""
        result = run_js_generator(
            "portfolio",
            {"runId": "test001", "lowerBound": "0.05"},
        )
        assert result["isValid"] is True
        assert "--lower-bound 0.05" in result["command"]

    def test_lower_bound_omitted_when_default(self):
        """Test that lower-bound is omitted when at default (0.0)."""
        result = run_js_generator(
            "portfolio",
            {"runId": "test001", "lowerBound": "0.0"},
        )
        assert result["isValid"] is True
        assert "--lower-bound" not in result["command"]

    def test_upper_bound_included_when_changed(self):
        """Test that upper-bound is included when different from default (0.7)."""
        result = run_js_generator(
            "portfolio",
            {"runId": "test001", "upperBound": "0.25"},
        )
        assert result["isValid"] is True
        assert "--upper-bound 0.25" in result["command"]

    def test_upper_bound_omitted_when_default(self):
        """Test that upper-bound is omitted when at default (0.7)."""
        result = run_js_generator(
            "portfolio",
            {"runId": "test001", "upperBound": "0.7"},
        )
        assert result["isValid"] is True
        assert "--upper-bound" not in result["command"]

    def test_both_bounds_included(self):
        """Test that both bounds are included when both changed."""
        result = run_js_generator(
            "portfolio",
            {"runId": "test001", "lowerBound": "0.05", "upperBound": "0.25"},
        )
        assert result["isValid"] is True
        assert "--lower-bound 0.05" in result["command"]
        assert "--upper-bound 0.25" in result["command"]


class TestCardinalityCLIGeneration:
    """Test CLI generation for cardinality constraints."""

    def test_min_selected_assets_included(self):
        """Test that min-selected-assets is included when set."""
        result = run_js_generator(
            "portfolio",
            {"runId": "test001", "minSelectedAssets": "5"},
        )
        assert result["isValid"] is True
        assert "--min-selected-assets 5" in result["command"]

    def test_max_selected_assets_included(self):
        """Test that max-selected-assets is included when set."""
        result = run_js_generator(
            "portfolio",
            {"runId": "test001", "maxSelectedAssets": "15"},
        )
        assert result["isValid"] is True
        assert "--max-selected-assets 15" in result["command"]

    def test_both_cardinality_constraints_included(self):
        """Test that both cardinality constraints are included when set."""
        result = run_js_generator(
            "portfolio",
            {"runId": "test001", "minSelectedAssets": "5", "maxSelectedAssets": "15"},
        )
        assert result["isValid"] is True
        assert "--min-selected-assets 5" in result["command"]
        assert "--max-selected-assets 15" in result["command"]

    def test_cardinality_omitted_when_empty(self):
        """Test that cardinality options are omitted when not set."""
        result = run_js_generator(
            "portfolio",
            {"runId": "test001"},
        )
        assert result["isValid"] is True
        assert "--min-selected-assets" not in result["command"]
        assert "--max-selected-assets" not in result["command"]


class TestEqualBoundsValidation:
    """Test that equal bounds (fixed investment) are accepted."""

    def test_equal_bounds_accepted(self):
        """Test that lower_bound == upper_bound is valid."""
        result = run_js_generator(
            "portfolio",
            {"runId": "test001", "lowerBound": "0.10", "upperBound": "0.10"},
        )
        assert result["isValid"] is True
        assert "--lower-bound 0.1" in result["command"]
        assert "--upper-bound 0.1" in result["command"]

    def test_equal_bounds_parses(self, portfolio_parser):
        """Test that equal bounds are accepted by Python parser."""
        result = run_js_generator(
            "portfolio",
            {"runId": "test001", "lowerBound": "0.10", "upperBound": "0.10"},
        )
        assert result["isValid"] is True
        args = extract_cli_args(result["command"])
        parsed = portfolio_parser.parse_args(args)
        assert parsed.lower_bound == 0.10
        assert parsed.upper_bound == 0.10


class TestExactCardinalityValidation:
    """Test that exact cardinality (min == max) is accepted."""

    def test_exact_cardinality_accepted(self):
        """Test that min_selected == max_selected is valid."""
        result = run_js_generator(
            "portfolio",
            {"runId": "test001", "minSelectedAssets": "10", "maxSelectedAssets": "10"},
        )
        assert result["isValid"] is True
        assert "--min-selected-assets 10" in result["command"]
        assert "--max-selected-assets 10" in result["command"]

    def test_exact_cardinality_parses(self, portfolio_parser):
        """Test that exact cardinality is accepted by Python parser."""
        result = run_js_generator(
            "portfolio",
            {"runId": "test001", "minSelectedAssets": "10", "maxSelectedAssets": "10"},
        )
        assert result["isValid"] is True
        args = extract_cli_args(result["command"])
        parsed = portfolio_parser.parse_args(args)
        assert parsed.min_selected_assets == 10
        assert parsed.max_selected_assets == 10


class TestInvalidBoundsValidation:
    """Test that invalid bounds are rejected."""

    def test_upper_less_than_lower_rejected(self):
        """Test that upper < lower is rejected."""
        result = run_js_generator(
            "portfolio",
            {"runId": "test001", "lowerBound": "0.30", "upperBound": "0.20"},
        )
        assert result["isValid"] is False

    def test_negative_lower_bound_rejected(self):
        """Test that negative lower bound is rejected."""
        result = run_js_generator(
            "portfolio",
            {"runId": "test001", "lowerBound": "-0.1"},
        )
        assert result["isValid"] is False

    def test_zero_upper_bound_rejected(self):
        """Test that upper bound = 0 is rejected."""
        result = run_js_generator(
            "portfolio",
            {"runId": "test001", "upperBound": "0"},
        )
        assert result["isValid"] is False

    def test_non_integer_cardinality_rejected(self):
        """Test that float cardinality is rejected."""
        result = run_js_generator(
            "portfolio",
            {"runId": "test001", "minSelectedAssets": "5.5"},
        )
        assert result["isValid"] is False

    def test_min_greater_than_max_cardinality_rejected(self):
        """Test that min > max cardinality is rejected."""
        result = run_js_generator(
            "portfolio",
            {"runId": "test001", "minSelectedAssets": "15", "maxSelectedAssets": "5"},
        )
        assert result["isValid"] is False

    def test_cardinality_exceeds_asset_count_rejected(self):
        """Test that cardinality > asset_count is rejected."""
        result = run_js_generator(
            "portfolio",
            {"runId": "test001", "assetCount": "10", "minSelectedAssets": "15"},
        )
        assert result["isValid"] is False


class TestCombinedParametersParsing:
    """Test that combined parameters parse correctly in Python."""

    def test_full_config_with_bounds_and_cardinality(self, portfolio_parser):
        """Test full config with all new parameters."""
        result = run_js_generator(
            "portfolio",
            {
                "runId": "full_bounds_test",
                "assetCount": "100",
                "lowerBound": "0.05",
                "upperBound": "0.25",
                "minSelectedAssets": "5",
                "maxSelectedAssets": "15",
            },
        )
        assert result["isValid"] is True
        args = extract_cli_args(result["command"])
        parsed = portfolio_parser.parse_args(args)

        assert parsed.run_id == "full_bounds_test"
        assert parsed.asset_count == 100
        assert parsed.lower_bound == 0.05
        assert parsed.upper_bound == 0.25
        assert parsed.min_selected_assets == 5
        assert parsed.max_selected_assets == 15

    def test_fixed_allocation_portfolio(self, portfolio_parser):
        """Test exact cardinality with fixed investment per asset."""
        result = run_js_generator(
            "portfolio",
            {
                "runId": "fixed_allocation",
                "assetCount": "50",
                "lowerBound": "0.10",
                "upperBound": "0.10",
                "minSelectedAssets": "10",
                "maxSelectedAssets": "10",
            },
        )
        assert result["isValid"] is True
        args = extract_cli_args(result["command"])
        parsed = portfolio_parser.parse_args(args)

        # Fixed investment: all 10 assets get exactly 10% each
        assert parsed.lower_bound == 0.10
        assert parsed.upper_bound == 0.10
        assert parsed.min_selected_assets == 10
        assert parsed.max_selected_assets == 10


class TestResetDefaults:
    """Test that reset button restores default values for new parameters."""

    def test_reset_restores_default_lower_bound(self):
        """Test that reset button restores lowerBound to 0.0."""
        # Set non-default value, then click reset
        result = run_js_generator(
            "portfolio",
            {
                "runId": "test001",
                "lowerBound": "0.15",  # Non-default
                "_action": "reset",
            },
        )
        # After reset, lowerBound should be 0.0
        assert result["currentValues"]["lowerBound"] == "0.0"

    def test_reset_restores_default_upper_bound(self):
        """Test that reset button restores upperBound to 0.7."""
        result = run_js_generator(
            "portfolio",
            {
                "runId": "test001",
                "upperBound": "0.25",  # Non-default
                "_action": "reset",
            },
        )
        # After reset, upperBound should be 0.7
        assert result["currentValues"]["upperBound"] == "0.7"

    def test_reset_clears_cardinality(self):
        """Test that reset button clears cardinality (defaults are empty)."""
        result = run_js_generator(
            "portfolio",
            {
                "runId": "test001",
                "minSelectedAssets": "5",  # Non-default
                "maxSelectedAssets": "15",  # Non-default
                "_action": "reset",
            },
        )
        # After reset, cardinality fields should be empty
        assert result["currentValues"]["minSelectedAssets"] == ""
        assert result["currentValues"]["maxSelectedAssets"] == ""

    def test_reset_updates_command_preview(self):
        """Test that reset updates the CLI command preview."""
        # Set non-default values, then reset
        result = run_js_generator(
            "portfolio",
            {
                "runId": "test001",
                "lowerBound": "0.10",
                "upperBound": "0.30",
                "minSelectedAssets": "5",
                "_action": "reset",
            },
        )
        # After reset, command should not include the non-default values
        assert "--lower-bound" not in result["command"]
        assert "--upper-bound" not in result["command"]
        assert "--min-selected-assets" not in result["command"]

    def test_reset_clears_validation_errors(self):
        """Test that reset clears validation errors."""
        # Set invalid value (upper < lower), then reset
        result = run_js_generator(
            "portfolio",
            {
                "runId": "test001",
                "lowerBound": "0.50",
                "upperBound": "0.20",  # Invalid: less than lower
                "_action": "reset",
            },
        )
        # After reset, should be valid
        assert result["isValid"] is True
        assert not result["errors"]

    def test_reset_restores_all_four_new_fields(self):
        """Test that reset restores all four new fields in one operation."""
        result = run_js_generator(
            "portfolio",
            {
                "runId": "test001",
                "lowerBound": "0.05",
                "upperBound": "0.25",
                "minSelectedAssets": "3",
                "maxSelectedAssets": "12",
                "_action": "reset",
            },
        )
        # All four fields should be at defaults
        assert result["currentValues"]["lowerBound"] == "0.0"
        assert result["currentValues"]["upperBound"] == "0.7"
        assert result["currentValues"]["minSelectedAssets"] == ""
        assert result["currentValues"]["maxSelectedAssets"] == ""


class TestTooltipPresence:
    """Test that new parameters have tooltips."""

    @pytest.fixture
    def portfolio_html(self) -> str:
        """Load portfolio HTML content."""
        html_path = Path(__file__).parent.parent / "uix" / "experiment_portfolio_mv.html"
        return html_path.read_text()

    def test_lower_bound_has_tooltip(self, portfolio_html: str) -> None:
        """Test that lowerBound field has PARAM_DESC comment."""
        assert "PARAM_DESC:" in portfolio_html
        # The PARAM_DESC for lowerBound should exist
        assert 'id="lowerBound"' in portfolio_html

    def test_upper_bound_has_tooltip(self, portfolio_html: str) -> None:
        """Test that upperBound field has PARAM_DESC comment."""
        assert 'id="upperBound"' in portfolio_html

    def test_min_selected_assets_has_tooltip(self, portfolio_html: str) -> None:
        """Test that minSelectedAssets field has PARAM_DESC comment."""
        assert 'id="minSelectedAssets"' in portfolio_html

    def test_max_selected_assets_has_tooltip(self, portfolio_html: str) -> None:
        """Test that maxSelectedAssets field has PARAM_DESC comment."""
        assert 'id="maxSelectedAssets"' in portfolio_html


class TestBoundsWithReductionModes:
    """Test that bounds work correctly in both baseline and reduction modes."""

    def test_bounds_included_in_baseline_mode(self):
        """Test that bounds are included even in baseline mode (rounds=0)."""
        result = run_js_generator(
            "portfolio",
            {
                "runId": "baseline_bounds",
                "maxRounds": "0",
                "lowerBound": "0.05",
                "upperBound": "0.25",
            },
        )
        assert result["isValid"] is True
        assert "--max-reduction-rounds 0" in result["command"]
        assert "--lower-bound 0.05" in result["command"]
        assert "--upper-bound 0.25" in result["command"]

    def test_cardinality_included_in_baseline_mode(self):
        """Test that cardinality constraints are included in baseline mode."""
        result = run_js_generator(
            "portfolio",
            {
                "runId": "baseline_cardinality",
                "maxRounds": "0",
                "minSelectedAssets": "5",
                "maxSelectedAssets": "15",
            },
        )
        assert result["isValid"] is True
        assert "--max-reduction-rounds 0" in result["command"]
        assert "--min-selected-assets 5" in result["command"]
        assert "--max-selected-assets 15" in result["command"]

    def test_bounds_included_in_reduction_mode(self):
        """Test that bounds are included in reduction mode."""
        result = run_js_generator(
            "portfolio",
            {
                "runId": "reduction_bounds",
                "maxRounds": "2",
                "lowerBound": "0.05",
                "upperBound": "0.25",
            },
        )
        assert result["isValid"] is True
        assert "--max-reduction-rounds 2" in result["command"]
        assert "--lower-bound 0.05" in result["command"]
        assert "--upper-bound 0.25" in result["command"]
