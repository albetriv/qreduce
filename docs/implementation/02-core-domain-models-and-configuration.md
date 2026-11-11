# 02 - Core domain models and configuration

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
src/qreduce/mis/registry.py
src/qreduce/classical/registry.py
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

## Criteri di completamento

- Esiste una configurazione risolta, immutabile durante il run e serializzabile.
- Core, adapter di dominio e backend condividono contratti senza dipendere da oggetti CPLEX o provider MIS.
- La validazione delle capability avviene prima di compilation ed esecuzione.
- Stati e failure richiesti possono essere emessi in modo uniforme dalla pipeline.