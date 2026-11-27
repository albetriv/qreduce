// Load the real SR page and scripts, but never depend on local pipeline outputs.
const {JSDOM, VirtualConsole} = require('jsdom');
const fs = require('node:fs/promises');
const path = require('node:path');
const {pathToFileURL} = require('node:url');
const {TextEncoder, TextDecoder} = require('node:util');
const assert = require('node:assert/strict');

async function waitFor(predicate) {
  for (let i = 0; i < 100; i++) {
    if (predicate()) return;
    await new Promise(resolve => setTimeout(resolve, 30));
  }
  throw new Error('Timed out waiting for SR panel');
}

function entry(id, classical, sharpe) {
  const docs = {
    'run_manifest.json': {artifact_schema_version: '1.1', experiment_id: 'sharpe_portfolio', run_id: id, run_status: 'success', is_classical_only: classical, has_reduction: !classical},
    'problem.json': {tickers: ['A', 'B'], mean_returns: [0.15, 0.2], covariance: [[0.04, 0.01], [0.01, 0.09]], max_positions: 2},
    'run_result.json': {run_result: {run_status: 'success', adoption_status: 'adopted'}, postcheck_result: {postcheck_feasible: true}, domain_evaluation_metrics: [{metric_id: 'sharpe_ratio', value: sharpe}], classical_result: {variable_values: {x_scale: 2, x_scaled__A: 1, x_scaled__B: 1, delta__A: 1, delta__B: 1}}, final_retained_item_ids: classical ? null : ['A', 'B'], metrics: {end_to_end_runtime_seconds: classical ? 10 : 5}},
    'config_used.json': {run_identity: {run_id: id}}, 'experiment_metadata.json': {}
  };
  return {id, files: Object.fromEntries(Object.entries(docs).map(([name, value]) => [name, JSON.stringify(value)]))};
}

