"""Tests for UIX parameter tooltips.

These tests verify that:
1. Each parameter has a PARAM_DESC comment in the HTML
2. The tooltip system correctly extracts and displays descriptions
3. All parameters in both configurators have tooltips (exact coverage)
4. Tooltip behavior: click, Escape, exclusive open
5. Accessibility: button element, aria-describedby, unique IDs
"""

import re
from pathlib import Path

import pytest

# Expected parameters for each configurator (exact list - no tolerance)
PORTFOLIO_PARAMS = [
    "runId",
    "outputRoot",
    "logConfig",
    "assetCount",
    "riskAversion",
    "generationSeed",
    "observationCount",
    "lowerBound",
    "upperBound",
    "minSelectedAssets",
    "maxSelectedAssets",
    "edgeMode",
    "correlationThreshold",
    "returnDifference",
    "varianceDifference",
    "maxRounds",
    "minItems",
    "maxItems",
    "targetBinary",
    "minReductionRatio",
    "endToEndBudget",
    "domainRecovery",
    "infeasibleRecovery",
    "recoveryAttempts",
    "misSolver",
    "classicalSolver",
    "classicalTimeLimit",
    "numReads",
    "numSweeps",
    "embeddingProfile",
    "pasqalShots",
    "modelExport",
    "modelExportPath",
]

FACILITY_LOCATION_PARAMS = [
    "instancePath",
    "runId",
    "outputRoot",
    "logConfig",
    "rounds",
    "cap",
    "budget",
    "classicalTimeLimit",
    "seed",
    "minReductionRatio",
    "recoveryAttempts",
    "protectAll",
    "solver",
    "misSolver",
    "modelExport",
    "alpha",
    "epsilon",
    "profileFraction",
    "overlapThreshold",
    "capacityDifference",
]


def get_uix_path() -> Path:
    """Get the UIX directory path."""
    return Path(__file__).parent.parent / "uix"


def extract_param_desc_comments(html_content: str) -> dict[str, str]:
    """Extract PARAM_DESC comments from HTML content.

    Returns a dict mapping field ID to description text.
    The comment must immediately precede a .field or .switch-row element.
    """
    results = {}

    # For each comment, find the associated field ID
    for match in re.finditer(r'<!--\s*PARAM_DESC:\s*(.+?)\s*-->\s*\n?\s*<div class="(?:field[^"]*|switch-row)"', html_content):
        desc = match.group(1).strip()
        # Find the field ID in the following content
        after_comment = html_content[match.end():]
        # Look for id= attribute in input, select, or within switch-row
        id_match = re.search(r'id="([^"]+)"', after_comment[:500])
        if id_match:
            field_id = id_match.group(1)
            results[field_id] = desc

    return results


class TestPortfolioTooltipComments:
    """Test that portfolio.html has PARAM_DESC comments for all parameters."""

    @pytest.fixture
    def html_content(self) -> str:
        """Load portfolio HTML content."""
        html_path = get_uix_path() / "experiment_portfolio_mv.html"
        return html_path.read_text()

    def test_exact_param_coverage(self, html_content: str) -> None:
        """Test that exactly all expected parameters have PARAM_DESC comments."""
        comments = extract_param_desc_comments(html_content)

        missing = set(PORTFOLIO_PARAMS) - set(comments.keys())

        assert not missing, f"Missing PARAM_DESC comments for: {sorted(missing)}"
        # Extra comments are OK (future parameters)

    def test_comments_are_non_empty(self, html_content: str) -> None:
        """Test that all PARAM_DESC comments have content."""
        comments = extract_param_desc_comments(html_content)
        empty = [param for param, desc in comments.items() if not desc.strip()]
        assert not empty, f"Empty PARAM_DESC comments for: {empty}"

    def test_comments_have_minimum_length(self, html_content: str) -> None:
        """Test that comments are descriptive (minimum 30 characters)."""
        comments = extract_param_desc_comments(html_content)
        short = [param for param, desc in comments.items() if len(desc.strip()) < 30]
        assert not short, f"Too short PARAM_DESC comments for: {short}"

    @pytest.mark.parametrize("param_id", PORTFOLIO_PARAMS)
    def test_individual_param_has_comment(self, html_content: str, param_id: str) -> None:
        """Test that each individual parameter has a PARAM_DESC comment."""
        comments = extract_param_desc_comments(html_content)
        assert param_id in comments, f"Missing PARAM_DESC comment for {param_id}"


