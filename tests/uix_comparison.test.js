const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {importRun, adaptPortfolio, compareRuns} = require('../uix/assets/comparison.js');
const folder = name => { const dir = path.join(__dirname, '../outputs/portfolio_mv', name); return Object.fromEntries(fs.readdirSync(dir).filter(n => n.endsWith('.json')).map(n => [n, fs.readFileSync(path.join(dir, n))])); };
const load = async name => adaptPortfolio(await importRun(folder(name)));

test('contradictory classical evidence and selection block comparison', async () => {
  for (const mutate of [
    f => change(f, 'run_manifest.json', m => m.has_reduction = true),
    f => change(f, 'run_manifest.json', m => m.round_count = 1),
    f => change(f, 'run_result.json', r => r.round_results = [{round_index: 0}]),
    f => change(f, 'run_result.json', r => r.classical_result.variable_values.delta__a = 0)
  ]) {
    const files = synthetic(true); mutate(files);
    const run = adaptPortfolio(await importRun(files));
    assert.equal(run.solution, null);
    assert.equal(compareRuns(run, run).objective.comparable, false);
  }
  const files = synthetic(true);
  change(files, 'run_result.json', r => r.classical_result.variable_values.delta__a = 1);
  assert.ok(adaptPortfolio(await importRun(files)).solution);
});

test('conflicting round decisions suppress exclusion totals and reasons', async () => {
  const a = adaptPortfolio(await importRun(synthetic(true)));
  const b = adaptPortfolio(await importRun(synthetic()));
  b.reduction.rounds = [{index: 0, inputIds: ['a', 'b'], retained: ['a'], reasons: [
    {decision: 'excluded', reason: 'cap', itemIds: ['b']},
    {decision: 'retained', reason: 'selected', itemIds: ['b']}
  ]}];
  const round = compareRuns(a, b).dashboard.rounds[0];
  assert.equal(round.excluded, null);
  assert.deepEqual(round.reasons, []);
});


const localOutputs = ['ptf_100_classic', 'ptf_100_dwave'].every(n => fs.existsSync(path.join(__dirname, '../outputs/portfolio_mv', n, 'run_result.json')));
test('real portfolio fixtures and inversion', {skip: !localOutputs}, async () => {
  const a = await load('ptf_100_classic'), b = await load('ptf_100_dwave');
  const report = compareRuns(a, b);
  assert.equal(report.sameInstance, true);
  assert.deepEqual(report.dashboard.thermometer.budgets, {
    solver: {baseline: {state: 'numeric', seconds: a.timings.budget}, comparison: {state: 'unlimited', seconds: null}},
    pipeline: {baseline: {state: 'numeric', seconds: 60}, comparison: {state: 'unlimited', seconds: null}}
  });
  assert.equal(a.reduction.state, 'not_applicable');
  assert.deepEqual(b.reduction.rounds[0].graph, {nodes: 100, edges: 1123});
  assert.equal(b.reduction.rounds[0].backend.mode, 'local');
  assert.equal(b.retained.length, 38);
  assert.equal(report.baselineExcludedCount, 13);
  assert.deepEqual(report.composition.filter(x => x.status === 'selected_both').map(x => x.id).sort(), ['asset-098', 'asset-099']);
  assert.ok(Math.abs(a.solution.objective + 0.11039653) < 1e-8);
  assert.ok(Math.abs(b.solution.objective + 0.08842327) < 1e-8);
  assert.ok(Math.abs(compareRuns(b, a).objective.delta + report.objective.delta) < 1e-12);
});

test('missing, unsupported, failed and unverified inputs', {skip: !localOutputs}, async () => {
  let partial = adaptPortfolio(await importRun({}));
  assert.equal(partial.solution, null);
  assert.ok(partial.issues.length);
  let files = folder('ptf_100_classic');
  const manifest = JSON.parse(files['run_manifest.json']); manifest.artifact_schema_version = '99';
  files['run_manifest.json'] = JSON.stringify(manifest);
  assert.equal(adaptPortfolio(await importRun(files)).solution, null);
  files = folder('ptf_100_classic');
  const result = JSON.parse(files['run_result.json']); result.postcheck_result.postcheck_feasible = false;
  files['run_result.json'] = JSON.stringify(result);
  assert.equal(adaptPortfolio(await importRun(files)).solution, null);
  files = folder('ptf_100_dwave'); files['problem.json'] = Buffer.concat([files['problem.json'], Buffer.from(' ')]);
  const report = compareRuns(await load('ptf_100_classic'), adaptPortfolio(await importRun(files)));
  assert.equal(report.sameInstance, false); assert.equal(report.objective.delta, null);
});

