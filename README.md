# QReduce

QReduce e` un framework per ridurre il dominio combinatorio di grandi problemi di ottimizzazione mista prima del solve classico del problema residuo.

Usa **Maximum Weight Independent Set (MWIS)** per selezionare un sottoinsieme di decisioni binarie da mantenere attive. Le decisioni escluse vengono fissate esplicitamente; obiettivo e vincoli hard del problema originale restano responsabilita` del solver classico.

La QUBO MWIS e` un problema ausiliario di riduzione: i suoi termini quadratici
non vengono sommati all'obiettivo di dominio. Il contratto residuale corrente
rappresenta MILP e MIQP con vincoli lineari, quindi l'obiettivo originale puo`
essere lineare o quadratico; vincoli quadratici, conici, indicatori o non
lineari richiedono una riformulazione oppure un'estensione esplicita.

> **Stato sintetico**: il repository contiene un nucleo single-pass utilizzabile, con risultato auditabile in memoria e un esperimento sintetico persistito. Lo stato dettagliato delle feature previste e delle relative milestone e` mantenuto nella roadmap di implementazione.

Gli adapter devono implementare `evaluate_domain_metrics`: dopo il post-check
possono restituire metriche di dominio con valore, unita`, convenzione e
provenance, oppure una sequenza vuota. Il metodo non viene chiamato se il
post-check non e` raggiunto; in quel caso il campo del risultato e` `None`.
Un errore del metodo produce `adapter_failure` e conserva i risultati precedenti.
Anche eccezioni o risultati non validi del post-check producono `adapter_failure`,
conservando il risultato del solve e il fixing manifest senza adottare la soluzione.
Il manifest degli esperimenti include la provenance della policy redatta.
Le metriche single-pass distinguono sample uniche prima del cap, sample elaborate
e candidate riparate; la ratio misura item del grafo, non variabili logiche.
Il fixing manifest distingue origine e garanzia per ogni entry e registra round,
candidate selezionate e versione della policy del grafo. Gli adapter possono
fornire `describe_input` per calcolare un hash dell'input serializzabile redatto;
se assente o non serializzabile, l'hash resta indisponibile.

## Specifiche e roadmap

`docs/specifications.md` definisce le feature previste, i requisiti, le
garanzie e i non-obiettivi di QReduce. La roadmap in
`docs/implementation/00-implementation-overview.md` stabilisce invece come tali
feature vengono completate, con milestone, stato ed evidenze di verifica.

Questo README riassume le capacita` utilizzabili e le istruzioni operative del
repository; non sostituisce ne` duplica il piano di implementazione.

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

Il portfolio media-varianza presente in `qreduce.experiments` e` un esempio
sintetico interno: dimostra un adapter che costruisce il grafo, applica fixing,
compila un MIQP residuo ed esegue il post-check. Non e` un adapter finanziario
generico, una policy raccomandata o una dipendenza della distribuzione; gli
adapter di altri domini devono implementare il contratto QReduce con la propria
semantica.

Gli adapter di dominio devono implementare `describe_logical_variables(problem)`
e restituire `LogicalVariableCounts` per problema originale e residuo. I conteggi
escludono le variabili esplicitamente fissate e le ausiliarie dei solver; non
richiedono un solve per dedurre fixing impliciti. Gli adapter precedenti devono
essere aggiornati: l'assenza del metodo produce `adapter_failure`. Il risultato
espone `original_variable_counts` e `residual_variable_counts`; quest'ultimo e`
assente finche` il residuo non e` costruito e descritto con successo.

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

Il kernel e` indipendente da QPU, simulatore e SDK specifici. Il backend
configurato dichiara le proprie capability e QReduce rifiuta richieste
incompatibili senza selezionare automaticamente un'alternativa. Le feature
previste e lo stato dei rispettivi adapter sono documentati nelle specifiche e
nella roadmap.

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
poetry run python -m qreduce.experiments.portfolio \
  --run-id scip-run-001 \
  --mis-solver-id local_greedy \
  --classical-solver-id scip
```

Il notebook corrispondente e`
`notebooks/experiments/01_synthetic_portfolio_single_pass.ipynb` e carica
`outputs/synthetic-portfolio-single-pass/scip-run-001/`. Il percorso predefinito
usa `local_greedy` per MIS e `scip` per il solve classico residuo.

L'export del modello residuo e` disabilitato per default. Per richiederlo,
aggiungere `--model-export`: il runner pubblica `residual_model.lp` nella
directory del run. Con `--model-export-path /percorso/modello.lp` si sceglie
invece un file `.lp` o `.mps`; la directory esterna deve gia` esistere e un
file esistente non viene sovrascritto. Il manifest registra formato e hash.
L'export predefinito segue la pubblicazione atomica del run; un file esterno
non fa parte della stessa transazione. Nell'uso diretto di `run_pipeline`,
chi abilita l'export deve fornire `model_export_path` nella configurazione.
Il loader verifica l'hash del modello interno al run; l'hash del file esterno
e` registrato nel manifest, ma non viene verificato dal loader.

Per analizzare il percorso con simulatore MIS D-Wave Ocean locale e solve
classico CPLEX, produrre prima artifact distinti:

```bash
poetry run python -m qreduce.experiments.portfolio \
  --run-id dwave-cplex-001 \
  --mis-solver-id dwave_simulated_annealing \
  --classical-solver-id cplex \
  --mis-num-reads 100 \
  --mis-num-sweeps 1000
```

Il notebook `notebooks/experiments/02_synthetic_portfolio_single_pass.ipynb`
carica `outputs/synthetic-portfolio-single-pass/dwave-cplex-001/`. Il simulatore
Ocean non richiede credenziali o QPU; CPLEX richiede invece un binding e una
licenza utilizzabile. Anche un eventuale failure CPLEX viene pubblicato come
artifact analizzabile.

Per l'esperimento multi-round più grande, con 30 asset predefiniti e SCIP:

```bash
poetry run python -m qreduce.experiments.portfolio_multi_round --run-id multi-round-001
```

Il notebook `notebooks/experiments/03_synthetic_portfolio_multi_round.ipynb`
analizza gli artifact pubblicati. L'opzione `--asset-count` cambia la dimensione
(minimo 6). Il limite di tre round non garantisce tre iterazioni: la pipeline
si arresta al primo successo o successo parziale.

Un run QReduce con esito normalizzato `failed` viene comunque salvato: e` un risultato analizzabile, non un fallimento della serializzazione. Se invece la scrittura degli artifact non riesce, il runner fallisce e non pubblica una directory finale incompleta.

I notebook in `notebooks/experiments/` devono caricare i dati gia` prodotti dal filesystem tramite `qreduce.experiments.load_experiment_run`; non devono chiamare direttamente la pipeline.

## Documentazione

### Notebook di visualizzazione

I notebook in `notebooks/tasks/` sono esempi didattici sintetici in memoria: grafo
MWIS ed equivalenza QUBO/Ising. La logica degli esempi risiede in
`src/qreduce/notebooks/examples.py`; questi notebook non esportano artifact e non
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

Le fonti autorevoli sono:

- [`docs/specifications.md`](./docs/specifications.md) per feature previste e requisiti normativi;
- [`docs/implementation/00-implementation-overview.md`](./docs/implementation/00-implementation-overview.md) per roadmap, stato ed evidenze di implementazione.
