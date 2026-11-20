#!/usr/bin/env node
/**
 * Test runner for UIX math formulation panel integration.
 *
 * Usage: node tests/uix_math_runner.js <configurator> <test_type> [json_input]
 *
 * Where:
 *   configurator: "portfolio", "portfolio_sr", or "facility_location"
 *   test_type: see switch in main()
 *   json_input: JSON object with field values to set (optional)
 *
 * Output: JSON object with test results
 */

const { JSDOM } = require("jsdom");
const fs = require("fs");
const path = require("path");

/**
 * Centralized configurator mapping.
 * All configurator-specific details in one place.
 */
const CONFIGURATOR_CONFIG = {
  portfolio: {
    htmlFile: "experiment_portfolio_mv.html",
    scriptMode: "file",
    scriptFile: "portfolio_mv.js",
    roundsField: "maxRounds",
    cardinalityFields: ["minSelectedAssets", "maxSelectedAssets"],
    dynamicIds: ["mathCardinalityLatex", "mathReductionContent"],
  },
  portfolio_sr: {
    htmlFile: "experiment_portfolio_sr.html",
    scriptMode: "inline",
    roundsField: "maxRounds",
    cardinalityFields: ["maxPositions"],
    dynamicIds: ["mathReductionContent"],
  },
  facility_location: {
    htmlFile: "experiment_facility_location.html",
    scriptMode: "file",
    scriptFile: "facility_location.js",
    roundsField: "rounds",
    cardinalityFields: [],
    dynamicIds: ["mathReductionContent"],
  },
};

const VALID_CONFIGURATORS = Object.keys(CONFIGURATOR_CONFIG);

/**
 * Get configurator config with validation.
 */
function getConfiguratorConfig(configurator) {
  if (!CONFIGURATOR_CONFIG[configurator]) {
    throw new Error(`Invalid configurator: ${configurator}. Valid: ${VALID_CONFIGURATORS.join(", ")}`);
  }
  return CONFIGURATOR_CONFIG[configurator];
}

/**
 * Setup jsdom with required globals.
 */
function setupJsdomGlobals(window) {
  // Polyfill requestAnimationFrame
  if (typeof window.requestAnimationFrame !== "function") {
    window.requestAnimationFrame = function (callback) {
      return setTimeout(callback, 0);
    };
  }
  if (typeof window.cancelAnimationFrame !== "function") {
    window.cancelAnimationFrame = function (id) {
      clearTimeout(id);
    };
  }
}

/**
 * Create a MathJax mock with optional consumption of source text.
 * The consuming mode catches missing TeX restoration on subsequent renders.
 */
function createMathJaxMock(window, options = {}) {
  const calls = {
    typesetPromise: [],
    typesetClear: [],
    cleansWhileRendering: 0,
  };

  // Track rendering state
  let isRendering = false;

  // Configurable delay for slow renderer tests
  const renderDelay = options.slowRenderer ? 100 : 10;

  window.MathJax = {
    typesetPromise: function (elements) {
      return new Promise((resolve) => {
        isRendering = true;
        calls.typesetPromise.push({
          elements: elements ? elements.map((el) => el.id || el.tagName) : null,
          timestamp: Date.now(),
        });

        // Simulate async rendering with configurable delay
        setTimeout(() => {
          // Simulate transformation of .math-latex elements.
          if (elements) {
            elements.forEach((container) => {
              if (!container) return;
              container.querySelectorAll(".math-latex").forEach((el) => {
                // Only add mjx-container if not already present
                if (!el.querySelector("mjx-container")) {
                  const mockContainer = window.document.createElement("mjx-container");
                  mockContainer.setAttribute("data-rendered", "true");
                  mockContainer.textContent = "[Rendered]";
                  if (options.consumeTex) el.textContent = "";
                  el.appendChild(mockContainer);
                }
              });
            });
          }
          isRendering = false;
          resolve();
        }, renderDelay);
      });
    },

    typesetClear: function (elements) {
      if (isRendering) {
        calls.cleansWhileRendering++;
      }
      calls.typesetClear.push({
        elements: elements ? elements.map((el) => el.id || el.tagName) : null,
        timestamp: Date.now(),
        whileRendering: isRendering,
      });
    },

    _testCalls: calls,
    _isRendering: function () {
      return isRendering;
    },
  };

  return calls;
}

/**
 * Load and initialize the UIX page.
 * @param {string} configurator - "portfolio", "portfolio_sr", or "facility_location"
 * @param {object} options - { simulateLoadFailure: boolean, slowRenderer: boolean }
 */
function loadPage(configurator, options = {}) {
  const config = getConfiguratorConfig(configurator);
  const uixDir = path.join(__dirname, "..", "uix");
  const htmlPath = path.join(uixDir, config.htmlFile);

  if (!fs.existsSync(htmlPath)) {
    throw new Error(`HTML file not found: ${htmlPath}`);
  }

  const htmlContent = fs.readFileSync(htmlPath, "utf8");

  const dom = new JSDOM(htmlContent, {
    url: "file://" + htmlPath,
    runScripts: "outside-only",
  });

  const { window } = dom;
  const { document } = window;

  setupJsdomGlobals(window);

  // Initialize select elements
  document.querySelectorAll("select").forEach((select) => {
    const firstOption = select.querySelector("option");
    if (firstOption) {
      select.value = firstOption.value;
    }
  });

  // Load common.js
  const commonJs = fs.readFileSync(path.join(uixDir, "assets", "common.js"), "utf8");
  window.eval(commonJs);

  // Create MathJax mock BEFORE loading math_formulation.js
  let mathJaxCalls = null;
  if (!options.simulateLoadFailure) {
    mathJaxCalls = createMathJaxMock(window, options);
  }

  // Load math_formulation.js
  const mathJs = fs.readFileSync(path.join(uixDir, "assets", "math_formulation.js"), "utf8");
  window.eval(mathJs);

  // Mark MathJax as ready (simulate successful load) unless testing failure
  if (!options.simulateLoadFailure && window.QReduceMath && window.QReduceMath._setReadyForTesting) {
    window.QReduceMath._setReadyForTesting(true);
  } else if (options.simulateLoadFailure && window.QReduceMath && window.QReduceMath._simulateLoadFailure) {
    window.QReduceMath._simulateLoadFailure();
  }

  // Load specific script based on config
  if (config.scriptMode === "file" && config.scriptFile) {
    const specificJs = fs.readFileSync(path.join(uixDir, "assets", config.scriptFile), "utf8");
    window.eval(specificJs);
  } else if (config.scriptMode === "inline") {
    // Extract and evaluate inline scripts from HTML
    // Skip the module scripts (common.js, math_formulation.js) which are already loaded
    const scriptTags = document.querySelectorAll("script:not([src])");
    scriptTags.forEach((script) => {
      const content = script.textContent;
      // Only eval application scripts (not empty or library config)
      if (content && content.includes("DOMContentLoaded")) {
        window.eval(content);
      }
    });
  }

  // Trigger DOMContentLoaded
  const initEvent = new window.Event("DOMContentLoaded");
  document.dispatchEvent(initEvent);

  return { dom, window, document, mathJaxCalls, config };
}

