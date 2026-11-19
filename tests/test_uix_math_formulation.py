"""Tests for UIX mathematical formulation panel integration.

These tests verify that:
1. Math formulation panels are properly initialized
2. TeX source is preserved for static elements (not dynamic ones)
3. Formulas are restored correctly after clearing
4. Cardinality constraints survive debounce and render cycle
5. Multiple cardinality updates work correctly
6. Values are updated when form fields change
7. Reduction mode display updates based on rounds
8. Reset restores the math panel to default state
9. Fallback behavior when MathJax fails to load
10. Render serialization prevents DOM modifications during active render
11. Number formatting preserves precision
12. No HTML tags inside TeX delimiters
"""

import json
import subprocess
from pathlib import Path

import pytest


def run_math_test(configurator: str, test_type: str, field_values: dict | None = None) -> dict:
    """Run the math formulation test runner and return the result.

    Args:
        configurator: "portfolio" or "facility_location"
        test_type: Test type to run
        field_values: Optional dict of field values to set

    Returns:
        Dict with test results

    Raises:
        pytest.skip: If Node.js or jsdom is not available
    """
    runner_path = Path(__file__).parent / "uix_math_runner.js"
    if not runner_path.exists():
        pytest.skip("uix_math_runner.js not found")

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

    args = ["node", str(runner_path), configurator, test_type]
    if field_values:
        args.append(json.dumps(field_values))

    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=60,  # Increased for async tests with slow renderer
        check=False,
    )

    if result.returncode != 0:
        if "Cannot find module" in result.stderr and "jsdom" in result.stderr:
            pytest.skip("jsdom not installed (run: npm install)")
        pytest.fail(f"Math runner failed: {result.stderr}")

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        pytest.fail(f"Invalid JSON output: {result.stdout}")


@pytest.mark.parametrize("fallback", [False, True])
@pytest.mark.parametrize("rounds", ["0", "1"])
def test_risk_aversion_math_panel_and_reset(fallback, rounds):
    result = run_math_test("portfolio", "risk_aversion", {
        "riskAversion": "2.5", "maxRounds": rounds, "_fallback": fallback,
    })
    assert result["success"]
    assert float(result["displayed"]) == 2.5
    assert "\\lambda" in result["latex"]
    assert "λ" in result["fallback"]
    assert result["disabled"] is False
    assert float(result["afterReset"]) == 1.0
    assert float(result["fieldAfterReset"]) == 1.0


class TestMathPanelInitialization:
    """Test that math formulation panels are properly initialized."""

    def test_portfolio_panel_exists(self):
        """Test that portfolio has a math formulation panel."""
        result = run_math_test("portfolio", "init")
        assert result["success"] is True
        assert result["hasMathPanel"] is True
        assert result["hasMathContent"] is True
        assert result["hasReductionSection"] is True

    def test_facility_location_panel_exists(self):
        """Test that facility location has a math formulation panel."""
        result = run_math_test("facility_location", "init")
        assert result["success"] is True
        assert result["hasMathPanel"] is True
        assert result["hasMathContent"] is True
        assert result["hasReductionSection"] is True


class TestTexSourcePreservation:
    """Test that TeX source is preserved for static elements only."""

    def test_portfolio_static_tex_preserved(self):
        """Test that portfolio static TeX is saved, dynamic is not."""
        result = run_math_test("portfolio", "tex_preservation")
        assert result["success"] is True
        assert result["staticElements"] > 0
        assert result["allStaticPreserved"] is True
        # Dynamic elements should not be preserved
        assert result["dynamicElements"] > 0

    def test_facility_location_static_tex_preserved(self):
        """Test that facility location static TeX is saved."""
        result = run_math_test("facility_location", "tex_preservation")
        assert result["success"] is True
        assert result["staticElements"] > 0
        assert result["allStaticPreserved"] is True

    def test_preserved_source_contains_tex(self):
        """Test that preserved source contains actual TeX content."""
        result = run_math_test("portfolio", "tex_preservation")
        assert result["success"] is True
        if result["sampleSource"]:
            has_tex_content = "\\" in result["sampleSource"]
            assert has_tex_content, f"Sample source doesn't look like TeX: {result['sampleSource']}"


class TestFormulaRestoration:
    """Test that static formulas are restored after clearing MathJax output."""

    def test_portfolio_static_formulas_restored_after_clear(self):
        """Test that portfolio static formulas are restored after clearTypeset."""
        result = run_math_test("portfolio", "formula_restoration")
        assert result["success"] is True
        assert result["contentRestored"] is True, (
            f"Content not restored. Original: {result['originalContent']}, "
            f"Restored: {result['restoredContent']}"
        )
        assert result["noMjxContainer"] is True

    def test_facility_location_formulas_restored_after_clear(self):
        """Test that facility location formulas are restored after clearTypeset."""
        result = run_math_test("facility_location", "formula_restoration")
        assert result["success"] is True
        assert result["contentRestored"] is True


