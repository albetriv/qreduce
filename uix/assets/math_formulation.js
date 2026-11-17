/**
 * QReduce Math Formulation Module
 *
 * Shared utilities for rendering mathematical formulations in UIX configurators.
 * Uses MathJax 3 for LaTeX rendering with graceful fallback to plain text.
 *
 * MathJax is loaded from CDN (jsdelivr) with version 3.2.2.
 * When MathJax is unavailable (offline, blocked), formulas are shown as plain text.
 *
 * Key design decisions:
 * - Static TeX (objective, constraints, legend) is preserved in data-tex-source
 * - Dynamic TeX (cardinality, reduction section) is NOT preserved - it's rebuilt by JS
 * - The entire update cycle (clear, update, render) is serialized in the queue
 * - Revision IDs are checked inside the queue to skip stale operations
 */

// eslint-disable-next-line no-unused-vars
var QReduceMath = (function () {
  "use strict";

  // MathJax CDN configuration
  var MATHJAX_VERSION = "3.2.2";
  var MATHJAX_CDN_URL =
    "https://cdn.jsdelivr.net/npm/mathjax@" + MATHJAX_VERSION + "/es5/tex-mml-chtml.js";

  // State
  var mathjaxReady = false;
  var mathjaxFailed = false;
  var mathjaxLoading = false;
  var pendingTypesets = [];

  // Render queue for serialization - ALL DOM operations go through this
  var renderQueue = Promise.resolve();
  var currentRevision = 0;

  // Debounce state
  var renderDebounceTimer = null;
  var RENDER_DEBOUNCE_MS = 150;

  // Track if a render is currently in progress (for testing)
  var renderInProgress = false;

  /**
   * Configure MathJax before loading.
   * Must be called before the script is loaded.
   */
  function configureMathJax() {
    window.MathJax = {
      tex: {
        inlineMath: [["\\(", "\\)"]],
        displayMath: [["\\[", "\\]"]],
        processEscapes: false,
        processEnvironments: true,
      },
      options: {
        skipHtmlTags: ["script", "noscript", "style", "textarea", "pre", "code"],
        ignoreHtmlClass: "mathjax-ignore",
        processHtmlClass: "mathjax-process",
      },
      startup: {
        pageReady: function () {
          mathjaxReady = true;
          mathjaxLoading = false;
          // Process any pending typesets
          processPendingTypesets();
        },
      },
    };
  }

  /**
   * Load MathJax from CDN.
   * @returns {Promise<boolean>} - Resolves to true if loaded, false on failure
   */
  function loadMathJax() {
    if (mathjaxReady) {
      return Promise.resolve(true);
    }
    if (mathjaxFailed) {
      return Promise.resolve(false);
    }
    if (mathjaxLoading) {
      return new Promise(function (resolve) {
        pendingTypesets.push({ resolve: resolve, isLoadCheck: true });
      });
    }

    mathjaxLoading = true;
    configureMathJax();

    return new Promise(function (resolve) {
      var script = document.createElement("script");
      script.src = MATHJAX_CDN_URL;
      script.async = true;
      script.id = "MathJax-script";

      script.onload = function () {
        // MathJax startup will set mathjaxReady and call processPendingTypesets
        // We resolve after a short delay to ensure MathJax has initialized
        var checkReady = function () {
          if (mathjaxReady) {
            resolve(true);
          } else if (mathjaxFailed) {
            resolve(false);
          } else {
            setTimeout(checkReady, 50);
          }
        };
        setTimeout(checkReady, 100);
      };

      script.onerror = function () {
        mathjaxFailed = true;
        mathjaxLoading = false;
        console.warn("QReduceMath: Failed to load MathJax from CDN. Falling back to plain text.");
        // Process pending typesets with fallback
        processPendingTypesets();
        resolve(false);
      };

      document.head.appendChild(script);
    });
  }

  /**
   * Process any pending load checks.
   * Called when MathJax becomes ready (or fails).
   * Resolves all pending waitForMathJaxReady() Promises.
   */
  function processPendingTypesets() {
    var pending = pendingTypesets.slice();
    pendingTypesets = [];

    pending.forEach(function (item) {
      if (item.isLoadCheck && item.resolve) {
        item.resolve(mathjaxReady);
      }
      // Note: element/callback pairs are no longer used since typesetElement
      // no longer queues requests - it either typesets or shows fallback immediately
    });
  }

  /**
   * Save TeX source from STATIC .math-latex elements for later restoration.
   * Call this once during initialization to preserve original content.
   *
   * IMPORTANT: Only call this on static content that doesn't change.
   * Dynamic content (cardinality, reduction section) should NOT be preserved
   * because it gets rebuilt by JS on each update.
   *
   * @param {HTMLElement} container - The container with .math-latex elements
   * @param {string[]} [excludeIds] - IDs of elements to exclude from preservation
   */
  function preserveTexSource(container, excludeIds) {
    if (!container) return;

    var excludeSet = {};
    if (excludeIds) {
      excludeIds.forEach(function (id) {
        excludeSet[id] = true;
      });
    }

    container.querySelectorAll(".math-latex").forEach(function (el) {
      // Skip if already saved
      if (el.hasAttribute("data-tex-source")) return;

      // Skip excluded elements (dynamic content)
      if (el.id && excludeSet[el.id]) return;

      // Skip elements inside excluded containers
      var parent = el.parentElement;
      while (parent && parent !== container) {
        if (parent.id && excludeSet[parent.id]) return;
        parent = parent.parentElement;
      }

      // Save the source
      el.setAttribute("data-tex-source", el.innerHTML);
    });
  }

  /**
   * Restore TeX source from saved data attributes.
   * This undoes MathJax rendering so the element can be re-typeset.
   * Only restores elements that have data-tex-source (static content).
   * @param {HTMLElement} element - A .math-latex element or container
   */
  function restoreTexSource(element) {
    if (!element) return;

    // If this is a .math-latex element with saved source
    if (element.classList && element.classList.contains("math-latex")) {
      var saved = element.getAttribute("data-tex-source");
      if (saved !== null) {
        element.innerHTML = saved;
      }
      return;
    }

    // Otherwise, restore all .math-latex children that have saved source
    element.querySelectorAll(".math-latex[data-tex-source]").forEach(function (el) {
      el.innerHTML = el.getAttribute("data-tex-source");
    });
  }

  /**
   * Clear MathJax rendering from an element.
   * For static content: restores TeX source from data attribute.
   * For dynamic content: just removes MathJax output (JS will rebuild).
   * @param {HTMLElement} element - The element to clear
   */
  function clearTypeset(element) {
    if (!element) return;

    // Clear MathJax's internal state for this element first
    if (window.MathJax && window.MathJax.typesetClear) {
      try {
        window.MathJax.typesetClear([element]);
      } catch (e) {
        // Ignore errors during clear
      }
    }

    // Remove MathJax-generated elements
    element.querySelectorAll(".MathJax, mjx-container").forEach(function (el) {
      el.remove();
    });

    // Restore TeX source for static elements (those with data-tex-source)
    restoreTexSource(element);

    // Reset fallback state
    element.classList.remove("mathjax-failed");
  }

  /**
   * Typeset a specific element using MathJax.
   * Falls back to showing pre-formatted text if MathJax is unavailable.
   * 
   * IMPORTANT: This function assumes MathJax is already ready or failed.
   * It does NOT wait for MathJax to load - callers must ensure MathJax
   * is ready before calling this function to avoid deadlocks.
   * 
   * @param {HTMLElement} element - The element to typeset
   * @returns {Promise<void>}
   */
  function typesetElement(element) {
    if (!element) {
      return Promise.resolve();
    }

    // If MathJax failed or isn't ready, show fallback immediately
    // Do NOT wait for loading - this would cause deadlock in the queue
    if (mathjaxFailed || !mathjaxReady) {
      showFallback(element);
      return Promise.resolve();
    }

    // Use MathJax to typeset
    renderInProgress = true;
    return window.MathJax.typesetPromise([element])
      .catch(function (err) {
        console.warn("QReduceMath: MathJax typeset error:", err);
        showFallback(element);
      })
      .then(function () {
        renderInProgress = false;
      });
  }

  /**
   * Show fallback text representation when MathJax fails.
   * The element should contain both .math-latex (hidden when MathJax works)
   * and .math-fallback (shown when MathJax fails).
   * @param {HTMLElement} element
   */
  function showFallback(element) {
    if (!element) return;
    element.classList.add("mathjax-failed");
    // The CSS will handle showing/hiding the appropriate content
  }

  /**
   * Wait for MathJax to be ready (or fail).
   * @returns {Promise<boolean>} - true if ready, false if failed
   */
  function waitForMathJaxReady() {
    if (mathjaxReady) {
      return Promise.resolve(true);
    }
    if (mathjaxFailed) {
      return Promise.resolve(false);
    }
    // MathJax is still loading - wait for it
    return new Promise(function (resolve) {
      pendingTypesets.push({ resolve: resolve, isLoadCheck: true });
    });
  }

  /**
   * Request a debounced render.
   * The ENTIRE operation (update, clear, typeset) is serialized in the queue.
   * @param {function} updateFn - Function that updates content and returns elements to typeset
   */
  function requestRender(updateFn) {
    // Increment revision immediately (outside debounce)
    var revision = ++currentRevision;

    if (renderDebounceTimer) {
      clearTimeout(renderDebounceTimer);
    }

    renderDebounceTimer = setTimeout(function () {
      renderDebounceTimer = null;

      // Enqueue the ENTIRE operation: check revision, update DOM, clear, typeset
      renderQueue = renderQueue.then(function () {
        // Check revision INSIDE the queue - skip if stale
        if (revision !== currentRevision) {
          return; // A newer render was requested, skip this one
        }

        // Execute the update function to get elements to typeset
        // This happens inside the queue, so no concurrent DOM modifications
        var elements = updateFn();

        // Handle single element or array
        if (!elements) return;
        if (!Array.isArray(elements)) {
          elements = [elements];
        }

        // Clear each element (inside the queue)
        elements.forEach(function (el) {
          if (el) {
            clearTypeset(el);
          }
        });

        // Wait for MathJax to be ready BEFORE typesetting
        // This avoids the deadlock where typesetElement waits for loading
        // while the queue is blocked
        return waitForMathJaxReady().then(function () {
          // Typeset all elements sequentially
          var typesetChain = Promise.resolve();
          elements.forEach(function (el) {
            if (el) {
              typesetChain = typesetChain.then(function () {
                return typesetElement(el);
              });
            }
          });
          return typesetChain;
        });
      });
    }, RENDER_DEBOUNCE_MS);
  }

  /**
   * Initialize MathJax and render initial content.
   * Preserves TeX source for static elements.
   * The initial typeset is serialized through the render queue.
   * @param {HTMLElement} element - The element containing math content
   * @param {string[]} [dynamicIds] - IDs of dynamic elements to exclude from preservation
   * @returns {Promise<void>}
   */
  function initialize(element, dynamicIds) {
    // Preserve original TeX source before first render (excluding dynamic content)
    if (element) {
      preserveTexSource(element, dynamicIds);
    }

    return loadMathJax().then(function () {
      if (element) {
        // Enqueue the initial typeset through the render queue
        // This prevents concurrent rendering with updates that arrive
        // during MathJax initialization
        return new Promise(function (resolve) {
          renderQueue = renderQueue.then(function () {
            return typesetElement(element);
          }).then(resolve);
        });
      }
    });
  }

  /**
   * Check if MathJax is available and ready.
   * @returns {boolean}
   */
  function isReady() {
    return mathjaxReady;
  }

  /**
   * Check if MathJax loading has failed.
   * @returns {boolean}
   */
  function hasFailed() {
    return mathjaxFailed;
  }

  /**
   * Format a number for display in formulas.
   * Preserves the precision of the input value, removing only trailing zeros
   * after the decimal point while keeping all significant digits.
   * @param {number|string} value
   * @returns {string}
   */
  function formatNumber(value) {
    if (value === null || value === undefined || value === "") {
      return "?";
    }

    var str = String(value).trim();

    // Handle special cases
    if (str === "" || str === "NaN" || str === "Infinity" || str === "-Infinity") {
      return "?";
    }

    var num = Number(value);
    if (!Number.isFinite(num)) {
      return "?";
    }

    // Return the original string representation if it's a valid number
    // This preserves user input precision (e.g., "0.001" stays "0.001")
    // Only clean up trailing zeros if there's a decimal point
    if (str.indexOf(".") !== -1) {
      // Remove trailing zeros after decimal, but keep at least one digit after decimal
      // e.g., "1.000" -> "1", "1.100" -> "1.1", "0.001" -> "0.001"
      str = str.replace(/(\.\d*?)0+$/, "$1").replace(/\.$/, "");
    }

    return str;
  }

  /**
   * Escape special LaTeX characters in text.
   * @param {string} text
   * @returns {string}
   */
  function escapeLatex(text) {
    if (!text) return "";
    return text
      .replace(/\\/g, "\\textbackslash{}")
      .replace(/[&%$#_{}]/g, function (c) {
        return "\\" + c;
      })
      .replace(/~/g, "\\textasciitilde{}")
      .replace(/\^/g, "\\textasciicircum{}");
  }

  /**
   * Get the current revision number.
   * Useful for tests to verify render serialization.
   * @returns {number}
   */
  function getRevision() {
    return currentRevision;
  }

  /**
   * Check if a render is currently in progress.
   * @returns {boolean}
   */
  function isRenderInProgress() {
    return renderInProgress;
  }

  // For testing: allow resetting state
  function _resetForTesting() {
    mathjaxReady = false;
    mathjaxFailed = false;
    mathjaxLoading = false;
    pendingTypesets = [];
    renderQueue = Promise.resolve();
    currentRevision = 0;
    renderInProgress = false;
    if (renderDebounceTimer) {
      clearTimeout(renderDebounceTimer);
      renderDebounceTimer = null;
    }
  }

  // For testing: simulate MathJax ready
  function _setReadyForTesting(ready) {
    mathjaxReady = ready;
    mathjaxFailed = !ready;
    mathjaxLoading = false;
    // Process any pending waitForMathJaxReady() calls
    processPendingTypesets();
  }

  // For testing: simulate MathJax loading failure
  function _simulateLoadFailure() {
    mathjaxFailed = true;
    mathjaxLoading = false;
    mathjaxReady = false;
  }

  // For testing: get render queue (to await completion)
  function _getRenderQueue() {
    return renderQueue;
  }

  // For testing: get debounce delay
  function _getDebounceMs() {
    return RENDER_DEBOUNCE_MS;
  }

  // Public API
  return {
    initialize: initialize,
    loadMathJax: loadMathJax,
    typesetElement: typesetElement,
    clearTypeset: clearTypeset,
    requestRender: requestRender,
    preserveTexSource: preserveTexSource,
    restoreTexSource: restoreTexSource,
    isReady: isReady,
    hasFailed: hasFailed,
    formatNumber: formatNumber,
    escapeLatex: escapeLatex,
    getRevision: getRevision,
    isRenderInProgress: isRenderInProgress,
    // Testing utilities (prefixed with underscore)
    _resetForTesting: _resetForTesting,
    _setReadyForTesting: _setReadyForTesting,
    _simulateLoadFailure: _simulateLoadFailure,
    _getRenderQueue: _getRenderQueue,
    _getDebounceMs: _getDebounceMs,
  };
})();
