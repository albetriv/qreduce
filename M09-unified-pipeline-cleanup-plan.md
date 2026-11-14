# M09 - Piano di pulizia e unificazione strutturale della pipeline

## Stato e obiettivo

Piano redatto il 2026-11-14; implementazione e verifica conclusiva completate.
La suite completa ha prodotto 354 test passati; lint e controllo del diff sono
stati eseguiti. Le evidenze iniziali seguenti descrivono lo stato precedente alla
pulizia, non quello attuale.

Completare l'unificazione strutturale della pipeline QReduce eliminando le API
legacy e i percorsi di compatibilita`. Il progetto non e` ancora pubblicato e
non richiede retrocompatibilita`: non sono previsti alias transitori o periodi
di deprecazione.

Il risultato atteso e` un solo entry point pubblico, `run_pipeline`, un solo
contratto di risultato del run, `PipelineRunResult`, e una sola orchestrazione.
La modularita` interna per round, recovery, solve e post-check va preservata:
pipeline unica non significa funzione monolitica o singolo file.

## Evidenze dell'ispezione iniziale

- `run_pipeline` seleziona la baseline per `max_reduction_rounds = 0` e delega
  tutti i valori positivi all'orchestrazione interna multi-round. Un round e`
  gia` un caso particolare del ciclo nel percorso principale.
- `run_multi_round` e` un wrapper deprecato dell'implementazione interna.
- `run_single_pass` mantiene un percorso distinto, calcola informazioni del run
  e converte `SinglePassRunResult` in `PipelineRunResult`.
- Entrambe le API legacy sono ancora esportate pubblicamente e chiamate da
  diversi test. Il runner degli esperimenti usa gia` `run_pipeline`.
- Alcune proprieta` di compatibilita` di `PipelineRunResult` espongono i dati
  del primo round: in particolare `retained_item_ids` e `fixing_manifest`
  possono essere confusi con i dati finali o cumulativi.
- Il delegato di riduzione riceve `started_at`, ma non lo inoltra
  all'implementazione multi-round, che avvia un nuovo cronometro.
- Il documento M09 attuale ammette esplicitamente la compatibilita` transitoria.
  La pulizia modifica tale scelta, non dimostra da sola che i precedenti criteri
  di completamento fossero contraddetti dalla presenza delle API legacy.

## Contratto e confini da preservare

```text
max_reduction_rounds = 0  -> baseline classical-only
max_reduction_rounds = 1  -> al massimo un round di riduzione
max_reduction_rounds > 1  -> riduzione iterativa con recovery configurabile
```

- La baseline non costruisce il grafo e non invoca alcun backend MIS; mantiene
  tutti gli item e risolve il problema completo.
- La baseline conserva il manifest con origine `no_reduction`, una sequenza
  `round_results` vuota e nessun artifact `round_XX_result.json`.
- Restano invariati, salvo modifiche esplicitamente approvate nelle specifiche,
  policy di recovery, criteri di arresto, fixing, garanzie, stati, failure reason,
  post-check e responsabilita` dell'applicazione.
- La riorganizzazione non deve spostare arbitrariamente il solve dopo tutti i
  round: va preservata la semantica esistente di solve, recovery e stop.
- Non introdurre nuove dipendenze o logica applicativa nei notebook.

## Fase 1 - Inventario e verifica preliminare

1. Rileggere le specifiche normative e i documenti M02, M05, M06, M07, M08 e M09.
2. Censire definizioni, import, export e chiamanti delle API e dei tipi legacy
   in codice, test, documentazione, esempi e notebook.
3. Confrontare il percorso legacy single-pass con `run_pipeline` configurata
   con un round: individuare differenze di metriche, provenance, bound, stati,
   export del modello e gestione degli errori prima di rimuoverlo.
4. Rilevare la copertura iniziale con test pertinenti e lint; distinguere
   eventuali problemi preesistenti o backend opzionali non disponibili.
5. In caso di ambiguita` normativa che richieda una scelta osservabile,
   chiarirla prima dell'implementazione.

## Fase 2 - Unico contratto pubblico

1. Mantenere `run_pipeline` come unico entry point pubblico di esecuzione.
2. Eliminare `run_single_pass`, `run_multi_round`, i relativi export,
   `DeprecationWarning`, docstring di transizione e conversioni usate soltanto
   dalla compatibilita`.
3. Mantenere `PipelineRunResult` come unico risultato di un run completo.
4. Rimuovere le proprieta` di compatibilita` che selezionano implicitamente il
   primo round. Migrare i chiamanti verso `final_retained_item_ids`,
   `cumulative_fixing_manifest` oppure uno specifico elemento di `round_results`,
   secondo l'intento effettivo; evitare sostituzioni automatiche ambigue.
5. Verificare gli altri helper del risultato: non dedurre automaticamente la
   modalita` classical-only dalla sola assenza di round, che puo` verificarsi
   anche per failure prima della riduzione. Se serve modificarne la semantica,
   allineare prima contratto, documentazione e test.

## Fase 3 - Unica orchestrazione e componenti interni

1. Consolidare la gestione del run sotto `run_pipeline`:
   validazione iniziale, contesto temporale, input hash, provenance, budget,
   aggregazione delle evidenze ed esito finale.
2. Trattare uno e piu` round con la stessa orchestrazione parametrizzata dalla
   configurazione; mantenere il ramo senza riduzione della baseline.
