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

## CLI unificata

Tutti gli esperimenti portfolio usano un singolo comando CLI. La modalità di
esecuzione è controllata da `--max-reduction-rounds`:

```bash
poetry run python -m qreduce.experiments.portfolio --help
```

| Valore                     | Modalità                         |
|----------------------------|----------------------------------|
| `--max-reduction-rounds 0` | Classical-only baseline          |
| `--max-reduction-rounds 1` | Single-pass (default)            |
| `--max-reduction-rounds N` | Multi-round (N > 1)              |

### Configuratore HTML

Il configuratore [`uix/experiment_portfolio.html`](../../uix/experiment_portfolio.html)
genera comandi CLI interattivamente. È una pagina statica apribile direttamente
da filesystem; seleziona i parametri e copia il comando nel terminale.

Formati disponibili:
- **Una riga**: comando inline per copia diretta
- **Multilinea**: comando formattato con continuazioni Bash/Zsh

Il configuratore include solo i flag con valori diversi dai default e non
verifica la disponibilità dei solver.

### Classical-only baseline (senza riduzione)

```bash
poetry run python -m qreduce.experiments.portfolio \
  --run-id 001_classical \
  --asset-count 30 \
  --max-reduction-rounds 0
```

Il problema è risolto direttamente senza riduzione MWIS. Utile come baseline
per confronto.

### Single-pass (un round di riduzione)

```bash
poetry run python -m qreduce.experiments.portfolio \
  --run-id 002_scip \
  --asset-count 12 \
  --graph-edge-mode correlation_only \
  --correlation-threshold 0.80 \
  --mis-solver-id local_greedy \
  --classical-solver-id scip
```

Un solo round di riduzione seguito dal solve classico del residuo. È la
modalità predefinita (`--max-reduction-rounds 1`).

### Multi-round (più round di riduzione)

```bash
poetry run python -m qreduce.experiments.portfolio \
  --run-id 004_correlation_only \
  --asset-count 30 \
  --graph-edge-mode correlation_only \
  --correlation-threshold 0.90 \
  --max-reduction-rounds 3
```

La pipeline si arresta al primo successo o successo parziale. Non garantisce
tre iterazioni.

## Opzioni CLI

Tutte le opzioni sono disponibili per tutte le modalità. La CLI unificata
espone i seguenti gruppi di opzioni:

### Opzioni generali

| Opzione                  | Descrizione                                      | Default               |
|--------------------------|--------------------------------------------------|-----------------------|
| `--run-id`               | Identificatore unico del run (obbligatorio)      |                       |
| `--output-root`          | Directory radice degli artifact                  | `outputs/portfolio`   |
| `--log-config`           | Percorso file YAML di configurazione logging     | `config/logging.yaml` |
| `--model-export`         | Esporta il modello residuo                       | disabilitato          |
| `--model-export-path`    | Percorso per export esterno                      |                       |

### Opzioni di generazione

| Opzione                  | Descrizione                                      | Default               |
|--------------------------|--------------------------------------------------|-----------------------|
| `--asset-count`          | Numero di asset nel portfolio                    | 30                    |
| `--generation-seed`      | Seed per la generazione                          | 42                    |
| `--observation-count`    | Numero di osservazioni storiche                  | 10 × asset_count      |

### Opzioni limiti di investimento e cardinalità

Queste opzioni controllano i vincoli sul portfolio finale:

| Opzione                  | Descrizione                                      | Default               |
|--------------------------|--------------------------------------------------|-----------------------|
| `--lower-bound`          | Investimento minimo per asset selezionato        | 0.0                   |
| `--upper-bound`          | Investimento massimo per asset selezionato       | 0.7                   |
| `--min-selected-assets`  | Numero minimo di asset da selezionare            | nessun vincolo        |
| `--max-selected-assets`  | Numero massimo di asset da selezionare           | nessun vincolo        |

**Semantica dei limiti:**

- I limiti sono condizionali alla selezione: `lower_bound * delta <= x <= upper_bound * delta`
- Con `lower_bound > 0`, un asset selezionato (δ=1) ha sempre investimento positivo
- Con `lower_bound = 0`, una binaria può essere attiva anche con peso nullo
- `lower_bound = upper_bound` rappresenta investimento fisso per asset selezionato

**Semantica della cardinalità:**

- `min_selected_assets`: aggiunge vincolo `sum_i delta_i >= min`
- `max_selected_assets`: aggiunge vincolo `sum_i delta_i <= max`
- Per cardinalità esatta, impostare min = max
- Il dominio candidato (riduzione) è distinto dalla cardinalità finale: 40 candidati
  possono alimentare un portfolio di 10 asset selezionati