/**
 * Set field values and trigger update.
 */
function setFieldValues(document, window, fieldValues) {
  for (const [id, value] of Object.entries(fieldValues)) {
    if (id.startsWith("_")) continue;
    const el = document.getElementById(id);
    if (!el) continue;
    if (el.type === "checkbox") {
      el.checked = Boolean(value);
    } else {
      el.value = String(value);
    }
  }

  // Trigger update
  const form = document.getElementById("configForm");
  if (form) {
    form.dispatchEvent(new window.Event("input", { bubbles: true }));
    form.dispatchEvent(new window.Event("change", { bubbles: true }));
  }
}

/**
 * Wait for debounce and render queue to settle.
 */
async function waitForRender(window, extraMs = 50) {
  const debounceMs = window.QReduceMath._getDebounceMs ? window.QReduceMath._getDebounceMs() : 150;

  // Wait for debounce timer
  await new Promise((resolve) => setTimeout(resolve, debounceMs + extraMs));

  // Wait for render queue
  if (window.QReduceMath._getRenderQueue) {
    await window.QReduceMath._getRenderQueue();
  }

  // Extra settle time for MathJax mock
  await new Promise((resolve) => setTimeout(resolve, 100));
}

/**
 * Test: Panel initialization
 */
function testInit(configurator) {
  const { document, mathJaxCalls } = loadPage(configurator);

  const mathPanel = document.getElementById("mathPanel");
  const mathContent = document.getElementById("mathContent");
  const mathReductionSection = document.getElementById("mathReductionSection");

  return {
    success: true,
    hasMathPanel: !!mathPanel,
    hasMathContent: !!mathContent,
    hasReductionSection: !!mathReductionSection,
    mathContentClasses: mathContent ? Array.from(mathContent.classList) : [],
    typesetCalled: mathJaxCalls ? mathJaxCalls.typesetPromise.length > 0 : false,
  };
}

/**
 * Test: TeX source preservation (excluding dynamic elements)
 */
function testTexSourcePreservation(configurator) {
  const { document, window } = loadPage(configurator);

  const mathContent = document.getElementById("mathContent");
  const allLatexElements = mathContent ? mathContent.querySelectorAll(".math-latex") : [];

  // Dynamic elements that should NOT have data-tex-source
  const dynamicIds =
    configurator === "portfolio"
      ? ["mathCardinalityLatex", "mathReductionContent"]
      : ["mathReductionContent"];

  let preservedCount = 0;
  let dynamicCount = 0;
  let totalCount = allLatexElements.length;
  let sampleSource = null;

  allLatexElements.forEach((el) => {
    // Check if this is inside a dynamic container
    let isDynamic = false;
    let parent = el;
    while (parent && parent !== mathContent) {
      if (dynamicIds.includes(parent.id)) {
        isDynamic = true;
        break;
      }
      parent = parent.parentElement;
    }
    if (el.id && dynamicIds.includes(el.id)) {
      isDynamic = true;
    }

    if (isDynamic) {
      dynamicCount++;
    } else if (el.hasAttribute("data-tex-source")) {
      preservedCount++;
      if (!sampleSource) {
        sampleSource = el.getAttribute("data-tex-source").substring(0, 100);
      }
    }
  });

  const staticCount = totalCount - dynamicCount;

  return {
    success: true,
    totalLatexElements: totalCount,
    staticElements: staticCount,
    dynamicElements: dynamicCount,
    preservedCount: preservedCount,
    allStaticPreserved: preservedCount === staticCount,
    sampleSource: sampleSource,
  };
}

/**
 * Test: Formula restoration after clear (static elements only)
 */
async function testFormulaRestoration(configurator) {
  const { document, window } = loadPage(configurator);

  const mathContent = document.getElementById("mathContent");
  const mathObjective = document.getElementById("mathObjective");

  if (!mathObjective) {
    return { success: false, error: "mathObjective not found" };
  }

  // Get original TeX content from a static element
  const latexEl = mathObjective.querySelector(".math-latex");
  const originalContent = latexEl ? latexEl.getAttribute("data-tex-source") : null;

  if (!originalContent) {
    return { success: false, error: "No data-tex-source found on static element" };
  }

  // Simulate MathJax rendering (our mock clears text and adds mjx-container)
  await waitForRender(window);

  // Now clear the typeset
  window.QReduceMath.clearTypeset(mathContent);

  // Check that static content was restored
  const restoredContent = latexEl ? latexEl.innerHTML : null;
  const contentRestored =
    restoredContent && (restoredContent.includes("\\min") || restoredContent === originalContent);

  return {
    success: true,
    originalContent: originalContent ? originalContent.substring(0, 100) : null,
    restoredContent: restoredContent ? restoredContent.substring(0, 100) : null,
    contentRestored: contentRestored,
    noMjxContainer: !latexEl || !latexEl.querySelector("mjx-container"),
  };
}

