# 04 - MWIS execution backends and adapter contracts

## Scopo

Definire il contratto provider-agnostic per compilation ed esecuzione del problema MWIS e implementare i backend locali concreti. Il termine MWIS identifica il problema di riduzione, non la tecnologia del backend: un backend MWIS puo` essere classico, come `local_greedy`, oppure un simulatore o un adapter quantistico. I backend devono restituire sample binarie auditabili senza rendere il kernel dipendente da SDK, QPU o formato di job specifico.

## Riferimenti alle specifiche

- Sezioni 3.1, 7, 11, 12, 17, 18, 19 e 20.2.
- `docs/implementation/02-core-domain-models-and-configuration.md`.
- `docs/implementation/03-canonical-mwis-graph-and-qubo.md`.

## Stato dell'audit

**Stato: Completata.** L'audit del 2026-11-11 ha verificato i contratti
provider-agnostic, il catalogo esplicito, il gate di capability prima della
compilation, il clamping dei timeout, i backend `local_greedy` e
`dwave_simulated_annealing`, oltre a normalizzazione, deduplicazione e
redazione dei metadata. I timeout di fase sono applicati solo dagli adapter
che li dichiarano supportati: `local_greedy` segnala la compilation o
l'execution time-limited, mentre il simulatore Ocean rifiuta una richiesta di
limite temporale prima della compilation. L'audit M03 del 2026-11-11 ha inoltre
confermato il solver exact diagnostico bounded e il suo rifiuto esplicito oltre
`exact_solver_max_variables`, chiudendo la dipendenza indicata da questa
milestone.

### Matrice di conformita'

| Requisito | Implementazione | Evidenza riproducibile | Esito |
|---|---|---|---|
| Separazione `capabilities` / `compile` / `solve` e contratti serializzabili (11.2, 11.6) | `contracts.py`, `compilation.py` | `tests/solving/mwis/test_contracts.py` | Conforme |
| Backend richiesto ed effettivo, famiglia, modalita', capability e failure normalizzate (11.2, 11.6, 20.2) | `CompiledMISJob`, `MISCompilationResult`, `MISBackendResult`, `RuntimeCapabilities` | `tests/solving/mwis/test_contracts.py`, `tests/test_capabilities.py` | Conforme |
| Registry deterministica, ID ignoto senza fallback e failure della factory non mascherata (11.5, 11.6) | `registry.py` | `tests/solving/mwis/test_mis_solver_registry.py` | Conforme |
| Disponibilita' SDK lazy e assenza di import del provider dal kernel (11.1, 11.5, 20.2) | `dwave_simulated_annealing_backend.py`, `registry.py` | `tests/solving/mwis/test_dwave_simulated_annealing_backend.py`, `tests/test_runtime_independence.py` | Conforme |
| Capability incompatibile rifiutata prima della compilation (11.3, 20.2) | `capabilities.py`, `single_pass.py` | `tests/test_capabilities.py`, `tests/solving/mwis/test_pipeline_capability_gate.py` | Conforme |
| Timeout di compilation ed execution limitati al minimo tra limite di fase e budget end-to-end; richieste rifiutate se il backend non li supporta (11.3, 11.6) | `config.effective_timeout`, `capabilities.py`, `single_pass.py` | `tests/test_config.py`, `tests/test_capabilities.py`, `tests/solving/mwis/test_pipeline_capability_gate.py` | Conforme |
| `local_greedy`: seed, ordine canonico, sample binarie, timeout esplicito di compilation/execution e nessuna certificazione di ottimalita' (11.5, 20.2) | `local_backend.py` | `tests/experiments/test_local_greedy_mis.py` | Conforme |
| D-Wave Ocean locale: traduzione QUBO/BQM, decoding nel `node_order`, rifiuto di label mancanti/extra o valori non binari, parametri dichiarati e SDK assente esplicito (11.1, 11.2, 20.3) | `dwave_simulated_annealing_backend.py` | `tests/solving/mwis/test_dwave_simulated_annealing_backend.py`; test integrazione opzionale in `tests/experiments/test_portfolio_single_pass.py` | Conforme |
| Normalizzazione: validazione binaria e `node_order`, ricalcolo QUBO/Ising e validita' strutturale, score nativo non reinterpretato (11.4, 20.2) | `normalization.py` | `tests/solving/mwis/test_normalization.py` | Conforme |
| Deduplicazione stabile, occurrence aggregata e cap deterministico (12, 20.2) | `normalization.py` | `tests/solving/mwis/test_normalization.py` | Conforme |
| Sample provenance e metadata redatti, incluso il solo flag booleano di capability `required_credentials` senza bypass per valori sensibili (11.4, 20.2) | `contracts.py`, `artifacts/metadata.py`, backend locali | `tests/solving/mwis/test_contracts.py`, `tests/solving/mwis/test_dwave_simulated_annealing_backend.py`, `tests/artifacts/test_metadata.py` | Conforme |
| Exact MIS/QUBO diagnostico con rifiuto oltre soglia (11.5, 20.2) | `mwis/exact.py` | Audit e certificazione assegnati a M03 | Dipendenza non verificata |

Gli adapter gate-based, remote, neutral-atom, embedding e mapping geometrico
non sono implementati in M04. I loro requisiti restano condizionali: se un
adapter viene aggiunto, deve rispettare gli stessi contratti e produrre reason
esplicite per capability, mapping o runtime indisponibili.

## Contratto MIS minimo

L'API concreta puo` evolvere, ma deve mantenere la separazione funzionale:

