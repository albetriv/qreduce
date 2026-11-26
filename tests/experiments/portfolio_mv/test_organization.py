"""Structural checks for the internal portfolio experiment package."""

import ast
import importlib
import json
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from qreduce.experiments.portfolio_mv import execution
from qreduce.experiments.portfolio_mv.inputs import build_synthetic_portfolio_inputs


@pytest.mark.parametrize("name", ["models", "adapter", "postcheck", "generator", "inputs", "analysis", "execution"])
def test_portfolio_modules_import(name):
    assert importlib.import_module(f"qreduce.experiments.portfolio_mv.{name}")


@pytest.mark.parametrize("document", ["README.md", "portfolio-mv.md", "portfolio-sr.md"])
def test_experiment_documentation_local_links_exist(document):
    root = Path(__file__).resolve().parents[3]
    path = root / "docs/experiments" / document
    for target in re.findall(r"\]\(([^)]+)\)", path.read_text(encoding="utf-8")):
        if "://" not in target and not target.startswith("#"):
            assert (path.parent / target.split("#")[0]).exists(), f"{path}: broken link {target}"


def test_portfolio_documentation_has_required_sections():
    root = Path(__file__).resolve().parents[3]
    content = (root / "docs/experiments/portfolio-mv.md").read_text(encoding="utf-8")
    assert "## 2. Formulazione matematica" in content
    assert "## 3. CLI unificata" in content
    assert "## 4. Parametri" in content