/**
 * Test: Portfolio cardinality survives debounce
 * This is the key test for the bug where cardinality was erased
 */
async function testCardinalitySurvivesDebounce(fieldValues) {
  const { document, window } = loadPage("portfolio");

  // Set cardinality values
  setFieldValues(document, window, fieldValues);

  // Check immediately after setting (before debounce)
  const cardinalityLatex = document.getElementById("mathCardinalityLatex");
  const contentBeforeDebounce = cardinalityLatex ? cardinalityLatex.innerHTML : null;

  // Wait for debounce AND render queue to complete
  await waitForRender(window, 200);

  // Check after debounce and render
  const contentAfterDebounce = cardinalityLatex ? cardinalityLatex.innerHTML : null;

  // The content should still contain the cardinality constraint
  const hasMinConstraint = contentAfterDebounce && contentAfterDebounce.includes("\\geq");
  const hasMaxConstraint = contentAfterDebounce && contentAfterDebounce.includes("\\leq");

  return {
    success: true,
    contentBeforeDebounce: contentBeforeDebounce ? contentBeforeDebounce.substring(0, 200) : null,
    contentAfterDebounce: contentAfterDebounce ? contentAfterDebounce.substring(0, 200) : null,
    hasMinConstraint: hasMinConstraint,
    hasMaxConstraint: hasMaxConstraint,
    contentSurvived: contentAfterDebounce && contentAfterDebounce.length > 0,
  };
}

/**
 * Test: Multiple cardinality updates
 */
async function testMultipleCardinalityUpdates() {
  const { document, window } = loadPage("portfolio");

  const cardinalityLatex = document.getElementById("mathCardinalityLatex");
  const results = [];

  // First update: set min to 3
  setFieldValues(document, window, { minSelectedAssets: "3", maxSelectedAssets: "" });
  await waitForRender(window);
  results.push({
    step: "min=3",
    content: cardinalityLatex ? cardinalityLatex.innerHTML : null,
    hasContent: cardinalityLatex && cardinalityLatex.innerHTML.length > 0,
  });

  // Second update: add max to 8
  setFieldValues(document, window, { minSelectedAssets: "3", maxSelectedAssets: "8" });
  await waitForRender(window);
  results.push({
    step: "min=3,max=8",
    content: cardinalityLatex ? cardinalityLatex.innerHTML : null,
    hasContent: cardinalityLatex && cardinalityLatex.innerHTML.length > 0,
  });

  // Third update: change min to 5
  setFieldValues(document, window, { minSelectedAssets: "5", maxSelectedAssets: "8" });
  await waitForRender(window);
  results.push({
    step: "min=5,max=8",
    content: cardinalityLatex ? cardinalityLatex.innerHTML : null,
    hasContent: cardinalityLatex && cardinalityLatex.innerHTML.length > 0,
  });

  // Fourth update: clear min
  setFieldValues(document, window, { minSelectedAssets: "", maxSelectedAssets: "8" });
  await waitForRender(window);
  results.push({
    step: "max=8",
    content: cardinalityLatex ? cardinalityLatex.innerHTML : null,
    hasContent: cardinalityLatex && cardinalityLatex.innerHTML.length > 0,
  });

  return {
    success: true,
    results: results,
    allUpdatesPreserved: results.every((r) => r.hasContent),
  };
}

/**
 * Test: Portfolio value updates
 */
async function testPortfolioUpdateValues(fieldValues) {
  const { document, window } = loadPage("portfolio");

  // Set field values
  setFieldValues(document, window, fieldValues);

  // Wait for debounce and render queue
  await waitForRender(window);

  // Read displayed values
  const mathAssetCount = document.getElementById("mathAssetCount");
  const mathLowerBound = document.getElementById("mathLowerBound");
  const mathUpperBound = document.getElementById("mathUpperBound");

  return {
    success: true,
    displayedAssetCount: mathAssetCount ? mathAssetCount.textContent : null,
    displayedLowerBound: mathLowerBound ? mathLowerBound.textContent : null,
    displayedUpperBound: mathUpperBound ? mathUpperBound.textContent : null,
  };
}

/** Test risk aversion through render, reset, and the offline fallback. */
async function testRiskAversion(fieldValues) {
  const { document, window } = loadPage("portfolio", {
    simulateLoadFailure: Boolean(fieldValues._fallback),
  });
  setFieldValues(document, window, fieldValues);
  await waitForRender(window);
  const displayed = document.getElementById("mathRiskAversion").textContent;
  const objective = document.getElementById("mathObjective");
  const result = {
    success: true,
    displayed,
    latex: objective.querySelector(".math-latex").textContent,
    fallback: objective.querySelector(".math-fallback").textContent,
    disabled: document.getElementById("riskAversion").disabled,
  };
  document.getElementById("resetDefaults").click();
  await waitForRender(window);
  result.afterReset = document.getElementById("mathRiskAversion").textContent;
  result.fieldAfterReset = document.getElementById("riskAversion").value;
  window.close();
  return result;
}

/**
 * Test: Portfolio cardinality display
 */
async function testPortfolioCardinality(fieldValues) {
  const { document, window } = loadPage("portfolio");

  // Set field values
  setFieldValues(document, window, fieldValues);

  // Wait for debounce and render queue
  await waitForRender(window);

  const cardinalityBlock = document.getElementById("mathCardinalityBlock");
  const minSelectedRow = document.getElementById("mathMinSelectedRow");
  const maxSelectedRow = document.getElementById("mathMaxSelectedRow");
  const cardinalityLatex = document.getElementById("mathCardinalityLatex");

  return {
    success: true,
    cardinalityBlockVisible: cardinalityBlock && cardinalityBlock.style.display !== "none",
    minSelectedRowVisible: minSelectedRow && minSelectedRow.style.display !== "none",
    maxSelectedRowVisible: maxSelectedRow && maxSelectedRow.style.display !== "none",
    cardinalityLatexContent: cardinalityLatex ? cardinalityLatex.innerHTML : null,
  };
}

/**
 * Test: Reduction mode display
 */
