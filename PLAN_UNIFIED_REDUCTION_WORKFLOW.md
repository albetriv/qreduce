# Piano: workflow unico di riduzione e solve classico

## Obiettivo

Eliminare il parametro `mode` dal runner e far convergere gli attuali workflow
single-pass e multi-round in un unico workflow pubblico, con gli stessi oggetti
di input, output e artifact.

Il comportamento deve essere determinato unicamente dalla policy di riduzione:

| `max_reduction_rounds` | Comportamento |
|---:|---|
| `0` | Solve classico dell'intero problema, senza riduzione MWIS |
| `1` | Un singolo round di riduzione |
| `> 1` | Riduzione iterativa fino al limite, con eventuale recovery |

La recovery resta controllata da:

```text
max_recovery_attempts
recovery_policy_on_domain_too_small
recovery_policy_on_infeasible
```

## Motivazione

L'API attuale combina:

```python
mode="single_pass" | "multi_round"
```

con:

```python
config.reduction.max_reduction_rounds
```

Questa combinazione permette configurazioni ambigue. Per esempio:

```python
mode="single_pass"
max_reduction_rounds=3
max_recovery_attempts=2
```

Nel percorso single-pass i parametri multi-round e recovery non hanno effetto.
Il nuovo design elimina questa duplicazione: esiste un solo orchestratore e il
numero massimo di round determina il comportamento.

## Invarianti del nuovo workflow

1. Esiste una sola entry point pubblica per eseguire pipeline e pubblicare
   artifact.
2. Esiste un solo tipo top-level di risultato in memoria.
3. Tutte le run producono lo stesso schema di manifest.
4. Il solver classico continua a ricevere un problema residuale costruito
   dall'adapter; non deve ricevere direttamente un problema di dominio opaco.
5. Il post-check continua a essere eseguito sul problema originale.
6. Il caso `max_reduction_rounds=0` non deve costruire grafo, compilare MWIS,
   invocare un backend MIS, selezionare candidate domain o applicare fixing
   euristici.
7. Gli artifact di round e recovery sono presenti solo quando esistono dati da
   pubblicare.

## API di esecuzione target

Sostituire:

```python
run_experiment(..., mode="single_pass")
run_experiment(..., mode="multi_round")
```

con:

```python
run_experiment(
    experiment_id,
    problem,
    adapter,
    config,
    mis_solver_registry=None,
    classical_solver_registry=None,
    output_root="outputs",
    experiment_metadata=None,
)
```

Il runner invoca un unico orchestratore, per esempio:

```python
run_pipeline(...)
```

oppure:

```python
run_reduction_pipeline(...)
```

Il nome definitivo deve rendere chiaro che il caso senza riduzione e` supportato.

## Risultato top-level unificato

Introdurre un tipo unico, per esempio `PipelineRunResult`, che sostituisce
`SinglePassRunResult` e `MultiRoundRunResult` come output pubblico top-level.

Campi principali proposti:

```python
@dataclass(frozen=True, slots=True)
class PipelineRunResult:
    run_result: RunResult
    resolved_config: ResolvedRunConfig

    round_results: tuple[ReductionRoundResult, ...]
    recovery_attempts: tuple[RecoveryAttempt, ...]

    cumulative_fixing_manifest: FixingManifest
    final_retained_item_ids: tuple[str, ...]

    original_variable_counts: LogicalVariableCounts | None
    residual_variable_counts: LogicalVariableCounts | None

    classical_result: ClassicalSolveResult | None
    postcheck_result: FinalSolutionValidationResult | None
    domain_evaluation_metrics: tuple[DomainEvaluationMetric, ...] | None

    objective_sense: str
    original_primal_bound: float | None
    original_dual_bound: float | None
    original_bound_provenance: str
    original_problem_optimality_claim: str
    residual_problem_optimality_claim: str

    metrics: Mapping[str, object]
```

L'attuale risultato single-pass diventa un risultato dettagliato di round,
per esempio `ReductionRoundResult`. Mantiene gli artifact specifici:

```text
selected_mis_samples
candidate_records
candidate_domain_item_records
protection_declaration
mis_compilation_result
mis_execution_result
fixing_manifest
classical_result
postcheck_result
```

Semantica uniforme:

| Caso | `round_results` | Manifest cumulativo |
|---|---:|---|
| Nessuna riduzione | `()` | Manifest vuoto |
| Un round | un elemento | fixing del round 0 |
| Piu` round | da uno al limite configurato | fixing cumulati |

## Semantica di `max_reduction_rounds=0`

`max_reduction_rounds=0` significa solve classico baseline, senza riduzione.

### Comportamento richiesto

1. Identificare tutti gli item riducibili:

   ```python
   original_item_ids = tuple(adapter.identify_reducible_items(problem))
   ```

2. Costruire un manifest esplicitamente vuoto:

   ```python
   FixingManifest(
       retained_item_ids=original_item_ids,
       excluded_item_ids=(),
       entries=(),
       origin="no_reduction",
       provenance={
           "reduction_applied": False,
           "optimality_preservation_claim": "not_applicable",
       },
   )
   ```

