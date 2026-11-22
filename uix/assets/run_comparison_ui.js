/* Presentation of comparison data as text, never HTML. */
(function () {
  'use strict';
  const inputs = [document.getElementById('comparison-a'), document.getElementById('comparison-b')];
  if (!inputs[0] || !inputs[1]) return;
  const status = document.getElementById('comparison-status'), report = document.getElementById('comparison-report');
  const swap = document.getElementById('comparison-swap');
  const refresh = document.getElementById('comparison-refresh');
  const mathPanel = document.getElementById('mathPanel');
  const comparisonPanel = document.getElementById('comparison');
  document.querySelector('.portfolio-tabs').addEventListener('click', () => {
    mathPanel.hidden = comparisonPanel.classList.contains('active');
  });
  const runs = [null, null], names = ['', ''], versions = [0, 0];
  const catalog = new Map();
  const missing = 'Dato non registrato';
  const fmt = v => v == null ? missing : typeof v === 'number' ? (Number.isFinite(v) ? String(Number(v.toFixed(8))) : missing) : typeof v === 'boolean' ? (v ? 'Sì' : 'No') : String(v);
  const wholeSeconds = value => Number.isFinite(value) ? String(Math.round(value)) : fmt(value);
  const seconds = value => Number.isFinite(value) ? wholeSeconds(value) + ' s' : fmt(value);
  function el(parent, tag, text) { const e = document.createElement(tag); if (text !== undefined) e.textContent = text; parent.appendChild(e); return e; }
  function facts(parent, rows) {
    const list = el(parent, 'dl'); list.className = 'comparison-facts';
    for (const [label, value] of rows) {
      const pair = el(list, 'div');
      el(pair, 'dt', label);
      el(pair, 'dd', value);
    }
  }
  function note(parent, text) { el(parent, 'p', text).className = 'comparison-note'; }
  function dashboard(parent, r) {
    const d = r.dashboard, t = d.thermometer;
    const card = (host, title) => { const section = el(host, 'section'); section.className = 'card comparison-card'; el(section, 'h3', title); return section; };
    const grid = el(parent, 'div'); grid.className = 'comparison-grid';
    const verdicts = {favorable: 'Confronto favorevole', partially_favorable: 'Confronto parzialmente favorevole', tradeoff: 'Compromesso tra qualità e tempo', no_overall_advantage: 'Nessun vantaggio complessivo osservato', unchanged: 'Qualità e tempo invariati'};
    const reasons = {instance_unverified: 'identità dell’istanza non verificata', invalid_solution: 'soluzione non valida o assente', baseline_not_verified_unreduced: 'baseline senza riduzione non verificata (la baseline potrebbe essere ridotta)', comparison_not_verified_reduced: 'riduzione del confronto non verificata (il confronto potrebbe essere senza riduzione)', insufficient_metrics: 'metriche insufficienti'};
    const directions = {improved: 'migliorato', worsened: 'peggiorato', unchanged: 'invariato', unknown: 'non valutabile'};
    const summary = card(grid, 'Conclusione');
    summary.classList.add('comparison-wide');
    el(summary, 'p', d.verdict.value ? verdicts[d.verdict.value] || d.verdict.value : 'Giudizio complessivo non disponibile').className = 'comparison-verdict';
    if (!d.verdict.value && d.verdict.reasons.length) {
      const list = el(summary, 'ul');
      d.verdict.reasons.forEach(reason => el(list, 'li', reasons[reason] || reason));
    }
    facts(summary, [['Baseline', fmt(r.baseline.id)], ['Confronto', fmt(r.comparison.id)],
      ['Qualità', directions[d.verdict.quality] || d.verdict.quality],
      ['Tempo end-to-end', directions[d.verdict.endToEnd] || d.verdict.endToEnd]]);
    note(summary, 'I risultati descrivono i run osservati e non dimostrano un effetto causale.');
    if (r.warnings.length) { const warnings = card(grid, 'Avvisi'); const list = el(warnings, 'ul'); r.warnings.forEach(w => el(list, 'li', w)); }
    const indicators = card(grid, 'Indicatori');
    facts(indicators, [
      ['Dominio finale', fmt(d.domain.final) + ' su ' + fmt(d.domain.initial) + ' asset'],
      ['Variazione dell’obiettivo', fmt(t.quality.delta) + (t.quality.percent == null ? '' : ' (' + fmt(t.quality.percent) + '% rispetto al valore assoluto della baseline)')],
      ['Posizioni della baseline escluse', r.baselineExcludedCount == null ? 'Non verificabile' : fmt(r.baselineExcludedCount)]
    ]);
    function bar(host, parts, total) {
      if (total == null || total < 0 || parts.some(p => p.value == null || p.value < 0)) { el(host, 'p', 'Dati del grafico non disponibili.'); return; }
      const chart = el(host, 'div'); chart.className = 'comparison-bar'; chart.setAttribute('role', 'img'); chart.setAttribute('aria-label', parts.map(p => p.label + ': ' + fmt(p.value)).join('; '));
      parts.forEach((p, i) => { const segment = el(chart, 'span'); segment.className = 'comparison-color-' + (i % 5); segment.style.width = (total ? p.value / total * 100 : 0) + '%'; });
      const list = el(host, 'ul'); list.className = 'comparison-legend';
      parts.forEach((p, i) => { const item = el(list, 'li'); const swatch = el(item, 'span'); swatch.className = 'comparison-swatch comparison-color-' + (i % 5); el(item, 'span', p.label + ': ' + fmt(p.value)); });
    }
    const domain = card(grid, 'Dominio prima e dopo');
    el(domain, 'p', 'Asset iniziali: ' + fmt(d.domain.initial) + '; mantenuti: ' + fmt(d.domain.final) + '.');
    bar(domain, [{label: 'Mantenuti', value: d.domain.final}, {label: 'Esclusi', value: d.domain.excluded}], d.domain.initial);
    facts(domain, [['Massimo configurato del dominio candidato', fmt(d.domain.cap)]]);
    note(domain, 'Distinto dal target di binarie e dal massimo di posizioni.');
    const reasonCard = card(grid, 'Motivi delle esclusioni');
    if (!d.rounds.length) el(reasonCard, 'p', 'Nessun round disponibile.');
    else {
      const label = el(reasonCard, 'label', 'Round '), select = el(label, 'select');
      select.setAttribute('aria-label', 'Seleziona il round del confronto');
      d.rounds.forEach((round, index) => { const option = el(select, 'option', 'Round ' + fmt(round.index)); option.value = String(index); });
      const content = el(reasonCard, 'div');
      const names = {not_present_in_selected_candidates: 'Assenza dai candidati selezionati', candidate_domain_cap: 'Tetto del dominio', best_effort_protection_excluded_by_cap: 'Tetto del dominio nonostante la protezione facoltativa', undocumented: 'Non documentato'};
      function showRound() {
        content.replaceChildren();
        const round = d.rounds[Number(select.value) || 0];
        el(content, 'p', 'Grafo effettivo: ' + fmt(round.graph?.nodes) + ' nodi; ' + fmt(round.graph?.edges) + ' archi.');
        if (round.excluded === 0) { el(content, 'p', 'Nessuna esclusione nel round.'); return; }
        if (round.excluded == null) el(content, 'p', 'Totale delle esclusioni non verificabile; i conteggi documentati possono essere incompleti.');
        else {
          el(content, 'p', 'Esclusi nel round: ' + fmt(round.excluded) + '.');
          const donut = el(content, 'div'); donut.className = 'comparison-donut'; donut.setAttribute('aria-hidden', 'true');
          let offset = 0;
          const colors = Array.from({length: 5}, (_, i) => 'var(--comparison-color-' + i + ')');
          const stops = round.reasons.map((item, i) => { const start = offset; offset += item.percent || 0; return colors[i % colors.length] + ' ' + start + '% ' + offset + '%'; });
          donut.style.background = 'conic-gradient(' + stops.join(', ') + ')';
        }
        const list = el(content, 'ul'); list.className = 'comparison-legend';
        round.reasons.forEach((item, i) => { const li = el(list, 'li'); const swatch = el(li, 'span'); swatch.className = 'comparison-swatch comparison-color-' + (i % 5); el(li, 'span', (names[item.reason] || 'Altro motivo registrato: ' + fmt(item.reason)) + ': ' + fmt(item.count) + (item.percent == null ? '' : ' (' + fmt(item.percent) + '%)')); });
      }
      select.addEventListener('change', showRound); showRound();
    }
    const positions = card(grid, 'Destinazione delle posizioni della baseline');
    const labels = {selected_both: 'Scelto in entrambi', available_not_selected: 'Disponibile ma non scelto', excluded_from_domain: 'Escluso dal dominio', domain_unknown: 'Stato sconosciuto'};
    if (!d.positions) el(positions, 'p', 'Composizione confrontabile non disponibile.');
    else { const parts = d.positions.map(x => ({label: labels[x.status] || x.status, value: x.count})); bar(positions, parts, parts.reduce((sum, x) => sum + x.value, 0)); }
    const thermometer = card(grid, 'Termometro finale');
    const percent = x => x == null ? 'non disponibile' : fmt(x) + '%';
    thermometer.classList.add('comparison-wide');
    const axes = el(thermometer, 'div'); axes.className = 'comparison-axes';
    function axis(title, direction, rows) {
      const section = el(axes, 'section');
      el(section, 'h4', title);
      if (direction) el(section, 'p', directions[direction] || direction).className = 'comparison-verdict';
      facts(section, rows);
    }
    axis('Qualità della soluzione', t.quality.direction, [
      ['Baseline', fmt(t.quality.baseline)], ['Confronto', fmt(t.quality.comparison)],
      ['Differenza', fmt(t.quality.delta)], ['Variazione', percent(t.quality.percent)]
    ]);
    axis('Tempo solver', t.solverTime.direction, [
      ['Baseline', seconds(t.solverTime.baseline)], ['Confronto', seconds(t.solverTime.comparison)], ['Variazione', percent(t.solverTime.percent)]
    ]);
    axis('Tempo end-to-end', t.endToEnd.direction, [
      ['Baseline', seconds(t.endToEnd.baseline)], ['Confronto', seconds(t.endToEnd.comparison)],
      ['Rapporto', t.endToEnd.ratio == null ? missing : t.endToEnd.ratio.toFixed(2) + '×']
    ]);
    axis('Dimensione del dominio', null, [
      ['Asset iniziali', fmt(t.domain.initial)], ['Asset finali', fmt(t.domain.final)], ['Riduzione', percent(t.domain.reductionPercent)]
    ]);
    const budgetText = b => b?.state === 'unlimited' ? 'illimitato' : b?.state === 'numeric' ? seconds(b.seconds) : missing;
    for (const [label, pair] of [['solver', t.budgets.solver], ['pipeline end-to-end', t.budgets.pipeline]]) {
      el(thermometer, 'h4', 'Budget ' + label);
      facts(thermometer, [['Baseline', budgetText(pair?.baseline)], ['Confronto', budgetText(pair?.comparison)]]);
    }
    note(thermometer, 'Durate e budget arrotondati al secondo; i calcoli usano i valori originali.');
  }

  function render(r) {
    report.replaceChildren();
    dashboard(report, r);
    const technical = el(report, 'details');
    technical.className = 'card comparison-technical';
    el(technical, 'summary', 'Dettagli tecnici');
    const output = el(technical, 'div');
    output.className = 'comparison-technical-body';
    let section;
    function heading(text) { section = el(output, 'section'); el(section, 'h3', text); }
    function paragraph(text) { el(section, 'p', text); }
    function table(headers, rows, parent) {
      const wrapper = el(parent || section, 'div'); wrapper.className = 'comparison-table-wrap';
      wrapper.tabIndex = 0;
      wrapper.setAttribute('role', 'region');
      wrapper.setAttribute('aria-label', headers[0]);
      const t = el(wrapper, 'table'), tr = el(el(t, 'thead'), 'tr');
      headers.forEach(x => { el(tr, 'th', x).scope = 'col'; });
      const body = el(t, 'tbody');
      rows.forEach(row => {
        const line = el(body, 'tr');
        el(line, 'th', fmt(row[0])).scope = 'row';
        row.slice(1).forEach(x => el(line, 'td', fmt(x)));
      });
    }
    function details(title, callback) { const d = el(section, 'details'); el(d, 'summary', title); callback(el(d, 'div')); }
    const a = r.baseline, b = r.comparison;
    const count = x => x.retained ? x.retained.length : x.reduction.state === 'not_applicable' ? x.originalCount : null;
    const diff = (x, y) => typeof x === 'number' && typeof y === 'number' ? y - x : null;
    const row = (label, x, y, comparable = true) => [label, x, y, comparable ? diff(x, y) : null];
    const timeRow = (label, x, y) => row(label, x, y).map((value, index) => index ? wholeSeconds(value) : value);
    heading('Sintesi');
    facts(section, [['Baseline', fmt(a.id)], ['Confronto', fmt(b.id)]]);
    paragraph(r.sameInstance ? 'Istanza identica: problem.json coincide byte per byte.' : 'Identità dell’istanza non verificata: i file possono differire anche solo nella serializzazione.');
    facts(section, [
      ['Dominio del confronto', fmt(count(b)) + ' asset su ' + fmt(b.originalCount)],
      ['Posizioni baseline escluse', r.baselineExcludedCount == null ? 'Non verificabile' : fmt(r.baselineExcludedCount)],
      ['Variazione dell’obiettivo', r.objective.comparable ? fmt(r.objective.delta) + ' (' + (r.objective.percent == null ? 'percentuale non disponibile' : fmt(r.objective.percent) + '%') + ')' : 'Non confrontabile']
    ]);
    if (r.objective.comparable) {
      const sense = String(a.sense).toLowerCase();
      const direction = sense === 'minimize' || sense === 'min' ? -1 : sense === 'maximize' || sense === 'max' ? 1 : 0;
      const change = r.objective.delta * direction;
      paragraph(!direction ? 'Verso dell’obiettivo non riconosciuto: variazione non interpretata.' : change === 0 ? 'Obiettivo invariato al valore registrato.' : 'Nel confronto l’obiettivo è ' + (change > 0 ? 'migliore' : 'peggiore') + ' secondo il verso di ottimizzazione (' + fmt(a.sense) + '). La percentuale usa il valore assoluto della baseline come denominatore.');
    }
    heading('Come ha operato la riduzione');
    const state = x => x.reduction.state === 'not_applicable' ? 'Riduzione non applicata' : x.reduction.state === 'available' ? 'Traccia disponibile' : missing;
    const na = 'Non applicabile';
    const reductionValue = (run, value) => run.reduction.state === 'not_applicable' ? na : value;
    const reductionRow = (label, x, y) => [label, reductionValue(a, x), reductionValue(b, y), a.reduction.state === 'not_applicable' || b.reduction.state === 'not_applicable' ? na : diff(x, y)];
    const countLabel = (n, singular, plural) => fmt(n) + ' ' + (n === 1 ? singular : plural);
    const exclusionText = new Map([
      ['not_present_in_selected_candidates', 'per assenza dai candidati selezionati'],
      ['candidate_domain_cap', 'per il limite del dominio candidato'],
      ['best_effort_protection_excluded_by_cap', 'per il limite del dominio candidato nonostante la protezione facoltativa']
    ]);
    [a, b].forEach((run, i) => {
      const label = i ? 'Confronto' : 'Baseline', red = run.reduction;
      const block = el(section, 'section');
      el(block, 'h4', label);
      if (red.state === 'not_applicable') { note(block, 'Riduzione non applicata: il dominio originale resta disponibile.'); return; }
      facts(block, [['Dominio finale', fmt(count(run)) + ' su ' + fmt(run.originalCount) + ' asset'],
        ['Round eseguiti', fmt(red.roundCount) + ' su ' + fmt(red.maxRounds)], ['Motivo di arresto', fmt(red.stopReason)]]);
      red.rounds.forEach(round => {
        const parts = [];
        if (round.graph?.nodes != null) parts.push(countLabel(round.graph.nodes, 'nodo', 'nodi'));
        if (round.graph?.edges != null) parts.push(countLabel(round.graph.edges, 'arco', 'archi'));
        const evidence = parts.length ? ['grafo effettivo: ' + parts.join(', ')] : [];
        if (Array.isArray(round.retained)) evidence.push(countLabel(round.retained.length, 'asset mantenuto', 'asset mantenuti'));
        if (red.maxCandidateItems != null) evidence.push('massimo configurato: ' + fmt(red.maxCandidateItems) + ' asset');
        for (const group of round.reasons || []) {
          if (group.decision !== 'excluded') continue;
          const count = group.itemIds.length, reason = exclusionText.get(group.reason);
          evidence.push(countLabel(count, 'asset escluso', 'asset esclusi') + (reason ? ' ' + reason : ' (motivo registrato: ' + fmt(group.reason) + ')'));
        }
        if (evidence.length) {
          el(block, 'h5', 'Round ' + fmt(round.index));
          const list = el(block, 'ul');
          evidence.forEach(item => el(list, 'li', item));
        }
      });
      if (red.targetBinary === 0) note(block, 'Criterio di arresto sul target binario disabilitato (target 0).');
      else if (typeof red.targetBinary === 'number' && red.targetBinary > 0 && typeof red.residualBinary === 'number') {
        facts(block, [['Target binario', fmt(red.residualBinary) + ' binarie residue su ' + fmt(red.targetBinary) + (red.residualBinary <= red.targetBinary ? ' (raggiunto)' : ' (non raggiunto)')]]);
        note(block, 'Il target non è il limite di posizioni del portafoglio. Un target non raggiunto non spiega da solo l’arresto.');
      } else note(block, 'Raggiungimento del target binario non determinabile dai dati registrati.');
      if (!red.stopReason && red.roundCount === 1 && red.rounds.length === 1 && (run.status === 'success' || run.status === 'partial_success')) {
        note(block, 'Il primo round ha prodotto un esito positivo. La pipeline arresta l’iterazione al successo prima di verificare il target.');
      }
    });
    table(['Indicatore', 'Baseline', 'Confronto', 'Differenza'], [
      ['Stato riduzione', state(a), state(b), 'Non applicabile'],
      row('Asset originali', a.originalCount, b.originalCount, r.sameInstance), row('Asset mantenuti', count(a), count(b), r.sameInstance),
      reductionRow('Limite dominio candidato', a.reduction.maxCandidateItems, b.reduction.maxCandidateItems),
      row('Round eseguiti', a.reduction.roundCount, b.reduction.roundCount), reductionRow('Massimo round', a.reduction.maxRounds, b.reduction.maxRounds),
      reductionRow('Target binarie (arresto)', a.reduction.targetBinary, b.reduction.targetBinary), row('Binarie residue', a.reduction.residualBinary, b.reduction.residualBinary),
      row('Cardinalità minima portafoglio', a.cardinality.min, b.cardinality.min), row('Cardinalità massima portafoglio', a.cardinality.max, b.cardinality.max),
      ['Motivo arresto registrato', a.reduction.stopReason, b.reduction.stopReason, 'Non applicabile'],
      ['Tentativi di recupero', Array.isArray(a.reduction.recovery) ? a.reduction.recovery.length : null, Array.isArray(b.reduction.recovery) ? b.reduction.recovery.length : null, 'Non applicabile']
    ]);
    const policyFields = [
      ['Policy grafo', 'policy_id'], ['Modalità archi', 'edge_mode'],
      ['Soglia correlazione assoluta', 'correlation_absolute_threshold'],
      ['Differenza relativa massima rendimento', 'near_duplicate_max_relative_return_difference'],
      ['Differenza relativa massima varianza', 'near_duplicate_max_relative_variance_difference'],
      ['Policy peso nodi', 'node_weight_policy_id'], ['Formula peso nodi', 'node_weight_formula_description'],
      ['Normalizzazione peso nodi', 'node_weight_normalization']
    ];
    table(['Policy del grafo', 'Baseline', 'Confronto'], policyFields.map(([label, key]) => [label,
      a.reduction.state === 'not_applicable' ? 'Non applicabile' : a.reduction.policy?.[key],
      b.reduction.state === 'not_applicable' ? 'Non applicabile' : b.reduction.policy?.[key]]));
    details('Differenze di configurazione significative', parent => {
      const fields = [
        ['Solver MIS richiesto', 'mis_solver_id'], ['Penalità archi', 'lambda_edge'],
        ['Campioni richiesti', 'mis_execution.requested_solution_count'], ['Seed MIS', 'mis_execution.random_seed'],
        ['Riparazione abilitata', 'mis_execution.repair_enabled'], ['Letture', 'mis_execution.provider_parameters.num_reads'],
        ['Sweep', 'mis_execution.provider_parameters.num_sweeps'], ['Solver classico', 'classical_solve.classical_solver_id'],
        ['Limite tempo solver configurato', 'classical_solve.time_limit_seconds'], ['Seed solver', 'classical_solve.random_seed']
      ];
      const get = (obj, path) => path.split('.').reduce((value, key) => value?.[key], obj);
      const changes = fields.filter(([, key]) => get(a.config, key) !== get(b.config, key));
      if (changes.length) table(['Configurazione', 'Baseline', 'Confronto'], changes.map(([label, key]) => {
        const values = [get(a.config, key), get(b.config, key)];
        return key === 'classical_solve.time_limit_seconds' ? [label, ...values.map(seconds)] : [label, ...values];
      }), parent);
      else { el(parent, 'p', 'Nessuna differenza registrata nei campi esaminati.'); }
    });
    [a, b].forEach((run, i) => {
      details('Traccia per round - ' + (i ? 'Confronto' : 'Baseline'), parent => {
        if (!run.reduction.rounds.length) { const text = state(run); el(parent, 'p', text); return; }
        run.reduction.rounds.forEach(round => {
          const candidates = Array.isArray(round.candidates) ? round.candidates : null;
          const selected = candidates && candidates.filter(c => c.selection_status === 'selected');
          el(parent, 'h4', 'Round ' + fmt(round.index));
          table(['Dato del round ' + fmt(round.index), 'Valore'], [
            ['Nodi del grafo effettivo', round.graph?.nodes], ['Archi del grafo effettivo', round.graph?.edges],
            ['Backend', round.backend?.id], ['Provider', round.backend?.provider], ['Modalità', round.backend?.mode], ['Dispositivo', round.backend?.device],
            ['Presolve esatto applicato', round.audit?.presolve], ['Codifica dei pesi', round.audit?.weightEncoding],
            ['Strategia impulso', round.audit?.pulseStrategy], ['Minimi fisici indipendenti', round.audit?.physicalIndependent],
            ['Candidati registrati', candidates?.length], ['Candidati usati', selected?.length], ['Campioni usati', Array.isArray(round.usedSamples) ? round.usedSamples.length : null],
            ['Stato candidati usati', selected ? selected.map(c => fmt(c.repair_status)).join(', ') || 'Nessuno' : null],
            ['Dimensioni candidati selezionati', selected ? selected.map(c => fmt(c.num_selected)).join(', ') || 'Nessuno' : null],
            ['Archi violati prima della riparazione', selected ? selected.map(c => fmt(c.num_violated_edges_before_repair)).join(', ') || 'Nessuno' : null],
            ['Riparazioni registrate', selected ? selected.map(c => Array.isArray(c.repair_actions) ? c.repair_actions.length : missing).join(', ') || 'Nessuno' : null],
            ['Completamento classico applicato', selected ? selected.map(c => fmt(c.completion_applied)).join(', ') || 'Nessuno' : null],
            ['Aggiunte classiche registrate', selected ? selected.map(c => Array.isArray(c.completion_actions) ? c.completion_actions.length : missing).join(', ') || 'Nessuno' : null],
            ['Asset mantenuti', Array.isArray(round.retained) ? round.retained.length : null], ['Rapporto di riduzione', round.reductionRatio], ['Motivo arresto', round.terminalReason]
          ], parent);
          if (round.reasons) table(['Decisione', 'Motivo registrato', 'Numero asset', 'Asset'], round.reasons.map(g => [g.decision, g.reason, g.itemIds.length, g.itemIds.join(', ')]), parent);
          else { el(parent, 'p', 'Motivi delle decisioni: ' + missing); }
        });
      });
    });
    heading('Effetto sulla soluzione');
    table(['Indicatore', 'Baseline', 'Confronto', 'Differenza'], [
      row('Obiettivo ricalcolato', a.solution?.objective, b.solution?.objective, r.objective.comparable),
      row('Rendimento atteso', a.solution?.expectedReturn, b.solution?.expectedReturn, r.sameInstance),
      row('Volatilità', a.solution?.volatility, b.solution?.volatility, r.sameInstance),
      row('Gap solver', a.solver.gap, b.solver.gap, false), ['Modello risolto', a.solver.scope, b.solver.scope, 'Non applicabile'],
      ['Ottimalità problema originale', a.solver.originalClaim, b.solver.originalClaim, 'Non applicabile'],
      ['Ottimalità problema residuo', a.solver.residualClaim, b.solver.residualClaim, 'Non applicabile']
    ]);
    paragraph('Il gap riguarda il modello risolto e non certifica automaticamente il problema originale. Le differenze non attribuiscono la causa al campionatore.');
    const labels = {selected_both: 'Scelto in entrambi', available_not_selected: 'Disponibile ma non scelto', excluded_from_domain: 'Escluso dal dominio', domain_unknown: 'Dominio non registrato', comparison_only: 'Solo confronto'};
    if (r.composition.length) table(['Asset', 'Peso baseline', 'Peso confronto', 'Stato'], r.composition.map(c => [c.id, c.baselineWeight, c.comparisonWeight, labels[c.status] || c.status]));
    else paragraph('Composizione confrontabile non disponibile.');
    heading('Dettagli sui tempi');
    note(section, 'Durate, budget e differenze sono arrotondati al secondo dopo il calcolo.');
    details('Tempi e budget effettivo (secondi)', parent => table(['Indicatore', 'Baseline', 'Confronto', 'Differenza'], [
      timeRow('End-to-end', a.timings.endToEnd, b.timings.endToEnd), timeRow('Solver classico', a.timings.classical, b.timings.classical),
      timeRow('MIS', a.timings.mis, b.timings.mis), timeRow('Budget solver', a.timings.budget, b.timings.budget)
    ], parent));
  }
  function update() {
    report.replaceChildren(); swap.disabled = !(runs[0] && runs[1]) || names[0] === names[1];
    if (!runs[0] || !runs[1]) return;
    if (names[0] === names[1]) { status.textContent = 'Scegli due run diversi.'; return; }
    try { render(window.QReduceComparison.compareRuns(runs[0], runs[1])); status.textContent = 'Confronto pronto.'; }
    catch (error) { status.textContent = 'Impossibile confrontare i run: ' + error.message; }
  }
  async function selectRun(index) {
    const version = ++versions[index], id = inputs[index].value;
    runs[index] = null; names[index] = id; update();
    if (!catalog.has(id)) { status.textContent = 'Seleziona due run dal catalogo.'; return; }
    status.textContent = 'Lettura del run ' + id + '…';
    try {
      const core = window.QReduceComparison;
      if (!core) throw new Error('Modulo di confronto non disponibile');
      const imported = await core.importRun(catalog.get(id));
      if (version !== versions[index]) return;
      const run = core.adaptPortfolio(imported);
      if (run.id !== id) throw new Error('Il run-id non coincide con il catalogo.');
      runs[index] = run;
      status.textContent = 'Run caricato. Seleziona anche l’altro run.'; update();
    } catch (error) { if (version === versions[index]) status.textContent = 'Errore nel run ' + id + ': ' + error.message; }
  }
  inputs.forEach((input, index) => input.addEventListener('change', () => selectRun(index)));

  function loadCatalog() {
    return new Promise(resolve => {
      const script = document.createElement('script');
      const url = new URL('../outputs/portfolio_mv/run_catalog.js', document.baseURI);
      // Reload the local classic script; fetch() cannot read it from file://.
      url.searchParams.set('v', String(Date.now()));
      delete window.QReduceRunCatalog;
      function finish(entries) {
        delete window.QReduceRunCatalog;
        script.remove();
        resolve(entries);
      }
      script.onload = () => finish(window.QReduceRunCatalog);
      script.onerror = () => finish(undefined);
      script.src = url.href;
      document.head.appendChild(script);
    });
  }

  async function refreshCatalog(manual = false) {
    const selected = inputs.map(input => input.value);
    refresh.disabled = true;
    inputs.forEach((input, index) => {
      input.disabled = true;
      versions[index]++;
      runs[index] = null;
      names[index] = '';
    });
    update();
    status.textContent = 'Ricaricamento del catalogo locale…';
    try {
      const entries = await loadCatalog();
      catalog.clear();
      if (Array.isArray(entries)) for (const entry of entries) {
        if (typeof entry?.id === 'string' && entry.id && entry.files && typeof entry.files === 'object') catalog.set(entry.id, entry.files);
      }
      inputs.forEach((input, index) => {
        input.replaceChildren();
        el(input, 'option', 'Seleziona un run').value = '';
        for (const id of catalog.keys()) el(input, 'option', id).value = id;
        input.value = catalog.has(selected[index]) ? selected[index] : '';
      });
      if (catalog.size < 2) {
        const catalogMissingOrEmpty = !Array.isArray(entries);
        const catalogTooSmall = Array.isArray(entries) && entries.length < 2;
        let message = '';
        if (catalogMissingOrEmpty) {
          message = 'Catalogo locale non trovato o non valido.';
        } else if (catalogTooSmall) {
          message = 'Il catalogo contiene meno di due run (' + entries.length + ' run).';
        }
        message += ' Per generare o aggiornare il catalogo, esegui dalla root del workspace:';
        status.textContent = message;
        // Show the generation command
        const cmdNote = document.createElement('code');
        cmdNote.textContent = 'python -m qreduce.experiments.portfolio_mv.run_catalog';
        cmdNote.style.display = 'block';
        cmdNote.style.marginTop = '0.5em';
        cmdNote.style.fontSize = '0.85rem';
        status.appendChild(cmdNote);
        const refreshNote = document.createElement('span');
        refreshNote.textContent = 'Dopo la generazione, premi ↻ per ricaricare.';
        refreshNote.style.display = 'block';
        refreshNote.style.marginTop = '0.5em';
        status.appendChild(refreshNote);
        return;
      }
      status.textContent = (manual ? 'Catalogo ricaricato dal disco. ' : '') + 'Seleziona due run dal catalogo.';
      for (const [index, input] of inputs.entries()) {
        if (input.value) await selectRun(index);
      }
      if (manual && (status.textContent === 'Confronto pronto.' || status.textContent.startsWith('Run caricato.'))) {
        status.textContent = 'Catalogo ricaricato dal disco. ' + status.textContent;
      }
    } finally {
      refresh.disabled = false;
      for (const input of inputs) input.disabled = catalog.size < 2;
    }
  }
  swap.addEventListener('click', function () {
    versions[0]++; versions[1]++;
    [runs[0], runs[1]] = [runs[1], runs[0]]; [names[0], names[1]] = [names[1], names[0]];
    inputs.forEach((input, index) => { input.value = names[index]; }); update();
  });
  refresh.addEventListener('click', () => refreshCatalog(true));
  refreshCatalog();
}());


