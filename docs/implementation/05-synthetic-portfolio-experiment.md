# 05 - Synthetic mean-variance portfolio experiment

> **Nota**: Questo documento descrive il design originale del percorso single-pass
> per l'esperimento portfolio (milestone M05). La pipeline è stata successivamente
> unificata: il nuovo entry point è `run_pipeline` e il tipo di risultato è
> `PipelineRunResult`. Le funzioni `run_single_pass` e `run_multi_round` sono
> deprecate ma rimangono disponibili per compatibilità. Vedere la sezione M09 in
> `09-multi-round-design.md` per i dettagli.

## Scopo

Definire un esperimento interno di ottimizzazione media-varianza di portafoglio che genera un MIQP residuo solver-agnostico. Il portfolio resta confinato negli esperimenti; i solver built-in `local_greedy`, `dwave_simulated_annealing`, `cplex` e `scip` appartengono invece alla libreria e non importano il dominio portfolio.

## Riferimenti alle specifiche

- Sezioni 3.1, 4, 5.1, 8, 13, 14, 15, 17 e 21.
- `docs/implementation/00-implementation-overview.md`.
- `docs/implementation/02-core-domain-models-and-configuration.md`.

## Problema dimostrativo

Per ciascun asset `i`, `delta_i` indica se l'asset resta selezionabile e `x_i` il peso continuo. Una formulazione iniziale e`:

```text
minimize:
    risk_aversion * x^T * Sigma * x
    - expected_return^T * x

subject to:
    sum_i x_i = 1
    lower_bound_i * delta_i <= x_i <= upper_bound_i * delta_i
    delta_i in {0, 1}
    x_i >= 0
```

Questa e` una forma iniziale per dati sintetici e test. Vincoli ulteriori, limiti di cardinalita`, budget, turnover, esposizioni o costi possono essere aggiunti solo se rimangono espliciti nell'adapter e nel post-check.

## Confini di responsabilita`

| Componente | Responsabilita` |
|---|---|
| Esperimento portfolio | Item ID, pesi, archi, fixing, compilazione MIQP generica e post-check di dominio |
| QReduce core | Pipeline MWIS, cataloghi solver, modello classico generico, traduzione backend, tempi e artifact comuni |
| Backend classici built-in | Traduzione lazy del modello generico verso CPLEX o SCIP senza dipendenza dal portfolio |
| Chiamante | Policy, dati/istanza, adozione di business e valutazione esterna |

Il core riceve problemi opachi costruiti dall'adapter. Non deve conoscere classi CPLEX, formule finanziarie o strutture dati dell'istanza.

## Item, fixing e modello residuo

Ogni asset deve avere un `item_id` unico e stabile almeno per il run. Se un asset viene escluso dal candidate domain, il fixing manifest deve fare applicare:

```text
delta_i = 0
x_i = 0
```

Il secondo fixing puo` essere ottenuto dalle linking constraints gia` presenti, ma l'adapter deve dimostrarne e verificarne l'effetto. Obiettivo e tutti i vincoli globali devono restare nel modello residuo.

Prima del cap, la pipeline single-pass consulta
`declare_protected_items(problem)` dell'adapter. Il contratto puo` restituire la
tupla legacy di item obbligatori oppure una `ProtectionDeclaration` con le
categorie `mandatory`, `user_locked`, `safe_retained` e
`incumbent_supported`. La dichiarazione e` letta una volta per round; gli ID
devono appartenere al grafo canonico e non possono comparire in piu` categorie.

`mandatory`, `user_locked` e `safe_retained` hanno precedenza sul cap. Gli
`incumbent_supported` seguono `incumbent_protection_mode = required | best_effort`:
nel primo caso hanno la stessa precedenza obbligatoria; nel secondo partecipano
al ranking ma possono essere esclusi dal cap con il reason code
`best_effort_protection_excluded_by_cap`. Se le protezioni obbligatorie superano
`candidate_domain_max_items`, il run termina con
`protected_items_exceed_candidate_domain_cap`, senza creare un fixing manifest.
La dichiarazione resta separata da `validate_candidate_domain`, che valida il
dominio effettivo dopo cap e protezioni.

