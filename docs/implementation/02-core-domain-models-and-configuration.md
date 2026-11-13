# 02 - Core domain models and configuration

> **Nota**: Questo documento descrive i modelli originali della pipeline.
> Con l'unificazione della pipeline (M09), il tipo di risultato principale è
> ora `PipelineRunResult` e i tipi `SinglePassRunResult` e `MultiRoundRunResult`
> sono deprecati. Vedere `09-multi-round-design.md` per i dettagli.

## Scopo

Definire i contratti dati minimi per configurazione risolta, policy, capability,
risultati, stati e metadata della pipeline. Questo documento definisce confini
verificabili; non impone ancora una libreria, nomi definitivi di classi o schema
JSON definitivo.

## Riferimenti alle specifiche

- Sezioni 5.1, 7, 10, 11, 13, 14, 15, 17, 18 e 19.
- `docs/implementation/00-implementation-overview.md`.

## Principio di tassonomia

La configurazione deve distinguere tre concetti:

| Categoria | Ruolo | Esempi |
|---|---|---|
| Configurazione di run risolta | Richiesta validata e serializzata | Budget, seed, cap, lambda, solver richiesto |
| Policy e provenance | Decisioni esterne applicate senza adattamento implicito | ID, versione, hash, selection status |
| Capability runtime | Cio` che un adapter/backend puo` realmente fare | Forme supportate, solver disponibile, seed supportato |

Una capability non cambia la configurazione richiesta. Se una richiesta e` incompatibile con capability o ambiente, il run deve fallire esplicitamente.

## Contratti minimi da introdurre

L'implementazione dovra` fornire tipi serializzabili equivalenti ai seguenti gruppi, anche se la loro organizzazione Python puo` evolvere:

```text
ResolvedRunConfig
ReductionPolicy
MISExecutionOptions
ClassicalSolveOptions
RunIdentity
PolicyProvenance
RuntimeCapabilities
RunResult
RoundResult
```

I contratti devono rendere possibili validazione prima dell'esecuzione, serializzazione della configurazione effettiva e test indipendenti dal dominio.

## Configurazione corrente

La configurazione risolta deve poter rappresentare almeno i campi normativi:

```text
max_reduction_rounds
candidate_domain_min_items
candidate_domain_max_items
num_source_mis_candidates
min_reduction_ratio
target_binary_variables
max_end_to_end_runtime_seconds

lambda_edge or lambda_edge_policy
allow_noncertifying_penalty
mis_solver_id
provider/backend/device details, resolved from the selected solver capability
mis_backend_family
execution_mode
fallback_policy
requested_solution_count
random_seed
max_distinct_samples
repair_enabled
repair_max_iterations
minimum_candidate_jaccard_distance
exact_solver_max_variables

