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
- **MWIS**: `local_greedy`, `dwave_simulated_annealing`, `pasqal_local` (opt-in),
  `pasqal_cloud_emulator` (opt-in, richiede credenziali)

Il gruppo `experiments` include `pulser-simulation` (con `pulser-core`) e
`pasqal-cloud`: installare con `poetry install --with experiments` sia per
l'emulazione locale sia per il backend cloud. Non serve un gruppo separato.
Nelle CLI portfolio MV e SR selezionare `--mis-solver-id pasqal_local`, con
`--max-end-to-end-runtime-seconds=0` e, facoltativamente, `--pasqal-shots 100`
(valore predefinito). Il backend accetta al massimo 12 nodi, non richiede
credenziali e non esegue job cloud. I pesi MWIS sono valutati dalla pipeline.

Il backend cloud della CLI portfolio MV si seleziona con
`--mis-solver-id pasqal_cloud_emulator --pasqal-emulator-service emu_free`.
L'esecuzione remota richiede credenziali Pasqal Cloud, configurabili in
`~/.pasqual/credentials`; l'installazione dell'SDK non le richiede.
L'MVP supporta solo `emu_free`, con un limite prudenziale di 12 atomi per
gli invii remoti. Il riferimento del batch è salvato sotto
`<output-root>/.pasqal-cloud-jobs/<run-id>/`, anche se il run fallisce.
Per recuperare i campioni senza reinviare il batch:

```bash
poetry run python -m qreduce.experiments.portfolio_mv recover-pasqal \
  --reference "$OUTPUT_ROOT/.pasqal-cloud-jobs/$RUN_ID/pasqal_cloud_job_$BATCH_ID.json"
```

Il flusso è verificato con SDK reale e trasporto simulato; non sul servizio reale.
Stato e limiti in
`docs/implementation/pasqal-local-status.md`.
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
- **portfolio_mv**: ottimizzazione media-varianza sintetica;
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

Nella scheda Solver, parametri e informazioni MIS sono contestuali al backend
selezionato; gli avvisi di embedding compaiono solo con un profilo attivo.
In baseline il MIS non è utilizzato, mentre le informazioni del solver classico
restano disponibili. Cambiare backend o disattivare la riduzione conserva i
valori inattivi senza includerli nel comando. I pannelli descrivono requisiti,
non verificano SDK installati o licenze. Gli errori bloccanti sono associati ai
campi da correggere, incluso il budget end-to-end per Pasqal.

I configuratori includono un pannello espandibile con la formulazione
matematica del problema configurato, renderizzata con MathJax quando
disponibile.

Nel pannello destro, **Comandi preferiti** permette di salvare, caricare e
cancellare configurazioni con elenco alfabetico. I dati restano nel browser:
nessun archivio viene creato nel workspace. Import/export JSON consente il
trasferimento manuale tra browser e macchine, salvando il file fuori dal repository.
Con pagine `file://`, verificare la persistenza dopo la riapertura del browser;
se lo storage non e disponibile, la UI segnala la modalita solo in memoria.
Dettagli e procedura di verifica in [Configuratori HTML](docs/experiments/README.md#comandi-preferiti).

Il nome proposto segue l'ID del run finché non viene personalizzato; svuotandolo,
la proposta riprende alla successiva modifica dell'ID. Carica conserva il nome
salvato, mentre Ripristina default riallinea la proposta all'ID ripristinato.
Nel portfolio MV, **Candidati MIS da aggregare** espone
`--num-source-mis-candidates`: vuoto omette il flag (default CLI 1), in baseline
è disabilitato e non viene emesso. Non cambia il numero di shot del backend MIS.

Nel configuratore **Portfolio Mean–Variance**, la scheda **05 · Confronto**
permette di scegliere **Baseline** e **Run di confronto** da due tendine di run ID,
senza selezionare cartelle, avviare un server o rilanciare i solver. La dashboard mostra indicatori,
grafici del dominio, motivi registrati per round, posizioni della baseline, tempi e
un verdetto complessivo quando sono soddisfatte le condizioni di confrontabilita;
in caso contrario ne indica i motivi. I dettagli tecnici sono espandibili e il report
resta nella pagina, senza generazione o download Markdown. Le differenze descrivono
i run osservati, non provano un effetto causale.

Per creare il catalogo locale o aggiornarlo dopo aver aggiunto, rimosso o
rigenerato dei run, eseguire dalla root del repository (con l'ambiente del progetto
attivo), poi premere **↻** nella scheda **Confronto** per ricaricare il catalogo.
Non occorre ricaricare la pagina; le selezioni restano valide finché i relativi
run sono presenti nel catalogo.

```powershell
python -m qreduce.experiments.portfolio_mv.run_catalog
```

Il comando legge gli output già pubblicati in `outputs/portfolio_mv` e genera
`outputs/portfolio_mv/run_catalog.js`, uno snapshot locale non tracciato da Git.
Per requisiti dei file, stato delle verifiche e limiti del confronto si veda la
[nota di implementazione](./docs/implementation/uix-portfolio-comparison-findings.md).

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

### Post-processing dei candidati MWIS

Il completamento greedy è un'opzione classica esplicita, disabilitata per
default: impostare insieme `completion_enabled=true` e
`completion_policy_id="greedy_by_weight"` (oppure `greedy_by_degree` o
`greedy_weight_degree`). Il repair resta indipendente da questa opzione.
Gli artefatti distinguono campione originale, riparazione e completamento;
i candidati finali uguali vengono aggregati prima della selezione.
Il confronto UI mostra le aggiunte classiche separatamente dalle riparazioni.

### Notebook portfolio MV: MWIS e Pasqal 2D

Il notebook `notebooks/experiments/portfolio_mv/001_mwis_pasqal_2d.ipynb`
analizza i run salvati senza avviare solver o simulatori. Impostare `RUN_ID`,
`BASELINE_RUN_ID` (opzionale) e `ROUND_INDEX` nella cella di configurazione.
Mostra correlazioni e incompatibilità, grafo MWIS, coordinate Pasqal, congruenza
degli archi geometrici, diagnostiche fisiche, selezioni raw Pulser, candidati e
cap del dominio, quindi le allocazioni finali a confronto con la baseline.
La logica è in `src/qreduce/notebooks/portfolio_mv.py`. Il confronto delle
allocazioni richiede lo stesso problema originale e soluzioni adottate con
postcheck superato; l'enumerazione MWIS è diagnostica e limitata esplicitamente.
