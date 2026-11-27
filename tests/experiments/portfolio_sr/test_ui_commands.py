"""Execute the real command generator and validate it with the real CLI parser."""

import json
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from qreduce.experiments.portfolio_sr.__main__ import _build_parser, _validate_args


@pytest.mark.parametrize("fields", [
    {},
    {"csvPath": "/data/prices with spaces.csv", "maxRounds": "0", "classicalTimeout": "0",
     "minSelectedAssets": "1", "maxPositions": "2", "modelExport": True,
     "modelExportPath": "/data/model export.lp"},
    {"misSolver": "dwave_simulated_annealing", "misNumReads": "100", "misNumSweeps": "200"},
    {"lowerBound": "0.05"},
])
def test_actual_generator_preserves_cli_values(fields):
    if shutil.which("node") is None:
        pytest.skip("Node.js is not available")
    root = Path(__file__).resolve().parents[3]
    # A minimal DOM exercises generateCommand without jsdom or browser/network side effects.
    script = r'''
const fs = require('fs'), vm = require('vm');
const html = fs.readFileSync(process.argv[1], 'utf8');
const elements = {};
for (const match of html.matchAll(/<(input|select|textarea)\b([^>]*)>/g)) {
  const id = match[2].match(/id="([^"]+)"/);
  if (id) elements[id[1]] = {value: (match[2].match(/value="([^"]*)"/) || [])[1] || '', checked: false};
}
for (const [id, value] of Object.entries({runId:'ui-test', returnConvention:'log',
  selectionMode:'count', selectionOrder:'alphabetical', edgeMode:'near_duplicate', recoveryInfeasible:'fail', recoveryDomainTooSmall:'fail',
  misSolver:'local_greedy', classicalSolver:'scip'})) elements[id] = {value};
for (const [id, value] of Object.entries(JSON.parse(process.argv[3]))) {
  elements[id] = typeof value === 'boolean' ? {checked:value} : {value:String(value)};
}
const context = {document: {
  getElementById(id) { return elements[id] || {value:'', checked:false}; },
  addEventListener() {}, querySelector() { return null; }
}};
context.window = context;
vm.createContext(context);
vm.runInContext(fs.readFileSync(process.argv[2], 'utf8'), context);
for (const match of html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/g)) {
  if (match[1].trim()) vm.runInContext(match[1], context);
}
console.log(JSON.stringify(vm.runInContext('generateCommand()', context)));
'''
    completed = subprocess.run(
        ["node", "-e", script, str(root / "uix/experiment_portfolio_sr.html"),
         str(root / "uix/assets/common.js"), json.dumps(fields)],
        check=True, capture_output=True, text=True, timeout=10,
    )
    command = json.loads(completed.stdout)
    tokens = shlex.split(command.replace("\\\n", " "))
    parser = _build_parser()
    args = parser.parse_args(tokens[tokens.index("qreduce.experiments.portfolio_sr") + 1:])
    if "maxPositions" in fields:
        assert "--max-selected-assets" in tokens
        assert "--max-positions" not in tokens
    _validate_args(parser, args)
    assert args.run_id == "ui-test"
    if "lowerBound" in fields:
        assert args.lower_bound == 0.05
    if "csvPath" in fields:
        assert str(args.csv_path) == fields["csvPath"]
        assert args.max_reduction_rounds == 0
        assert args.classical_time_limit_seconds == 0
        assert args.min_selected_assets == 1
        assert args.max_positions == 2
        assert args.model_export
        assert str(args.model_export_path) == fields["modelExportPath"]
    if "misNumReads" in fields:
        assert args.mis_num_reads == 100
        assert args.mis_num_sweeps == 200


def run_ui(fields):
    """Execute the real configurator with jsdom."""
    runner = Path(__file__).resolve().parents[2] / "uix_js_runner.js"
    try:
        result = subprocess.run(
            ["node", str(runner), "portfolio_sr", json.dumps(fields)],
            capture_output=True, text=True, timeout=15, check=False,
        )
    except FileNotFoundError:
        pytest.skip("Node.js is not available")
    if "Cannot find module 'jsdom'" in result.stderr:
        pytest.skip("jsdom is not installed")
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.mark.parametrize("tickers", ["AAPL,,MSFT", ",AAPL", "AAPL,", "AAPL,AAPL"])
def test_invalid_ticker_list_blocks_copy(tickers):
    result = run_ui({"selectionMode": "explicit", "explicitTickers": tickers})
    assert result["copyDisabled"]
    assert result["errors"]["explicitTickers"]


def test_explicit_tickers_and_exponent_values_reach_cli():
    result = run_ui({
        "selectionMode": "explicit", "explicitTickers": " AAPL , MSFT ",
        "maxPositions": "2", "targetBinary": "1e1", "numSourceMisCandidates": "1e1",
    })
    assert not result["copyDisabled"], result
    tokens = shlex.split(result["command"])
    parser = _build_parser()
    args = parser.parse_args(tokens[tokens.index("qreduce.experiments.portfolio_sr") + 1:])
    _validate_args(parser, args)
    assert args.explicit_tickers == "AAPL,MSFT"
    assert args.asset_count is None
    assert args.target_binary_variables == 10
    assert args.num_source_mis_candidates == 10


