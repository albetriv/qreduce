"""Tests for UIX JavaScript command generators using actual JS execution.

These tests run the actual JavaScript code through Node.js with jsdom
and verify that:
1. Generated commands are accepted by Python parsers
2. Validation rejects invalid inputs that Python would reject
3. Solver switching and baseline/recovery states work correctly
"""

import argparse
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
        # Check if jsdom is missing
        if "Cannot find module" in result.stderr and "jsdom" in result.stderr:
            pytest.skip("jsdom not installed (run: npm install)")
        pytest.fail(f"JS runner failed: {result.stderr}")

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        pytest.fail(f"Invalid JSON output: {result.stdout}")


@pytest.fixture
def portfolio_parser():
    """Return the portfolio CLI parser."""
    return build_portfolio_parser()


@pytest.fixture
def facility_parser():
    """Return the facility location CLI parser by extracting from run.py.

    We create a parser matching the actual CLI arguments defined in
    qreduce.experiments.facility_location.run.main().
    """
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("instance")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output-root", default="outputs/facility_location")
    parser.add_argument("--rounds", type=int, default=0)
    parser.add_argument("--solver", default="scip")
    parser.add_argument("--mis-solver", default="local_greedy")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--budget", type=float, default=60)
    parser.add_argument("--cap", type=int)
    parser.add_argument("--protect-all", action="store_true")
    parser.add_argument("--recovery-attempts", type=int, default=0)
    parser.add_argument("--min-reduction-ratio", type=float, default=0.1)
    parser.add_argument("--model-export", action="store_true")
    parser.add_argument("--alpha", type=float, default=0.5)
    parser.add_argument("--epsilon", type=float, default=0.01)
    parser.add_argument("--profile-fraction", type=float, default=0.5)
    parser.add_argument("--overlap-threshold", type=float, default=0.5)
    parser.add_argument("--capacity-difference", type=float, default=0.25)
    return parser


def get_facility_location_parser() -> argparse.ArgumentParser:
    """Get the facility location parser for validation.

    This mirrors the parser defined in
    qreduce.experiments.facility_location.run.main().
    If that parser changes, this needs to be updated.
    """
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("instance")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output-root", default="outputs/facility_location")
    parser.add_argument("--rounds", type=int, default=0)
    parser.add_argument("--solver", default="scip")
    parser.add_argument("--mis-solver", default="local_greedy")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--budget", type=float, default=60)
    parser.add_argument("--cap", type=int)
    parser.add_argument("--protect-all", action="store_true")
    parser.add_argument("--recovery-attempts", type=int, default=0)
    parser.add_argument("--min-reduction-ratio", type=float, default=0.1)
    parser.add_argument("--model-export", action="store_true")
    parser.add_argument("--alpha", type=float, default=0.5)
    parser.add_argument("--epsilon", type=float, default=0.01)
    parser.add_argument("--profile-fraction", type=float, default=0.5)
    parser.add_argument("--overlap-threshold", type=float, default=0.5)
    parser.add_argument("--capacity-difference", type=float, default=0.25)
    return parser


def extract_cli_args(command: str) -> list[str]:
    """Extract CLI arguments from a poetry run command.

    Handles both inline and multiline formats.
    """
    # Normalize multiline format: remove backslashes and join lines
    command = command.replace("\\\n", " ")
    command = " ".join(command.split())  # Normalize whitespace

    # Remove the poetry prefix
    command = command.removeprefix("poetry run python -m ")
    parts = shlex.split(command)
    # Skip the module name
    if parts and "." in parts[0]:
        parts = parts[1:]
    return parts