3. Costruire il residuale tramite l'adapter:

   ```python
   adapter.restrict_problem(problem, original_item_ids, empty_manifest)
   ```

4. Costruire il modello residuale con l'adapter e invocare il backend classico.
5. Eseguire il post-check sul problema originale con il manifest vuoto.
6. Eseguire `evaluate_domain_metrics` dopo un post-check raggiunto.

### Passi vietati nel baseline

Il caso `max_reduction_rounds=0` non deve invocare:

```text
adapter.build_conflict_graph(...)
adapter.declare_protected_items(...)
adapter.validate_candidate_domain(...)
adapter.build_fixing_manifest(...)
MIS compilation
MIS backend execution
candidate ranking
recovery
```

In particolare, un backend MIS mancante o non disponibile non deve poter far
fallire il solve classico baseline.

### Perche` non usare `adapter.build_fixing_manifest(...)`

L'adapter portfolio corrente attribuisce al manifest:

```text
origin = heuristic_candidate_domain
optimality_preservation_claim = none
```

Questa provenance sarebbe fuorviante per un solve senza esclusioni. Il manifest
baseline deve essere creato dal kernel con semantica `no_reduction`.

## Validazione della configurazione

Modificare la validazione:

```text
max_reduction_rounds >= 1
```

in:

```text
max_reduction_rounds >= 0
```

Quando:

```text
max_reduction_rounds == 0
```

richiedere:

```text
max_recovery_attempts == 0
recovery_policy_on_domain_too_small == "fail"
recovery_policy_on_infeasible == "fail"
```

Altrimenti produrre una validation failure esplicita, per esempio:

```text
Recovery requires max_reduction_rounds >= 1.
```

Per minimizzare il perimetro, i campi MIS e lambda restano presenti in
`ResolvedRunConfig`: sono persistiti negli artifact ma non usati, ne` sottoposti
a capability validation, quando non viene eseguita riduzione.

## Orchestratore unico

Struttura proposta:

```text
run_pipeline
|
|-- max_reduction_rounds == 0
|   `-- _run_classical_only(...)
|
`-- max_reduction_rounds > 0
    `-- ciclo dei round
        |-- _run_reduction_round(...)
        |-- recovery eventuale
        |-- manifest cumulativo
        `-- stopping criteria
```

L'attuale `run_single_pass()` deve diventare una primitive interna per un round,
per esempio:

```python
_run_reduction_round(...)
```

L'attuale `run_multi_round()` costituisce la base dell'orchestratore unificato.

## Artifact e manifest uniformi

Rimuovere il campo di scelta workflow:

```json
{"run_mode": "single_pass"}
```

oppure:

```json
{"run_mode": "multi_round"}
```

Ogni manifest deve invece contenere:

```json
{
  "artifact_schema_version": "1.1",
  "experiment_id": "...",
  "run_id": "...",
  "run_status": "...",
  "config_hash": "...",
  "round_count": 0,
  "recovery_attempt_count": 0,
  "files": {}
}
```

Interpretazione:

| Caso | Config | `round_count` |
|---|---:|---:|
| Baseline classico | `max_reduction_rounds=0` | `0` |
| Successo primo round | `max_reduction_rounds>=1` | `1` |
| Multi-round | `max_reduction_rounds>1` | `>1` |

Policy di file:

| Caso | File aggiuntivi |
|---|---|
| Nessuna riduzione | nessun `round_XX_result.json` |
| Un round | `round_00_result.json` |
| Piu` round | un file `round_XX_result.json` per ogni round |
| Recovery | `recovery_attempts.json` solo se esistono tentativi |

Il file top-level `canonical_mwis_problem.json` deve essere eliminato come caso
speciale del vecchio single-pass: il problema MWIS canonico resta dentro il
risultato del round che lo ha costruito.

## Loader e versione schema

Aggiornare `ExperimentRunArtifacts` per esporre proprieta` basate sul contenuto:

```python
@property
def reduction_round_count(self) -> int: ...

@property
def has_reduction(self) -> bool: ...

@property
def is_classical_only(self) -> bool: ...
```

Eliminare `is_multi_round` oppure mantenerla soltanto come compatibilita`
temporanea.

Incrementare:

```text
ARTIFACT_SCHEMA_VERSION = "1.1"
```

Il writer produce solo `1.1`. Il loader dovrebbe supportare almeno `1.0` e
`1.1`, cosi` da non rendere inutilizzabili gli artifact gia` presenti in
`outputs/`.

## Model export

L'attuale disparita` deve essere eliminata:

```text
single-pass: model export supportato
multi-round: model export non supportato
```

Ogni solve classico deve poter produrre un export con path auditabile, per
esempio:

