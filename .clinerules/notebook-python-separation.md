---
globs:
  - "notebooks/**/*.ipynb"
  - "src/**/*.py"
---

# Regola: separazione tra notebook Jupyter e file Python

Sintesi
- Nel progetto possono essere usati sia notebook Jupyter (`.ipynb`) sia file Python (`.py`).
- I notebook hanno scopo puramente di visualizzazione, esplorazione e presentazione dei risultati.
- Tutta la business logic, le funzioni riutilizzabili e le implementazioni devono risiedere nei file Python.

Convenzione obbligatoria
- I notebook Jupyter devono importare e usare logica definita nei moduli Python del progetto.
- I file `.py` devono contenere:
  - funzioni di dominio;
  - classi;
  - algoritmi;
  - trasformazioni dati;
  - validazioni;
  - implementazioni di modelli, solvers, pipeline o workflow riutilizzabili.
- I notebook `.ipynb` devono contenere solo:
  - celle di caricamento/configurazione minima;
  - chiamate a funzioni/classi definite nei `.py`;
  - visualizzazioni;
  - grafici;
  - tabelle di riepilogo;
  - testo esplicativo e commenti narrativi.

Struttura tipica
- In un package o sotto-package è normale avere:
  - uno o più file `.py` che contengono la logica applicativa;
  - un notebook Jupyter che attinge da quei file per mostrare risultati, grafici o analisi.

Esempio atteso
```text
src/qreduce/example_package/
├── __init__.py
├── data_processing.py      # logica di caricamento/trasformazione
├── optimization.py         # algoritmi e funzioni riutilizzabili
└── analysis.ipynb          # visualizzazione e chiamate alla logica Python
```

Linee guida pratiche
- Se una cella notebook contiene logica non banale, estrarla in una funzione o classe dentro un file `.py`.
- Se una funzione viene usata in più celle o più notebook, deve stare in un modulo Python.
- Evitare implementazioni lunghe direttamente nei notebook.
- Evitare duplicazione di codice tra notebook e file `.py`.
- Preferire notebook piccoli, leggibili e orientati alla comunicazione dei risultati.
- I notebook non devono essere la fonte primaria della logica del progetto.

Checklist revisione
- Il notebook contiene solo orchestrazione leggera, visualizzazioni e spiegazioni?
- La business logic è nei file `.py`?
- Le funzioni usate nel notebook sono importate da moduli Python?
- Eventuale codice complesso scritto nel notebook è stato estratto in un `.py`?
- La struttura package + notebook è chiara e riutilizzabile?

Eccezioni
- Sono ammessi esperimenti temporanei nei notebook durante una fase esplorativa.
- Prima di consolidare il lavoro, la logica utile deve essere migrata nei file `.py`.
- In caso di deviazione motivata, aggiungere una breve nota nel notebook che spieghi perché la logica non è stata ancora estratta.
