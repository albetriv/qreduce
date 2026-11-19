# Esperimento portfolio Sharpe ratio (portfolioSR)

L'esperimento portfolioSR ottimizza il rapporto Sharpe usando dati reali
S&P500. Misura l'effetto della riduzione QReduce su qualità e costo
computazionale per un problema di massimizzazione Sharpe con vincoli
settoriali e cardinalità facoltativa.

## Problema di dominio

L'obiettivo è massimizzare lo Sharpe ratio:

```text
SR(x) = (μ' * x) / √(x' * Σ * x)
```

dove `μ` sono i rendimenti medi annualizzati, `Σ` la covarianza annualizzata,
`x` i pesi del portafoglio. A differenza del portfolio media-varianza
tradizionale, non c'è un parametro di avversione al rischio: l'obiettivo è
un rapporto adimensionale.

### Trasformazione convessa

Il problema non lineare viene trasformato in un QP convesso. Definendo
`x_scale = 1/(μ' * x)`:

```text
minimize  x_scaled' * Σ * x_scaled
subject to  μ' * x_scaled = 1
            vincoli lineari su pesi e scale
```

La ricostruzione: `x = x_scaled / x_scale` e `SR = 1/√(obiettivo)`.

### Vincoli

- **Budget**: somma dei pesi = 1
- **Upper bounds**: peso massimo per asset
- **Settori**: limiti min/max per esposizione settoriale (opzionale)
- **Cardinalità**: massimo numero di posizioni (opzionale)

## Dataset

Il dataset è il file CSV S&P500 in `data/yahoo/SP500.csv`:

- 480 ticker con prezzi dal 2020 al 2026
- 11 settori, valuta USD
- Adjusted close per calcolo rendimenti

Il preprocessing:
1. Filtra per intervallo temporale
2. Calcola rendimenti (log o semplici)
3. Annualizza a 252 giorni
4. Esclude ticker con media non positiva
5. Valida covarianza PSD

## CLI

```bash
poetry run python -m qreduce.experiments.portfolio_sr --help
```

| Valore                     | Modalità                         |
|----------------------------|----------------------------------|
| `--max-reduction-rounds 0` | Classical-only baseline          |
| `--max-reduction-rounds 1` | Single-pass (default)            |
| `--max-reduction-rounds N` | Multi-round (N > 1)              |

### Classical-only baseline

```bash
poetry run python -m qreduce.experiments.portfolio_sr \
  --run-id sr_baseline \
  --asset-count 50 \
  --max-reduction-rounds 0
```

### Single-pass con riduzione

```bash
poetry run python -m qreduce.experiments.portfolio_sr \
  --run-id sr_reduced \
  --asset-count 50 \
  --correlation-threshold 0.80 \
  --edge-mode near_duplicate
```

### Con vincolo cardinalità

```bash
poetry run python -m qreduce.experiments.portfolio_sr \
  --run-id sr_cardinality \
  --asset-count 100 \
  --max-positions 20
```

### Con vincoli settoriali

```bash
poetry run python -m qreduce.experiments.portfolio_sr \
  --run-id sr_sectors \
  --asset-count 50 \
  --sector-min "Technology=0.10,Health Care=0.05" \
  --sector-max "Technology=0.30,Health Care=0.20"
```

### Multi-round con recovery

```bash
poetry run python -m qreduce.experiments.portfolio_sr \
  --run-id sr_recovery \
  --asset-count 100 \
  --max-reduction-rounds 3 \
  --recovery-policy-on-infeasible retry_with_larger_domain \
  --max-recovery-attempts 2
```

## Opzioni CLI

### Opzioni dati

| Opzione | Default | Descrizione |
|---------|---------|-------------|
| `--csv-path` | `data/yahoo/SP500.csv` | File CSV prezzi |
| `--asset-count` | 50 | Numero asset da selezionare |
| `--explicit-tickers` | - | Lista ticker esplicita (alternativa ad asset-count) |
| `--start-date` | - | Data inizio (YYYY-MM-DD) |
| `--end-date` | - | Data fine (YYYY-MM-DD) |
| `--return-convention` | `log` | Tipo rendimento: `log` o `simple` |
| `--annualization-factor` | 252 | Giorni per annualizzazione |
| `--selection-order` | `alphabetical` | Ordine selezione: `alphabetical`, `sharpe_descending`, `random` |
| `--random-seed` | - | Seed per selezione random |

### Opzioni problema

| Opzione | Default | Descrizione |
|---------|---------|-------------|
| `--upper-bound` | 1.0 | Peso massimo per asset |
| `--max-positions` | - | Massimo posizioni (cardinalità) |
| `--risk-free-rate` | 0.0 | Tasso risk-free |
| `--sector-min` | - | Minimi settoriali (es. `Tech=0.10,Health=0.05`) |
| `--sector-max` | - | Massimi settoriali |

### Opzioni grafo