```text
residual_models/
|- classical_only_attempt_00.lp
|- round_00_attempt_00.lp
|- round_00_attempt_01.lp
`- round_01_attempt_00.lp
```

Il manifest deve registrare una lista di export, includendo almeno:

```text
path
sha256
round_index
recovery_attempt_index
external
```

## Aggiornamenti ai consumer

### Runner

* Rimuovere `mode` dalla firma di `run_experiment`.
* Restituire sempre il tipo top-level unificato.
* Eliminare i branch per `SinglePassRunResult` e `MultiRoundRunResult`.

### Esperimenti e CLI

* Il portfolio standard resta un esperimento con:

  ```text
  max_reduction_rounds=1
  ```

* L'esperimento portfolio grande resta configurato con:

  ```text
  max_reduction_rounds=3
  ```

* Rimuovere `mode="multi_round"` da
  `src/qreduce/experiments/portfolio_multi_round.py`.
* In un refactor separato, valutare un rinominamento del modulo
  `portfolio_multi_round.py` in un nome relativo alla dimensione o al caso
  sperimentale, non al workflow interno.

### Adapter

Il protocollo puo` rimanere invariato. Il baseline usa:

```text
describe_logical_variables
identify_reducible_items
restrict_problem
build_residual_model
validate_final_solution
evaluate_domain_metrics
```

Non deve bypassare l'adapter passando il problema di dominio direttamente al
backend classico.

## Piano di test

### Configurazione

* `max_reduction_rounds=0` e` valido.
* `max_reduction_rounds=-1` e` invalido.
* Recovery configurata con zero round e` invalida.
* Uno e piu` round restano validi.

### Baseline classico senza riduzione

Verificare che:

1. il backend MIS non venga creato;
2. `build_conflict_graph()` non venga chiamato;
3. tutti gli item siano retained;
4. il manifest abbia zero fixing e origine `no_reduction`;
5. il residuale conservi il dominio completo;
6. il backend classico venga invocato;
7. il post-check usi il problema originale;
8. la soluzione possa essere adottata;
9. `round_results == ()`;
10. `recovery_attempts == ()`;
11. i conteggi delle variabili logiche originali e residue coincidano.

### Riduzione con un round

Verificare che:

```text
max_reduction_rounds=1
round_count=1
round_00_result.json presente
```

e che non esista piu` un percorso runner separato single-pass.

### Riduzione multi-round e recovery

Migrare gli attuali test M08 verso l'entry point unico:

* stop al successo;
* stop al limite round;
* recovery per infeasibility;
* recovery per domain troppo piccolo;
* manifest cumulativo;
* post-check sull'originale;
* monotonicita` del dominio;
* artifact round-trip.

### Artifact e loader

* Schema artifact `1.1`.
* Baseline classico con zero round.
* Run con un round.
* Run con piu` round.
* Run con recovery.
* Verifica hash per ogni artifact dinamico.
* Compatibilita` in lettura con schema `1.0`, se adottata.

### Model export

* Baseline classico.
* Un round.
* Recovery con solve classici multipli.
* Tampering di ogni export interno.
* Export esterno, se il requisito viene mantenuto.

## Documentazione da aggiornare

Aggiornare, se impattati:

```text
README.md
docs/specifications.md
docs/implementation/00-implementation-overview.md
docs/implementation/08-experiment-artifacts.md
docs/implementation/09-multi-round-design.md
```

La documentazione deve descrivere:

* workflow unico;
* `max_reduction_rounds=0` come baseline classico;
* `max_reduction_rounds=1` come singola riduzione;
* `max_reduction_rounds>1` come riduzione iterativa;
* recovery;
* schema artifact aggiornato;
* model export uniforme.

## Sequenza di implementazione

### Fase 1 - Contratti e validazione

1. Consentire `max_reduction_rounds=0`.
2. Rendere invalida recovery senza round.
3. Aggiungere test di configurazione baseline.
4. Mantenere temporaneamente le API esistenti.

### Fase 2 - Workflow unico interno

1. Estrarre l'orchestratore unico dalla logica multi-round.
2. Trasformare il single-pass in primitive interna di round.
3. Implementare `_run_classical_only(...)`.
4. Introdurre il risultato top-level unificato.
5. Coprire con test di pipeline.

### Fase 3 - Runner e artifact

1. Rimuovere `mode` da `run_experiment`.
2. Restituire sempre il tipo unificato.
3. Uniformare artifact e manifest.
4. Aggiornare il loader per schema `1.1`.
5. Implementare strategy uniforme per model export.

### Fase 4 - Consumer

1. Aggiornare experiment factory e CLI.
2. Aggiornare test, notebook, README e documentazione.
3. Rimuovere o deprecare le vecchie entry point e i vecchi tipi pubblici.

### Fase 5 - Verifica finale

Eseguire:

```bash
cd /Users/trivellatoa/DATADIR/Programmazione/python_local/python-312/qreduce
poetry run pytest -q
poetry run ruff check src tests
```

Pubblicare e verificare tramite loader almeno tre run:

```text
baseline-classical-only
one-reduction-round
iterative-reduction-with-recovery
```

Per ciascuna verificare:

```text
round_count
recovery_attempt_count
fixing manifest
classical result
post-check
artifact hash verification
loader round-trip
```