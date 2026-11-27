# Esperimenti interni

Gli esperimenti interni di QReduce verificano la pipeline con famiglie di
problemi specifiche. Ogni famiglia implementa un adapter di dominio, policy di
riduzione e post-check dedicati.

## Organizzazione per famiglia

Ogni famiglia di problemi occupa una struttura dedicata:

```text
src/qreduce/experiments/<famiglia>/    # adapter, policy, parser, analisi
notebooks/experiments/<famiglia>/      # notebook di visualizzazione
outputs/<famiglia>/<run_id>/           # artifact serializzati
```

Le famiglie sono indipendenti: ogni adapter implementa il contratto
`ReducibleProblemAdapter` con la propria semantica di dominio.
Parser e loader sono separati dagli adapter; non si deduce un adapter
universale da modelli MIP generici. Gli esperimenti restano nel repository e
sono esclusi dal wheel. I benchmark del solo core MWIS sono distinti dagli
esperimenti end-to-end.

## Infrastruttura condivisa

Runner, lettura degli artifact e loader sono condivisi tra tutte le famiglie:

- `qreduce.experiments.runner`: esegue la pipeline e pubblica gli artifact;
- `qreduce.experiments.artifacts`: legge e valida run esistenti;
- `qreduce.experiments.load_experiment_run`: entry point per i notebook.

La pubblicazione è atomica: una directory viene creata solo al completamento.
Un run con esito `failed` (failure normalizzata della pipeline) è comunque
pubblicato come risultato analizzabile.

**Errori non pubblicati:**
- Errori di preparazione (parsing, configurazione) prima dell'invocazione del
  runner non producono artifact.
- Errori di serializzazione o pubblicazione causano l'eccezione e nessuna
  directory finale; il cleanup rimuove i file temporanei.

## Convenzioni degli artifact

Ogni run produce una directory `{output_root}/{run_id}/` contenente:

| File                      | Contenuto                                    | Presenza      |
|---------------------------|----------------------------------------------|---------------|
| `run_result.json`         | Risultato completo della pipeline            | sempre        |
| `config_used.json`        | Configurazione effettiva                     | sempre        |
| `problem.json`            | Problema serializzato                        | sempre        |
| `experiment_metadata.json`| Metadati del run (timestamp, family, etc.)   | sempre        |
| `run_manifest.json`       | Indice degli artifact con hash               | sempre        |
| `round_NN_result.json`    | Risultato di ogni round di riduzione         | se riduzione  |
| `recovery_attempts.json`  | Tentativi di recovery eseguiti               | se recovery   |
| `residual_model.lp`       | Export del modello residuo (interno)         | se prodotto   |

**Model export:**
- **Interno** (default quando `--model-export` senza `--model-export-path`):
  il file viene scritto nella run directory. Compare in tabella solo se il
  backend ha effettivamente prodotto il file.
- **Esterno** (`--model-export-path` con path fuori dalla run directory):
  il runner usa uno staging temporaneo, poi sposta il file al path finale
  *prima* di pubblicare la directory del run. Se la pubblicazione successiva
  fallisce, il file esterno può rimanere presente senza una directory finale.

Il runner verifica l'avvenuta scrittura: `residual_model.lp` compare solo
se il backend ha prodotto il file, non semplicemente perché l'export era
richiesto.

**Default di output_root:**
- API runner (`run_experiment`): `outputs`
- CLI delle famiglie (convenzione): `outputs/<famiglia>` (es. `outputs/portfolio_mv`)

L'opzione `--output-root` sostituisce questo default: il runner usa
`{output_root}/{run_id}/` senza aggiungere automaticamente la famiglia.

Il `run_id` deve essere unico nella root di output; directory esistenti non
vengono sovrascritte.

## Relazione tra runner e notebook

I notebook leggono artifact già prodotti tramite `load_experiment_run` e non
eseguono direttamente la pipeline. La logica di analisi risiede nei moduli
Python (`analysis.py`); i notebook si occupano di visualizzazione e
presentazione.

## Aggiungere una nuova famiglia

1. Creare `src/qreduce/experiments/<famiglia>/` con adapter, models, policy.
2. Implementare `ReducibleProblemAdapter` per la semantica di dominio.
3. Aggiungere entry point CLI (es. `single_pass.py`, `multi_round.py`).
4. Creare `notebooks/experiments/<famiglia>/` per l'analisi.
5. Documentare comandi e parametri in `docs/experiments/<famiglia>.md`.

## Famiglie disponibili

