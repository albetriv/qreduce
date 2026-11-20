"""Check shared label styles without claiming browser geometry coverage."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("configurator", ["portfolio_mv", "portfolio_sr", "facility_location"])
def test_shared_label_layout(configurator: str) -> None:
    """Keep flags stacked, switch labels untouched and mobile icons anchored."""
    if shutil.which("node") is None:
        pytest.skip("Node.js not available")

    script = r"""
const { JSDOM } = require('jsdom');
const fs = require('fs');
const html = fs.readFileSync(process.argv[1], 'utf8');
const css = fs.readFileSync(process.argv[2], 'utf8');
const dom = new JSDOM(html);
const document = dom.window.document;
const style = document.createElement('style');
style.textContent = css;
document.head.appendChild(style);
const labels = [...document.querySelectorAll('.field > label')];
const flags = [...document.querySelectorAll('label .param')];
const switches = [...document.querySelectorAll('label.switch')];
const computed = element => dom.window.getComputedStyle(element);
const mobileRules = [...style.sheet.cssRules]
  .filter(rule => rule.conditionText === '(max-width: 680px)')
  .flatMap(rule => [...rule.cssRules]);
console.log(JSON.stringify({
  labelCount: labels.length,
  flagCount: flags.length,
  switchCount: switches.length,
  headings: labels.every(label => computed(label).paddingRight === '26px'),
  flags: flags.every(flag => computed(flag).display === 'block'
    && computed(flag).overflowWrap === 'anywhere'
    && computed(flag).wordBreak !== 'break-all'),
  switches: switches.every(label => !parseFloat(computed(label).paddingRight)),
  gridHeadings: [...document.querySelectorAll('.form-grid > .field > label')]
    .every(label => computed(label).minHeight === '3.9rem'),
  mobileHeightReset: mobileRules.some(rule =>
    rule.selectorText === '.form-grid > .field > label'
    && parseFloat(rule.style.getPropertyValue('min-height')) === 0),
  mobileIconOverride: mobileRules.some(rule =>
    rule.selectorText === '.field > .tooltip-wrapper'),
  unusedHeadingRule: css.includes('.label-text')
}));
dom.window.close();
"""
    result = subprocess.run(
        [
            "node", "-e", script,
            str(ROOT / "uix" / f"experiment_{configurator}.html"),
            str(ROOT / "uix" / "assets" / "common.css"),
        ],
        cwd=ROOT, capture_output=True, text=True, timeout=15, check=False,
    )
    if result.returncode and "Cannot find module 'jsdom'" in result.stderr:
        pytest.skip("jsdom not installed")
    assert result.returncode == 0, result.stderr
    checks = json.loads(result.stdout)
    assert checks["labelCount"] > 0
    assert checks["flagCount"] > 0
    for name in ("headings", "flags", "switches", "gridHeadings", "mobileHeightReset"):
        assert checks[name], f"{configurator}: {name} failed"
    assert not checks["mobileIconOverride"]
    assert not checks["unusedHeadingRule"]