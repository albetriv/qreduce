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

  /**
   * Extract parameter description from HTML comment preceding a field.
   * Looks for pattern: <!-- PARAM_DESC: description text -->
   * @param {HTMLElement} fieldElement - The .field element
   * @returns {string|null} - The description text or null if not found
   */
  function extractParamDescription(fieldElement) {
    if (!fieldElement) return null;

    // Walk through sibling nodes before the field to find comment
    var node = fieldElement.previousSibling;
    while (node) {
      if (node.nodeType === Node.COMMENT_NODE) {
        var text = node.nodeValue.trim();
        if (text.startsWith("PARAM_DESC:")) {
          return text.substring("PARAM_DESC:".length).trim();
        }
      }
      // Stop if we hit another element (not whitespace text node)
      if (node.nodeType === Node.ELEMENT_NODE) break;
      node = node.previousSibling;
    }
    return null;
  }

  /**
   * Extract parameter description for a switch-row from HTML comment.
   * @param {HTMLElement} switchRow - The .switch-row element
   * @returns {string|null}
   */
  function extractSwitchDescription(switchRow) {
    if (!switchRow) return null;

    var node = switchRow.previousSibling;
    while (node) {
      if (node.nodeType === Node.COMMENT_NODE) {
        var text = node.nodeValue.trim();
        if (text.startsWith("PARAM_DESC:")) {
          return text.substring("PARAM_DESC:".length).trim();
        }
      }
      if (node.nodeType === Node.ELEMENT_NODE) break;
      node = node.previousSibling;
    }
    return null;
  }

  // Tooltip state management
  // - activeTooltip: currently visible tooltip element
  // - pinnedTooltip: tooltip that was explicitly clicked (persists until clicked again or Escape)
  var activeTooltip = null;
  var pinnedTooltip = null;

  /**
   * Close the currently active tooltip.
   * @param {boolean} clearPin - Whether to also clear the pinned state
   */
  function closeActiveTooltip(clearPin) {
    if (activeTooltip) {
      activeTooltip.classList.remove("tooltip-active");
      activeTooltip = null;
    }
    if (clearPin) {
      pinnedTooltip = null;
    }
  }

  /**
   * Open a tooltip (closes any other open tooltip).
   * @param {HTMLElement} tooltipEl - The .tooltip element to open
   * @param {boolean} pin - Whether this is a pinned (clicked) open
   */
  function openTooltip(tooltipEl, pin) {
    if (activeTooltip === tooltipEl) {
      // Already open, just update pin state if needed
      if (pin) pinnedTooltip = tooltipEl;
      return;
    }
    // Close previous tooltip (clear pin only if opening a new pinned one)
    closeActiveTooltip(pin);
    tooltipEl.classList.add("tooltip-active");
    activeTooltip = tooltipEl;
    if (pin) {
      pinnedTooltip = tooltipEl;
    }
  }

  /**
   * Handle click on tooltip button.
   * If tooltip is pinned, unpin and close. Otherwise, pin it open.
   * @param {HTMLElement} tooltipEl - The .tooltip element
   */
  function handleTooltipClick(tooltipEl) {
    if (pinnedTooltip === tooltipEl) {
      // Already pinned, unpin and close
      closeActiveTooltip(true);
    } else {
      // Pin this tooltip open
      openTooltip(tooltipEl, true);
    }
  }

  /**
   * Handle hover/focus open (temporary, not pinned).
   * @param {HTMLElement} tooltipEl - The .tooltip element
   * @param {HTMLElement} wrapper - The wrapper element for positioning
   */
  function handleTooltipHoverFocus(tooltipEl, wrapper) {
    // Don't override a pinned tooltip from another field
    if (pinnedTooltip && pinnedTooltip !== tooltipEl) {
      return;
    }
    openTooltip(tooltipEl, false);
    adjustTooltipPosition(wrapper);
  }

  /**
   * Handle hover/focus leave (close if not pinned).
   * @param {HTMLElement} tooltipEl - The .tooltip element
   * @param {HTMLElement} wrapper - The wrapper element
   * @param {HTMLElement} button - The button element
   */
  function handleTooltipLeave(tooltipEl, wrapper, button) {
    // Don't close if this tooltip is pinned
    if (pinnedTooltip === tooltipEl) {
      return;
    }
    // Don't close if still hovering or focused
    if (wrapper.matches(":hover") || document.activeElement === button) {
      return;
    }
    if (activeTooltip === tooltipEl) {
      closeActiveTooltip(false);
    }
  }

  /**
   * Get parameter name from label text for accessible naming.
   * @param {HTMLElement} labelOrContext - The label element or switch-row context
   * @returns {string}
   */
  function getParamName(labelOrContext) {
    if (!labelOrContext) return "parametro";

    // For labels, get text before the .param span
    var text = "";
    var childNodes = labelOrContext.childNodes;
    for (var i = 0; i < childNodes.length; i++) {
      var child = childNodes[i];
      if (child.nodeType === Node.TEXT_NODE) {
        text += child.textContent;
      } else if (child.nodeType === Node.ELEMENT_NODE) {
        // Stop at .param or .tooltip-wrapper
        if (child.classList && (child.classList.contains("param") || child.classList.contains("tooltip-wrapper"))) {
          break;
        }
        text += child.textContent || "";
      }
    }
    text = text.trim();
    return text || "parametro";
  }

  /**
   * Get parameter name from switch-row context.
   * @param {HTMLElement} switchRow
   * @returns {string}
   */
  function getSwitchParamName(switchRow) {
    var strong = switchRow.querySelector("strong");
    if (strong) {
      return strong.textContent.trim() || "opzione";
    }
    return "opzione";
  }

  /**
   * Generate unique ID for tooltip.
   * @param {string} fieldId
   * @returns {string}
   */
  function generateTooltipId(fieldId) {
    return "tooltip-" + fieldId;
  }

  /**
   * Create tooltip button and tooltip content as sibling elements.
   * Returns an object with { button, tooltip } to be inserted separately.
   * @param {string} description - The tooltip text
   * @param {string} fieldId - The associated field ID for ARIA
   * @param {string} paramName - Human-readable parameter name
   * @returns {{button: HTMLElement, tooltip: HTMLElement, wrapper: HTMLElement}}
   */
  function createTooltipElements(description, fieldId, paramName) {
    // Wrapper for positioning context
    var wrapper = document.createElement("span");
    wrapper.className = "tooltip-wrapper";

    // Use native button for accessibility
    var button = document.createElement("button");
    button.type = "button";
    button.className = "info-icon";
    button.setAttribute("aria-label", "Informazioni su " + paramName);
    button.setAttribute("aria-expanded", "false");
    button.textContent = "i";

    var tooltipId = generateTooltipId(fieldId);
    var tooltip = document.createElement("span");
    tooltip.className = "tooltip";
    tooltip.id = tooltipId;
    tooltip.setAttribute("role", "tooltip");
    tooltip.textContent = description;

    // Link button to tooltip
    button.setAttribute("aria-describedby", tooltipId);

    wrapper.appendChild(button);
    wrapper.appendChild(tooltip);

    // Click pins/unpins tooltip
    button.addEventListener("click", function (e) {
      e.preventDefault();
      e.stopPropagation();
      handleTooltipClick(tooltip);
      button.setAttribute("aria-expanded", pinnedTooltip === tooltip ? "true" : "false");
    });

    // Enter and Space activate button
    button.addEventListener("keydown", function (e) {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        handleTooltipClick(tooltip);
        button.setAttribute("aria-expanded", pinnedTooltip === tooltip ? "true" : "false");
      }
    });

    // Hover opens tooltip (temporary)
    wrapper.addEventListener("mouseenter", function () {
      handleTooltipHoverFocus(tooltip, wrapper);
    });

    // Mouse leave closes if not pinned
    wrapper.addEventListener("mouseleave", function () {
      setTimeout(function () {
        handleTooltipLeave(tooltip, wrapper, button);
      }, 50);
    });

    // Focus opens tooltip (temporary)
    button.addEventListener("focus", function () {
      handleTooltipHoverFocus(tooltip, wrapper);
    });

    // Blur closes if not pinned
    button.addEventListener("blur", function () {
      setTimeout(function () {
        handleTooltipLeave(tooltip, wrapper, button);
      }, 100);
    });

    return { button: button, tooltip: tooltip, wrapper: wrapper };
  }

  // Keep old function name for compatibility
  function createTooltipElement(description, fieldId, paramName) {
    return createTooltipElements(description, fieldId, paramName).wrapper;
  }

  /**
   * Adjust tooltip position using fixed positioning to escape overflow:hidden.
   * @param {HTMLElement} wrapper - The tooltip wrapper element
   */
  function adjustTooltipPosition(wrapper) {
    var tooltip = wrapper.querySelector(".tooltip");
    if (!tooltip) return;

    // Reset positioning
    tooltip.classList.remove("tooltip-left", "tooltip-right", "tooltip-below");
    tooltip.style.position = "";
    tooltip.style.top = "";
    tooltip.style.left = "";
    tooltip.style.bottom = "";
    tooltip.style.transform = "";

    var adjustFn = function () {
      var wrapperRect = wrapper.getBoundingClientRect();
      var viewportWidth = window.innerWidth;
      var viewportHeight = window.innerHeight;

      // Measure tooltip
      var originalDisplay = tooltip.style.display;
      var originalVisibility = tooltip.style.visibility;
      tooltip.style.visibility = "hidden";
      tooltip.style.display = "block";
      tooltip.style.position = "fixed";

      var tooltipRect = tooltip.getBoundingClientRect();
      var tooltipWidth = tooltipRect.width;
      var tooltipHeight = tooltipRect.height;

      // Calculate ideal position (above the button, centered)
      var idealTop = wrapperRect.top - tooltipHeight - 8;
      var idealLeft = wrapperRect.left + wrapperRect.width / 2 - tooltipWidth / 2;

      // Check if it fits above
      var showBelow = idealTop < 10;
      if (showBelow) {
        idealTop = wrapperRect.bottom + 8;
        tooltip.classList.add("tooltip-below");
      }

      // Check horizontal bounds
      if (idealLeft < 10) {
        idealLeft = 10;
        tooltip.classList.add("tooltip-right");
      } else if (idealLeft + tooltipWidth > viewportWidth - 10) {
        idealLeft = viewportWidth - tooltipWidth - 10;
        tooltip.classList.add("tooltip-left");
      }

      // Check if it would overflow bottom when shown below
      if (showBelow && idealTop + tooltipHeight > viewportHeight - 10) {
        // Not enough space below either, show above anyway
        idealTop = Math.max(10, wrapperRect.top - tooltipHeight - 8);
        tooltip.classList.remove("tooltip-below");
      }

      // Apply fixed positioning
      tooltip.style.position = "fixed";
      tooltip.style.top = idealTop + "px";
      tooltip.style.left = idealLeft + "px";
      tooltip.style.bottom = "auto";
      tooltip.style.transform = "none";

      // Restore visibility
      tooltip.style.display = originalDisplay;
      tooltip.style.visibility = originalVisibility;
    };

    if (typeof requestAnimationFrame === "function") {
      requestAnimationFrame(adjustFn);
    } else {
      adjustFn();
    }
  }

  /**
   * Initialize tooltips for all fields with PARAM_DESC comments.
   * Call this on DOMContentLoaded.
   */
  function initTooltips() {
    // Global Escape key handler
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && activeTooltip) {
        closeActiveTooltip(true);
        // Update aria-expanded on all buttons
        document.querySelectorAll(".info-icon").forEach(function (btn) {
          btn.setAttribute("aria-expanded", "false");
        });
      }
    });

    // Global click handler to close tooltip when clicking outside
    document.addEventListener("click", function (e) {
      if (activeTooltip && !e.target.closest(".tooltip-wrapper")) {
        closeActiveTooltip(true);
        document.querySelectorAll(".info-icon").forEach(function (btn) {
          btn.setAttribute("aria-expanded", "false");
        });
      }
    });

    // Process regular fields
    var fields = document.querySelectorAll(".field");
    fields.forEach(function (field) {
      var description = extractParamDescription(field);
      if (!description) return;

      var label = field.querySelector("label");
      if (!label) return;

      // Check if tooltip already exists
      if (field.querySelector(".tooltip-wrapper")) return;

      // Get field ID and parameter name
      var input = field.querySelector("input, select, textarea");
      var fieldId = input ? input.id : "field-" + Math.random().toString(36).substr(2, 9);
      var paramName = getParamName(label);

      var elements = createTooltipElements(description, fieldId, paramName);

      // Insert wrapper as sibling after label, not inside it
      label.parentNode.insertBefore(elements.wrapper, label.nextSibling);
    });

    // Process switch-row elements (checkboxes with switch styling)
    var switchRows = document.querySelectorAll(".switch-row");
    switchRows.forEach(function (switchRow) {
      var description = extractSwitchDescription(switchRow);
      if (!description) return;

      // Check if tooltip already exists
      if (switchRow.querySelector(".tooltip-wrapper")) return;

      // Get field ID from checkbox
      var checkbox = switchRow.querySelector('input[type="checkbox"]');
      var fieldId = checkbox ? checkbox.id : "switch-" + Math.random().toString(36).substr(2, 9);
      var paramName = getSwitchParamName(switchRow);

      var elements = createTooltipElements(description, fieldId, paramName);
      switchRow.appendChild(elements.wrapper);
    });
  }

  /** Initialize per-configurator favorites without requiring a server. */
  function setupFavorites(family, updateCallback) {
    var form = $("configForm");
    var host = document.querySelector("aside.summary");
    if (!form || !host || $("favoritesPanel")) return;
    var key = "qreduce.uix.favorites.v1." + family;
    var storage = null;
    var blocked = false;
    var entries = [];
    var panel = document.createElement("section");
    panel.id = "favoritesPanel";
    panel.className = "favorites";
    panel.setAttribute("aria-labelledby", "favoritesTitle");
    panel.innerHTML = '<h3 id="favoritesTitle">Comandi preferiti</h3>' +
      '<p id="favoritesStorage" class="help" role="status"></p>' +
      '<label for="favoriteName">Nome del preferito</label>' +
      '<input id="favoriteName" maxlength="160" autocomplete="off">' +
      '<div class="actions"><button type="button" class="button primary" id="saveFavorite">Salva</button></div>' +
      '<label for="favoritesList">Preferiti salvati (ordine alfabetico)</label>' +
      '<select id="favoritesList" size="5"></select>' +
      '<div class="actions"><button type="button" class="button ghost" id="loadFavorite">Carica</button>' +
      '<button type="button" class="button ghost" id="deleteFavorite">Cancella</button></div>' +
      '<div class="actions"><button type="button" class="button ghost" id="exportFavorites">Esporta JSON</button>' +
      '<button type="button" class="button ghost" id="importFavorites">Importa JSON</button></div>' +
      '<input id="favoritesFile" type="file" accept=".json,application/json" hidden>' +
      '<p id="favoritesMessage" class="help" role="status" aria-live="polite"></p>';
    host.appendChild(panel);
    var nameInput = $("favoriteName");
    var list = $("favoritesList");
    var fields = Array.from(form.querySelectorAll("input[id], select[id], textarea[id]"));
    var fieldMap = new Map(fields.map(function (field) { return [field.id, field]; }));
    nameInput.value = value("runId");

    function message(text) { $("favoritesMessage").textContent = text; }
    function storageStatus(text) { $("favoritesStorage").textContent = text; }
    function normalized(name) { return name.trim().toLocaleLowerCase("it"); }
    function envelope(items) {
      return { application: "qreduce-uix-favorites", version: 1, family: family,
        entries: items.slice().sort(function (a, b) { return a.name.localeCompare(b.name, "it", { sensitivity: "base", numeric: true }); }).map(function (item) {
          var values = Object.create(null);
          Object.keys(item.fields).sort().forEach(function (id) { values[id] = item.fields[id]; });
          return { name: item.name, format: item.format, command: item.command, fields: values };
        }) };
    }
    function validateArchive(data) {
      if (!data || data.application !== "qreduce-uix-favorites" || data.version !== 1 ||
          data.family !== family || !Array.isArray(data.entries) || data.entries.length > 1000) {
        throw new Error("Formato, versione o configuratore incompatibile.");
      }
      var names = new Set();
      return data.entries.map(function (item) {
        if (!item || typeof item.name !== "string" || !item.name.trim() || item.name.length > 160 ||
            !["inline", "multiline"].includes(item.format) || typeof item.command !== "string" ||
            !item.fields || typeof item.fields !== "object" || Array.isArray(item.fields)) {
          throw new Error("Preferito non valido.");
        }
        if (names.has(normalized(item.name))) throw new Error("Nomi duplicati nell'archivio.");
        names.add(normalized(item.name));
        // Exact field sets prevent silently loading obsolete configurations.
        if (Object.keys(item.fields).length !== fields.length) {
          throw new Error("Campi incompatibili con questa versione del configuratore.");
        }
        fields.forEach(function (field) {
          if (!Object.prototype.hasOwnProperty.call(item.fields, field.id)) {
            throw new Error("Campo mancante: " + field.id);
          }
          var saved = item.fields[field.id];
          if (typeof saved !== (field.type === "checkbox" ? "boolean" : "string") ||
              (field.tagName === "SELECT" && !Array.from(field.options).some(function (o) { return o.value === saved; })) ||
              (field.readOnly && saved !== field.value)) {
            throw new Error("Valore incompatibile: " + field.id);
          }
        });
        return { name: item.name.trim(), format: item.format, command: item.command, fields: item.fields };
      });
    }
    function refresh() {
      var selected = list.value;
      entries.sort(function (a, b) {
        return a.name.localeCompare(b.name, "it", { sensitivity: "base", numeric: true });
      });
      list.replaceChildren();
      entries.forEach(function (entry) {
        var option = document.createElement("option");
        option.value = entry.name;
        option.textContent = entry.name;
        list.appendChild(option);
      });
      if (!entries.length) {
        var empty = document.createElement("option");
        empty.textContent = "Nessun preferito salvato";
        empty.disabled = true;
        list.appendChild(empty);
      }
      list.value = selected;
      selectionChanged();
      $("exportFavorites").disabled = entries.length === 0;
      syncSave();
    }
    function selectionChanged() {
      var selected = entries.some(function (entry) { return entry.name === list.value; });
      $("loadFavorite").disabled = !selected;
      $("deleteFavorite").disabled = !selected;
    }
    function syncSave() {
      $("saveFavorite").disabled = blocked || !nameInput.value.trim() || nameInput.value.length > 160 || $("copyCommand").disabled;
    }
    function commit(next, notice) {
      if (blocked) return;
      if (next.length > 1000) { message("Limite di 1000 preferiti."); return; }
      var serialized = JSON.stringify(envelope(next));
      if (new Blob([serialized]).size > 5 * 1024 * 1024) {
        message("Modifica rifiutata: archivio oltre 5 MiB. Esporta i preferiti esistenti prima di ridurne il numero.");
        return;
      }
      // Re-read before writing: never silently overwrite another window's edits.
      if (storage) {
        try {
          var raw = storage.getItem(key);
          var current = raw === null ? [] : validateArchive(JSON.parse(raw));
          if (JSON.stringify(envelope(current)) !== JSON.stringify(envelope(entries))) {
            message("Archivio modificato in un'altra finestra. Riapri la pagina prima di salvare.");
            return;
          }
          storage.setItem(key, serialized);
        } catch (error) {
          storage = null;
          storageStatus("Scrittura non riuscita: modifiche solo in memoria. Esporta prima di chiudere o ricaricare.");
        }
      }
      entries = next;
      refresh();
      message(notice + (storage ? "" : " Solo in memoria: esporta per conservarli."));
    }
    var readableStorage = null;
    try {
      storage = window.localStorage;
      readableStorage = storage;
      var probe = key + ".probe." + Date.now() + Math.random();
      try {
        storage.setItem(probe, "ok");
        if (storage.getItem(probe) !== "ok") throw new Error("Storage non disponibile");
      } finally {
        storage.removeItem(probe);
      }
      storageStatus("Archivio locale del browser, non sincronizzato. Con file:// verifica la persistenza dopo la riapertura; esporta una copia di sicurezza.");
    } catch (error) {
      storage = null;
      storageStatus("Storage non disponibile: preferiti solo in memoria fino alla chiusura o al ricaricamento. Usa Esporta JSON.");
    }
    if (readableStorage) {
      try {
        var raw = readableStorage.getItem(key);
        if (raw !== null) entries = validateArchive(JSON.parse(raw));
      } catch (error) {
        blocked = true;
        storageStatus("Archivio illeggibile o incompatibile: nessun dato sovrascritto. " + error.message);
        $("importFavorites").disabled = true;
      }
    }
    nameInput.addEventListener("input", syncSave);
    form.addEventListener("input", syncSave);
    form.addEventListener("change", syncSave);
    // Validation can also change after reset or a programmatic update.
    var observer = new MutationObserver(syncSave);
    observer.observe($("copyCommand"), { attributes: true, attributeFilter: ["disabled"] });
    list.addEventListener("change", function () {
      selectionChanged();
      if (list.value) nameInput.value = list.value;
      syncSave();
    });
    $("saveFavorite").addEventListener("click", function () {
      updateCallback();
      syncSave();
      if ($("saveFavorite").disabled) return;
      var name = nameInput.value.trim();
      var existing = entries.find(function (item) { return normalized(item.name) === normalized(name); });
      if (existing && !window.confirm('Sovrascrivere il preferito "' + existing.name + '"?')) return;
      var values = Object.create(null);
      fields.forEach(function (field) { values[field.id] = field.type === "checkbox" ? field.checked : field.value; });
      var next = entries.filter(function (item) { return item !== existing; });
      next.push({ name: name, fields: values, format: getFormat(), command: $("cliPreview").textContent });
      commit(next, "Preferito salvato.");
    });
    $("loadFavorite").addEventListener("click", function () {
      var entry = entries.find(function (item) { return item.name === list.value; });
      if (!entry) return;
      validateArchive(envelope([entry]));
      Object.keys(entry.fields).forEach(function (id) {
        var field = fieldMap.get(id);
        if (field.type === "checkbox") field.checked = entry.fields[id];
        else field.value = entry.fields[id];
      });
      document.querySelectorAll(".format-selector button").forEach(function (button) {
        button.classList.toggle("active", button.dataset.format === entry.format);
      });
      updateCallback();
      syncSave();
      message("Configurazione caricata e comando rigenerato. Nessun comando eseguito.");
    });
    $("deleteFavorite").addEventListener("click", function () {
      var selected = list.value;
      if (!selected || !window.confirm('Cancellare il preferito "' + selected + '"?')) return;
      commit(entries.filter(function (entry) { return entry.name !== selected; }), "Preferito cancellato.");
    });
    $("exportFavorites").addEventListener("click", function () {
      var url = null;
      var link = document.createElement("a");
      try {
        var blob = new Blob([JSON.stringify(envelope(entries))], { type: "application/json" });
        url = URL.createObjectURL(blob);
        link.href = url;
        link.download = "qreduce-favorites-" + family + ".json";
        document.body.appendChild(link);
        link.click();
        message("Download richiesto. Conserva il JSON fuori dal workspace; puo contenere percorsi locali.");
      } catch (error) {
        message("Esportazione non riuscita: " + error.message);
      } finally {
        link.remove();
        if (url) setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
      }
    });
    $("importFavorites").addEventListener("click", function () { $("favoritesFile").click(); });
    $("favoritesFile").addEventListener("change", function () {
      var input = this;
      var file = input.files[0];
      if (!file || blocked) return;
      if (file.size > 5 * 1024 * 1024) {
        message("Importazione rifiutata: limite di 5 MiB.");
        input.value = "";
        return;
      }
      var reader = new FileReader();
      reader.onload = function () {
        try {
          var imported = validateArchive(JSON.parse(reader.result));
          var next = entries.slice();
          imported.forEach(function (entry) {
            var base = entry.name;
            var suffix = 2;
            while (next.some(function (item) { return normalized(item.name) === normalized(entry.name); })) {
              entry.name = base.slice(0, 145) + " (" + suffix++ + ")";
            }
            next.push(entry);
          });
          if (next.length > 1000) throw new Error("Limite di 1000 preferiti.");
          commit(next, "Importati " + imported.length + " preferiti.");
        } catch (error) {
          message("Importazione rifiutata: " + error.message);
        }
        input.value = "";
      };
      reader.onerror = function () { message("Impossibile leggere il file."); input.value = ""; };
      reader.readAsText(file);
    });
    refresh();
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
    setupFavorites: setupFavorites,
    setButtonsEnabled: setButtonsEnabled,
    extractParamDescription: extractParamDescription,
    extractSwitchDescription: extractSwitchDescription,
    createTooltipElement: createTooltipElement,
    initTooltips: initTooltips,
    closeActiveTooltip: closeActiveTooltip,
  };
})();
