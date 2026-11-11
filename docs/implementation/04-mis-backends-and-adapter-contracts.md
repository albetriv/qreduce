# 04 - MIS backends and adapter contracts

## Scopo

Definire il contratto provider-agnostic per compilation ed esecuzione MIS e implementare il solver locale concreto. Il solver locale deve restituire sample binarie auditabili, senza rendere il kernel dipendente da SDK, QPU o formato di job specifico.

## Riferimenti alle specifiche

- Sezioni 3.1, 7, 11, 12, 17, 18, 19 e 20.2.
- `docs/implementation/02-core-domain-models-and-configuration.md`.
- `docs/implementation/03-canonical-mwis-graph-and-qubo.md`.

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

## Solver built-in e registry di estensione

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
src/qreduce/mis/contracts.py
src/qreduce/mis/capabilities.py
src/qreduce/mis/local_backend.py
src/qreduce/mis/dwave_simulated_annealing_backend.py
src/qreduce/mis/registry.py
src/qreduce/mis/normalization.py
src/qreduce/mis/compilation.py
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