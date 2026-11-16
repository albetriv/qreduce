/**
 * QReduce Facility Location Experiment Configurator
 *
 * Generates CLI commands for: poetry run python -m qreduce.experiments.facility_location.run
 */

(function () {
  "use strict";

  var C = QReduceCommon;

  // Default values for reset
  var defaults = {
    instancePath: "data/benchmarks/or_library/capacitated_facility_location/cap41.txt",
    runId: "cap41_001",
    outputRoot: "outputs/facility_location",
    rounds: "0",
    cap: "",
    budget: "60",
    seed: "7",
    minReductionRatio: "0.1",
    recoveryAttempts: "0",
    protectAll: false,
    solver: "scip",
    misSolver: "local_greedy",
    modelExport: false,
    alpha: "0.5",
    epsilon: "0.01",
    profileFraction: "0.5",
    overlapThreshold: "0.5",
    capacityDifference: "0.25",
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
    var rounds = C.number("rounds");
    return rounds !== null && rounds > 0;
  }

  /**
   * Extract filename from path for display.
   * @param {string} path
   * @returns {string}
   */
  function getFilename(path) {
    if (!path) return "—";
    var parts = path.replace(/\\/g, "/").split("/");
    return parts[parts.length - 1] || "—";
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

    // Instance path is required (positional argument)
    require("instancePath", C.value("instancePath") !== "", "Il percorso dell'istanza è obbligatorio.");

    // Run ID is required
    require("runId", C.value("runId") !== "", "L'ID del run è obbligatorio.");

    // Rounds must be non-negative integer
    var rounds = C.number("rounds");
    require(
      "rounds",
      isFiniteNumber(rounds) && Number.isInteger(rounds) && rounds >= 0,
      "Inserisci un intero >= 0."
    );

    // Seed must be integer
    var seed = C.number("seed");
    if (seed !== null) {
      require(
        "seed",
        isFiniteNumber(seed) && Number.isInteger(seed),
        "Inserisci un intero."
      );
    }

    // Budget must be positive finite number
    var budget = C.number("budget");
    require(
      "budget",
      isFiniteNumber(budget) && budget > 0,
      "Il budget deve essere un numero > 0."
    );

    // Cap if provided must be positive integer
    var cap = C.number("cap");
    if (cap !== null) {
      require(
        "cap",
        isFiniteNumber(cap) && Number.isInteger(cap) && cap >= 1,
        "Inserisci un intero >= 1."
      );
    }

    // Min reduction ratio must be in [0, 1]
    var minRatio = C.number("minReductionRatio");
    if (minRatio !== null) {
      require(
        "minReductionRatio",
        isFiniteNumber(minRatio) && minRatio >= 0 && minRatio <= 1,
        "Il valore deve essere un numero fra 0 e 1."
      );
    }

    // Recovery attempts validation
    var recoveryAttempts = C.number("recoveryAttempts");
    if (recoveryAttempts !== null) {
      require(
        "recoveryAttempts",
        isFiniteNumber(recoveryAttempts) && Number.isInteger(recoveryAttempts) && recoveryAttempts >= 0,
        "Inserisci un intero >= 0."
      );
    }

    // Recovery requires reduction (rounds > 0) - align with Python config.py
    if (!reductionActive && recoveryAttempts !== null && recoveryAttempts > 0) {
      require(
        "recoveryAttempts",
        false,
        "Il recovery richiede rounds >= 1."
      );
    }

    // Graph policy parameters validation - align with Python FacilityLocationGraphPolicy
    // All must be in [0, 1], and epsilon/profile_fraction must be > 0

    // Alpha must be in [0, 1]
    var alpha = C.number("alpha");
    if (alpha !== null) {
      require(
        "alpha",
        isFiniteNumber(alpha) && alpha >= 0 && alpha <= 1,
        "Il valore deve essere un numero fra 0 e 1."
      );
    }

    // Epsilon must be in (0, 1] - must be positive
    var epsilon = C.number("epsilon");
    if (epsilon !== null) {
      require(
        "epsilon",
        isFiniteNumber(epsilon) && epsilon > 0 && epsilon <= 1,
        "Il valore deve essere un numero fra 0 (escluso) e 1."
      );
    }

    // Profile fraction must be in (0, 1] - must be positive
    var profileFraction = C.number("profileFraction");
    if (profileFraction !== null) {
      require(
        "profileFraction",
        isFiniteNumber(profileFraction) && profileFraction > 0 && profileFraction <= 1,
        "Il valore deve essere un numero fra 0 (escluso) e 1."
      );
    }

    // Overlap threshold must be in [0, 1]
    var overlapThreshold = C.number("overlapThreshold");
    if (overlapThreshold !== null) {
      require(
        "overlapThreshold",
        isFiniteNumber(overlapThreshold) && overlapThreshold >= 0 && overlapThreshold <= 1,
        "Il valore deve essere un numero fra 0 e 1."
      );
    }

    // Capacity difference must be in [0, 1]
    var capacityDifference = C.number("capacityDifference");
    if (capacityDifference !== null) {
      require(
        "capacityDifference",
        isFiniteNumber(capacityDifference) && capacityDifference >= 0 && capacityDifference <= 1,
        "Il valore deve essere un numero fra 0 e 1."
      );
    }

    return valid;
  }

  /**
   * Generate the CLI command.
   * @returns {string}
   */
  function generateCommand() {
    var base = "poetry run python -m qreduce.experiments.facility_location.run";
    var format = C.getFormat();

    var args = [];

    // Positional argument: instance path (must come first)
    args.push({ isPositional: true, value: C.value("instancePath") });

    // Required --run-id
    args.push({ flag: "--run-id", value: C.value("runId") });

    // Output root if different from default
    var outputRoot = C.value("outputRoot");
    if (outputRoot && outputRoot !== "outputs/facility_location") {
      args.push({ flag: "--output-root", value: outputRoot });
    }

    // Rounds if different from default (0)
    var rounds = C.number("rounds");
    if (rounds !== null && rounds !== 0) {
      args.push({ flag: "--rounds", value: rounds });
    }

    // Solver if different from default
    var solver = C.value("solver");
    if (solver !== "scip") {
      args.push({ flag: "--solver", value: solver });
    }

    // MIS solver if different from default
    var misSolver = C.value("misSolver");
    if (misSolver !== "local_greedy") {
      args.push({ flag: "--mis-solver", value: misSolver });
    }

    // Seed if different from default
    var seed = C.number("seed");
    if (seed !== null && seed !== 7) {
      args.push({ flag: "--seed", value: seed });
    }

    // Budget if different from default
    var budget = C.number("budget");
    if (budget !== null && budget !== 60) {
      args.push({ flag: "--budget", value: budget });
    }

    // Cap if specified
    var cap = C.number("cap");
    if (cap !== null) {
      args.push({ flag: "--cap", value: cap });
    }

    // Protect all flag
    if (C.bool("protectAll")) {
      args.push({ flag: "--protect-all", value: true, isFlag: true });
    }

    // Recovery attempts if different from default (only serialize if rounds > 0)
    var recoveryAttempts = C.number("recoveryAttempts");
    if (recoveryAttempts !== null && recoveryAttempts !== 0 && isReductionActive()) {
      args.push({ flag: "--recovery-attempts", value: recoveryAttempts });
    }

    // Min reduction ratio if different from default
    var minRatio = C.number("minReductionRatio");
    if (minRatio !== null && minRatio !== 0.1) {
      args.push({ flag: "--min-reduction-ratio", value: minRatio });
    }

    // Model export flag
    if (C.bool("modelExport")) {
      args.push({ flag: "--model-export", value: true, isFlag: true });
    }

    // Graph policy parameters - only include if different from defaults
    var alpha = C.number("alpha");
    if (alpha !== null && alpha !== 0.5) {
      args.push({ flag: "--alpha", value: alpha });
    }

    var epsilon = C.number("epsilon");
    if (epsilon !== null && epsilon !== 0.01) {
      args.push({ flag: "--epsilon", value: epsilon });
    }

    var profileFraction = C.number("profileFraction");
    if (profileFraction !== null && profileFraction !== 0.5) {
      args.push({ flag: "--profile-fraction", value: profileFraction });
    }

    var overlapThreshold = C.number("overlapThreshold");
    if (overlapThreshold !== null && overlapThreshold !== 0.5) {
      args.push({ flag: "--overlap-threshold", value: overlapThreshold });
    }

    var capacityDifference = C.number("capacityDifference");
    if (capacityDifference !== null && capacityDifference !== 0.25) {
      args.push({ flag: "--capacity-difference", value: capacityDifference });
    }

    return C.buildCommand(base, args, format);
  }

  /**
   * Update UI with current state.
   */
  function update() {
    var isValid = validate();

    // Update preview
    C.$("cliPreview").textContent = generateCommand();

    // Update summary
    C.$("summaryRunId").textContent = C.value("runId") || "run ID mancante";
    C.$("summaryInstance").textContent = getFilename(C.value("instancePath"));

    var rounds = C.number("rounds");
    var modeText = "baseline";
    if (rounds === 1) modeText = "single-pass";
    else if (rounds > 1) modeText = "multi-round";
    C.$("summaryMode").textContent = modeText;
    C.$("summaryReduction").textContent = rounds + " round" + (rounds !== 1 ? "s" : "");

    C.$("summarySolver").textContent = C.value("solver");
    C.$("summaryBudget").textContent = (C.number("budget") || 60) + " s";

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
    C.toast("Ripristinati i default di facility location.");
  }

  // Initialize on DOM ready
  document.addEventListener("DOMContentLoaded", function () {
    var form = C.$("configForm");

    // Setup event listeners
    form.addEventListener("input", update);
    form.addEventListener("change", update);

    C.setupTabs();
    C.setupFormatSelector(update);

    C.$("copyCommand").addEventListener("click", function () {
      C.copy(generateCommand(), "Comando CLI copiato negli appunti.");
    });

    C.$("resetDefaults").addEventListener("click", resetDefaults);

    // Initial update
    update();
  });
})();