```text
capabilities()
compile(canonical_problem, compilation_request)
solve(compiled_job, execution_request)
```

La separazione tra compilation ed esecuzione e` obbligatoria anche quando il backend locale le realizza internamente nella stessa operazione. Devono rimanere auditabili tempi, parametri effettivi, forma compilata, stato di completion e failure reason.

## Capability richieste

Ogni adapter deve dichiarare almeno:

- provider e backend identifier;
- backend family;
- execution location locale o remota;
- forme supportate tra `mis_graph`, `qubo`, `bqm` e `ising`;
- supporto seed, solution count e limite dimensionale;
- parametri supportati e parametri rifiutati;
- requisiti di SDK, credenziali, device o mapping;
- disponibilita` runtime effettiva.

Il framework usa `fallback_policy = fail`. Il framework non puo` sostituire silenziosamente backend, provider, device, modalita` o algoritmo.

## Solver MWIS built-in e registry di estensione

QReduce include `local_greedy` e `dwave_simulated_annealing` nel catalogo MIS
standard. Il chiamante seleziona uno dei due ID nella configurazione e la pipeline
costruisce il backend tramite la factory built-in. Il secondo usa il simulatore
locale Ocean `dwave.samplers.SimulatedAnnealingSampler` sulla rappresentazione
QUBO, supporta `num_reads`, `num_sweeps`, `beta_range` e `beta_schedule_type` in
`provider_parameters`, e richiede lazy `dimod` + `dwave-samplers`. Non usa Leap,
QPU, credenziali o embedding. Le `MISSolverRegistry` possono estendere il catalogo
in modo esplicito, ma nessun ID non noto puo` attivare un fallback.

Ogni backend deve:

- essere operativo senza provider remoto;
- rispettare il contratto capability/compile/solve;
- accettare una rappresentazione canonica dichiarata;
- restituire zero, una o piu` sample binarie nel `node_order` canonico;
- registrare seed, runtime, parametri effettivi e completion status;
- non dichiarare automaticamente che una sample sia un optimum MWIS;
- produrre failure normalizzata se non puo` eseguire la richiesta.

L'exact solver della task 03 resta separato: e` uno strumento diagnostico sotto soglia, non il backend locale operativo.

## Normalizzazione delle sample

Ogni esito deve diventare un `RawMISSample` equivalente con:

```text
stable raw_sample_id
node_order
delta vector in {0, 1}
provider/native metadata, redacted when necessary
native score or energy, if supplied
source execution metadata
```

Il framework deve poi deduplicare per vettore `delta`, validare l'independent set e ricalcolare, quando possibile, energia QUBO e peso di selezione. Uno score nativo non e` automaticamente un'energia QUBO.

## Parametri condizionali

Campi come `num_reads`, `shots`, `embedding_policy`, `transpiler_options` o parametri di emulatori non appartengono al contratto comune di ogni backend. Possono essere presenti nella configurazione, ma sono validi soltanto quando dichiarati supportati dall'adapter selezionato.

## Moduli Python indicativi

```text
src/qreduce/solving/mwis/contracts.py
src/qreduce/capabilities.py
src/qreduce/solving/mwis/local_backend.py
src/qreduce/solving/mwis/dwave_simulated_annealing_backend.py
src/qreduce/solving/mwis/registry.py
src/qreduce/solving/mwis/normalization.py
src/qreduce/solving/mwis/compilation.py
```

Questi nomi non fissano l'API pubblica finale.

## Test minimi

- Capability incompatibile rifiutata prima della compilation.
- Backend locale restituisce `delta` binarie nel node order dichiarato.
- Piu` sample distinte sono normalizzate senza assumerne l'ottimalita`.
- Sample duplicate sono aggregate deterministicamente.
- Parametri non supportati producono failure esplicita.
- SDK/provider dichiarato ma indisponibile produce reason normalizzata.
- Metadata non contengono segreti e distinguono backend richiesto da effettivo.
- Exact solver sopra soglia produce rejection esplicita.

## Criteri di completamento

- La pipeline usa il backend associato all'ID built-in configurato, oppure un ID
  presente in una registry di estensione esplicitamente passata.
- Il core non importa classi di provider o formati runtime proprietari.
- Compilation, execution e normalizzazione sono osservabili separatamente.
- Ogni cambio di backend o modalita` richiede una configurazione esplicita.
- L'exact solver diagnostico di M03 resta confinato a test e diagnostica bounded;
  la sua verifica e il rifiuto oltre soglia sono coperti da `tests/mwis/`.