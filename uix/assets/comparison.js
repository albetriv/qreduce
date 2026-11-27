/* Standalone comparison core: CommonJS in tests, QReduceComparison in a browser. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.QReduceComparison = factory();
}(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  const required = ['run_manifest.json', 'problem.json', 'run_result.json', 'config_used.json', 'experiment_metadata.json'];
  const finite = x => typeof x === 'number' && Number.isFinite(x) ? x : null;
  const object = x => x !== null && typeof x === 'object' && !Array.isArray(x);
  // Effective solver limits use the literal "unlimited"; pipeline config uses zero.
  function budget(value, zeroIsUnlimited = false) {
    if (value === 'unlimited' || (zeroIsUnlimited && value === 0)) return {state: 'unlimited', seconds: null};
    if (finite(value) !== null && value >= 0) return {state: 'numeric', seconds: value};
    return {state: 'unrecorded', seconds: null};
  }
  // Fill missing nested fields from the round artifact without replacing recorded values.
  function mergeRound(extra, main) {
    const result = {...extra};
    for (const [key, value] of Object.entries(main)) {
      result[key] = object(value) && object(result[key]) ? mergeRound(result[key], value) : value;
    }
    return result;
  }
  const bytes = value => typeof value === 'string' ? new TextEncoder().encode(value) : new Uint8Array(value);

  // Generic import that accepts both MV (synthetic-portfolio) and SR (sharpe_portfolio).
  async function importRunGeneric(input, experimentId) {
    const files = {};
    if (input && typeof input[Symbol.iterator] === 'function' && typeof input !== 'string') {
      for (const file of input) {
        if (files[file.name]) throw new Error('Duplicate file: ' + file.name);
        files[file.name] = new Uint8Array(await file.arrayBuffer());
      }
    } else {
      for (const [name, value] of Object.entries(input || {})) files[name] = bytes(value);
    }
    const errors = [], warnings = [], data = {};
    for (const name of [...required, ...Object.keys(files).filter(n => /^round_\d+_result\.json$/.test(n)).sort()]) {
      if (!files[name]) { errors.push('Missing ' + name); continue; }
      const diagnostics = required.includes(name) ? errors : warnings;
      try {
        const parsed = JSON.parse(new TextDecoder('utf-8', {fatal: true}).decode(files[name]));
        if (!object(parsed)) diagnostics.push('Expected JSON object: ' + name);
        else data[name] = parsed;
      } catch (_) { diagnostics.push('Invalid JSON: ' + name); }
    }
    const manifest = data['run_manifest.json'];
    if (manifest && !['1.0', '1.1'].includes(manifest.artifact_schema_version)) errors.push('Unsupported artifact schema: ' + manifest.artifact_schema_version);
    if (manifest && manifest.experiment_id !== experimentId) errors.push('Unsupported experiment: ' + manifest.experiment_id + ' (expected ' + experimentId + ')');
    return {data, problemBytes: files['problem.json'] || null, errors, warnings};
  }

  // Accept browser File objects, or a name -> string/Uint8Array map for callers/tests.
  async function importRun(input) {
    return importRunGeneric(input, 'synthetic-portfolio');
  }

  // Import SR artifacts (sharpe_portfolio experiment).
  async function importRunSharpe(input) {
    return importRunGeneric(input, 'sharpe_portfolio');
  }
  function sameBytes(a, b) {
    return !!a && !!b && a.length === b.length && a.every((v, i) => v === b[i]);
  }
  function adaptPortfolio(imported) {
    const d = imported.data, p = d['problem.json'] || {}, r = d['run_result.json'] || {}, m = d['run_manifest.json'] || {}, c = d['config_used.json'] || {}, meta = d['experiment_metadata.json'] || {};
    const issues = imported.errors.slice(), warnings = (imported.warnings || []).slice();
    if (typeof m.run_id !== 'string' || !m.run_id.trim()) issues.push('Missing run identity');
    for (const [label, identity] of [['result', r.run_result?.run_id], ['config', c.run_identity?.run_id], ['result', r.run_id]]) {
      if (identity != null && identity !== m.run_id) issues.push('Run identity mismatch: ' + label);
    }
    for (const [label, status] of [['result', r.run_result?.run_status], ['result', r.run_status]]) {
      if (status != null && status !== m.run_status) issues.push('Run status mismatch: ' + label);
    }
    const ids = p.asset_ids, values = r.classical_result?.variable_values;
    const returns = Array.isArray(ids) && p.expected_returns ? ids.map((id, i) => Array.isArray(p.expected_returns) ? p.expected_returns[i] : p.expected_returns[id]) : [];
    const validProblem = Array.isArray(ids) && ids.length > 0 && ids.every(id => typeof id === 'string' && id.length > 0) && new Set(ids).size === ids.length && returns.length === ids.length && Array.isArray(p.covariance) && p.covariance.length === ids.length && p.covariance.every(row => Array.isArray(row) && row.length === ids.length && row.every(v => finite(v) !== null)) && returns.every(v => finite(v) !== null);
    if (!validProblem) issues.push('Invalid portfolio problem');
    if (!['success', 'partial_success'].includes(m.run_status)) issues.push('Run did not succeed: ' + m.run_status);
    if (m.run_status === 'partial_success') warnings.push('Partial success: adopted solution is feasible, but the run is incomplete');
    if (r.postcheck_result?.postcheck_feasible !== true) issues.push('Postcheck not passed or unavailable');
    if (r.run_result?.adoption_status != null && r.run_result.adoption_status !== 'adopted') issues.push('Solution not adopted');
    if (m.run_status === 'partial_success' && r.run_result?.adoption_status !== 'adopted') issues.push('Partial success adoption not verified');
    if (r.run_result?.postcheck_status != null && r.run_result.postcheck_status !== 'passed') issues.push('Result postcheck status not passed');
    if (r.run_result?.run_id == null || c.run_identity?.run_id == null) warnings.push('Run identity not verified across all artifacts');
    const classical = m.is_classical_only === true;
    if (classical && (m.has_reduction === true || (Array.isArray(r.round_results) && r.round_results.length > 0) || (Number.isFinite(m.round_count) && m.round_count > 0))) issues.push('Classical run has contradictory reduction evidence');
    if (object(values) && Array.isArray(ids) && ids.some(id => (finite(values['x__' + id]) ?? 0) > 1e-8 && finite(values['delta__' + id]) !== null && values['delta__' + id] <= 0.5)) issues.push('Positive weight conflicts with selection');
    const domains = [r.final_retained_item_ids, m.fixing_manifest?.retained_item_ids, r.cumulative_fixing_manifest?.retained_item_ids].filter(x => x != null);
    const validDomain = domain => Array.isArray(domain) && validProblem && domain.every(id => ids.includes(id)) && new Set(domain).size === domain.length;
    const equalDomain = (a, b) => a.length === b.length && a.every(id => b.includes(id));
    if (domains.some(x => !validDomain(x))) issues.push('Invalid retained domain');
    const goodDomains = domains.filter(validDomain);
    if (goodDomains.some(x => !equalDomain(x, goodDomains[0]))) issues.push('Conflicting retained domains');
    if (classical && goodDomains.some(x => !equalDomain(x, ids))) issues.push('Classical retained domain is not full');
    const retained = validProblem && !issues.some(x => /retained domain/.test(x)) ? (classical ? ids.slice() : goodDomains[0] ?? null) : null;
    if (retained && object(values) && ids.some(id => !retained.includes(id) && ((finite(values['x__' + id]) ?? 0) > 1e-8 || (finite(values['delta__' + id]) ?? 0) > 0.5))) issues.push('Selected asset outside retained domain');
    const rounds = [], roundIndices = new Set();
    const recordedRounds = r.round_results;
    if (recordedRounds != null && !Array.isArray(recordedRounds)) warnings.push('Traccia della riduzione incompleta: elenco dei round non valido.');
    for (const round of Array.isArray(recordedRounds) ? recordedRounds : []) {
      if (!object(round) || !Number.isSafeInteger(round.round_index) || round.round_index < 0 || roundIndices.has(round.round_index)) {
        warnings.push('Traccia della riduzione incompleta: record di round non valido o duplicato ignorato.');
        continue;
      }
      roundIndices.add(round.round_index);
      rounds.push(round);
    }
    const verified = !issues.length && r.postcheck_result?.postcheck_feasible === true;
    let solution = null;
    if (verified && validProblem && values && ids.every(id => finite(values['x__' + id]) !== null)) {
      const weights = ids.map(id => values['x__' + id]);
      const expectedReturn = weights.reduce((sum, w, i) => sum + w * returns[i], 0);
      const variance = weights.reduce((sum, w, i) => sum + w * weights.reduce((s, v, j) => s + v * p.covariance[i][j], 0), 0);
      solution = {objective: finite(r.postcheck_result.objective_recomputed), expectedReturn: finite(expectedReturn), volatility: Number.isFinite(variance) && variance >= -1e-12 ? Math.sqrt(Math.max(0, variance)) : null, weights: Object.fromEntries(ids.map((id, i) => [id, weights[i]])), selected: ids.filter((id, i) => finite(values['delta__' + id]) !== null ? values['delta__' + id] > 0.5 : weights[i] > 1e-8)};
    } else if (verified) issues.push('Solution weights unavailable');
    const declared = object(m.files) ? m.files : {};
    for (const name of Object.keys(d).filter(n => /^round_\d+_result\.json$/.test(n))) {
      const round = d[name], index = Number(name.match(/^round_(\d+)_result\.json$/)[1]);
      if (!Object.hasOwn(declared, name)) { warnings.push('Ignored undeclared round artifact: ' + name); continue; }
      if (round.round_index !== index) { warnings.push('Ignored mismatched round artifact: ' + name); continue; }
      const i = rounds.findIndex(x => x.round_index === index);
      if (i < 0) { warnings.push('Ignored unmatched round artifact: ' + name); continue; }
      rounds[i] = mergeRound(round, rounds[i]);
    }
    for (const name of Object.keys(declared).filter(n => /^round_\d+_result\.json$/.test(n))) {
      if (!d[name]) warnings.push('Declared round artifact unavailable: ' + name);
    }
    rounds.sort((a, b) => (finite(a.round_index) ?? Infinity) - (finite(b.round_index) ?? Infinity));
    const trace = rounds.map(round => {
      const job = round.mis_compilation_result?.compiled_job, graph = job?.compiled_problem?.graph;
      const records = round.candidate_domain_item_records;
      const reasons = [];
      for (const item of Array.isArray(records) ? records.filter(object) : []) { let group = reasons.find(x => x.reason === item.reason && x.decision === item.decision); if (!group) reasons.push(group = {reason: item.reason, decision: item.decision, itemIds: []}); group.itemIds.push(item.item_id); }
      return {index: round.round_index, inputIds: Array.isArray(graph?.node_ids) ? graph.node_ids.slice() : null, graph: graph ? {nodes: Array.isArray(graph.node_ids) ? graph.node_ids.length : null, edges: Array.isArray(graph.edges) ? graph.edges.length : null} : null, audit: job ? {presolve: job.provider_payload?.presolve_applied ?? (job.effective_backend_id === "presolve_exact" ? true : null), weightEncoding: job.provider_payload?.weight_encoding_mode ?? null, pulseStrategy: job.provider_payload?.pulse_strategy?.strategy_id ?? null, physicalIndependent: job.provider_payload?.physical_vs_canonical?.all_ground_states_independent ?? job.provider_payload?.physical_vs_canonical?.physical_is_independent ?? null} : null, backend: job ? {id: job.effective_backend_id, provider: job.effective_provider_id, mode: job.execution_mode, device: job.effective_device_id} : null, candidates: Array.isArray(round.candidate_records) ? round.candidate_records.filter(object) : null, usedSamples: Array.isArray(round.selected_mis_samples) ? round.selected_mis_samples : null, retained: round.retained_item_ids ?? null, reductionRatio: finite(round.round_reduction_ratio), reasons: Array.isArray(records) ? reasons : null, terminalReason: round.terminal_reason ?? null};
    });
    return {id: m.run_id ?? null, issues, warnings, status: m.run_status ?? null, problemBytes: imported.problemBytes, sense: r.objective_sense ?? null, solution, retained, originalCount: validProblem ? ids.length : null, reduction: {state: classical ? 'not_applicable' : trace.length ? 'available' : 'not_recorded', applied: classical ? false : m.has_reduction === true ? true : null, rounds: trace, policy: meta.portfolio_graph_policy ?? null, maxCandidateItems: c.reduction?.candidate_domain_max_items ?? null, maxRounds: c.reduction?.max_reduction_rounds ?? null, targetBinary: c.reduction?.target_binary_variables ?? null, residualBinary: r.residual_variable_counts?.binary_free ?? null, roundCount: m.round_count ?? null, recovery: r.recovery_attempts ?? null, stopReason: r.run_result?.terminal_reason ?? null}, cardinality: {min: p.min_selected_assets ?? null, max: p.max_selected_assets ?? null}, solver: {gap: finite(r.classical_result?.gap), scope: classical ? 'full' : m.has_reduction === true ? 'reduced' : 'unknown', originalClaim: r.original_problem_optimality_claim ?? null, residualClaim: r.residual_problem_optimality_claim ?? null}, timings: {endToEnd: finite(r.metrics?.end_to_end_runtime_seconds), classical: finite(r.classical_result?.runtime_seconds), mis: finite(r.metrics?.mis_runtime_seconds), budget: r.classical_result?.effective_solver_parameters?.time_limit_seconds ?? null}, config: c};
  }
  // Adapt SR (Sharpe Portfolio) artifacts to the common comparison model.
  // Uses tickers, mean_returns, scaled weights and Sharpe ratio as the quality metric.
  function adaptSharpePortfolio(imported) {
    const d = imported.data, p = d['problem.json'] || {}, r = d['run_result.json'] || {}, m = d['run_manifest.json'] || {}, c = d['config_used.json'] || {}, meta = d['experiment_metadata.json'] || {};
    const issues = imported.errors.slice(), warnings = (imported.warnings || []).slice();
    if (typeof m.run_id !== 'string' || !m.run_id.trim()) issues.push('Missing run identity');
    for (const [label, identity] of [['result', r.run_result?.run_id], ['config', c.run_identity?.run_id], ['result', r.run_id]]) {
      if (identity != null && identity !== m.run_id) issues.push('Run identity mismatch: ' + label);
    }
    for (const [label, status] of [['result', r.run_result?.run_status], ['result', r.run_status]]) {
      if (status != null && status !== m.run_status) issues.push('Run status mismatch: ' + label);
    }
    // Read ticker identifiers and expected returns.
    const ids = p.tickers, values = r.classical_result?.variable_values;
    const returns = Array.isArray(ids) && p.mean_returns ? ids.map((id, i) => Array.isArray(p.mean_returns) ? p.mean_returns[i] : p.mean_returns[id]) : [];
    const validProblem = Array.isArray(ids) && ids.length > 0 && ids.every(id => typeof id === 'string' && id.length > 0) && new Set(ids).size === ids.length && returns.length === ids.length && Array.isArray(p.covariance) && p.covariance.length === ids.length && p.covariance.every(row => Array.isArray(row) && row.length === ids.length && row.every(v => finite(v) !== null)) && returns.every(v => finite(v) !== null);
    if (!validProblem) issues.push('Invalid portfolio problem');
    if (!['success', 'partial_success'].includes(m.run_status)) issues.push('Run did not succeed: ' + m.run_status);
    if (m.run_status === 'partial_success') warnings.push('Partial success: adopted solution is feasible, but the run is incomplete');
    if (r.postcheck_result?.postcheck_feasible !== true) issues.push('Postcheck not passed or unavailable');
    // SR requires explicit adoption for all successful runs, not just when adoption_status is recorded
    if (r.run_result?.adoption_status !== 'adopted') issues.push('Solution not adopted');
    if (r.run_result?.postcheck_status != null && r.run_result.postcheck_status !== 'passed') issues.push('Result postcheck status not passed');
    if (r.run_result?.run_id == null || c.run_identity?.run_id == null) warnings.push('Run identity not verified across all artifacts');
    const classical = m.is_classical_only === true;
    if (classical && (m.has_reduction === true || (Array.isArray(r.round_results) && r.round_results.length > 0) || (Number.isFinite(m.round_count) && m.round_count > 0))) issues.push('Classical run has contradictory reduction evidence');
    // SR uses x_scaled__<ticker> / x_scale for weights
    const xScale = finite(values?.x_scale);
    const tolerance = key => {
      const value = finite(r.postcheck_result?.tolerances_used?.[key]);
      return value !== null && value >= 0 ? value : null;
    };
    const primalTolerance = tolerance('primal_feasibility');
    const integralityTolerance = tolerance('integrality');
    // Historic runs without tolerances retain the original weight and binary checks.
    const legacyWeightTolerance = 1e-8;
    if (object(values) && Array.isArray(ids) && xScale && xScale > 0) {
      const hasConflict = ids.some(id => {
        const scaledWeight = finite(values['x_scaled__' + id]);
        const delta = finite(values['delta__' + id]);
        const realWeight = scaledWeight != null && xScale > 0 ? scaledWeight / xScale : 0;
        return realWeight > (primalTolerance ?? legacyWeightTolerance) && delta !== null && delta <= 0.5;
      });
      if (hasConflict) issues.push('Positive weight conflicts with selection');
    }
    const domains = [r.final_retained_item_ids, m.fixing_manifest?.retained_item_ids, r.cumulative_fixing_manifest?.retained_item_ids].filter(x => x != null);
    const validDomain = domain => Array.isArray(domain) && validProblem && domain.every(id => ids.includes(id)) && new Set(domain).size === domain.length;
    const equalDomain = (a, b) => a.length === b.length && a.every(id => b.includes(id));
    if (domains.some(x => !validDomain(x))) issues.push('Invalid retained domain');
    const goodDomains = domains.filter(validDomain);
    if (goodDomains.some(x => !equalDomain(x, goodDomains[0]))) issues.push('Conflicting retained domains');
    if (classical && goodDomains.some(x => !equalDomain(x, ids))) issues.push('Classical retained domain is not full');
    const retained = validProblem && !issues.some(x => /retained domain/.test(x)) ? (classical ? ids.slice() : goodDomains[0] ?? null) : null;
    // Check selected assets outside retained domain using SR variable names
    if (retained && object(values) && xScale && xScale > 0 && ids.some(id => {
      if (retained.includes(id)) return false;
      const scaledWeight = finite(values['x_scaled__' + id]);
      const delta = finite(values['delta__' + id]);
      const realWeight = scaledWeight != null ? scaledWeight / xScale : 0;
      const weightConflict = primalTolerance === null
        ? realWeight > legacyWeightTolerance : Math.abs(scaledWeight ?? 0) > primalTolerance;
      const binaryConflict = integralityTolerance === null
        ? (delta ?? 0) > 0.5 : Math.abs(delta ?? 0) > integralityTolerance;
      return weightConflict || binaryConflict;
    })) issues.push('Selected asset outside retained domain');
    const rounds = [], roundIndices = new Set();
    const recordedRounds = r.round_results;
    if (recordedRounds != null && !Array.isArray(recordedRounds)) warnings.push('Traccia della riduzione incompleta: elenco dei round non valido.');
    for (const round of Array.isArray(recordedRounds) ? recordedRounds : []) {
      if (!object(round) || !Number.isSafeInteger(round.round_index) || round.round_index < 0 || roundIndices.has(round.round_index)) {
        warnings.push('Traccia della riduzione incompleta: record di round non valido o duplicato ignorato.');
        continue;
      }
      roundIndices.add(round.round_index);
      rounds.push(round);
    }
    const verified = !issues.length && r.postcheck_result?.postcheck_feasible === true;
    let solution = null;
    // Extract Sharpe ratio from domain_evaluation_metrics (SR's primary quality metric)
    const domainMetrics = Array.isArray(r.domain_evaluation_metrics) ? r.domain_evaluation_metrics : [];
    const metricValue = id => { const m = domainMetrics.find(x => x?.metric_id === id); return m ? finite(m.value) : null; };
    const countValue = id => {
      const count = metricValue(id) ?? r.postcheck_result?.tolerances_used?.[id];
      return Number.isSafeInteger(count) && count >= 0 && count <= ids.length ? count : null;
    };
    const sharpeRatio = metricValue('sharpe_ratio');
    if (verified && validProblem && values && xScale && xScale > 0 && ids.every(id => finite(values['x_scaled__' + id]) !== null)) {
      const weights = ids.map(id => values['x_scaled__' + id] / xScale);
      const expectedReturn = metricValue('expected_return') ?? weights.reduce((sum, w, i) => sum + w * returns[i], 0);
      const computedVariance = weights.reduce((sum, w, i) => sum + w * weights.reduce((s, v, j) => s + v * p.covariance[i][j], 0), 0);
      const volatility = metricValue('volatility') ?? (Number.isFinite(computedVariance) && computedVariance >= -1e-12 ? Math.sqrt(Math.max(0, computedVariance)) : null);
      // For SR, objective is Sharpe ratio (higher is better); do NOT fallback to objective_recomputed (which is variance)
      // If Sharpe ratio is missing, objective is null and quality comparison is not available
      const selectionRecorded = ids.every(id => finite(values['delta__' + id]) !== null);
      solution = {objective: sharpeRatio, sharpeRatio, expectedReturn: finite(expectedReturn), volatility: finite(volatility), weights: Object.fromEntries(ids.map((id, i) => [id, weights[i]])), selected: selectionRecorded ? ids.filter(id => values['delta__' + id] > 0.5) : null};
      // Recorded counts use the solver's selection variables and the postcheck's
      // weight tolerance, respectively; neither is implied by composition length.
      solution.selectedCount = countValue('selected_count');
      solution.investedCount = countValue('position_count');
      if (sharpeRatio === null) warnings.push('Sharpe ratio metric unavailable; quality comparison disabled');
    } else if (verified) issues.push('Solution weights unavailable');
    const declared = object(m.files) ? m.files : {};
    for (const name of Object.keys(d).filter(n => /^round_\d+_result\.json$/.test(n))) {
      const round = d[name], index = Number(name.match(/^round_(\d+)_result\.json$/)[1]);
      if (!Object.hasOwn(declared, name)) { warnings.push('Ignored undeclared round artifact: ' + name); continue; }
      if (round.round_index !== index) { warnings.push('Ignored mismatched round artifact: ' + name); continue; }
      const i = rounds.findIndex(x => x.round_index === index);
      if (i < 0) { warnings.push('Ignored unmatched round artifact: ' + name); continue; }
      rounds[i] = mergeRound(round, rounds[i]);
    }
    for (const name of Object.keys(declared).filter(n => /^round_\d+_result\.json$/.test(n))) {
      if (!d[name]) warnings.push('Declared round artifact unavailable: ' + name);
    }
    rounds.sort((a, b) => (finite(a.round_index) ?? Infinity) - (finite(b.round_index) ?? Infinity));
    const trace = rounds.map(round => {
      const job = round.mis_compilation_result?.compiled_job, graph = job?.compiled_problem?.graph;
      const records = round.candidate_domain_item_records;
      const reasons = [];
      for (const item of Array.isArray(records) ? records.filter(object) : []) { let group = reasons.find(x => x.reason === item.reason && x.decision === item.decision); if (!group) reasons.push(group = {reason: item.reason, decision: item.decision, itemIds: []}); group.itemIds.push(item.item_id); }
      return {index: round.round_index, inputIds: Array.isArray(graph?.node_ids) ? graph.node_ids.slice() : null, graph: graph ? {nodes: Array.isArray(graph.node_ids) ? graph.node_ids.length : null, edges: Array.isArray(graph.edges) ? graph.edges.length : null} : null, audit: job ? {presolve: job.provider_payload?.presolve_applied ?? (job.effective_backend_id === "presolve_exact" ? true : null), weightEncoding: job.provider_payload?.weight_encoding_mode ?? null, pulseStrategy: job.provider_payload?.pulse_strategy?.strategy_id ?? null, physicalIndependent: job.provider_payload?.physical_vs_canonical?.all_ground_states_independent ?? job.provider_payload?.physical_vs_canonical?.physical_is_independent ?? null} : null, backend: job ? {id: job.effective_backend_id, provider: job.effective_provider_id, mode: job.execution_mode, device: job.effective_device_id} : null, candidates: Array.isArray(round.candidate_records) ? round.candidate_records.filter(object) : null, usedSamples: Array.isArray(round.selected_mis_samples) ? round.selected_mis_samples : null, retained: round.retained_item_ids ?? null, reductionRatio: finite(round.round_reduction_ratio), reasons: Array.isArray(records) ? reasons : null, terminalReason: round.terminal_reason ?? null};
    });
    // SR optimizes Sharpe ratio (maximize); sense in comparison should reflect that
    // The objective_sense in result is 'minimize' (variance), but for comparison we use Sharpe
    const comparisonSense = 'maximize'; // Sharpe ratio is higher-is-better
    // Historical SR artifacts did not record a minimum investment.
    const lowerBounds = object(p.lower_bounds) ? p.lower_bounds : null;
    const lowerBound = lowerBounds ? null : p.lower_bound == null ? 0 : finite(p.lower_bound);
    return {id: m.run_id ?? null, issues, warnings, status: m.run_status ?? null, problemBytes: imported.problemBytes, lowerBound, lowerBounds, sense: comparisonSense, solution, retained, originalCount: validProblem ? ids.length : null, reduction: {state: classical ? 'not_applicable' : trace.length ? 'available' : 'not_recorded', applied: classical ? false : m.has_reduction === true ? true : null, rounds: trace, policy: meta.graph_policy ?? null, maxCandidateItems: c.reduction?.candidate_domain_max_items ?? null, maxRounds: c.reduction?.max_reduction_rounds ?? null, targetBinary: c.reduction?.target_binary_variables ?? null, residualBinary: r.residual_variable_counts?.binary_free ?? null, roundCount: m.round_count ?? null, recovery: r.recovery_attempts ?? null, stopReason: r.run_result?.terminal_reason ?? null}, cardinality: {min: p.min_selected_assets ?? null, max: p.max_positions ?? null}, solver: {gap: finite(r.classical_result?.gap), scope: classical ? 'full' : m.has_reduction === true ? 'reduced' : 'unknown', originalClaim: r.original_problem_optimality_claim ?? null, residualClaim: r.residual_problem_optimality_claim ?? null}, timings: {endToEnd: finite(r.metrics?.end_to_end_runtime_seconds), classical: finite(r.classical_result?.runtime_seconds), mis: finite(r.metrics?.mis_runtime_seconds), budget: r.classical_result?.effective_solver_parameters?.time_limit_seconds ?? null}, config: c};
  }
  // Round totals are verified from actual graph IDs and retained IDs, never inferred
  // from the configured cap or from the number of recorded decisions.
  function roundSeries(round) {
    const input = round.inputIds, retained = round.retained;
    const valid = Array.isArray(input) && Array.isArray(retained) &&
      input.every(id => typeof id === 'string') && retained.every(id => typeof id === 'string') &&
      new Set(input).size === input.length && new Set(retained).size === retained.length &&
      retained.every(id => input.includes(id));
    const excluded = valid ? new Set(input.filter(id => !retained.includes(id))) : null;
    const seen = new Set(), counts = new Map(), decisions = new Map();
    let consistent = true;
    for (const group of round.reasons || []) {
      if (!Array.isArray(group.itemIds)) { consistent = false; continue; }
      for (const id of group.itemIds) {
        if (decisions.has(id) && decisions.get(id) !== group.decision) consistent = false;
        else decisions.set(id, group.decision);
        if (valid && group.decision === 'retained' && !retained.includes(id)) consistent = false;
      }
      if (group.decision !== 'excluded') continue;
      for (const id of group.itemIds) {
        if (typeof id !== 'string' || seen.has(id) || (excluded && !excluded.has(id))) { consistent = false; continue; }
        seen.add(id);
        const reason = typeof group.reason === 'string' && group.reason ? group.reason : 'undocumented';
        counts.set(reason, (counts.get(reason) || 0) + 1);
      }
    }
    const total = excluded && consistent ? excluded.size : null;
    if (total !== null) {
      const missing = total - seen.size;
      if (missing > 0) counts.set('undocumented', (counts.get('undocumented') || 0) + missing);
    }
    return {index: round.index, graph: round.graph, excluded: total,
      reasons: consistent ? [...counts].map(([reason, count]) => ({reason, count, percent: total > 0 ? count / total * 100 : null})) : []};
  }
  function dashboardModel(baseline, comparison, sameInstance, objective, composition) {
    const initial = comparison.originalCount;
    const final = comparison.retained ? comparison.retained.length : null;
    const domain = {initial, final, excluded: initial !== null && final !== null ? initial - final : null,
      reductionPercent: initial > 0 && final !== null ? (initial - final) / initial * 100 : null,
      cap: comparison.reduction.maxCandidateItems};
    const statuses = ['selected_both', 'available_not_selected', 'excluded_from_domain', 'domain_unknown'];
    const positions = Array.isArray(baseline.solution?.selected) && Array.isArray(comparison.solution?.selected) && sameInstance ?
      statuses.map(status => ({status, count: composition.filter(item => item.status === status).length})) : null;
    const sense = String(baseline.sense).toLowerCase();
    const direction = ['min', 'minimize'].includes(sense) ? -1 : ['max', 'maximize'].includes(sense) ? 1 : 0;
    const state = value => value === null ? 'unknown' : value === 0 ? 'unchanged' : value > 0 ? 'improved' : 'worsened';
    const quality = {...objective, baseline: baseline.solution?.objective ?? null, comparison: comparison.solution?.objective ?? null,
      direction: objective.delta !== null && direction ? state(objective.delta * direction) : 'unknown'};
    function time(key) {
      const a = finite(baseline.timings[key]), b = finite(comparison.timings[key]);
      const valid = a !== null && b !== null && a >= 0 && b >= 0;
      return {baseline: a, comparison: b, delta: valid ? b - a : null,
        percent: valid && a !== 0 ? (b - a) / a * 100 : null,
        ratio: valid && a !== 0 ? b / a : null,
        direction: valid && sameInstance ? state(a - b) : 'unknown'};
    }
    const solverTime = time('classical'), endToEnd = time('endToEnd');
    const reasons = [];
    if (!sameInstance) reasons.push('instance_unverified');
    if (!baseline.solution || !comparison.solution) reasons.push('invalid_solution');
    if (baseline.reduction.applied !== false) reasons.push('baseline_not_verified_unreduced');
    if (comparison.reduction.applied !== true) reasons.push('comparison_not_verified_reduced');
    if (quality.direction === 'unknown' || endToEnd.direction === 'unknown') reasons.push('insufficient_metrics');
    let verdict = null;
    if (!reasons.length) {
      const axes = [quality.direction, endToEnd.direction];
      verdict = axes.includes('improved') && axes.includes('worsened') ? 'tradeoff' :
        axes.includes('worsened') ? 'no_overall_advantage' :
        axes.includes('improved') ? (axes.includes('unchanged') ? 'partially_favorable' : 'favorable') : 'unchanged';
    }
    return {domain, rounds: comparison.reduction.rounds.map(roundSeries), positions,
      thermometer: {quality, solverTime, endToEnd, domain,
        budgets: {
          solver: {baseline: budget(baseline.timings.budget), comparison: budget(comparison.timings.budget)},
          pipeline: {baseline: budget(baseline.config?.reduction?.max_end_to_end_runtime_seconds, true), comparison: budget(comparison.config?.reduction?.max_end_to_end_runtime_seconds, true)}
        }},
      verdict: {value: verdict, reasons, quality: quality.direction, endToEnd: endToEnd.direction}};
  }
  function compareRuns(baseline, comparison) {
    const sameInstance = sameBytes(baseline.problemBytes, comparison.problemBytes);
    const a = baseline.solution, b = comparison.solution;
    const comparable = sameInstance && !!a && !!b && a.objective !== null && b.objective !== null && baseline.sense != null && baseline.sense === comparison.sense;
    const delta = comparable ? b.objective - a.objective : null;
    const retained = comparison.retained && new Set(comparison.retained);
    const selectedB = new Set(b?.selected || []), selectedA = new Set(a?.selected || []);
    const composition = a && b && sameInstance && Array.isArray(a.selected) && Array.isArray(b.selected) ? [...new Set([...a.selected, ...b.selected])].map(id => ({id, baselineWeight: a.weights[id] ?? null, comparisonWeight: b.weights[id] ?? null, status: selectedA.has(id) ? selectedB.has(id) ? 'selected_both' : retained ? retained.has(id) ? 'available_not_selected' : 'excluded_from_domain' : 'domain_unknown' : 'comparison_only'})) : [];
    const warnings = [...baseline.issues, ...(baseline.warnings || [])].map(x => 'Baseline: ' + x).concat([...comparison.issues, ...(comparison.warnings || [])].map(x => 'Comparison: ' + x));
    if (!sameInstance) warnings.push('Instance identity not verified');
    if (!comparable) warnings.push('Objective comparison unavailable');
    const objective = {comparable, delta, percent: delta !== null && a.objective !== 0 ? delta / Math.abs(a.objective) * 100 : null};
    const dashboard = dashboardModel(baseline, comparison, sameInstance, objective, composition);
    return {baseline, comparison, sameInstance, objective, composition, dashboard, baselineExcludedCount: a && b && Array.isArray(a.selected) && Array.isArray(b.selected) && sameInstance && retained ? composition.filter(x => x.status === 'excluded_from_domain').length : null, warnings};
  }
  return {importRun, importRunSharpe, adaptPortfolio, adaptSharpePortfolio, compareRuns};
}));
