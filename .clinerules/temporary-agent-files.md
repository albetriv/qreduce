# Regola: file temporanei strumentali di Cline

Quando Cline ha bisogno di creare file temporanei per svolgere i propri compiti, deve usare esclusivamente:

```text
.cline-tmp/
```

Questa cartella è riservata ai file strumentali dell'agente e non fa parte della logica applicativa QIS.

## File temporanei strumentali

Sono file temporanei strumentali:

- script one-shot creati per ispezione, parsing, diagnostica o automazione locale;
- dump provvisori;
- file diagnostici;
- appunti tecnici generati dall'agente;
- file intermedi usati solo per completare un task;
- esperimenti locali che non sono deliverable del progetto.

## Regole operative

- Non creare file temporanei strumentali nella root del progetto.
- Non creare file temporanei strumentali in `src/`, `tests/`, `docs/`, `notebooks/`, `pipeline/` o `outputs/`.
- Non usare `outputs/` per file interni di Cline: `outputs/` è riservata agli artefatti della pipeline e della logica di progetto QIS.
- Non importare mai codice da `.cline-tmp/` in moduli di produzione, test permanenti o notebook consolidati.
- Considerare tutto il contenuto di `.cline-tmp/` eliminabile in qualsiasi momento.
- Se uno script temporaneo contiene logica utile, prima di completare il task migrarla o proporne la migrazione in una posizione appropriata:
  - `src/qreduce/` per logica applicativa;
  - `tests/` per test permanenti;
  - `docs/` per documentazione;
  - `notebooks/` solo per presentazione, visualizzazione o orchestrazione leggera.
- Prima di concludere un task, verificare che eventuali file temporanei creati da Cline siano rimasti confinati in `.cline-tmp/` oppure siano stati rimossi.

## Note

`.cline-tmp/` deve essere ignorata da Git e da Cline.