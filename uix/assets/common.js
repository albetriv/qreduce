/**
 * QReduce Experiment Configurators - Shared Utilities
 *
 * Common functions for command composition, quoting, validation, and UI.
 * Works in file:// context without fetch or ES modules.
 */

// eslint-disable-next-line no-unused-vars
var QReduceCommon = (function () {
  "use strict";

  let toastTimer = null;

  /**
   * Get element by ID.
   * @param {string} id
   * @returns {HTMLElement|null}
   */
  function $(id) {
    return document.getElementById(id);
  }

  /**
   * Get trimmed value of an input element.
   * @param {string} id
   * @returns {string}
   */
  function value(id) {
    const el = $(id);
    if (!el) return "";
    // Handle select elements specially - value might be undefined in some DOM implementations
    if (el.tagName === "SELECT") {
      const val = el.value;
      if (val !== undefined && val !== null && val !== "") {
        return typeof val === "string" ? val.trim() : String(val);
      }
      // Fallback: get value from selected option or first option
      const selectedOption = el.querySelector("option[selected]") || el.querySelector("option");
      if (selectedOption) {
        const optVal = selectedOption.value || selectedOption.getAttribute("value") || selectedOption.textContent;
        return typeof optVal === "string" ? optVal.trim() : "";
      }
      return "";
    }
    const val = el.value;
    return typeof val === "string" ? val.trim() : "";
  }

  /**
   * Parse numeric value or return null if empty.
   * @param {string} id
   * @returns {number|null}
   */
  function number(id) {
    const v = value(id);
    return v === "" ? null : Number(v);
  }

  /**
   * Get checkbox state.
   * @param {string} id
   * @returns {boolean}
   */
  function bool(id) {
    const el = $(id);
    return el ? el.checked : false;
  }

  /**
   * Quote a value for Bash/Zsh if it contains special characters.
   * Handles spaces, quotes, and shell metacharacters.
   * @param {string} text
   * @returns {string}
   */
  function quote(text) {
    if (text === "") {
      return '""';
    }
    // Characters that require quoting in bash
    if (/[\s"'`$\\!*?#~<>|;&(){}[\]]/.test(text)) {
      // Use single quotes, escaping any existing single quotes
      return "'" + text.replace(/'/g, "'\\''") + "'";
    }
    return text;
  }

  /**
   * Set error message for a field.
   * @param {string} id - Field ID
   * @param {string} message - Error message (empty to clear)
   */
  function setError(id, message) {
    const el = $(id);
    if (!el) return;
    const host = el.closest(".field");
    if (host) {
      const errorEl = host.querySelector(".error");
      if (errorEl) errorEl.textContent = message || "";
    }
  }

  /**
   * Clear all error messages in a form.
   * @param {HTMLFormElement} form
   */
  function clearErrors(form) {
    form.querySelectorAll(".field .error").forEach(function (item) {
      item.textContent = "";
    });
  }

  /**
   * Show a toast notification.
   * @param {string} message
   * @param {number} duration - Duration in ms (default 2300)
   */
  function toast(message, duration) {
    duration = duration || 2300;
    const item = $("toast");
    if (!item) return;
    item.textContent = message;
    item.classList.add("show");
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(function () {
      item.classList.remove("show");
    }, duration);
  }

  /**
   * Copy text to clipboard with fallback message.
   * @param {string} text
   * @param {string} successMessage
   */
  function copy(text, successMessage) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard
        .writeText(text)
        .then(function () {
          toast(successMessage);
        })
        .catch(function () {
          toast("Copia non disponibile: seleziona il testo manualmente.");
        });
    } else {
      toast("Copia non disponibile: seleziona il testo manualmente.");
    }
  }

  /**
   * Build a command string from base and arguments.
   * @param {string} base - Base command (e.g., "poetry run python -m ...")
   * @param {Array<{flag: string, value: string|number|boolean|null, isFlag?: boolean}>} args
   * @param {string} format - "inline" or "multiline"
   * @returns {string}
   */
  function buildCommand(base, args, format) {
    const parts = [];

    for (var i = 0; i < args.length; i++) {
      var arg = args[i];
      if (arg.value === null || arg.value === undefined) continue;
      if (arg.value === false) continue;

      if (arg.isFlag && arg.value === true) {
        // Boolean flag without value
        parts.push(arg.flag);
      } else if (arg.isPositional) {
        // Positional argument (no flag)
        parts.push(quote(String(arg.value)));
      } else if (arg.value !== true) {
        // Flag with value
        parts.push(arg.flag + " " + quote(String(arg.value)));
      }
    }

    if (format === "multiline" && parts.length > 0) {
      return base + " \\\n  " + parts.join(" \\\n  ");
    }
    return base + (parts.length > 0 ? " " + parts.join(" ") : "");
  }

  /**
   * Update validation badge styling.
   * @param {boolean} isValid
   */
  function updateValidationBadge(isValid) {
    const badge = $("validationBadge");
    if (!badge) return;
    badge.textContent = isValid ? "Configurazione valida" : "Correggi i campi evidenziati";
    badge.style.color = isValid ? "#a3f4e1" : "#ffb0ba";
    badge.style.background = isValid ? "#0a2b38" : "#3b1721";
    badge.style.borderColor = isValid ? "#29516a" : "#853444";
  }

  /**
   * Update validation status box.
   * @param {boolean} isValid
   */
  function updateValidationStatus(isValid) {
    const validationStatus = $("validationStatus");
    if (!validationStatus) return;

    validationStatus.classList.toggle("invalid", !isValid);

    const icon = $("validationIcon");
    const title = $("validationTitle");
    const text = $("validationText");

    if (icon) icon.textContent = isValid ? "✓" : "!";
    if (title) title.textContent = isValid ? "Configurazione verificata" : "Configurazione da correggere";
    if (text)
      text.textContent = isValid
        ? "Puoi copiare il comando CLI."
        : "Correggi i messaggi in rosso prima di copiare.";
  }

  /**
   * Setup tab navigation.
   */
  function setupTabs() {
    const tabButtons = document.querySelectorAll(".tab");
    tabButtons.forEach(function (button) {
      button.addEventListener("click", function () {
        tabButtons.forEach(function (tab) {
          tab.classList.toggle("active", tab === button);
        });
        document.querySelectorAll(".tab-content").forEach(function (content) {
          content.classList.toggle("active", content.id === button.dataset.tab);
        });
      });
    });
  }

  /**
   * Setup format selector (inline/multiline).
   * @param {function} updateCallback - Function to call when format changes
   */
  function setupFormatSelector(updateCallback) {
    const buttons = document.querySelectorAll(".format-selector button");
    buttons.forEach(function (button) {
      button.addEventListener("click", function () {
        buttons.forEach(function (btn) {
          btn.classList.toggle("active", btn === button);
        });
        if (updateCallback) updateCallback();
      });
    });
  }

  /**
   * Get current format selection.
   * @returns {string} "inline" or "multiline"
   */
  function getFormat() {
    const active = document.querySelector(".format-selector button.active");
    return active ? active.dataset.format : "inline";
  }

  /**
   * Enable/disable buttons based on validation state.
   * @param {boolean} isValid
   * @param {string[]} buttonIds - IDs of buttons to control
   */
  function setButtonsEnabled(isValid, buttonIds) {
    buttonIds.forEach(function (id) {
      const btn = $(id);
      if (btn) btn.disabled = !isValid;
    });
  }

  // Public API
  return {
    $: $,
    value: value,
    number: number,
    bool: bool,
    quote: quote,
    setError: setError,
    clearErrors: clearErrors,
    toast: toast,
    copy: copy,
    buildCommand: buildCommand,
    updateValidationBadge: updateValidationBadge,
    updateValidationStatus: updateValidationStatus,
    setupTabs: setupTabs,
    setupFormatSelector: setupFormatSelector,
    getFormat: getFormat,
    setButtonsEnabled: setButtonsEnabled,
  };
})();
