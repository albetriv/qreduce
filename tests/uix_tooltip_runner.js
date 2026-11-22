#!/usr/bin/env node
/**
 * Test runner for UIX tooltip initialization and behavior.
 *
 * Usage: node tests/uix_tooltip_runner.js <configurator> [test_type]
 *
 * Where:
 *   configurator: "portfolio" or "facility_location"
 *   test_type: "init", "click", "escape", "exclusive", "hover_focus_click",
 *              "focus_enter", "pinned_behavior", "form_controls"
 *
 * Output: JSON object with test results
 */

const { JSDOM } = require("jsdom");
const fs = require("fs");
const path = require("path");

/**
 * Setup jsdom with required globals for the tooltip code.
 */
function setupJsdomGlobals(window) {
  // Polyfill requestAnimationFrame for jsdom (not available by default)
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
 * Helper to simulate focus on an element.
 */
function simulateFocus(element, window) {
  element.focus();
  const focusEvent = new window.FocusEvent("focus", {
    bubbles: true,
    cancelable: true,
  });
  element.dispatchEvent(focusEvent);
}

/**
 * Helper to simulate blur on an element.
 */
function simulateBlur(element, window) {
  element.blur();
  const blurEvent = new window.FocusEvent("blur", {
    bubbles: true,
    cancelable: true,
  });
  element.dispatchEvent(blurEvent);
}

/**
 * Helper to simulate mouseenter on an element.
 */
function simulateMouseEnter(element, window) {
  const event = new window.MouseEvent("mouseenter", {
    bubbles: true,
    cancelable: true,
    view: window,
  });
  element.dispatchEvent(event);
}

/**
 * Helper to simulate mouseleave on an element.
 */
function simulateMouseLeave(element, window) {
  const event = new window.MouseEvent("mouseleave", {
    bubbles: true,
    cancelable: true,
    view: window,
  });
  element.dispatchEvent(event);
}

/**
 * Helper to simulate click on an element.
 */
function simulateClick(element, window) {
  const event = new window.MouseEvent("click", {
    bubbles: true,
    cancelable: true,
    view: window,
  });
  element.dispatchEvent(event);
}

/**
 * Helper to simulate keydown on an element.
 */
function simulateKeydown(element, key, window) {
  const event = new window.KeyboardEvent("keydown", {
    key: key,
    bubbles: true,
    cancelable: true,
  });
  element.dispatchEvent(event);
}

/**
 * Wait for setTimeout callbacks to execute.
 */
function flushTimeouts() {
  return new Promise((resolve) => setTimeout(resolve, 150));
}

/**
 * Extract all form control IDs from the DOM.
 */
function getFormControlIds(document) {
  const controls = document.querySelectorAll("#configForm input, #configForm select, #configForm textarea");
  const ids = [];
  controls.forEach((control) => {
    if (control.id) {
      ids.push(control.id);
    }
  });
  return ids;
}

/**
 * Run initialization test - verify tooltips are created correctly.
 */
function runInitTest(document, window) {
  const tooltipWrappers = document.querySelectorAll(".tooltip-wrapper");
  const tooltipCount = tooltipWrappers.length;

  const fieldsWithTooltips = [];
  const tooltipTexts = {};
  const tooltipIds = [];
  let usesButtonElement = true;
  let hasAriaDescribedby = true;
  let hasAriaExpanded = true;
  let buttonOutsideLabel = true;

  tooltipWrappers.forEach((wrapper) => {
    // Check if using button element
    const button = wrapper.querySelector("button.info-icon");
    if (!button) {
      usesButtonElement = false;
    }

    // Check aria-describedby
    if (button && !button.hasAttribute("aria-describedby")) {
      hasAriaDescribedby = false;
    }

    // Check aria-expanded
    if (button && !button.hasAttribute("aria-expanded")) {
      hasAriaExpanded = false;
    }

    // Check if button is outside label (wrapper is sibling of label, not child)
    const parentLabel = wrapper.closest("label");
    if (parentLabel) {
      buttonOutsideLabel = false;
    }

    // Get tooltip ID
    const tooltip = wrapper.querySelector(".tooltip");
    if (tooltip && tooltip.id) {
      tooltipIds.push(tooltip.id);
    }

    // Find the associated field
    const field = wrapper.closest(".field");
    const switchRow = wrapper.closest(".switch-row");

    let fieldId = null;

    if (field) {
      const input = field.querySelector("input, select, textarea");
      if (input && input.id) {
        fieldId = input.id;
      }
    } else if (switchRow) {
      const input = switchRow.querySelector("input");
      if (input && input.id) {
        fieldId = input.id;
      }
    }

    if (fieldId) {
      fieldsWithTooltips.push(fieldId);
      if (tooltip) {
        tooltipTexts[fieldId] = tooltip.textContent.trim();
      }
    }
  });

  // Get all form control IDs for comparison
  const formControlIds = getFormControlIds(document);

  return {
    tooltipCount,
    infoIconCount: document.querySelectorAll(".info-icon").length,
    fieldsWithTooltips,
    tooltipTexts,
    tooltipIds,
    usesButtonElement,
    hasAriaDescribedby,
    hasAriaExpanded,
    buttonOutsideLabel,
    formControlIds,
    errors: [],
  };
}

/**
 * Run click test - verify clicking opens tooltip.
 */
function runClickTest(document, window) {
  const wrapper = document.querySelector(".tooltip-wrapper");
  if (!wrapper) {
    return { tooltipOpened: false, error: "No tooltip wrapper found" };
  }

  const button = wrapper.querySelector("button.info-icon, .info-icon");
  const tooltip = wrapper.querySelector(".tooltip");

  if (!button || !tooltip) {
    return { tooltipOpened: false, error: "Button or tooltip not found" };
  }

  // Initially tooltip should not be active
  const initiallyActive = tooltip.classList.contains("tooltip-active");

  // Simulate click
  simulateClick(button, window);

  // Allow event handlers to run
  const afterClickActive = tooltip.classList.contains("tooltip-active");

  return {
    tooltipOpened: !initiallyActive && afterClickActive,
    initiallyActive,
    afterClickActive,
  };
}

/**
 * Run escape test - verify Escape key closes tooltip.
 */
function runEscapeTest(document, window) {
  const wrapper = document.querySelector(".tooltip-wrapper");
  if (!wrapper) {
    return { tooltipClosed: false, error: "No tooltip wrapper found" };
  }

  const button = wrapper.querySelector("button.info-icon, .info-icon");
  const tooltip = wrapper.querySelector(".tooltip");

  if (!button || !tooltip) {
    return { tooltipClosed: false, error: "Button or tooltip not found" };
  }

  // First, open the tooltip via click (pinned)
  simulateClick(button, window);
  const afterClickActive = tooltip.classList.contains("tooltip-active");

  // Now simulate Escape key
  simulateKeydown(document, "Escape", window);
  const afterEscapeActive = tooltip.classList.contains("tooltip-active");

  return {
    tooltipClosed: afterClickActive && !afterEscapeActive,
    afterClickActive,
    afterEscapeActive,
  };
}

/**
 * Run exclusive test - verify only one tooltip can be open.
 */
function runExclusiveTest(document, window) {
  const wrappers = document.querySelectorAll(".tooltip-wrapper");
  if (wrappers.length < 2) {
    return { onlyOneOpen: true, error: "Need at least 2 tooltips to test exclusivity" };
  }

  const wrapper1 = wrappers[0];
  const wrapper2 = wrappers[1];

  const button1 = wrapper1.querySelector("button.info-icon, .info-icon");
  const button2 = wrapper2.querySelector("button.info-icon, .info-icon");
  const tooltip1 = wrapper1.querySelector(".tooltip");
  const tooltip2 = wrapper2.querySelector(".tooltip");

  if (!button1 || !button2 || !tooltip1 || !tooltip2) {
    return { onlyOneOpen: false, error: "Buttons or tooltips not found" };
  }

  // Click first tooltip (pins it)
  simulateClick(button1, window);
  const tooltip1AfterClick1 = tooltip1.classList.contains("tooltip-active");
  const tooltip2AfterClick1 = tooltip2.classList.contains("tooltip-active");

  // Click second tooltip (should close first, open second)
  simulateClick(button2, window);
  const tooltip1AfterClick2 = tooltip1.classList.contains("tooltip-active");
  const tooltip2AfterClick2 = tooltip2.classList.contains("tooltip-active");

  // Only one should be open: first open after click1, then second open after click2
  const onlyOneOpen =
    tooltip1AfterClick1 &&
    !tooltip2AfterClick1 &&
    !tooltip1AfterClick2 &&
    tooltip2AfterClick2;

  return {
    onlyOneOpen,
    tooltip1AfterClick1,
    tooltip2AfterClick1,
    tooltip1AfterClick2,
    tooltip2AfterClick2,
  };
}

/**
 * Test sequence: hover -> focus -> click
 * Verifies that:
 * 1. Hover opens tooltip (temporary)
 * 2. Focus keeps tooltip open
 * 3. Click pins the tooltip (doesn't close it)
 */
async function runHoverFocusClickTest(document, window) {
  const wrapper = document.querySelector(".tooltip-wrapper");
  if (!wrapper) {
    return { success: false, error: "No tooltip wrapper found" };
  }

  const button = wrapper.querySelector("button.info-icon, .info-icon");
  const tooltip = wrapper.querySelector(".tooltip");

  if (!button || !tooltip) {
    return { success: false, error: "Button or tooltip not found" };
  }

  const results = {
    initiallyActive: tooltip.classList.contains("tooltip-active"),
  };

  // Step 1: Hover (mouseenter)
  simulateMouseEnter(wrapper, window);
  await flushTimeouts();
  results.afterHoverActive = tooltip.classList.contains("tooltip-active");

  // Step 2: Focus (while still hovering)
  simulateFocus(button, window);
  await flushTimeouts();
  results.afterFocusActive = tooltip.classList.contains("tooltip-active");

  // Step 3: Click (while focused)
  simulateClick(button, window);
  await flushTimeouts();
  results.afterClickActive = tooltip.classList.contains("tooltip-active");

  // The tooltip should be pinned and remain open
  results.success =
    !results.initiallyActive &&
    results.afterHoverActive &&
    results.afterFocusActive &&
    results.afterClickActive;

  return results;
}

/**
 * Test sequence: focus -> Enter
 * Verifies that focus opens tooltip and Enter pins it (doesn't close it).
 */
async function runFocusEnterTest(document, window) {
  const wrapper = document.querySelector(".tooltip-wrapper");
  if (!wrapper) {
    return { success: false, error: "No tooltip wrapper found" };
  }

  const button = wrapper.querySelector("button.info-icon, .info-icon");
  const tooltip = wrapper.querySelector(".tooltip");

  if (!button || !tooltip) {
    return { success: false, error: "Button or tooltip not found" };
  }

  const results = {
    initiallyActive: tooltip.classList.contains("tooltip-active"),
  };

  // Step 1: Focus
  simulateFocus(button, window);
  await flushTimeouts();
  results.afterFocusActive = tooltip.classList.contains("tooltip-active");

  // Step 2: Press Enter (should pin, not close)
  simulateKeydown(button, "Enter", window);
  await flushTimeouts();
  results.afterEnterActive = tooltip.classList.contains("tooltip-active");

  // The tooltip should be pinned and remain open
  results.success =
    !results.initiallyActive &&
    results.afterFocusActive &&
    results.afterEnterActive;

  return results;
}

/**
 * Test pinned behavior:
 * 1. Hover opens, mouseleave closes (not pinned)
 * 2. Click pins, mouseleave doesn't close (pinned)
 * 3. Second click unpins and closes
 */
async function runPinnedBehaviorTest(document, window) {
  const wrapper = document.querySelector(".tooltip-wrapper");
  if (!wrapper) {
    return { success: false, error: "No tooltip wrapper found" };
  }

  const button = wrapper.querySelector("button.info-icon, .info-icon");
  const tooltip = wrapper.querySelector(".tooltip");

  if (!button || !tooltip) {
    return { success: false, error: "Button or tooltip not found" };
  }

  const results = {};

  // Test 1: Hover opens, mouseleave closes (not pinned)
  simulateMouseEnter(wrapper, window);
  await flushTimeouts();
  results.hoverOpens = tooltip.classList.contains("tooltip-active");

  simulateMouseLeave(wrapper, window);
  await flushTimeouts();
  results.leaveClosesUnpinned = !tooltip.classList.contains("tooltip-active");

  // Test 2: Click pins, mouseleave doesn't close
  simulateClick(button, window);
  await flushTimeouts();
  results.clickPins = tooltip.classList.contains("tooltip-active");

  simulateMouseLeave(wrapper, window);
  await flushTimeouts();
  results.leaveKeepsPinned = tooltip.classList.contains("tooltip-active");

  // Test 3: Second click unpins and closes
  simulateClick(button, window);
  await flushTimeouts();
  results.secondClickCloses = !tooltip.classList.contains("tooltip-active");

  results.success =
    results.hoverOpens &&
    results.leaveClosesUnpinned &&
    results.clickPins &&
    results.leaveKeepsPinned &&
    results.secondClickCloses;

  return results;
}

/**
 * Compare tooltips with actual form controls.
 * Returns IDs of form controls that don't have tooltips.
 */
function runFormControlsTest(document, window) {
  const formControlIds = getFormControlIds(document);
  const tooltipWrappers = document.querySelectorAll(".tooltip-wrapper");

  const fieldsWithTooltips = new Set();
  tooltipWrappers.forEach((wrapper) => {
    const field = wrapper.closest(".field");
    const switchRow = wrapper.closest(".switch-row");

    if (field) {
      const input = field.querySelector("input, select, textarea");
      if (input && input.id) {
        fieldsWithTooltips.add(input.id);
      }
    } else if (switchRow) {
      const input = switchRow.querySelector("input");
      if (input && input.id) {
        fieldsWithTooltips.add(input.id);
      }
    }
  });

  const controlsWithoutTooltips = formControlIds.filter(
    (id) => !fieldsWithTooltips.has(id)
  );
  const tooltipsWithoutControls = [...fieldsWithTooltips].filter(
    (id) => !formControlIds.includes(id)
  );

  return {
    formControlCount: formControlIds.length,
    tooltipCount: fieldsWithTooltips.size,
    controlsWithoutTooltips,
    tooltipsWithoutControls,
    allControlsHaveTooltips: controlsWithoutTooltips.length === 0,
    formControlIds,
    fieldsWithTooltips: [...fieldsWithTooltips],
  };
}

async function main() {
  const args = process.argv.slice(2);
  if (args.length < 1) {
    console.error("Usage: node uix_tooltip_runner.js <configurator> [test_type]");
    console.error('  configurator: "portfolio" or "facility_location"');
    console.error('  test_type: "init", "click", "escape", "exclusive", "hover_focus_click",');
    console.error('             "focus_enter", "pinned_behavior", "form_controls"');
    process.exit(1);
  }

  const configurator = args[0];
  const testType = args[1] || "init";

  if (!["portfolio", "facility_location"].includes(configurator)) {
    console.error(`Invalid configurator: ${configurator}`);
    process.exit(1);
  }

  const validTestTypes = [
    "init",
    "click",
    "escape",
    "exclusive",
    "hover_focus_click",
    "focus_enter",
    "pinned_behavior",
    "form_controls",
  ];

  if (!validTestTypes.includes(testType)) {
    console.error(`Invalid test type: ${testType}`);
    process.exit(1);
  }

  try {
    const uixDir = path.join(__dirname, "..", "uix");
    const htmlFile =
      configurator === "portfolio"
        ? "experiment_portfolio_mv.html"
        : "experiment_facility_location.html";
    const htmlPath = path.join(uixDir, htmlFile);

    if (!fs.existsSync(htmlPath)) {
      throw new Error(`HTML file not found: ${htmlPath}`);
    }

    const htmlContent = fs.readFileSync(htmlPath, "utf8");

    // Create DOM without running scripts
    const dom = new JSDOM(htmlContent, {
      url: "file://" + htmlPath,
      runScripts: "outside-only",
    });

    const { window } = dom;
    const { document } = window;

    // Setup required globals
    setupJsdomGlobals(window);

    // Initialize select elements to their first option (default browser behavior)
    document.querySelectorAll("select").forEach((select) => {
      const firstOption = select.querySelector("option");
      if (firstOption) {
        select.value = firstOption.value;
      }
    });

    // Load and execute common.js
    const commonJs = fs.readFileSync(path.join(uixDir, "assets", "common.js"), "utf8");
    window.eval(commonJs);

    // Load specific script
    const specificJs =
      configurator === "portfolio"
        ? fs.readFileSync(path.join(uixDir, "assets", "portfolio_mv.js"), "utf8")
        : fs.readFileSync(path.join(uixDir, "assets", "facility_location.js"), "utf8");
    window.eval(specificJs);

    // Trigger DOMContentLoaded to initialize the scripts (including tooltips)
    const initEvent = new window.Event("DOMContentLoaded");
    document.dispatchEvent(initEvent);
    // Initialization is idempotent: repeated calls must not duplicate
    // wrappers or handlers, including those of the static catalog tooltip.
    window.QReduceCommon.initTooltips();

    // Run the appropriate test
    let result;
    switch (testType) {
      case "click":
        result = runClickTest(document, window);
        break;
      case "escape":
        result = runEscapeTest(document, window);
        break;
      case "exclusive":
        result = runExclusiveTest(document, window);
        break;
      case "hover_focus_click":
        result = await runHoverFocusClickTest(document, window);
        break;
      case "focus_enter":
        result = await runFocusEnterTest(document, window);
        break;
      case "pinned_behavior":
        result = await runPinnedBehaviorTest(document, window);
        break;
      case "form_controls":
        result = runFormControlsTest(document, window);
        break;
      case "init":
      default:
        result = runInitTest(document, window);
        break;
    }

    console.log(JSON.stringify(result));
  } catch (e) {
    const errorResult = {
      tooltipCount: 0,
      infoIconCount: 0,
      fieldsWithTooltips: [],
      tooltipTexts: {},
      tooltipIds: [],
      usesButtonElement: false,
      hasAriaDescribedby: false,
      hasAriaExpanded: false,
      buttonOutsideLabel: false,
      errors: [e.message, e.stack],
    };
    console.log(JSON.stringify(errorResult));
    process.exit(1);
  }
}

main();