3. Trasformare il nucleo oggi denominato single-pass in un componente interno
   di esecuzione del round, anziche` una pipeline completa alternativa.
4. Sostituire `SinglePassRunResult` con un contratto interno di round appropriato,
   riusando o completando `ReductionRoundResult` dove semanticamente corretto.
   Preservare tutte le evidenze necessarie ad audit e aggregazione.
5. Organizzare tipi condivisi e componenti in modo da evitare dipendenze
   circolari motivate soltanto dalla vecchia separazione delle pipeline.
6. Rinominare o riorganizzare i moduli legacy secondo le responsabilita` reali,
   senza creare alias di compatibilita`.

Schema concettuale, non ordine imposto al solve:

```text
run_pipeline
  -> validazione e contesto del run
  -> baseline senza riduzione oppure ciclo di riduzione
       -> esecuzione del round
       -> solve, post-check, recovery e stop secondo il contratto
  -> risultato finale auditabile
```

## Fase 4 - Consolidamento delle responsabilita` trasversali

1. Usare un'unica origine temporale per l'intero run e propagarla ai componenti.
2. Consolidare la gestione dei budget senza azzerarli implicitamente tra
   delegati, round o tentativi di recovery.
3. Ridurre duplicazioni di validazione iniziale, hash, provenance, costruzione
   degli esiti terminali e aggregazione delle metriche, mantenendo le
   validazioni locali necessarie ai singoli componenti.
4. Preservare conteggi originali e residui, bound e claim di ottimalita`,
   metriche di dominio, manifest cumulativo e distinzione tra dati per-round
   e dati finali.
5. Preservare il contratto di staging e pubblicazione degli export del modello
   usato dal runner degli esperimenti.

## Fase 5 - Migrazione e rafforzamento dei test

1. Migrare i test end-to-end dalle API legacy a `run_pipeline`, impostando
   esplicitamente il numero massimo di round richiesto dallo scenario.
2. Conservare test unitari mirati ai componenti interni, senza esporre nuove
   pipeline pubbliche per facilitarne il testing.
3. Verificare baseline, un round, piu` round, recovery, criteri di arresto,
   infeasibility, failure dei backend, errori degli adapter e budget.
4. Verificare dati finali e cumulativi distinti dal primo round e conservazione
   delle evidenze nelle terminazioni anticipate.
5. Verificare che la baseline non invochi grafo o MIS e che gli artifact
   rispettino i contratti delle diverse modalita`.
6. Aggiungere controlli sugli export pubblici e sull'assenza delle API legacy.
7. Verificare integrazioni, serializzazione, round-trip degli artifact ed export
   del modello, con backend opzionali disponibili nell'ambiente.

## Fase 6 - Allineamento documentale

1. Aggiornare le specifiche per rendere esplicito il contratto della pipeline
   unica e la semantica dei risultati, senza introdurre garanzie non verificate.
2. Aggiornare M09 eliminando compatibilita` transitoria e deprecazione dai
   criteri; registrare nuove evidenze prima di dichiarare conclusa la pulizia.
3. Aggiornare roadmap e documenti M05/M08 per descrivere single-pass e
   multi-round come modalita` della stessa pipeline e non API concorrenti.
4. Controllare M02, M06, M07, README, esempi e notebook; aggiornare solo gli
   artefatti effettivamente impattati.
5. Nei notebook mantenere esclusivamente configurazione minima, chiamate ai
   moduli Python, visualizzazioni e spiegazioni.

## Verifica finale

Eseguire dalla root del workspace:

```powershell
poetry run pytest
poetry run ruff check .
git diff --check
git status --short
```

Integrare con ricerche mirate dei riferimenti legacy e controllo dei file
modificati. Riportare test eseguiti, test saltati e relativi motivi, errori
preesistenti ed eventuali limiti dell'ambiente. Non dichiarare verificate
integrazioni che non siano state eseguite.

## Criteri di completamento

- Unico entry point pubblico di esecuzione: `run_pipeline`.
- Nessun wrapper, alias o percorso alternativo di compatibilita` per
  `run_single_pass` o `run_multi_round`.
- Unico risultato del run completo: `PipelineRunResult`; contratti interni
  esplicitamente riferiti al round o al tentativo, non a pipeline concorrenti.
- Nessuna selezione implicita del primo round tramite proprieta` legacy.
- Baseline senza grafo o MIS; modalita` positive gestite dalla stessa
  orchestrazione, con evidenze di round e recovery conservate.
- Contesto temporale e budget coerenti per tutto il run.
- Test end-to-end migrati all'API unica e verifiche pertinenti eseguite.
- Specifiche, implementazione, test, documentazione ed esempi coerenti.
- Riepilogo finale degli artefatti modificati e di quelli verificati senza
  necessita` di modifica.

## Gestione dei file strumentali

Questo documento e` un deliverable richiesto nella root del workspace, non un
file temporaneo dell'agente. Eventuali script one-shot, dump o file diagnostici
necessari durante l'implementazione devono restare esclusivamente in
`.cline-tmp/` e non essere importati dal codice di produzione o dai test.