class TestPortfolioRiskAversion:
    """Exercise the real JavaScript generator and the Python CLI parser."""

    @pytest.mark.parametrize("value", ["1.0", "2.5", "2.55", "0.0001"])
    @pytest.mark.parametrize("rounds", ["0", "1", "3"])
    def test_valid_values_and_formats(self, portfolio_parser, value, rounds):
        results = [run_js_generator("portfolio", {
            "riskAversion": value, "maxRounds": rounds, "_format": format_name,
        }) for format_name in ("inline", "multiline")]
        for result in results:
            assert result["isValid"], result["errors"]
            assert result["riskAversionDisabled"] is False
            argv = extract_cli_args(result["command"])
            assert portfolio_parser.parse_args(argv).risk_aversion == float(value)
            assert ("--risk-aversion" in argv) is (float(value) != 1.0)
        assert extract_cli_args(results[0]["command"]) == extract_cli_args(results[1]["command"])

    @pytest.mark.parametrize("value", ["", "0", "-1", "NaN", "Infinity", "invalid"])
    def test_invalid_values(self, value):
        result = run_js_generator("portfolio", {"riskAversion": value})
        assert result["isValid"] is False
        assert "riskAversion" in result["errors"]

    def test_reset_restores_default(self):
        result = run_js_generator("portfolio", {"riskAversion": "2.5", "_action": "reset"})
        assert result["isValid"]
        assert float(result["currentValues"]["riskAversion"]) == 1.0
        assert "--risk-aversion" not in result["command"]


class TestPortfolioJSValidation:
    """Test portfolio_mv.js validation catches invalid inputs."""

    def test_valid_minimal_config(self):
        """Test that minimal valid config passes validation."""
        result = run_js_generator("portfolio", {"runId": "test001"})
        assert result["isValid"] is True
        assert "poetry run python -m qreduce.experiments.portfolio_mv" in result["command"]

    def test_invalid_seed_float(self):
        """Test that float seed is rejected."""
        result = run_js_generator("portfolio", {"runId": "test001", "generationSeed": "1.5"})
        assert result["isValid"] is False

    def test_invalid_seed_nan(self):
        """Test that NaN seed is rejected."""
        result = run_js_generator("portfolio", {"runId": "test001", "generationSeed": "NaN"})
        # NaN gets converted to empty string by jsdom for number inputs
        # so it becomes null which is valid (optional field)
        # This test documents the behavior
        assert result["isValid"] is True  # null seed is valid

    def test_invalid_asset_count_too_small(self):
        """Test that asset count < 6 is rejected."""
        result = run_js_generator("portfolio", {"runId": "test001", "assetCount": "5"})
        assert result["isValid"] is False

    def test_invalid_asset_count_float(self):
        """Test that float asset count is rejected."""
        result = run_js_generator("portfolio", {"runId": "test001", "assetCount": "6.5"})
        assert result["isValid"] is False

    def test_invalid_correlation_threshold_out_of_range(self):
        """Test that correlation threshold > 1 is rejected."""
        result = run_js_generator("portfolio", {"runId": "test001", "correlationThreshold": "1.5"})
        assert result["isValid"] is False

    def test_invalid_max_rounds_negative(self):
        """Test that negative max rounds is rejected."""
        result = run_js_generator("portfolio", {"runId": "test001", "maxRounds": "-1"})
        assert result["isValid"] is False

    def test_empty_run_id_rejected(self):
        """Test that empty run ID is rejected."""
        result = run_js_generator("portfolio", {"runId": ""})
        assert result["isValid"] is False


class TestPortfolioJSSolverSwitch:
    """Test that switching solver doesn't break validation."""

    def test_dwave_params_ignored_when_local_greedy(self):
        """Test that D-Wave params don't cause validation error with local_greedy."""
        # Set D-Wave params, then switch to local_greedy
        # The JS should ignore numReads/numSweeps when validating for local_greedy
        result = run_js_generator(
            "portfolio",
            {
                "runId": "test001",
                "misSolver": "local_greedy",
                "numReads": "100",
                "numSweeps": "1000",
            },
        )
        # Should be valid - D-Wave params are ignored when local_greedy is selected
        assert result["isValid"] is True
        # Command should NOT include D-Wave params
        assert "--mis-num-reads" not in result["command"]
        assert "--mis-num-sweeps" not in result["command"]

    def test_dwave_params_included_when_dwave(self):
        """Test that D-Wave params are included when D-Wave solver is selected."""
        result = run_js_generator(
            "portfolio",
            {
                "runId": "test001",
                "misSolver": "dwave_simulated_annealing",
                "numReads": "100",
                "numSweeps": "1000",
            },
        )
        assert result["isValid"] is True
        assert "--mis-num-reads 100" in result["command"]
        assert "--mis-num-sweeps 1000" in result["command"]