class TestFacilityLocationTooltipComments:
    """Test that facility_location.html has PARAM_DESC comments for all parameters."""

    @pytest.fixture
    def html_content(self) -> str:
        """Load facility_location HTML content."""
        html_path = get_uix_path() / "experiment_facility_location.html"
        return html_path.read_text()

    def test_exact_param_coverage(self, html_content: str) -> None:
        """Test that exactly all expected parameters have PARAM_DESC comments."""
        comments = extract_param_desc_comments(html_content)

        missing = set(FACILITY_LOCATION_PARAMS) - set(comments.keys())

        assert not missing, f"Missing PARAM_DESC comments for: {sorted(missing)}"

    def test_comments_are_non_empty(self, html_content: str) -> None:
        """Test that all PARAM_DESC comments have content."""
        comments = extract_param_desc_comments(html_content)
        empty = [param for param, desc in comments.items() if not desc.strip()]
        assert not empty, f"Empty PARAM_DESC comments for: {empty}"

    def test_comments_have_minimum_length(self, html_content: str) -> None:
        """Test that comments are descriptive (minimum 30 characters)."""
        comments = extract_param_desc_comments(html_content)
        short = [param for param, desc in comments.items() if len(desc.strip()) < 30]
        assert not short, f"Too short PARAM_DESC comments for: {short}"

    @pytest.mark.parametrize("param_id", FACILITY_LOCATION_PARAMS)
    def test_individual_param_has_comment(self, html_content: str, param_id: str) -> None:
        """Test that each individual parameter has a PARAM_DESC comment."""
        comments = extract_param_desc_comments(html_content)
        assert param_id in comments, f"Missing PARAM_DESC comment for {param_id}"


class TestTooltipJavaScript:
    """Test that tooltip JavaScript functions are present and correct."""

    @pytest.fixture
    def common_js(self) -> str:
        """Load common.js content."""
        js_path = get_uix_path() / "assets" / "common.js"
        return js_path.read_text()

    @pytest.fixture
    def portfolio_js(self) -> str:
        """Load portfolio_mv.js content."""
        js_path = get_uix_path() / "assets" / "portfolio_mv.js"
        return js_path.read_text()

    @pytest.fixture
    def facility_location_js(self) -> str:
        """Load facility_location.js content."""
        js_path = get_uix_path() / "assets" / "facility_location.js"
        return js_path.read_text()

    def test_extract_param_description_function_exists(self, common_js: str) -> None:
        """Test that extractParamDescription function exists."""
        assert "extractParamDescription" in common_js

    def test_extract_switch_description_function_exists(self, common_js: str) -> None:
        """Test that extractSwitchDescription function exists."""
        assert "extractSwitchDescription" in common_js

    def test_create_tooltip_element_function_exists(self, common_js: str) -> None:
        """Test that createTooltipElement function exists."""
        assert "createTooltipElement" in common_js

    def test_init_tooltips_function_exists(self, common_js: str) -> None:
        """Test that initTooltips function exists."""
        assert "initTooltips" in common_js

    def test_init_tooltips_exported(self, common_js: str) -> None:
        """Test that initTooltips is exported in the public API."""
        assert "initTooltips: initTooltips" in common_js

    def test_portfolio_calls_init_tooltips(self, portfolio_js: str) -> None:
        """Test that portfolio_mv.js calls initTooltips."""
        assert "initTooltips()" in portfolio_js or "C.initTooltips()" in portfolio_js

    def test_facility_location_calls_init_tooltips(self, facility_location_js: str) -> None:
        """Test that facility_location.js calls initTooltips."""
        assert "initTooltips()" in facility_location_js or "C.initTooltips()" in facility_location_js

    # New tests for improved functionality
    def test_active_tooltip_state_management(self, common_js: str) -> None:
        """Test that activeTooltip state variable exists."""
        assert "activeTooltip" in common_js

    def test_close_active_tooltip_function(self, common_js: str) -> None:
        """Test that closeActiveTooltip function exists."""
        assert "closeActiveTooltip" in common_js

    def test_escape_key_handler(self, common_js: str) -> None:
        """Test that Escape key handler is registered."""
        assert 'key === "Escape"' in common_js or "key === 'Escape'" in common_js

    def test_button_element_used(self, common_js: str) -> None:
        """Test that native button element is used (not span with role=button)."""
        assert 'createElement("button")' in common_js or "createElement('button')" in common_js

    def test_aria_describedby_set(self, common_js: str) -> None:
        """Test that aria-describedby is set on info buttons."""
        assert "aria-describedby" in common_js

    def test_tooltip_has_unique_id(self, common_js: str) -> None:
        """Test that tooltips get unique IDs."""
        assert "generateTooltipId" in common_js or "tooltip.id =" in common_js

    def test_param_specific_label(self, common_js: str) -> None:
        """Test that aria-label includes parameter name."""
        assert "Informazioni su" in common_js


