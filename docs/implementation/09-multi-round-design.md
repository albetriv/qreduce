# M08: riduzione multi-round e recovery

Stato: **implementata**. L'orchestratore multi-round è eseguibile e coperto da test.

> **Nota**: Con la pipeline unificata (M09), `max_reduction_rounds` può essere 0, 1, o >1.
> La sezione seguente descrive l'implementazione legacy `run_multi_round`, ora deprecata
> a favore di `run_pipeline`. Vedere la sezione M09 alla fine del documento per l'API
> attuale.

## Requisiti delle specifiche

Il runner applica le sezioni 9 delle specifiche: ogni round parte dal problema
residuo precedente e dal relativo dominio, senza reintrodurre item esclusi.
I tentativi di recovery ricostruiscono dal problema di inizio round e sono
registrati separatamente; il post-check finale considera il problema originale
e tutti i fixing cumulativi.

## Implementazione

### Configurazione (`src/qreduce/models.py`)

`ReductionPolicy` include i parametri di controllo:

```python
max_reduction_rounds: int                      # >= 0, default 1
recovery_policy_on_domain_too_small: str       # "fail" | "retry_with_larger_domain"
recovery_policy_on_infeasible: str             # "fail" | "retry_with_larger_domain"
max_recovery_attempts: int                     # >= 0
```

Semantica di `max_reduction_rounds`:
- `0`: baseline classico, nessuna riduzione MWIS, solve diretto del problema originale
- `1`: un singolo round di riduzione
- `>1`: riduzione iterativa con recovery opzionale

La validazione in `config.py` verifica:
- `max_reduction_rounds >= 0`
- Se `max_reduction_rounds == 0`, le policy di recovery devono essere `"fail"`
- `max_recovery_attempts > 0` richiede almeno una policy diversa da `"fail"` e `max_reduction_rounds >= 1`

### Orchestratore (implementazione interna)

L'implementazione interna `_run_multi_round_impl` gestisce l'iterazione:

1. **Loop sui round**: chiama `_run_single_pass_with_counts` con `_round_index`
   corretto, passando il problema residuo del round precedente.

2. **Criteri di stop**:
   - Success o partial success
   - `max_reduction_rounds` raggiunto
   - `min_reduction_ratio` non soddisfatto (stallo del dominio)
   - `target_binary_variables` raggiunto
   - Budget temporale end-to-end esaurito
   - Dominio candidato troppo piccolo

3. **Recovery operativa**: quando una failure è recuperabile (`CANDIDATE_DOMAIN_TOO_SMALL`
   o `CLASSICAL_SOLVER_INFEASIBLE` con policy `retry_with_larger_domain`):
   - Espande il dominio usando `expand_ranked_domain` e `rank_recovery_items`
   - Ricostruisce P_t con il dominio espanso tramite `_run_with_expanded_domain`
   - Ri-esegue fixing, solve classico e post-check con il nuovo dominio
   - Registra ogni tentativo in `RecoveryAttempt` con trigger, dimensioni e outcome

4. **Manifest cumulativo**: `cumulative_fixing_manifest` da `rounds.py` unisce
   i manifest di tutti i round, verificando monotonicità e assenza di conflitti.
   Gli errori di validazione non sono silenziati e causano failure esplicita.

5. **Post-check con fixing cumulativi**: il post-check finale valida contro il
   problema **originale** con il manifest **cumulativo**, non solo quello del round.

### Risultato (`MultiRoundRunResult`)

```python
@dataclass(frozen=True, slots=True)
class MultiRoundRunResult:
    run_result: RunResult
    resolved_config: ResolvedRunConfig
    round_results: tuple[SinglePassRunResult, ...]
    recovery_attempts: tuple[RecoveryAttempt, ...]  # ogni tentativo registrato
    cumulative_fixing_manifest: FixingManifest | None
    original_variable_counts: LogicalVariableCounts | None
    residual_variable_counts: LogicalVariableCounts | None
    final_retained_item_ids: tuple[str, ...]
    classical_result: ClassicalSolveResult | None
    metrics: Mapping[str, object]  # include round_count, recovery_attempt_count
```

### `RecoveryAttempt`

```python
@dataclass(frozen=True, slots=True)
class RecoveryAttempt:
    attempt_index: int
    trigger_reason: TerminalReason
    expanded_domain_size: int
    previous_domain_size: int
    outcome: str  # "success", "exhausted", "retry", "failed"
```

### Primitive di supporto

- `recovery.py`:
  - `expand_ranked_domain`: aggiunge un item per tentativo, deterministico
  - `rank_recovery_items`: completa il ranking con item non selezionati per peso

