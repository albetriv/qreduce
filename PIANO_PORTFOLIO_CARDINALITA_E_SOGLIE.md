# Piano: cardinalità e soglie minime di investimento nel portfolio

Data: 16 novembre 2026.

Stato: piano concordato da implementare. Questo documento non dichiara le
funzionalità proposte come già disponibili.

## Obiettivo e perimetro

Rendere l'esperimento portfolio utilizzabile con soglie minime positive di
investimento e vincoli espliciti di cardinalità, mantenendo allineati modello,
validazioni, riduzione, post-check, API, CLI, UIX, artifact, test e documentazione.

L'intervento riguarda l'adapter portfolio e gli strumenti degli esperimenti.
Non comprende modifiche al kernel di riduzione né al comportamento di arresto
del multi-round: riduzione graduale, soglie per round e solve soltanto al target
dimensionale costituiscono un intervento separato.

## Evidenze iniziali

- Il modello rappresenta già limiti inferiori e superiori condizionati dalla
  selezione e li verifica nel post-check.
- Il generatore Python accetta limiti uniformi, ma il builder standard non li
  espone e usa il minimo predefinito zero.
- La validazione che richiede la somma dei minimi di tutti i candidati non
  superiore al budget è troppo restrittiva: non tutti gli asset devono essere
  selezionati.
- Il modello portfolio non contiene vincoli espliciti di cardinalità.
- Il limite al dominio candidato non equivale alla cardinalità finale.

## 1. Contratto dei parametri e semantica

Parametri proposti per gli esperimenti sintetici:

| Parametro | Significato | Default |
|---|---|---|
| `lower_bound` | Investimento minimo per asset selezionato | `0.0` |
| `upper_bound` | Investimento massimo per asset selezionato | `0.7` |
| `min_selected_assets` | Numero minimo di asset selezionati | Nessun vincolo aggiuntivo |
| `max_selected_assets` | Numero massimo di asset selezionati | Nessun vincolo aggiuntivo |

Il modello Python manterrà limiti eterogenei tramite `lower_bounds` e
`upper_bounds`. La cardinalità esatta sarà espressa impostando minimo e massimo
allo stesso valore, senza aggiungere un terzo parametro.

Convenzioni: `x_i` è il peso continuo; `delta_i` è la selezione binaria.

```text
sum_i x_i = 1
lower_bound_i * delta_i <= x_i
x_i <= upper_bound_i * delta_i
min_selected_assets <= sum_i delta_i
sum_i delta_i <= max_selected_assets
delta_i in {0, 1}
```

I vincoli opzionali di cardinalità saranno aggiunti soltanto se configurati.
Con minimo positivo, un asset selezionato ha investimento positivo. Con minimo
zero, una binaria può essere attiva anche con peso nullo: questa distinzione
deve essere documentata e visibile nei risultati. Gli esempi di selezione
combinatoria useranno minimi positivi.

## 2. Validazioni del problema

- Eliminare il controllo scorretto sulla somma dei minimi di tutti i candidati.
- Mantenere controlli su valori finiti, non negativi e minimo non superiore al
  massimo per ciascun asset.
- Allineare modello e generatore sul caso minimo uguale al massimo, che
  rappresenta investimento fisso quando l'asset è selezionato.
- Validare cardinalità intere, escludendo booleani, intervalli incoerenti e
  valori incompatibili con il numero di asset.
- Aggiungere controlli di incompatibilità evidente tra budget, limiti di
  investimento e cardinalità, condividendo la logica riutilizzabile.
- Distinguere precheck necessari da certificazione di fattibilità: superare i
  precheck non garantisce che il problema completo sia ammissibile.

Esempio di configurazione sicuramente inammissibile:

```text
max_selected_assets = 4
upper_bound = 0.20
investimento_totale_massimo = 0.80 < 1
```

## 3. Modello classico e post-check

- Aggiungere i vincoli di cardinalità al modello comune usato da baseline e
  problema ridotto, senza duplicazioni nei backend SCIP e CPLEX.
- Conservare i vincoli originali quando si restringe il problema.
- Verificare nel post-check cardinalità minima e massima, linking dei pesi,
  budget, integrità, fixing e obiettivo ricalcolato.
- Definire motivazioni distinguibili per violazioni di cardinalità e di soglie.
- Usare tolleranze coerenti con quelle già previste dal progetto.

## 4. Dominio candidato e recovery

- Rilevare domini con meno asset della cardinalità minima.
- Rilevare capacità di investimento insufficiente considerando anche la
  cardinalità massima.
- Rilevare incompatibilità evidenti tra minimi, cardinalità e budget.
- Valutare soltanto gli asset disponibili nel round corrente.
- Conservare i nuovi vincoli nelle restrizioni successive.
- Rendere la diagnostica coerente con i contratti e con il recovery esistente,
  senza inventare nuovi stati del kernel se non necessari.
- Verificare che il recovery reintegri opzioni nei casi recuperabili, entro i
  limiti configurati, senza promettere il recupero di ogni infeasibilità.
- Distinguere sempre dominio candidato e portafoglio finale: 40 candidati
  possono alimentare, per esempio, un portafoglio di 10 asset selezionati.

## 5. API, CLI, UIX e artifact

Propagare i parametri attraverso generatore, builder degli input,
`run_portfolio_experiment`, CLI e configuratore HTML.

Opzioni CLI proposte:

```text
--lower-bound
--upper-bound
--min-selected-assets
--max-selected-assets
```

### Adeguamento obbligatorio della UIX

Anche la UIX deve essere sistemata di conseguenza, non soltanto la CLI:

- aggiungere i campi per limiti di investimento e cardinalità ai configuratori
  portfolio pertinenti;