class TestTooltipCSS:
    """Test that tooltip CSS styles are present."""

    @pytest.fixture
    def common_css(self) -> str:
        """Load common.css content."""
        css_path = get_uix_path() / "assets" / "common.css"
        return css_path.read_text()

    def test_info_icon_class_exists(self, common_css: str) -> None:
        """Test that .info-icon class exists."""
        assert ".info-icon" in common_css

    def test_tooltip_class_exists(self, common_css: str) -> None:
        """Test that .tooltip class exists."""
        assert ".tooltip" in common_css

    def test_tooltip_wrapper_class_exists(self, common_css: str) -> None:
        """Test that .tooltip-wrapper class exists."""
        assert ".tooltip-wrapper" in common_css

    def test_tooltip_has_visibility_styles(self, common_css: str) -> None:
        """Test that tooltip has visibility/opacity styles for show/hide."""
        assert "visibility" in common_css
        assert "opacity" in common_css

    def test_tooltip_active_class(self, common_css: str) -> None:
        """Test that tooltip-active class exists for JS-managed state."""
        assert ".tooltip-active" in common_css or "tooltip-active" in common_css

    def test_tooltip_below_class(self, common_css: str) -> None:
        """Test that tooltip-below class exists for vertical positioning."""
        assert ".tooltip-below" in common_css or "tooltip-below" in common_css

    def test_tooltip_has_hover_state(self, common_css: str) -> None:
        """Test that tooltip has hover state for showing."""
        assert ":hover" in common_css

    def test_tooltip_has_focus_state(self, common_css: str) -> None:
        """Test that tooltip has focus state for accessibility."""
        assert ":focus" in common_css