classical_solver_id
time_limit_seconds
mip_gap_tolerance
threads
model_export_enabled
primal_feasibility_tolerance
integrality_tolerance
objective_recomputation_absolute_tolerance
objective_recomputation_relative_tolerance
postcheck_mode
```

I valori iniziali, i default concreti e il canale di caricamento della configurazione sono dettagli implementativi futuri. Non devono essere introdotti in modo implicito in orchestratori, adapter o test.

## Matrice requisiti -> configurazione M02

La tabella separa i campi gia` rappresentati nella configurazione risolta dai
campi normativi che richiedono una decisione di policy o una semantica
multi-round. "Non rappresentato" non significa che il requisito sia ignorato:
significa che non e` consentito introdurre un default implicito prima della
milestone che lo rende eseguibile.

| Requisito | Stato | Implementazione verificata | Test/evidenza | Decisione o milestone successiva |
|---|---|---|---|---|
| 13, 16.2: conteggi logici originali e residui | Coperto nel single-pass | `LogicalVariableCounts`, metodo obbligatorio adapter e campi del risultato | `tests/domains/test_logical_variable_counts.py`, test portfolio e runner | Distinti dai conteggi fisici solver; adapter esterni da aggiornare |
| 18: cap, minimo dominio, numero candidate, ratio minima, target binarie, budget E2E | Coperto come contratto | `ReductionPolicy` in `src/qreduce/models.py`; validazione in `src/qreduce/config.py` | `tests/test_config.py` valida bounds, tipi, range e budget | `min_reduction_ratio` e `target_binary_variables` diventano stop criteria solo con M08 multi-round |
| 18: protezioni `mandatory`, `user_locked`, `safe_retained`, `incumbent_supported` | Coperto nel contratto adapter, non nella run config | `ProtectionDeclaration` in `src/qreduce/domains/contracts.py` | `tests/domains/test_protection_declaration.py` | La sorgente delle protezioni e` l'adapter per round; non e` definito un override config che possa disabilitare una protezione mandatory |
| 8.3, 18: `incumbent_protection_mode` | Coperto nella dichiarazione adapter | `ProtectionDeclaration.incumbent_protection_mode` (`required` o `best_effort`) | `tests/domains/test_protection_declaration.py`; `tests/pipeline/test_single_pass_selection.py` | Se M08 richiedera` un override di run, deve definire precedenza fra adapter, policy e incumbent |
| 9.5, 18: `on_candidate_domain_too_small` | Non rappresentato | Single-pass applica il comportamento effettivo `fail` | `tests/experiments/test_portfolio_single_pass.py` verifica `candidate_domain_too_small` prima del fixing | M08: definire/implementare `retain_more_ranked_items_before_fixing` da `P_t`, con artifact per tentativo |
| 9.5, 18: `on_reduced_problem_infeasible` | Non rappresentato | Single-pass termina sulla failure classica/infeasibility senza recovery implicito | Test backend/classical e risultati single-pass | M08: definire/implementare `retry_with_larger_domain_from_same_round` da `P_t` |
| 9.5, 18: `max_recovery_attempts` | Non rappresentato | Nessun recovery e nessun rollback nel single-pass | Invariante documentata; nessun codice di riattivazione | M08: introdurre insieme alle due policy di recovery, non prima |
| 17, 18: `run_id`, config immutabile e `resolved_config_hash` | Coperto | `RunIdentity`, `ResolvedRunConfig.config_hash()` e `RunResult.config_hash` | `tests/test_config.py`; artifact test in `tests/experiments/test_runner.py` | Nessuna |
| 16.3, 18, 20.8: provenance policy esterna | Coperto | `PolicyProvenance` e serializzazione canonica di `ResolvedRunConfig` | `tests/test_config.py`; artifact runner | Nessuna; il kernel conserva i metadata senza interpretarli |
| 17: `input_hash` del problema opaco | Non rappresentato | Il campo esiste in `RunResult`, ma il kernel non calcola hash di oggetti adapter-owned | Verificato nei risultati serializzati come `null` quando assente | Definire un contratto adapter per una rappresentazione input canonica/redatta prima di valorizzarlo |

### Vincoli di progettazione emersi

- Le protezioni mandatory/user-locked/safe non possono essere disattivate da un
  flag generico di configurazione: contraddirebbe la loro semantica e
  introdurrebbe una precedenza non definita dalle specifiche.
- Le policy di recovery non sono semplici enum di configurazione: richiedono la
  ricostruzione da `P_t`, contatori di tentativo e artifact distinti. Rimangono
  quindi bloccate a M08.
- `min_reduction_ratio` e `target_binary_variables` sono gia` parte del
  contratto validato, ma la loro applicazione come stop criterion richiede il
  loop iterativo; il single-pass non deve reinterpretarli come failure policy.

## Invarianti di validazione iniziali

- La configurazione richiesta non puo` essere modificata durante un run.
- `fallback_policy = fail` e` l'unico comportamento supportato.
- `max_reduction_rounds = 1` e` la configurazione supportata dalla pipeline single-pass; il contratto puo` contenere il campo multi-round.
- Un timeout effettivo non puo` superare il budget end-to-end residuo.
- Una policy MWIS standard richiede `lambda_edge > max_i(w_i)` per il grafo del round, salvo esplicita policy non certificante consentita dalle specifiche.
- Gli ID pubblici `mis_solver_id` e `classical_solver_id` sono risolti dai
  cataloghi built-in QReduce; una registry passata esplicitamente puo` estendere
  il catalogo. ID sconosciuti sono errori di configurazione e non attivano
  fallback.
- I parametri specifici di un backend sono validi soltanto se la capability dell'implementazione selezionata li dichiara supportati.

## Stati, failure e adozione

L'implementazione deve usare valori normalizzati compatibili con la sezione 19 delle specifiche, distinguendo almeno:

```text
run_status
stage
terminal_reason
classical_solver_status
postcheck_status
adoption_status
```

Le eccezioni Python possono essere usate internamente, ma non devono sostituire il risultato terminale serializzabile. Failure, artefatti parziali e motivo normalizzato devono rimanere osservabili.

### Evidenza single-pass corrente