- `rounds.py`:
  - `validate_round_manifest`: verifica partizione corretta del dominio di round
  - `validate_manifest_sequence`: verifica monotonicità inter-round
  - `cumulative_fixing_manifest`: unisce i manifest preservando provenance

### Propagazione round_index

Il parametro `_round_index` viene propagato attraverso la pipeline single-pass a:
- `MISCompilationRequest.round_index`
- `MISBackendRequest.round_index`
- `FixingManifest.round_index`
- `ClassicalSolveRequest.round_index`

## Test

21 test in `tests/pipeline/test_multi_round.py` coprono:
- Single round equivalente a single-pass
- Stop on success
- Max rounds limit
- Manifest cumulativo
- Monotonicità del dominio
- Item esclusi che non riappaiono
- Propagazione round_index ai backend
- Validazione recovery policy
- Validazione recovery attempts
- Metriche round_count
- Serializzazione risultato
- **Recovery espande effettivamente il dominio su infeasible** (con assert su `expanded_domain_size > previous_domain_size`)
- **RecoveryAttempt registrati con metadati corretti**
- **Recovery si ferma quando il dominio non può espandersi**
- **Errori cumulative manifest sollevano ValueError** (verifica diretta su `cumulative_fixing_manifest`)
- **Post-check usa problema originale** (verifica tipo `SimpleProblem`)
- **Infeasible senza recovery termina immediatamente**
- **Adapter failure in `build_fixing_manifest` durante recovery**
- **Adapter failure in `restrict_problem` durante recovery**
- **Adapter failure in `validate_candidate_domain` durante recovery**

Test di configurazione in `tests/test_config.py` coprono i nuovi parametri.

Test del runner in `tests/experiments/test_runner.py`:
- **`test_multi_round_experiment_persists_round_artifacts`**: verifica persistenza
  artifact multi-round, manifest con `round_count`, `recovery_attempt_count`

## Integrazione Runner

Il runner `run_experiment` usa internamente `run_pipeline`:
- Il comportamento è determinato da `config.reduction.max_reduction_rounds`
- Persiste `round_XX_result.json` per ogni round di riduzione
- Persiste `recovery_attempts.json` se presenti
- Il manifest (schema 1.1) include:
  - `round_count`: numero di round di riduzione eseguiti
  - `is_classical_only`: true se `max_reduction_rounds=0`
  - `has_reduction`: true se almeno un round di riduzione
  - `recovery_attempt_count`: numero di tentativi di recovery
  - `fixing_manifest`: manifest cumulativo serializzato

> **Nota**: Il parametro `mode` è stato rimosso. Il comportamento è ora
> determinato esclusivamente da `max_reduction_rounds` nella configurazione.

## Esportazione

`run_pipeline`, `PipelineRunResult` e `ReductionRoundResult` sono i tipi
principali esportati da `qreduce.pipeline`.

Le funzioni e tipi legacy rimangono disponibili ma sono deprecati:
- `run_multi_round` (deprecato, usa `run_pipeline`)
- `run_single_pass` (deprecato, usa `run_pipeline` con `max_reduction_rounds=1`)
- `MultiRoundRunResult` (usa `PipelineRunResult`)
- `SinglePassRunResult` (usa `PipelineRunResult` o `ReductionRoundResult`)

## Invarianti garantite

- **Monotonicità**: `V_(t+1) ⊆ V_t` - il dominio non cresce mai tra round
- **Esclusione permanente**: un item escluso non può rientrare in round successivi
- **Partizione**: ogni manifest partiziona esattamente il dominio di input del round
- **Provenance**: i manifest di round sono preservati per auditabilità
- **Recovery operativa**: l'espansione del dominio modifica effettivamente P_t
- **Post-check cumulativo**: validazione finale contro problema originale + tutti i fixing
- **Failure path espliciti**: errori adapter in recovery producono `ADAPTER_FAILURE`

---

## M09: pipeline unificata e baseline classical-only

Stato: **implementata**. La pipeline unificata `run_pipeline` sostituisce le funzioni
legacy `run_single_pass` e `run_multi_round`.

### Motivazione

La separazione tra single-pass e multi-round creava ridondanza nella configurazione
(parametro `mode`) e nel runner. La pipeline unificata usa un singolo entry point
che determina il comportamento in base a `max_reduction_rounds`:

- `0`: Baseline classical-only (nessuna riduzione MWIS)
- `1`: Singolo round di riduzione
- `>1`: Riduzione iterativa con recovery opzionale

### Implementazione (`src/qreduce/pipeline/unified.py`)