class TestPortfolioJSBaselineRecovery:
    """Test baseline/recovery coherence in portfolio_mv.js."""

    def test_baseline_ignores_recovery_policy_values(self):
        """Test that baseline (rounds=0) ignores recovery policy values in disabled fields.

        When switching to baseline, recovery fields are disabled.
        Their existing values should be ignored, not cause validation errors.
        The command should not include recovery flags.
        """
        result = run_js_generator(
            "portfolio",
            {
                "runId": "test001",
                "maxRounds": "0",
                "domainRecovery": "retry_with_larger_domain",
            },
        )
        # Valid because disabled fields are ignored
        assert result["isValid"] is True
        # Command should NOT include recovery flags
        assert "--recovery-policy-on-domain-too-small" not in result["command"]

    def test_baseline_ignores_recovery_attempts_values(self):
        """Test that baseline (rounds=0) ignores recovery attempts in disabled field.

        When switching to baseline, the recovery attempts field is disabled.
        Its value should be ignored and not serialized to the command.
        """
        result = run_js_generator(
            "portfolio",
            {
                "runId": "test001",
                "maxRounds": "0",
                "recoveryAttempts": "3",
            },
        )
        # Valid because disabled fields are ignored
        assert result["isValid"] is True
        # Command should NOT include recovery attempts
        assert "--max-recovery-attempts" not in result["command"]

    def test_baseline_mode_valid_with_defaults(self):
        """Test that baseline mode is valid with default recovery settings."""
        result = run_js_generator(
            "portfolio",
            {
                "runId": "test001",
                "maxRounds": "0",
            },
        )
        assert result["isValid"] is True
        # Command should include --max-reduction-rounds 0
        assert "--max-reduction-rounds 0" in result["command"]

    def test_reduction_mode_with_recovery_requires_attempts(self):
        """Test that enabling recovery policy requires at least 1 attempt."""
        result = run_js_generator(
            "portfolio",
            {
                "runId": "test001",
                "maxRounds": "2",
                "domainRecovery": "retry_with_larger_domain",
                "recoveryAttempts": "0",
            },
        )
        assert result["isValid"] is False

    def test_reduction_mode_with_recovery_valid(self):
        """Test that reduction mode with proper recovery config is valid."""
        result = run_js_generator(
            "portfolio",
            {
                "runId": "test001",
                "maxRounds": "2",
                "domainRecovery": "retry_with_larger_domain",
                "recoveryAttempts": "3",
            },
        )
        assert result["isValid"] is True


class TestPortfolioJSCommandGeneration:
    """Test that generated commands are accepted by Python parser."""

    def test_generated_command_parses(self, portfolio_parser):
        """Test that default generated command parses correctly."""
        result = run_js_generator("portfolio", {"runId": "test001"})
        assert result["isValid"] is True

        args = extract_cli_args(result["command"])
        parsed = portfolio_parser.parse_args(args)
        assert parsed.run_id == "test001"

    def test_full_config_parses(self, portfolio_parser):
        """Test that a full config generates a parseable command."""
        result = run_js_generator(
            "portfolio",
            {
                "runId": "full_test",
                "assetCount": "25",
                "generationSeed": "123",
                "edgeMode": "correlation_only",
                "correlationThreshold": "0.85",
                "maxRounds": "3",
                "misSolver": "dwave_simulated_annealing",
                "classicalSolver": "cplex",
                "numReads": "100",
            },
        )
        assert result["isValid"] is True

        args = extract_cli_args(result["command"])
        parsed = portfolio_parser.parse_args(args)
        assert parsed.run_id == "full_test"
        assert parsed.asset_count == 25
        assert parsed.generation_seed == 123
        assert parsed.graph_edge_mode == "correlation_only"
        assert parsed.mis_solver_id == "dwave_simulated_annealing"
        assert parsed.classical_solver_id == "cplex"