class TestCardinalitySurvivesDebounce:
    """Test that cardinality constraints survive the debounce and render cycle.
    
    This is the key test for the bug where cardinality was erased after debounce.
    """

    def test_min_cardinality_survives_debounce(self):
        """Test that min cardinality survives debounce and render."""
        result = run_math_test(
            "portfolio",
            "cardinality_survives",
            {"minSelectedAssets": "3", "maxSelectedAssets": ""},
        )
        assert result["success"] is True
        assert result["contentSurvived"] is True, (
            f"Cardinality erased after debounce. "
            f"Before: {result['contentBeforeDebounce']}, "
            f"After: {result['contentAfterDebounce']}"
        )
        assert result["hasMinConstraint"] is True

    def test_max_cardinality_survives_debounce(self):
        """Test that max cardinality survives debounce and render."""
        result = run_math_test(
            "portfolio",
            "cardinality_survives",
            {"minSelectedAssets": "", "maxSelectedAssets": "10"},
        )
        assert result["success"] is True
        assert result["contentSurvived"] is True
        assert result["hasMaxConstraint"] is True

    def test_both_cardinality_survive_debounce(self):
        """Test that both min and max cardinality survive debounce."""
        result = run_math_test(
            "portfolio",
            "cardinality_survives",
            {"minSelectedAssets": "5", "maxSelectedAssets": "15"},
        )
        assert result["success"] is True
        assert result["contentSurvived"] is True
        assert result["hasMinConstraint"] is True
        assert result["hasMaxConstraint"] is True


class TestMultipleCardinalityUpdates:
    """Test that multiple cardinality updates work correctly."""

    def test_sequential_cardinality_updates(self):
        """Test that multiple sequential cardinality updates are preserved."""
        result = run_math_test("portfolio", "cardinality_updates")
        assert result["success"] is True
        assert result["allUpdatesPreserved"] is True, (
            f"Some updates lost content: {result['results']}"
        )
        # Verify each step has content
        for step_result in result["results"]:
            assert step_result["hasContent"] is True, (
                f"Step {step_result['step']} lost content"
            )


class TestPortfolioValueUpdates:
    """Test that portfolio math panel updates with form values."""

    def test_asset_count_displayed(self):
        """Test that asset count is displayed in math panel."""
        result = run_math_test("portfolio", "update_values", {"assetCount": "25"})
        assert result["success"] is True
        assert result["displayedAssetCount"] == "25"

    def test_investment_bounds_displayed(self):
        """Test that investment bounds are displayed correctly."""
        result = run_math_test(
            "portfolio",
            "update_values",
            {"lowerBound": "0.05", "upperBound": "0.4"},
        )
        assert result["success"] is True
        assert result["displayedLowerBound"] == "0.05"
        assert result["displayedUpperBound"] == "0.4"

    def test_default_values_displayed(self):
        """Test that default values are displayed after initialization."""
        result = run_math_test("portfolio", "update_values", {})
        assert result["success"] is True
        assert result["displayedAssetCount"] == "30"


class TestPortfolioCardinality:
    """Test cardinality constraint display in portfolio (immediate state)."""

    def test_cardinality_hidden_when_empty(self):
        """Test that cardinality block is hidden when no constraints set."""
        result = run_math_test(
            "portfolio",
            "cardinality",
            {"minSelectedAssets": "", "maxSelectedAssets": ""},
        )
        assert result["success"] is True
        assert result["cardinalityBlockVisible"] is False

    def test_cardinality_shown_with_min_only(self):
        """Test that cardinality is shown with only min constraint."""
        result = run_math_test(
            "portfolio",
            "cardinality",
            {"minSelectedAssets": "5", "maxSelectedAssets": ""},
        )
        assert result["success"] is True
        assert result["cardinalityBlockVisible"] is True
        assert result["minSelectedRowVisible"] is True
        assert result["maxSelectedRowVisible"] is False
        assert "\\geq 5" in result["cardinalityLatexContent"]

    def test_cardinality_shown_with_max_only(self):
        """Test that cardinality is shown with only max constraint."""
        result = run_math_test(
            "portfolio",
            "cardinality",
            {"minSelectedAssets": "", "maxSelectedAssets": "10"},
        )
        assert result["success"] is True
        assert result["cardinalityBlockVisible"] is True
        assert "\\leq 10" in result["cardinalityLatexContent"]

    def test_cardinality_shown_with_both(self):
        """Test that cardinality is shown with both constraints."""
        result = run_math_test(
            "portfolio",
            "cardinality",
            {"minSelectedAssets": "3", "maxSelectedAssets": "8"},
        )
        assert result["success"] is True
        assert result["cardinalityBlockVisible"] is True
        assert "\\geq 3" in result["cardinalityLatexContent"]
        assert "\\leq 8" in result["cardinalityLatexContent"]


