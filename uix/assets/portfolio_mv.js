/**
 * QReduce Portfolio Media-Varianza Experiment Configurator
 *
 * Generates CLI commands for: poetry run python -m qreduce.experiments.portfolio_mv
 */

(function () {
  "use strict";

  var C = QReduceCommon;

  // Default values for reset
  var defaults = {
    runId: "ui_portfolio_001",
    outputRoot: "outputs/portfolio_mv",
    logConfig: "",
    assetCount: "30",
    riskAversion: "1.0",
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
    numSourceMisCandidates: "",
    endToEndBudget: "",
    classicalTimeLimit: "",
    domainRecovery: "fail",
    infeasibleRecovery: "fail",
    recoveryAttempts: "",
    misSolver: "local_greedy",
    classicalSolver: "scip",
    numReads: "",
    numSweeps: "",
    embeddingProfile: "none",
    pasqalShots: "",
    pasqalQpuDevice: "",
    pasqalQpuShots: "",
    pasqalQpuConsent: false,
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
   * Check if local Pasqal solver is selected.
   * @returns {boolean}
   */
  function isPasqalSolver() {
    return C.value("misSolver") === "pasqal_local";
  }

  /**
   * Check if Pasqal Cloud solver is selected.
   * @returns {boolean}
   */
  function isPasqalCloudSolver() {
    return C.value("misSolver") === "pasqal_cloud_emulator";
  }

  function isPasqalQpuSolver() {
    return C.value("misSolver") === "pasqal_qpu";
  }

  /**
   * Check if any Pasqal solver (local or cloud) is selected.
   * @returns {boolean}
   */
  function isAnyPasqalSolver() {
    return isPasqalSolver() || isPasqalCloudSolver();
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
    C.$("endToEndBudget").setAttribute("aria-invalid", "false");

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

    // Risk aversion must be finite number > 0
    var riskAversion = C.number("riskAversion");
    require(
      "riskAversion",
      isFiniteNumber(riskAversion) && riskAversion > 0,
      "Inserisci un numero > 0."
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
        isFiniteNumber(budget) && budget >= 0,
        "Il budget deve essere un numero >= 0."
      );
    }

    // Classical time limit is always validated
    var classicalTimeLimit = C.number("classicalTimeLimit");
    if (classicalTimeLimit !== null) {
      require(
        "classicalTimeLimit",
        isFiniteNumber(classicalTimeLimit) && classicalTimeLimit >= 0,
        "Il timeout deve essere un numero >= 0."
      );
    }

    // Reduction-specific validations: only validate if reduction is active
    // When disabled, these fields' values are ignored (not serialized)
    if (reductionActive) {
      // Graph policy validation: only when reduction is active
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

      // Num source MIS candidates if provided must be >= 1
      var numSourceMisCandidates = C.number("numSourceMisCandidates");
      var candidateInput = C.$("numSourceMisCandidates");
      if (numSourceMisCandidates !== null || candidateInput.validity.badInput) {
        require(
          "numSourceMisCandidates",
          !candidateInput.validity.badInput && isFiniteNumber(numSourceMisCandidates) && Number.isInteger(numSourceMisCandidates) && numSourceMisCandidates >= 1,
          "Inserisci un intero >= 1."
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

      if (isPasqalQpuSolver()) {
        var qpuDevice = C.value("pasqalQpuDevice");
        var qpuShots = C.number("pasqalQpuShots");
        require("maxRounds", maxRounds === 1, "Pasqal QPU richiede esattamente un round.");
        require("pasqalQpuDevice", /^[A-Za-z0-9][A-Za-z0-9_-]*$/.test(qpuDevice) && !qpuDevice.startsWith("EMU_"),
          "Inserisci l'ID di una QPU restituito dalla discovery.");
        require("pasqalQpuShots", !C.$("pasqalQpuShots").validity.badInput && Number.isSafeInteger(qpuShots) && qpuShots >= 1,
          "Inserisci un numero intero positivo di shot.");
        require("pasqalQpuConsent", C.bool("pasqalQpuConsent"), "Conferma i potenziali costi per generare il comando.");
      }

      if (isAnyPasqalSolver()) {
        var pasqalShots = C.number("pasqalShots");
        var shotsInput = C.$("pasqalShots");
        if (pasqalShots !== null || shotsInput.validity.badInput) {
          require(
            "pasqalShots",
            !shotsInput.validity.badInput && isFiniteNumber(pasqalShots) && Number.isInteger(pasqalShots) && pasqalShots >= 1,
            "Inserisci un intero >= 1."
          );
        }
      }

      if (isPasqalSolver()) {
        // Pasqal LOCAL requires explicit budget=0 (unlimited) when reduction is active
        // The local emulator cannot guarantee meeting a time deadline
        var budgetForPasqal = C.number("endToEndBudget");
        var pasqalBudgetError = C.$("pasqalBudgetError");
        if (budgetForPasqal !== 0) {
          C.$("endToEndBudget").setAttribute("aria-invalid", "true");
          if (pasqalBudgetError) {
            pasqalBudgetError.style.display = "";
          }
          valid = false;
        } else {
          if (pasqalBudgetError) {
            pasqalBudgetError.style.display = "none";
          }
        }
      } else {
        // Hide Pasqal budget error when Pasqal local is not selected
        var pasqalBudgetErrorHide = C.$("pasqalBudgetError");
        if (pasqalBudgetErrorHide) {
          pasqalBudgetErrorHide.style.display = "none";
        }
      }
    } else {
      // Reduction not active (baseline mode): hide Pasqal budget error
      var pasqalBudgetErrorBaseline = C.$("pasqalBudgetError");
      if (pasqalBudgetErrorBaseline) {
        pasqalBudgetErrorBaseline.style.display = "none";
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
    var base = "poetry run python -m qreduce.experiments.portfolio_mv";
    var format = C.getFormat();
    var reductionActive = isReductionActive();

    var args = [
      { flag: "--run-id", value: C.value("runId") },
    ];

    // Only include output-root if different from default
    var outputRoot = C.value("outputRoot");
    if (outputRoot && outputRoot !== "outputs/portfolio_mv") {
      args.push({ flag: "--output-root", value: outputRoot });
    }

    // Log config if specified
    var logConfig = C.value("logConfig");
    if (logConfig) {
      args.push({ flag: "--log-config", value: logConfig });
    }

    // Asset count (always include since it's important)
    args.push({ flag: "--asset-count", value: C.number("assetCount") });

    // Risk aversion if different from default
    var riskAversion = C.number("riskAversion");
    if (riskAversion !== null && riskAversion !== 1.0) {
      args.push({ flag: "--risk-aversion", value: riskAversion });
    }

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
    if (maxRounds !== null && (maxRounds !== 1 || (reductionActive && isPasqalQpuSolver()))) {
      args.push({ flag: "--max-reduction-rounds", value: maxRounds });
    }

    // Budget end-to-end is ALWAYS included if specified (applies to baseline too)
    // Include 0 explicitly to signal unlimited
    var budget = C.number("endToEndBudget");
    if (budget !== null) {
      args.push({ flag: "--max-end-to-end-runtime-seconds", value: budget });
    }

    // Classical time limit is ALWAYS included if specified (applies to baseline too)
    // Include 0 explicitly to signal unlimited
    var classicalTimeLimit = C.number("classicalTimeLimit");
    if (classicalTimeLimit !== null) {
      args.push({ flag: "--classical-time-limit-seconds", value: classicalTimeLimit });
    }

    // Reduction-specific params only when reduction is active
    if (reductionActive) {
      // Graph options (only when reduction is active)
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

      var numSourceMisCandidates = C.number("numSourceMisCandidates");
      if (numSourceMisCandidates !== null) {
        args.push({ flag: "--num-source-mis-candidates", value: numSourceMisCandidates });
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
        // Embedding profile (only if not "none")
        var embeddingProfile = C.value("embeddingProfile");
        if (embeddingProfile && embeddingProfile !== "none") {
          args.push({ flag: "--mis-embedding-profile", value: embeddingProfile });
        }
      }

      if (isPasqalCloudSolver()) {
        args.push({ flag: "--pasqal-emulator-service", value: "emu_free" });
      }

      if (isPasqalQpuSolver()) {
        args.push({ flag: "--pasqal-device-id", value: C.value("pasqalQpuDevice") });
        args.push({ flag: "--pasqal-shots", value: C.number("pasqalQpuShots") });
        args.push({ flag: "--pasqal-cost-consent", value: true, isFlag: true });
      }

      if (isAnyPasqalSolver()) {
        var pasqalShots = C.number("pasqalShots");
        // Preserve the local solver's existing omission of the default value.
        if (pasqalShots !== null && (isPasqalCloudSolver() || pasqalShots !== 100)) {
          args.push({ flag: "--pasqal-shots", value: pasqalShots });
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
    var pasqalSolver = isPasqalSolver();
    var pasqalCloudSolver = isPasqalCloudSolver();
    var greedySolver = C.value("misSolver") === "local_greedy";
    var nearDuplicate = isNearDuplicateMode();

    // Graph policy controls: disabled in baseline mode
    var graphPolicyCard = C.$("graphPolicyCard");
    var graphBaselineNote = C.$("graphBaselineNote");
    if (graphPolicyCard) {
      // Show/hide baseline note
      if (graphBaselineNote) {
        graphBaselineNote.style.display = reductionActive ? "none" : "";
      }
      // Disable graph policy controls in baseline
      graphPolicyCard.querySelectorAll("input, select").forEach(function (el) {
        // Near-duplicate controls have additional condition
        if (el.closest(".near-duplicate")) {
          el.disabled = !reductionActive || !nearDuplicate;
        } else {
          el.disabled = !reductionActive;
        }
      });
      // Visual dimming
      graphPolicyCard.style.opacity = reductionActive ? "1" : "0.6";
    }

    // MIS params card: show appropriate section based on solver and mode
    var misParamsCard = C.$("misParamsCard");
    var dwaveParamsSection = C.$("dwaveParams");
    var pasqalParamsSection = C.$("pasqalParams");
    var pasqalCloudParamsSection = C.$("pasqalCloudParams");
    var greedyParamsSection = C.$("greedyParams");
    C.$("misParamsCard").hidden = !reductionActive;

    if (misParamsCard) {
      if (!reductionActive) {
        // Baseline mode: show notice, hide all params
        if (dwaveParamsSection) dwaveParamsSection.style.display = "none";
        if (pasqalParamsSection) pasqalParamsSection.style.display = "none";
        if (pasqalCloudParamsSection) pasqalCloudParamsSection.style.display = "none";
        if (greedyParamsSection) greedyParamsSection.style.display = "none";
      } else {
        // Reduction active: show params for selected solver
        if (dwaveParamsSection) dwaveParamsSection.style.display = dwaveSolver ? "" : "none";
        if (pasqalParamsSection) pasqalParamsSection.style.display = pasqalSolver ? "" : "none";
        if (pasqalCloudParamsSection) pasqalCloudParamsSection.style.display = pasqalCloudSolver ? "" : "none";
        if (greedyParamsSection) greedyParamsSection.style.display = greedySolver ? "" : "none";
      }
    }

    // D-Wave params: disabled if not D-Wave OR if baseline mode
    document.querySelectorAll(".dwave-only input").forEach(function (input) {
      input.disabled = !dwaveSolver || !reductionActive;
    });

    // D-Wave select fields (embedding profile): disabled if not D-Wave OR if baseline mode
    document.querySelectorAll(".dwave-only select").forEach(function (select) {
      select.disabled = !dwaveSolver || !reductionActive;
    });

    // Keep inactive values for a later return; serialization excludes them.

    // Near-duplicate params outside graph card: disabled if not near_duplicate mode OR baseline
    document.querySelectorAll(".near-duplicate input").forEach(function (input) {
      // Skip if already handled above (inside graph policy card)
      if (input.closest(".graph-policy")) return;
      input.disabled = !nearDuplicate || !reductionActive;
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
    var reductionFields = ["minItems", "maxItems", "targetBinary", "minReductionRatio", "numSourceMisCandidates"];
    reductionFields.forEach(function (id) {
      var el = C.$(id);
      if (el) {
        el.disabled = !reductionActive;
      }
    });

    var pasqalActive = reductionActive && isAnyPasqalSolver();
    C.$("pasqalShotField").hidden = !pasqalActive;
    C.$("pasqalShots").disabled = !pasqalActive;

    var qpuActive = reductionActive && isPasqalQpuSolver();
    C.$("pasqalQpuParams").hidden = !qpuActive;
    ["pasqalQpuDevice", "pasqalQpuShots", "pasqalQpuConsent"].forEach(function (id) {
      C.$(id).disabled = !qpuActive;
    });
    if (!qpuActive) C.$("pasqalQpuConsent").checked = false;

    // Update dynamic solver info panels
    updateSolverInfoPanels(reductionActive);
  }

  /**
   * Update the dynamic solver info panels based on current selections.
   * @param {boolean} reductionActive - Whether reduction is active
   */
  function updateSolverInfoPanels(reductionActive) {
    // Check if solver info module is available
    if (typeof QReduceSolverInfo === "undefined") {
      return;
    }

    var misSolverId = C.value("misSolver");
    var classicalSolverId = C.value("classicalSolver");
    var embeddingProfile = C.value("embeddingProfile");

    // Render MIS solver info panel
    QReduceSolverInfo.renderMisPanel("misSolverInfoContainer", misSolverId, {
      reductionActive: reductionActive,
      embeddingProfile: embeddingProfile
    });

    // Render classical solver info panel (always visible)
    QReduceSolverInfo.renderClassicalPanel("classicalSolverInfoContainer", classicalSolverId);
  }

  /**
   * Update UI with current state.
   */
  function update() {
    updateEnabled();
    var isValid = validate();

    // Update preview
    C.$("cliPreview").textContent = !isValid && isReductionActive() && isPasqalQpuSolver()
      ? "Completa i campi evidenziati per generare il comando QPU."
      : generateCommand();

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

  // Favorites control object (assigned during initialization)
  var favoritesControl = null;

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
    // Reset name tracking to realign proposal with restored runId
    if (favoritesControl) {
      favoritesControl.resetNameTracking();
    }
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
      if (validate()) C.copy(generateCommand(), "Comando CLI copiato negli appunti.");
    });

    C.$("resetDefaults").addEventListener("click", resetDefaults);

    // Initial update
    update();
    favoritesControl = C.setupFavorites("portfolio_mv", update);

  });
})();