def test_portfolio_unified_cli_help():
    """The unified CLI entry point provides help."""
    completed = subprocess.run(
        [sys.executable, "-m", "qreduce.experiments.portfolio_mv", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "--run-id" in completed.stdout
    assert "--max-reduction-rounds" in completed.stdout


@pytest.mark.parametrize("value", [None, "2.5", "0.0001", "2.55"])
def test_cli_risk_aversion_reaches_execution(monkeypatch, value):
    from qreduce.experiments.portfolio_mv import __main__ as cli

    seen = []
    monkeypatch.setattr(cli, "configure_logging", lambda *args: "configured")
    monkeypatch.setattr(cli, "run_portfolio_experiment", lambda *args, **kwargs: (
        seen.append(kwargs) or SimpleNamespace(run_directory="run")
    ))
    argv = ["portfolio_mv", "--run-id", "risk-test"]
    if value is not None:
        argv.extend(["--risk-aversion", value])
    monkeypatch.setattr(sys, "argv", argv)
    assert cli.main() == 0
    assert seen[0]["risk_aversion"] == (1.0 if value is None else float(value))


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf", "-inf", "invalid"])
def test_invalid_cli_risk_aversion_never_starts_experiment(monkeypatch, value):
    from qreduce.experiments.portfolio_mv import __main__ as cli

    def unexpected_run(*args, **kwargs):
        pytest.fail("Invalid input must not start an experiment")

    monkeypatch.setattr(cli, "run_portfolio_experiment", unexpected_run)
    monkeypatch.setattr(sys, "argv", ["portfolio_mv", "--run-id", "invalid", f"--risk-aversion={value}"])
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 2


def test_unified_api_uses_shared_input_factory():
    """The unified execution module uses the shared input factory."""
    assert execution.build_synthetic_portfolio_inputs is build_synthetic_portfolio_inputs


def test_portfolio_output_root_default_and_override(monkeypatch, tmp_path):
    """The unified API respects output_root default and override."""
    monkeypatch.chdir(tmp_path)
    seen = []
    monkeypatch.setattr(execution, "run_experiment", lambda *args, **kwargs: seen.append(kwargs["output_root"]))
    execution.run_portfolio_experiment("default", asset_count=6)
    execution.run_portfolio_experiment("override", asset_count=6, output_root="custom")
    assert seen == ["outputs/portfolio_mv", "custom"]


def test_portfolio_cli_output_root(monkeypatch):
    """The CLI passes output_root correctly."""
    from qreduce.experiments.portfolio_mv import __main__ as cli_module

    seen = []

    def capture_run(*args, **kwargs):
        seen.append(kwargs.get("output_root"))
        return SimpleNamespace(run_directory="run")

    monkeypatch.setattr(cli_module, "run_portfolio_experiment", capture_run)
    argv = ["experiment", "--run-id", "test", "--asset-count", "6"]
    monkeypatch.setattr(sys, "argv", argv)
    cli_module.main()
    assert seen == ["outputs/portfolio_mv"]

    seen.clear()
    argv = ["experiment", "--run-id", "test", "--asset-count", "6", "--output-root", "custom"]
    monkeypatch.setattr(sys, "argv", argv)
    cli_module.main()
    assert seen == ["custom"]


def test_portfolio_notebooks_use_family_directory():
    root = Path(__file__).resolve().parents[3]
    notebooks = sorted((root / "notebooks/experiments/portfolio_mv").glob("*.ipynb"))
    assert len(notebooks) == 4
    for notebook in notebooks:
        content = json.loads(notebook.read_text(encoding="utf-8"))
        sources = "\n".join("".join(cell["source"]) for cell in content["cells"])
        assert 'repository_root / "outputs/portfolio_mv/' in sources
        assert "--output-root outputs " not in sources


@pytest.mark.parametrize("name", ["__init__.py", "runner.py", "artifacts.py"])
def test_common_infrastructure_does_not_import_portfolio(name):
    experiments = Path(__file__).resolve().parents[3] / "src/qreduce/experiments"
    tree = ast.parse((experiments / name).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(not alias.name.startswith("qreduce.experiments.portfolio_mv") for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert not (node.module or "").startswith("qreduce.experiments.portfolio_mv")


def test_unified_cli_max_reduction_rounds_options(monkeypatch):
    """The CLI builds correct reduction policy based on --max-reduction-rounds."""
    from qreduce.experiments.portfolio_mv import __main__ as cli_module

    captured_policies = []

    def capture_policy(*args, **kwargs):
        captured_policies.append(kwargs.get("reduction_policy"))
        return SimpleNamespace(run_directory="run")

    monkeypatch.setattr(cli_module, "run_portfolio_experiment", capture_policy)

    # Default (single-pass) - no explicit reduction_policy when using defaults
    argv = ["experiment", "--run-id", "default", "--asset-count", "6"]
    monkeypatch.setattr(sys, "argv", argv)
    cli_module.main()
    assert captured_policies[-1] is None  # Uses default from inputs builder

    # Classical-only
    argv = ["experiment", "--run-id", "classical", "--asset-count", "6", "--max-reduction-rounds", "0"]
    monkeypatch.setattr(sys, "argv", argv)
    cli_module.main()
    policy = captured_policies[-1]
    assert policy is not None
    assert policy.max_reduction_rounds == 0

    # Multi-round
    argv = ["experiment", "--run-id", "multi", "--asset-count", "6", "--max-reduction-rounds", "5"]
    monkeypatch.setattr(sys, "argv", argv)
    cli_module.main()
    policy = captured_policies[-1]
    assert policy is not None
    assert policy.max_reduction_rounds == 5


def test_old_wrappers_removed():
    """The old wrapper modules have been removed."""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("qreduce.experiments.portfolio_mv.classical")
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("qreduce.experiments.portfolio_mv.single_pass")
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("qreduce.experiments.portfolio_mv.multi_round")


def test_cli_recovery_policy_uses_valid_values(monkeypatch):
    """The CLI accepts retry_with_larger_domain for recovery policies."""
    from qreduce.experiments.portfolio_mv import __main__ as cli_module

    captured_policies = []

    def capture_policy(*args, **kwargs):
        captured_policies.append(kwargs.get("reduction_policy"))
        return SimpleNamespace(run_directory="run")

    monkeypatch.setattr(cli_module, "run_portfolio_experiment", capture_policy)

    argv = [
        "experiment",
        "--run-id", "recovery-test",
        "--asset-count", "6",
        "--max-reduction-rounds", "3",
        "--recovery-policy-on-infeasible", "retry_with_larger_domain",
        "--max-recovery-attempts", "2",
    ]
    monkeypatch.setattr(sys, "argv", argv)
    cli_module.main()

    policy = captured_policies[-1]
    assert policy is not None
    assert policy.recovery_policy_on_infeasible == "retry_with_larger_domain"
    assert policy.max_recovery_attempts == 2


@pytest.mark.parametrize(
    ("arg_name", "arg_value", "expected_field", "expected_value"),
    [
        ("--min-reduction-ratio", "0", "min_reduction_ratio", 0.0),
        ("--candidate-domain-min-items", "0", "candidate_domain_min_items", 0),
        ("--target-binary-variables", "0", "target_binary_variables", 0),
        ("--max-recovery-attempts", "0", "max_recovery_attempts", 0),
    ],
)
def test_cli_zero_values_are_preserved(monkeypatch, arg_name, arg_value, expected_field, expected_value):
    """Zero values passed via CLI are preserved, not replaced with defaults."""
    from qreduce.experiments.portfolio_mv import __main__ as cli_module

    captured_policies = []

    def capture_policy(*args, **kwargs):
        captured_policies.append(kwargs.get("reduction_policy"))
        return SimpleNamespace(run_directory="run")

    monkeypatch.setattr(cli_module, "run_portfolio_experiment", capture_policy)

    argv = ["experiment", "--run-id", "zero-test", "--asset-count", "6", arg_name, arg_value]
    monkeypatch.setattr(sys, "argv", argv)
    cli_module.main()

    policy = captured_policies[-1]
    assert policy is not None
    assert getattr(policy, expected_field) == expected_value


def test_cli_recovery_policy_passes_real_validator(monkeypatch, tmp_path):
    """Recovery policy built by CLI passes the actual configuration validator."""
    from qreduce.config import validate_resolved_run_config
    from qreduce.experiments.portfolio_mv import __main__ as cli_module
    from qreduce.experiments.portfolio_mv.inputs import build_synthetic_portfolio_inputs

    captured_policies = []

    def capture_policy(*args, **kwargs):
        captured_policies.append(kwargs.get("reduction_policy"))
        return SimpleNamespace(run_directory=str(tmp_path / "run"))

    monkeypatch.setattr(cli_module, "run_portfolio_experiment", capture_policy)

    argv = [
        "experiment",
        "--run-id", "validator-test",
        "--asset-count", "6",
        "--max-reduction-rounds", "3",
        "--recovery-policy-on-infeasible", "retry_with_larger_domain",
        "--recovery-policy-on-domain-too-small", "retry_with_larger_domain",
        "--max-recovery-attempts", "2",
    ]
    monkeypatch.setattr(sys, "argv", argv)
    cli_module.main()

    policy = captured_policies[-1]
    assert policy is not None

    # Build a full config with this policy and validate it
    inputs = build_synthetic_portfolio_inputs("_test", asset_count=6)
    from dataclasses import replace
    config = replace(inputs.config, reduction=policy)
    result = validate_resolved_run_config(config)
    assert result.is_valid, f"Validation failed: {[i.message for i in result.issues]}"


def test_cli_zero_budget_is_accepted_as_unlimited(monkeypatch, tmp_path):
    """A zero runtime budget passed via CLI is accepted as unlimited (no time limit)."""
    from qreduce.config import validate_resolved_run_config
    from qreduce.experiments.portfolio_mv import __main__ as cli_module
    from qreduce.experiments.portfolio_mv.inputs import build_synthetic_portfolio_inputs

    captured_policies = []

    def capture_policy(*args, **kwargs):
        captured_policies.append(kwargs.get("reduction_policy"))
        return SimpleNamespace(run_directory=str(tmp_path / "run"))

    monkeypatch.setattr(cli_module, "run_portfolio_experiment", capture_policy)

    argv = [
        "experiment",
        "--run-id", "zero-budget-test",
        "--asset-count", "6",
        "--max-end-to-end-runtime-seconds", "0",
    ]
    monkeypatch.setattr(sys, "argv", argv)
    cli_module.main()

    policy = captured_policies[-1]
    assert policy is not None
    assert policy.max_end_to_end_runtime_seconds == 0.0

    # Build a full config with this policy and validate it
    inputs = build_synthetic_portfolio_inputs("_test", asset_count=6)
    from dataclasses import replace
    config = replace(inputs.config, reduction=policy)
    result = validate_resolved_run_config(config)
    # Zero budget should now be accepted (means unlimited)
    assert result.is_valid, f"Zero budget should be accepted as unlimited: {result.issues}"
