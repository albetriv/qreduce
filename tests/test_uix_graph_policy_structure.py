"""Tests for UIX graph policy structure and transitions.

These tests verify:
1. Graph policy controls are located in the Reduction tab in all configurators
2. Facility Location does not have a dedicated Graph Policy tab
3. Baseline/reduction transitions preserve and re-validate values
4. near_duplicate/correlation_only transitions work correctly
5. Portfolio SR tolerance validation
"""

import json
import subprocess
from pathlib import Path

import pytest

# Path to the UIX directory
UIX_DIR = Path(__file__).parent.parent / "uix"
TESTS_DIR = Path(__file__).parent


def check_node_available():
    """Check if Node.js is available."""
    try:
        subprocess.run(
            ["node", "--version"],
            capture_output=True,
            check=True,
            timeout=5,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return False


def check_jsdom_available():
    """Check if jsdom is available."""
    try:
        result = subprocess.run(
            ["node", "-e", "require('jsdom')"],
            check=False,
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


NODE_AVAILABLE = check_node_available()
JSDOM_AVAILABLE = NODE_AVAILABLE and check_jsdom_available()

requires_jsdom = pytest.mark.skipif(
    not JSDOM_AVAILABLE,
    reason="Node.js and jsdom required for JS execution tests",
)


def run_math_test(configurator: str, test_type: str, field_values: dict) -> dict:
    """Run a test using the math runner which supports all configurators."""
    runner_path = TESTS_DIR / "uix_math_runner.js"
    if not runner_path.exists():
        pytest.skip("uix_math_runner.js not found")

    result = subprocess.run(
        ["node", str(runner_path), configurator, test_type, json.dumps(field_values)],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
        cwd=str(TESTS_DIR),
    )
    if result.returncode != 0:
        pytest.fail(f"Math runner failed: {result.stderr}")
    return json.loads(result.stdout)


class TestGraphPolicyStructure:
    """Test that graph policy controls are correctly placed in HTML structure."""

    @pytest.fixture
    def portfolio_mv_html(self) -> str:
        """Return portfolio MV HTML content."""
        return (UIX_DIR / "experiment_portfolio_mv.html").read_text()

    @pytest.fixture
    def portfolio_sr_html(self) -> str:
        """Return portfolio SR HTML content."""
        return (UIX_DIR / "experiment_portfolio_sr.html").read_text()

    @pytest.fixture
    def facility_location_html(self) -> str:
        """Return facility location HTML content."""
        return (UIX_DIR / "experiment_facility_location.html").read_text()

    def test_portfolio_mv_graph_policy_in_reduction_tab(self, portfolio_mv_html: str) -> None:
        """Test that graphPolicyCard is inside the reduction section in Portfolio MV."""
        # Find reduction section start
        reduction_start = portfolio_mv_html.find('id="reduction"')
        assert reduction_start != -1, "Reduction section not found"

        # Find graphPolicyCard
        graph_policy_pos = portfolio_mv_html.find('id="graphPolicyCard"')
        assert graph_policy_pos != -1, "graphPolicyCard not found"

        # Find next section after reduction
        reduction_end = portfolio_mv_html.find('id="solver"', reduction_start)
        assert reduction_end != -1, "Solver section not found"

        # Graph policy should be between reduction start and solver section
        assert reduction_start < graph_policy_pos < reduction_end, (
            "graphPolicyCard is not inside the Reduction tab"
        )

    def test_portfolio_sr_graph_policy_in_reduction_tab(self, portfolio_sr_html: str) -> None:
        """Test that graphPolicyCard is inside the reduction section in Portfolio SR."""
        reduction_start = portfolio_sr_html.find('id="reduction"')
        assert reduction_start != -1, "Reduction section not found"

        graph_policy_pos = portfolio_sr_html.find('id="graphPolicyCard"')
        assert graph_policy_pos != -1, "graphPolicyCard not found"

        # Find next section after reduction
        reduction_end = portfolio_sr_html.find('id="solver"', reduction_start)
        assert reduction_end != -1, "Solver section not found"

        assert reduction_start < graph_policy_pos < reduction_end, (
            "graphPolicyCard is not inside the Reduction tab"
        )

    def test_facility_location_graph_policy_in_reduction_tab(
        self, facility_location_html: str
    ) -> None:
        """Test that graphPolicyCard is inside the reduction section in Facility Location."""
        reduction_start = facility_location_html.find('id="reduction"')
        assert reduction_start != -1, "Reduction section not found"

        graph_policy_pos = facility_location_html.find('id="graphPolicyCard"')
        assert graph_policy_pos != -1, "graphPolicyCard not found"

        # Find next section after reduction
        reduction_end = facility_location_html.find('id="solvers"', reduction_start)
        assert reduction_end != -1, "Solvers section not found"

        assert reduction_start < graph_policy_pos < reduction_end, (
            "graphPolicyCard is not inside the Reduction tab"
        )

    def test_facility_location_no_graph_policy_tab(self, facility_location_html: str) -> None:
        """Test that Facility Location does not have a dedicated Graph Policy tab."""
        # Check that there's no tab button for graph policy
        assert 'data-tab="graph"' not in facility_location_html, (
            "Facility Location should not have a Graph Policy tab button"
        )

        # Check that there's no tab-content with id="graph"
        assert 'class="tab-content" id="graph"' not in facility_location_html, (
            "Facility Location should not have a Graph Policy tab content section"
        )

    def test_portfolio_mv_has_graph_baseline_note(self, portfolio_mv_html: str) -> None:
        """Test that Portfolio MV has the baseline note element."""
        assert 'id="graphBaselineNote"' in portfolio_mv_html

    def test_portfolio_sr_has_graph_baseline_note(self, portfolio_sr_html: str) -> None:
        """Test that Portfolio SR has the baseline note element."""
        assert 'id="graphBaselineNote"' in portfolio_sr_html

    def test_facility_location_has_graph_baseline_note(
        self, facility_location_html: str
    ) -> None:
        """Test that Facility Location has the baseline note element."""
        assert 'id="graphBaselineNote"' in facility_location_html

    def test_facility_location_section_balance(self, facility_location_html: str) -> None:
        """Test that Facility Location has balanced section tags."""
        open_count = facility_location_html.count("<section")
        close_count = facility_location_html.count("</section>")
        assert open_count == close_count, (
            f"Unbalanced section tags: {open_count} opens, {close_count} closes"
        )

    def test_no_duplicate_ids_portfolio_mv(self, portfolio_mv_html: str) -> None:
        """Test that Portfolio MV has no duplicate element IDs."""
        import re

        ids = re.findall(r'id="([^"]+)"', portfolio_mv_html)
        duplicates = [id_ for id_ in ids if ids.count(id_) > 1]
        assert not duplicates, f"Duplicate IDs found: {set(duplicates)}"

    def test_no_duplicate_ids_portfolio_sr(self, portfolio_sr_html: str) -> None:
        """Test that Portfolio SR has no duplicate element IDs."""
        import re

        ids = re.findall(r'id="([^"]+)"', portfolio_sr_html)
        duplicates = [id_ for id_ in ids if ids.count(id_) > 1]
        assert not duplicates, f"Duplicate IDs found: {set(duplicates)}"

    def test_no_duplicate_ids_facility_location(self, facility_location_html: str) -> None:
        """Test that Facility Location has no duplicate element IDs."""
        import re

        ids = re.findall(r'id="([^"]+)"', facility_location_html)
        duplicates = [id_ for id_ in ids if ids.count(id_) > 1]
        assert not duplicates, f"Duplicate IDs found: {set(duplicates)}"

    def test_all_tab_buttons_have_targets_portfolio_mv(self, portfolio_mv_html: str) -> None:
        """Test that all tab buttons in Portfolio MV have corresponding sections."""
        import re

        tab_targets = re.findall(r'data-tab="([^"]+)"', portfolio_mv_html)
        for target in tab_targets:
            assert f'id="{target}"' in portfolio_mv_html, (
                f"Tab button target '{target}' has no corresponding section"
            )

    def test_all_tab_buttons_have_targets_portfolio_sr(self, portfolio_sr_html: str) -> None:
        """Test that all tab buttons in Portfolio SR have corresponding sections."""
        import re

        tab_targets = re.findall(r'data-tab="([^"]+)"', portfolio_sr_html)
        for target in tab_targets:
            assert f'id="{target}"' in portfolio_sr_html, (
                f"Tab button target '{target}' has no corresponding section"
            )

    def test_all_tab_buttons_have_targets_facility_location(
        self, facility_location_html: str
    ) -> None:
        """Test that all tab buttons in Facility Location have corresponding sections."""
        import re

        tab_targets = re.findall(r'data-tab="([^"]+)"', facility_location_html)
        for target in tab_targets:
            assert f'id="{target}"' in facility_location_html, (
                f"Tab button target '{target}' has no corresponding section"
            )


@requires_jsdom
class TestPortfolioSRToleranceValidation:
    """Test Portfolio SR tolerance validation for near_duplicate mode."""

    def test_negative_return_diff_rejected(self) -> None:
        """Test that negative returnDiff is rejected when reduction and near_duplicate active."""
        result = run_math_test("portfolio_sr", "update_values", {
            "runId": "test001",
            "maxRounds": "1",
            "edgeMode": "near_duplicate",
            "returnDiff": "-1",
        })
        assert result["valid"] is False

    def test_negative_variance_diff_rejected(self) -> None:
        """Test that negative varianceDiff is rejected."""
        result = run_math_test("portfolio_sr", "update_values", {
            "runId": "test001",
            "maxRounds": "1",
            "edgeMode": "near_duplicate",
            "varianceDiff": "-0.5",
        })
        assert result["valid"] is False

    def test_empty_return_diff_rejected(self) -> None:
        """Test that empty returnDiff is rejected."""
        result = run_math_test("portfolio_sr", "update_values", {
            "runId": "test001",
            "maxRounds": "1",
            "edgeMode": "near_duplicate",
            "returnDiff": "",
        })
        assert result["valid"] is False

    def test_valid_tolerances_accepted(self) -> None:
        """Test that valid tolerance values are accepted."""
        result = run_math_test("portfolio_sr", "update_values", {
            "runId": "test001",
            "maxRounds": "1",
            "edgeMode": "near_duplicate",
            "returnDiff": "0.15",
            "varianceDiff": "0.15",
        })
        assert result["valid"] is True

    def test_tolerances_ignored_in_baseline(self) -> None:
        """Test that invalid tolerances are ignored in baseline mode."""
        result = run_math_test("portfolio_sr", "update_values", {
            "runId": "test001",
            "maxRounds": "0",
            "edgeMode": "near_duplicate",
            "returnDiff": "-1",
            "varianceDiff": "-1",
        })
        assert result["valid"] is True
        # Tolerances should not appear in command in baseline
        assert "--near-duplicate-max-return-diff" not in result["command"]

    def test_tolerances_ignored_in_correlation_only(self) -> None:
        """Test that invalid tolerances are ignored in correlation_only mode."""
        result = run_math_test("portfolio_sr", "update_values", {
            "runId": "test001",
            "maxRounds": "1",
            "edgeMode": "correlation_only",
            "returnDiff": "-1",
            "varianceDiff": "-1",
        })
        assert result["valid"] is True
        # Tolerances should not appear in command in correlation_only
        assert "--near-duplicate-max-return-diff" not in result["command"]


@requires_jsdom
class TestModeTransitions:
    """Test mode transitions preserve and re-validate values."""

    @staticmethod
    def run_steps(configurator: str, steps: list[dict]) -> list[dict]:
        """Apply every step to the same page, not separate DOM instances."""
        result = subprocess.run(
            ["node", str(TESTS_DIR / "uix_transition_runner.js"), configurator, json.dumps(steps)],
            capture_output=True, text=True, timeout=15, check=True, cwd=TESTS_DIR,
        )
        data = json.loads(result.stdout)
        assert data["success"], data
        return data["steps"]

    @pytest.mark.parametrize("configurator,rounds,field,flag", [
        ("portfolio", "maxRounds", "correlationThreshold", "--correlation-threshold"),
        ("portfolio_sr", "maxRounds", "correlationThreshold", "--correlation-threshold"),
        ("facility_location", "rounds", "epsilon", "--epsilon"),
    ])
    def test_baseline_roundtrip(self, configurator, rounds, field, flag) -> None:
        """Preserve invalid values, ignore in baseline, and revalidate on return."""
        steps = self.run_steps(configurator, [
            {"set": {"runId": "test001", rounds: "1", field: "2"},
             "verify": {field: {"value": "2", "disabled": False}}},
            {"set": {rounds: "0"}, "verify": {field: {"value": "2", "disabled": True}}},
            {"set": {rounds: "1"}, "verify": {field: {"value": "2", "disabled": False}}},
            {"set": {field: "0.7"}},
            {"set": {rounds: "0"}},
            {"set": {rounds: "1"}, "verify": {field: {"value": "0.7", "disabled": False}}},
            {"action": "reset"},
        ])
        assert [step["copyDisabled"] for step in steps] == [True, False, True, False, False, False, False]
        for index in (1, 4, 6):
            assert flag not in steps[index]["command"]
        for index in (3, 5):
            assert f"{flag} 0.7" in steps[index]["command"]

    @pytest.mark.parametrize("configurator,field,flag", [
        ("portfolio", "returnDifference", "--near-duplicate-max-relative-return-difference"),
        ("portfolio", "varianceDifference", "--near-duplicate-max-relative-variance-difference"),
        ("portfolio_sr", "returnDiff", "--near-duplicate-max-return-diff"),
        ("portfolio_sr", "varianceDiff", "--near-duplicate-max-variance-diff"),
    ])
    def test_edge_mode_roundtrip(self, configurator, field, flag) -> None:
        """Ignore inactive tolerances without losing their values or validation."""
        steps = self.run_steps(configurator, [
            {"set": {"runId": "test001", "maxRounds": "1", "edgeMode": "near_duplicate", field: "-1"}},
            {"set": {"edgeMode": "correlation_only"},
             "verify": {field: {"value": "-1", "disabled": True}}},
            {"set": {"edgeMode": "near_duplicate"},
             "verify": {field: {"value": "-1", "disabled": False}}},
            {"set": {field: "0.3"}},
            {"set": {"edgeMode": "correlation_only"}},
            {"set": {"edgeMode": "near_duplicate"},
             "verify": {field: {"value": "0.3", "disabled": False}}},
        ])
        assert [step["copyDisabled"] for step in steps] == [True, False, True, False, False, False]
        assert flag not in steps[1]["command"]
        assert flag not in steps[4]["command"]
        assert f"{flag} 0.3" in steps[3]["command"]
        assert f"{flag} 0.3" in steps[5]["command"]


@requires_jsdom
@pytest.mark.parametrize("value,rounds,valid", [("-1", "1", False), ("-1", "0", True), ("0.3", "1", True)])
def test_generic_runner_portfolio_sr(value, rounds, valid):
    """The generic runner must initialize SR and report actual validation state."""
    from test_uix_js_execution import run_js_generator

    result = run_js_generator("portfolio_sr", {
        "runId": "test001", "maxRounds": rounds, "returnDiff": value,
    })
    assert result["isValid"] is valid
    if valid and rounds == "1":
        assert "--near-duplicate-max-return-diff 0.3" in result["command"]
    elif rounds == "0":
        assert "--near-duplicate-max-return-diff" not in result["command"]
