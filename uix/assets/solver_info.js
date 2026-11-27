/**
 * QReduce Solver Information Panels
 *
 * Provides contextual information and warnings for MIS and classical solver backends.
 * Panels are shown only when the corresponding backend is selected; others are hidden completely.
 *
 * Usage:
 *   QReduceSolverInfo.renderMisPanel(containerId, solverId, options)
 *   QReduceSolverInfo.renderClassicalPanel(containerId, solverId)
 *   QReduceSolverInfo.renderBaselineNotice(containerId)
 *
 * Options for MIS panels:
 *   - embeddingProfile: current embedding selection (for D-Wave)
 *   - reductionActive: whether reduction is enabled
 */

(function () {
  "use strict";

  // Cache by container so unrelated form edits do not mutate live regions.
  var renderedStates = new WeakMap();

  function needsRender(container, state) {
    if (renderedStates.get(container) === state) return false;
    renderedStates.set(container, state);
    container.replaceChildren();
    return true;
  }

  // ============================================================================
  // MIS Backend Descriptions
  // ============================================================================

  // Counts from build_target_topology in qreduce.solving.mwis.dwave_embedding.
  var EMBEDDING_TOPOLOGIES = {
    pegasus_p16: { name: "Pegasus P16", nodes: "5.640", edges: "40.484", maxDegree: 15 },
    zephyr_z12: { name: "Zephyr Z12", nodes: "4.800", edges: "45.864", maxDegree: 20 }
  };

  var MIS_INFO = {
    local_greedy: {
      title: "Local Greedy: informazioni",
      type: "info", // info, warning, error
      items: [
        "Esecuzione locale senza SDK opzionali.",
        "Metodo euristico: i risultati non certificano l'ottimo MWIS.",
        "La qualità della soluzione dipende dal grafo e dalla ricerca euristica."
      ]
    },

    dwave_simulated_annealing: {
      title: "D-Wave Simulated Annealing: informazioni",
      type: "info",
      items: [
        "Campionamento classico locale tramite Ocean SDK.",
        "Non è esecuzione su QPU né simulazione della dinamica quantistica.",
        "Richiede le dipendenze Ocean (<code>dimod</code>, <code>dwave-samplers</code>) del gruppo <code>experiments</code>.",
        "Nessuna garanzia di ottimalità; i campioni sono soluzioni candidate.",
        "Il sampling non supporta un limite temporale rigido. La compilazione usa un budget cooperativo: il tempo può superare la scadenza richiesta."
      ],
      // Additional warnings shown only when embedding profile is selected
      embeddingWarnings: {
        title: "Profilo di embedding attivo",
        type: "warning",
        items: [
          "Il campionamento rispetta vincoli topologici hardware-like.",
          "Le catene di embedding introducono overhead e possono degradare la qualità.",
          "La ricerca può non trovare un embedding entro il budget disponibile; il fallimento non dimostra necessariamente incompatibilità con la topologia.",
          "Richiede <code>dwave-system</code>, <code>dwave-graphs</code> e <code>minorminer</code>, inclusi nel gruppo <code>experiments</code>.",
          "Questo è un profilo locale: non rappresenta accesso a hardware reale."
        ]
      }
    },

    pasqal_local: {
      title: "Pasqal locale: requisiti e limitazioni",
      type: "warning",
      items: [
        "Emulazione locale Pulser/QuTiP; nessun accesso cloud o QPU.",
        "Massimo 12 nodi nel grafo effettivo (limite dell'emulatore, non fisico).",
        "La ricerca del layout può fallire; non implica impossibilità di rappresentazione.",
        "I pesi MWIS sono valutati classicamente; i campioni non certificano ottimalità.",
        "Con riduzione attiva, richiede budget end-to-end esplicitamente 0 (illimitato).",
        "Richiede <code>poetry install --with experiments</code> (include <code>pulser-simulation</code>)."
      ]
    },

    pasqal_cloud_emulator: {
      title: "Pasqal Cloud (EMU_FREE): requisiti e limitazioni",
      type: "warning",
      items: [
        "Esecuzione remota su emulatore Pasqal Cloud (servizio <code>emu_free</code>).",
        "Richiede credenziali Pasqal Cloud configurate nel processo CLI.",
        "Le credenziali vengono lette da <code>~/.pasqual/credentials</code> o dalle variabili d'ambiente.",
        "Qreduce impone un limite di 12 atomi per gli invii remoti.",
        "I pesi MWIS sono valutati classicamente; i campioni non certificano ottimalità.",
        "Il batch_id viene persistito prima del polling per consentire il recupero.",
        "Accetta un budget positivo; la scadenza locale non annulla il batch remoto.",
        "Richiede <code>poetry install --with experiments</code> (include <code>pasqal-cloud</code>)."
      ]
    },

    pasqal_qpu: {
      title: "Pasqal QPU (hardware reale): requisiti e limitazioni",
      type: "warning",
      items: [
        "Un solo round di riduzione; device, shot e consenso ai costi espliciti.",
        "Il preflight CLI compila senza inviare un batch. La discovery non conferma accesso al calcolo o crediti.",
        "Le credenziali restano nel processo CLI. Il browser non esegue il comando."
      ]
    }
  };

  // ============================================================================
  // Classical Backend Descriptions
  // ============================================================================

  var CLASSICAL_INFO = {
    scip: {
      title: "SCIP: informazioni",
      type: "info",
      items: [
        "Solver open-source per MILP e MIQP.",
        "Richiede PySCIPOpt e il runtime SCIP.",
        "Un'interruzione per limite di tempo non equivale a certificazione di ottimalità.",
        "Una soluzione disponibile non implica automaticamente ottimalità del problema originale."
      ]
    },

    cplex: {
      title: "CPLEX: informazioni",
      type: "info",
      items: [
        "Solver commerciale IBM per MILP e MIQP.",
        "Richiede il binding Python (<code>cplex</code>) e un ambiente/licenza utilizzabile.",
        "La presenza del binding non garantisce la disponibilità della licenza.",
        "Un'interruzione per limite di tempo non equivale a certificazione di ottimalità.",
        "Un'ottimalità del problema residuo non certifica quella del problema originale."
      ]
    }
  };

  // ============================================================================
  // Rendering Functions
  // ============================================================================

  /**
   * Create a panel element with the given content.
   * @param {object} info - Panel info object with title, type, items
   * @param {string} [panelId] - Optional ID for the panel element
   * @returns {HTMLElement}
   */
  function createPanel(info, panelId) {
    var panel = document.createElement("div");
    panel.className = "card solver-info-panel solver-info-" + info.type;
    if (panelId) {
      panel.id = panelId;
    }

    var header = document.createElement("h3");
    header.textContent = info.title;
    panel.appendChild(header);

    var list = document.createElement("ul");
    list.className = "solver-info-list";
    info.items.forEach(function (item) {
      var li = document.createElement("li");
      li.innerHTML = item; // Allow HTML for <code> tags
      list.appendChild(li);
    });
    panel.appendChild(list);

    return panel;
  }

  /**
   * Render the MIS backend information panel.
   * Shows only the panel for the selected backend; hides others completely.
   *
   * @param {string} containerId - ID of the container element
   * @param {string} solverId - Selected MIS solver ID
   * @param {object} [options] - Additional options
   * @param {string} [options.embeddingProfile] - Current embedding profile (for D-Wave)
   * @param {boolean} [options.reductionActive] - Whether reduction is active
   */
  function renderMisPanel(containerId, solverId, options) {
    options = options || {};
    var container = document.getElementById(containerId);
    if (!container) return;

    // If reduction is not active, show baseline notice instead
    if (options.reductionActive === false) {
      renderBaselineNotice(containerId);
      return;
    }

    var embedding = solverId === "dwave_simulated_annealing" ? (options.embeddingProfile || "none") : "none";
    if (!needsRender(container, JSON.stringify(["mis", solverId, embedding]))) return;

    var info = MIS_INFO[solverId];
    if (!info) {
      // Unknown solver, show nothing
      return;
    }

    // Create main panel
    var panel = createPanel(info, "misSolverInfoPanel");
    container.appendChild(panel);

    // For D-Wave with a known embedding profile, describe the local target graph.
    if (solverId === "dwave_simulated_annealing" &&
        Object.prototype.hasOwnProperty.call(EMBEDDING_TOPOLOGIES, embedding)) {
      var topology = EMBEDDING_TOPOLOGIES[embedding];
      var warnings = info.embeddingWarnings;
      var embeddingPanel = createPanel({
        title: warnings.title + ": " + topology.name,
        type: warnings.type,
        items: [
          "<strong>Grafo target locale:</strong> " + topology.nodes + " nodi, " +
            topology.edges + " collegamenti, fino a " + topology.maxDegree + " vicini per nodo."
        ].concat(warnings.items)
      }, "embeddingWarningPanel");
      container.appendChild(embeddingPanel);
    }
  }

  /**
   * Render the classical solver information panel.
   * Shows only the panel for the selected backend.
   *
   * @param {string} containerId - ID of the container element
   * @param {string} solverId - Selected classical solver ID
   */
  function renderClassicalPanel(containerId, solverId) {
    var container = document.getElementById(containerId);
    if (!container) return;

    if (!needsRender(container, JSON.stringify(["classical", solverId]))) return;

    var info = CLASSICAL_INFO[solverId];
    if (!info) {
      // Unknown solver, show nothing
      return;
    }

    var panel = createPanel(info, "classicalSolverInfoPanel");
    container.appendChild(panel);
  }

  /**
   * Render a notice that MIS backend is not used in baseline mode.
   *
   * @param {string} containerId - ID of the container element
   */
  function renderBaselineNotice(containerId) {
    var container = document.getElementById(containerId);
    if (!container) return;

    if (!needsRender(container, "baseline")) return;

    var notice = document.createElement("div");
    notice.className = "solver-info-panel solver-info-baseline";
    notice.id = "misBaselineNotice";

    var text = document.createElement("p");
    text.className = "muted";
    text.innerHTML = "<strong>Riduzione disattivata:</strong> il backend MIS non viene utilizzato. " +
      "Il problema viene risolto direttamente dal solver classico.";
    notice.appendChild(text);

    container.appendChild(notice);
  }

  /**
   * Check if a solver ID is known.
   * @param {string} type - "mis" or "classical"
   * @param {string} solverId - Solver ID to check
   * @returns {boolean}
   */
  function isKnownSolver(type, solverId) {
    if (type === "mis") {
      return solverId in MIS_INFO;
    } else if (type === "classical") {
      return solverId in CLASSICAL_INFO;
    }
    return false;
  }

  /**
   * Get available MIS solver IDs.
   * @returns {string[]}
   */
  function getMisSolverIds() {
    return Object.keys(MIS_INFO);
  }

  /**
   * Get available classical solver IDs.
   * @returns {string[]}
   */
  function getClassicalSolverIds() {
    return Object.keys(CLASSICAL_INFO);
  }

  // ============================================================================
  // Export
  // ============================================================================

  window.QReduceSolverInfo = {
    renderMisPanel: renderMisPanel,
    renderClassicalPanel: renderClassicalPanel,
    renderBaselineNotice: renderBaselineNotice,
    isKnownSolver: isKnownSolver,
    getMisSolverIds: getMisSolverIds,
    getClassicalSolverIds: getClassicalSolverIds,
    // Expose info objects for testing
    _MIS_INFO: MIS_INFO,
    _CLASSICAL_INFO: CLASSICAL_INFO
  };
})();