| Famiglia            | Stato         | Guida                                    |
|---------------------|---------------|------------------------------------------|
| portfolio_mv        | completo      | [portfolio-mv.md](./portfolio-mv.md)     |
| portfolio_sr        | completo      | [portfolio-sr.md](./portfolio-sr.md)     |
| facility_location   | sperimentale  | [facility-location.md](./facility-location.md) |

Le guide delle famiglie disponibili descrivono i modelli, i parametri CLI e le
directory degli artifact; il comando `--help` mostra le opzioni disponibili.

## Anteprime sperimentali non eseguibili

Queste guide descrivono proposte di esperimenti, senza configuratore né CLI:

- [Asset Liability Management (ALM)](./asset-liability-management.md)
- [Riassicurazione passiva](./riassicurazione-passiva.md)
- [Cessione di crediti deteriorati](./cessione-crediti-deteriorati.md)
- [Pianificazione degli audit interni](./pianificazione-audit-interni.md)

## Configuratori HTML

La directory [`uix/`](../../uix/) contiene configuratori HTML per generare
comandi CLI interattivamente. Le pagine sono statiche, apribili direttamente
da filesystem senza server.

| Configuratore                           | Famiglia          |
|-----------------------------------------|-------------------|
| [experiment_portfolio_mv.html](../../uix/experiment_portfolio_mv.html) | portfolio_mv |
| [experiment_portfolio_sr.html](../../uix/experiment_portfolio_sr.html) | portfolio_sr |
| [experiment_facility_location.html](../../uix/experiment_facility_location.html) | facility_location |

Il catalogo [`uix/index.html`](../../uix/index.html) elenca i configuratori
disponibili e le anteprime con la rispettiva documentazione.
I collegamenti alla documentazione aprono i file Markdown: a seconda del browser
e dell'ambiente possono mostrare il testo sorgente o scaricare il file, anziché
renderizzarlo. La vista Markdown di GitHub renderizza le formule; in locale usare
un visualizzatore Markdown compatibile con la sintassi matematica dei documenti.

I configuratori:
- generano comandi CLI con sintassi Bash/Zsh;
- supportano formato inline (una riga) e multilinea;
- includono solo i flag con valori diversi dai default;
- mostrano icone informative (ⓘ) con descrizioni dei parametri;
- non verificano la disponibilità dei solver o l'esistenza dei file.

Nei configuratori Portfolio, con D-Wave Simulated Annealing e riduzione attiva,
la scheda **Profilo di embedding attivo** mostra il numero di nodi, di
collegamenti e il massimo numero di vicini per nodo del grafo target locale
selezionato. Questi valori non misurano la capacità di una QPU reale né
garantiscono che l'embedding riesca. Con **None** la scheda non compare.

Nei configuratori **Portfolio SR** e **Portfolio MV**, accanto al profilo appare
**Forza delle catene** solo con riduzione attiva e con Pegasus o Zephyr. **Auto
bilanciato** non emette il flag: la pipeline usa `0.375 * lambda_edge` effettiva
del QUBO. **Manuale** richiede un numero finito maggiore di zero prima di
generare `--mis-chain-strength`. In **Confronto > Traccia per round** vengono
mostrati politica e valore effettivo registrati, anche se il MIS fallisce dopo
la compilazione. Gli artefatti storici non vengono ricalcolati.

### Comandi preferiti

Nel pannello destro di ciascun configuratore, **Comandi preferiti** offre:

- nome obbligatorio, proposto dall'ID del run, e **Salva** per
  configurazioni valide; un nome gia presente richiede conferma di sovrascrittura;
- elenco alfabetico (con ordinamento naturale dei numeri), **Carica** e
  **Cancella**, con conferma di cancellazione;
- **Esporta JSON** e **Importa JSON**, relativi al configuratore corrente.

Il salvataggio conserva campi, checkbox, valori temporaneamente disabilitati,
formato inline/multilinea e comando. Carica ripristina la configurazione e
rigenera il comando con validazione, riepilogo e formule correnti: non esegue
comandi. Nessun preferito e caricato automaticamente; Ripristina default non
cancella l'archivio.

Il nome segue le modifiche all'ID del run finché non è personalizzato.
Svuotandolo, la proposta automatica riprende alla successiva modifica dell'ID.
Carica ripristina il nome salvato come esplicito, anche se il campo del nome è
stato modificato dopo la selezione; successive modifiche all'ID non lo cambiano.
Ripristina default riallinea il nome all'ID ripristinato nelle tre famiglie.

