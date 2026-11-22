# UIX portfolio comparison: inspection and test handoff

## Contextual solver panels (22 November 2026)

The three configurators share `uix/assets/solver_info.js`. MIS descriptions and
embedding warnings follow the active backend; baseline has a single notice.
Classical descriptions remain available in baseline. Hidden backend values are
retained but omitted from commands. Rendering is cached per container and relevant
state to avoid rebuilding live regions on unrelated form edits. The Pasqal budget
error is attached to the budget field with accessible description and invalid state.
Pulser installation now uses the `experiments` dependency group.

DOM regression coverage is in `tests/test_uix_solver_context.py`, including
same-DOM transitions, reset/favorite restoration, stable nodes, unique notices,
budget errors and full portfolio CLI validation. Native-browser layout and screen
reader verification remain separate from jsdom checks.

`PIANO_UIX_IMPATTO_QREDUCE.md` supersedes the presentation in
`PIANO_UIX_CONFRONTO_RUN.md`. The current **Impatto di QReduce** panel presents
an in-page dashboard and expandable technical details. It has no Markdown
report generation or download. The dashboard renders charts and the core's gated
verdict, or explains why an overall verdict is unavailable.

Generate or refresh the local snapshot from the repository root with
`python -m qreduce.experiments.portfolio_mv.run_catalog`. Open
`uix/experiment_portfolio_mv.html`, switch to **05 · Confronto**, and select two
distinct run IDs. If the page is already open, click **↻** to load the updated
snapshot without reloading the page. The browser loads the generated classic script
from `file://`; no server, folder picker, Cline or new run is required.
The two-way arrow between the dropdowns swaps the runs. The comparison tab hides
the mathematical formulation; the configuration tabs keep it. Displayed durations,
budgets and time differences are rounded to whole seconds after calculation.
The snapshot contains copies
of the comparison inputs and needs a refresh after output changes. Each run needs `run_manifest.json`, `problem.json`,
`run_result.json`, `config_used.json` and `experiment_metadata.json`; optional
`round_<index>_result.json` files supplement the recorded trace. The importer
supports artifact schemas 1.0 and 1.1 for `synthetic-portfolio`.

The Node core tests include synthetic inputs and optional checks against local
output folders: `node --test tests/uix_comparison.test.js`.

## Dashboard implementation

The visible cards show final-domain, objective-change and excluded-baseline-position
indicators, domain counts and the configured cap, a round selector with recorded
exclusion reasons and graph counts, baseline position statuses, and a textual
thermometer with objective change, solver time, end-to-end time, budgets and
domain counts. Unknown values are not treated as zero. Exclusion totals are
verified when round input and retained IDs permit it; otherwise recorded reasons
are shown without claiming a complete total. Technical details remain expandable.

The dashboard renders stacked bars for the domain and baseline positions, and a
per-round exclusion-reason donut when the exclusion total is available, with text
legends. The conclusion displays the verdict based on quality and end-to-end
time, gated on verified identical instances, valid solutions, an unreduced
baseline, a reduced comparison and sufficient data; otherwise it displays the
reasons. A zero or missing denominator prevents the corresponding ratio. Observed
differences are not evidence of a causal effect or a certificate of global
optimality.

## Remaining limitations

- This is not a complete schema validator: malformed nested fields can be
  unavailable rather than diagnosed individually. Selection falls back to a
  weight threshold when binary values are absent.
- Declared round artifacts supplement matching indexed records; conflicting
  recorded fields favor the main result. Missing graphs are never reconstructed.
  Invalid or duplicate embedded round records are ignored with a warning; a
  valid solution remains comparable if only the round trace is incomplete.
  The in-page report summarizes recorded graph size, domain cap and exclusion
  reasons per round. Asset-level evidence stays in the details.
- Run identifiers and retained domains are checked for contradictions. Missing
  cross-artifact identifiers are reported; the browser does not validate the
  canonical JSON hashes checked by the Python loader.
- Timing metrics are shown individually; no unallocated duration is inferred,
  since their scopes and overlap are not established. Configuration differences
  and graph policy details are not fully surfaced by the current panel.
- DOM emulation cannot establish native Windows browser folder selection,
  file-origin restrictions or real layout. Independent Python parity checks for
  portfolio metrics remain desirable.

## Local artifact observations

The following observations are from locally generated, Git-ignored outputs and
are not portable test fixtures:

- `outputs/portfolio_mv/ptf_100_classic` contains the manifest, problem,
  configuration, metadata and result. `ptf_100_dwave` also contains
  `round_00_result.json`. Both manifests report artifact schema `1.1`,
  experiment `synthetic-portfolio` and successful runs.
- The two `problem.json` files have the same SHA-256 hash
  `B29CF0714F611F15F07AF3B8A24E1C7CAD81521ECF342D31FFFEE47F4CDAEBD3`.
  This establishes byte identity for these files, not semantic identity in
  general.
- The classical run has zero rounds and 100 residual free binaries. The other
  has one round, 38 residual free binaries and reports a local
  `simulated_annealing` backend. Its provider name is `dwave`; that alone does
  not indicate QPU execution.
- Both postchecks report feasible. Their recomputed objectives are approximately
  -0.11039653 and -0.08842327, respectively. These are postcheck values, not
  necessarily identical to solver-reported objectives. The reduced solve's
  optimality claim is not a certificate for the original problem.
- The measured end-to-end durations are approximately 5.677 and 42.338 seconds;
  they are observations, not reproducible performance expectations.

## Test infrastructure and commands

UIX tests use pytest to launch Node.js runners; DOM tests require `jsdom`.
`package.json` declares `jsdom`, but its `npm test` script is a placeholder.
From the repository root, install the JavaScript dependencies with `npm install`,
then run, for example:

```powershell
.venv\Scripts\python.exe -m pytest tests/test_uix_favorites.py -q
.venv\Scripts\python.exe -m pytest tests/test_uix_js_execution.py -q
```

On this machine the first command skipped three tests without a normally
installed `jsdom`. With the pre-existing local dependency directory supplied
through `NODE_PATH`, it passed all three:

```powershell
$env:NODE_PATH = (Resolve-Path '.cline-tmp\uix-jsdeps\node_modules').Path
.venv\Scripts\python.exe -m pytest tests/test_uix_favorites.py -q
```

That temporary dependency directory is local and is not a project prerequisite.
A skipped UIX test is not evidence that the UI behavior passed.

## Further verification

The final local check passed 15 core tests and 32 targeted UIX tests, including
the panel test in jsdom. The panel test distinguishes a verified count of zero
excluded baseline positions from an unverified count; the positions chart still
shows unclassified positions as unknown. Run it with
`pytest tests/test_uix_comparison_panel.py -q` after installing jsdom.

A Windows Chrome headless smoke test opened the current dashboard from `file://`
and assigned `ptf_100_classic` and `ptf_100_dwave` to the file inputs through
browser automation. At 1,366 and 390 px it verified all three charts, the layout
without page or panel horizontal overflow, the expected verdict, 13 excluded
baseline positions and the absence of the Markdown export button. This did not
exercise the native graphical folder picker. An independent comparison of
calculated return and volatility with Python portfolio analysis remains outside
these checks.

