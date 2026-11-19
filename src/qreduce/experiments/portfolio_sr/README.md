# Portfolio Sharpe Ratio Experiment (portfolioSR)

Esperimento dimostrativo per ottimizzazione Sharpe ratio con riduzione QReduce,
sviluppato per discussione tecnica con Intesa Sanpaolo e Davide Corbelletto.

## Obiettivo

Misurare l'effetto della riduzione di dominio QReduce su qualità, fattibilità e
costo computazionale di un problema di massimizzazione dello Sharpe ratio usando
dati reali S&P500.

## Caratteristiche principali

- **Dati reali**: dataset S&P500 con prezzi storici di 480 titoli
- **Pesi continui**: allocazioni calcolate dal solver classico (no codifica binaria)
- **Sharpe ratio**: unico obiettivo finanziario
- **Diversificazione settoriale**: vincoli hard nel solver finale (non penalità MWIS)
- **Cardinalità facoltativa**: limite massimo posizioni (quando abilitato)
- **QUBO MWIS ausiliaria**: problema di riduzione distinto dall'obiettivo finanziario

## Confronto metodologico con l'articolo di Corbelletto

### Riferimento bibliografico

Mattesi et al., "Diversifying Investments and Maximizing Sharpe Ratio: A Novel
Quadratic Unconstrained Binary Optimization Formulation", *Quantum Reports*,
2024, 6(2), 244-262. DOI: [10.3390/quantum6020018](https://doi.org/10.3390/quantum6020018)

Davide Corbelletto è tra i coautori.

### Tabella di confronto

| Aspetto | Articolo | portfolioSR |
|---------|----------|-------------|
| **Allocazioni** | Codifica binaria di variabili scalate | Variabili continue |
| **QUBO** | Formulazione finanziaria integrata | MWIS ausiliaria di riduzione |
| **Diversificazione** | Componente dell'obiettivo (penalità) | Limiti settoriali hard |
| **Cardinalità** | Non obbligatoria nella formulazione principale | Massimo facoltativo |
| **Allocazione finale** | Ricostruita dalla soluzione codificata | Calcolata dal solver classico |
| **Focus** | Formulazione e soluzione proposte nel paper | Compromesso riduzione/qualità/tempo |

### Distinzione metodologica

Il paper propone una formulazione QUBO che integra l'obiettivo finanziario
(Sharpe ratio) con un termine di diversificazione settoriale:

```
H = -H_r + λH_σ + γH_d + penalità di normalizzazione
```

Dove:
- `H_r`: contributo del rendimento
- `H_σ`: contributo della varianza
- `H_d`: penalità di diversificazione settoriale
- La penalità di normalizzazione incorpora il vincolo di budget

**portfolioSR adotta un approccio diverso:**

1. **Formulazione continua**: massimizza lo Sharpe ratio con variabili continue,
   trasformando il problema in un QP convesso:

   ```
   minimize  x_scaled^T Σ x_scaled
   subject to μ^T x_scaled = 1
              vincoli lineari su x_scaled e x_scale
   ```

2. **MWIS per riduzione del dominio**: la QUBO MWIS seleziona quali titoli
   mantenere disponibili per l'ottimizzazione, non determina le allocazioni.

3. **Settori come vincoli hard**: i limiti settoriali sono vincoli lineari nel
   problema residuo, non componenti dell'obiettivo.

### Perché la distinzione è importante

- La **penalità di normalizzazione** nel paper incorpora un vincolo (budget = 1)
  mentre la **componente settoriale** esprime una preferenza finanziaria aggiuntiva.
  Non confondere le due finalità.

- portfolioSR è una **variante ispirata al paper**, non una replica esatta:
  sostituisce la diversificazione morbida con vincoli e rimuove la
  discretizzazione dei pesi.

- Non confrontare direttamente gli obiettivi numerici dei due modelli come se
  fossero equivalenti.

- Non dichiarare superiorità sul metodo del paper.

## Formulazione matematica

### Problema originale

```
maximize SR(x) = (μ^T x) / √(x^T Σ x)

subject to  Σᵢ xᵢ = 1
            0 ≤ xᵢ ≤ upperᵢ
            sector_minₛ ≤ Σᵢ∈ₛ xᵢ ≤ sector_maxₛ
```

Con tutti i rendimenti medi `μᵢ > 0` (filtro applicato in preprocessing).

### Trasformazione convessa

Definendo `x_scale = 1/(μ^T x)` e `x_scaled = x_scale · x`:

```
minimize  x_scaled^T Σ x_scaled

subject to  μ^T x_scaled = 1
            Σᵢ x_scaledᵢ = x_scale
            0 ≤ x_scaledᵢ ≤ upperᵢ · x_scale
            1/μ_max ≤ x_scale ≤ 1/μ_min
            sector_minₛ · x_scale ≤ Σᵢ∈ₛ x_scaledᵢ ≤ sector_maxₛ · x_scale
```

Ricostruzione: `xᵢ = x_scaledᵢ / x_scale`, `SR = 1/√(obiettivo)`.

### Cardinalità facoltativa

Quando abilitata (`max_positions ≠ None`):

```
δᵢ ∈ {0, 1}
Σᵢ δᵢ ≤ K
x_scaledᵢ ≤ Mᵢ · δᵢ   dove Mᵢ = upperᵢ / μ_min
```

Una binaria attiva (`δᵢ = 1`) può avere peso zero: il vincolo garantisce
**al massimo** K pesi positivi.

## Dataset

- **Sorgente**: `data/yahoo/SP500.csv`
- **Formato**: CSV separato da `;`, encoding UTF-8 (con BOM opzionale)
- **Colonne**: Societa, Ticker Yahoo, Settore, Data, Open, High, Low, Close,
  Volume, Adjusted Close, Currency
- **Date**: formato DD/MM/YYYY
- **Periodo**: 2 gennaio 2020 - 30 giugno 2026
- **Ticker**: 480 titoli, 11 settori, valuta USD
- **Allineamento**: stesso calendario per tutti i titoli

Il file contiene prezzi, non rendimenti. Il preprocessing:
1. Applica l'intervallo temporale richiesto
2. Calcola rendimenti (semplici o logaritmici)
3. Annualizza media e covarianza (252 giorni default)
4. Filtra titoli con media annualizzata strettamente positiva
5. Valida che la covarianza sia PSD

## Uso

### CLI

```bash
# Single-pass con 50 asset (default)
poetry run python -m qreduce.experiments.portfolio_sr --run-id run001

# Classical-only baseline
poetry run python -m qreduce.experiments.portfolio_sr --run-id baseline001 \
    --max-reduction-rounds 0

# Con vincolo cardinalità
poetry run python -m qreduce.experiments.portfolio_sr --run-id card001 \
    --max-positions 15

# Con vincoli settoriali
poetry run python -m qreduce.experiments.portfolio_sr --run-id sector001 \
    --sector-min "Technology=0.10,Health Care=0.05" \
    --sector-max "Technology=0.30,Health Care=0.20"
```

### Programmatico

```python
from qreduce.experiments.portfolio_sr import (
    build_sharpe_portfolio_inputs,
    run_sharpe_portfolio_experiment,
)

# Esecuzione diretta
run = run_sharpe_portfolio_experiment(
    "my_run",
    asset_count=50,
    max_positions=15,
)

# Con inputs pre-costruiti (per benchmark)
inputs = build_sharpe_portfolio_inputs(
    asset_count=100,
    return_convention="log",
)
```

## Struttura del package

```
src/qreduce/experiments/portfolio_sr/
├── __init__.py          # Export pubblici
├── __main__.py          # CLI
├── adapter.py           # ReducibleProblemAdapter implementation
├── analysis.py          # Caricamento e analisi artifact
├── benchmark.py         # Confronti baseline
├── datasets.py          # Loader CSV S&P500
├── execution.py         # Orchestrazione esperimento
├── formulation.py       # Trasformazione e ricostruzione
├── graph_policy.py      # Costruzione grafo MWIS
├── inputs.py            # Factory input
├── models.py            # Contratti dati
├── postcheck.py         # Validazione soluzione
└── README.md            # Questo file
```

## Limiti e avvertenze

- Il dataset contiene prezzi storici; provenienza e continuità dei ticker non
  sono verificabili dal solo CSV.
- La classificazione settoriale è statica.
- Un sottouniverso piccolo può non rappresentare tutti i settori richiesti.
- La riduzione MWIS propone un dominio candidato; non certifica l'ottimalità.
- Ogni fixing derivato euristicamente non preserva l'ottimalità globale.
- Senza cardinalità il residuo è continuo: il beneficio della riduzione non è
  scontato.
- Non dichiarare vantaggio quantistico.

## Confronti benchmark

Il modulo `benchmark.py` fornisce:
1. **Full baseline**: problema completo senza riduzione
2. **QReduce**: riduzione MWIS e solve residuo
3. **Sharpe screening**: selezione top-K per Sharpe individuale
4. **Random screening**: selezione casuale con seed
5. **Correlation screening**: selezione greedy diversificata

Ogni confronto usa gli stessi dati, vincoli e solver finale.

## Riferimenti

- Specifiche complete: [`docs/specifications.md`](../../../docs/specifications.md)
- Guida operativa: [`docs/experiments/portfolio-sr.md`](../../../docs/experiments/portfolio-sr.md)
- Configuratore HTML: [`uix/experiment_portfolio_sr.html`](../../../uix/experiment_portfolio_sr.html)

## Artifact verificabili

I test verticali in `tests/experiments/portfolio_sr/test_vertical_artifacts.py`
eseguono pubblicazione, caricamento e analisi su disco con SCIP: baseline,
screening con esclusioni e screening che elimina un settore obbligatorio.
Verificano metriche e obiettivo senza assertion condizionali sulla loro presenza.
L'analisi presenta solo soluzioni adottate con post-check superato e valori
completi e finiti. Le esposizioni usano sempre i settori del problema originale;
le classifiche escludono i fallimenti e trattano correttamente runtime zero.

NumPy è dichiarato direttamente nel gruppo `experiments`. Il loader registra
nei metadati le esclusioni delle serie incomplete, gestisce CSV con quoting e
richiede settori coerenti e almeno tre prezzi per la covarianza campionaria.

Il notebook di presentazione è
`notebooks/experiments/portfolio_sr/001_artifact_analysis.ipynb`.
