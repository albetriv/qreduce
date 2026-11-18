#!/usr/bin/env node
/**
 * Test runner for UIX JavaScript DOM state transitions.
 *
 * Unlike uix_js_runner.js which sets values all at once, this runner
 * applies changes in sequence and triggers proper DOM events between steps.
 *
 * Usage: node tests/uix_transition_runner.js <configurator> <steps_json>
 *
 * Where:
 *   configurator: "portfolio" or "facility_location"
 *   steps_json: JSON array of steps, each with {set: {id: value}, verify: {id: expected}}
 *
 * Output: JSON object with { success, steps: [...results per step] }
 */

const { JSDOM } = require("jsdom");
const fs = require("fs");
const path = require("path");

function main() {
  const args = process.argv.slice(2);
  if (args.length < 2) {
    console.error("Usage: node uix_transition_runner.js <configurator> <steps_json>");
    process.exit(1);
  }

  const configurator = args[0];
  const stepsJson = args[1];

  if (!["portfolio", "facility_location"].includes(configurator)) {
    console.error(`Invalid configurator: ${configurator}`);
    process.exit(1);
  }

  let steps;
  try {
    steps = JSON.parse(stepsJson);
    if (!Array.isArray(steps)) {
      throw new Error("steps_json must be an array");
    }
  } catch (e) {
    console.error(`Invalid JSON input: ${e.message}`);
    process.exit(1);
  }

  try {
    const uixDir = path.join(__dirname, "..", "uix");
    const htmlFile =
      configurator === "portfolio"
        ? "experiment_portfolio.html"
        : "experiment_facility_location.html";
    const htmlPath = path.join(uixDir, htmlFile);

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

    // Initialize select elements
    document.querySelectorAll("select").forEach((select) => {
      const firstOption = select.querySelector("option");
      if (firstOption) {
        select.value = firstOption.value;
      }
    });

    // Load and execute scripts
    const commonJs = fs.readFileSync(path.join(uixDir, "assets", "common.js"), "utf8");
    window.eval(commonJs);

    const specificJs =
      configurator === "portfolio"
        ? fs.readFileSync(path.join(uixDir, "assets", "portfolio.js"), "utf8")
        : fs.readFileSync(path.join(uixDir, "assets", "facility_location.js"), "utf8");
    window.eval(specificJs);

    // Trigger DOMContentLoaded
    const initEvent = new window.Event("DOMContentLoaded");
    document.dispatchEvent(initEvent);

    // Helper to set a value and trigger events
    function setFieldValue(id, value) {
      const el = document.getElementById(id);
      if (!el) return false;

      if (el.type === "checkbox") {
        el.checked = Boolean(value);
      } else {
        el.value = String(value);
      }

      // Trigger both input and change events (as the UI handlers expect)
      el.dispatchEvent(new window.Event("input", { bubbles: true }));
      el.dispatchEvent(new window.Event("change", { bubbles: true }));
      return true;
    }

    // Helper to get field state
    function getFieldState(id) {
      const el = document.getElementById(id);
      if (!el) return { exists: false };

      return {
        exists: true,
        value: el.type === "checkbox" ? el.checked : el.value,
        disabled: el.disabled,
      };
    }

    // Process each step
    const stepResults = [];
    let allSuccess = true;

    for (let i = 0; i < steps.length; i++) {
      const step = steps[i];
      const stepResult = { index: i, set: [], verify: [] };

      // Apply "set" values
      if (step.set) {
        for (const [id, value] of Object.entries(step.set)) {
          const success = setFieldValue(id, value);
          stepResult.set.push({ id, value, success });
          if (!success) allSuccess = false;
        }
      }

      // Verify expected values
      if (step.verify) {
        for (const [id, expected] of Object.entries(step.verify)) {
          const state = getFieldState(id);
          let match = false;

          if (expected && typeof expected === "object") {
            // Expected is an object with value and/or disabled
            match = state.exists;
            if (match && "value" in expected) {
              match = match && state.value === expected.value;
            }
            if (match && "disabled" in expected) {
              match = match && state.disabled === expected.disabled;
            }
          } else {
            // Expected is just a value
            match = state.exists && state.value === expected;
          }

          stepResult.verify.push({
            id,
            expected,
            actual: state,
            match,
          });

          if (!match) allSuccess = false;
        }
      }

      stepResults.push(stepResult);
    }

    const result = {
      success: allSuccess,
      steps: stepResults,
    };

    console.log(JSON.stringify(result, null, 2));
  } catch (e) {
    console.error(`Error: ${e.message}`);
    console.error(e.stack);
    process.exit(1);
  }
}

main();
