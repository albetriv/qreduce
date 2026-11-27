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
- **Cardinalità facoltativa**: minimo e massimo di asset selezionati, configurabili separatamente
- **Minimo condizionale facoltativo**: ogni peso è zero oppure almeno il minimo applicabile al titolo, anche senza cardinalità
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

1. **Pesi continui e selezioni binarie**: massimizza lo Sharpe ratio
   trasformando il problema in un MIQP:

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

```text
maximize SR(x) = (mu^T * x) / sqrt(x^T * Sigma * x)
subject to  sum_i x_i = 1
            lower_i * delta_i <= x_i <= upper_i * delta_i
            delta_i in {0, 1}
            sum_i delta_i >= K_min  [se impostato]
            sum_i delta_i <= K_max  [se impostato]
            sector_min_s <= sum_{i in s} x_i <= sector_max_s  [se configurato]
```

Le selezioni binarie sono sempre presenti, anche con minimi nulli e senza
cardinalità. Se una selezione è zero il peso è zero; se è uno valgono i limiti
del titolo. Con minimo zero è possibile selezionare un titolo a peso zero.
La cardinalità conta le selezioni, non i pesi positivi; minimo e massimo uguali
impongono cardinalità esatta. Tutti i rendimenti medi sono positivi dopo il
filtro di preprocessing.

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

### Selezione, minimo e cardinalità facoltativi

Le binarie non sono scalate e il modello è sempre un MIQP. I settori sono
facoltativi e i loro limiti sono moltiplicati per `x_scale`. Posti `lower_i`
uguale al minimo effettivo del titolo e
`x_scale_max = 1 / mu_min`:

```text
delta_i in {0, 1}
x_scaled_i <= upper_i * x_scale_max * delta_i
x_scaled_i >= lower_i * x_scale - lower_i * x_scale_max * (1 - delta_i)  [se lower_i > 0]
sum_i delta_i >= K_min  [se min_selected_assets = K_min > 0]
sum_i delta_i <= K_max  [se max_positions = K_max]
```

Il vincolo superiore scalato `x_scaled_i <= upper_i * x_scale` resta in vigore.
Un titolo con minimo zero può essere selezionato anche a peso zero. Quindi
`min_selected_assets` da solo non impone altrettante posizioni investite;
per imporre un peso positivo a ogni titolo selezionato, impostare un minimo
positivo per tutti i titoli. Il target predefinito di binarie residue è 3.

La CLI espone `--min-selected-assets` e `--max-selected-assets`;
`--max-positions` resta un alias del massimo. Se si passano entrambi i nomi
del massimo, i valori devono coincidere. In Python i parametri sono
`min_selected_assets` e `max_positions`. Il minimo è un intero non negativo,
zero equivale a ometterlo; il massimo, se impostato, è un intero positivo.
Nessuno dei due può superare la numerosità dell'universo del problema e il
minimo non può superare il massimo.

`lower_bound` è il minimo uniforme (default `0.0`, opzione CLI `--lower-bound`).
CLI e configuratore UIX accettano un `--upper-bound` uniforme, finito e
positivo (default `1.0`). Un valore superiore a `1` è ridondante con budget
unitario e pesi non negativi, ma viene passato al modello senza modificarlo.
In Python si può fornire `lower_bounds`, una mappa da ticker a minimo: i ticker
omessi hanno minimo zero, quelli sconosciuti sono rifiutati. Ogni minimo deve
essere finito, tra 0 e 1, e non superare il corrispondente limite superiore.
Il modello Python accetta anche singoli limiti superiori pari a zero, purché
la capacità complessiva sia sufficiente. Un `lower_bound` positivo non può
essere combinato con una mappa esplicita, neppure vuota. Una mappa vuota o
composta soltanto da zeri equivale all'omissione del parametro.

I controlli preliminari su budget e conflitti settoriali evidenti valgono anche
per il dominio ridotto, ma non sostituiscono il solver. La riduzione fissa
pesi e binarie degli esclusi a zero; gli altri titoli rimangono candidati. Il
modello rifiuta un manifest che non separa tutti i ticker in trattenuti ed
esclusi o che non fissa esattamente a zero il peso scalato e la binaria di ogni
escluso. Questo controllo riguarda la compilazione di nuovi modelli, non la
lettura degli artefatti storici. Un
dominio candidato deve contenere almeno `min_selected_assets` titoli, ma questo
non garantisce che il solver possa soddisfare budget, limiti individuali e
vincoli settoriali. Un tetto esplicito inferiore al minimo è rifiutato con
riduzione attiva; nella baseline non limita le selezioni. Il postcheck controlla i pesi ricostruiti e distingue
integrità delle binarie e violazioni dei vincoli.