class TestReductionModeDisplay:
    """Test reduction mode display in math panel."""

    def test_portfolio_baseline_mode(self):
        """Test that portfolio shows baseline when rounds=0."""
        result = run_math_test("portfolio", "reduction_mode", {"maxRounds": "0"})
        assert result["success"] is True
        assert result["showsBaseline"] is True
        assert result["showsReduction"] is False

    def test_portfolio_single_pass_mode(self):
        """Test that portfolio shows single-pass when rounds=1."""
        result = run_math_test("portfolio", "reduction_mode", {"maxRounds": "1"})
        assert result["success"] is True
        assert result["showsBaseline"] is False
        assert result["showsReduction"] is True
        assert "single-pass" in result["reductionContentHTML"]

    def test_portfolio_multi_round_mode(self):
        """Test that portfolio shows multi-round when rounds>1."""
        result = run_math_test("portfolio", "reduction_mode", {"maxRounds": "3"})
        assert result["success"] is True
        assert result["showsBaseline"] is False
        assert result["showsReduction"] is True
        assert "multi-round" in result["reductionContentHTML"]

    def test_facility_baseline_mode(self):
        """Test that facility location shows baseline when rounds=0."""
        result = run_math_test("facility_location", "reduction_mode", {"rounds": "0"})
        assert result["success"] is True
        assert result["showsBaseline"] is True
        assert result["showsReduction"] is False

    def test_facility_single_pass_mode(self):
        """Test that facility location shows single-pass when rounds=1."""
        result = run_math_test("facility_location", "reduction_mode", {"rounds": "1"})
        assert result["success"] is True
        assert result["showsBaseline"] is False
        assert result["showsReduction"] is True

    def test_facility_multi_round_mode(self):
        """Test that facility location shows multi-round when rounds>1."""
        result = run_math_test("facility_location", "reduction_mode", {"rounds": "2"})
        assert result["success"] is True
        assert result["showsBaseline"] is False
        assert result["showsReduction"] is True


class TestResetBehavior:
    """Test that reset restores math panel to default state."""

    def test_portfolio_reset_restores_values(self):
        """Test that portfolio reset restores math panel values."""
        result = run_math_test("portfolio", "reset")
        assert result["success"] is True
        assert result["assetCountAfterReset"] == "30"
        assert result["cardinalityHiddenAfterReset"] is True

    def test_facility_reset_restores_baseline(self):
        """Test that facility location reset shows baseline mode."""
        result = run_math_test("facility_location", "reset")
        assert result["success"] is True
        assert result["showsBaselineAfterReset"] is True


class TestFallbackBehavior:
    """Test fallback behavior when MathJax fails to load."""

    def test_portfolio_fallback_on_load_failure(self):
        """Test that portfolio shows fallback when MathJax fails to load."""
        result = run_math_test("portfolio", "fallback_load_failure")
        assert result["success"] is True
        assert result["mathJaxHasFailed"] is True
        assert result["hasLatexElements"] is True
        assert result["hasFallbackElements"] is True

    def test_facility_fallback_on_load_failure(self):
        """Test that facility location shows fallback when MathJax fails."""
        result = run_math_test("facility_location", "fallback_load_failure")
        assert result["success"] is True
        assert result["mathJaxHasFailed"] is True
        assert result["hasLatexElements"] is True
        assert result["hasFallbackElements"] is True


class TestRenderSerialization:
    """Test that rendering is serialized to prevent DOM modifications during active render."""

    def test_portfolio_no_cleans_during_render(self):
        """Test that no clearTypeset happens while render is in progress."""
        result = run_math_test("portfolio", "render_serialization")
        assert result["success"] is True
        assert result["revisionsIncremented"] is True
        assert result["noCleansDuringRender"] is True, (
            f"Found {result['cleansWhileRendering']} cleans during active render"
        )

    def test_facility_no_cleans_during_render(self):
        """Test that facility location has no cleans during render."""
        result = run_math_test("facility_location", "render_serialization")
        assert result["success"] is True
        assert result["revisionsIncremented"] is True
        assert result["noCleansDuringRender"] is True


