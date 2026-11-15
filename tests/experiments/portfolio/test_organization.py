"""Structural checks for the internal portfolio experiment package."""

import ast
import importlib
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from qreduce.experiments.portfolio import classical, multi_round, single_pass
from qreduce.experiments.portfolio.inputs import build_synthetic_portfolio_inputs


@pytest.mark.parametrize("name", ["models", "adapter", "postcheck", "generator", "inputs", "analysis"])
def test_portfolio_modules_import(name):
    assert importlib.import_module(f"qreduce.experiments.portfolio.{name}")


@pytest.mark.parametrize("name", ["single_pass", "multi_round", "classical"])
def test_portfolio_cli_help(name):
    completed = subprocess.run(
        [sys.executable, "-m", f"qreduce.experiments.portfolio.{name}", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "--run-id" in completed.stdout


def test_all_modes_use_shared_input_factory():
    assert classical.build_synthetic_portfolio_inputs is build_synthetic_portfolio_inputs
    assert multi_round.build_synthetic_portfolio_inputs is build_synthetic_portfolio_inputs
    assert single_pass.build_synthetic_portfolio_inputs is build_synthetic_portfolio_inputs


@pytest.mark.parametrize(
    ("module", "function"),
    [
        (classical, "run_portfolio_classical_experiment"),
        (multi_round, "run_portfolio_multi_round_experiment"),
        (single_pass, "run_synthetic_portfolio_experiment"),
    ],
)
def test_portfolio_output_root_default_and_override(module, function, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    seen = []
    monkeypatch.setattr(module, "run_experiment", lambda *args, **kwargs: seen.append(kwargs["output_root"]))
    run = getattr(module, function)
    run("default", asset_count=6)
    run("override", asset_count=6, output_root="custom")
    assert seen == ["outputs/portfolio", "custom"]


@pytest.mark.parametrize(
    ("module", "function"),
    [
        (classical, "run_portfolio_classical_experiment"),
        (multi_round, "run_portfolio_multi_round_experiment"),
        (single_pass, "run_synthetic_portfolio_experiment"),
    ],
)
@pytest.mark.parametrize("override", [None, "custom"])
def test_portfolio_cli_output_root(module, function, override, monkeypatch):
    seen = []
    monkeypatch.setattr(
        module, function,
        lambda *args, **kwargs: seen.append(kwargs["output_root"]) or SimpleNamespace(run_directory="run"),
    )
    argv = ["experiment", "--run-id", "test", "--asset-count", "6"]
    if override is not None:
        argv += ["--output-root", override]
    monkeypatch.setattr(sys, "argv", argv)
    module._main()
    assert seen == [override or "outputs/portfolio"]


def test_portfolio_notebooks_use_family_directory():
    root = Path(__file__).resolve().parents[3]
    notebooks = sorted((root / "notebooks/experiments/portfolio").glob("*.ipynb"))
    assert len(notebooks) == 4
    for notebook in notebooks:
        content = json.loads(notebook.read_text(encoding="utf-8"))
        sources = "\n".join("".join(cell["source"]) for cell in content["cells"])
        assert 'repository_root / "outputs/portfolio/' in sources
        assert "--output-root outputs " not in sources


@pytest.mark.parametrize("name", ["__init__.py", "runner.py", "artifacts.py"])
def test_common_infrastructure_does_not_import_portfolio(name):
    experiments = Path(__file__).resolve().parents[3] / "src/qreduce/experiments"
    tree = ast.parse((experiments / name).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(not alias.name.startswith("qreduce.experiments.portfolio") for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert not (node.module or "").startswith("qreduce.experiments.portfolio")