async function testReductionMode(configurator, fieldValues) {
  const { document, window, config } = loadPage(configurator);

  // Set field values using the correct rounds field for this configurator
  const roundsField = config.roundsField;
  const roundsValue = fieldValues.maxRounds || fieldValues.rounds || fieldValues[roundsField];
  if (roundsValue !== undefined) {
    setFieldValues(document, window, { [roundsField]: String(roundsValue) });
  }

  // Wait for debounce and render queue
  await waitForRender(window);

  const reductionContent = document.getElementById("mathReductionContent");
  const content = reductionContent ? reductionContent.innerHTML : "";
  const textContent = reductionContent ? reductionContent.textContent : "";

  // Check for baseline vs reduction indicators
  const isBaseline = /baseline/i.test(textContent) || /senza riduzione/i.test(textContent);
  const isSinglePass = /single[- ]?pass/i.test(textContent) || /un round/i.test(textContent);
  const isMultiRound = /multi[- ]?round/i.test(textContent) || /fino a \d+/i.test(textContent);

  return {
    success: true,
    reductionContent: textContent.substring(0, 500),
    reductionContentHTML: content.substring(0, 500),
    showsBaseline: isBaseline,
    showsSinglePass: isSinglePass,
    showsMultiRound: isMultiRound,
    showsReduction: isSinglePass || isMultiRound,
  };
}

/**
 * Test: Reset restores math panel
 */
async function testReset(configurator) {
  const { document, window, config } = loadPage(configurator);

  // Modify some values using the correct rounds field
  const roundsField = config.roundsField;
  if (configurator === "portfolio") {
    setFieldValues(document, window, {
      assetCount: "50",
      lowerBound: "0.1",
      upperBound: "0.5",
      minSelectedAssets: "5",
      maxSelectedAssets: "10",
      [roundsField]: "3",
    });
  } else if (configurator === "portfolio_sr") {
    setFieldValues(document, window, {
      assetCount: "100",
      upperBound: "0.5",
      maxPositions: "20",
      [roundsField]: "3",
    });
  } else {
    setFieldValues(document, window, {
      [roundsField]: "2",
    });
  }

  // Wait for first render to complete
  await waitForRender(window);

  // Click reset button
  const resetButton = document.getElementById("resetDefaults");
  if (resetButton) {
    resetButton.click();
  }

  // Wait for reset render to complete
  await waitForRender(window);

  // Check values after reset
  if (configurator === "portfolio") {
    const mathAssetCount = document.getElementById("mathAssetCount");
    const mathLowerBound = document.getElementById("mathLowerBound");
    const cardinalityBlock = document.getElementById("mathCardinalityBlock");

    return {
      success: true,
      assetCountAfterReset: mathAssetCount ? mathAssetCount.textContent : null,
      lowerBoundAfterReset: mathLowerBound ? mathLowerBound.textContent : null,
      cardinalityHiddenAfterReset: cardinalityBlock && cardinalityBlock.style.display === "none",
    };
  } else if (configurator === "portfolio_sr") {
    const mathAssetCount = document.getElementById("mathAssetCount");
    const mathUpperBound = document.getElementById("mathUpperBound");
    const cardinalityBlock = document.getElementById("mathCardinalityBlock");
    const reductionContent = document.getElementById("mathReductionContent");
    const content = reductionContent ? reductionContent.textContent : "";

    return {
      success: true,
      assetCountAfterReset: mathAssetCount ? mathAssetCount.textContent : null,
      upperBoundAfterReset: mathUpperBound ? mathUpperBound.textContent : null,
      cardinalityHiddenAfterReset: cardinalityBlock && cardinalityBlock.style.display === "none",
      showsSinglePassAfterReset: /single[- ]?pass/i.test(content) || /un round/i.test(content),
    };
  } else {
    const reductionContent = document.getElementById("mathReductionContent");
    const content = reductionContent ? reductionContent.textContent : "";

    return {
      success: true,
      showsBaselineAfterReset: /baseline/i.test(content),
    };
  }
}

/**
 * Test: Fallback when MathJax fails to load
 */
function testFallbackOnLoadFailure(configurator) {
  const { document, window } = loadPage(configurator, { simulateLoadFailure: true });

  // Check that fallback is shown
  const hasFailed = window.QReduceMath.hasFailed();

  // Check that fallback elements exist
  const latexElements = document.querySelectorAll(".math-latex");
  const fallbackElements = document.querySelectorAll(".math-fallback");

  return {
    success: true,
    mathJaxHasFailed: hasFailed,
    hasLatexElements: latexElements.length > 0,
    hasFallbackElements: fallbackElements.length > 0,
  };
}

/**
 * Test: Render serialization - no DOM modifications during active render
 */
async function testRenderSerialization(configurator) {
  const { document, window, mathJaxCalls, config } = loadPage(configurator, { slowRenderer: true });

  // Get initial revision
  const initialRevision = window.QReduceMath.getRevision();

  // Trigger multiple rapid updates using the correct rounds field
  const fieldName = config.roundsField;
  setFieldValues(document, window, { [fieldName]: "1" });
  const rev1 = window.QReduceMath.getRevision();

  setFieldValues(document, window, { [fieldName]: "2" });
  const rev2 = window.QReduceMath.getRevision();

  setFieldValues(document, window, { [fieldName]: "3" });
  const rev3 = window.QReduceMath.getRevision();

  // Wait for everything to complete
  await waitForRender(window, 300);

  // Check results
  const finalRevision = window.QReduceMath.getRevision();
  const cleansWhileRendering = mathJaxCalls ? mathJaxCalls.cleansWhileRendering : 0;

  return {
    success: true,
    initialRevision: initialRevision,
    revisionAfterUpdates: [rev1, rev2, rev3],
    finalRevision: finalRevision,
    revisionsIncremented: rev3 > initialRevision,
    cleansWhileRendering: cleansWhileRendering,
    noCleansDuringRender: cleansWhileRendering === 0,
  };
}

/**
 * Test: Number formatting preserves precision
 */
