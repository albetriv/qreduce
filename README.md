# QReduce

QReduce e` un framework per ridurre il dominio combinatorio di grandi problemi di ottimizzazione mista prima del solve classico del problema residuo.

Il framework usa **Maximum Weight Independent Set (MWIS)** per proporre un insieme piu` piccolo di decisioni binarie ancora disponibili. La proposta non sostituisce il problema originale: le decisioni escluse vengono fissate esplicitamente e il modello residuo, con obiettivo e vincoli hard originali, viene risolto da un backend classico.

> **Stato del repository**: il progetto e` attualmente in fase di specifica e progettazione. Non sono ancora presenti un pacchetto installabile, un'implementazione eseguibile, dipendenze dichiarate o comandi di esecuzione supportati.

## Flusso di alto livello

```text
problema MIP/MIQP/MIQCP originale
  -> grafo di conflitto o ridondanza tra decisioni binarie
  -> problema MWIS canonico: grafo, QUBO e/o BQM/Ising
  -> compilation per il backend MIS configurato
  -> esecuzione su solver locale, simulatore, QPU o backend hybrid
  -> normalizzazione, validazione e repair delle sample binarie
  -> costruzione del candidate domain ridotto
  -> fixing esplicito delle decisioni escluse
  -> solve classico del problema residuo
  -> post-check indipendente della soluzione finale
```

## Principi chiave

- **MIS come riduzione, non come soluzione finale**: un insieme indipendente propone quali decisioni trattenere; non certifica da solo una soluzione del problema originale.
- **Vincoli hard conservati**: il solver classico residuo mantiene l'obiettivo e tutti i vincoli applicabili del modello originale.
- **Fixing esplicito e auditabile**: ogni decisione esclusa e` fissata, tracciata in un fixing manifest e classificata come euristica, sicura o imposta dall'utente.
- **Post-check obbligatorio**: una soluzione non puo` essere adottata se non rispetta i fixing e i vincoli originali verificati dall'adapter di dominio.
- **Riproducibilita`**: configurazioni risolte, policy, seed, metriche, risultati intermedi e failure devono essere serializzati come artifact.

## Backend MIS indipendenti dal provider

QReduce non e` legato a un QPU, simulatore o SDK specifico. Il kernel costruisce una rappresentazione canonica del problema MWIS e delega compilation ed esecuzione a un adapter selezionato dalla configurazione.

Le famiglie di backend previste includono:

| Famiglia | Esempi possibili | Rappresentazione o fase tipica |
|---|---|---|
| Solver classico locale | exact solver, simulated annealing, euristiche | grafo MIS, QUBO o BQM |
| Annealing | D-Wave Ocean, Leap Hybrid, QPU D-Wave | BQM/QUBO, embedding se necessario |
| Gate-based | IBM Qiskit/IBM Quantum, AWS Braket | Ising/Hamiltoniana, circuiti e bitstring |
| Neutral-atom | Pasqal/Pulser | grafo MIS o Ising, mapping geometrico e sequenza fisica |
| Hybrid | servizi o workflow quantum-classical | formato dichiarato dall'adapter |

Un adapter dichiara le proprie capability: forme di problema supportate, esecuzione locale o remota, supporto per QPU, seed, `num_reads`, shots, compilation, embedding, transpilation, mapping geometrico e limiti di risorse.

La configurazione deve rifiutare esplicitamente una richiesta incompatibile. Non sono ammessi fallback silenziosi, ad esempio da QPU remota a simulatore locale o da un provider a un altro.

## Architettura concettuale

```text
ReducibleProblemAdapter
  -> ReductionGraph
  -> CanonicalMISProblem
  -> MISExecutionAdapter.compile(...)
  -> CompiledMISJob
  -> MISExecutionAdapter.solve(...)
  -> RawMISSample normalizzate
  -> candidate domain e fixing manifest
  -> ClassicalBackend.solve(...)
  -> post-check dell'adapter di dominio
```

I ruoli principali sono:

- `ReducibleProblemAdapter`: identifica le decisioni riducibili, costruisce il grafo, applica il fixing e valida la soluzione rispetto al problema originale.
- `MISExecutionAdapter`: dichiara capability, compila il problema MWIS verso un target concreto ed esegue il job.
- `ClassicalBackend`: risolve il problema residuo con un solver classico, ad esempio SCIP o CPLEX.

## Garanzie e limiti

La formulazione QUBO standard del MWIS usa una penalita` sugli archi che, se configurata con `lambda_edge > max_i(w_i)`, garantisce che ogni minimizzatore globale della QUBO sia un insieme indipendente. Questa proprieta` riguarda il sottoproblema MWIS, non l'ottimalita` del problema originale.

Quando la riduzione esclude decisioni per ragioni euristiche, anche un solve ottimo del problema residuo **non** certifica l'ottimalita` globale del problema originario. QReduce distingue quindi in modo esplicito:

```text
fixing origin:    mis_heuristic | certified_rule | user_mandated
guarantee level:  heuristic | safe | user_imposed
```

## Documentazione

La specifica normativa del framework e` disponibile in:

- [`docs/specifications.md`](docs/specifications.md)

Il documento definisce, tra gli altri aspetti:

- classe di problemi supportata;
- formulazione MWIS/QUBO/BQM/Ising;
- pipeline single-pass e iterativa;
- contratti per adapter di dominio, backend MIS e backend classici;
- capability e normalizzazione di backend eterogenei;
- repair, ranking, candidate domain e fixing;
- artifact, riproducibilita`, configurazione e failure reason;
- requisiti di test e criteri di accettazione della prima versione.

## Roadmap della prima versione

La prima versione prevista include almeno:

1. un adapter dimostrativo per un problema MIQP o MIQCP;
2. il flusso completo `graph -> MIS -> candidate domain -> residual solve -> post-check`;
3. una rappresentazione MWIS canonica e contratti provider-agnostic;
4. un backend MIS locale concreto e un exact solver diagnostico per piccole istanze;
5. almeno un backend classico operativo tra SCIP e CPLEX;
6. artifact completi per grafo, compilation/esecuzione MIS, fixing, solve classico e post-check.

Adapter per D-Wave, IBM Quantum/Qiskit, AWS Braket e Pasqal/Pulser possono essere implementati progressivamente senza modificare il kernel del framework.

## Contributi

Prima di implementare componenti o proporre modifiche architetturali, verificare l'allineamento con `docs/specifications.md`. In particolare, le implementazioni devono:

- evitare dipendenze dirette del kernel da SDK di provider specifici;
- dichiarare e validare capability, parametri e limiti del backend;
- mantenere auditabili compilation, esecuzione, mapping, embedding e risultati normalizzati;
- non introdurre fallback impliciti;
- preservare la separazione tra selezione MIS e solve classico del problema originale.