Nel portfolio MV, **Candidati MIS da aggregare** accetta un intero positivo
e aggiunge `--num-source-mis-candidates`. Vuoto omette il flag e conserva il
default CLI 1; in baseline il controllo è disabilitato e il flag omesso.
Si selezionano fino al numero richiesto di candidati validi e distinti secondo
ranking MWIS e filtro di diversità, non necessariamente i campioni più frequenti.
Gli asset vengono uniti prima di applicare protezioni e cap del dominio;
**Max item dominio** è un limite separato. I candidati disponibili possono
essere meno di quelli richiesti: il campo non controlla la generazione degli shot.
Il valore è incluso nei preferiti e negli archivi JSON. Caricare un vecchio
preferito senza questo campo lo ripristina a vuoto, senza ereditare il valore
della configurazione precedente.

La persistenza usa `localStorage`, non cookie, server o file nel workspace.
Non e sincronizzata tra Chrome, Firefox, profili o macchine. Su `file://`
il comportamento dipende dal browser: mantenere una copia esportata, anche
prima di spostare gli HTML o cancellare i dati del browser.
Il test iniziale di scrittura/rilettura non garantisce persistenza tra sessioni.
Se lo storage e indisponibile o una scrittura fallisce, un avviso indica che
le modifiche restano solo in memoria fino a chiusura/ricaricamento: esportarle.
Archivi illeggibili/incompatibili non vengono sovrascritti; modifiche rilevate
da un'altra finestra richiedono di riaprire la pagina prima di salvare.

Il JSON include identificatore applicazione, versione (1), famiglia e preferiti.
L'import valida tutti i dati prima di applicarli e rifiuta versioni/famiglie,
campi o opzioni incompatibili senza modifiche parziali. I duplicati vengono
rinominati con suffissi `(2)`, `(3)`, ecc., senza eliminare quelli esistenti.
Limiti: nomi di 160 caratteri, 1000 preferiti, archivio e file importati di 5 MiB.
Se la scrittura non e disponibile ma i dati sono leggibili, i preferiti esistenti
restano consultabili ed esportabili.
L'export richiede un download del browser: scegliere una destinazione fuori
dal workspace, eventualmente sincronizzata. Il file puo contenere percorsi
locali e altri valori configurati; condividerlo consapevolmente.

**Verifica manuale in Chrome e Firefox**, separatamente, in profili normali:

1. Aprire lo stesso HTML via `file://`, salvare due configurazioni con nomi
   in ordine inverso e verificare l'elenco alfabetico.
2. Cambiare campi e formato, caricare un preferito e verificare comando,
   riepilogo, controlli dipendenti e formule. Annullare/confermare una cancellazione.
3. Chiudere completamente il browser, riaprire lo stesso HTML e verificare
   la presenza dei preferiti. Non confondere questa prova con il controllo iniziale.
4. Esportare fuori dal workspace, importare nell'altro browser e verificare
   il ripristino; importare nuovamente e controllare i suffissi dei duplicati.
5. Ripetere per tutti i configuratori; provare JSON errati e di altra famiglia.

### Configurazione del grafo di riduzione

In tutti e tre i configuratori, la card **Costruzione del grafo MWIS** si trova
nella tab **Riduzione**. Facility Location non ha una tab Graph Policy separata.
Questi parametri definiscono lo screening euristico, non i vincoli del problema.

In baseline i controlli del grafo sono disabilitati, i loro valori sono conservati
e i relativi flag non vengono aggiunti al comando. Riattivando la riduzione,
i valori tornano utilizzabili e vengono nuovamente validati. Nei portfolio le
tolleranze di rendimento e varianza sono utilizzate soltanto in modalità
`near_duplicate`; in `correlation_only` rimangono conservate ma inattive.

### Test dei configuratori

I test in `tests/test_uix_js_execution.py` eseguono il JavaScript effettivo
dei configuratori tramite Node.js e jsdom, verificando che i comandi generati
siano accettati dai parser Python.

**Setup opzionale per i test JavaScript:**

```bash
npm install   # installa jsdom come dev dependency
```

I test saltano automaticamente se Node.js o jsdom non sono disponibili.
La suite principale (`pytest tests/`) funziona anche senza Node.js; i test
JavaScript sono verifiche aggiuntive sulla coerenza UI/CLI.

**Cosa verificano i test:**
- Validazione: campi numerici, intervalli, interi vs decimali
- Transizioni di modalità: da riduzione a baseline e viceversa
- Comandi parsabili: i comandi generati sono accettati da argparse
- Equivalenza formati: inline e multilinea producono gli stessi argomenti