`run_pipeline` è il nuovo entry point che:
1. Valida la configurazione
2. Esegue `_run_classical_only()` se `max_reduction_rounds=0`
3. Altrimenti esegue `_run_reduction_pipeline()` (che delega a `run_multi_round`)

#### Baseline classical-only (`max_reduction_rounds=0`)

Quando `max_reduction_rounds=0`:
- **Non viene invocato alcun componente MWIS** (grafo, solver, canonicalizzazione)
- Il problema originale viene risolto classicamente senza riduzione
- Il manifest ha `origin="no_reduction"` con tutti gli item retained
- `original_variable_counts == residual_variable_counts`
- `round_results=()` e `is_classical_only=True`

Questo percorso serve come **baseline classica** per confrontare i risultati con
la riduzione MWIS attivata.

### Tipo di risultato unificato (`PipelineRunResult`)

```python
@dataclass(frozen=True, slots=True)
class PipelineRunResult:
    run_result: RunResult
    resolved_config: ResolvedRunConfig
    round_results: tuple[ReductionRoundResult, ...]  # vuoto per classical-only
    recovery_attempts: tuple[RecoveryAttempt, ...]
    cumulative_fixing_manifest: FixingManifest | None
    final_retained_item_ids: tuple[str, ...]
    original_variable_counts: LogicalVariableCounts | None
    residual_variable_counts: LogicalVariableCounts | None
    classical_result: ClassicalSolveResult | None
    postcheck_result: FinalSolutionValidationResult | None
    domain_evaluation_metrics: tuple[DomainEvaluationMetric, ...] | None
    metrics: Mapping[str, object]

    @property
    def is_classical_only(self) -> bool:
        return len(self.round_results) == 0

    @property
    def has_reduction(self) -> bool:
        return len(self.round_results) > 0

    @property
    def reduction_round_count(self) -> int:
        return len(self.round_results)
```

### Deprecazione API legacy

Le funzioni `run_single_pass` e `run_multi_round` sono deprecate e emettono
`DeprecationWarning`:

```python
# DEPRECATO - usare run_pipeline
from qreduce.pipeline import run_single_pass  # emette DeprecationWarning
result = run_single_pass(problem, adapter, config)

# NUOVO - pipeline unificata
from qreduce.pipeline import run_pipeline
result = run_pipeline(problem, adapter, config)  # max_reduction_rounds determina il comportamento
```

I tipi `SinglePassRunResult` e `MultiRoundRunResult` rimangono disponibili per
compatibilità con codice esistente e per la rappresentazione interna dei round,
ma `PipelineRunResult` è il tipo di risultato raccomandato.

### Runner e artifact

Il runner `run_experiment` usa internamente `run_pipeline`. Gli artifact prodotti
includono:

- Schema `1.1` con campi aggiuntivi:
  - `is_classical_only: bool`
  - `has_reduction: bool`
  - `fixing_manifest: {...}` (manifest cumulativo serializzato)

- Per baseline classical-only:
  - `round_count: 0`
  - Nessun file `round_XX_result.json`
  - `fixing_manifest.origin: "no_reduction"`

Il loader `load_experiment_run` espone la property `fixing_manifest` per accedere
al manifest dal file JSON.

### Validazione configurazione

La validazione in `config.py` ora permette:
- `max_reduction_rounds >= 0` (era `>= 1`)
- Se `max_reduction_rounds == 0`, le policy di recovery devono essere `fail`

### Test

11 test in `tests/pipeline/test_classical_only_baseline.py`:
- Baseline completa senza MIS
- MIS solver non invocato
- Grafo non costruito
- Manifest con `origin="no_reduction"`
- Tutti gli item retained
- Variable counts corrispondono
- `round_results=()` vuoto
- Solver riceve problema completo
- Test E2E con SCIP reale
- Gestione fallimento solver
- Gestione problema infeasible

1 test in `tests/experiments/test_runner.py`:
- `test_classical_only_baseline_persists_correct_artifacts`: round-trip artifact

### Migrazione

Per migrare dal codice legacy:

```python
# Prima (DEPRECATO):
from qreduce.pipeline import run_single_pass, run_multi_round, SinglePassRunResult

if mode == "single_pass":
    result = run_single_pass(problem, adapter, config)
else:
    result = run_multi_round(problem, adapter, config)

# Dopo:
from qreduce.pipeline import run_pipeline, PipelineRunResult

# Il comportamento è determinato da config.reduction.max_reduction_rounds:
# - 0: baseline classical-only
# - 1: equivalente a single_pass
# - >1: equivalente a multi_round
result = run_pipeline(problem, adapter, config)
```