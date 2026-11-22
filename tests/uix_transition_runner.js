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
 *   configurator: "portfolio", "portfolio_sr", or "facility_location"
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

  if (!["portfolio", "portfolio_sr", "facility_location"].includes(configurator)) {
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
        ? "experiment_portfolio_mv.html"
        : configurator === "portfolio_sr"
        ? "experiment_portfolio_sr.html"
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

    // Load solver_info.js for all configurators
    const solverInfoPath = path.join(uixDir, "assets", "solver_info.js");
    if (fs.existsSync(solverInfoPath)) {
      window.eval(fs.readFileSync(solverInfoPath, "utf8"));
    }

    if (configurator === "portfolio_sr") {
      document.querySelectorAll("script:not([src])").forEach((script) => {
        if (script.textContent.includes("DOMContentLoaded")) {
          window.eval(script.textContent);
        }
      });
    } else {
      const scriptFile = configurator === "portfolio" ? "portfolio_mv.js" : "facility_location.js";
      window.eval(fs.readFileSync(path.join(uixDir, "assets", scriptFile), "utf8"));
    }

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

    // CSS selectors allow assertions about containment as well as unique IDs.
    const rememberedNodes = new Map();
    function findNodes(id) {
      return document.querySelectorAll(id.startsWith("css:") ? id.slice(4) : `[id="${id}"]`);
    }

    function getFieldState(id) {
      const nodes = findNodes(id);
      const el = nodes[0];
      if (!el) return { exists: false, count: 0, visible: false };
      let visible = true;
      for (let ancestor = el; ancestor; ancestor = ancestor.parentElement) {
        const style = window.getComputedStyle(ancestor);
        if (ancestor.hidden || style.display === "none" || style.visibility === "hidden") {
          visible = false;
          break;
        }
      }
      return {
        exists: true,
        count: nodes.length,
        visible,
        text: el.textContent.replace(/\s+/g, " ").trim(),
        attributes: Object.fromEntries(Array.from(el.attributes, attr => [attr.name, attr.value])),
        sameNode: rememberedNodes.has(id) && rememberedNodes.get(id) === el,
        value: el.type === "checkbox" ? el.checked : el.value,
        disabled: el.disabled,
        display: el.style.display,
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

      if (step.action === "reset") {
        document.getElementById("resetDefaults").click();
      }
      if (step.action === "saveFavorite" || step.action === "loadFavorite") {
        document.getElementById(step.action).click();
      }

      // Verify expected values
      if (step.verify) {
        for (const [id, expected] of Object.entries(step.verify)) {
          const state = getFieldState(id);
          let match = false;

          if (expected && typeof expected === "object") {
            match = Object.entries(expected).every(([key, value]) => {
              if (key === "includes" || key === "excludes") {
                const fragments = Array.isArray(value) ? value : [value];
                return state.exists && fragments.every(fragment =>
                  key === "includes" ? state.text.includes(fragment) : !state.text.includes(fragment));
              }
              if (key === "attributes") {
                return state.exists && Object.entries(value).every(([name, attribute]) =>
                  (state.attributes[name] ?? null) === attribute);
              }
              return state[key] === value;
            });
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

      for (const id of step.remember || []) {
        const node = findNodes(id)[0];
        if (!node) throw new Error(`Cannot remember missing node: ${id}`);
        rememberedNodes.set(id, node);
      }

      stepResult.command = document.getElementById("cliPreview").textContent;
      stepResult.copyDisabled = document.getElementById("copyCommand").disabled;
      stepResults.push(stepResult);
    }

    const result = {
      success: allSuccess,
      steps: stepResults,
    };

    console.log(JSON.stringify(result, null, 2));
    dom.window.close();
  } catch (e) {
    console.error(`Error: ${e.message}`);
    console.error(e.stack);
    process.exit(1);
  }
}

main();