class TestNumberFormatPrecision:
    """Test that formatNumber preserves the precision of input values."""

    def test_precision_preserved(self):
        """Test that formatNumber preserves significant digits."""
        result = run_math_test("portfolio", "number_precision")
        assert result["success"] is True
        assert result["allPassed"] is True, (
            f"Some precision tests failed: {[r for r in result['results'] if not r['passed']]}"
        )

    def test_small_decimals_preserved(self):
        """Test that small decimals like 0.001 are not rounded to 0."""
        result = run_math_test("portfolio", "number_precision")
        assert result["success"] is True
        for tc in result["results"]:
            if str(tc.get("input", "")) == "0.001" or tc.get("input") == 0.001:
                assert tc["actual"] == "0.001", f"0.001 was formatted as {tc['actual']}"
                break

    def test_trailing_zeros_removed(self):
        """Test that trailing zeros are removed but precision kept."""
        result = run_math_test("portfolio", "number_precision")
        assert result["success"] is True
        for tc in result["results"]:
            inp = str(tc.get("input", ""))
            if inp == "1.000":
                assert tc["actual"] == "1"
            elif inp == "1.100":
                assert tc["actual"] == "1.1"


class TestNoHtmlInTex:
    """Test that TeX content has no HTML tags inside delimiters."""

    def test_portfolio_no_html_in_tex(self):
        """Test that portfolio TeX has no internal HTML tags."""
        result = run_math_test("portfolio", "no_html_in_tex")
        assert result["success"] is True
        assert result["noViolations"] is True, f"Found HTML inside TeX: {result['violations']}"

    def test_facility_no_html_in_tex(self):
        """Test that facility location TeX has no internal HTML tags."""
        result = run_math_test("facility_location", "no_html_in_tex")
        assert result["success"] is True
        assert result["noViolations"] is True, f"Found HTML inside TeX: {result['violations']}"


class TestLateMathJaxLoading:
    """Test that late MathJax loading doesn't cause concurrent renders."""

    def test_portfolio_no_concurrent_renders(self):
        """Test that portfolio has no concurrent renders on late load."""
        result = run_math_test("portfolio", "late_loading")
        assert result["success"] is True
        assert result["noConcurrentRenders"] is True, (
            f"Found {result['maxConcurrentRenders']} concurrent renders, expected max 1"
        )

    def test_facility_no_concurrent_renders(self):
        """Test that facility location has no concurrent renders on late load."""
        result = run_math_test("facility_location", "late_loading")
        assert result["success"] is True
        assert result["noConcurrentRenders"] is True, (
            f"Found {result['maxConcurrentRenders']} concurrent renders, expected max 1"
        )


class TestMutationsDuringRender:
    """Test that no user DOM mutations happen during active render."""

    def test_portfolio_no_mutations_during_render(self):
        """Test that portfolio DOM updates are queued, not concurrent."""
        result = run_math_test("portfolio", "mutations_during_render")
        assert result["success"] is True
        # Note: some mutations during render are OK (MathJax adding mjx-container)
        # The test checks for USER mutations (innerHTML changes by our code)
        assert result["noUserMutationsDuringRender"] is True, (
            f"Found {result['userMutationsDuringRender']} user mutations during render. "
            f"Details: {result.get('details', {}).get('duringRender', [])}"
        )

    def test_facility_no_mutations_during_render(self):
        """Test that facility location DOM updates are queued, not concurrent."""
        result = run_math_test("facility_location", "mutations_during_render")
        assert result["success"] is True
        assert result["noUserMutationsDuringRender"] is True, (
            f"Found {result['userMutationsDuringRender']} user mutations during render. "
            f"Details: {result.get('details', {}).get('duringRender', [])}"
        )


class TestTrueLateMathJaxLoading:
    """Test that true late MathJax loading (after debounce) doesn't deadlock."""

    def test_portfolio_no_deadlock_on_late_loading(self):
        """Test that portfolio doesn't deadlock when MathJax loads after debounce."""
        result = run_math_test("portfolio", "true_late_loading")
        assert result["success"] is True
        assert result["queueCompleted"] is True, "Render queue did not complete (deadlock)"
        assert result["typesetCalls"] > 0, "No typeset calls made"
        assert result["noDeadlock"] is True, (
            f"Deadlock detected: queue={result['queueCompleted']}, "
            f"typesets={result['typesetCalls']}"
        )

    def test_facility_no_deadlock_on_late_loading(self):
        """Test that facility location doesn't deadlock when MathJax loads late."""
        result = run_math_test("facility_location", "true_late_loading")
        assert result["success"] is True
        assert result["queueCompleted"] is True, "Render queue did not complete (deadlock)"
        assert result["typesetCalls"] > 0, "No typeset calls made"
        assert result["noDeadlock"] is True

    def test_portfolio_subsequent_updates_work(self):
        """Test that portfolio updates work after late loading."""
        result = run_math_test("portfolio", "true_late_loading")
        assert result["success"] is True
        assert result["subsequentUpdateWorks"] is True, (
            "Subsequent updates don't work after late MathJax loading"
        )

    def test_facility_subsequent_updates_work(self):
        """Test that facility updates work after late loading."""
        result = run_math_test("facility_location", "true_late_loading")
        assert result["success"] is True
        assert result["subsequentUpdateWorks"] is True
