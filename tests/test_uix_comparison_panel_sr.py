"""Integration test for the SR comparison panel over file URLs."""

import subprocess
from pathlib import Path

import pytest


def test_sr_comparison_panel_file_url():
    runner = Path(__file__).with_name("uix_comparison_panel_sr_runner.js")
    try:
        result = subprocess.run(
            ["node", str(runner)], capture_output=True, text=True, encoding="utf-8",
            timeout=30, check=False,
        )
    except FileNotFoundError:
        pytest.skip("Node.js not available")
    if "Cannot find module 'jsdom'" in result.stderr:
        pytest.skip("jsdom not installed (run: npm install)")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "sr panel ok"