Il contratto `ProtectionDeclaration` consente all'adapter di dichiarare, una
sola volta per round, gli item `mandatory`, `user_locked`, `safe_retained` e
`incumbent_supported`. I primi tre hanno precedenza obbligatoria sul cap; gli
incumbent usano `incumbent_protection_mode = required | best_effort`. Per
compatibilita` con gli adapter single-pass gia` esistenti, una tupla legacy
restituita da `declare_protected_items` e` interpretata come protezione
`mandatory`.

`SinglePassRunResult` serializza inoltre `candidate_records`,
`candidate_domain_item_records` e la `protection_declaration` effettiva. I
record conservano, entro lo stage raggiunto, l'esito di deduplicazione, repair,
ranking/diversita` e la decisione per item del candidate domain. Questa evidenza
non introduce rollback o recovery e non completa ancora il contratto multi-round.

## Identita`, hash e artifact

Ogni run deve avere un `run_id` immutabile e una configurazione risolta serializzata. `RunIdentity` appartiene al kernel in memoria; schema, versione del producer, timestamp, hash dei file e redazione appartengono al runner interno `qreduce.experiments`. Il meccanismo deve:

- produrre JSON canonico o un equivalente deterministico per il calcolo hash;
- distinguere `config_hash`, `input_hash` e `policy_hash` quando applicabili;
- non serializzare credenziali, token, segreti o dati personali;
- associare `schema_version`, `producer_version`, `run_id` e `created_at` agli artifact strutturati richiesti dalle specifiche.

## Moduli Python indicativi

```text
src/qreduce/config.py
src/qreduce/models.py
src/qreduce/status.py
src/qreduce/capabilities.py
src/qreduce/solving/mwis/registry.py
src/qreduce/solving/residual/registry.py
src/qreduce/artifacts/metadata.py
src/qreduce/experiments/
```

Questa struttura e` una proposta iniziale, non un'API pubblica congelata.

## Test minimi

- Configurazioni invalide producono reason compatibili con `invalid_configuration`.
- Parametri non supportati da una capability sono rifiutati prima della compilation.
- Metadata policy sono preservati senza modificarne il significato.
- Budget residuo non positivo impedisce l'invocazione del backend.
- Stato, failure reason e adozione non vengono confusi in un singolo booleano.
- La serializzazione redige esplicitamente i campi segreti, se introdotti.
- Le categorie di protezione non possono sovrapporsi; gli incumbent
  `best_effort` esclusi dal cap mantengono un reason code serializzato.
- Candidate selezionate, repair falliti, duplicati oltre il cap e scarti del
  filtro di diversita` rimangono osservabili nel risultato in memoria.

## Criteri di completamento

- Esiste una configurazione risolta, immutabile durante il run e serializzabile.
- Core, adapter di dominio e backend condividono contratti senza dipendere da oggetti CPLEX o provider MIS.
- La validazione delle capability avviene prima di compilation ed esecuzione.
- Stati e failure richiesti possono essere emessi in modo uniforme dalla pipeline.

## Stato della verifica

**Stato: Completata.** La verifica del 2026-11-12 ha confermato che tutti i
criteri di completamento sono soddisfatti per il perimetro single-pass.

### Criteri soddisfatti

| Criterio | Evidenza |
|---|---|
| Configurazione risolta, immutabile e serializzabile | `ResolvedRunConfig` in `src/qreduce/models.py`; `config_hash()`, `to_canonical_json()`; test in `tests/test_config.py` |
| Contratti condivisi senza dipendenze CPLEX/provider MIS | `ReducibleProblemAdapter`, `LogicalVariableCounts`, `ProtectionDeclaration`, `FixingManifest`, `DomainEvaluationMetric` in `src/qreduce/domains/contracts.py`; nessun import di SDK nei contratti |
| Validazione capability prima di compilation/esecuzione | `validate_backend_compatibility` in `src/qreduce/capabilities.py`; gate nella pipeline single-pass; test in `tests/test_capabilities.py` e `tests/solving/mwis/test_pipeline_capability_gate.py` |
| Stati e failure emessi uniformemente | `RunStatus`, `TerminalReason`, `ClassicalSolverStatus`, `PostcheckStatus`, `AdoptionStatus` in `src/qreduce/status.py`; invarianti in `RunResult.__post_init__`; test in `tests/test_config.py` |

### Requisiti esplicitamente esclusi dal perimetro M02

I seguenti requisiti delle specifiche sono documentati come **bloccati a M08**
perche' richiedono semantica multi-round che il single-pass non puo` fornire:

- `on_candidate_domain_too_small` (policy di recovery)
- `on_reduced_problem_infeasible` (policy di recovery)
- `max_recovery_attempts` (contatore di recovery)

Questa esclusione e` una decisione di progetto esplicita, non un gap da colmare
in M02. Il single-pass applica il comportamento `fail` senza recovery implicito.