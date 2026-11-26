# Esperimento portfolio Sharpe ratio

## 1. Descrizione del problema

Si scelgono i pesi long-only di un portafoglio a partire da prezzi adjusted
close, ticker e settori. Si massimizza il rapporto tra rendimento atteso e
volatilità, rispettando budget e limite di peso per asset; limiti settoriali e
cardinalità massima sono facoltativi. Le medie e la covarianza sono stimate
dai rendimenti e annualizzate. Il tasso privo di rischio è fissato a zero.

## 2. Formulazione matematica

Sia $I$ l'insieme degli asset e $I_s$ il sottoinsieme del settore $s$.
Per ogni $i$, $\mu_i>0$ è il rendimento medio annualizzato, $U_i>0$
il limite di peso e $x_i\geq 0$ il peso continuo. La matrice di covarianza
annualizzata $\Sigma$ è semidefinita positiva. I limiti settoriali sono
$L_s,H_s$; se è richiesta cardinalità, $K$ è il massimo di posizioni e
$\delta_i\in\{0,1\}$ indica la selezione.

Il problema di dominio, per portafogli a varianza positiva, è:

$$
\max_x\quad SR(x)=\frac{\mu^T x}{\sqrt{x^T\Sigma x}}
$$
$$
\sum_{i\in I}x_i=1,\qquad 0\leq x_i\leq U_i\quad(i\in I).
$$

Quando configurati si aggiungono i vincoli settoriali e di cardinalità:

$$
L_s\leq\sum_{i\in I_s}x_i\leq H_s,\qquad
x_i\leq U_i\delta_i,\quad \sum_{i\in I}\delta_i\leq K.
$$

La trasformazione usa la positività di tutti i rendimenti selezionati e il
budget: ponendo $x_{scale}=1/(\mu^T x)>0$ e $x_{scaled,i}=x_{scale}x_i$, con $x_{scaled}$ e $x_{scale}$
variabili continue, si ottiene il QP seguente:

$$
\begin{aligned}
\min_{x_{scaled},x_{scale}}\quad & x_{scaled}^T\Sigma x_{scaled}\\
\text{soggetto a}\quad & \mu^T x_{scaled}=1,\quad \sum_i x_{scaled,i}=x_{scale},\\
& 0\leq x_{scaled,i}\leq U_i x_{scale},\quad
1/\mu_{\max}\leq x_{scale}\leq 1/\mu_{\min}.
\end{aligned}
$$

Qui $\mu_{\min}$ e $\mu_{\max}$ sono rispettivamente minimo e massimo
dei rendimenti degli asset. I vincoli opzionali diventano:

$$
L_s x_{scale}\leq\sum_{i\in I_s}x_{scaled,i}\leq H_s x_{scale},\qquad
 x_{scaled,i}\leq\frac{U_i}{\mu_{\min}}\delta_i,\quad
\sum_i\delta_i\leq K,\quad \delta_i\in\{0,1\}.
$$

Il collegamento big-M è lineare e si aggiunge al limite $x_{scaled,i}\leq U_i x_{scale}$.
Senza cardinalità il modello è un QP convesso; con cardinalità è un MIQP.
La ricostruzione è $x_i=x_{scaled,i}/x_{scale}$; se il valore ottimo $v=x_{scaled}^T\Sigma x_{scaled}$
è positivo, lo Sharpe è $1/\sqrt v$. Una covarianza semidefinita può
ammettere varianza nulla: in tal caso il rapporto e questa ricostruzione dello
Sharpe non sono matematicamente definiti. La metrica implementata restituisce
zero quando la volatilità calcolata non è positiva.

## 3. CLI unificata

```bash
poetry run python -m qreduce.experiments.portfolio_sr --help
```

## 4. Parametri

### 4.1 Esecuzione e dati

| Parametro | Significato, valori e default |
|---|---|
| `-h`, `--help` | Mostra l'aiuto ed esce. |
| `--run-id` | Identificativo della run; obbligatorio. |
| `--log-config` | Percorso della configurazione YAML di logging; omesso usa la configurazione predefinita. |
| `--output-root` | Radice degli artifact; default `outputs/portfolio_sr`. |
| `--model-export` | Abilita l'esportazione del modello classico residuo; disabilitata per default. |
| `--model-export-path` | Percorso personalizzato di export `.lp` o `.mps`; richiede `--model-export`. Se omesso si usa il percorso predefinito. |
| `--csv-path` | CSV dei prezzi; default `data/yahoo/SP500.csv`. |
| `--asset-count` | Numero intero positivo di asset; mutuamente esclusivo con `--explicit-tickers`. Se entrambi omessi, 50. |
| `--explicit-tickers` | Lista di ticker separati da virgola, non vuoti e senza duplicati; alternativa a `--asset-count`. |
| `--start-date`, `--end-date` | Estremi opzionali della finestra, date ISO `YYYY-MM-DD`. |
| `--return-convention` | Rendimento `simple` o `log`; default `log`. |
| `--annualization-factor` | Fattore intero positivo di annualizzazione; default 252. |
| `--selection-order` | Ordine di selezione: `alphabetical` (default), `sharpe_descending` o `random`. |
| `--random-seed` | Seed intero opzionale per la selezione casuale. |

### 4.2 Vincoli e grafo

