# QReduce

QReduce e` un framework per ridurre il dominio combinatorio di grandi problemi di ottimizzazione mista prima del solve classico del problema residuo.

Usa **Maximum Weight Independent Set (MWIS)** per selezionare un sottoinsieme di decisioni binarie da mantenere attive. Le decisioni escluse vengono fissate esplicitamente; obiettivo e vincoli hard del problema originale restano responsabilita` del solver classico.

> **Stato**: e` disponibile una pipeline single-pass domain- e solver-agnostica, con risultato auditabile in memoria. Il repository include un esperimento sintetico di portfolio persistito, non distribuito con la libreria. Recovery e multi-round non sono inclusi.

## Sviluppo

Il progetto usa [Poetry](https://python-poetry.org/) e adotta un layout `src/`.
La compatibilita` tecnica supportata e` Python `>=3.12,<3.13`; il valore in
`pyproject.toml` e` la fonte autorevole.

```powershell
poetry lock
poetry install
poetry run pytest
poetry run ruff check .
```

I backend built-in opzionali usano binding runtime-specifici. Per installare
CPLEX, PySCIPOpt e il simulatore locale D-Wave Ocean per gli esperimenti o per
l'esecuzione dei backend corrispondenti:

```powershell
poetry install --with experiments
```

`poetry lock` risolve le dipendenze e crea o rigenera il file `poetry.lock`, che
e` versionato. `poetry install` crea o riusa l'ambiente virtuale e installa il
package in modalita` editable insieme alle dipendenze gia` risolte.

Le dipendenze core restano provider-agnostic. I binding Python `cplex`,
`pyscipopt`, `dimod` e `dwave-samplers` sono opzionali e vengono importati lazy
dai backend QReduce; `import qreduce` non li carica. Se il binding, il runtime o
una licenza richiesta non sono disponibili, QReduce produce una failure esplicita
e non seleziona automaticamente un'alternativa.

## Selezione dei solver

L'applicazione seleziona i solver tramite ID pubblici e serializzabili. La pipeline
risolve automaticamente gli ID forniti da QReduce; non richiede registry popolati
dal chiamante per usare i backend standard.

```text
mis_solver_id = "local_greedy"
# oppure: mis_solver_id = "dwave_simulated_annealing"
classical_solver_id = "cplex"
# oppure: classical_solver_id = "scip"
```

Il catalogo iniziale QReduce contiene `local_greedy` e
`dwave_simulated_annealing` per MWIS, oltre a `cplex` e `scip` per il solve
classico residuo. `dwave_simulated_annealing` usa il simulatore locale Ocean
`dwave.samplers.SimulatedAnnealingSampler` sul QUBO canonico; richiede le
dipendenze opzionali `dimod` e `dwave-samplers`, non credenziali Leap, QPU o
embedding. Puoi impostare `num_reads`, `num_sweeps`, `beta_range` e
`beta_schedule_type` in `mis_execution.provider_parameters`. Un ID sconosciuto
e` un errore esplicito di configurazione; un ID noto con binding, runtime o
licenza non disponibile produce un failure esplicito del backend. Non e` previsto
fallback silenzioso. Le registry restano disponibili soltanto come estensione
esplicita per backend applicativi.

Per installare i binding opzionali dei solver inclusi nel repository:

```bash
poetry install --with experiments
```

## Policy e valutazione esterna

QReduce esegue policy graph/MIS/riduzione fornite dall'applicazione chiamante e ne registra configurazione, provenance ed esiti. Non include un workflow di calibrazione, benchmark o selezione automatica della policy: riferimenti classici, metriche di qualita`, soglie e separazione fra tuning e valutazione finale restano responsabilita` dell'applicazione o dell'adapter di dominio.

## Integrazione concettuale

```text
applicazione esterna
  -> problema originale + policy esplicita
  -> adapter di dominio + solver ID configurati
  -> QReduce
  -> candidate domain + fixing manifest + solve residuo + post-check
  -> decisione dell'applicazione
