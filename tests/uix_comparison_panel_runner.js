// Exercise the actual page and local scripts at a Windows-safe file URL.
const {JSDOM, VirtualConsole} = require('jsdom');
const fs = require('node:fs/promises');
const {pathToFileURL} = require('node:url');
const path = require('node:path');
const assert = require('node:assert/strict');
const {TextEncoder, TextDecoder} = require('node:util');

const tick = () => new Promise(resolve => setTimeout(resolve, 30));
async function waitFor(predicate) {
  for (let i = 0; i < 100; i++) { if (predicate()) return; await tick(); }
  throw new Error('Timed out waiting for panel');
}
function entry(id, reduced, {omitFinalDomain = false} = {}) {
  const docs = {
    'run_manifest.json': {artifact_schema_version: '1.1', experiment_id: 'synthetic-portfolio', run_status: 'success', run_id: id, is_classical_only: !reduced, has_reduction: reduced, round_count: reduced ? 1 : 0},
    'problem.json': {asset_ids: ['a', 'b'], expected_returns: [0.1, 0.2], covariance: [[0.04, 0], [0, 0.09]]},
    'run_result.json': {objective_sense: 'minimize', postcheck_result: {postcheck_feasible: true, objective_recomputed: reduced ? -0.1 : -0.2}, classical_result: {effective_solver_parameters: {time_limit_seconds: reduced ? 'unlimited' : 60}, variable_values: reduced ? {x__a: 1, x__b: 0} : {x__a: 0, x__b: 1}}, final_retained_item_ids: reduced ? ['a'] : null, residual_variable_counts: {binary_free: 1}, run_result: {terminal_reason: 'target_reached'}, round_results: reduced ? [{
      round_index: 0, run_status: 'success', terminal_reason: 'target_reached', retained_item_ids: ['a'], round_reduction_ratio: 0.5,
      mis_compilation_result: {compiled_job: {effective_backend_id: 'greedy_mis', effective_provider_id: 'local', execution_mode: 'local', compiled_problem: {graph: {node_ids: ['a', 'b'], edges: [['a', 'b']]}}}},
      candidate_records: [{candidate_id: 'candidate:0000', selection_status: 'selected', repair_status: 'valid_without_repair', num_selected: 1, num_violated_edges_before_repair: 0, repair_actions: [], selected_item_ids: ['a']}],
      selected_mis_samples: [{raw_sample_id: 'sample:0000', num_selected: 1}],
      candidate_domain_item_records: [{item_id: 'a', decision: 'retained', reason: 'selected_candidate_aggregation'}, {item_id: 'b', decision: 'excluded', reason: 'not_present_in_selected_candidates'}]
    }, {round_index: 1, retained_item_ids: ['a'], mis_compilation_result: {compiled_job: {compiled_problem: {graph: {node_ids: ['a'], edges: []}}}}, candidate_domain_item_records: []}, null] : [], metrics: {end_to_end_runtime_seconds: reduced ? 5.123456 : 10.654321}},
    'config_used.json': {run_identity: {run_id: id}, reduction: {candidate_domain_max_items: 1, max_reduction_rounds: 2, target_binary_variables: 1}, mis_solver_id: reduced ? 'greedy_mis' : 'none'}, 'experiment_metadata.json': {portfolio_graph_policy: {policy_id: 'correlation'}}
  };
  if (omitFinalDomain) delete docs['run_result.json'].final_retained_item_ids;
  return {id, files: Object.fromEntries(Object.entries(docs).map(([name, value]) => [name, JSON.stringify(value)]))};
}
(async () => {
  const errors = [];
  const console = new VirtualConsole();
  console.on('jsdomError', error => errors.push(error.message));
  const baseline = '<img src=x onerror=alert(1)> à|#';
  const entries = [entry(baseline, false), entry('second-id', true), entry('unknown-domain', true, {omitFinalDomain: true})];
  const temporaryRoot = path.resolve(__dirname, '../.cline-tmp');
  await fs.mkdir(temporaryRoot, {recursive: true});
  const fixture = await fs.mkdtemp(path.join(temporaryRoot, 'uix-catalog-test-'));
  let dom;
  try {
    const fixtureUix = path.join(fixture, 'uix');
    await fs.cp(path.resolve(__dirname, '../uix'), fixtureUix, {recursive: true});
    const fixtureOutput = path.join(fixture, 'outputs', 'portfolio_mv');
    await fs.mkdir(fixtureOutput, {recursive: true});
    const catalogPath = path.join(fixtureOutput, 'run_catalog.js');
    const writeCatalog = runs => fs.writeFile(catalogPath, 'window.QReduceRunCatalog = ' + JSON.stringify(runs) + ';', 'utf8');
    await writeCatalog(entries);
    const page = path.join(fixtureUix, 'experiment_portfolio_mv.html');
    dom = await JSDOM.fromFile(page, {
      url: pathToFileURL(page).href,
      resources: 'usable', runScripts: 'dangerously', virtualConsole: console,
      beforeParse(window) { window.TextEncoder = TextEncoder; window.TextDecoder = TextDecoder; }
    });
    await new Promise(resolve => dom.window.addEventListener('load', resolve));
    const {document, Event} = dom.window;
    assert.ok(dom.window.QReduceComparison, 'comparison core loaded from file URL');
    const a = document.getElementById('comparison-a'), b = document.getElementById('comparison-b');
    const status = document.getElementById('comparison-status'), report = document.getElementById('comparison-report');
    const swap = document.getElementById('comparison-swap');
    const refresh = document.getElementById('comparison-refresh');
    const tab = document.querySelector('[data-tab="comparison"]');
    const panel = document.getElementById('comparison');
    for (const icon of [refresh, swap]) {
      assert.ok(icon.querySelector('svg[aria-hidden="true"]'));
      assert.ok(icon.getAttribute('aria-label'));
    }
    assert.equal(a.parentElement.nextElementSibling, swap);
    assert.equal(swap.nextElementSibling, b.parentElement);
    assert.equal(tab.previousElementSibling.dataset.tab, 'export');
    assert.equal(dom.window.getComputedStyle(panel).display, 'none');
    tab.click();
    document.querySelector('[data-tab="export"]').click();
    tab.click();
    assert.equal(dom.window.getComputedStyle(panel).display, 'block');
    assert.equal(dom.window.getComputedStyle(document.getElementById('experiment')).display, 'none');
    await waitFor(() => !a.disabled);
    assert.ok(swap.disabled);
    assert.equal(document.getElementById('comparison-download'), null, 'no export control');
    assert.ok(![...document.querySelectorAll('button, a')].some(e => /(?:scarica|esporta|download|export).*markdown/i.test(e.textContent)));
    for (const input of [a, b]) {
      assert.equal(input.tagName, 'SELECT');
      assert.equal(input.disabled, false);
      assert.deepEqual([...input.options].map(option => option.value), ['', ...entries.map(run => run.id)]);
    }
    function select(input, id) { input.value = id; input.dispatchEvent(new Event('change')); }
    // jsdom has no layout engine: exclude closed details and CSS-hidden ancestors.
    function visibleText(root) {
      return [...root.querySelectorAll('*')].filter(e => {
        if (e.children.length || e.closest('details:not([open])')) return false;
        for (let p = e; p && p.nodeType === 1; p = p.parentElement) {
          const style = dom.window.getComputedStyle(p);
          if (p.hidden || style.display === 'none' || style.visibility === 'hidden') return false;
        }
        return true;
      }).map(e => e.textContent).join(' ');
    }
    select(a, baseline);
    await waitFor(() => status.textContent.includes('Run caricato'));
    assert.ok(swap.disabled);
    select(b, baseline);
    await waitFor(() => status.textContent === 'Scegli due run diversi.');
    assert.ok(swap.disabled);
    select(b, 'second-id');
    await waitFor(() => status.textContent === 'Confronto pronto.');
    assert.ok(!swap.disabled);
    const visible = visibleText(report);
    for (const label of [/dominio finale/i, /variazione (?:dell.?\s*)?obiettivo/i, /posizioni.*baseline.*escluse/i, /dominio prima e dopo/i, /motivi delle esclusioni/i, /destinazione delle posizioni della baseline/i, /mantenut/i, /esclus/i, /candidati selezionati/i, /tetto|massimo configurato/i]) {
      assert.match(visible, label, `visible dashboard label: ${label}`);
    }
    assert.match(visible, /Baseline /);
    assert.match(report.textContent, /<img src=x onerror=alert\(1\)>/);
    assert.equal(report.querySelector('img'), null);
    assert.match(report.textContent, /traccia.*incompleta/i);
    assert.match(visible, /0[.,]1/);
    assert.match(visible, /50\s*%/);
    assert.match(visible, /2\s*nod/i);
    assert.match(visible, /1\s*arc/i);
    assert.match(visible, /traccia.*incompleta/i, 'warnings must be visible without opening details');
    assert.ok(visible.includes('Baseline ' + baseline));
    assert.doesNotMatch(visible, /Ã|Â|â€|�/, 'visible dashboard must be valid UTF-8');
    const roundSelect = report.querySelector('select[aria-label*="round"]');
    assert.ok(roundSelect, 'round selector is accessible');
    assert.equal(roundSelect.options.length, 2);
    roundSelect.value = '1';
    roundSelect.dispatchEvent(new Event('change'));
    assert.match(visibleText(report), /1\s*nod/i, 'round selection updates graph evidence');
    assert.match(visibleText(report), /0\s*arc/i);
    roundSelect.value = '0';
    roundSelect.dispatchEvent(new Event('change'));
    assert.ok(report.querySelector('.comparison-donut'), 'exclusion donut is rendered');
    assert.ok([...report.querySelectorAll('.comparison-card')].find(section => section.querySelector('h3')?.textContent === 'Destinazione delle posizioni della baseline').querySelector('.comparison-bar'), 'positions bar is rendered');
    const card = title => [...report.querySelectorAll('.comparison-card')].find(section => section.querySelector('h3')?.textContent === title);
    const fact = (root, label) => [...root.querySelectorAll('dt')].find(dt => dt.textContent === label)?.nextElementSibling.textContent;
    assert.equal(fact(card('Indicatori'), 'Posizioni della baseline escluse'), '1');
    const domainCard = card('Dominio prima e dopo');
    const segments = domainCard.querySelectorAll('.comparison-bar > span');
    assert.equal(segments.length, 2, 'domain chart has retained and excluded segments');
    assert.deepEqual([...segments].map(segment => segment.style.width), ['50%', '50%']);
    assert.match(visibleText(domainCard), /Mantenuti:\s*1/);
    assert.match(visibleText(domainCard), /Esclusi:\s*1/);
    assert.equal(fact(domainCard, 'Massimo configurato del dominio candidato'), '1');
    assert.equal(fact(card('Conclusione'), 'Qualità'), 'peggiorato');
    assert.equal(fact(card('Conclusione'), 'Tempo end-to-end'), 'migliorato');
    assert.match(visibleText(card('Conclusione')), /Compromesso tra qualità e tempo/);
    assert.match(visibleText(card('Avvisi')), /traccia.*incompleta/i);
    const thermometer = card('Termometro finale');
    assert.match(visibleText(thermometer), /Budget solver Baseline 60 s Confronto illimitato/);
    assert.match(visibleText(thermometer), /Budget pipeline end-to-end Baseline Dato non registrato Confronto Dato non registrato/);
    assert.match(visibleText(thermometer), /Tempo end-to-end migliorato Baseline 11 s Confronto 5 s/);
    const technical = report.querySelector('.comparison-technical');
    technical.open = true;
    assert.deepEqual([...technical.querySelectorAll('h3')].map(h => h.textContent), ['Sintesi', 'Come ha operato la riduzione', 'Effetto sulla soluzione', 'Dettagli sui tempi']);
    const endToEnd = [...technical.querySelectorAll('th[scope="row"]')].find(th => th.textContent === 'End-to-end');
    assert.deepEqual([...endToEnd.parentElement.querySelectorAll('td')].map(td => td.textContent), ['11', '5', '-6']);
    assert.doesNotMatch(visibleText(report), /modello di confronto non fornisce ancora/i, 'verdict uses the actual dashboard model');
    swap.click();
    assert.equal(fact(card('Conclusione'), 'Baseline'), 'second-id');
    assert.equal(a.value, 'second-id');
    assert.equal(b.value, baseline);
    assert.match(report.textContent, /-0[.,]1/);
    assert.equal(fact(card('Conclusione'), 'Qualità'), 'migliorato');
    assert.equal(fact(card('Conclusione'), 'Tempo end-to-end'), 'peggiorato');
    assert.match(visibleText(card('Conclusione')), /Giudizio complessivo non disponibile.*baseline senza riduzione non verificata.*riduzione del confronto non verificata/i);
    assert.equal(fact(card('Indicatori'), 'Posizioni della baseline escluse'), '0');
    swap.click();
    select(b, 'unknown-domain');
    await waitFor(() => status.textContent === 'Confronto pronto.');
    assert.equal(fact(card('Indicatori'), 'Posizioni della baseline escluse'), 'Non verificabile');
    assert.match(visibleText(card('Destinazione delle posizioni della baseline')), /Stato sconosciuto: 1/);
    select(a, '');
    assert.ok(swap.disabled);
    assert.equal(report.children.length, 0);
    assert.match(status.textContent, /Seleziona due run/);
    assert.deepEqual(errors, []);

    select(a, baseline);
    select(b, 'second-id');
    await waitFor(() => status.textContent === 'Confronto pronto.');
    const added = entry('new-id', true);
    await writeCatalog([...entries, added]);
    refresh.click();
    await waitFor(() => !refresh.disabled);
    assert.match(status.textContent, /Catalogo ricaricato dal disco\. Confronto pronto/);
    assert.deepEqual([a.value, b.value], [baseline, 'second-id']);
    assert.ok([...a.options].some(option => option.value === 'new-id'));
    await writeCatalog([entries[0], added]);
    refresh.click();
    await waitFor(() => !refresh.disabled);
    assert.deepEqual([a.value, b.value], [baseline, '']);
    assert.equal(report.children.length, 0);
    await writeCatalog([entries[0]]);
    refresh.click();
    await waitFor(() => !refresh.disabled);
    assert.match(status.textContent, /meno di due run/);
    assert.ok(a.disabled && b.disabled);
    await fs.unlink(catalogPath);
    refresh.click();
    await waitFor(() => !refresh.disabled);
    assert.match(status.textContent, /Catalogo locale non trovato o non valido/);
    assert.ok(a.disabled && b.disabled);
    await writeCatalog(entries);
    refresh.click();
    await waitFor(() => !refresh.disabled);
    assert.ok(!a.disabled && !b.disabled);
    assert.equal(a.options.length, entries.length + 1);
    assert.ok(tab.classList.contains('active'));
    process.stdout.write('panel ok\n');
  } finally {
    dom?.window.close();
    await fs.rm(fixture, {recursive: true, force: true});
  }
})().catch(error => { process.stderr.write(error.stack + '\n'); process.exitCode = 1; });