test('zero baseline and absent reduction trace', {skip: !localOutputs}, async () => {
  const a = await load('ptf_100_classic'), b = await load('ptf_100_dwave');
  a.solution.objective = 0;
  assert.equal(compareRuns(a, b).objective.percent, null);
  const files = folder('ptf_100_dwave'); delete files['round_00_result.json'];
  const result = JSON.parse(files['run_result.json']); result.round_results = [];
  files['run_result.json'] = JSON.stringify(result);
  assert.equal(adaptPortfolio(await importRun(files)).reduction.state, 'not_recorded');
});

function synthetic(classical = false) {
  const entries = {
    'run_manifest.json': {artifact_schema_version: '1.1', experiment_id: 'synthetic-portfolio', run_id: 'run', run_status: 'success', is_classical_only: classical},
    'problem.json': {asset_ids: ['a', 'b'], expected_returns: [0.1, 0.2], covariance: [[0.04, 0], [0, 0.09]]},
    'run_result.json': {objective_sense: 'minimize', postcheck_result: {postcheck_feasible: true, objective_recomputed: -0.1}, classical_result: {variable_values: {x__a: 1, x__b: 0}}, final_retained_item_ids: classical ? null : ['a']},
    'config_used.json': {}, 'experiment_metadata.json': {}
  };
  return Object.fromEntries(Object.entries(entries).map(([k, v]) => [k, JSON.stringify(v)]));
}

test('classical comparison retains the full domain when inverted', async () => {
  const reduced = synthetic(), full = synthetic(true);
  const result = JSON.parse(reduced['run_result.json']);
  result.classical_result.variable_values = {x__a: 0, x__b: 1};
  result.final_retained_item_ids = ['b'];
  reduced['run_result.json'] = JSON.stringify(result);
  const a = adaptPortfolio(await importRun(reduced)), b = adaptPortfolio(await importRun(full));
  const report = compareRuns(a, b);
  assert.equal(report.baselineExcludedCount, 0);
  assert.equal(report.composition.find(x => x.id === 'b').status, 'available_not_selected');
  assert.equal(b.solution.expectedReturn, 0.1);
  assert.equal(b.solution.volatility, 0.2);
});

test('malformed artifacts and round records are handled safely', async () => {
  for (const bad of ['null', '[]', '42', '{']) {
    const files = synthetic(); files['problem.json'] = bad;
    const run = adaptPortfolio(await importRun(files));
    assert.equal(run.solution, null); assert.ok(run.issues.length);
  }
  const files = synthetic();
  const result = JSON.parse(files['run_result.json']);
  result.round_results = [null, {}, {round_index: 0, candidate_domain_item_records: {}, candidate_records: [null]}, {round_index: 0}];
  files['run_result.json'] = JSON.stringify(result);
  const run = adaptPortfolio(await importRun(files));
  assert.deepEqual(run.issues, []);
  assert.equal(run.warnings.filter(w => w.includes('Traccia della riduzione incompleta')).length, 3);
  assert.equal(run.solution.objective, -0.1);
  assert.equal(compareRuns(run, run).objective.comparable, true);
  assert.equal(run.reduction.rounds.length, 1);
  assert.deepEqual(run.reduction.rounds[0].candidates, []);
  assert.equal(run.reduction.rounds[0].reasons, null);
  result.round_results = {};
  files['run_result.json'] = JSON.stringify(result);
  const unavailable = adaptPortfolio(await importRun(files));
  assert.equal(unavailable.solution.objective, -0.1);
  assert.equal(unavailable.reduction.state, 'not_recorded');
  assert.ok(unavailable.warnings.some(w => w.includes('elenco dei round non valido')));
});

