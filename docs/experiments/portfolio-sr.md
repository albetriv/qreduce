# Esperimento portfolio Sharpe ratio

## 1. Descrizione del problema

Si scelgono i pesi long-only di un portafoglio a partire da prezzi adjusted
close, ticker e settori. Si massimizza il rapporto tra rendimento atteso e
volatilità, rispettando il budget unitario e i limiti di peso condizionati a
una selezione binaria per asset. Il minimo per titolo è nullo per default;
cardinalità minima, cardinalità massima e limiti settoriali sono facoltativi.
Le medie e la covarianza sono stimate dai rendimenti e
annualizzate. Il tasso privo di rischio è fissato a zero.

## 2. Formulazione matematica

### Modello sui pesi originali

Sia $I=\{1,\ldots,n\}$ l'insieme degli asset e $S$ l'insieme dei settori
con limiti configurati. Per ciascun settore $s\in S$, $I_s$ è l'insieme dei
suoi asset e $L_s$ e $H_s$ sono i limiti di esposizione. Per il titolo $i$,
$x_i$ è il peso, $\delta_i$ la selezione e $0\leq l_i\leq u_i$ i limiti di
investimento. I rendimenti attesi $\mu_i>0$ e le covarianze $\Sigma_{ij}$
sono annualizzati; $\Sigma$ è semidefinita positiva. $K_{\min}$ e $K_{\max}$
sono i limiti di cardinalità.

Per portafogli a varianza positiva, con tasso privo di rischio nullo:

$$
\begin{alignedat}{2}
\max_{x,\delta}\quad & \frac{\mu^T x}{\sqrt{x^T\Sigma x}} \\
\text{soggetto a}\quad & \sum_{i\in I}x_i = 1, \\
& l_i\delta_i \leq x_i \leq u_i\delta_i, &&\qquad i\in I, \\
& K_{\min} \leq \sum_{i\in I}\delta_i \leq K_{\max}, &&\qquad \text{(limiti facoltativi)}, \\
& L_s \leq \sum_{i\in I_s}x_i \leq H_s, &&\qquad s\in S, \\
& x_i\geq 0,\quad \delta_i\in\{0,1\}, &&\qquad i\in I.
\end{alignedat}
$$

- **Limiti per titolo.** Con $\delta_i=0$ il peso è nullo; con $\delta_i=1$
  valgono i limiti del titolo. La CLI imposta limiti uniformi: minimo
  predefinito $0$, massimo $1$. Un massimo maggiore di $1$ è ammesso ma
  ridondante. L'API Python consente anche minimi per ticker (`lower_bounds`),
  non configurabili da CLI.
- **Cardinalità.** Ogni asset ha una binaria anche in assenza di vincoli di
  cardinalità. Con $l_i=0$ si può selezionare un titolo a peso zero: la
  cardinalità conta le selezioni, non le posizioni investite. I due limiti sono
  indipendenti; nella formula, gli estremi omessi valgono implicitamente $0$
  e $n$. Minimo e massimo uguali impongono una cardinalità esatta.
- **Settori.** Il minimo e il massimo di esposizione si applicano alla somma
  dei pesi del settore. Un estremo omesso vale $0$ per il minimo o $1$ per
  il massimo. Se non sono configurati limiti settoriali, $S$ è vuoto.

### Modello trasformato

Ponendo $x_{\mathrm{scale}}=1/(\sum_{i\in I}\mu_i x_i)>0$ e
$x_{\mathrm{scaled},i}=x_{\mathrm{scale}}x_i$, si ottiene il MIQP seguente.
Indichiamo con $\mu_{\min}$ e $\mu_{\max}$ il minimo e il massimo dei
rendimenti attesi e con $x_{\mathrm{scale},\max}=1/\mu_{\min}$ il limite
superiore del fattore di scala.