function testNumberFormatPrecision() {
  // Create a minimal page to get QReduceMath
  const dom = new JSDOM("<!DOCTYPE html><html><body></body></html>", {
    runScripts: "outside-only",
  });
  const { window } = dom;

  // Load math_formulation.js
  const uixDir = path.join(__dirname, "..", "uix");
  const mathJs = fs.readFileSync(path.join(uixDir, "assets", "math_formulation.js"), "utf8");
  window.eval(mathJs);

  const formatNumber = window.QReduceMath.formatNumber;

  const testCases = [
    { input: "0.001", expected: "0.001" },
    { input: "0.704", expected: "0.704" },
    { input: "0.7", expected: "0.7" },
    { input: "1.000", expected: "1" },
    { input: "1.100", expected: "1.1" },
    { input: 0.001, expected: "0.001" },
    { input: 0.704, expected: "0.704" },
    { input: 30, expected: "30" },
    { input: "", expected: "?" },
    { input: null, expected: "?" },
    { input: undefined, expected: "?" },
  ];

  const results = testCases.map((tc) => ({
    input: tc.input,
    expected: tc.expected,
    actual: formatNumber(tc.input),
    passed: formatNumber(tc.input) === tc.expected,
  }));

  return {
    success: true,
    allPassed: results.every((r) => r.passed),
    results: results,
  };
}

/**
 * Test: Render operations are serialized even when triggered from multiple sources.
 * This tests that initialize() and requestRender() both use the same queue.
 */
async function testLateMathJaxLoading(configurator) {
  // Use the standard loadPage which sets up MathJax mock correctly
  const { document, window, config } = loadPage(configurator, { slowRenderer: true });

  // Track concurrent renders by wrapping the original mock
  const calls = {
    typesetPromise: [],
    maxConcurrentRenders: 0,
  };
  let activeRenders = 0;

  const originalTypeset = window.MathJax.typesetPromise;
  window.MathJax.typesetPromise = function (elements) {
    activeRenders++;
    calls.typesetPromise.push({ timestamp: Date.now() });

    if (activeRenders > calls.maxConcurrentRenders) {
      calls.maxConcurrentRenders = activeRenders;
    }

    return originalTypeset.call(window.MathJax, elements).finally(() => {
      activeRenders--;
    });
  };

  // Initial render has already started from DOMContentLoaded
  // Now trigger multiple rapid updates that should all be serialized
  const fieldName = config.roundsField;

  // These updates arrive while initialize's render might still be in progress
  setFieldValues(document, window, { [fieldName]: "1" });
  setFieldValues(document, window, { [fieldName]: "2" });
  setFieldValues(document, window, { [fieldName]: "3" });

  // Wait for debounce
  const debounceMs = window.QReduceMath._getDebounceMs();
  await new Promise((resolve) => setTimeout(resolve, debounceMs + 50));

  // Wait for all renders to complete
  await new Promise((resolve) => setTimeout(resolve, 300));

  // Wait for render queue
  const queue = window.QReduceMath._getRenderQueue();
  if (queue) {
    await queue;
  }

  return {
    success: true,
    typesetCalls: calls.typesetPromise.length,
    maxConcurrentRenders: calls.maxConcurrentRenders,
    noConcurrentRenders: calls.maxConcurrentRenders <= 1,
  };
}

/**
 * Test: True late MathJax loading - MathJax becomes ready AFTER debounce expires.
 * This tests the specific deadlock scenario where:
 * 1. Debounce expires while MathJax is still loading
 * 2. The queued operation waits for MathJax
 * 3. MathJax becomes ready
 * 4. The queue should complete and render should happen
 */