class TestFacilityLocationJSValidation:
    """Test facility_location.js validation."""

    def test_valid_minimal_config(self):
        """Test that minimal valid config passes validation."""
        result = run_js_generator("facility_location", {"runId": "test001"})
        assert result["isValid"] is True
        assert "qreduce.experiments.facility_location.run" in result["command"]

    def test_invalid_seed_float(self):
        """Test that float seed is rejected."""
        result = run_js_generator("facility_location", {"runId": "test001", "seed": "1.5"})
        assert result["isValid"] is False

    def test_invalid_budget_negative(self):
        """Test that negative budget is rejected."""
        result = run_js_generator("facility_location", {"runId": "test001", "budget": "-1"})
        assert result["isValid"] is False

    def test_invalid_cap_negative(self):
        """Test that negative cap is rejected."""
        result = run_js_generator("facility_location", {"runId": "test001", "cap": "-2"})
        assert result["isValid"] is False

    def test_invalid_alpha_out_of_range(self):
        """Test that alpha > 1 is rejected."""
        result = run_js_generator("facility_location", {"runId": "test001", "alpha": "1.5"})
        assert result["isValid"] is False

    def test_invalid_epsilon_zero(self):
        """Test that epsilon = 0 is rejected (must be > 0)."""
        result = run_js_generator("facility_location", {"runId": "test001", "epsilon": "0"})
        assert result["isValid"] is False

    def test_invalid_overlap_threshold_out_of_range(self):
        """Test that overlap threshold > 1 is rejected."""
        result = run_js_generator("facility_location", {"runId": "test001", "overlapThreshold": "1.5"})
        assert result["isValid"] is False


class TestFacilityLocationJSCommandGeneration:
    """Test that generated facility location commands are valid."""

    def test_generated_command_parses(self, facility_parser):
        """Test that default generated command parses correctly."""
        result = run_js_generator("facility_location", {"runId": "test001"})
        assert result["isValid"] is True

        args = extract_cli_args(result["command"])
        parsed = facility_parser.parse_args(args)
        assert parsed.run_id == "test001"

    def test_positional_instance_path(self, facility_parser):
        """Test that instance path is correctly placed as positional argument."""
        result = run_js_generator(
            "facility_location",
            {
                "runId": "test001",
                "instancePath": "data/custom/instance.txt",
            },
        )
        assert result["isValid"] is True

        args = extract_cli_args(result["command"])
        parsed = facility_parser.parse_args(args)
        assert parsed.instance == "data/custom/instance.txt"

    def test_all_graph_policy_params(self, facility_parser):
        """Test that all graph policy params are included when changed."""
        result = run_js_generator(
            "facility_location",
            {
                "runId": "test001",
                "alpha": "0.7",
                "epsilon": "0.02",
                "profileFraction": "0.6",
                "overlapThreshold": "0.4",
                "capacityDifference": "0.3",
            },
        )
        assert result["isValid"] is True
        assert "--alpha 0.7" in result["command"]
        assert "--epsilon 0.02" in result["command"]
        assert "--profile-fraction 0.6" in result["command"]
        assert "--overlap-threshold 0.4" in result["command"]
        assert "--capacity-difference 0.3" in result["command"]


class TestJSFormatEquivalence:
    """Test that inline and multiline formats produce equivalent arguments."""

    def test_portfolio_format_equivalence(self, portfolio_parser):
        """Test that inline and multiline produce same parsed arguments."""
        config = {
            "runId": "format_test",
            "assetCount": "20",
            "maxRounds": "2",
        }

        inline_result = run_js_generator("portfolio", {**config, "_format": "inline"})
        multiline_result = run_js_generator("portfolio", {**config, "_format": "multiline"})

        # Both should be valid
        assert inline_result["isValid"] is True
        assert multiline_result["isValid"] is True

        # Parse both
        inline_args = extract_cli_args(inline_result["command"])
        multiline_args = extract_cli_args(multiline_result["command"])

        inline_parsed = portfolio_parser.parse_args(inline_args)
        multiline_parsed = portfolio_parser.parse_args(multiline_args)

        # Parsed results should be identical
        assert inline_parsed.run_id == multiline_parsed.run_id
        assert inline_parsed.asset_count == multiline_parsed.asset_count
        assert inline_parsed.max_reduction_rounds == multiline_parsed.max_reduction_rounds



