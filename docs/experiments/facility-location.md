# Facility location con capacità

## 1. Descrizione del problema

Si decide quali sedi aprire e come ripartire la domanda dei clienti tra le sedi
aperte, minimizzando costi fissi e costi di allocazione. La domanda è
frazionabile, ogni cliente può essere servito da più sedi e tutti i collegamenti
sede-cliente sono ammessi. Ogni domanda deve essere soddisfatta interamente e
ogni sede rispetta la propria capacità.

L'ingresso è un'istanza numerica OR-Library: capacità e costi fissi delle sedi,
domande dei clienti e costi di allocazione. Capacità e domande sono finite e
positive; i costi sono finiti e non negativi.

## 2. Formulazione matematica

Siano $I$ l'insieme delle sedi e $J$ quello dei clienti. Per ogni sede
$i$, $u_i$ è la capacità e $f_i$ il costo fisso; per ogni cliente $j$,
$d_j$ è la domanda e $c_{ji}$ il costo di assegnare alla sede $i$
l'intera domanda del cliente $j$. Il costo di una frazione è proporzionale a
quella frazione: non si moltiplica nuovamente $c_{ji}$ per $d_j$.

La variabile binaria $\delta_i$ indica l'apertura della sede; la variabile
continua $x_{ij}$ è la frazione della domanda del cliente $j$ assegnata a
$i$. Il modello minimizza

$$
\min \quad \sum_{i\in I} f_i\delta_i +
\sum_{i\in I}\sum_{j\in J} c_{ji}x_{ij}
$$

soggetto ai seguenti vincoli, sempre attivi:

$$
\begin{aligned}
\sum_{i\in I} x_{ij} &= 1 && \forall j\in J && \text{(domanda)},\\
\sum_{j\in J} d_j x_{ij} &\le u_i\delta_i && \forall i\in I && \text{(capacità)},\\
x_{ij} &\le \delta_i && \forall i\in I,\ j\in J && \text{(collegamento)},\\
\delta_i &\in \{0,1\} && \forall i\in I,\\
0\le x_{ij} &\le 1 && \forall i\in I,\ j\in J.
\end{aligned}
$$

Quando la riduzione esclude una sede, il modello residuo aggiunge i fissaggi
$\delta_i=0$ e $x_{ij}=0$ per tutti i suoi clienti. Questi fissaggi
sono euristici e non garantiscono la conservazione dell'ottimo originale.

## 3. CLI unificata

```bash
poetry run python -m qreduce.experiments.facility_location.run --help
```

## 4. Parametri

### 4.1 Ingresso e configurazione

| Parametro | Significato e condizioni |
| --- | --- |
| `instance` | Posizionale obbligatorio: percorso del file numerico OR-Library, codificato ASCII. Sono richieste dimensioni positive e il numero esatto di valori; i segnaposto `capacity` non sono supportati. |
| `--run-id` | Obbligatorio: identificativo non vuoto dell'esecuzione. |
| `--output-root` | Directory radice degli artifact; predefinita `outputs/facility_location`. |
| `--log-config` | Percorso della configurazione YAML dei log; se omesso si usa `QREDUCE_LOG_CONFIG`, altrimenti la configurazione predefinita del repository se presente. |
| `-h`, `--help` | Mostra la guida ed esce. |

### 4.2 Riduzione e solver

