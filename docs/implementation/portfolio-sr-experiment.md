# Esperimento Portfolio Sharpe Ratio

Esperimento dimostrativo per la demo Intesa Sanpaolo. Massimizza lo Sharpe ratio
con dati reali S&P500, vincoli settoriali hard e cardinalità facoltativa.
A differenza dell'esperimento portfolio sintetico, usa pesi continui e una
trasformazione convessa del problema.

## Formulazione matematica

**Problema originale:**

```
max SR(x) = μ'x / √(x'Σx)
s.t. 1'x = 1
     0 ≤ x ≤ upper
     sector_min ≤ Σ_{i∈s} x_i ≤ sector_max  (per ogni settore s)
     |{i: x_i > 0}| ≤ K                      (cardinalità, opzionale)
```

**Trasformazione convessa** (Cornuejols & Tütüncü):

```
min y'Σy
s.t. μ'y = 1
     1'y = k   (k = variabile ausiliaria)
     0 ≤ y ≤ k·upper
     sector_min·k ≤ Σ_{i∈s} y_i ≤ sector_max·k

Recovery: x = y/k, SR = 1/√(obj)
Bounds su k: [1/μ_max, 1/μ_min]
```

Con cardinalità, si aggiungono variabili binarie δ_i:
- y_i ≤ M_i·δ_i dove M_i = upper_i / μ_min
- Σ δ_i ≤ K

## Struttura del modulo

```
src/qreduce/experiments/portfolio_sr/
├── __init__.py          # Public exports
├── datasets.py          # CSV loader S&P500 con validazione
├── models.py            # Contratti dati (SharpePortfolioProblem, ...)
├── formulation.py       # Trasformazione e ricostruzione
├── graph_policy.py      # Costruzione grafo MWIS
├── adapter.py           # ReducibleProblemAdapter
├── postcheck.py         # Validazione soluzione finale
├── inputs.py            # Factory per input esperimento
├── execution.py         # Orchestrazione run
├── benchmark.py         # Suite benchmark confronti
├── analysis.py          # Caricamento e analisi risultati
├── __main__.py          # CLI
└── README.md            # Confronto metodologico Corbelletto
```

## Dataset S&P500

Il file `data/yahoo/SP500.csv` contiene prezzi storici:
- 480 ticker, 11 settori, denominazione USD
- Date in formato DD/MM/YYYY, separatore `;`, encoding UTF-8 con BOM
- Colonne: Societa, Ticker Yahoo, Settore, Data, Open, High, Low, Close,
  Volume, Adjusted Close, Currency

Il loader valida:
- Schema colonne e encoding
- Date parsabili e ordinabili
- Allineamento serie temporali per ticker
- Duplicati

Le statistiche dei rendimenti (media, covarianza) sono calcolate su rendimenti
log o semplici, con annualizzazione e filtro per media positiva.

## Policy di riduzione

La policy costruisce un grafo MWIS sui ticker basandosi su:
- **Pesi:** Sharpe ratio individuale (μ_i / σ_i), normalizzato
- **Archi:** Due modalità
  - `correlation_only`: arco se |ρ_ij| > soglia
  - `near_duplicate`: arco se correlazione alta E rendimenti/volatilità simili

La cardinalità e i vincoli settoriali sono vincoli hard del problema
trasformato, non penalità nella riduzione MWIS.

## Differenze da Corbelletto et al. (2024)

| Aspetto | QReduce portfolio_sr | Corbelletto et al. |
|---------|---------------------|--------------------|
| Obiettivo | Sharpe ratio | Media-varianza |
| Pesi | Continui | Discretizzati |
| Correlazione | Solo constraint MWIS | QUBO penalità |
| QUBO settoriale | No (hard constraint) | Sì |
| Cardinalità | Opzionale, hard | Sì, penalità QUBO |
| Annealers | Non necessari | Usati |
| Dichiarazione speedup | No | Sì |

Il README del package (`src/qreduce/experiments/portfolio_sr/README.md`)
contiene il confronto metodologico completo.

## Comandi CLI

Baseline classica:
```bash
poetry run python -m qreduce.experiments.portfolio_sr \
    --csv-path data/yahoo/SP500.csv \
    --asset-count 50 \
    --run-id baseline-50 \
    --max-reduction-rounds 0
```

Con riduzione:
```bash
poetry run python -m qreduce.experiments.portfolio_sr \
    --csv-path data/yahoo/SP500.csv \
    --asset-count 50 \
    --run-id reduced-50 \
    --max-reduction-rounds 1 \
    --correlation-threshold 0.8
```

Con cardinalità:
```bash
poetry run python -m qreduce.experiments.portfolio_sr \
    --csv-path data/yahoo/SP500.csv \
    --asset-count 50 \
    --max-positions 10 \
    --run-id card-50-10 \
    --max-reduction-rounds 1
```

## Artifact prodotti

| File | Contenuto |
|------|-----------|
| `run_result.json` | Risultato pipeline |
| `config_used.json` | Configurazione |
| `problem.json` | Problema serializzato |
| `experiment_metadata.json` | Metadati run |
| `run_manifest.json` | Indice artifact |
| `round_NN_result.json` | Round riduzione |

## Test

```bash
poetry run pytest tests/experiments/portfolio_sr/ -v
```

I test coprono:
- Loader CSV e calcolo statistiche
- Trasformazione convessa e ricostruzione
- Validazione x_scale bounds
- Costruzione grafo adapter
- Validazione dominio e fixing manifest
- Modello classico con/senza cardinalità
- Vincoli settoriali

## Limiti noti

- Lo Sharpe ratio è una metrica ex-post; l'ottimizzazione non garantisce
  performance future
- La riduzione MWIS è euristica; non certifica ottimalità
- La cardinalità introduce variabili binarie che aumentano la complessità
- I vincoli settoriali possono rendere il problema infeasible se troppo
  restrittivi con un universo ridotto

## Configuratore HTML

`uix/experiment_portfolio_sr.html` genera comandi CLI con 4 tab:
- Dati: CSV, date, universo
- Problema: cardinalità, settori
- Riduzione: policy, soglie
- Solver: SCIP/CPLEX, timeout

Le formule matematiche sono renderizzate con MathJax.

## Accettazione artifact e analisi

I test verticali pubblicano realmente gli artifact su disco tramite il runner,
li ricaricano e analizzano baseline, screening trasformato con esclusioni e
screening non ammissibile per perdita di un settore obbligatorio. Sono verificati
obiettivo ricalcolato, metriche finanziarie, budget, vincoli settoriali, pesi
esclusi nulli, conteggi originali/residui, manifest e provenance.

L'analisi usa `original_problem` per i metadati finanziari degli screening.
Pesi ed esposizioni richiedono una soluzione adottata, post-check passato e
valori completi e finiti per scala e variabili scalate; una soluzione diagnostica
non è un portafoglio valido. I settori a esposizione zero restano visibili.
La soglia di visualizzazione dei pesi non rinormalizza il portafoglio.
Le classifiche escludono i fallimenti; un runtime pari a zero è valido.

Il loader usa parsing CSV con quoting, esclude le serie incomplete riportandone
il motivo in `source_dataset.exclusion_reasons` (codice
`incomplete_price_history`) e richiede metadati settoriali coerenti nella finestra
selezionata. La covarianza campionaria richiede almeno due rendimenti (tre prezzi).
NumPy è una dipendenza diretta del gruppo `experiments`.

Il notebook `notebooks/experiments/portfolio_sr/001_artifact_analysis.ipynb`
carica gli artifact già prodotti e importa la logica dai moduli Python.
