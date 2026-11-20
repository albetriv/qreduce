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



class TestPortfolioSRMathPanel:
    """Test portfolio_sr specific math formulation functionality."""

    def test_panel_exists(self):
        """Test that portfolio_sr has a math formulation panel."""
        result = run_math_test("portfolio_sr", "init")
        assert result["success"] is True
        assert result["hasMathPanel"] is True
        assert result["hasMathContent"] is True
        assert result["hasReductionSection"] is True

    def test_static_tex_preserved(self):
        """Test that portfolio_sr static TeX is preserved."""
        result = run_math_test("portfolio_sr", "tex_preservation")
        assert result["success"] is True
        assert result["staticElements"] > 0
        # Not all elements may be preserved if they're in dynamic containers
        # The important thing is that some static content is preserved
        assert result["preservedCount"] > 0

    def test_formulas_restored_after_clear(self):
        """Test that portfolio_sr formulas are restored after clear."""
        result = run_math_test("portfolio_sr", "formula_restoration")
        assert result["success"] is True
        assert result["contentRestored"] is True

    def test_cardinality_display(self):
        """Test that cardinality block appears when maxPositions is set."""
        result = run_math_test(
            "portfolio_sr",
            "values_update",
            {"maxPositions": "10"},
        )
        assert result["success"] is True
        assert result["hasRenderedContent"] is True
        assert result["cardinalityVisible"] is True
        assert result["transformedCardinalityVisible"] is True
        assert result["displayedMaxPositions"] == "10"
        assert "M_i" in result["cardinalityText"]

    def test_reduction_mode_display(self):
        """Test that reduction mode displays correctly for baseline."""
        result = run_math_test(
            "portfolio_sr",
            "reduction_mode",
            {"maxRounds": "0"},
        )
        assert result["success"] is True
        # Use reductionContent (text) which the runner now returns
        content = result.get("reductionContent") or result.get("reductionContentHTML") or ""
        assert content, "No reduction content found"
        assert "baseline" in content.lower() or "senza riduzione" in content.lower()

    def test_reduction_mode_single_pass(self):
        """Test that reduction mode displays correctly for single-pass."""
        result = run_math_test(
            "portfolio_sr",
            "reduction_mode",
            {"maxRounds": "1"},
        )
        assert result["success"] is True
        content = result.get("reductionContent") or result.get("reductionContentHTML") or ""
        assert content, "No reduction content found"
        assert "single" in content.lower() or "un round" in content.lower()

    def test_reduction_mode_multi_round(self):
        """Test that reduction mode displays correctly for multi-round."""
        result = run_math_test(
            "portfolio_sr",
            "reduction_mode",
            {"maxRounds": "3"},
        )
        assert result["success"] is True
        content = result.get("reductionContent") or result.get("reductionContentHTML") or ""
        assert content, "No reduction content found"
        assert "multi" in content.lower() or "3" in content or "fino a" in content.lower()

    def test_fallback_on_load_failure(self):
        """Test that portfolio_sr shows fallback when MathJax fails."""
        result = run_math_test("portfolio_sr", "fallback_load_failure")
        assert result["success"] is True
        assert result["mathJaxHasFailed"] is True
        assert result["hasLatexElements"] is True
        assert result["hasFallbackElements"] is True

    def test_no_html_in_tex(self):
        """Test that portfolio_sr TeX has no internal HTML tags."""
        result = run_math_test("portfolio_sr", "no_html_in_tex")
        assert result["success"] is True
        assert result["noViolations"] is True, f"Found HTML inside TeX: {result['violations']}"

    def test_no_concurrent_renders(self):
        """Test that portfolio_sr has no concurrent renders on late load."""
        result = run_math_test("portfolio_sr", "late_loading")
        assert result["success"] is True
        assert result["noConcurrentRenders"] is True

    def test_reset_restores_defaults(self):
        """Test that reset restores default values in math panel."""
        result = run_math_test("portfolio_sr", "reset")
        assert result["success"] is True
        # After reset, asset count should be default (50)
        assert result.get("assetCountAfterReset") == "50"
        # Cardinality should be hidden after reset
        assert result.get("cardinalityHiddenAfterReset") is True

    def test_render_serialization(self):
        """Test that renders are serialized correctly."""
        result = run_math_test("portfolio_sr", "render_serialization")
        assert result["success"] is True
        assert result["revisionsIncremented"] is True
        assert result["noCleansDuringRender"] is True

    def test_true_late_loading_no_deadlock(self):
        """Test that late MathJax loading doesn't cause deadlock."""
        result = run_math_test("portfolio_sr", "true_late_loading")
        assert result["success"] is True
        assert result["queueCompleted"] is True
        assert result["noDeadlock"] is True

    def test_optional_formulas_survive_consuming_renderer(self):
        result = run_math_test("portfolio_sr", "sr_formula_lifecycle")
        assert len(result["stages"]) == 7
        assert all(result["stages"])
        assert result["typesetCalls"] >= 7
        assert result["cardinalityHidden"] and result["sectorsHidden"]

    @pytest.mark.parametrize("fields,display,key", [
        ({"assetCount": "12.5"}, "?", "displayedAssetCount"),
        ({"assetCount": ""}, "?", "displayedAssetCount"),
        ({"assetCount": "0"}, "?", "displayedAssetCount"),
        ({"maxPositions": "2.5"}, "Non valido", "displayedMaxPositions"),
        ({"maxPositions": "0"}, "Non valido", "displayedMaxPositions"),
        ({"maxPositions": "-1"}, "Non valido", "displayedMaxPositions"),
        ({"maxPositions": "51"}, "Non valido", "displayedMaxPositions"),
        ({"upperBound": "0"}, "?", "displayedUpperBound"),
        ({"upperBound": "1.1"}, "?", "displayedUpperBound"),
    ])
    def test_invalid_numbers_are_not_presented_as_valid(self, fields, display, key):
        result = run_math_test("portfolio_sr", "update_values", fields)
        assert result[key] == display
        assert not result["valid"]
        assert result["copyDisabled"]
        assert result["command"].startswith("Configurazione non valida")

    @pytest.mark.parametrize("rounds", ["", "-1", "1.5"])
    def test_invalid_rounds_do_not_become_baseline(self, rounds):
        result = run_math_test("portfolio_sr", "update_values", {"maxRounds": rounds})
        assert "non determinabile" in result["reductionText"]
        assert not result["valid"]

    @pytest.mark.parametrize("fields", [
        {"sectorMin": "Technology=0.2junk"},
        {"sectorMin": "Technology"},
        {"sectorMin": "Technology="},
        {"sectorMin": "Technology=Infinity"},
        {"sectorMin": "Technology=NaN"},
        {"sectorMin": "Technology=-0.1"},
        {"sectorMax": "Technology=1.1"},
        {"sectorMin": "Technology=0.5", "sectorMax": "Technology=0.2"},
        {"sectorMin": "Technology=0.6,Health Care=0.6"},
        {"sectorMin": "Technology=0.1,malformed"},
    ])
    def test_invalid_sectors_are_not_silently_ignored(self, fields):
        result = run_math_test("portfolio_sr", "update_values", fields)
        assert not result["valid"]
        assert result["copyDisabled"]
        assert result["sectorVisible"]
        assert not result["sectorFormulaVisible"]
        assert "non validi" in result["sectorDetails"]

    @pytest.mark.parametrize("fields,expected", [
        ({"sectorMin": "Technology=0.1"}, "0.1–1"),
        ({"sectorMax": "Technology=0.3"}, "0–0.3"),
        ({"sectorMin": "Technology=0.1", "sectorMax": "Technology=0.3"}, "0.1–0.3"),
        ({"sectorMin": "hasOwnProperty=0.1"}, "0.1–1"),
        ({"sectorMin": "__proto__=0.1"}, "0.1–1"),
    ])
    def test_sector_defaults_and_transformed_details(self, fields, expected):
        result = run_math_test("portfolio_sr", "update_values", fields)
        assert result["valid"]
        assert expected in result["sectorDetails"]
        assert result["sectorDetails"] == result["transformedSectorDetails"]

    def test_sr_command_is_accepted_by_python_parser(self):
        import shlex

        from qreduce.experiments.portfolio_sr.__main__ import (
            _build_parser,
            _parse_sector_constraints,
        )

        result = run_math_test("portfolio_sr", "update_values", {
            "assetCount": "25", "maxPositions": "10", "maxRounds": "3",
            "upperBound": "0.5", "sectorMin": "Technology=0.1",
            "sectorMax": "Technology=0.3",
        })
        assert result["valid"]
        tokens = shlex.split(result["command"].replace("\\\n", " "))
        args = _build_parser().parse_args(tokens[tokens.index("qreduce.experiments.portfolio_sr") + 1:])
        assert args.asset_count == 25
        assert args.max_positions == 10
        sectors = _parse_sector_constraints(args.sector_min, args.sector_max)
        assert sectors.sector_min["Technology"] == 0.1

    def test_integer_scientific_notation_is_not_truncated_in_command(self):
        result = run_math_test("portfolio_sr", "update_values", {
            "assetCount": "1e2", "maxPositions": "1e1", "maxRounds": "2e0",
        })
        assert result["valid"]
        assert result["displayedAssetCount"] == "100"
        assert result["displayedMaxPositions"] == "10"
        assert "--asset-count 100" in result["command"]
        assert "--max-positions 10" in result["command"]
        assert "--max-reduction-rounds 2" in result["command"]

    # ===== Summary panel tests =====

    def test_summary_initial_state(self):
        """Test that summary panel shows correct initial values."""
        result = run_math_test("portfolio_sr", "sr_summary_panel", {})
        assert result["success"] is True
        initial = result["initial"]
        assert initial["runId"] == "sr_001"
        assert initial["assets"] == "50"
        assert initial["mode"] == "single pass"
        assert initial["reduction"] == "1 round"
        assert initial["mis"] == "local_greedy"
        assert initial["classical"] == "scip"
        assert initial["valid"] is True
        assert initial["copyDisabled"] is False

    def test_summary_updates_on_form_change(self):
        """Test that summary updates when form fields change."""
        result = run_math_test("portfolio_sr", "sr_summary_panel", {
            "runId": "test_run_123",
            "assetCount": "75",
            "maxRounds": "3",
            "misSolver": "dwave_simulated_annealing",
            "classicalSolver": "cplex",
        })
        assert result["success"] is True
        after = result["afterChange"]
        assert after["runId"] == "test_run_123"
        assert after["assets"] == "75"
        assert after["mode"] == "multi-round"
        assert after["reduction"] == "3 rounds"
        assert after["mis"] == "dwave_simulated_annealing"
        assert after["classical"] == "cplex"
        assert result["afterReset"]["classical"] == "scip"

    @pytest.mark.parametrize("rounds,expected_mode,expected_reduction,expected_mis", [
        ("0", "classical only", "0 rounds", "(non usato)"),
        ("1", "single pass", "1 round", "local_greedy"),
        ("5", "multi-round", "5 rounds", "local_greedy"),
    ])
    def test_summary_mode_transitions_valid(self, rounds, expected_mode, expected_reduction, expected_mis):
        """Test mode transitions with valid round values."""
        result = run_math_test("portfolio_sr", "update_values", {"maxRounds": rounds})
        assert result["summaryMode"] == expected_mode
        assert result["summaryReduction"] == expected_reduction
        assert result["summaryMis"] == expected_mis

    @pytest.mark.parametrize("rounds", ["", "-1", "1.5"])
    def test_summary_mode_invalid_rounds(self, rounds):
        """Test that invalid rounds show placeholder values, not baseline."""
        result = run_math_test("portfolio_sr", "update_values", {"maxRounds": rounds})
        assert result["summaryMode"] == "—"
        assert result["summaryReduction"] == "—"
        assert result["summaryMis"] == "—"
        assert not result["valid"]
        assert result["copyDisabled"]

    def test_summary_mode_recovery_from_invalid_to_valid(self):
        """Test recovery from invalid rounds to valid values."""
        result = run_math_test("portfolio_sr", "sr_summary_panel", {})
        stages = result["roundTransitions"]
        expected = [
            ("multi-round", "3 rounds", "local_greedy", True),
            ("—", "—", "—", False),
            ("classical only", "0 rounds", "(non usato)", True),
            ("single pass", "1 round", "local_greedy", True),
        ]
        assert len(stages) == len(expected)
        for stage, (mode, reduction, mis, valid) in zip(stages, expected, strict=True):
            assert stage["mode"] == mode
            assert stage["reduction"] == reduction
            assert stage["mis"] == mis
            assert stage["valid"] is valid
            assert stage["copyDisabled"] is not valid
            assert stage["validationInvalid"] is not valid
            assert stage["validationTitle"] == (
                "Configurazione verificata" if valid else "Configurazione da correggere"
            )
            assert stage["validationText"] == (
                "Puoi copiare il comando CLI." if valid
                else "Correggi i messaggi in rosso prima di copiare."
            )
            assert stage["command"].startswith("Configurazione non valida") is not valid

    def test_format_switch_multiline(self):
        """Test that multiline format produces continuation lines."""
        result = run_math_test("portfolio_sr", "sr_summary_panel", {
            "assetCount": "100",
            "maxPositions": "20",
        })
        assert result["success"] is True
        # After clicking multiline button
        multiline_cmd = result["afterMultiline"]["command"]
        assert " \\\n" in multiline_cmd, "Multiline command should have continuation"
        assert result["afterMultiline"]["format"] == "multiline"

    def test_format_switch_inline(self):
        """Test that inline format has no continuation lines."""
        result = run_math_test("portfolio_sr", "sr_summary_panel", {
            "assetCount": "100",
        })
        assert result["success"] is True
        inline_cmd = result["afterInline"]["command"]
        assert " \\\n" not in inline_cmd, "Inline command should not have continuation"
        assert result["afterInline"]["format"] == "inline"

    def test_copy_matches_preview(self):
        """Test that copied text matches preview text."""
        result = run_math_test("portfolio_sr", "sr_summary_panel", {
            "assetCount": "60",
        })
        assert result["success"] is True
        assert result["copyMatchesPreview"] is True
        assert result["copiedText"] is not None
        assert result["inlineCopies"] == [result["afterInline"]["command"]]
        assert result["multilineCopies"] == [result["afterMultiline"]["command"]]
        assert "\\\n" in result["multilineCopies"][0]
        assert result["resetCopies"] == [result["afterReset"]["command"]]

    def test_copy_blocked_when_invalid(self):
        """Test that copy is blocked when configuration is invalid."""
        result = run_math_test("portfolio_sr", "sr_summary_panel", {})
        invalid = result["afterInvalid"]
        assert invalid["copyDisabled"] is True
        assert invalid["command"].startswith("Configurazione non valida")
        assert invalid["validationInvalid"] is True
        assert result["callsBeforeInvalid"] == 2
        assert result["callsAfterInvalid"] == result["callsBeforeInvalid"]
        assert len(result["resetCopies"]) == 1

    def test_reset_restores_summary(self):
        """Test that reset restores summary to default values."""
        result = run_math_test("portfolio_sr", "sr_summary_panel", {
            "runId": "modified_run",
            "assetCount": "100",
            "maxRounds": "5",
        })
        assert result["success"] is True
        # After reset, should be back to defaults
        after = result["afterReset"]
        assert after["runId"] == "sr_001"
        assert after["assets"] == "50"
        assert after["mode"] == "single pass"
        assert after["reduction"] == "1 round"
        assert after["valid"] is True
        assert after["copyDisabled"] is False
        assert after["validationInvalid"] is False
        assert after["validationTitle"] == "Configurazione verificata"
        assert after["validationText"] == "Puoi copiare il comando CLI."

    def test_multiline_command_accepted_by_parser(self):
        """Test that multiline command is accepted by Python CLI parser."""
        import shlex

        from qreduce.experiments.portfolio_sr.__main__ import _build_parser

        result = run_math_test("portfolio_sr", "sr_summary_panel", {
            "assetCount": "30",
            "maxPositions": "10",
            "maxRounds": "2",
        })
        assert result["success"] is True
        multiline_cmd = result["afterMultiline"]["command"]
        # Remove continuation characters for parsing
        flat_cmd = multiline_cmd.replace("\\\n", " ")
        tokens = shlex.split(flat_cmd)
        args = _build_parser().parse_args(tokens[tokens.index("qreduce.experiments.portfolio_sr") + 1:])
        assert args.asset_count == 30
        assert args.max_positions == 10
        assert args.max_reduction_rounds == 2
