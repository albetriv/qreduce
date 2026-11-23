# Esperimento portfolio media-varianza

L'esperimento portfolio media-varianza (`portfolio_mv`) verifica la pipeline QReduce con un problema di
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
poetry run python -m qreduce.experiments.portfolio_mv --help
```

| Valore                     | Modalità                         |
|----------------------------|----------------------------------|
| `--max-reduction-rounds 0` | Classical-only baseline          |
| `--max-reduction-rounds 1` | Single-pass (default)            |
| `--max-reduction-rounds N` | Multi-round (N > 1)              |

### Caso dimostrativo: campioni Pulser fattibili e non fattibili

Questo è il caso predefinito del notebook [MWIS e Pasqal 2D](../../notebooks/experiments/portfolio_mv/001_mwis_pasqal_2d.ipynb).
Il portafoglio può investire in 4–7 asset, con pesi individuali del 4–30%.
La simulazione locale produce entrambi i tipi di selezione indipendente,
senza repair o completamento. Nel run salvato, su 5000 shot:

| Campioni raw | Shot | Quota |
|---|---:|---:|
| Indipendenti e fattibili | 3324 | 66,48% |
| Indipendenti ma non fattibili | 1325 | 26,50% |
| Con conflitti nel grafo | 351 | 7,02% |

Tra le 20 bitstring più frequenti, 4 sono verdi e 16 rosse. La riduzione
passa da 12 a 6 asset e uguaglia l'ottimo classico (`-0.1265045501`), con
postcheck superato. Il candidato selezionato dal ranking MWIS ha 10 asset e
non è un portafoglio fattibile: i campioni verdi esistono nel pool raw, ma
la pipeline non li privilegia. Il controllo `local_greedy` conserva lo stesso
dominio e obiettivo; non si osserva un vantaggio del campionatore.

Comandi dalla root del repository (usare ID nuovi per ripetere run già salvati):

```bash
(
  set -e
  set -- --asset-count 12 --generation-seed 42 --observation-count 120 \
    --risk-aversion 0.1 --lower-bound 0.04 --upper-bound 0.30 \
    --min-selected-assets 4 --max-selected-assets 7 \
    --graph-edge-mode correlation_only --correlation-threshold 0.88 \
    --classical-solver-id cplex --max-end-to-end-runtime-seconds 0 \
    --target-binary-variables 6 --candidate-domain-min-items 4 \
    --candidate-domain-max-items 6 --num-source-mis-candidates 1

  poetry run python -m qreduce.experiments.portfolio_mv "$@" \
    --max-reduction-rounds 0 --run-id 001_mixed_classic
  poetry run python -m qreduce.experiments.portfolio_mv "$@" \
    --max-reduction-rounds 1 --mis-solver-id pasqal_local --pasqal-shots 5000 \
    --run-id 001_mixed_pasqal_local
  poetry run python -m qreduce.experiments.portfolio_mv "$@" \
    --max-reduction-rounds 1 --mis-solver-id local_greedy --run-id 001_mixed_greedy
)
```

### Caso dimostrativo: da 12 a 4 asset con Pulser locale

Il portafoglio investe in esattamente 3 asset, ciascuno fra il 5% e il 45%.
Il grafo ha 2 archi (`correlation_only`, soglia 0.88) e non codifica la
cardinalità del portafoglio. QReduce usa un candidato MWIS per costruire
un dominio di al massimo 4 asset, poi risolve il MIQP residuo in CPLEX.

Da eseguire dalla root del repository; per nuove repliche usare ID non ancora presenti:

```bash
(
  set -e
  set -- --asset-count 12 --generation-seed 42 --observation-count 120 \
    --risk-aversion 1 --lower-bound 0.05 --upper-bound 0.45 \
    --min-selected-assets 3 --max-selected-assets 3 \
    --graph-edge-mode correlation_only --correlation-threshold 0.88 \
    --classical-solver-id cplex --max-end-to-end-runtime-seconds 0 \
    --target-binary-variables 4 --candidate-domain-min-items 3 \
    --candidate-domain-max-items 4 --num-source-mis-candidates 1

  poetry run python -m qreduce.experiments.portfolio_mv "$@" \
    --max-reduction-rounds 0 --run-id ptf_12_k3_classic
  poetry run python -m qreduce.experiments.portfolio_mv "$@" \
    --max-reduction-rounds 1 --mis-solver-id pasqal_local --pasqal-shots 1000 \
    --run-id ptf_12_k3_pasqal_local
  poetry run python -m qreduce.experiments.portfolio_mv "$@" \
    --max-reduction-rounds 1 --mis-solver-id local_greedy --run-id ptf_12_k3_greedy
)
```

Nel notebook [MWIS e Pasqal 2D](../../notebooks/experiments/portfolio_mv/001_mwis_pasqal_2d.ipynb)
impostare `RUN_ID = "ptf_12_k3_pasqal_local"` e `BASELINE_RUN_ID = "ptf_12_k3_classic"`.
Nel run di riferimento, su 1000 shot: 894 indipendenti ma non fattibili a
selezione fissata (rosso), 27 indipendenti e fattibili (verde), 79 con archi
violati (arancione). Il seed 42 controlla i dati, non i conteggi Pulser.

Il candidato scelto ha 10 asset e non è fattibile come portafoglio. Non è
usato come allocazione: il MIQP sceglie 3 dei 4 asset conservati, supera il
postcheck e uguaglia l'obiettivo della baseline (`-0.1127259018`). Anche
`local_greedy` raggiunge lo stesso risultato, e il simulatore è più lento
della baseline end-to-end. Questo caso mostra la riduzione senza perdita
sull'istanza, non un vantaggio del campionatore né una garanzia generale.

### Configuratore HTML

Il configuratore [`uix/experiment_portfolio_mv.html`](../../uix/experiment_portfolio_mv.html)
genera comandi CLI interattivamente. È una pagina statica apribile direttamente
da filesystem; seleziona i parametri e copia il comando nel terminale.

Formati disponibili:
- **Una riga**: comando inline per copia diretta
- **Multilinea**: comando formattato con continuazioni Bash/Zsh

Il configuratore include solo i flag con valori diversi dai default e non
verifica la disponibilità dei solver.

### Classical-only baseline (senza riduzione)

```bash
poetry run python -m qreduce.experiments.portfolio_mv \
  --run-id 001_classical \
  --asset-count 30 \
  --max-reduction-rounds 0