- aggiornare generazione dei comandi e propagazione delle opzioni;
- validare valori e combinazioni incoerenti, mantenendo le validazioni Python
  come fonte autorevole;
- aggiornare tooltip, default, descrizioni ed esempi;
- spiegare minimo condizionale, cardinalità binaria e differenza rispetto al
  limite del dominio candidato;
- mantenere coerenti i comandi per baseline, single-pass e multi-round;
- aggiornare i test UIX di comandi, tooltip ed esecuzione JavaScript pertinenti.

### Persistenza e compatibilità

- Conservare parametri effettivi nel problema serializzato e nei metadata
  pertinenti, per verificare la comparabilità tra esperimenti.
- Senza nuove opzioni mantenere il comportamento attuale.
- Continuare a leggere artifact precedenti privi dei nuovi campi.
- Valutare l'impatto sui formati e sul versionamento prima di cambiare lo schema.

## 6. Analisi, notebook e documentazione

- Mostrare separatamente asset iniziali, mantenuti, selezionati tramite binarie
  e investiti con peso positivo, indicando le tolleranze usate per i conteggi.
- Mostrare cardinalità e limiti richiesti negli elementi di riepilogo pertinenti.
- Mantenere business logic e calcoli riutilizzabili nei file Python; i notebook
  devono limitarsi a caricamento, chiamate ai moduli e presentazione.
- Preservare le modifiche utente già presenti nei notebook portfolio 001 e 004.
- Non sostituire né rigenerare automaticamente gli output esistenti.
- Aggiornare specifiche, documentazione dell'esperimento, documentazione di
  implementazione, README ed esempi soltanto dove effettivamente impattati.
- Non documentare le nuove funzionalità come disponibili prima della verifica.

## 7. Test e verifica

### Test unitari

- Minimi positivi con somma su tutti i candidati superiore a uno, ma selezione
  ammissibile.
- Limiti non validi e minimo uguale al massimo.
- Cardinalità minima, massima ed esatta, incluse validazioni dei tipi.
- Configurazioni sicuramente inammissibili.
- Dominio residuo insufficiente per cardinalità o capacità.
- Violazioni di cardinalità e soglie nel post-check.
- Propagazione da API, CLI e UIX, inclusi default e combinazioni non valide.
- Caricamento degli artifact precedenti.

### Test di integrazione

- Baseline e riduzione sulla stessa istanza con minimi positivi e cardinalità.
- Verifica di cardinalità e soglie sulla soluzione finale.
- Recovery su dominio inizialmente insufficiente ma recuperabile.
- Piccola istanza confrontabile con un riferimento indipendente.
- Esecuzione con SCIP e, se binding e licenza disponibili, CPLEX.

### Verifica finale

1. Eseguire i test mirati, quindi la suite completa e Ruff.
2. Verificare i test UIX pertinenti con gli strumenti già usati dal progetto.
3. Eseguire due nuovi esperimenti comparabili con run ID distinti e medesimo
   problema, vincoli, solver, budget e tolleranze.
4. Confrontare tempo end-to-end, obiettivo ricalcolato, fattibilità, cardinalità
   finale e dimensione residua.
5. Controllare i file modificati, il diff e la coerenza degli artifact prodotti.
6. Riportare i test eseguiti, eventuali limitazioni e gli artefatti documentali
   modificati o verificati senza necessità di modifica.

Gli esperimenti finali sono smoke test funzionali, non una dimostrazione
statistica di superiorità prestazionale. Eventuali file strumentali dell'agente
devono rimanere in `.cline-tmp/`; gli artifact degli esperimenti appartengono
invece alle directory di output del progetto.

## Componenti interessati

Percorsi assoluti principali:

```text
/Users/trivellatoa/DATADIR/Programmazione/python_local/python-312/qreduce/src/qreduce/experiments/portfolio/models.py
/Users/trivellatoa/DATADIR/Programmazione/python_local/python-312/qreduce/src/qreduce/experiments/portfolio/generator.py
/Users/trivellatoa/DATADIR/Programmazione/python_local/python-312/qreduce/src/qreduce/experiments/portfolio/adapter.py
/Users/trivellatoa/DATADIR/Programmazione/python_local/python-312/qreduce/src/qreduce/experiments/portfolio/postcheck.py
/Users/trivellatoa/DATADIR/Programmazione/python_local/python-312/qreduce/src/qreduce/experiments/portfolio/inputs.py
/Users/trivellatoa/DATADIR/Programmazione/python_local/python-312/qreduce/src/qreduce/experiments/portfolio/execution.py
/Users/trivellatoa/DATADIR/Programmazione/python_local/python-312/qreduce/src/qreduce/experiments/portfolio/__main__.py
/Users/trivellatoa/DATADIR/Programmazione/python_local/python-312/qreduce/src/qreduce/experiments/portfolio/analysis.py
/Users/trivellatoa/DATADIR/Programmazione/python_local/python-312/qreduce/tests/experiments/portfolio/
/Users/trivellatoa/DATADIR/Programmazione/python_local/python-312/qreduce/uix/
/Users/trivellatoa/DATADIR/Programmazione/python_local/python-312/qreduce/docs/experiments/portfolio.md
```

Controllare anche i test di pipeline, artifact e UIX correlati, le specifiche,
il README, la documentazione di implementazione e i notebook interessati.

## Criterio di completamento

Deve essere possibile configurare, sia nella baseline sia nel percorso ridotto,
un esperimento con 100 asset candidati, investimento minimo positivo per asset
selezionato e cardinalità finale esatta o entro un intervallo.

La soluzione deve superare il post-check; parametri, risultati e motivazioni di
eventuali failure devono essere leggibili negli artifact. La stessa
configurazione deve essere accessibile da API e CLI e generabile dalla UIX.