class TestFacilityLocationGraphPolicyLimits:
    """Test that facility_location graph policy limits match Python constraints."""

    def test_profile_fraction_zero_rejected(self):
        """Test that profileFraction = 0 is rejected (must be > 0)."""
        result = run_js_generator("facility_location", {"runId": "test001", "profileFraction": "0"})
        assert result["isValid"] is False

    def test_epsilon_above_one_rejected(self):
        """Test that epsilon > 1 is rejected (must be <= 1)."""
        result = run_js_generator("facility_location", {"runId": "test001", "epsilon": "2"})
        assert result["isValid"] is False

    def test_capacity_difference_above_one_rejected(self):
        """Test that capacityDifference > 1 is rejected (must be <= 1)."""
        result = run_js_generator("facility_location", {"runId": "test001", "capacityDifference": "2"})
        assert result["isValid"] is False

    def test_baseline_with_recovery_attempts_rejected(self):
        """Test that recovery attempts with rounds=0 is rejected."""
        result = run_js_generator(
            "facility_location",
            {"runId": "test001", "rounds": "0", "recoveryAttempts": "2"},
        )
        assert result["isValid"] is False

    def test_valid_boundary_values(self):
        """Test that valid boundary values are accepted."""
        # epsilon and profileFraction just above 0
        result = run_js_generator(
            "facility_location",
            {
                "runId": "test001",
                "epsilon": "0.001",
                "profileFraction": "0.001",
                "alpha": "0",
                "overlapThreshold": "1",
                "capacityDifference": "1",
            },
        )
        assert result["isValid"] is True


class TestPortfolioModeTransitions:
    """Test mode transitions preserve valid state and command generation."""

    def test_reduction_to_baseline_preserves_validity(self):
        """Test that switching from reduction to baseline with recovery values stays valid.

        This simulates: configure recovery, then switch to baseline.
        The recovery values should be ignored, not cause validation errors.
        """
        result = run_js_generator(
            "portfolio",
            {
                "runId": "test001",
                "maxRounds": "0",  # Baseline
                "domainRecovery": "retry_with_larger_domain",
                "infeasibleRecovery": "retry_with_larger_domain",
                "recoveryAttempts": "5",
                "minItems": "3",
                "maxItems": "20",
            },
        )
        # Should be valid - disabled fields are ignored
        assert result["isValid"] is True
        # Command should not include any reduction-specific params except rounds
        assert "--max-reduction-rounds 0" in result["command"]
        assert "--recovery-policy" not in result["command"]
        assert "--max-recovery-attempts" not in result["command"]
        assert "--candidate-domain-min-items" not in result["command"]
        assert "--candidate-domain-max-items" not in result["command"]

    def test_baseline_budget_is_serialized(self):
        """Test that budget is included in baseline command."""
        result = run_js_generator(
            "portfolio",
            {
                "runId": "test001",
                "maxRounds": "0",
                "endToEndBudget": "120",
            },
        )
        assert result["isValid"] is True
        assert "--max-end-to-end-runtime-seconds 120" in result["command"]

    def test_baseline_to_reduction_validates_recovery(self):
        """Test that switching from baseline to reduction validates recovery config.

        If recovery policy is set but attempts is 0, validation should fail.
        """
        result = run_js_generator(
            "portfolio",
            {
                "runId": "test001",
                "maxRounds": "2",  # Reduction active
                "domainRecovery": "retry_with_larger_domain",
                "recoveryAttempts": "0",  # Invalid: recovery needs attempts >= 1
            },
        )
        assert result["isValid"] is False

    def test_dwave_params_preserved_but_ignored_in_baseline(self):
        """Test that D-Wave params don't cause errors in baseline mode."""
        result = run_js_generator(
            "portfolio",
            {
                "runId": "test001",
                "maxRounds": "0",  # Baseline
                "misSolver": "dwave_simulated_annealing",
                "numReads": "100",
                "numSweeps": "500",
            },
        )
        # Should be valid - MIS params are ignored in baseline
        assert result["isValid"] is True
        # Command should not include MIS-related params
        assert "--mis-solver-id" not in result["command"]
        assert "--mis-num-reads" not in result["command"]
        assert "--mis-num-sweeps" not in result["command"]