```

Il problema è risolto direttamente senza riduzione MWIS. Utile come baseline
per confronto.

### Single-pass (un round di riduzione)

```bash
poetry run python -m qreduce.experiments.portfolio_mv \
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
poetry run python -m qreduce.experiments.portfolio_mv \
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
| `--output-root`          | Directory radice degli artifact                  | `outputs/portfolio_mv`   |
| `--log-config`           | Percorso file YAML di configurazione logging     | `config/logging.yaml` |
| `--model-export`         | Esporta il modello residuo                       | disabilitato          |
| `--model-export-path`    | Percorso per export esterno                      |                       |

### Opzioni di generazione

| Opzione                  | Descrizione                                      | Default               |
|--------------------------|--------------------------------------------------|-----------------------|
| `--asset-count`          | Numero di asset nel portfolio                    | 30                    |
| `--risk-aversion`        | Coefficiente di avversione al rischio            | 1.0                   |
| `--generation-seed`      | Seed per la generazione                          | 42                    |
| `--observation-count`    | Numero di osservazioni storiche                  | 10 × asset_count      |

**Avversione al rischio:**

Il parametro `--risk-aversion` (λ) controlla il trade-off tra rendimento atteso
e varianza nella funzione obiettivo media-varianza:

```text
minimize  λ * x' * Σ * x - μ' * x
```

- Valori maggiori (λ > 1) penalizzano di più la varianza, producendo portfolio
  meno rischiosi ma con rendimento atteso potenzialmente inferiore.
- Valori minori (0 < λ < 1) riducono la penalizzazione della varianza, favorendo
  il rendimento atteso.
- Il parametro deve essere finito e strettamente positivo. Valori di zero o
  negativi sono rifiutati.
- Il default (1.0) mantiene la compatibilità con il comportamento originale,
  ma non garantisce contributi equivalenti tra rendimento e varianza: il
  bilanciamento dipende dalla scala dei dati.

Il valore viene salvato in `problem.json` ed è verificabile nelle analisi.
Il coefficiente numerico va interpretato rispetto alla scala temporale e alla
scala dei rendimenti e della covarianza usati.

**Esempio con alta avversione al rischio:**

```bash
poetry run python -m qreduce.experiments.portfolio_mv \
  --run-id high_risk_aversion \
  --asset-count 30 \
  --risk-aversion 2.5
```

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
poetry run python -m qreduce.experiments.portfolio_mv \
  --run-id cardinality_test \
  --asset-count 100 \
  --lower-bound 0.05 \
  --upper-bound 0.25 \
  --min-selected-assets 5 \
  --max-selected-assets 15
```

**Esempio con cardinalità esatta e investimento fisso:**

```bash
poetry run python -m qreduce.experiments.portfolio_mv \
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
| `--mis-embedding-profile`| Profilo embedding locale: `none`, `pegasus_p16`, `zephyr_z12` | `none`   |

**Embedding locale:**

Il parametro `--mis-embedding-profile` vincola il campionamento D-Wave a una
topologia hardware-like senza richiedere QPU o credenziali. I profili
disponibili sono:

- `none` (default): campionamento diretto del BQM logico, senza embedding.
- `pegasus_p16`: embedding su topologia Pegasus ideale con parametro m=16.
- `zephyr_z12`: embedding su topologia Zephyr ideale con parametro m=12.

L'embedding modella i vincoli di connettività e l'overhead delle catene, ma
non simula dinamiche quantistiche o tempi QPU. È un campionamento classico
vincolato alla struttura del grafo hardware.

Requisiti per profili diversi da `none`:
- `--mis-solver-id dwave_simulated_annealing`
- `--max-reduction-rounds >= 1` (riduzione attiva)

**Gestione del budget durante l'embedding:**

