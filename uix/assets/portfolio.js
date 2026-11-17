/**
 * QReduce Portfolio Experiment Configurator
 *
 * Generates CLI commands for: poetry run python -m qreduce.experiments.portfolio
 */

(function () {
  "use strict";

  var C = QReduceCommon;

  // Default values for reset
  var defaults = {
    runId: "ui_portfolio_001",
    outputRoot: "outputs/portfolio",
    logConfig: "",
    assetCount: "30",
    generationSeed: "42",
    observationCount: "",
    edgeMode: "near_duplicate",
    correlationThreshold: "0.90",
    returnDifference: "0.10",
    varianceDifference: "0.10",
    lowerBound: "0.0",
    upperBound: "0.7",
    minSelectedAssets: "",
    maxSelectedAssets: "",
    maxRounds: "1",
    minItems: "",
    maxItems: "",
    targetBinary: "",
    minReductionRatio: "",
    endToEndBudget: "",
    domainRecovery: "fail",
    infeasibleRecovery: "fail",
    recoveryAttempts: "",
    misSolver: "local_greedy",
    classicalSolver: "scip",
    numReads: "",
    numSweeps: "",
    modelExport: false,
    modelExportPath: "",
  };

  /**
   * Check if a value is a finite number.
   * @param {number|null} val
   * @returns {boolean}
   */
  function isFiniteNumber(val) {
    return val !== null && Number.isFinite(val);
  }

  /**
   * Check if reduction is active (rounds > 0).
   * @returns {boolean}
   */
  function isReductionActive() {
    var maxRounds = C.number("maxRounds");
    return maxRounds !== null && maxRounds > 0;
  }

  /**
   * Check if D-Wave solver is selected.
   * @returns {boolean}
   */
  function isDwaveSolver() {
    return C.value("misSolver") === "dwave_simulated_annealing";
  }

  /**
   * Check if near_duplicate edge mode is selected.
   * @returns {boolean}
   */
  function isNearDuplicateMode() {
    return C.value("edgeMode") === "near_duplicate";
  }

  /**
   * Validate all fields and return whether the form is valid.
   * @returns {boolean}
   */
  function validate() {
    var valid = true;
    var form = C.$("configForm");
    C.clearErrors(form);

    function require(id, condition, message) {
      if (!condition) {
        C.setError(id, message);
        valid = false;
      }
    }

    var reductionActive = isReductionActive();

    // Run ID is required and must not be empty/whitespace
    require("runId", C.value("runId") !== "", "L'ID del run è obbligatorio.");

    // Asset count must be integer >= 6
    var assetCount = C.number("assetCount");
    require(
      "assetCount",
      isFiniteNumber(assetCount) && Number.isInteger(assetCount) && assetCount >= 6,
      "Inserisci un intero >= 6."
    );

    // Generation seed must be integer if provided
    var genSeed = C.number("generationSeed");
    if (genSeed !== null) {
      require(
        "generationSeed",
        isFiniteNumber(genSeed) && Number.isInteger(genSeed),
        "Inserisci un intero."
      );
    }

    // Observation count if provided must be integer >= 10 * asset_count
    var observations = C.number("observationCount");
    if (observations !== null) {
      require(
        "observationCount",
        isFiniteNumber(observations) && Number.isInteger(observations) && observations > 0,
        "Inserisci un intero positivo."
      );
      if (assetCount !== null && observations < assetCount * 10) {
        require(
          "observationCount",
          false,
          "Servono almeno 10 osservazioni per asset."
        );
      }
    }

    // Correlation threshold must be finite number in [0, 1]
    var corrThresh = C.number("correlationThreshold");
    require(
      "correlationThreshold",
      isFiniteNumber(corrThresh) && corrThresh >= 0 && corrThresh <= 1,
      "Il valore deve essere un numero fra 0 e 1."
    );

    // Near-duplicate params: validate only if near_duplicate mode is active
    if (isNearDuplicateMode()) {
      var returnDiff = C.number("returnDifference");
      if (returnDiff !== null) {
        require(
          "returnDifference",
          isFiniteNumber(returnDiff) && returnDiff >= 0,
          "Inserisci un numero >= 0."
        );
      }
      var varianceDiff = C.number("varianceDifference");
      if (varianceDiff !== null) {
        require(
          "varianceDifference",
          isFiniteNumber(varianceDiff) && varianceDiff >= 0,
          "Inserisci un numero >= 0."
        );
      }
    }

    // Investment bounds validation
    var lowerBound = C.number("lowerBound");
    var upperBound = C.number("upperBound");
    require(
      "lowerBound",
      isFiniteNumber(lowerBound) && lowerBound >= 0,
      "Inserisci un numero >= 0."
    );
    require(
      "upperBound",
      isFiniteNumber(upperBound) && upperBound > 0,
      "Inserisci un numero > 0."
    );
    if (isFiniteNumber(lowerBound) && isFiniteNumber(upperBound) && upperBound < lowerBound) {
      require("upperBound", false, "Deve essere >= investimento minimo.");
    }

    // Cardinality validation
    var minSelected = C.number("minSelectedAssets");
    var maxSelected = C.number("maxSelectedAssets");
    if (minSelected !== null) {
      require(
        "minSelectedAssets",
        isFiniteNumber(minSelected) && Number.isInteger(minSelected) && minSelected >= 0,
        "Inserisci un intero >= 0."
      );
      if (assetCount !== null && minSelected > assetCount) {
        require("minSelectedAssets", false, "Non può superare il numero di asset.");
      }
    }
    if (maxSelected !== null) {
      require(
        "maxSelectedAssets",
        isFiniteNumber(maxSelected) && Number.isInteger(maxSelected) && maxSelected >= 1,
        "Inserisci un intero >= 1."
      );
      if (assetCount !== null && maxSelected > assetCount) {
        require("maxSelectedAssets", false, "Non può superare il numero di asset.");
      }
    }
    if (minSelected !== null && maxSelected !== null && minSelected > maxSelected) {
      require("maxSelectedAssets", false, "Deve essere >= min asset selezionati.");
    }

    // Max rounds must be non-negative integer
    var maxRounds = C.number("maxRounds");
    require(
      "maxRounds",
      isFiniteNumber(maxRounds) && Number.isInteger(maxRounds) && maxRounds >= 0,
      "Inserisci un intero >= 0."
    );

    // Budget is always validated (applies to both baseline and reduction)
    var budget = C.number("endToEndBudget");
    if (budget !== null) {
      require(
        "endToEndBudget",
        isFiniteNumber(budget) && budget > 0,
        "Il budget deve essere un numero > 0."
      );
    }

    // Reduction-specific validations: only validate if reduction is active
    // When disabled, these fields' values are ignored (not serialized)
    if (reductionActive) {
      // Min/max items validation
      var minItems = C.number("minItems");
      var maxItems = C.number("maxItems");
      if (minItems !== null) {
        require(
          "minItems",
          isFiniteNumber(minItems) && Number.isInteger(minItems) && minItems >= 0,
          "Inserisci un intero >= 0."
        );
      }
      if (maxItems !== null) {
        require(
          "maxItems",
          isFiniteNumber(maxItems) && Number.isInteger(maxItems) && maxItems >= 0,
          "Inserisci un intero >= 0."
        );
        if (minItems !== null && maxItems < minItems) {
          require("maxItems", false, "Deve essere >= min item.");
        }
      }

      // Target binary variables if provided must be non-negative integer
      var targetBinary = C.number("targetBinary");
      if (targetBinary !== null) {
        require(
          "targetBinary",
          isFiniteNumber(targetBinary) && Number.isInteger(targetBinary) && targetBinary >= 0,
          "Inserisci un intero >= 0."
        );
      }

      // Min reduction ratio if provided must be in [0, 1]
      var minRatio = C.number("minReductionRatio");
      if (minRatio !== null) {
        require(
          "minReductionRatio",
          isFiniteNumber(minRatio) && minRatio >= 0 && minRatio <= 1,
          "Il valore deve essere un numero fra 0 e 1."
        );
      }

      // Recovery validation: only validate when reduction is active
      var domainRecovery = C.value("domainRecovery");
      var infeasibleRecovery = C.value("infeasibleRecovery");
      var recoveryAttempts = C.number("recoveryAttempts");
      var recoveryPolicyActive = domainRecovery !== "fail" || infeasibleRecovery !== "fail";

      // If recovery policy is active, attempts must be >= 1
      if (recoveryPolicyActive) {
        require(
          "recoveryAttempts",
          recoveryAttempts !== null && Number.isInteger(recoveryAttempts) && recoveryAttempts >= 1,
          "Il recovery richiede almeno 1 tentativo."
        );
      }
      // Validate recovery attempts is non-negative integer if provided
      if (recoveryAttempts !== null) {
        require(
          "recoveryAttempts",
          isFiniteNumber(recoveryAttempts) && Number.isInteger(recoveryAttempts) && recoveryAttempts >= 0,
          "Inserisci un intero >= 0."
        );
      }

      // D-Wave params validation: only if D-Wave solver is selected AND reduction active
      if (isDwaveSolver()) {
        var numReads = C.number("numReads");
        if (numReads !== null) {
          require(
            "numReads",
            isFiniteNumber(numReads) && Number.isInteger(numReads) && numReads >= 1,
            "Inserisci un intero >= 1."
          );
        }
        var numSweeps = C.number("numSweeps");
        if (numSweeps !== null) {
          require(
            "numSweeps",
            isFiniteNumber(numSweeps) && Number.isInteger(numSweeps) && numSweeps >= 1,
            "Inserisci un intero >= 1."
          );
        }
      }
    }
    // Note: When reduction is NOT active (baseline mode), we skip validation of
    // reduction-specific fields entirely. Their values may still exist but are
    // ignored and not serialized to the command.

    // Model export path validation (always relevant)
    var exportPath = C.value("modelExportPath");
    if (C.bool("modelExport") && exportPath && !/\.(lp|mps)$/i.test(exportPath)) {
      C.setError("modelExportPath", "Il percorso deve terminare in .lp o .mps.");
      valid = false;
    }

    return valid;
  }

  /**
   * Generate the CLI command.
   * @returns {string}
   */
  function generateCommand() {
    var base = "poetry run python -m qreduce.experiments.portfolio";
    var format = C.getFormat();
    var reductionActive = isReductionActive();

    var args = [
      { flag: "--run-id", value: C.value("runId") },
    ];

    // Only include output-root if different from default
    var outputRoot = C.value("outputRoot");
    if (outputRoot && outputRoot !== "outputs/portfolio") {
      args.push({ flag: "--output-root", value: outputRoot });
    }

    // Log config if specified
    var logConfig = C.value("logConfig");
    if (logConfig) {
      args.push({ flag: "--log-config", value: logConfig });
    }

    // Asset count (always include since it's important)
    args.push({ flag: "--asset-count", value: C.number("assetCount") });

    // Generation seed if different from default
    var genSeed = C.number("generationSeed");
    if (genSeed !== null && genSeed !== 42) {
      args.push({ flag: "--generation-seed", value: genSeed });
    }

    // Observation count if specified
    var observations = C.number("observationCount");
    if (observations !== null) {
      args.push({ flag: "--observation-count", value: observations });
    }

    // Graph options - include if different from defaults
    var edgeMode = C.value("edgeMode");
    if (edgeMode !== "near_duplicate") {
      args.push({ flag: "--graph-edge-mode", value: edgeMode });
    }

    var corrThresh = C.number("correlationThreshold");
    if (corrThresh !== null && corrThresh !== 0.9) {
      args.push({ flag: "--correlation-threshold", value: corrThresh });
    }

    // Near-duplicate params only matter for near_duplicate mode
    if (isNearDuplicateMode()) {
      var returnDiff = C.number("returnDifference");
      if (returnDiff !== null && returnDiff !== 0.1) {
        args.push({ flag: "--near-duplicate-max-relative-return-difference", value: returnDiff });
      }
      var varianceDiff = C.number("varianceDifference");
      if (varianceDiff !== null && varianceDiff !== 0.1) {
        args.push({ flag: "--near-duplicate-max-relative-variance-difference", value: varianceDiff });
      }
    }

    // Investment bounds (only if different from defaults)
    var lowerBound = C.number("lowerBound");
    if (lowerBound !== null && lowerBound !== 0.0) {
      args.push({ flag: "--lower-bound", value: lowerBound });
    }
    var upperBound = C.number("upperBound");
    if (upperBound !== null && upperBound !== 0.7) {
      args.push({ flag: "--upper-bound", value: upperBound });
    }

    // Cardinality constraints (optional, always include if set)
    var minSelected = C.number("minSelectedAssets");
    if (minSelected !== null) {
      args.push({ flag: "--min-selected-assets", value: minSelected });
    }
    var maxSelected = C.number("maxSelectedAssets");
    if (maxSelected !== null) {
      args.push({ flag: "--max-selected-assets", value: maxSelected });
    }

    // Reduction policy - max-reduction-rounds is key
    var maxRounds = C.number("maxRounds");
    if (maxRounds !== null && maxRounds !== 1) {
      args.push({ flag: "--max-reduction-rounds", value: maxRounds });
    }

    // Budget end-to-end is ALWAYS included if specified (applies to baseline too)
    var budget = C.number("endToEndBudget");
    if (budget !== null) {
      args.push({ flag: "--max-end-to-end-runtime-seconds", value: budget });
    }

    // Reduction-specific params only when reduction is active
    if (reductionActive) {
      // Domain items
      var minItems = C.number("minItems");
      if (minItems !== null) {
        args.push({ flag: "--candidate-domain-min-items", value: minItems });
      }
      var maxItems = C.number("maxItems");
      if (maxItems !== null) {
        args.push({ flag: "--candidate-domain-max-items", value: maxItems });
      }

      // Other reduction params if provided
      var targetBinary = C.number("targetBinary");
      if (targetBinary !== null) {
        args.push({ flag: "--target-binary-variables", value: targetBinary });
      }

      var minRatio = C.number("minReductionRatio");
      if (minRatio !== null) {
        args.push({ flag: "--min-reduction-ratio", value: minRatio });
      }

      // Recovery policies (only if reduction is active)
      var domainRecovery = C.value("domainRecovery");
      if (domainRecovery !== "fail") {
        args.push({ flag: "--recovery-policy-on-domain-too-small", value: domainRecovery });
      }

      var infeasibleRecovery = C.value("infeasibleRecovery");
      if (infeasibleRecovery !== "fail") {
        args.push({ flag: "--recovery-policy-on-infeasible", value: infeasibleRecovery });
      }

      var recoveryAttempts = C.number("recoveryAttempts");
      if (recoveryAttempts !== null && recoveryAttempts > 0) {
        args.push({ flag: "--max-recovery-attempts", value: recoveryAttempts });
      }

      // MIS Solver (only matters if reduction is active)
      var misSolver = C.value("misSolver");
      if (misSolver !== "local_greedy") {
        args.push({ flag: "--mis-solver-id", value: misSolver });
      }

      // D-Wave params (only if D-Wave solver AND reduction active)
      if (isDwaveSolver()) {
        var numReads = C.number("numReads");
        if (numReads !== null) {
          args.push({ flag: "--mis-num-reads", value: numReads });
        }
        var numSweeps = C.number("numSweeps");
        if (numSweeps !== null) {
          args.push({ flag: "--mis-num-sweeps", value: numSweeps });
        }
      }
    }

    // Classical solver (always relevant)
    var classicalSolver = C.value("classicalSolver");
    if (classicalSolver !== "scip") {
      args.push({ flag: "--classical-solver-id", value: classicalSolver });
    }

    // Model export
    if (C.bool("modelExport")) {
      args.push({ flag: "--model-export", value: true, isFlag: true });
      var exportPath = C.value("modelExportPath");
      if (exportPath) {
        args.push({ flag: "--model-export-path", value: exportPath });
      }
    }

    return C.buildCommand(base, args, format);
  }

  /**
   * Update enabled/disabled state of fields based on current selections.
   */
  function updateEnabled() {
    var reductionActive = isReductionActive();
    var dwaveSolver = isDwaveSolver();
    var nearDuplicate = isNearDuplicateMode();

    // D-Wave params: disabled if not D-Wave OR if baseline mode
    document.querySelectorAll(".dwave-only input").forEach(function (input) {
      input.disabled = !dwaveSolver || !reductionActive;
    });

    // Near-duplicate params: disabled if not near_duplicate mode
    document.querySelectorAll(".near-duplicate input").forEach(function (input) {
      input.disabled = !nearDuplicate;
    });

    // Model export path: disabled if export not enabled
    C.$("modelExportPath").disabled = !C.bool("modelExport");

    // MIS solver: disabled in baseline mode
    var misSolverSelect = C.$("misSolver");
    if (misSolverSelect) {
      misSolverSelect.disabled = !reductionActive;
    }

    // Recovery fields: disabled in baseline mode
    var recoveryFields = ["domainRecovery", "infeasibleRecovery", "recoveryAttempts"];
    recoveryFields.forEach(function (id) {
      var el = C.$(id);
      if (el) {
        el.disabled = !reductionActive;
      }
    });

    // Reduction-specific policy fields: disabled in baseline mode
    // NOTE: endToEndBudget is NOT in this list - it stays enabled always
    var reductionFields = ["minItems", "maxItems", "targetBinary", "minReductionRatio"];
    reductionFields.forEach(function (id) {
      var el = C.$(id);
      if (el) {
        el.disabled = !reductionActive;
      }
    });
  }

  /**
   * Update UI with current state.
   */
  function update() {
    updateEnabled();
    var isValid = validate();

    // Update preview
    C.$("cliPreview").textContent = generateCommand();

    // Update summary
    C.$("summaryRunId").textContent = C.value("runId") || "run ID mancante";
    C.$("summaryAssets").textContent = C.number("assetCount") || "—";

    var maxRounds = C.number("maxRounds");
    var modeText = "single pass";
    if (maxRounds === 0) modeText = "classical only";
    else if (maxRounds > 1) modeText = "multi-round";
    C.$("summaryMode").textContent = modeText;
    C.$("summaryReduction").textContent = maxRounds + " round" + (maxRounds !== 1 ? "s" : "");

    // MIS solver: show "N/A" in baseline mode
    var reductionActive = isReductionActive();
    C.$("summaryMis").textContent = reductionActive ? C.value("misSolver") : "(non usato)";
    C.$("summaryClassical").textContent = C.value("classicalSolver");

    // Update validation display
    C.updateValidationBadge(isValid);
    C.updateValidationStatus(isValid);
    C.setButtonsEnabled(isValid, ["copyCommand"]);
  }

  /**
   * Reset form to defaults.
   */
  function resetDefaults() {
    Object.keys(defaults).forEach(function (id) {
      var el = C.$(id);
      if (!el) return;
      if (el.type === "checkbox") {
        el.checked = defaults[id];
      } else {
        el.value = defaults[id];
      }
    });
    update();
    C.toast("Ripristinati i default del portfolio.");
  }

  // Initialize on DOM ready
  document.addEventListener("DOMContentLoaded", function () {
    var form = C.$("configForm");

    // Setup event listeners
    form.addEventListener("input", update);
    form.addEventListener("change", update);

    C.setupTabs();
    C.setupFormatSelector(update);
    C.initTooltips();

    C.$("copyCommand").addEventListener("click", function () {
      C.copy(generateCommand(), "Comando CLI copiato negli appunti.");
    });

    C.$("resetDefaults").addEventListener("click", resetDefaults);

    // Initial update
    update();
  });
})();
