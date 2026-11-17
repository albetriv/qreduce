# QReduce

QReduce riduce il dominio combinatorio di grandi problemi di ottimizzazione
mista prima del solve classico del problema residuo.

Usa **Maximum Weight Independent Set (MWIS)** per selezionare un sottoinsieme di
decisioni binarie da mantenere attive. Le decisioni escluse vengono fissate
esplicitamente; obiettivo e vincoli hard del problema originale restano
responsabilita` del solver classico.

La QUBO MWIS e` un problema ausiliario di riduzione: i suoi termini quadratici
non vengono sommati all'obiettivo di dominio.

## Come funziona

```text
applicazione esterna
  -> problema originale + policy esplicita
  -> adapter di dominio + solver ID configurati
  -> QReduce
  -> candidate domain + fixing manifest + solve residuo + post-check
  -> decisione dell'applicazione
```

**Flusso interno:**

```text
problema MILP/MIQP (vincoli lineari)
  -> grafo di conflitto/ridondanza
  -> MWIS canonico (QUBO e/o BQM/Ising)
  -> esecuzione del MIS solver
  -> validazione, repair e candidate domain
  -> fixing delle decisioni escluse
  -> solve classico del problema residuo
  -> post-check della soluzione finale
```

L'applicazione mantiene la responsabilita` del modello di dominio, della scelta
della policy, delle metriche di qualita` e dell'adozione del risultato. QReduce
gestisce la riduzione e restituisce un risultato auditabile in memoria.

L'entry point principale e` `qreduce.pipeline.run_pipeline`.

Il contratto residuale corrente supporta MILP e MIQP con vincoli lineari.
Vincoli quadratici, conici, indicatori o non lineari richiedono una
riformulazione o un'estensione esplicita del contratto. Le specifiche
dettagliate sono in [`docs/specifications.md`](./docs/specifications.md).

Le tre modalita` di esecuzione sono determinate da `max_reduction_rounds`:
- `0`: classical-only baseline, senza riduzione;
- `1`: single-pass, un solo round di riduzione;
- `>1`: multi-round, arresto al primo successo o successo parziale.

## Garanzie e limiti

- MWIS propone una riduzione del dominio; non e` la soluzione finale del
  problema originale.
- Un fixing derivato euristicamente non certifica l'ottimalita` globale.
- Ogni soluzione residua deve superare un post-check rispetto ai fixing e ai
  vincoli del problema originale.
- Configuration, risultati intermedi, failure e provenance del backend sono
  disponibili nel risultato in memoria.
- Il kernel e` indipendente da QPU, simulatore e SDK specifici.
- Non e` previsto fallback silenzioso: un backend non disponibile produce un
  failure esplicito.

## Sviluppo