```

L'applicazione mantiene la responsabilita` del modello di dominio, della scelta della policy, delle metriche di qualita` e dell'adozione del risultato. QReduce gestisce la riduzione e restituisce un risultato auditabile in memoria senza scrivere file. Il runner interno `qreduce.experiments` persiste invece ogni esperimento completato per l'analisi successiva; non e` incluso nella distribuzione della libreria. La descrizione completa del flusso e dei confini di responsabilita` e` nella sezione 5.1 delle specifiche.

## Flusso

```text
problema MIP/MIQP/MIQCP
  -> grafo di conflitto/ridondanza
  -> MWIS canonico: grafo, QUBO e/o BQM/Ising
  -> compilation ed esecuzione del MIS solver
  -> validazione, repair e candidate domain
  -> fixing delle decisioni escluse
  -> solve classico del problema residuo
  -> post-check della soluzione finale
```

## Backend indipendenti dal provider

Il kernel e` indipendente da QPU, simulatore e SDK specifici. Un adapter compila ed esegue il problema MWIS sul backend configurato, che puo` essere un solver locale, un simulatore o una QPU annealing, gate-based, neutral-atom o hybrid.

Esempi di adapter previsti: D-Wave, IBM Qiskit/Quantum, AWS Braket e Pasqal/Pulser. Nessun provider e` richiesto dal kernel e non sono ammessi fallback silenziosi fra backend o modalita` di esecuzione.

## Garanzie

- MWIS propone una riduzione del dominio; non e` la soluzione finale del problema originale.
- Un fixing derivato euristicamente non certifica l'ottimalita` globale dell'originale.
- Ogni soluzione residua deve superare un post-check rispetto ai fixing e ai vincoli del problema originale.
- Configuration, risultati intermedi, failure e provenance del backend sono disponibili nel risultato in memoria; il runner interno del repository li serializza per gli esperimenti.

## Esperimenti interni e notebook

Il runner interno salva sempre gli artifact sotto:

```text
outputs/{experiment_id}/{run_id}/
```

Un esperimento interno disponibile e` il portfolio sintetico single-pass. Per
produrre un run da analizzare:

```bash
poetry run python -m qreduce.experiments.portfolio --run-id run-001
```

Il notebook corrispondente e`
`notebooks/experiments/01_synthetic_portfolio_single_pass.ipynb` e carica
`outputs/synthetic-portfolio-single-pass/run-001/`.

Un run QReduce con esito normalizzato `failed` viene comunque salvato: e` un risultato analizzabile, non un fallimento della serializzazione. Se invece la scrittura degli artifact non riesce, il runner fallisce e non pubblica una directory finale incompleta.

I notebook in `notebooks/experiments/` devono caricare i dati gia` prodotti dal filesystem tramite `qreduce.experiments.load_experiment_run`; non devono chiamare `run_single_pass`.

## Documentazione

### Notebook di visualizzazione

I notebook in `notebooks/tasks/` sono esempi didattici sintetici in memoria: grafo
MWIS ed equivalenza QUBO/Ising. La logica degli esempi risiede in
`src/qreduce/notebook_examples.py`; questi notebook non esportano artifact e non
sono benchmark o raccomandazioni di policy. I notebook in `notebooks/experiments/`
sono invece dedicati all'analisi degli artifact gia` prodotti.
I grafici di riduzione mostrano nodi, pesi e archi con un layout circolare
illustrativo, non coordinate geometriche del problema. Nell'esperimento portfolio
sintetico il caso usa cinque asset; la matrice delle correlazioni evidenzia gli
archi generati dalla soglia assoluta. Nel grafo del risultato il colore
evidenzia il dominio mantenuto, non la selezione finale. Gli archi non sono
vincoli hard del problema originale.

```bash
poetry install --with notebooks
poetry run jupyter lab
```
Per eseguire il runner portfolio con un solve classico reale, installare inoltre
`poetry install --with notebooks,experiments` e configurare `cplex` o `scip`.
CPLEX richiede una licenza utilizzabile; SCIP usa il binding PySCIPOpt. In assenza
del binding selezionato il runner salva la failure effettiva e gli eventuali
risultati intermedi, senza sostituire il solver. Le selezioni MWIS non sono la
soluzione finale e non certificano l'ottimo del problema originale.

La specifica completa e normativa e` disponibile in [`docs/specifications.md`](./docs/specifications.md).
