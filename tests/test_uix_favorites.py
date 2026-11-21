"""Verify favorite commands using the actual UIX JavaScript and DOM."""

import json
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize("family", ["portfolio_mv", "portfolio_sr", "facility_location"])
def test_favorites_lifecycle(family):
    """Exercise storage, restore, import/export and error paths per configurator."""
    runner = Path(__file__).with_name("uix_favorites_runner.js")
    try:
        result = subprocess.run(
            ["node", str(runner), family], capture_output=True, text=True, timeout=30,
            check=False,
        )
    except FileNotFoundError:
        pytest.skip("Node.js not available")
    if "Cannot find module 'jsdom'" in result.stderr:
        pytest.skip("jsdom not installed (run: npm install)")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"family": family, "success": True}