async function testTrueLateMathJaxLoading(configurator) {
  const config = getConfiguratorConfig(configurator);
  const uixDir = path.join(__dirname, "..", "uix");
  const htmlPath = path.join(uixDir, config.htmlFile);
  const htmlContent = fs.readFileSync(htmlPath, "utf8");

  const dom = new JSDOM(htmlContent, {
    url: "file://" + htmlPath,
    runScripts: "outside-only",
  });

  const { window } = dom;
  const { document } = window;

  setupJsdomGlobals(window);

  // Initialize select elements
  document.querySelectorAll("select").forEach((select) => {
    const firstOption = select.querySelector("option");
    if (firstOption) {
      select.value = firstOption.value;
    }
  });

  // Track render calls
  let typesetCalls = 0;

  // Load common.js
  const commonJs = fs.readFileSync(path.join(uixDir, "assets", "common.js"), "utf8");
  window.eval(commonJs);

  // Load math_formulation.js
  const mathJs = fs.readFileSync(path.join(uixDir, "assets", "math_formulation.js"), "utf8");
  window.eval(mathJs);

  // Reset state - MathJax is NOT ready yet
  window.QReduceMath._resetForTesting();

  // Load specific script based on config
  if (config.scriptMode === "file" && config.scriptFile) {
    const specificJs = fs.readFileSync(path.join(uixDir, "assets", config.scriptFile), "utf8");
    window.eval(specificJs);
  } else if (config.scriptMode === "inline") {
    // Extract and evaluate inline scripts from HTML
    const scriptTags = document.querySelectorAll("script:not([src])");
    scriptTags.forEach((script) => {
      const content = script.textContent;
      if (content && content.includes("DOMContentLoaded")) {
        window.eval(content);
      }
    });
  }

  // Trigger DOMContentLoaded - initialize() will start loading MathJax
  // but since we've reset, it won't be ready
  const initEvent = new window.Event("DOMContentLoaded");
  document.dispatchEvent(initEvent);

  // Set a field value - this will trigger requestRender()
  let fieldName, fieldValue;
  if (configurator === "portfolio") {
    fieldName = "minSelectedAssets";
    fieldValue = "5";
  } else if (configurator === "portfolio_sr") {
    fieldName = "maxPositions";
    fieldValue = "10";
  } else {
    fieldName = config.roundsField;
    fieldValue = "2";
  }
  setFieldValues(document, window, { [fieldName]: fieldValue });

  // Wait for debounce to expire (150ms) - the queued operation should now be waiting for MathJax
  const debounceMs = window.QReduceMath._getDebounceMs();
  await new Promise((resolve) => setTimeout(resolve, debounceMs + 50));

  // At this point, if there's a deadlock, the queue is stuck
  // Now install MathJax mock and mark as ready
  window.MathJax = {
    typesetPromise: function () {
      typesetCalls++;
      return Promise.resolve();
    },
    typesetClear: function () {},
  };
  window.QReduceMath._setReadyForTesting(true);

  // Wait for queue to drain (should not deadlock)
  // Use a timeout to detect deadlock
  let queueCompleted = false;
  const timeoutMs = 500;

  const queuePromise = window.QReduceMath._getRenderQueue();
  const timeoutPromise = new Promise((resolve) =>
    setTimeout(() => resolve("timeout"), timeoutMs)
  );

  const result = await Promise.race([
    queuePromise.then(() => {
      queueCompleted = true;
      return "completed";
    }),
    timeoutPromise,
  ]);

  // Check if a subsequent update works
  let subsequentUpdateWorks = false;
  if (queueCompleted) {
    // Use config-appropriate fields for the subsequent update
    let fieldName2, fieldValue2;
    if (configurator === "portfolio") {
      fieldName2 = "maxSelectedAssets";
      fieldValue2 = "10";
    } else if (configurator === "portfolio_sr") {
      fieldName2 = config.roundsField;
      fieldValue2 = "3";
    } else {
      fieldName2 = config.roundsField;
      fieldValue2 = "3";
    }
    setFieldValues(document, window, { [fieldName2]: fieldValue2 });

    await new Promise((resolve) => setTimeout(resolve, debounceMs + 100));
    await window.QReduceMath._getRenderQueue();

    // Check if content was updated
    if (configurator === "portfolio") {
      const cardinalityLatex = document.getElementById("mathCardinalityLatex");
      subsequentUpdateWorks = cardinalityLatex && cardinalityLatex.innerHTML.length > 0;
    } else if (configurator === "portfolio_sr") {
      const reductionContent = document.getElementById("mathReductionContent");
      subsequentUpdateWorks =
        reductionContent && /multi[- ]?round/i.test(reductionContent.textContent);
    } else {
      const reductionContent = document.getElementById("mathReductionContent");
      subsequentUpdateWorks =
        reductionContent && reductionContent.innerHTML.includes("multi-round");
    }
  }

  return {
    success: true,
    queueCompleted: queueCompleted,
    typesetCalls: typesetCalls,
    subsequentUpdateWorks: subsequentUpdateWorks,
    noDeadlock: queueCompleted && typesetCalls > 0,
  };
}

/**
 * Test: DOM mutations don't happen during active render.
 * Uses MutationObserver to detect DOM changes while MathJax is rendering.
 */
async function testMutationsDuringRender(configurator) {
  const { document, window, mathJaxCalls, config } = loadPage(configurator, { slowRenderer: true });

  // Track mutations to the math content panel
  const mathContent = document.getElementById("mathContent");
  const mutations = {
    duringRender: [],
    outsideRender: [],
  };

  // Set up MutationObserver
  const observer = new window.MutationObserver((mutationsList) => {
    const isRendering = window.MathJax && window.MathJax._isRendering && window.MathJax._isRendering();
    mutationsList.forEach((mutation) => {
      const record = {
        type: mutation.type,
        target: mutation.target.id || mutation.target.tagName,
        timestamp: Date.now(),
      };
      if (isRendering) {
        mutations.duringRender.push(record);
      } else {
        mutations.outsideRender.push(record);
      }
    });
  });

  observer.observe(mathContent, {
    childList: true,
    subtree: true,
    characterData: true,
    attributes: true,
  });

  // Start a render by changing a parameter using the correct field
  const fieldName = config.roundsField;
  setFieldValues(document, window, { [fieldName]: "2" });

  // Wait for debounce
  const debounceMs = window.QReduceMath._getDebounceMs();
  await new Promise((resolve) => setTimeout(resolve, debounceMs + 20));

  // Now MathJax should be rendering (slow render is 100ms)
  // Try to trigger another update during the render
  setFieldValues(document, window, { [fieldName]: "3" });

  // Wait for everything to complete
  await new Promise((resolve) => setTimeout(resolve, 400));

  // Wait for render queue
  const queue = window.QReduceMath._getRenderQueue();
  if (queue) {
    await queue;
  }

  observer.disconnect();

  // Mutations during render should be minimal - only MathJax adding mjx-container
  // User DOM updates (innerHTML) should NOT happen during render
  const userMutationsDuringRender = mutations.duringRender.filter((m) => {
    // MathJax adds mjx-container - that's expected
    // User code changing innerHTML or textContent is NOT expected
    return m.type === "childList" && m.target !== "mathContent";
  });

  return {
    success: true,
    mutationsDuringRender: mutations.duringRender.length,
    userMutationsDuringRender: userMutationsDuringRender.length,
    mutationsOutsideRender: mutations.outsideRender.length,
    noUserMutationsDuringRender: userMutationsDuringRender.length === 0,
    details: {
      duringRender: mutations.duringRender.slice(0, 10),
      outsideRender: mutations.outsideRender.slice(0, 10),
    },
  };
}

/**
 * Test: TeX has no internal HTML tags
 */
function testNoHtmlInTex(configurator) {
  const { document } = loadPage(configurator);

  const mathLatexElements = document.querySelectorAll(".math-latex");
  const violations = [];

  mathLatexElements.forEach((el, index) => {
    const source = el.getAttribute("data-tex-source") || el.innerHTML;

    // Check for span, div, or other HTML tags inside TeX delimiters
    // Look for patterns like \[...<span>...\] or \(...<div>...\)
    const texBlockMatch = source.match(/\\\[[\s\S]*?\\\]|\\\([\s\S]*?\\\)/g) || [];

    texBlockMatch.forEach((block) => {
      // Check for HTML tags inside the TeX block
      if (/<(span|div|p|a|b|i|em|strong)[^>]*>/i.test(block)) {
        violations.push({
          elementIndex: index,
          elementId: el.id || "(no id)",
          snippet: block.substring(0, 200),
        });
      }
    });
  });

  return {
    success: true,
    totalLatexElements: mathLatexElements.length,
    violationsFound: violations.length,
    violations: violations,
    noViolations: violations.length === 0,
  };
}

