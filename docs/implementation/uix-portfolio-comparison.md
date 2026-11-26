# Confronto UIX Portfolio MV

## Utilizzo e artifact

Il pannello **Confronto tra run** visualizza una dashboard e dettagli tecnici,
senza generare o scaricare un report Markdown. Dalla root del repository:

```bash
python -m qreduce.experiments.portfolio_mv.run_catalog
```

Aprire `uix/experiment_portfolio_mv.html`, scegliere **05 · Confronto** e
selezionare due run distinti. Se la pagina è già aperta, il pulsante di
aggiornamento ricarica il catalogo. Rigenerare lo snapshot dopo modifiche agli
output: contiene copie degli input e non viene aggiornato automaticamente.

Ogni run richiede `run_manifest.json`, `problem.json`, `run_result.json`,
`config_used.json` ed `experiment_metadata.json`. I file opzionali
`round_<index>_result.json` integrano la traccia. L'importatore supporta gli
schema artifact 1.0 e 1.1 per `synthetic-portfolio`.

## Interpretazione e limiti

Il pannello mostra dominio, obiettivo, posizioni della baseline, motivi di
esclusione, tempi e budget disponibili. I valori sconosciuti non sono zero. Il
verdetto complessivo richiede istanze verificate identiche, soluzioni valide,
una baseline non ridotta, un confronto ridotto e dati sufficienti; altrimenti
vengono indicati i motivi dell'indisponibilità. Un denominatore nullo o assente
impedisce il calcolo del relativo rapporto. Le differenze osservate non
provano causalità o ottimalità globale.

Il browser non è un validatore completo dello schema e non verifica gli hash
JSON canonici controllati dal loader Python. I file di round integrano i dati
principali, che prevalgono in caso di conflitto; i grafi mancanti non sono
ricostruiti. Identificativi e domini sono controllati per contraddizioni,
mentre identificativi mancanti vengono segnalati. Se mancano valori binari,
la selezione usa una soglia sui pesi. Dettagli della configurazione e della
policy del grafo non sono tutti visibili. I tempi sono riportati separatamente,
senza inferire durate residue da ambiti potenzialmente sovrapposti.

I test DOM non dimostrano il comportamento di tutti i browser reali; rimane
utile una verifica indipendente della parità delle metriche finanziarie con
l'analisi Python. I test del pannello sono in `tests/test_uix_comparison_panel.py`;
quelli del core sono in `tests/uix_comparison.test.js`. I test DOM richiedono
`jsdom` e un test saltato non attesta il corretto funzionamento.

## Caso osservato: da 100 a 38 variabili

Queste osservazioni provengono da output locali ignorati da Git, non da fixture
portabili: `ptf_100_classic` e `ptf_100_dwave` avevano schema 1.1 e lo stesso
hash SHA-256 del file `problem.json`. L'identità dei byte di quel file non
stabilisce l'identità semantica in generale.

La baseline aveva zero round e 100 binarie libere residue; l'altro run aveva
un round e 38 binarie libere, usando `simulated_annealing` locale. Il nome del
provider `dwave` non indica esecuzione su QPU. Entrambi i post-check erano
ammissibili; gli obiettivi ricalcolati erano circa -0.11039653 e -0.08842327,
con durate end-to-end osservate di circa 5.677 e 42.338 secondi. Sono singole
osservazioni, non aspettative riproducibili né prova di un effetto causale;
l'ottimalità del residuo non certifica quella del problema originale.