$$
\begin{alignedat}{2}
\min_{x_{\mathrm{scaled}},x_{\mathrm{scale}},\delta}\quad
& x_{\mathrm{scaled}}^T\Sigma x_{\mathrm{scaled}} \\
\text{soggetto a}\quad & \mu^T x_{\mathrm{scaled}} = 1, \\
& \sum_{i\in I}x_{\mathrm{scaled},i} = x_{\mathrm{scale}}, \\
& 1/\mu_{\max} \leq x_{\mathrm{scale}} \leq x_{\mathrm{scale},\max}, \\
& 0 \leq x_{\mathrm{scaled},i} \leq u_i x_{\mathrm{scale}}, &&\qquad i\in I, \\
& x_{\mathrm{scaled},i} \leq u_i x_{\mathrm{scale},\max}\delta_i, &&\qquad i\in I, \\
& x_{\mathrm{scaled},i} \geq l_i\bigl(x_{\mathrm{scale}}-x_{\mathrm{scale},\max}(1-\delta_i)\bigr),
  &&\qquad i\in I,\ l_i>0, \\
& K_{\min} \leq \sum_{i\in I}\delta_i \leq K_{\max}, &&\qquad \text{(limiti facoltativi)}, \\
& L_s x_{\mathrm{scale}} \leq \sum_{i\in I_s}x_{\mathrm{scaled},i} \leq H_s x_{\mathrm{scale}}, &&\qquad s\in S, \\
& \delta_i\in\{0,1\}, &&\qquad i\in I.
\end{alignedat}
$$

Le binarie non sono scalate, quindi i vincoli di cardinalità non cambiano.
Il collegamento superiore con la binaria si applica anche con minimo nullo;
quello inferiore serve solo se il minimo del titolo è positivo. La
trasformazione preserva le coppie ammissibili di pesi e selezioni; il modello
risolto è un MIQP anche senza minimi o cardinalità. La baseline risolve il
modello completo. Dopo la riduzione, si risolve lo stesso MIQP con il peso
scalato e la binaria degli esclusi fissati a zero; i titoli trattenuti restano
candidati, non selezioni obbligatorie.
Un nuovo modello rifiuta un manifest di fixing incompleto o incoerente; questa
validazione non si applica alla lettura degli artefatti storici.

I pesi originali si ricavano come $x_i=x_{\mathrm{scaled},i}/x_{\mathrm{scale}}$.
Se il valore ottimo $v$ dell'obiettivo trasformato è positivo, lo Sharpe è
$1/\sqrt v$. Una covarianza semidefinita può
ammettere varianza nulla: in tal caso il rapporto e questa ricostruzione dello
Sharpe non sono matematicamente definiti. La metrica implementata restituisce
zero quando la volatilità calcolata non è positiva. Nei risultati, lo Sharpe
ricostruito, da massimizzare, è distinto dal gap del MIQP effettivamente risolto.
L'ottimalità del residuo non certifica quella del problema originale.

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
| `--upper-bound` | Limite uniforme per asset, finito e positivo; default 1.0. Valori maggiori di 1 sono ammessi ma ridondanti. |
| `--lower-bound` | Peso minimo uniforme per titolo selezionato: finito, tra 0 e 1 e non superiore a ogni upper bound; default 0.0. Un peso è zero oppure almeno il minimo, anche senza cardinalità. |
| `--min-selected-assets` | Minimo di asset selezionati, intero tra 0 e il numero di asset idonei del problema. Zero equivale all'omissione. Non può superare il massimo, se presente. |
| `--max-selected-assets`, `--max-positions` | Massimo di asset selezionati, intero positivo non superiore al numero di asset del problema. Omesso: nessun massimo. `--max-positions` è l'alias di compatibilità; se si usano entrambe le opzioni i valori devono coincidere. |
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
| `--candidate-domain-min-items` | Minimo di asset nel dominio candidato; default 1. La cardinalità minima alza la soglia effettiva: gli asset mantenuti sono candidati, non selezioni obbligatorie. |
| `--candidate-domain-max-items` | Massimo di asset nel dominio candidato; il default con riduzione è il maggiore tra 1, il minimo di selezioni richiesto e il 60% (arrotondato per difetto) della numerosità richiesta: numero di ticker espliciti, `--asset-count` oppure 50. Non è ricalcolato sugli asset effettivamente idonei. Con riduzione attiva, un valore esplicito non può essere inferiore a `--min-selected-assets`; nella baseline non limita le selezioni. |
| `--num-source-mis-candidates` | Numero di candidati MIS sorgente considerati; default 1. |
| `--min-reduction-ratio` | Rapporto minimo di riduzione; default 0.1. |
| `--target-binary-variables` | Target di binarie residue; default 3. |
| `--max-end-to-end-runtime-seconds` | Limite totale in secondi; default 120.0, zero disabilita il limite. |
| `--recovery-policy-on-domain-too-small` | Politica per dominio troppo piccolo: `fail` (default) o `retry_with_larger_domain`. |
| `--recovery-policy-on-infeasible` | Politica per problema non fattibile: `fail` (default) o `retry_with_larger_domain`. |
| `--max-recovery-attempts` | Numero massimo di tentativi di recovery; default 0. |