| Parametro | Significato e condizioni |
| --- | --- |
| `--rounds` | Intero non negativo, massimo numero di round di riduzione; predefinito `0`, ossia baseline senza riduzione. |
| `--solver` | Identificativo del solver classico: `scip` (predefinito) o `cplex`. |
| `--mis-solver` | Solver del grafo di riduzione; predefinito `local_greedy`. Identificativi inclusi: `local_greedy`, `dwave_simulated_annealing`, `pasqal_local`, `pasqal_cloud_emulator`, `pasqal_qpu`. Usato nei round di riduzione. |
| `--seed` | Intero, predefinito `7`; seed passato alle opzioni MIS e al solver classico. |
| `--budget` | Secondi, numero finito non negativo; predefinito effettivo `60.0`. Budget complessivo condiviso tra round e recovery; `0` elimina il limite globale. |
| `--classical-time-limit-seconds` | Secondi, numero finito non negativo; predefinito effettivo `60.0`. Limite per ciascuna invocazione del solver classico; `0` elimina il limite per solve, ma resta applicabile il budget globale. |
| `--cap` | Intero, massimo numero di sedi nel dominio candidato; se omesso è il numero di sedi dell'istanza. Deve essere almeno `1`; un valore inferiore al numero di sedi protette può impedire la riduzione. |
| `--protect-all` | Flag, disattivato per default: protegge tutte le sedi dall'esclusione, senza imporne l'apertura. |
| `--recovery-attempts` | Intero non negativo, predefinito `0`: massimo numero di tentativi con dominio più ampio quando il dominio è troppo piccolo o il residuo è inammissibile. Un valore positivo richiede `--rounds` almeno `1`. |
| `--min-reduction-ratio` | Numero finito in `[0, 1]`, predefinito `0.1`: soglia minima della frazione di riduzione. |
| `--model-export` | Flag, disattivato per default: richiede l'esportazione del modello classico residuo. |

### 4.3 Policy del grafo

Questi parametri sono numeri finiti e controllano il grafo euristico usato
nei round di riduzione; i profili sono costruiti sull'istanza originale.

| Parametro | Significato e valori ammessi |
| --- | --- |
| `--alpha` | Peso della capacità utile nello score, in `[0, 1]`; predefinito `0.5`. Il peso restante è attribuito alla convenienza di costo. |
| `--epsilon` | Limite inferiore dello score, in `(0, 1]`; predefinito `0.01`. |
| `--profile-fraction` | Frazione della domanda totale da coprire nel profilo di ciascuna sede, in `(0, 1]`; predefinita `0.5`. I clienti sono ordinati per costo unitario e indice. |
| `--overlap-threshold` | Sovrapposizione minima dei profili, pesata per domanda, per creare un arco; in `[0, 1]`, predefinita `0.5`. |
| `--capacity-difference` | Differenza relativa massima tra capacità per creare un arco, in `[0, 1]`; predefinita `0.25`. Anche la soglia di sovrapposizione deve essere soddisfatta. |

Con `--rounds` maggiore di zero, i tre backend Pasqal non sono utilizzabili
tramite questa CLI: il runner passa sempre un seed MIS intero, non supportato
per il campionamento da nessuno dei tre. Impostare `--seed 0` non lo rimuove.
Inoltre `pasqal_local` non supporta un budget globale positivo; `--budget 0`
risolve solo questa limitazione, non quella del seed. Per `pasqal_qpu` servono
anche device esplicito, shot e consenso ai costi, che questa CLI non espone.
Con `--rounds 0` il solver MIS non viene usato.

## 5. Directory degli artifact

La directory radice predefinita è `outputs/facility_location`; `--output-root`
la sostituisce.

## 6. Note specifiche

Il grafo ausiliario rappresenta ridondanza euristica tra sedi, non vincoli di
incompatibilità del problema. Le sedi indispensabili per conservare capacità
complessiva sufficiente sono protette dall'esclusione, non obbligate ad aprire.
Con collegamenti completi e domanda frazionabile, una capacità complessiva
sufficiente permette di soddisfare la domanda. L'ottimalità del residuo non
certifica quella del modello originale.

Le istanze OR-Library sono dati esterni acquisiti separatamente dall'utente;
non è previsto il download automatico. Il manifest descrive i byte locali,
ma non ne certifica provenienza o diritti di redistribuzione.

Il recovery espande il dominio nel round corrente, senza aumentare il cap.
Configurare più round non garantisce che vengano eseguiti: la pipeline può
terminare al primo round con successo o successo parziale. Nei confronti con
la baseline usare tempi di ambito coerente: il tempo della pipeline include
i tentativi, mentre il caricamento è registrato separatamente; il solo tempo
dell'ultimo solve non è confrontabile con il tempo end-to-end della baseline.

## 7. Riferimenti

- [OR-Library: capacitated warehouse location](https://people.brunel.ac.uk/~mastjjb/jeb/orlib/capinfo.html): formato e istanze benchmark del problema.
- [SCIP Optimization Suite](https://www.scipopt.org/): documentazione di un solver per programmazione mista intera.