Il risultato single-pass conserva `candidate_records` e
`candidate_domain_item_records`: includono esito di repair, duplicazione,
diversita`, ranking e ragione di retention/esclusione per item. Le policy di
protezione specifiche del dominio portfolio restano assenti nel caso base: il
test usa dichiarazioni locali dell'adapter per verificare il comportamento del
kernel senza introdurre regole finanziarie implicite.

## Matrice requisiti -> implementazione -> test M05

La matrice copre i requisiti M02/M05 materializzati dal percorso portfolio
single-pass. I riferimenti alle sezioni sono di `docs/specifications.md`.

| Requisito | Implementazione | Test principale | Stato |
|---|---|---|---|
| 7: percorso `graph -> MIS -> candidate domain -> restrict -> classical -> post-check` | `run_single_pass` in `src/qreduce/pipeline/single_pass.py`; adapter in `src/qreduce/experiments/portfolio_domain/` | `tests/experiments/test_portfolio_single_pass.py`; integrazioni SCIP/CPLEX quando disponibili | Coperto |
| 8.1-8.2: candidate selezionate, ranking e dominio aggregato | `_select_diverse_samples`, `_candidate_domain_item_ids` e record audit nel single-pass | `tests/pipeline/test_single_pass_selection.py` | Coperto |
| 8.3: cap stabile e dominio minimo | applicazione cap, `candidate_domain_min_items`, validazione adapter | `test_pipeline_enforces_adapter_minimum_before_building_a_manifest`; test di ranking/cap in `tests/pipeline/test_single_pass_selection.py` | Coperto |
| 8.3: protezioni obbligatorie prima del cap | `ProtectionDeclaration.required_item_ids`; failure `protected_items_exceed_candidate_domain_cap` | `test_pipeline_retains_declared_protected_items_before_applying_cap`; `test_pipeline_fails_before_fixing_when_protected_items_exceed_cap` | Coperto |
| 8.3: incumbent best-effort auditabile | `ProtectionDeclaration.best_effort_item_ids`; reason `best_effort_protection_excluded_by_cap` | `test_pipeline_records_best_effort_protection_excluded_by_cap`; unit test cap best-effort | Coperto |
| 8.4, 10: fixing completo e manifest serializzabile | `FixingManifest`, adapter portfolio `restrict_problem`, controllo di coerenza prima della restriction | test fixing/manifest in `tests/experiments/test_portfolio_single_pass.py` | Coperto |
| 12.1-12.2: validazione strutturale, repair deterministico, esiti auditabili | validazione MWIS e `_repair_sample`; `CandidateRecord.repair_status`/`repair_actions` | test repair e candidate record in `tests/pipeline/test_single_pass_selection.py` | Coperto |
| 12.3: diversita` post-validazione e reason di scarto | `_select_diverse_samples`; `CandidateRecord.rejection_reason` | `test_diversity_audit_records_the_observed_rejection_reason` | Coperto |
| 16.2, 17: risultato serializzabile e artifact runner | `SinglePassRunResult.to_dict`; runner interno | `tests/experiments/test_runner.py`; matrice dettagliata in `06-single-pass-metrics-audit.md` | Parziale: colmare i gap individuati nell'audit |
| 13, 16.2: conteggi logici delle variabili libere | `LogicalVariableCounts`; `describe_logical_variables` dell'adapter portfolio | `tests/experiments/portfolio_domain/test_adapter.py`; test single-pass e runner | Coperto per il contratto obbligatorio; esclusi fixing espliciti e ausiliarie solver |
| 16.3, 20.8: provenance policy senza selezione automatica | `PolicyProvenance` in config risolta | `tests/test_config.py`; artifact runner | Coperto |
| 9, 20.6: domini monotoni, stop iterativi, per-round artifact | Nessun loop multi-round nel single-pass | Non applicabile al percorso M05 corrente | Non implementato: M08 |
| 9.5, 18: recovery e rollback | Nessun recovery implicito; fixing terminale nel singolo round | Non applicabile al percorso M05 corrente | Non implementato: M08 |

