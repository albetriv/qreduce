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

Un run con esito `failed` viene comunque salvato come risultato analizzabile.
Modelli, parametri CLI e directory degli artifact sono descritti nelle guide
delle famiglie in [`docs/experiments/`](./docs/experiments/).

## Configuratori HTML

La directory [`uix/`](./uix/) contiene configuratori HTML per generare comandi
CLI. Le pagine sono statiche, apribili direttamente da filesystem senza server.
Il catalogo [`uix/index.html`](./uix/index.html) elenca i configuratori
disponibili.

I configuratori offrono informazioni sui parametri e
comandi preferiti salvati nel browser, con import/export JSON. Non verificano
la disponibilita` di SDK o licenze. Dettagli sui preferiti nella
[guida agli esperimenti](docs/experiments/README.md#comandi-preferiti).

In **Portfolio SR** e **Portfolio MV**, con riduzione attiva e simulated annealing
D-Wave su Pegasus o Zephyr, **Forza delle catene** usa **Auto bilanciato** per
default. Selezionare **Manuale** per emettere `--mis-chain-strength`. La scheda
**Confronto** mostra il valore effettivo e la politica registrati negli artefatti.

Nel configuratore **Portfolio Mean–Variance**, la scheda **05 · Confronto**
mostra indicatori e dettagli di una baseline e di un altro run, senza rilanciare
i solver. Le differenze descrivono i run osservati e non provano causalita`.

Per creare il catalogo locale o aggiornarlo dopo aver aggiunto, rimosso o
rigenerato dei run, eseguire dalla root del repository con l'ambiente del progetto
attivo, poi premere **↻** nella scheda **Confronto** per ricaricarlo:

```bash
python -m qreduce.experiments.portfolio_mv.run_catalog
```

Il comando legge gli output già pubblicati in `outputs/portfolio_mv` e genera
`outputs/portfolio_mv/run_catalog.js`, uno snapshot locale non tracciato da Git.

## Notebook di visualizzazione

I notebook in `notebooks/experiments/` visualizzano gli artifact degli
esperimenti utilizzando la logica dei moduli Python del progetto.

```bash
poetry install --with notebooks
```

## Documentazione

Le fonti autorevoli sono:

- [`docs/specifications.md`](./docs/specifications.md): feature previste,
  requisiti e garanzie;
- [`docs/implementation/00-implementation-overview.md`](./docs/implementation/00-implementation-overview.md):
  sintesi dello stato di implementazione;
- [`docs/experiments/`](./docs/experiments/): guide operative degli esperimenti
  per famiglia;
- docstring nei moduli `src/qreduce/`: contratti operativi delle API.

Questo README riassume le capacita` utilizzabili e le istruzioni operative del
repository; non sostituisce le specifiche ne` la documentazione tecnica.