Il progetto usa [Poetry](https://python-poetry.org/) e adotta un layout `src/`.
La compatibilita` tecnica supportata e` Python `>=3.12,<3.13`; il valore in
`pyproject.toml` e` la fonte autorevole.

```bash
poetry lock
poetry install
poetry run pytest
poetry run ruff check .
```

I dependency groups `experiments` e `notebooks` sono definiti nel
`pyproject.toml` e vengono installati per default. Per escluderli:

```bash
poetry install --without experiments,notebooks
```

## Selezione dei solver

L'applicazione seleziona i solver tramite ID pubblici. La pipeline risolve
automaticamente gli ID forniti da QReduce.

```python
mis_solver_id = "local_greedy"        # oppure "dwave_simulated_annealing"
classical_solver_id = "scip"          # oppure "cplex"
```

Il catalogo iniziale contiene:
- **MWIS**: `local_greedy`, `dwave_simulated_annealing`
- **Classico residuo**: `cplex`, `scip`

Un ID sconosciuto e` un errore di configurazione; un ID noto con binding non
disponibile produce un failure esplicito. I parametri provider-specifici sono
documentati nelle docstring dei backend.

## Logging

QReduce usa il modulo `logging` standard di Python con configurazione YAML
esterna.

### Uso come libreria

All'import QReduce aggiunge solo un `NullHandler` al logger `qreduce`, senza
configurare destinazioni o livelli. L'applicazione ospite mantiene il controllo
della propria configurazione logging.

Per integrare i log di QReduce nella propria applicazione, configurare il logger
`qreduce` e i suoi figli secondo le proprie esigenze, senza chiamare
`configure_logging()`.

### Configurazione nelle CLI degli esperimenti

Le CLI degli esperimenti chiamano `configure_logging()`, che applica
`dictConfig()` all'intero processo. Questa funzione è destinata agli entry
point che controllano la configurazione del processo.

**Attenzione**: `configure_logging()` può chiudere o riconfigurare handler
precedentemente impostati dall'applicazione ospite. Non usarla se si vuole
integrare QReduce in un'applicazione con logging già configurato.

Le tre sorgenti per la configurazione, in ordine di precedenza:

1. Opzione `--log-config <path>` (esplicita)
2. Variabile d'ambiente `QREDUCE_LOG_CONFIG`
3. File predefinito `config/logging.yaml` del repository

Un percorso esplicito inesistente o malformato produce un errore all'avvio.
Senza configurazione il logging resta silenzioso (solo `NullHandler`).

Il file predefinito del repository non è disponibile quando QReduce è installato
come pacchetto esterno; in quel caso usare `--log-config` o la variabile
d'ambiente.

### Percorsi e destinazioni

Il file YAML predefinito configura:
- Console su `stderr` a livello `INFO`
- File con rotazione in `logs/qreduce.log` a livello `DEBUG`

I percorsi relativi nel YAML (es. `filename: "../logs/qreduce.log"`) sono
risolti rispetto alla directory del file YAML, non rispetto alla directory di
lavoro. Le directory di destinazione vengono create automaticamente.

I log sono tenuti separati dagli artifact degli esperimenti per preservare la
diagnostica anche in caso di errori di pubblicazione.

La rotazione su file condiviso da più processi concorrenti non è supportata;
per quel caso usare file separati per processo o un writer centralizzato.

### Contesto e campi

Gli eventi di logging possono includere campi contestuali:
- `run_id`: identificatore del run corrente
- `round_index`: indice del round di riduzione
- `stage`: fase della pipeline (graph_construction, mwis_execution, ...)
- `solver_id`: identificatore del solver attivo

Il filtro `ContextDefaultsFilter` inietta valori predefiniti (`-`) per i campi
non impostati, evitando errori di formattazione.

### Sicurezza

Il file YAML è caricato con `yaml.safe_load()`, ma `dictConfig()` può
istanziare oggetti indicati nella configurazione. Caricare solo file YAML
da sorgenti fidate.

## Esperimenti interni

Gli esperimenti sono organizzati per famiglia di problemi:

```text
src/qreduce/experiments/<famiglia>/
notebooks/experiments/<famiglia>/
outputs/<famiglia>/<run_id>/
```

Runner e loader degli artifact sono condivisi; adapter e parametri appartengono
alle singole famiglie. I notebook caricano artifact gia` prodotti tramite
`load_experiment_run` e non eseguono direttamente la pipeline.

Famiglie disponibili:
- **portfolio**: ottimizzazione media-varianza sintetica;
- **facility_location**: esperimento sperimentale con istanze OR-Library.

Un run con esito `failed` viene comunque salvato come risultato analizzabile.
Comandi, parametri e notebook specifici sono descritti nelle guide delle
famiglie in [`docs/experiments/`](./docs/experiments/).

### Configuratori HTML

La directory [`uix/`](./uix/) contiene configuratori HTML per generare comandi
CLI. Le pagine sono statiche, apribili direttamente da filesystem senza server.
Il catalogo [`uix/index.html`](./uix/index.html) elenca i configuratori
disponibili.

Ogni parametro ha un'icona informativa (ⓘ) che mostra una descrizione al
passaggio del mouse o con focus/tocco. Le descrizioni documentano scopo,
effetto e condizioni d'uso di ciascun parametro.

I configuratori includono un pannello espandibile con la formulazione
matematica del problema configurato, renderizzata con MathJax quando
disponibile.

## Notebook di visualizzazione

I notebook in `notebooks/tasks/` sono esempi didattici sintetici in memoria:
grafo MWIS ed equivalenza QUBO/Ising. La logica risiede in
`src/qreduce/notebooks/examples.py`; non esportano artifact.

```bash
poetry install --with notebooks
poetry run jupyter lab
```

## Documentazione

Le fonti autorevoli sono:

- [`docs/specifications.md`](./docs/specifications.md): feature previste,
  requisiti e garanzie;
- [`docs/implementation/00-implementation-overview.md`](./docs/implementation/00-implementation-overview.md):
  roadmap, stato ed evidenze di implementazione;
- [`docs/experiments/`](./docs/experiments/): guide operative degli esperimenti
  per famiglia;
- docstring nei moduli `src/qreduce/`: contratti operativi delle API.

Questo README riassume le capacita` utilizzabili e le istruzioni operative del
repository; non sostituisce le specifiche ne` la documentazione tecnica.