test('round artifact supplements nested graph and timing preserves zero', async () => {
  const files = synthetic();
  const result = JSON.parse(files['run_result.json']);
  result.metrics = {end_to_end_runtime_seconds: 0, mis_runtime_seconds: 0};
  result.round_results = [{round_index: 0, mis_compilation_result: {compiled_job: {execution_mode: 'local'}}}];
  files['run_result.json'] = JSON.stringify(result);
  const manifest = JSON.parse(files['run_manifest.json']); manifest.files = {'round_00_result.json': 'declared'};
  files['run_manifest.json'] = JSON.stringify(manifest);
  files['round_00_result.json'] = JSON.stringify({round_index: 0, mis_compilation_result: {compiled_job: {compiled_problem: {graph: {node_ids: ['a', 'b'], edges: []}}}}});
  const run = adaptPortfolio(await importRun(files));
  assert.deepEqual(run.reduction.rounds[0].graph, {nodes: 2, edges: 0});
  assert.equal(run.reduction.rounds[0].backend.mode, 'local');
  assert.equal(run.timings.endToEnd, 0); assert.equal(run.timings.mis, 0);
});


function change(files, name, fn) {
  const value = JSON.parse(files[name]); fn(value); files[name] = JSON.stringify(value);
}

test('identity and domain contradictions block solutions', async () => {
  for (const mutate of [
    f => change(f, 'config_used.json', c => c.run_identity = {run_id: 'other'}),
    f => change(f, 'run_result.json', r => r.run_result = {run_id: 'other'}),
    f => change(f, 'run_result.json', r => r.final_retained_item_ids = ['b']),
    f => change(f, 'run_manifest.json', m => m.fixing_manifest = {retained_item_ids: ['b']}),
    f => change(f, 'run_result.json', r => r.final_retained_item_ids = ['missing'])
  ]) {
    const files = synthetic(); mutate(files);
    const run = adaptPortfolio(await importRun(files));
    assert.equal(run.solution, null); assert.ok(run.issues.length);
  }
});

test('recorded adoption and postcheck contradictions block; missing identities warn', async () => {
  for (const [field, value] of [['adoption_status', 'rejected'], ['postcheck_status', 'failed']]) {
    const files = synthetic();
    change(files, 'run_result.json', r => r.run_result = {[field]: value});
    const run = adaptPortfolio(await importRun(files));
    assert.equal(run.solution, null);
    assert.equal(compareRuns(run, run).objective.comparable, false);
  }
  const run = adaptPortfolio(await importRun(synthetic()));
  assert.ok(run.solution);
  assert.ok(run.warnings.some(x => x.includes('identity not verified')));
});

test('partial success with adopted postchecked solution remains comparable', async () => {
  const files = synthetic();
  change(files, 'run_manifest.json', m => m.run_status = 'partial_success');
  change(files, 'run_result.json', r => { r.run_result = {adoption_status: 'adopted'}; });
  const run = adaptPortfolio(await importRun(files));
  assert.ok(run.solution); assert.equal(run.issues.length, 0); assert.ok(run.warnings.length);
  assert.equal(compareRuns(run, run).objective.comparable, true);
  change(files, 'run_result.json', r => { delete r.run_result.adoption_status; });
  assert.equal(adaptPortfolio(await importRun(files)).solution, null);
  change(files, 'run_result.json', r => r.postcheck_result.postcheck_feasible = false);
  assert.equal(adaptPortfolio(await importRun(files)).solution, null);
});

test('only declared and matching round supplements are used', async () => {
  const files = synthetic();
  change(files, 'run_result.json', r => r.round_results = [{round_index: 0}]);
  files['round_00_result.json'] = JSON.stringify({round_index: 0, terminal_reason: 'extra'});
  let run = adaptPortfolio(await importRun(files));
  assert.equal(run.reduction.rounds[0].terminalReason, null); assert.ok(run.warnings.length);
  change(files, 'run_manifest.json', m => m.files = {'round_00_result.json': 'declared'});
  change(files, 'round_00_result.json', r => r.round_index = 1);
  run = adaptPortfolio(await importRun(files));
  assert.equal(run.reduction.rounds[0].terminalReason, null);
  assert.ok(run.warnings.length); assert.ok(run.solution);
});