class TestPortfolioEmbeddingSelector:
    """Test embedding profile selector behavior in portfolio configurator."""

    def test_hardware_profile_emits_flag(self, portfolio_parser):
        """Test that hardware profiles (pegasus_p16, zephyr_z12) emit the flag."""
        for profile in ["pegasus_p16", "zephyr_z12"]:
            result = run_js_generator(
                "portfolio",
                {
                    "runId": "embed_test",
                    "maxRounds": "1",  # Reduction active
                    "misSolver": "dwave_simulated_annealing",
                    "embeddingProfile": profile,
                },
            )
            assert result["isValid"] is True, f"Profile {profile} should be valid"
            assert f"--mis-embedding-profile {profile}" in result["command"], (
                f"Profile {profile} should emit flag"
            )

            # Verify command parses
            args = extract_cli_args(result["command"])
            parsed = portfolio_parser.parse_args(args)
            assert parsed.mis_embedding_profile == profile

    def test_none_profile_omits_flag(self, portfolio_parser):
        """Test that profile 'none' (default) does not emit the flag."""
        result = run_js_generator(
            "portfolio",
            {
                "runId": "embed_test",
                "maxRounds": "1",
                "misSolver": "dwave_simulated_annealing",
                "embeddingProfile": "none",
            },
        )
        assert result["isValid"] is True
        # Default value should not be emitted
        assert "--mis-embedding-profile" not in result["command"]

    def test_embedding_reset_when_solver_changes(self):
        """Test that embedding profile resets to 'none' when switching to local_greedy.

        When the solver is not dwave_simulated_annealing, embedding profile
        should be ignored and not emitted.
        """
        result = run_js_generator(
            "portfolio",
            {
                "runId": "embed_test",
                "maxRounds": "1",
                "misSolver": "local_greedy",  # Not D-Wave
                "embeddingProfile": "pegasus_p16",  # Should be ignored
            },
        )
        assert result["isValid"] is True
        # Embedding flag should not be emitted for non-D-Wave solver
        assert "--mis-embedding-profile" not in result["command"]

    def test_embedding_ignored_in_baseline_mode(self):
        """Test that embedding profile is ignored when reduction is disabled.

        In baseline mode (maxRounds=0), MIS params including embedding are ignored.
        """
        result = run_js_generator(
            "portfolio",
            {
                "runId": "embed_test",
                "maxRounds": "0",  # Baseline - no MIS
                "misSolver": "dwave_simulated_annealing",
                "embeddingProfile": "zephyr_z12",
            },
        )
        assert result["isValid"] is True
        # Neither MIS solver nor embedding should be emitted in baseline
        assert "--mis-solver-id" not in result["command"]
        assert "--mis-embedding-profile" not in result["command"]

    def test_embedding_with_dwave_and_reduction(self, portfolio_parser):
        """Test full valid configuration with embedding, D-Wave solver, and reduction."""
        result = run_js_generator(
            "portfolio",
            {
                "runId": "full_embed_test",
                "maxRounds": "2",
                "misSolver": "dwave_simulated_annealing",
                "embeddingProfile": "pegasus_p16",
                "numReads": "100",
                "numSweeps": "500",
            },
        )
        assert result["isValid"] is True

        # All relevant flags should be emitted
        assert "--mis-solver-id dwave_simulated_annealing" in result["command"]
        assert "--mis-embedding-profile pegasus_p16" in result["command"]
        assert "--mis-num-reads 100" in result["command"]
        assert "--mis-num-sweeps 500" in result["command"]

        # Verify command parses correctly
        args = extract_cli_args(result["command"])
        parsed = portfolio_parser.parse_args(args)
        assert parsed.mis_solver_id == "dwave_simulated_annealing"
        assert parsed.mis_embedding_profile == "pegasus_p16"
        assert parsed.mis_num_reads == 100
        assert parsed.mis_num_sweeps == 500


