# Esperimento portfolio media-varianza

## 1. Descrizione del problema

Si decide la quota di capitale da investire in ciascun asset, bilanciando rendimento atteso e varianza. La CLI genera rendimenti sintetici, da cui ricava medie e covarianza campionaria. Il capitale è interamente investito, senza posizioni corte; limiti individuali condizionati alla selezione sono sempre attivi, mentre la cardinalità minima e massima è facoltativa.

## 2. Formulazione matematica

Sia $I=\{1,\ldots,n\}$ l'insieme degli asset. Per il titolo $i$, $x_i$ è il
peso continuo, $\delta_i$ la selezione binaria, $\mu_i$ il rendimento atteso
e $0\leq l_i\leq u_i$ i limiti di investimento. $\Sigma_{ij}$ è la covarianza
tra i rendimenti dei titoli $i$ e $j$, $\lambda>0$ è l'avversione al rischio
e $K_{\min}$ e $K_{\max}$ sono i limiti di cardinalità.

$$
\begin{alignedat}{2}
\min_{x,\delta}\quad &
\lambda \sum_{i\in I}\sum_{j\in I}\Sigma_{ij}x_i x_j - \sum_{i\in I}\mu_i x_i \\
\text{soggetto a}\quad & \sum_{i\in I}x_i = 1, \\
& l_i\delta_i \leq x_i \leq u_i\delta_i, &&\qquad i\in I, \\
& K_{\min} \leq \sum_{i\in I}\delta_i \leq K_{\max}, &&\qquad \text{(limiti facoltativi)}, \\
& x_i\geq 0,\quad \delta_i\in\{0,1\}, &&\qquad i\in I.
\end{alignedat}
$$

- **Limiti per titolo.** La CLI usa gli stessi limiti per tutti gli asset.
  Con limite inferiore nullo, un titolo selezionato può avere peso zero.
- **Cardinalità.** Minimo e massimo sono facoltativi e si configurano
  indipendentemente. Nella formula compatta, un minimo omesso equivale a $0$
  e un massimo omesso a $n$: sono limiti impliciti, non righe aggiunte al
  modello. La cardinalità conta le selezioni, non i pesi positivi.
- **Problema ridotto.** Per ogni asset escluso, sia il peso sia la selezione
  sono fissati a zero.

## 3. CLI unificata

```bash
poetry run python -m qreduce.experiments.portfolio_mv --help
```

## 4. Parametri

### 4.1 Generali e generazione

| Opzione | Significato, valori e default |
|---|---|
| `-h`, `--help` | Mostra la guida ed esce. |
| `--run-id` | Identificatore non vuoto del run; obbligatorio. |
| `--log-config` | Percorso YAML; prevale sulla variabile `QREDUCE_LOG_CONFIG`, altrimenti si usa la configurazione predefinita del repository se disponibile. |
| `--output-root` | Radice degli artifact; default `outputs/portfolio_mv`. |
| `--model-export` | Abilita l'export del modello; default disabilitato. |
| `--model-export-path` | Percorso esterno opzionale con estensione `.lp` o `.mps`; richiede `--model-export`, directory padre esistente e file non preesistente. |
| `--asset-count` | Intero almeno 6; default 30. |
| `--risk-aversion` | Reale finito strettamente positivo; default 1.0. |
| `--generation-seed` | Seed intero non negativo della generazione; default 42. |
| `--observation-count` | Intero almeno 10 volte il numero di asset; default il massimo tra 100 e 10 volte il numero di asset. |

### 4.2 Limiti e cardinalità

| Opzione | Significato, valori e default |
|---|---|
| `--lower-bound` | Limite inferiore uniforme per asset selezionato, reale finito non negativo; default 0.0. |
| `--upper-bound` | Limite superiore uniforme, reale finito almeno pari al limite inferiore; default 0.7. |
| `--min-selected-assets` | Minimo di selezioni, intero tra 0 e il numero di asset; default assente. |
| `--max-selected-assets` | Massimo di selezioni, intero tra 1 e il numero di asset; default assente e non inferiore al minimo, se presente. |

I limiti e la cardinalità devono anche permettere di soddisfare il budget. Il numero di asset nel dominio candidato non coincide necessariamente con la cardinalità finale.

### 4.3 Grafo di riduzione

| Opzione | Significato, valori e default |
|---|---|
| `--graph-edge-mode` | `correlation_only` oppure `near_duplicate` (default). |
| `--correlation-threshold` | Soglia di correlazione assoluta, reale finito tra 0 e 1; default 0.90. |
| `--near-duplicate-max-relative-return-difference` | Differenza relativa massima dei rendimenti in modalità `near_duplicate`, finita e non negativa; default 0.10. |
| `--near-duplicate-max-relative-variance-difference` | Differenza relativa massima delle varianze in modalità `near_duplicate`, finita e non negativa; default 0.10. |