**Esempio con cardinalità e soglie positive:**

```bash
poetry run python -m qreduce.experiments.portfolio \
  --run-id cardinality_test \
  --asset-count 100 \
  --lower-bound 0.05 \
  --upper-bound 0.25 \
  --min-selected-assets 5 \
  --max-selected-assets 15
```

**Esempio con cardinalità esatta e investimento fisso:**

```bash
poetry run python -m qreduce.experiments.portfolio \
  --run-id exact_cardinality \
  --asset-count 50 \
  --lower-bound 0.10 \
  --upper-bound 0.10 \
  --min-selected-assets 10 \
  --max-selected-assets 10
```

### Opzioni del grafo

| Opzione                                        | Descrizione                     | Default         |
|------------------------------------------------|---------------------------------|-----------------|
| `--graph-edge-mode`                            | `correlation_only`, `near_duplicate` | `near_duplicate` |
| `--correlation-threshold`                      | Soglia correlazione assoluta    | 0.90            |
| `--near-duplicate-max-relative-return-difference`  | Diff. relativa rendimento   | 0.10            |
| `--near-duplicate-max-relative-variance-difference`| Diff. relativa varianza     | 0.10            |

### Opzioni solver

| Opzione                  | Descrizione                                      | Default               |
|--------------------------|--------------------------------------------------|-----------------------|
| `--mis-solver-id`        | `local_greedy`, `dwave_simulated_annealing`      | `local_greedy`        |
| `--classical-solver-id`  | `cplex`, `scip`                                  | `scip`                |
| `--mis-num-reads`        | D-Wave num_reads (richiede dwave_simulated_annealing) |                  |
| `--mis-num-sweeps`       | D-Wave num_sweeps (richiede dwave_simulated_annealing) |                 |

### Opzioni reduction policy

| Opzione                                | Descrizione                           | Default               |
|----------------------------------------|---------------------------------------|-----------------------|
| `--max-reduction-rounds`               | Numero massimo di round               | 1                     |
| `--candidate-domain-min-items`         | Minimo item nel dominio candidato     | 1                     |
| `--candidate-domain-max-items`         | Massimo item nel dominio candidato    | 60% di asset_count    |
| `--target-binary-variables`            | Target variabili binarie              | 3                     |
| `--min-reduction-ratio`                | Rapporto minimo di riduzione          | 0.1                   |
| `--max-end-to-end-runtime-seconds`     | Timeout totale                        | 60.0                  |
| `--recovery-policy-on-domain-too-small`| `fail`, `retry_with_larger_domain`    | `fail`                |
| `--recovery-policy-on-infeasible`      | `fail`, `retry_with_larger_domain`    | `fail`                |
| `--max-recovery-attempts`              | Massimo tentativi di recovery         | 0                     |

## Esempi

### D-Wave simulated annealing con CPLEX

```bash
poetry run python -m qreduce.experiments.portfolio \
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

### Multi-round con recovery

```bash
poetry run python -m qreduce.experiments.portfolio \
  --run-id multi_with_recovery \
  --asset-count 50 \
  --max-reduction-rounds 5 \
  --recovery-policy-on-infeasible retry_with_larger_domain \
  --max-recovery-attempts 3
```

## Export del modello residuo

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

## API Python

L'entry point principale è `run_portfolio_experiment`:

```python
from dataclasses import replace

from qreduce.experiments.portfolio import (
    build_synthetic_portfolio_inputs,
    run_portfolio_experiment,
)

# Single-pass (default) - usa la policy predefinita
run = run_portfolio_experiment("run_001", asset_count=30)

# Classical-only - crea policy con max_reduction_rounds=0
inputs = build_synthetic_portfolio_inputs("_defaults", asset_count=30)
classical_policy = replace(inputs.config.reduction, max_reduction_rounds=0)
run = run_portfolio_experiment("baseline", reduction_policy=classical_policy)

# Multi-round - modifica max_reduction_rounds e abilita recovery
inputs = build_synthetic_portfolio_inputs("_defaults", asset_count=30)
multi_policy = replace(
    inputs.config.reduction,
    max_reduction_rounds=3,
    recovery_policy_on_infeasible="retry_with_larger_domain",
    max_recovery_attempts=2,
)
run = run_portfolio_experiment("multi", reduction_policy=multi_policy)
```

## Riferimenti

- Execution: `src/qreduce/experiments/portfolio/execution.py`
- Adapter: `src/qreduce/experiments/portfolio/adapter.py`
- Modelli: `src/qreduce/experiments/portfolio/models.py`
- Analisi: `src/qreduce/experiments/portfolio/analysis.py`
- Post-check: `src/qreduce/experiments/portfolio/postcheck.py`