`problem.json` conserva `max_positions` come chiave del massimo e omette
`min_selected_assets`, `lower_bound` e `lower_bounds` quando inattivi. Le run
storiche senza questi campi non hanno un minimo configurato. Il riepilogo di
analisi riporta le impostazioni del problema. La metrica `selected_count`
conta tutte le binarie valide pari a 1, incluse quelle associate a pesi nulli.
È disponibile solo se ci sono binarie e tutti i valori richiesti sono presenti
e validi. In tal caso compare anche in `validation.tolerances_used` e nel
riepilogo prodotto da `extract_solution_summary`. `position_count` conta
invece i pesi investiti sopra la tolleranza. Un `selected_count` mancante,
anche nelle run storiche, non equivale a zero.
Le run storiche senza binarie non registrano il conteggio delle selezioni, che
non va dedotto dai pesi positivi. A parità di pesi e Sharpe, assegnazioni
equivalenti delle binarie a peso zero possono produrre conteggi diversi.
Byte identici di `problem.json` descrivono lo stesso input, non dimostrano che
run di versioni diverse abbiano risolto lo stesso modello: export, mapping e
fixing possono differire.
Nel confronto UIX, una mappa `lower_bounds` è mostrata per ticker, con minimo
zero per i ticker omessi, anziché come minimo uniforme.
Il confronto usa le tolleranze registrate dal postcheck: verifica la coerenza
peso–selezione sui pesi ricostruiti e il fixing degli esclusi sui pesi scalati
e sulle binarie. Per gli artefatti senza tali tolleranze mantiene i controlli
storici (soglia `1e-8` sui pesi ricostruiti, `0.5` per la selezione).

In `BenchmarkConfig`, `lower_bound`, `lower_bounds` e `min_selected_assets`
si passano per nome; gli argomenti posizionali preesistenti non cambiano.

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
# Solo cardinalità massima (alias: --max-positions)
poetry run python -m qreduce.experiments.portfolio_sr --run-id card001 \
    --max-selected-assets 15
# Solo cardinalità minima: le selezioni a peso zero contano
poetry run python -m qreduce.experiments.portfolio_sr --run-id minsel001 \
    --min-selected-assets 5

# Minimo per titolo, senza cardinalità
poetry run python -m qreduce.experiments.portfolio_sr --run-id min001 \
    --lower-bound 0.05

# Minimo per titolo e cardinalità
poetry run python -m qreduce.experiments.portfolio_sr --run-id mincard001 \
    --lower-bound 0.05 --min-selected-assets 5 --max-selected-assets 15

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
    lower_bound=0.05,
    min_selected_assets=5,
    max_positions=15,
)

# Minimi diversi per ticker: MSFT ha minimo zero
inputs = build_sharpe_portfolio_inputs(
    explicit_tickers=("AAPL", "MSFT", "NVDA"),
    lower_bounds={"AAPL": 0.05, "NVDA": 0.10},
    min_selected_assets=2,
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
- Anche senza cardinalità e con minimo zero il residuo contiene binarie; il
  beneficio della riduzione non è scontato.
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

- Specifiche complete: [`docs/specifications.md`](../../../../docs/specifications.md)
- Guida operativa: [`docs/experiments/portfolio-sr.md`](../../../../docs/experiments/portfolio-sr.md)
- Configuratore HTML: [`uix/experiment_portfolio_sr.html`](../../../../uix/experiment_portfolio_sr.html)

## Artifact verificabili

I test verticali in `tests/experiments/portfolio_sr/test_vertical_artifacts.py`
eseguono pubblicazione, caricamento e analisi su disco con SCIP: baseline,
screening con esclusioni e screening che elimina un settore obbligatorio.
Verificano metriche e obiettivo senza assertion condizionali sulla loro presenza.
L'analisi presenta solo soluzioni adottate con post-check superato e valori
completi e finiti. Le esposizioni usano sempre i settori del problema originale;
le classifiche escludono i fallimenti e trattano correttamente runtime zero.
I settori con esposizione zero restano visibili. La soglia di visualizzazione
dei pesi è solo un filtro e non rinormalizza il portafoglio.

NumPy è dichiarato direttamente nel gruppo `experiments`. Il loader registra
nei metadati le esclusioni delle serie incomplete, gestisce CSV con quoting e
richiede settori coerenti e almeno tre prezzi per la covarianza campionaria.

Il notebook di presentazione è
`notebooks/experiments/portfolio_sr/001_artifact_analysis.ipynb`.