/**
 * Test: Portfolio SR specific - values update
 */
async function testPortfolioSRUpdateValues(fieldValues) {
  const { document, window, mathJaxCalls } = loadPage("portfolio_sr");

  // Set field values
  setFieldValues(document, window, fieldValues);

  // Wait for debounce and render queue
  await waitForRender(window);

  // Read displayed values
  const mathAssetCount = document.getElementById("mathAssetCount");
  const mathUpperBound = document.getElementById("mathUpperBound");
  const mathMaxPositions = document.getElementById("mathMaxPositions");

  // Check if script was executed and rendering happened
  const mathContent = document.getElementById("mathContent");
  const hasRenderedContent = mathJaxCalls.typesetPromise.length > 0 && !!mathContent.querySelector('mjx-container');
  const visible = (id) => document.getElementById(id).style.display !== 'none';

  // Read summary values
  const summaryRunId = document.getElementById("summaryRunId");
  const summaryAssets = document.getElementById("summaryAssets");
  const summaryMode = document.getElementById("summaryMode");
  const summaryReduction = document.getElementById("summaryReduction");
  const summaryMis = document.getElementById("summaryMis");
  const summaryClassical = document.getElementById("summaryClassical");

  return {
    success: true,
    hasMathContent: !!mathContent,
    hasRenderedContent: hasRenderedContent,
    displayedAssetCount: mathAssetCount ? mathAssetCount.textContent : null,
    displayedUpperBound: mathUpperBound ? mathUpperBound.textContent : null,
    displayedMaxPositions: mathMaxPositions ? mathMaxPositions.textContent : null,
    cardinalityVisible: visible('mathCardinalityBlock'),
    transformedCardinalityVisible: visible('mathTransformedCardinalityBlock'),
    cardinalityText: document.getElementById('mathTransformedCardinalityBlock').textContent,
    sectorVisible: visible('mathSectorBlock'),
    sectorFormulaVisible: document.querySelector('#mathSectorBlock .math-formula').style.display !== 'none',
    sectorDetails: document.getElementById('mathSectorDetails').textContent,
    transformedSectorDetails: document.getElementById('mathTransformedSectorNote').textContent,
    reductionText: document.getElementById('mathReductionContent').textContent,
    valid: document.getElementById('validationBadge').textContent === 'Configurazione valida',
    copyDisabled: document.getElementById('copyCommand').disabled,
    command: document.getElementById('cliPreview').textContent,
    // Summary panel values
    summaryRunId: summaryRunId ? summaryRunId.textContent : null,
    summaryAssets: summaryAssets ? summaryAssets.textContent : null,
    summaryMode: summaryMode ? summaryMode.textContent : null,
    summaryReduction: summaryReduction ? summaryReduction.textContent : null,
    summaryMis: summaryMis ? summaryMis.textContent : null,
    summaryClassical: summaryClassical ? summaryClassical.textContent : null,
  };
}

/** Verify repeated renders with a renderer that consumes the original TeX. */
async function testSROptionalFormulaLifecycle() {
  const { document, window, mathJaxCalls } = loadPage('portfolio_sr', { consumeTex: true });
  const ids = ['mathObjective', 'mathConstraints', 'mathCardinalityBlock', 'mathSectorBlock',
    'mathTransformedSectorBlock', 'mathTransformedCardinalityBlock'];
  const stages = [];
  const changes = [{}, { maxPositions: '10', sectorMin: 'Technology=0.1' },
    { upperBound: '0.5' }, { maxPositions: '8' }, { maxPositions: '', sectorMin: '' },
    { maxPositions: '5', sectorMax: 'Technology=0.4' }];
  for (const fields of changes) {
    setFieldValues(document, window, fields);
    await waitForRender(window);
    stages.push(ids.every((id) => Array.from(document.querySelectorAll('#' + id + ' .math-latex'))
      .every((el) => el.getAttribute('data-tex-source')?.includes('\\') && el.querySelector('mjx-container'))));
  }
  document.getElementById('resetDefaults').click();
  await waitForRender(window);
  stages.push(ids.every((id) => !!document.querySelector('#' + id + ' mjx-container')));
  return { success: true, stages, typesetCalls: mathJaxCalls.typesetPromise.length,
    cardinalityHidden: document.getElementById('mathCardinalityBlock').style.display === 'none',
    sectorsHidden: document.getElementById('mathSectorBlock').style.display === 'none' };
}

/**
 * Test SR summary panel: initial state, mode transitions, format switching, copy, and reset.
 */
