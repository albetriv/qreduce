# Esperimento portfolio

L'esperimento portfolio verifica la pipeline QReduce con un problema di
ottimizzazione media-varianza sintetico. È la famiglia principale per lo
sviluppo e il test del framework.

## Problema di dominio

Il portfolio media-varianza bilancia rendimento atteso e rischio (varianza)
tramite un coefficiente `risk_aversion`. L'obiettivo MIQP minimizza:

```text
risk_aversion * x' * Σ * x - μ' * x
```

dove `Σ` è la matrice di covarianza, `μ` i rendimenti attesi, `x` i pesi.
Il vincolo di budget impone che la somma dei pesi sia 1.

L'adapter portfolio:

- identifica ogni asset come item riducibile;
- costruisce il grafo di conflitto basato su correlazione o near-duplicate;
- fissa a zero i pesi degli asset esclusi;
- compila un MIQP residuo con vincolo di budget e link binario-continuo.

Le covarianze da serie sintetiche sono semidefinite positive per costruzione.
Matrici fornite esplicitamente sono verificate con Cholesky dopo shift
diagonale di `1e-8`.

## Modalità di esecuzione

### Classical-only baseline (senza riduzione)

```bash
poetry run python -m qreduce.experiments.portfolio.classical \
  --run-id 001_classical \
  --asset-count 30
```

`max_reduction_rounds=0`: il problema è risolto direttamente senza riduzione
MWIS. Utile come baseline per confronto. Usa SCIP come solver predefinito.

**Opzioni disponibili:** `--run-id`, `--output-root`, `--asset-count`,
`--generation-seed`, `--observation-count`.

### Single-pass (un round di riduzione)

```bash
poetry run python -m qreduce.experiments.portfolio.single_pass \
  --run-id 002_scip \
  --asset-count 12 \
  --graph-edge-mode correlation_only \
  --correlation-threshold 0.80 \
  --mis-solver-id local_greedy \
  --classical-solver-id scip
```

`max_reduction_rounds=1`: un solo round di riduzione seguito dal solve
classico del residuo.

**Opzioni disponibili:** tutte le opzioni della tabella sotto, inclusi
`--classical-solver-id`, `--mis-solver-id`, `--model-export`,
`--model-export-path`.

### Multi-round (più round di riduzione)

```bash
poetry run python -m qreduce.experiments.portfolio.multi_round \
  --run-id 004_correlation_only \
  --asset-count 30 \
  --graph-edge-mode correlation_only \
  --correlation-threshold 0.90
```

`max_reduction_rounds>1` (default 3): la pipeline si arresta al primo successo
o successo parziale. Non garantisce tre iterazioni. Usa solver predefiniti
(SCIP, local_greedy).

**Opzioni disponibili:** `--run-id`, `--output-root`, `--asset-count`,
`--graph-edge-mode`, `--correlation-threshold`,
`--near-duplicate-max-relative-return-difference`,
`--near-duplicate-max-relative-variance-difference`, `--generation-seed`,
`--observation-count`.

**Non disponibili in multi_round:** `--classical-solver-id`, `--mis-solver-id`,
`--model-export`.

## Opzioni per entry point

Le opzioni variano tra gli entry point. La tabella seguente indica la
disponibilità:

| Opzione                  | classical | single_pass | multi_round |
|--------------------------|:---------:|:-----------:|:-----------:|
| `--run-id`               | ✓         | ✓           | ✓           |
| `--output-root`          | ✓         | ✓           | ✓           |
| `--asset-count`          | ✓         | ✓           | ✓           |
| `--generation-seed`      | ✓         | ✓           | ✓           |
| `--observation-count`    | ✓         | ✓           | ✓           |
| `--classical-solver-id`  |           | ✓           |             |
| `--mis-solver-id`        |           | ✓           |             |
| `--graph-edge-mode`      |           | ✓           | ✓           |
| `--correlation-threshold`|           | ✓           | ✓           |
| `--mis-num-reads`        |           | ✓           |             |
| `--mis-num-sweeps`       |           | ✓           |             |
| `--model-export`         |           | ✓           |             |
| `--model-export-path`    |           | ✓           |             |

### Opzioni MIS D-Wave (solo single_pass)

| Opzione                  | Descrizione                                      |
|--------------------------|--------------------------------------------------|
| `--mis-num-reads`        | Numero di sample                                 |
| `--mis-num-sweeps`       | Sweep per sample                                 |

Esempio con D-Wave simulated annealing e CPLEX:

```bash
poetry run python -m qreduce.experiments.portfolio.single_pass \
  --run-id 003_dwave_cplex \
  --asset-count 12 \
  --graph-edge-mode correlation_only \
  --correlation-threshold 0.80 \
  --mis-solver-id dwave_simulated_annealing \
  --classical-solver-id cplex \
  --mis-num-reads 100 \
  --mis-num-sweeps 1000
```