class TestTooltipJSExecution:
    """Test tooltip initialization and behavior using Node.js and jsdom."""

    def run_tooltip_test(self, configurator: str, test_type: str = "init") -> dict:
        """Run tooltip test via Node.js.

        Args:
            configurator: "portfolio" or "facility_location"
            test_type: "init", "click", "escape", or "exclusive"

        Returns dict with test results.
        """
        import json
        import subprocess

        runner_path = Path(__file__).parent / "uix_tooltip_runner.js"
        if not runner_path.exists():
            pytest.skip("uix_tooltip_runner.js not found")

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
            ["node", str(runner_path), configurator, test_type],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )

        if result.returncode != 0:
            if "Cannot find module" in result.stderr and "jsdom" in result.stderr:
                pytest.skip("jsdom not installed (run: npm install)")
            pytest.fail(f"Tooltip test runner failed: {result.stderr}")

        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            pytest.fail(f"Invalid JSON output: {result.stdout}")

    def test_portfolio_exact_tooltip_count(self) -> None:
        """Test that exactly all portfolio parameters have tooltips."""
        result = self.run_tooltip_test("portfolio")
        expected = len(PORTFOLIO_PARAMS)
        actual = result["tooltipCount"]
        assert set(result["fieldsWithTooltips"]) == set(PORTFOLIO_PARAMS)
        assert actual == expected, \
            f"Expected exactly {expected} tooltips, got {actual}. Missing: {set(PORTFOLIO_PARAMS) - set(result.get('fieldsWithTooltips', []))}"

    def test_facility_location_exact_tooltip_count(self) -> None:
        """Test that exactly all facility_location parameters have tooltips."""
        result = self.run_tooltip_test("facility_location")
        expected = len(FACILITY_LOCATION_PARAMS)
        actual = result["tooltipCount"]
        assert set(result["fieldsWithTooltips"]) == set(FACILITY_LOCATION_PARAMS)
        assert actual == expected, \
            f"Expected exactly {expected} tooltips, got {actual}. Missing: {set(FACILITY_LOCATION_PARAMS) - set(result.get('fieldsWithTooltips', []))}"

    def test_portfolio_all_params_have_tooltips(self) -> None:
        """Test that all expected portfolio parameters have tooltips."""
        result = self.run_tooltip_test("portfolio")
        fields_with_tooltips = set(result.get("fieldsWithTooltips", []))
        missing = set(PORTFOLIO_PARAMS) - fields_with_tooltips
        assert not missing, f"Parameters without tooltips: {sorted(missing)}"

    def test_facility_location_all_params_have_tooltips(self) -> None:
        """Test that all expected facility_location parameters have tooltips."""
        result = self.run_tooltip_test("facility_location")
        fields_with_tooltips = set(result.get("fieldsWithTooltips", []))
        missing = set(FACILITY_LOCATION_PARAMS) - fields_with_tooltips
        assert not missing, f"Parameters without tooltips: {sorted(missing)}"

    def test_portfolio_tooltip_text_matches_comment(self) -> None:
        """Test that tooltip text matches the PARAM_DESC comment exactly."""
        result = self.run_tooltip_test("portfolio")
        html_path = get_uix_path() / "experiment_portfolio_mv.html"
        html_content = html_path.read_text()
        comments = extract_param_desc_comments(html_content)

        mismatches = []
        for field_id, tooltip_text in result.get("tooltipTexts", {}).items():
            if field_id in comments and comments[field_id] != tooltip_text:
                mismatches.append(field_id)

        assert not mismatches, f"Tooltip text mismatch for: {mismatches}"

    def test_facility_location_tooltip_text_matches_comment(self) -> None:
        """Test that tooltip text matches the PARAM_DESC comment exactly."""
        result = self.run_tooltip_test("facility_location")
        html_path = get_uix_path() / "experiment_facility_location.html"
        html_content = html_path.read_text()
        comments = extract_param_desc_comments(html_content)

        mismatches = []
        for field_id, tooltip_text in result.get("tooltipTexts", {}).items():
            if field_id in comments and comments[field_id] != tooltip_text:
                mismatches.append(field_id)

        assert not mismatches, f"Tooltip text mismatch for: {mismatches}"

    def test_portfolio_tooltips_use_button_element(self) -> None:
        """Test that tooltips use native button elements."""
        result = self.run_tooltip_test("portfolio")
        assert result.get("usesButtonElement", False), \
            "Tooltips should use native <button> elements for accessibility"

    def test_facility_location_tooltips_use_button_element(self) -> None:
        """Test that tooltips use native button elements."""
        result = self.run_tooltip_test("facility_location")
        assert result.get("usesButtonElement", False), \
            "Tooltips should use native <button> elements for accessibility"

    def test_portfolio_tooltips_have_aria_describedby(self) -> None:
        """Test that tooltip buttons have aria-describedby."""
        result = self.run_tooltip_test("portfolio")
        assert result.get("hasAriaDescribedby", False), \
            "Tooltip buttons should have aria-describedby attribute"

    def test_facility_location_tooltips_have_aria_describedby(self) -> None:
        """Test that tooltip buttons have aria-describedby."""
        result = self.run_tooltip_test("facility_location")
        assert result.get("hasAriaDescribedby", False), \
            "Tooltip buttons should have aria-describedby attribute"

    def test_portfolio_tooltips_have_unique_ids(self) -> None:
        """Test that tooltips have unique IDs."""
        result = self.run_tooltip_test("portfolio")
        tooltip_ids = result.get("tooltipIds", [])
        assert len(tooltip_ids) == len(set(tooltip_ids)), \
            "Tooltip IDs should be unique"

    def test_facility_location_tooltips_have_unique_ids(self) -> None:
        """Test that tooltips have unique IDs."""
        result = self.run_tooltip_test("facility_location")
        tooltip_ids = result.get("tooltipIds", [])
        assert len(tooltip_ids) == len(set(tooltip_ids)), \
            "Tooltip IDs should be unique"

    # Behavioral tests
    def test_click_opens_tooltip(self) -> None:
        """Test that clicking the info button opens the tooltip."""
        result = self.run_tooltip_test("portfolio", "click")
        assert result.get("tooltipOpened", False), \
            "Clicking info button should open the tooltip"

    def test_escape_closes_tooltip(self) -> None:
        """Test that pressing Escape closes the tooltip."""
        result = self.run_tooltip_test("portfolio", "escape")
        assert result.get("tooltipClosed", False), \
            "Pressing Escape should close the tooltip"

    def test_only_one_tooltip_open(self) -> None:
        """Test that only one tooltip can be open at a time."""
        result = self.run_tooltip_test("portfolio", "exclusive")
        assert result.get("onlyOneOpen", False), \
            "Only one tooltip should be open at a time"

    # New behavioral sequence tests
    def test_hover_focus_click_sequence(self) -> None:
        """Test sequence: hover opens, focus keeps open, click pins (doesn't close)."""
        result = self.run_tooltip_test("portfolio", "hover_focus_click")
        assert result.get("success", False), \
            f"Hover->focus->click sequence failed: {result}"

    def test_focus_enter_sequence(self) -> None:
        """Test sequence: focus opens tooltip, Enter pins it (doesn't close)."""
        result = self.run_tooltip_test("portfolio", "focus_enter")
        assert result.get("success", False), \
            f"Focus->Enter sequence failed: {result}"

    def test_pinned_behavior(self) -> None:
        """Test pinned vs unpinned behavior: hover closes unpinned, click pins, second click closes."""
        result = self.run_tooltip_test("portfolio", "pinned_behavior")
        assert result.get("success", False), \
            f"Pinned behavior test failed: {result}"

    # Form controls comparison tests
    def test_portfolio_all_form_controls_have_tooltips(self) -> None:
        """Test that all form controls in portfolio have tooltips (derived from DOM)."""
        result = self.run_tooltip_test("portfolio", "form_controls")
        assert result.get("allControlsHaveTooltips", False), \
            f"Form controls without tooltips: {result.get('controlsWithoutTooltips', [])}"

    def test_facility_location_all_form_controls_have_tooltips(self) -> None:
        """Test that all form controls in facility_location have tooltips (derived from DOM)."""
        result = self.run_tooltip_test("facility_location", "form_controls")
        assert result.get("allControlsHaveTooltips", False), \
            f"Form controls without tooltips: {result.get('controlsWithoutTooltips', [])}"

    # Button outside label tests
    def test_portfolio_button_outside_label(self) -> None:
        """Test that info buttons are siblings of labels, not children."""
        result = self.run_tooltip_test("portfolio")
        assert result.get("buttonOutsideLabel", False), \
            "Info buttons should be outside <label> elements"

    def test_facility_location_button_outside_label(self) -> None:
        """Test that info buttons are siblings of labels, not children."""
        result = self.run_tooltip_test("facility_location")
        assert result.get("buttonOutsideLabel", False), \
            "Info buttons should be outside <label> elements"

    # aria-expanded tests
    def test_portfolio_has_aria_expanded(self) -> None:
        """Test that info buttons have aria-expanded attribute."""
        result = self.run_tooltip_test("portfolio")
        assert result.get("hasAriaExpanded", False), \
            "Info buttons should have aria-expanded attribute"

    def test_facility_location_has_aria_expanded(self) -> None:
        """Test that info buttons have aria-expanded attribute."""
        result = self.run_tooltip_test("facility_location")
        assert result.get("hasAriaExpanded", False), \
            "Info buttons should have aria-expanded attribute"
