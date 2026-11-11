# QReduce

QReduce e` un framework per ridurre il dominio combinatorio di grandi problemi di ottimizzazione mista prima del solve classico del problema residuo.

Usa **Maximum Weight Independent Set (MWIS)** per selezionare un sottoinsieme di decisioni binarie da mantenere attive. Le decisioni escluse vengono fissate esplicitamente; obiettivo e vincoli hard del problema originale restano responsabilita` del solver classico.

> **Stato**: e` disponibile una pipeline single-pass dimostrativa per il portfolio sintetico, con risultato auditabile in memoria. Il repository include inoltre un runner interno per esperimenti persistiti, non distribuito con la libreria. Recovery e multi-round non sono inclusi.

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

Per installare il solver classico opzionale CPLEX:

```powershell
poetry install --extras cplex
```

`poetry lock` risolve le dipendenze e crea o rigenera il file `poetry.lock`, che
e` versionato. `poetry install` crea o riusa l'ambiente virtuale e installa il
package in modalita` editable insieme alle dipendenze gia` risolte.

Le dipendenze core restano provider-agnostic. Test e lint appartengono al gruppo
di sviluppo. Il binding Python CPLEX appartiene all'extra `cplex`, perche` e`
richiesto soltanto dal solver classico opzionale `cplex`. Il binding e` importato
lazy da `CplexClassicalBackend`, quindi `import qreduce` non lo carica. Se il
binding, la licenza o l'ambiente CPLEX non sono utilizzabili, QReduce produce una
failure esplicita e non seleziona automaticamente un solver alternativo.

## Selezione dei solver

L'applicazione seleziona i solver tramite ID pubblici e serializzabili; QReduce
risolve internamente il relativo backend Python attraverso registry espliciti.

```text
mis_solver_id = "local_greedy"
classical_solver_id = "cplex"
```

`local_greedy` risolve il MWIS usato per la riduzione del dominio. `cplex`
risolve il MILP/MIQP residuo dopo l'applicazione dei fixing. Le classi interne
`LocalGreedyMISBackend` e `CplexClassicalBackend` non sono la scelta primaria
dell'utente. Un ID sconosciuto, non disponibile o incompatibile fallisce in modo
esplicito; non e` previsto fallback silenzioso.

## Policy e valutazione esterna

QReduce esegue policy graph/MIS/riduzione fornite dall'applicazione chiamante e ne registra configurazione, provenance ed esiti. Non include un workflow di calibrazione, benchmark o selezione automatica della policy: riferimenti classici, metriche di qualita`, soglie e separazione fra tuning e valutazione finale restano responsabilita` dell'applicazione o dell'adapter di dominio.

## Integrazione concettuale

```text
applicazione esterna
  -> problema originale + policy esplicita
  -> adapter di dominio + MIS solver + solver classico
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

Il caso di riferimento e` il portfolio sintetico single-pass. Per produrre un
run da analizzare:

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

Aprire i notebook dal repository. Per eseguire il runner portfolio con il solve
classico reale, installare inoltre con `poetry install --with notebooks --extras
cplex` e disporre di una licenza CPLEX utilizzabile. In assenza di CPLEX il runner
salva la failure effettiva e gli eventuali risultati intermedi, senza sostituire
il solver. Le selezioni MWIS non sono la soluzione finale e non certificano
l'ottimo del problema originale.

La specifica completa e normativa e` disponibile in [`docs/specifications.md`](./docs/specifications.md).