La matrice non dichiara ottimalita` del problema portfolio originale: il solve
classico ottimo del problema residuo resta condizionato al fixing euristico o
imposto applicato nel single-pass.

## Policy iniziale del grafo

La policy di costruzione del grafo e` esterna/versionata e non e` una legge finanziaria universale. Per la prima implementazione puo` usare dati sintetici e una regola semplice, auditabile e sostituibile, per esempio:

- peso nodale da rendimento atteso, rischio individuale o score di retention dichiarato;
- arco per correlazione assoluta sopra una soglia esplicita;
- reason dell'arco che includa metrica e soglia applicata.

La policy deve registrare input, formula, soglie, versione e qualunque normalizzazione. Il grafo di riduzione non sostituisce Sigma, il modello MIQP o i vincoli hard di portafoglio.

## Solver classici built-in

Nell'esperimento gli ID classici `cplex` e `scip` sono risolti dalle factory
built-in QReduce. Il residual problem portfolio implementa
`build_classical_model()` e restituisce variabili, obiettivo MIQP e vincoli in
forma solver-agnostica; il backend selezionato effettua la traduzione nativa.
L'integrazione deve almeno:

- configurare time limit, mip gap, seed e threads quando supportati;
- restituire status, feasible, objective, bound/gap quando disponibili e runtime;
- distinguere optimal, infeasible, failed e time limit con o senza incumbent;
- esportare il modello se richiesto;
- dichiarare indisponibilita` del binding o della licenza senza fallback.

I binding Python CPLEX, PySCIPOpt e Ocean vengono installati tramite il gruppo
Poetry `experiments`. Il percorso portfolio predefinito usa `local_greedy` e
`scip`; SCIP richiede il binding PySCIPOpt. Il test live CPLEX richiede inoltre
una licenza locale utilizzabile e deve essere marcato come integrazione opzionale.
Il simulatore MIS `dwave_simulated_annealing` e` locale e non richiede credenziali
o una QPU.

Il runner dell'esperimento accetta inoltre ID built-in espliciti e parametri
Ocean `num_reads` e `num_sweeps`. Un run con D-Wave locale e CPLEX puo` essere
pubblicato con:

```bash
poetry run python -m qreduce.experiments.portfolio \
  --run-id 003_dwave_cplex \
  --mis-solver-id dwave_simulated_annealing \
  --classical-solver-id cplex \
  --mis-num-reads 100 \
  --mis-num-sweeps 1000
```

Il notebook `003_synthetic_portfolio_single_pass.ipynb`
analizza esclusivamente gli artifact del run pubblicato e non invoca la pipeline.

## Post-check indipendente

L'adapter deve validare la soluzione senza fidarsi soltanto dello status del solver. Il controllo deve includere almeno:

- conformita` a tutti i fixing del manifest;
- budget `sum_i x_i = 1` entro tolleranza;
- bounds e linking constraints;
- integrality delle variabili `delta`;
- non negativita` dei pesi, se attivata;
- ricomputazione obiettivo quando supportata;
- failure reasons di dominio.

Una soluzione e` adottabile soltanto con solve feasible, post-check positivo e fixing rispettati.

## Dati e test iniziali

Usare istanze sintetiche piccole e deterministiche, costruite nei test o tramite factory Python. Non introdurre dataset esterni o notebook come fonte primaria della logica.

Test minimi:

- mapping stabile asset/item/variabili;
- fixing di asset esclusi applica `delta_i = 0` e `x_i = 0`;
- problema residuo conserva obiettivo e vincoli globali;
- SCIP indisponibile restituisce failure esplicita;
- il percorso single-pass predefinito usa `local_greedy`, costruisce fixing e richiede `scip`;
- soluzione SCIP feasible supera il post-check;
- soluzione che viola fixing, integrality o budget non e` adottata;
- il solver puo` scegliere un sottoinsieme fattibile di `C_effective` che non coincide con una candidate MWIS sorgente.
- un item protetto dichiarato dall'adapter ha precedenza sul cap; protezioni oltre
  il cap o esterne al grafo falliscono prima del fixing.