async function testSRSummaryPanel(fieldValues) {
  const { document, window } = loadPage('portfolio_sr');

  // Capture initial state
  const getState = () => ({
    runId: document.getElementById('summaryRunId').textContent,
    assets: document.getElementById('summaryAssets').textContent,
    mode: document.getElementById('summaryMode').textContent,
    reduction: document.getElementById('summaryReduction').textContent,
    mis: document.getElementById('summaryMis').textContent,
    classical: document.getElementById('summaryClassical').textContent,
    valid: document.getElementById('validationBadge').textContent === 'Configurazione valida',
    copyDisabled: document.getElementById('copyCommand').disabled,
    validationInvalid: document.getElementById('validationStatus').classList.contains('invalid'),
    validationTitle: document.getElementById('validationTitle').textContent,
    validationText: document.getElementById('validationText').textContent,
    command: document.getElementById('cliPreview').textContent,
    format: document.querySelector('.format-selector button.active').dataset.format,
  });

  const initial = getState();

  // Apply field values if provided
  if (fieldValues && Object.keys(fieldValues).length > 0) {
    setFieldValues(document, window, fieldValues);
    await waitForRender(window);
  }
  const afterChange = getState();

  const clipboardCalls = [];
  const originalClipboard = window.navigator.clipboard;
  window.navigator.clipboard = {
    writeText: (text) => { clipboardCalls.push(text); return Promise.resolve(); },
  };

  // Test format switching
  const multilineBtn = document.querySelector('.format-selector button[data-format="multiline"]');
  multilineBtn.click();
  await waitForRender(window);
  const afterMultiline = getState();
  document.getElementById('copyCommand').click();
  await Promise.resolve();
  const multilineCopies = clipboardCalls.slice();

  const inlineBtn = document.querySelector('.format-selector button[data-format="inline"]');
  inlineBtn.click();
  await waitForRender(window);
  const afterInline = getState();

  // Test copy behavior (simulate clipboard)
  const callsBeforeInline = clipboardCalls.length;
  document.getElementById('copyCommand').click();
  await Promise.resolve();
  const inlineCopies = clipboardCalls.slice(callsBeforeInline);
  const copiedText = inlineCopies[0] ?? null;

  // Invalidate the same page after valid copies, then verify recovery via reset.
  setFieldValues(document, window, { runId: '' });
  await waitForRender(window);
  const afterInvalid = getState();
  const callsBeforeInvalid = clipboardCalls.length;
  document.getElementById('copyCommand').click();
  await Promise.resolve();
  const callsAfterInvalid = clipboardCalls.length;

  // Test reset
  document.getElementById('resetDefaults').click();
  await waitForRender(window);
  const afterReset = getState();
  const callsBeforeResetCopy = clipboardCalls.length;
  document.getElementById('copyCommand').click();
  await Promise.resolve();
  const resetCopies = clipboardCalls.slice(callsBeforeResetCopy);
  window.navigator.clipboard = originalClipboard;

  // Exercise real transitions without reloading the DOM between states.
  const roundTransitions = [];
  for (const rounds of ['3', '-1', '0', '1']) {
    setFieldValues(document, window, { maxRounds: rounds });
    await waitForRender(window);
    roundTransitions.push(getState());
  }

  return {
    success: true,
    initial,
    afterChange,
    afterMultiline,
    afterInline,
    afterReset,
    afterInvalid,
    multilineCopies,
    inlineCopies,
    resetCopies,
    callsBeforeInvalid,
    callsAfterInvalid,
    roundTransitions,
    copiedText,
    copyMatchesPreview: copiedText === afterInline.command,
  };
}

async function main() {
  const args = process.argv.slice(2);
  if (args.length < 2) {
    console.error("Usage: node uix_math_runner.js <configurator> <test_type> [json_input]");
    console.error(`  configurator: ${VALID_CONFIGURATORS.join(", ")}`);
    console.error("  test_type: init, tex_preservation, formula_restoration, update_values,");
    console.error("             cardinality, cardinality_survives, cardinality_updates,");
    console.error("             reduction_mode, reset, fallback_load_failure,");
    console.error("             render_serialization, number_precision, no_html_in_tex");
    process.exit(1);
  }

  const configurator = args[0];
  const testType = args[1];
  const jsonInput = args[2] ? JSON.parse(args[2]) : {};

  if (!VALID_CONFIGURATORS.includes(configurator)) {
    console.error(`Invalid configurator: ${configurator}. Valid: ${VALID_CONFIGURATORS.join(", ")}`);
    process.exit(1);
  }

  try {
    let result;

    switch (testType) {
      case "sr_formula_lifecycle":
        result = await testSROptionalFormulaLifecycle();
        break;
      case "sr_summary_panel":
        result = await testSRSummaryPanel(jsonInput);
        break;
      case "risk_aversion":
        result = await testRiskAversion(jsonInput);
        break;
      case "init":
        result = testInit(configurator);
        break;
      case "tex_preservation":
        result = testTexSourcePreservation(configurator);
        break;
      case "formula_restoration":
        result = await testFormulaRestoration(configurator);
        break;
      case "values_update":
      case "update_values":
        if (configurator === "portfolio") {
          result = await testPortfolioUpdateValues(jsonInput);
        } else if (configurator === "portfolio_sr") {
          result = await testPortfolioSRUpdateValues(jsonInput);
        } else {
          result = { success: false, error: "update_values only for portfolio/portfolio_sr" };
        }
        break;
      case "cardinality":
        if (configurator !== "portfolio") {
          result = { success: false, error: "cardinality only for portfolio" };
        } else {
          result = await testPortfolioCardinality(jsonInput);
        }
        break;
      case "cardinality_survives":
        if (configurator !== "portfolio") {
          result = { success: false, error: "cardinality_survives only for portfolio" };
        } else {
          result = await testCardinalitySurvivesDebounce(jsonInput);
        }
        break;
      case "cardinality_updates":
        if (configurator !== "portfolio") {
          result = { success: false, error: "cardinality_updates only for portfolio" };
        } else {
          result = await testMultipleCardinalityUpdates();
        }
        break;
      case "reduction_mode":
        result = await testReductionMode(configurator, jsonInput);
        break;
      case "reset":
        result = await testReset(configurator);
        break;
      case "fallback":
        // Legacy name
        result = testFallbackOnLoadFailure(configurator);
        break;
      case "fallback_load_failure":
        result = testFallbackOnLoadFailure(configurator);
        break;
      case "render_serialization":
        result = await testRenderSerialization(configurator);
        break;
      case "number_precision":
        result = testNumberFormatPrecision();
        break;
      case "no_html_in_tex":
        result = testNoHtmlInTex(configurator);
        break;
      case "late_loading":
        result = await testLateMathJaxLoading(configurator);
        break;
      case "true_late_loading":
        result = await testTrueLateMathJaxLoading(configurator);
        break;
      case "mutations_during_render":
        result = await testMutationsDuringRender(configurator);
        break;
      default:
        result = { success: false, error: `Unknown test type: ${testType}` };
    }

    console.log(JSON.stringify(result));
  } catch (e) {
    console.error(`Error: ${e.message}`);
    console.error(e.stack);
    process.exit(1);
  }
}

main();