Quando è impostato un budget end-to-end (`--max-end-to-end-runtime-seconds > 0`),
il backend gestisce cooperativamente il tempo residuo:

- Il budget viene ricontrollato prima di ogni operazione costosa (ricerca
  embedding, calcolo chain strength, campionamento).
- Il tempo residuo limita la durata della ricerca dell'embedding: se rimane
  poco budget, la ricerca può terminare prima del timeout standard di 60
  secondi.
- Non è garantita l'interruzione forzata di chiamate SDK già in corso: se
  una singola operazione supera il budget residuo, il fallimento viene
  rilevato solo al ritorno della chiamata.
- Se il budget si esaurisce prima del completamento, la compilazione
  fallisce con `MIS_COMPILATION_FAILED` e messaggio diagnostico esplicito.

**Esempio con embedding Pegasus:**

```bash
poetry run python -m qreduce.experiments.portfolio_mv \
  --run-id embedded_pegasus \
  --asset-count 20 \
  --mis-solver-id dwave_simulated_annealing \
  --mis-embedding-profile pegasus_p16 \
  --mis-num-reads 100
```

Il configuratore HTML include un selettore "Profilo embedding locale" nel
pannello dei parametri D-Wave, attivo solo con il solver D-Wave e riduzione
abilitata.

### Opzioni reduction policy

| Opzione                                | Descrizione                           | Default               |
|----------------------------------------|---------------------------------------|-----------------------|
| `--max-reduction-rounds`               | Numero massimo di round               | 1                     |
| `--candidate-domain-min-items`         | Minimo item nel dominio candidato     | 1                     |
| `--candidate-domain-max-items`         | Massimo item nel dominio candidato    | 60% di asset_count    |
| `--target-binary-variables`            | Target variabili binarie              | 3                     |
| `--min-reduction-ratio`                | Rapporto minimo di riduzione          | 0.1                   |
| `--max-end-to-end-runtime-seconds`     | Timeout totale pipeline               | 60.0                  |
| `--classical-time-limit-seconds`       | Timeout per invocazione solver        | 60.0                  |
| `--recovery-policy-on-domain-too-small`| `fail`, `retry_with_larger_domain`    | `fail`                |
| `--recovery-policy-on-infeasible`      | `fail`, `retry_with_larger_domain`    | `fail`                |
| `--max-recovery-attempts`              | Massimo tentativi di recovery         | 0                     |

**Semantica dei timeout:**

- `--max-end-to-end-runtime-seconds`: budget totale della pipeline, condiviso
  tra tutti i round e tentativi di recovery. Un valore di `0` significa
  nessun limite di tempo end-to-end.
- `--classical-time-limit-seconds`: limite per ogni singola invocazione del
  solver classico (si resetta ad ogni solve). Un valore di `0` significa
  che il solver prosegue fino al completamento o all'esaurimento del budget
  end-to-end.

Entrambi i parametri rifiutano valori negativi, NaN, infinito e booleani.

## Esempi

### D-Wave simulated annealing con CPLEX

```bash
poetry run python -m qreduce.experiments.portfolio_mv \
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
poetry run python -m qreduce.experiments.portfolio_mv \
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
outputs/portfolio_mv/{run_id}/
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

L'opzione `--output-root` sostituisce interamente `outputs/portfolio_mv`: il
runner usa `output_root/{run_id}/` senza aggiungere la famiglia.

## Notebook di analisi

I notebook si trovano in `notebooks/experiments/portfolio_mv/`:

| Notebook                                       | Dati caricati            |
|------------------------------------------------|--------------------------|
| `001_synthetic_portfolio_classical.ipynb`      | `001_classical/`         |
| `002_synthetic_portfolio_single_pass.ipynb`    | `002_scip/`              |
| `003_synthetic_portfolio_single_pass.ipynb`    | `003_dwave_cplex/`       |
| `004_synthetic_portfolio_multi_round.ipynb`    | `004_correlation_only/`  |

I notebook caricano artifact già prodotti tramite `load_experiment_run` e non
eseguono la pipeline. La logica di analisi risiede in
`qreduce.experiments.portfolio_mv.analysis`.

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
- **D-Wave simulatore**: `poetry install --with experiments` (simulatore locale, no QPU)
- **D-Wave embedding**: `poetry install --with dwave-embedding` (per profili `pegasus_p16`, `zephyr_z12`)

Un backend non disponibile produce failure esplicito senza fallback. L'uso di
profili di embedding diversi da `none` senza le dipendenze corrispondenti
produce un errore esplicito che indica come installare il gruppo mancante.

## API Python

L'entry point principale è `run_portfolio_experiment`:

```python
from dataclasses import replace

from qreduce.experiments.portfolio_mv import (
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

- Execution: `src/qreduce/experiments/portfolio_mv/execution.py`
- Adapter: `src/qreduce/experiments/portfolio_mv/adapter.py`
- Modelli: `src/qreduce/experiments/portfolio_mv/models.py`
- Analisi: `src/qreduce/experiments/portfolio_mv/analysis.py`
- Post-check: `src/qreduce/experiments/portfolio_mv/postcheck.py`