- il kernel rifiuta un dominio inferiore a `minimum_required_items` e un fixing
  manifest non corrispondente esattamente al dominio effettivo prima della
  restriction.

## Moduli Python indicativi

```text
src/qreduce/experiments/portfolio_domain/models.py
src/qreduce/experiments/portfolio_domain/adapter.py
src/qreduce/solving/residual/model.py
src/qreduce/solving/residual/contracts.py
src/qreduce/solving/residual/registry.py
src/qreduce/solving/residual/cplex_backend.py
src/qreduce/solving/residual/scip_backend.py
src/qreduce/pipeline/single_pass.py
src/qreduce/experiments/portfolio_domain/postcheck.py
```

I moduli finanziari restano confinati negli esperimenti e possono evolvere senza cambiare il contratto di `ReducibleProblemAdapter`.

## Criteri di completamento

- L'esperimento portfolio predefinito percorre `local_greedy`, restriction, solve
  `scip` e post-check tramite cataloghi solver built-in QReduce. CPLEX resta
  selezionabile esplicitamente, incluso nel notebook D-Wave + CPLEX.
- L'adapter fornisce mapping completo e auditabile fra item e variabili fissate.
- Il fixing euristico non viene presentato come preservazione dell'ottimo originale.
- L'indisponibilita` del backend selezionato e le infeasibility sono serializzate
  come esiti espliciti.

## Stato della verifica

**Stato: Completata.** La verifica del 2026-11-12 ha confermato che tutti i
criteri di completamento sono soddisfatti.

### Criteri soddisfatti

| Criterio | Evidenza |
|---|---|
| Esperimento portfolio con `local_greedy` + `scip` + post-check | `tests/experiments/test_portfolio_scip_integration.py::test_default_portfolio_path_solves_with_scip` passa; run pubblicati in `outputs/` |
| Mapping completo e auditabile | `FixingManifest` con `round_index`, `source_candidate_ids`, `policy_version`; ogni `FixingEntry` ha `fixing_origin` e `guarantee_level`; test in `tests/domains/test_fixing_guarantees.py` |
| Fixing euristico non presentato come ottimo | `original_problem_optimality_claim == "none"` verificato nei test; documentazione esplicita |
| Indisponibilita` backend serializzata | `test_portfolio_single_pass_reaches_explicit_cplex_unavailable_failure` verifica `CLASSICAL_BACKEND_UNAVAILABLE` |
| Infeasibility serializzata | `test_classical_solver_infeasible_is_serialized_with_candidate_data` verifica `CLASSICAL_SOLVER_INFEASIBLE` con preservazione di `fixing_manifest` e `candidate_records` |

### Metriche single-pass esposte

Le metriche richieste dalla sezione 16.2 delle specifiche sono ora disponibili
nel risultato in memoria:

- `round_reduction_ratio` e `cumulative_reduction_ratio` (coincidenti nel single-pass)
- `unique_sample_count`, `processed_unique_sample_count`, `repaired_candidate_count`
- `end_to_end_runtime_seconds`, `mis_runtime_seconds`, `classical_runtime_seconds`
- `candidate_domain_size`, `valid_candidate_count`, `selected_candidate_count`
- Conteggi logici `original_variable_counts` e `residual_variable_counts`
- Metriche di dominio tramite `evaluate_domain_metrics` dell'adapter

### Requisiti esplicitamente esclusi dal perimetro M05

I seguenti requisiti delle specifiche sono **bloccati a M08** perche' richiedono
semantica multi-round:

- §9, 20.6: domini monotoni, stop iterativi, artifact per round
- §9.5, 18: recovery e rollback