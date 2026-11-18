#!/usr/bin/env node
/**
 * Test runner for UIX JavaScript command generators.
 *
 * Usage: node tests/uix_js_runner.js <configurator> <json_input>
 *
 * Where:
 *   configurator: "portfolio" or "facility_location"
 *   json_input: JSON object with field values to set
 *
 * Output: JSON object with { command, isValid, errors }
 */

const { JSDOM } = require("jsdom");
const fs = require("fs");
const path = require("path");

function main() {
  const args = process.argv.slice(2);
  if (args.length < 2) {
    console.error("Usage: node uix_js_runner.js <configurator> <json_input>");
    console.error('  configurator: "portfolio" or "facility_location"');
    console.error("  json_input: JSON object with field values");
    process.exit(1);
  }

  const configurator = args[0];
  const jsonInput = args[1];

  if (!["portfolio", "facility_location"].includes(configurator)) {
    console.error(`Invalid configurator: ${configurator}`);
    process.exit(1);
  }

  let fieldValues;
  try {
    fieldValues = JSON.parse(jsonInput);
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

    // Create DOM without running scripts
    const dom = new JSDOM(htmlContent, {
      url: "file://" + htmlPath,
      runScripts: "outside-only",
    });

    const { window } = dom;
    const { document } = window;

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
        ? fs.readFileSync(path.join(uixDir, "assets", "portfolio.js"), "utf8")
        : fs.readFileSync(path.join(uixDir, "assets", "facility_location.js"), "utf8");
    window.eval(specificJs);

    // Trigger DOMContentLoaded to initialize the scripts
    const initEvent = new window.Event("DOMContentLoaded");
    document.dispatchEvent(initEvent);

    // Now set field values (after initialization)
    for (const [id, value] of Object.entries(fieldValues)) {
      if (id.startsWith("_")) continue; // Skip meta fields
      const el = document.getElementById(id);
      if (!el) continue;
      if (el.type === "checkbox") {
        el.checked = Boolean(value);
      } else {
        el.value = String(value);
      }
    }

    // Set format if specified
    if (fieldValues._format) {
      const formatButtons = document.querySelectorAll(".format-selector button");
      formatButtons.forEach((btn) => {
        if (btn.dataset) {
          btn.classList.toggle("active", btn.dataset.format === fieldValues._format);
        }
      });
    }

    // Execute reset if requested (click the reset button)
    if (fieldValues._action === "reset") {
      const resetButton = document.getElementById("resetDefaults");
      if (resetButton) {
        resetButton.click();
      }
    }

    // Trigger change event to update validation and preview
    const form = document.getElementById("configForm");
    if (form) {
      form.dispatchEvent(new window.Event("input", { bubbles: true }));
      form.dispatchEvent(new window.Event("change", { bubbles: true }));
    }

    // Collect field values for verification (used by reset tests)
    const currentValues = {};
    ["lowerBound", "upperBound", "minSelectedAssets", "maxSelectedAssets",
     "runId", "assetCount", "generationSeed", "maxRounds", "edgeMode",
     "correlationThreshold", "misSolver", "classicalSolver", "embeddingProfile"].forEach((id) => {
      const el = document.getElementById(id);
      if (el) {
        currentValues[id] = el.type === "checkbox" ? el.checked : el.value;
        // Also capture disabled state for embedding profile
        if (id === "embeddingProfile") {
          currentValues["embeddingProfileDisabled"] = el.disabled;
        }
      }
    });

    // Get validation state
    const errors = {};
    document.querySelectorAll(".field .error").forEach((el) => {
      const text = el.textContent ? el.textContent.trim() : "";
      if (text) {
        const field = el.closest(".field");
        if (field) {
          const input = field.querySelector("input, select, textarea");
          if (input && input.id) {
            errors[input.id] = text;
          }
        }
      }
    });

    const badge = document.getElementById("validationBadge");
    const isValid = badge
      ? badge.textContent.includes("valida") && !badge.textContent.includes("Correggi")
      : Object.keys(errors).length === 0;

    // Get generated command
    const preview = document.getElementById("cliPreview");
    const command = preview ? (preview.textContent || "") : "";

    const result = {
      isValid,
      errors,
      command,
      currentValues,
    };

    console.log(JSON.stringify(result));
  } catch (e) {
    console.error(`Error: ${e.message}`);
    console.error(e.stack);
    process.exit(1);
  }
}

main();