| Parametro | Significato, valori e default |
|---|---|
| `--upper-bound` | Limite uniforme per asset, reale positivo; default 1.0. |
| `--max-positions` | Massimo intero positivo di posizioni, non superiore al numero di asset; omesso disattiva la cardinalità. |
| `--risk-free-rate` | Tasso privo di rischio; default 0.0, unico valore attualmente accettato. |
| `--sector-min`, `--sector-max` | Limiti opzionali come coppie `settore=valore` separate da virgole. Ogni valore è finito tra 0 e 1; per ogni settore minimo non superiore al massimo e somma dei minimi non superiore a 1. Un estremo omesso vale rispettivamente 0 o 1. Un minimo positivo richiede asset del settore nell'universo selezionato. |
| `--edge-mode` | `correlation_only` oppure `near_duplicate` (default): criterio degli archi del grafo di riduzione. |
| `--correlation-threshold` | Soglia di correlazione con segno, finita tra 0 e 1; default 0.80. |
| `--near-duplicate-max-return-diff` | Massima differenza relativa di rendimento per `near_duplicate`, finita e non negativa; default 0.15. |
| `--near-duplicate-max-variance-diff` | Massima differenza relativa di varianza per `near_duplicate`, finita e non negativa; default 0.15. |

### 4.3 Solver e riduzione

| Parametro | Significato, valori e default |
|---|---|
| `--mis-solver-id` | Metodo MIS: `local_greedy` (default), `dwave_simulated_annealing` o `pasqal_local`. Con riduzione attiva, `pasqal_local` richiede esplicitamente `--max-end-to-end-runtime-seconds 0`, perché l'emulatore locale non applica deadline. |
| `--classical-solver-id` | Solver classico: `scip` (default) o `cplex`. |
| `--classical-time-limit-seconds` | Limite in secondi per solve classico; default 60.0, zero disabilita il limite. |
| `--pasqal-shots` | Numero intero positivo di shot, solo con `pasqal_local`; default effettivo 100. |
| `--mis-num-reads`, `--mis-num-sweeps` | Interi positivi opzionali per `dwave_simulated_annealing`; omessi usano i default del backend. |
| `--mis-embedding-profile` | `none`, `pegasus_p16` o `zephyr_z12`; omesso non impone un profilo. I profili diversi da `none` richiedono `dwave_simulated_annealing` e riduzione attiva (`--max-reduction-rounds` maggiore di zero). |
| `--max-reduction-rounds` | Intero non negativo; default 1. Zero disattiva la riduzione, uno abilita un round, valori superiori più round. |
| `--candidate-domain-min-items` | Minimo di asset nel dominio candidato; default 1. |
| `--candidate-domain-max-items` | Massimo di asset nel dominio candidato; default il massimo tra 1 e il 60% della numerosità richiesta, arrotondato per difetto: numero di ticker espliciti, oppure `--asset-count`, oppure 50 se entrambi omessi; non è ricalcolato sugli asset effettivamente idonei. |
| `--num-source-mis-candidates` | Numero di candidati MIS sorgente considerati; default 1. |
| `--min-reduction-ratio` | Rapporto minimo di riduzione; default 0.1. |
| `--target-binary-variables` | Target di binarie residue; default 3 con cardinalità, altrimenti 0. |
| `--max-end-to-end-runtime-seconds` | Limite totale in secondi; default 120.0, zero disabilita il limite. |
| `--recovery-policy-on-domain-too-small` | Politica per dominio troppo piccolo: `fail` (default) o `retry_with_larger_domain`. |
| `--recovery-policy-on-infeasible` | Politica per problema non fattibile: `fail` (default) o `retry_with_larger_domain`. |
| `--max-recovery-attempts` | Numero massimo di tentativi di recovery; default 0. |

## 5. Directory degli artifact

La radice predefinita è `outputs/portfolio_sr`; `--output-root` la sostituisce.

## 6. Note specifiche

Servono almeno tre date di prezzo per la covarianza campionaria. Sono esclusi
i ticker con rendimento medio annualizzato non superiore a `1e-12`; la
covarianza è verificata per simmetria, diagonale positiva e semidefinitezza
positiva con tolleranza numerica. La selezione avviene sull'universo idoneo.

Gli archi del grafo indicano ridondanza euristica, non incompatibilità tra
investimenti: `correlation_only` usa la correlazione con segno; `near_duplicate`
richiede anche differenze relative di rendimento e varianza entro le rispettive
soglie. La riduzione non garantisce di conservare l'ottimo originale.

## 7. Riferimenti

- [Sharpe, The Sharpe Ratio (1994)](https://web.stanford.edu/~wfsharpe/art/sr/sr.htm): definizione e interpretazione del rapporto di Sharpe.
- M. Mattesi et al., [Diversifying Investments and Maximizing Sharpe Ratio: a novel QUBO formulation](https://arxiv.org/abs/2302.12291), 2023: formulazione QUBO per Sharpe e diversificazione settoriale, distinta dal modello continuo e dai vincoli settoriali qui descritti.
- [Cornuéjols e Tütüncü, Optimization Methods in Finance](https://doi.org/10.1017/CBO9780511754871): modelli e trasformazioni per l'ottimizzazione di portafoglio.
- [NumPy, `cov`](https://numpy.org/doc/stable/reference/generated/numpy.cov.html): stima della matrice di covarianza campionaria.