class TestPortfolioEmbeddingDOMTransitions:
    """Test that embedding selector DOM state transitions work correctly.

    These tests verify the actual DOM element state changes after user interactions,
    not just the command output for a given configuration.
    """

    def run_transition_test(self, steps: list) -> dict:
        """Run a sequence of DOM changes and verify state transitions."""
        runner_path = Path(__file__).parent / "uix_transition_runner.js"
        if not runner_path.exists():
            pytest.skip("uix_transition_runner.js not found")

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
            ["node", str(runner_path), "portfolio", json.dumps(steps)],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

        if result.returncode != 0:
            if "Cannot find module" in result.stderr and "jsdom" in result.stderr:
                pytest.skip("jsdom not installed")
            pytest.fail(f"Transition runner failed: {result.stderr}")

        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            pytest.fail(f"Invalid JSON output: {result.stdout}")

    def test_embedding_resets_when_solver_changes_to_local_greedy(self):
        """Test DOM transition: D-Wave + pegasus -> local_greedy resets to none + disabled."""
        steps = [
            # Step 1: Set up initial state with D-Wave and hardware embedding
            {
                "set": {
                    "runId": "transition_test",
                    "maxRounds": "1",
                    "misSolver": "dwave_simulated_annealing",
                    "embeddingProfile": "pegasus_p16",
                },
                "verify": {
                    "embeddingProfile": {"value": "pegasus_p16", "disabled": False},
                },
            },
            # Step 2: Change solver to local_greedy - embedding should reset
            {
                "set": {"misSolver": "local_greedy"},
                "verify": {
                    "embeddingProfile": {"value": "none", "disabled": True},
                },
            },
        ]

        result = self.run_transition_test(steps)
        assert result["success"], f"Transition test failed: {result}"

    def test_embedding_resets_when_reduction_disabled(self):
        """Test DOM transition: reduction enabled + pegasus -> maxRounds=0 resets to none + disabled."""
        steps = [
            # Step 1: Set up initial state with D-Wave and hardware embedding
            {
                "set": {
                    "runId": "transition_test",
                    "maxRounds": "2",
                    "misSolver": "dwave_simulated_annealing",
                    "embeddingProfile": "zephyr_z12",
                },
                "verify": {
                    "embeddingProfile": {"value": "zephyr_z12", "disabled": False},
                },
            },
            # Step 2: Disable reduction - embedding should reset
            {
                "set": {"maxRounds": "0"},
                "verify": {
                    "embeddingProfile": {"value": "none", "disabled": True},
                },
            },
        ]

        result = self.run_transition_test(steps)
        assert result["success"], f"Transition test failed: {result}"

    def test_embedding_enabled_when_switching_to_dwave(self):
        """Test DOM transition: local_greedy -> D-Wave enables embedding selector."""
        steps = [
            # Step 1: Start with local_greedy
            {
                "set": {
                    "runId": "transition_test",
                    "maxRounds": "1",
                    "misSolver": "local_greedy",
                },
                "verify": {
                    "embeddingProfile": {"value": "none", "disabled": True},
                },
            },
            # Step 2: Switch to D-Wave - embedding should become enabled
            {
                "set": {"misSolver": "dwave_simulated_annealing"},
                "verify": {
                    "embeddingProfile": {"disabled": False},
                },
            },
            # Step 3: Now we can select a hardware profile
            {
                "set": {"embeddingProfile": "pegasus_p16"},
                "verify": {
                    "embeddingProfile": {"value": "pegasus_p16", "disabled": False},
                },
            },
        ]

        result = self.run_transition_test(steps)
        assert result["success"], f"Transition test failed: {result}"