## 5. Directory degli artifact

La radice predefinita è `outputs/portfolio_sr`; `--output-root` la sostituisce.
`problem.json` e il riepilogo di analisi registrano i vincoli configurati.
Il massimo rimane salvato come `max_positions`, anche con l'opzione canonica
`--max-selected-assets`. Le impostazioni inattive `min_selected_assets`,
`lower_bound` e `lower_bounds` sono omesse dal problema; negli artifact storici
l'assenza di questi campi significa che non è impostato alcun minimo.

`selected_count` conta le binarie valide attive, incluse quelle a peso zero;
è disponibile se il modello ha binarie di selezione e tutti i relativi valori
sono presenti e validi. `position_count` conta invece i pesi investiti sopra
la tolleranza. Un `selected_count` assente, anche nelle run storiche, non vale zero.
Negli artifact storici senza binarie la selezione non è registrata e non viene
dedotta dai pesi positivi. Selezioni a peso zero possono variare tra soluzioni
equivalenti, senza cambiare pesi o Sharpe. `problem.json` descrive il problema:
byte identici non dimostrano che run di versioni diverse abbiano risolto lo
stesso modello; export, mapping e fixing possono differire.

Per gli esempi CLI e Python, inclusi i minimi per ticker, consultare il
[README tecnico dell'esperimento](../../src/qreduce/experiments/portfolio_sr/README.md).

## 6. Note specifiche

Servono almeno tre date di prezzo per la covarianza campionaria. Sono esclusi
i ticker con rendimento medio annualizzato non superiore a `1e-12`; la
covarianza è verificata per simmetria, diagonale positiva e semidefinitezza
positiva con tolleranza numerica. La selezione avviene sull'universo idoneo.

Gli archi del grafo indicano ridondanza euristica, non incompatibilità tra
investimenti: `correlation_only` usa la correlazione con segno; `near_duplicate`
richiede anche differenze relative di rendimento e varianza entro le rispettive
soglie. La riduzione non garantisce di conservare l'ottimo originale.

I controlli preliminari su universo iniziale e dominio ridotto rilevano capacità
insufficiente per il budget, alcuni conflitti settoriali evidenti e casi in cui
la cardinalità minima richiede troppi candidati o pesi minimi che eccedono il
budget. Non certificano la fattibilità complessiva, che resta al solver. Gli
asset mantenuti dalla riduzione sono solo candidati, non selezioni obbligatorie.
Il postcheck verifica i pesi ricostruiti, la validità delle binarie, i pesi degli
esclusi, i limiti individuali e la cardinalità, distinguendo integrità delle
binarie e violazioni dei vincoli con le tolleranze previste.

## 7. Riferimenti

- [Sharpe, The Sharpe Ratio (1994)](https://web.stanford.edu/~wfsharpe/art/sr/sr.htm): definizione e interpretazione del rapporto di Sharpe.
- M. Mattesi et al., [Diversifying Investments and Maximizing Sharpe Ratio: a novel QUBO formulation](https://arxiv.org/abs/2302.12291), 2023: formulazione QUBO distinta dal MIQP e dai vincoli settoriali qui descritti.
- [Cornuéjols e Tütüncü, Optimization Methods in Finance](https://doi.org/10.1017/CBO9780511754871): modelli e trasformazioni per l'ottimizzazione di portafoglio.
- [NumPy, `cov`](https://numpy.org/doc/stable/reference/generated/numpy.cov.html): stima della matrice di covarianza campionaria.