Il simulatore D-Wave Ocean non richiede credenziali o QPU; CPLEX richiede
binding e licenza.

## Export del modello residuo (solo single_pass)

L'export è disabilitato per default. Per richiederlo, usare **entrambe** le
opzioni quando si specifica un percorso esterno:

```bash
# Export interno (nella directory del run)
--model-export

# Export esterno (percorso personalizzato) - richiede entrambe le opzioni
--model-export --model-export-path /percorso/modello.lp
```

Il manifest registra formato e hash. L'export interno segue la pubblicazione
atomica; un file esterno non fa parte della stessa transazione.

## Convenzioni dei run ID

I run degli esempi usano un prefisso numerico che corrisponde al notebook
associato:

- `001_*`: classical baseline → notebook `001_synthetic_portfolio_classical.ipynb`
- `002_*`: single-pass SCIP → notebook `002_synthetic_portfolio_single_pass.ipynb`
- `003_*`: single-pass D-Wave/CPLEX → notebook `003_synthetic_portfolio_single_pass.ipynb`
- `004_*`: multi-round → notebook `004_synthetic_portfolio_multi_round.ipynb`

Per un nuovo run mantenere il prefisso e scegliere un nome distinto (es.
`002_scip_50assets`).

## Directory degli artifact

```text
outputs/portfolio/{run_id}/
├── run_result.json
├── config_used.json
├── problem.json
├── experiment_metadata.json
├── run_manifest.json
├── round_NN_result.json      # uno per ogni round di riduzione completato
├── recovery_attempts.json    # se sono stati eseguiti tentativi di recovery
└── residual_model.lp         # se export interno effettivamente prodotto
```

**Model export:**
- `--model-export` senza `--model-export-path`: export interno, file nella
  run directory. Compare solo se il backend ha prodotto il file.
- `--model-export --model-export-path <path>`: export esterno. Il file viene
  scritto al path specificato (estensione `.lp` o `.mps`, directory padre
  esistente, file non preesistente). Non compare nella run directory.
- Un run fallito prima del solve classico non produce il file di export.

L'opzione `--output-root` sostituisce interamente `outputs/portfolio`: il
runner usa `output_root/{run_id}/` senza aggiungere la famiglia.

## Notebook di analisi

I notebook si trovano in `notebooks/experiments/portfolio/`:

| Notebook                                       | Dati caricati            |
|------------------------------------------------|--------------------------|
| `001_synthetic_portfolio_classical.ipynb`      | `001_classical/`         |
| `002_synthetic_portfolio_single_pass.ipynb`    | `002_scip/`              |
| `003_synthetic_portfolio_single_pass.ipynb`    | `003_dwave_cplex/`       |
| `004_synthetic_portfolio_multi_round.ipynb`    | `004_correlation_only/`  |

I notebook caricano artifact già prodotti tramite `load_experiment_run` e non
eseguono la pipeline. La logica di analisi risiede in
`qreduce.experiments.portfolio.analysis`.

### Interpretazione dei grafici

**Grafo di riduzione:**
- Nodi = asset con peso visualizzato.
- Archi = linee rosse che collegano asset in conflitto (correlazione o
  near-duplicate).
- Layout circolare illustrativo, non coordinate geometriche del problema.
- Colore nodi: verde chiaro = dominio mantenuto, bianco = altri nodi.

**Matrice delle correlazioni:**
- Celle con crocette rosse = archi presenti nel grafo persistito.
- Le crocette marcano gli archi effettivi, inclusi quelli ammessi dalla
  policy near-duplicate (non solo dalla soglia di correlazione).

Un grafo senza archi non mostra linee; la matrice corrispondente non mostra
crocette.

## Comportamento dei run

- Un run con esito `failed` (failure normalizzata della pipeline) viene
  pubblicato come artifact analizzabile.
- Errori di configurazione prima dell'invocazione del runner non producono
  artifact.
- Directory esistenti non vengono sovrascritte: archiviare o rimuovere prima
  di ripubblicare.
- Il loader verifica gli hash degli artifact interni.

## Requisiti

- **SCIP**: `poetry install --with experiments` (PySCIPOpt)
- **CPLEX**: binding `cplex` + licenza utilizzabile
- **D-Wave**: `poetry install --with experiments` (simulatore locale, no QPU)

Un backend non disponibile produce failure esplicito senza fallback.

## Riferimenti

- Adapter: `src/qreduce/experiments/portfolio/adapter.py`
- Modelli: `src/qreduce/experiments/portfolio/models.py`
- Analisi: `src/qreduce/experiments/portfolio/analysis.py`
- Post-check: `src/qreduce/experiments/portfolio/postcheck.py`
