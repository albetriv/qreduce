"""Integration tests for experiment CLI command logging."""

import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest
import yaml


@pytest.mark.parametrize("experiment", ["portfolio_mv", "portfolio_sr", "facility_location.run"])
def test_experiment_cli_logs_python_invocation(tmp_path, monkeypatch, experiment):
    pytest.importorskip("pyscipopt")
    repo_root = Path(__file__).resolve().parents[2]
    monkeypatch.setenv("PYTHONPATH", str(repo_root / "src"), prepend=os.pathsep)

    config = yaml.safe_load((repo_root / "config/logging.yaml").read_text(encoding="utf-8"))
    config["handlers"]["file"]["filename"] = "run.log"
    log_config = tmp_path / "logging config.yaml"
    log_config.write_text(yaml.safe_dump(config), encoding="utf-8")

    if experiment == "facility_location.run":
        instance = tmp_path / "instance with spaces.txt"
        instance.write_text("3 1 5 0 5 0 5 0 8 0 0 0", encoding="ascii")
        experiment_args = [str(instance), "--rounds", "0"]
    elif experiment == "portfolio_sr":
        experiment_args = [
            "--csv-path", str(repo_root / "data/yahoo/SP500.csv"),
            "--asset-count=6", "--start-date", "2020-01-02", "--end-date", "2020-04-30",
            "--max-reduction-rounds", "0",
        ]
    else:
        experiment_args = ["--asset-count=6", "--max-reduction-rounds", "0"]

    output_root = tmp_path / "run output"
    command = [
        sys.executable, "-B", "-m", f"qreduce.experiments.{experiment}",
        "--run-id", "log-test", "--output-root", str(output_root),
        "--log-config", str(log_config), *experiment_args,
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)

    assert result.returncode == 0, result.stderr
    assert (output_root / "log-test" / "run_manifest.json").is_file()
    marker = "Experiment command line: "
    assert marker not in result.stderr
    log_lines = (tmp_path / "run.log").read_text(encoding="utf-8").splitlines()
    (line,) = [line for line in log_lines if marker in line]
    assert "[log-test:-:experiment_cli:-]" in line
    assert shlex.split(line.split(marker, 1)[1]) == command