| Opzione | Default | Descrizione |
|---------|---------|-------------|
| `--edge-mode` | `near_duplicate` | Semantica archi: `correlation_only` o `near_duplicate` |
| `--correlation-threshold` | 0.80 | Soglia correlazione positiva |
| `--near-duplicate-max-return-diff` | 0.15 | Max differenza rendimento relativa |
| `--near-duplicate-max-variance-diff` | 0.15 | Max differenza varianza relativa |

### Opzioni solver

| Opzione | Default | Descrizione |
|---------|---------|-------------|
| `--mis-solver-id` | `local_greedy` | Solver MIS |
| `--classical-solver-id` | `scip` | Solver classico: `scip` o `cplex` |
| `--classical-time-limit-seconds` | 60.0 | Time limit per solve |

### Opzioni riduzione

| Opzione | Default | Descrizione |
|---------|---------|-------------|
| `--max-reduction-rounds` | 1 | Rounds riduzione (0=baseline) |
| `--candidate-domain-min-items` | 1 | Minimo item dominio candidato |
| `--candidate-domain-max-items` | 60% assets | Massimo item dominio |
| `--max-end-to-end-runtime-seconds` | 120.0 | Timeout totale |
| `--recovery-policy-on-infeasible` | `fail` | Policy recovery |
| `--max-recovery-attempts` | 0 | Tentativi recovery |

## Artifact

Gli artifact sono pubblicati in `outputs/portfolio_sr/<run_id>/`:

```
run_manifest.json        # Metadati e hash
config_used.json         # Configurazione risolta
problem.json             # Problema originale
run_result.json          # Risultato finale
experiment_metadata.json # Dataset e preprocessing
round_00_result.json     # Risultato round (se riduzione)
```

## Analisi dei risultati

```python
from qreduce.experiments.portfolio_sr.analysis import (
    load_sharpe_portfolio_analysis,
    compare_runs,
)

# Carica un run
analysis = load_sharpe_portfolio_analysis("outputs/portfolio_sr/my_run")

print(f"Sharpe ratio: {analysis.sharpe_ratio}")
print(f"Posizioni: {analysis.position_count}")

# Confronta più run
comparison = compare_runs([
    "outputs/portfolio_sr/baseline",
    "outputs/portfolio_sr/reduced",
])
best = comparison.best_sharpe
print(f"Best Sharpe: {best.run_id if best is not None else None}")
```

## Benchmark

Il modulo `benchmark.py` fornisce confronti strutturati:

```python
from qreduce.experiments.portfolio_sr.benchmark import (
    BenchmarkConfig,
    run_benchmark_suite,
)

config = BenchmarkConfig(
    asset_count=50,
    target_retention_fraction=0.5,
)

results = run_benchmark_suite("bench_001", config)
```

Metodi confrontati:
1. **Full baseline**: problema completo senza riduzione
2. **QReduce**: riduzione MWIS + solve residuo
3. **Sharpe screening**: top-K per Sharpe individuale
4. **Random screening**: selezione casuale con seed
5. **Correlation screening**: selezione greedy diversificata

## Configuratore HTML

Il configuratore [`uix/experiment_portfolio_sr.html`](../../uix/experiment_portfolio_sr.html)
genera comandi CLI interattivamente. È una pagina statica apribile da
filesystem.

## Differenze dal portfolio sintetico

| Aspetto | portfolio | portfolio_sr |
|---------|-----------|--------------|
| **Dati** | Sintetici | Reali S&P500 |
| **Obiettivo** | Media-varianza (risk_aversion) | Sharpe ratio |
| **Vincoli** | Budget, bounds | Budget, bounds, settori, cardinalità |
| **Trasformazione** | Nessuna | QP convesso |
| **Variabile ausiliaria** | No | x_scale |

## Limiti

- Dataset con provenienza e continuità non verificabili
- Classificazione settoriale statica
- Riduzione MWIS non certifica ottimalità
- Senza cardinalità il residuo è puramente continuo

Vedere il [README del package](../../src/qreduce/experiments/portfolio_sr/README.md)
per il confronto metodologico con l'articolo di Corbelletto.

## Notebook e validazione

Il notebook `notebooks/experiments/portfolio_sr/001_artifact_analysis.ipynb`
mostra configurazione, metriche, pesi ed esposizioni degli artifact persistiti.
Non esegue solver e non duplica logica finanziaria.

Per baseline e screening, l'analisi ricostruisce le esposizioni dai metadati del
problema originale. Soluzioni incomplete, non finite, non adottate o con
post-check fallito non vengono presentate come portafogli. Le classifiche
escludono i fallimenti e accettano runtime validi pari a zero.

Il loader gestisce campi CSV quotati, segnala le serie incomplete escluse nei
metadati e rifiuta settori incoerenti per lo stesso ticker nella finestra scelta.
Servono almeno tre prezzi per stimare una covarianza campionaria.