test('dashboard round denominators distinguish recorded reasons and missing evidence', async () => {
  const a = adaptPortfolio(await importRun(synthetic(true)));
  const b = adaptPortfolio(await importRun(synthetic()));
  b.reduction.applied = true;
  b.reduction.maxCandidateItems = 1;
  b.reduction.rounds = [{index: 0, inputIds: ['a', 'b', 'c', 'd'], retained: ['a'], graph: {nodes: 4, edges: 2}, reasons: [
    {decision: 'excluded', reason: 'candidate_domain_cap', itemIds: ['b']},
    {decision: 'excluded', reason: 'not_present_in_selected_candidates', itemIds: ['c']}
  ]}];
  let round = compareRuns(a, b).dashboard.rounds[0];
  assert.equal(round.excluded, 3);
  assert.deepEqual(round.reasons.map(x => [x.reason, x.count]), [['candidate_domain_cap', 1], ['not_present_in_selected_candidates', 1], ['undocumented', 1]]);
  assert.ok(Math.abs(round.reasons[0].percent - 100 / 3) < 1e-10);
  b.reduction.rounds[0].inputIds = null;
  round = compareRuns(a, b).dashboard.rounds[0];
  assert.equal(round.excluded, null); assert.equal(round.reasons[0].percent, null);
  b.reduction.rounds[0] = {index: 1, inputIds: ['a'], retained: ['a'], graph: {nodes: 1, edges: 0}, reasons: []};
  round = compareRuns(a, b).dashboard.rounds[0];
  assert.equal(round.excluded, 0); assert.deepEqual(round.reasons, []);
});

test('dashboard budget states preserve source semantics and inversion', async () => {
  const a = adaptPortfolio(await importRun(synthetic(true)));
  const b = adaptPortfolio(await importRun(synthetic()));
  a.timings.budget = 0;
  b.timings.budget = 'unlimited';
  a.config.reduction = {max_end_to_end_runtime_seconds: 0};
  b.config.reduction = {max_end_to_end_runtime_seconds: 12};
  const budgets = compareRuns(a, b).dashboard.thermometer.budgets;
  assert.deepEqual(budgets.solver, {baseline: {state: 'numeric', seconds: 0}, comparison: {state: 'unlimited', seconds: null}});
  assert.deepEqual(budgets.pipeline, {baseline: {state: 'unlimited', seconds: null}, comparison: {state: 'numeric', seconds: 12}});
  assert.deepEqual(compareRuns(b, a).dashboard.thermometer.budgets.solver.baseline, budgets.solver.comparison);
  a.timings.budget = null; b.timings.budget = -1;
  delete a.config.reduction.max_end_to_end_runtime_seconds;
  b.config.reduction.max_end_to_end_runtime_seconds = '60';
  const missing = compareRuns(a, b).dashboard.thermometer.budgets;
  for (const pair of Object.values(missing)) for (const item of Object.values(pair)) {
    assert.deepEqual(item, {state: 'unrecorded', seconds: null});
  }
});

test('dashboard verdict, zero denominators, inversion and unknown domains', async () => {
  const a = adaptPortfolio(await importRun(synthetic(true)));
  const b = adaptPortfolio(await importRun(synthetic()));
  b.reduction.applied = true;
  a.solution.objective = 0; b.solution.objective = 1;
  a.timings.endToEnd = 2; b.timings.endToEnd = 1;
  a.timings.classical = 0; b.timings.classical = 1;
  let report = compareRuns(a, b);
  assert.equal(report.dashboard.verdict.value, 'tradeoff');
  assert.equal(report.dashboard.thermometer.quality.percent, null);
  assert.equal(report.dashboard.thermometer.solverTime.percent, null);
  assert.equal(report.dashboard.thermometer.endToEnd.ratio, 0.5);
  assert.equal(compareRuns(b, a).dashboard.verdict.value, null);
  b.retained = null;
  b.solution.selected = [];
  report = compareRuns(a, b);
  assert.ok(report.dashboard.positions.some(x => x.status === 'domain_unknown' && x.count > 0));
  b.solution = null;
  report = compareRuns(a, b);
  assert.equal(report.dashboard.verdict.value, null);
  assert.ok(report.dashboard.verdict.reasons.includes('invalid_solution'));
});