In entrambe le modalità la correlazione assoluta deve raggiungere la soglia. In `near_duplicate` devono inoltre essere rispettate entrambe le soglie relative: la differenza assoluta dei rendimenti è divisa per il massimo dei loro valori assoluti e `1e-12`; quella delle varianze per il massimo delle due varianze e `1e-12`.

### 4.4 Solver

| Opzione | Significato, valori e default |
|---|---|
| `--mis-solver-id` | Solver MIS: `local_greedy` (default), `dwave_simulated_annealing`, `pasqal_local`, `pasqal_cloud_emulator`, `pasqal_qpu`. |
| `--classical-solver-id` | Solver classico: `scip` (default) o `cplex`. |
| `--classical-time-limit-seconds` | Limite per singola risoluzione classica, reale finito non negativo; default 60.0 secondi, 0 senza limite per singola risoluzione. Resta applicabile il budget complessivo. |
| `--pasqal-shots` | Numero intero positivo di shot, solo per solver Pasqal; default 100 per locale ed emulatore cloud, esplicito e obbligatorio per QPU. |
| `--pasqal-emulator-service` | Servizio cloud: `emu_free`; obbligatorio esplicitamente e ammesso solo con `pasqal_cloud_emulator`, che richiede riduzione attiva. |
| `--pasqal-device-id` | Identificatore non vuoto del dispositivo, obbligatorio e ammesso solo con `pasqal_qpu`. |
| `--pasqal-cost-consent` | Conferma dei possibili costi, obbligatoria e ammessa solo con `pasqal_qpu`. |
| `--mis-num-reads` | Numero intero positivo di letture, opzionale e solo per `dwave_simulated_annealing`; se omesso si usa il default del backend. |
| `--mis-num-sweeps` | Numero intero positivo di sweep, opzionale e solo per `dwave_simulated_annealing`; se omesso si usa il default del backend. |
| `--mis-embedding-profile` | `none` (default), `pegasus_p16` o `zephyr_z12`; un profilo diverso da `none` richiede `dwave_simulated_annealing` e riduzione attiva. |

Con `pasqal_local` e riduzione attiva occorre impostare esplicitamente `--max-end-to-end-runtime-seconds` a 0. `pasqal_qpu` richiede esattamente un round di riduzione; il cloud emulator richiede almeno un round.

### 4.5 Politica di riduzione

| Opzione | Significato, valori e default |
|---|---|
| `--max-reduction-rounds` | Intero non negativo; default 1. Zero disabilita la riduzione, valori maggiori di 1 consentono più round. |
| `--candidate-domain-min-items` | Minimo di elementi nel dominio candidato, intero non negativo; default 1. |
| `--candidate-domain-max-items` | Massimo di elementi nel dominio candidato, intero non negativo non inferiore al minimo; default il massimo tra 3 e la parte intera inferiore dei tre quinti del numero di asset. |
| `--num-source-mis-candidates` | Numero di candidati MIS sorgente, intero almeno 1; default 1. |
| `--min-reduction-ratio` | Rapporto minimo di riduzione, reale finito tra 0 e 1; default 0.1. |
| `--target-binary-variables` | Obiettivo sul numero di variabili binarie, intero non negativo; default 3. |
| `--max-end-to-end-runtime-seconds` | Budget complessivo condiviso, reale finito non negativo; default 60.0 secondi, 0 senza limite complessivo. |
| `--recovery-policy-on-domain-too-small` | Politica per dominio troppo piccolo: `fail` (default) o `retry_with_larger_domain`. |
| `--recovery-policy-on-infeasible` | Politica per problema non fattibile: `fail` (default) o `retry_with_larger_domain`. |
| `--max-recovery-attempts` | Numero massimo di tentativi, intero non negativo; default 0. Se positivo richiede almeno una politica diversa da `fail`. |

Il recovery richiede riduzione attiva. Il numero di round è un massimo, non una promessa che vengano tutti eseguiti.

## 5. Directory degli artifact

La radice predefinita è `outputs/portfolio_mv`; `--output-root` la sostituisce interamente.

## 6. Note specifiche

Il grafo è ausiliario: correlazione o quasi duplicazione sono criteri euristici di ridondanza, non vincoli di incompatibilità del portafoglio originario. La riduzione non garantisce la conservazione dell'ottimo. La covarianza campionaria generata è semidefinita positiva per costruzione; l'interpretazione dell'avversione al rischio dipende dalla scala temporale e numerica dei dati.

## 7. Riferimenti

- H. Markowitz, [Portfolio Selection](https://doi.org/10.1111/j.1540-6261.1952.tb01525.x), 1952: formulazione media-varianza.
- R. Yalovetzky et al., [Quantum-Informed Portfolio Selection: An End-to-End Pipeline Validated on Trapped-Ion Hardware with Real Market Data](https://arxiv.org/abs/2607.01037), 2026: selezione di portafoglio tramite insiemi indipendenti su grafi di correlazione e riduzione ibrida quantistico-classica; approccio distinto dal modello media-varianza qui descritto.
- [SCIP Optimization Suite](https://www.scipopt.org/doc/html/): documentazione dei metodi di ottimizzazione intera e non lineare.
