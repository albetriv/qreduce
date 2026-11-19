"""Execute the real command generator and validate it with the real CLI parser."""

import json
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

from qreduce.experiments.portfolio_sr.__main__ import _build_parser


@pytest.mark.parametrize("fields", [
    {},
    {"csvPath": "/data/prices with spaces.csv", "maxRounds": "0", "classicalTimeout": "0",
     "maxPositions": "2", "modelExport": True, "modelExportPath": "/data/model export.lp"},
    {"misSolver": "dwave_simulated_annealing", "misNumReads": "100", "misNumSweeps": "200"},
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
  selectionOrder:'alphabetical', edgeMode:'near_duplicate', recoveryInfeasible:'fail',
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
    args = _build_parser().parse_args(tokens[tokens.index("qreduce.experiments.portfolio_sr") + 1:])
    assert args.run_id == "ui-test"
    if "csvPath" in fields:
        assert str(args.csv_path) == fields["csvPath"]
        assert args.max_reduction_rounds == 0
        assert args.classical_time_limit_seconds == 0
        assert args.max_positions == 2
        assert args.model_export
        assert str(args.model_export_path) == fields["modelExportPath"]
    if "misNumReads" in fields:
        assert args.mis_num_reads == 100
        assert args.mis_num_sweeps == 200