(async () => {
  const temporaryRoot = path.resolve(__dirname, '../.cline-tmp');
  await fs.mkdir(temporaryRoot, {recursive: true});
  const fixture = await fs.mkdtemp(path.join(temporaryRoot, 'qreduce sr panel '));
  let dom;
  try {
    const uix = path.join(fixture, 'uix');
    await fs.cp(path.resolve(__dirname, '../uix'), uix, {recursive: true});
    const output = path.join(fixture, 'outputs', 'portfolio_sr');
    await fs.mkdir(output, {recursive: true});
    const catalog = path.join(output, 'run_catalog.js');
    const entries = [entry('baseline', true, 1.2), entry('reduced', false, 1.5)];
    const baselineProblem = JSON.parse(entries[0].files['problem.json']);
    baselineProblem.lower_bounds = {A: 0.2};
    entries[0].files['problem.json'] = JSON.stringify(baselineProblem);
    const reducedProblem = JSON.parse(entries[1].files['problem.json']);
    reducedProblem.lower_bound = 0.05;
    reducedProblem.min_selected_assets = 2;
    entries[1].files['problem.json'] = JSON.stringify(reducedProblem);
    const reducedResult = JSON.parse(entries[1].files['run_result.json']);
    reducedResult.domain_evaluation_metrics.push(
      {metric_id: 'selected_count', value: 2}, {metric_id: 'position_count', value: 2}
    );
    reducedResult.round_results = [{round_index: 0, terminal_reason: 'no_valid_mis_candidate',
      mis_compilation_result: {compiled_job: {effective_compilation_parameters: {
        _chain_strength: 9.618526483406905, _chain_strength_policy: 'uniform_torque_compensation',
      }}}}];
    entries[1].files['run_result.json'] = JSON.stringify(reducedResult);
    const writeCatalog = runs => fs.writeFile(catalog, 'window.QReduceRunCatalogSR = ' + JSON.stringify(runs) + ';', 'utf8');
    await writeCatalog(entries);
    const page = path.join(uix, 'experiment_portfolio_sr.html');
    const errors = [];
    const console = new VirtualConsole();
    console.on('jsdomError', error => errors.push(error));
    dom = await JSDOM.fromFile(page, {url: pathToFileURL(page).href, resources: 'usable', runScripts: 'dangerously', virtualConsole: console,
      beforeParse(window) { window.TextEncoder = TextEncoder; window.TextDecoder = TextDecoder; }});
    await new Promise(resolve => dom.window.addEventListener('load', resolve));
    const {document, Event} = dom.window;
    const a = document.getElementById('comparison-a'), b = document.getElementById('comparison-b');
    const status = document.getElementById('comparison-status'), report = document.getElementById('comparison-report');
    const swap = document.getElementById('comparison-swap'), refresh = document.getElementById('comparison-refresh');
    const selectors = document.querySelector('#comparison .comparison-selectors');
    assert.deepEqual([...selectors.children].map(element => element.id || element.className), ['field', 'comparison-swap', 'field']);
    assert.equal(refresh.closest('.comparison-refresh-wrapper').parentElement.className, 'section-head');
    assert.match(document.querySelector('#comparison .tooltip').textContent, /qreduce\.experiments\.portfolio_sr\.run_catalog/);
    assert.equal(status.getAttribute('role'), 'status');
    document.querySelector('[data-tab="comparison"]').click();
    try { await waitFor(() => !a.disabled && a.options.length === 3); }
    catch (error) { throw new Error(`${error.message}: ${status.textContent}; ${errors.map(e => e.message).join('; ')}`); }
    assert.ok(swap.disabled);
    const select = (element, value) => { element.value = value; element.dispatchEvent(new Event('change')); };
    select(a, 'baseline');
    select(b, 'reduced');
    await waitFor(() => status.textContent === 'Confronto pronto.');
    assert.match(report.textContent, /baseline/);
    assert.match(report.textContent, /reduced/);
    assert.match(report.textContent, /1[.,]2/);
    assert.match(report.textContent, /1[.,]5/);
    assert.match(report.textContent, /Investimento minimo baseline\s*Minimi per titolo: A = 0[.,]2; altri ticker = 0/);
    assert.match(report.textContent, /Investimento minimo confronto\s*0[.,]05/);
    assert.match(report.textContent, /Identità dell’istanza non verificata/);
    assert.match(report.textContent, /Politica forza delle catene\s*uniform_torque_compensation/);
    assert.match(report.textContent, /Forza effettiva delle catene\s*9\.618526483406905/);
    const valuesFor = label => Array.from(report.querySelectorAll('tbody tr'))
      .find(row => row.firstElementChild.textContent === label).textContent;
    assert.match(valuesFor('Cardinalità minima portafoglio'), /Nessun minimo\s*2/);
    assert.match(valuesFor('Ticker selezionati (binarie)'), /Non registrato\s*2/i);
    assert.match(valuesFor('Posizioni investite (peso sopra tolleranza)'), /Non registrato\s*2/i);
    entries[1].files['problem.json'] = entries[0].files['problem.json'];
    await writeCatalog(entries);
    refresh.click();
    await waitFor(() => !refresh.disabled);
    assert.match(report.textContent, /problem\.json coincide byte per byte/);
    assert.match(report.textContent, /non dimostra che il modello compilato e risolto sia identico/);
    assert.ok(!swap.disabled);
    swap.click();
    assert.deepEqual([a.value, b.value], ['reduced', 'baseline']);
    const conclusion = [...report.querySelectorAll('section')].find(section => section.querySelector('h3')?.textContent === 'Conclusione');
    assert.match(conclusion.textContent, /Baseline\s*reduced/);
    assert.match(conclusion.textContent, /Confronto\s*baseline/);
    await writeCatalog([...entries, entry('added', true, 1)]);
    refresh.click();
    await waitFor(() => !refresh.disabled);
    assert.match(status.textContent, /Catalogo ricaricato dal disco.*Confronto pronto/);
    assert.deepEqual([a.value, b.value], ['reduced', 'baseline']);
    assert.ok([...a.options].some(option => option.value === 'added'));
    await writeCatalog([entries[0], entry('added', true, 1)]);
    refresh.click();
    await waitFor(() => !refresh.disabled);
    assert.deepEqual([a.value, b.value], ['', 'baseline']);
    assert.equal(report.children.length, 0);
    await fs.unlink(catalog);
    refresh.click();
    await waitFor(() => !refresh.disabled);
    assert.match(status.textContent, /Catalogo locale non trovato o non valido/);
    assert.match(status.textContent, /qreduce\.experiments\.portfolio_sr\.run_catalog/);
    assert.ok(a.disabled && b.disabled);
    assert.equal(report.children.length, 0);
    await writeCatalog(entries);
    refresh.click();
    await waitFor(() => !refresh.disabled);
    assert.ok(!a.disabled && !b.disabled);
    assert.equal(a.options.length, 3);
    // A missing catalog produces one expected resource-loading error in jsdom.
    assert.equal(errors.length, 1, errors.map(error => error.message).join('\n'));
    assert.match(errors[0].message, /run_catalog\.js/);
    process.stdout.write('sr panel ok\n');
  } finally {
    dom?.window.close();
    await fs.rm(fixture, {recursive: true, force: true});
  }
})().catch(error => { process.stderr.write(error.stack + '\n'); process.exitCode = 1; });