def test_inactive_target_and_recovery_are_ignored():
    result = run_ui({
        "maxPositions": "", "targetBinary": "-1", "maxRounds": "0",
        "recoveryDomainTooSmall": "retry_with_larger_domain", "maxRecovery": "0",
    })
    assert not result["copyDisabled"], result
    assert "--target-binary-variables" not in result["command"]
    assert "--recovery-policy-on-domain-too-small" not in result["command"]


@pytest.mark.parametrize("upper", ["0", "-0.2", "1e999"])
def test_upper_bound_requires_positive_finite_value(upper):
    result = run_ui({"runId": "upper-bound", "upperBound": upper})
    assert result["copyDisabled"]
    assert "upperBound" in result["errors"]


def test_generated_commands_solve_and_compare_full_and_reduced_models(tmp_path):
    pytest.importorskip("pyscipopt")
    root = Path(__file__).resolve().parents[3]
    prices = tmp_path / "prices.csv"
    rows = ["Societa;Ticker Yahoo;Settore;Data;Open;High;Low;Close;Volume;Adjusted Close;Currency"]
    trajectories = {
        "AAA": (100, 101, 103, 104, 108, 107),
        "BBB": (100, 103, 102, 106, 107, 109),
        "CCC": (100, 101, 104, 106, 105, 110),
        "DDD": (100, 104, 103, 107, 106, 111),
    }
    for index, (ticker, values) in enumerate(trajectories.items()):
        sector = "Technology" if index < 2 else "Health Care"
        for day, price in enumerate(values, 1):
            rows.append(f"{ticker};{ticker};{sector};{day:02}/01/2020;{price};{price};{price};{price};100;{price};USD")
    prices.write_text("\n".join(rows) + "\n", encoding="utf-8")
    for name, rounds in (("baseline", 0), ("reduced", 1)):
        generated = run_ui({
            "runId": name, "csvPath": str(prices), "outputRoot": str(tmp_path),
            "selectionMode": "explicit", "explicitTickers": ",".join(trajectories),
            "lowerBound": "0.1", "upperBound": "1.2", "minSelectedAssets": "2", "maxPositions": "3",
            "sectorMin": "Technology=0.2,Health Care=0.2", "sectorMax": "Technology=0.7",
            "maxRounds": str(rounds), "misSolver": "local_greedy", "maxItems": "3", "minItems": "3",
            "edgeMode": "correlation_only", "correlationThreshold": "1", "modelExport": True,
        })
        assert not generated["copyDisabled"], generated
        tokens = shlex.split(generated["command"].replace("\\\n", " "))
        completed = subprocess.run(
            [sys.executable, "-m", *tokens[tokens.index("qreduce.experiments.portfolio_sr"):]],
            cwd=root, capture_output=True, text=True, timeout=20, check=False,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr
        directory = tmp_path / name
        problem = json.loads((directory / "problem.json").read_text())
        result = json.loads((directory / "run_result.json").read_text())
        assert set(problem["upper_bounds"].values()) == {1.2}
        assert (problem["lower_bound"], problem["min_selected_assets"], problem["max_positions"]) == (0.1, 2, 3)
        assert problem["sector_constraints"]["sector_max"] == {"Technology": 0.7, "Health Care": 1.0}
        assert result["postcheck_result"]["postcheck_feasible"]
        retained = result["final_retained_item_ids"]
        assert len(retained) == (3 if rounds else 4)
        values = result["classical_result"]["variable_values"]
        for ticker in set(trajectories) - set(retained):
            assert values[f"x_scaled__{ticker}"] == pytest.approx(0)
            assert values[f"delta__{ticker}"] == pytest.approx(0)
        weights = {ticker: values[f"x_scaled__{ticker}"] / values["x_scale"] for ticker in trajectories}
        assert sum(weights.values()) == pytest.approx(1, abs=1e-6)
        assert 0.2 - 1e-6 <= weights["AAA"] + weights["BBB"] <= 0.7 + 1e-6
        for ticker, weight in weights.items():
            assert weight >= (0.1 if values[f"delta__{ticker}"] > 0.5 else 0) - 1e-6

    comparison = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {importRunSharpe, adaptSharpePortfolio, compareRuns} = require(process.argv[1]);
async function load(name) {
  const dir = path.join(process.argv[2], name);
  const files = Object.fromEntries(fs.readdirSync(dir).filter(f => f.endsWith('.json'))
    .map(f => [f, fs.readFileSync(path.join(dir, f))]));
  return adaptSharpePortfolio(await importRunSharpe(files));
}
(async () => {
  const [full, reduced] = await Promise.all([load('baseline'), load('reduced')]);
  for (const run of [full, reduced]) {
    assert.deepEqual(run.issues, []);
    assert.ok(run.solution?.sharpeRatio > 0);
    assert.ok(run.solution.selectedCount >= 2 && run.solution.selectedCount <= 3);
    assert.equal(run.solution.selectedCount, run.solution.investedCount);
  }
  assert.equal(full.solver.scope, 'full');
  assert.equal(reduced.solver.scope, 'reduced');
  const report = compareRuns(full, reduced);
  assert.equal(report.sameInstance, true);
  assert.equal(report.objective.comparable, true);
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
    completed = subprocess.run(
        ["node", "-e", comparison, str(root / "uix/assets/comparison.js"), str(tmp_path)],
        capture_output=True, text=True, timeout=15, check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr