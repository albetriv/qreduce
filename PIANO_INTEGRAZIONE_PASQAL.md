# Piano di integrazione Pasqal in Qreduce

## Stato e obiettivi

Piano parzialmente implementato: `pasqal_local` è disponibile nelle CLI
portfolio MV e SR; il run CLI locale è già documentato, mentre il benchmark
rappresentativo resta aperto. Dettagli in
`docs/implementation/pasqal-local-status.md`. La Fase 2 è implementata nella
CLI portfolio MV e verificata con SDK reale e trasporto simulato. La UIX di
Portfolio MV genera il comando per `emu_free`, senza accesso diretto al cloud.
Lo smoke test su Pasqal Cloud resta separato e non eseguito. QPU, Portfolio SR
cloud e altri servizi cloud restano fuori perimetro.
Mantenere separate tre modalità:

1. Emulazione locale Pulser/QuTiP, senza credenziali cloud.
2. Emulatori online Pasqal, con scelta esplicita del servizio disponibile.
3. QPU Pasqal reale, con scelta esplicita del dispositivo disponibile.

`pasqal_cloud_emulator` è registrato; `pasqal_qpu` resta una proposta. Nessun passaggio
automatico tra backend, dispositivi o modalità: la policy resta `fail`.

## Decisioni e limiti di dominio

- **Mapping rigoroso:** un atomo per nodo, in 2D. Per una soglia `r` e un margine
  `m` espressi in micrometri (`0 < m < r`), accettare solo se la distanza
  euclidea di ogni arco è `<= r - m` e quella di ogni non-arco è `>= r + m`.
  Il profilo di compilazione fissa `r` e `m`; registrare i valori effettivi.
  Verificare il registro finale, anche dopo l'eventuale assegnazione alle
  trappole, e tutti i vincoli del dispositivo. Niente archi aggiunti o rimossi
  per far entrare il grafo nel layout.
- Distinguere un layout proposto non valido, una ricerca esaurita senza layout
  valido e un'impossibilità dimostrata (per esempio, troppi nodi per il target
  con un atomo per nodo). L'MVP non richiede un algoritmo di prova generale.
- Il confronto geometrico usa una soglia dichiarata; non equivale a interazioni
  fisiche a soglia esatta, né garantisce fattibilità o ottimalità delle sample.
- Inizialmente, usare la sequenza analogica come generatore euristico di sample
  MIS e valutare i pesi MWIS classicamente sul grafo originale. Non dichiarare
  una codifica quantistica dei pesi senza una strategia verificata e testata.
- Il ranking classico sulle sample non equivale a ottimizzare direttamente il
  MWIS pesato: documentare l'approssimazione e misurarne la qualità.
- Validare ogni sample sul grafo canonico; l'eventuale repair resta esplicito e
  affidato alla pipeline esistente. Non assumere ottimalità.
- Usare Pulser direttamente per l'MVP. Rimandare il confronto con la libreria
  MIS Pasqal a dopo il primo benchmark, senza introdurla come dipendenza o
  usarla come fallback.

## Architettura

Usare il contratto esistente `capabilities()`, `compile()` e `solve()` in
`src/qreduce/solving/mwis/compilation.py`. Integrare registry e ID pubblici,
famiglia `neutral_atom`, forma `mis_graph`, capability e failure normalizzate.
Il kernel non deve importare SDK dei provider: dipendenze opzionali e import lazy.

Condividere tra backend, nei limiti della compatibilità del target:

1. Traduzione del grafo e ricerca delle coordinate.
2. Diagnostica di mapping, registro, impulsi e sequenza Pulser.
3. Mappa stabile tra `node_order`, atomi e bitstring.
4. Conversione dei counts in `RawMISSample`; normalizzazione, repair e ranking
   restano nella pipeline canonica.

Riutilizzare il payload opzionale già presente in `CompiledMISJob`, con tipo
e versione di schema, opaco per il kernel. Per i job Pasqal con sequenza,
il payload contiene la sequenza nel formato JSON
astratto di Pulser (`Sequence.to_abstract_repr()`), il target effettivo,
coordinate, ordine, parametri, metodo ed eventuale seed del mapping, diagnostica
e versione SDK. L'adapter valida il payload e ricostruisce la sequenza in
`solve()`; testare il round trip. Lasciare invariato il campo BQM di D-Wave.
Non archiviare oggetti SDK vivi, né copiare il payload in ogni campione.

`compile()` non invia job. Per la Fase 2, propagare il servizio emulatore da
config e CLI tramite un parametro di compilazione validato e vincolarlo al
job compilato. Non usare `requested_device_id` per il servizio: la pipeline
inoltra già questo campo, da riservare alla scelta del dispositivo QPU.
Entrambe le modalità cloud usano `ExecutionMode.REMOTE`; non serve introdurre
un nuovo valore per distinguerle.

## Fase 0 - Verifica SDK

Usare le release più recenti non prerelease al momento dell'implementazione,
senza supportare API legacy. Baseline verificata su PyPI il 21 novembre 2026:
`pulser`, `pulser-core` e `pulser-simulation` **1.10.1** (17 novembre 2026);
per la Fase 2, `pasqal-cloud` **0.24.0**. Dichiarare `pulser-simulation`
(che include `pulser-core`) e `pasqal-cloud` nello stesso gruppo `experiments`,
installabile con `poetry install --with experiments`. Non aggiungere il
metapacchetto `pulser` né l'estensione legacy `pulser-pasqal`. Il backend
`pasqal_local` non deve usare l'SDK cloud a runtime. La baseline è un
riferimento storico, non una verifica della compatibilità del lock.

Su Windows/Python 3.12, risolvere e fissare le dipendenze opzionali nel lock
all'avvio della fase pertinente. Per il locale, fare uno smoke test con
`QutipBackendV2`, una sequenza di pochi atomi e la lettura dei conteggi finali
tramite `BitStrings`. Verificare ordine dei bit e totale delle occorrenze.
La versione pubblicata non dimostra compatibilità con il lock del progetto:
se la risoluzione fallisce, documentare il conflitto senza downgrade silenziosi.

## Fase 1 - Mapping ed emulatore locale

Mapping, backend locale e selezione via CLI sono già implementati. Resta da
chiudere la verifica su un corpus rappresentativo, con grafi di densità
intermedia e più run stocastici. Distinguere i casi risolti dal presolve
esatto (zero shot) da quelli effettivamente campionati.

1. Implementare una sola strategia di ricerca con budget esplicito, un solo
   profilo locale e una sola sequenza MIS di riferimento. Registrare archi
   target, archi geometrici, mancanti, aggiuntivi e coppie nella fascia di
   margine, senza sostenere fedeltà fisica perfetta.
2. Provare il mapping in anticipo su un piccolo corpus fisso di grafi generati
   dagli esperimenti Qreduce, oltre alle istanze giocattolo. Riportare la quota
   compilabile e i rifiuti per motivo, separatamente dalla qualità dei campioni.
3. Aggiungere `pasqal_local` con `QutipBackendV2`, import lazy e rilevamento
   esplicito di SDK assente o incompatibile.
4. `shots` è il numero di misure. Nell'MVP locale, in assenza di `shots`
   esplicito, usare `requested_solution_count` come valore di default degli
   shot, non come garanzia o limite di campioni distinti. Restituire tutti i
   bitstring distinti ricevuti con le loro occorrenze, senza tagli nell'adapter.
   La pipeline applica `max_distinct_samples` dopo la deduplicazione, in ordine
   lessicografico di `delta`, prima di repair e ranking per peso; conserva
   audit dei campioni esclusi. `num_source_mis_candidates` limita invece le
   candidate selezionate dopo ranking e diversità. Non cambiare tale policy
   nell'MVP; per i benchmark usare un cap non vincolante o riportare le esclusioni.
5. Dichiarare seed, timeout, cancellazione e limiti solo se realmente supportati;
   un seed del layout non garantisce riproducibilità completa del sampling.
6. Mantenere la selezione del solver da configurazione e CLI portfolio MV e
   SR, con parametri validati e copertura end-to-end.

## Fase 2 - Emulatori online Pasqal

1. Registrare `pasqal_cloud_emulator` e renderlo selezionabile da config e
   CLI in almeno un esperimento portfolio end-to-end. Richiedere un servizio
   esplicito; per l'MVP supportare solo `EMU_FREE` con
   `PasqalCloudConnection`. Distinguere dipendenza disponibile, servizio
   supportato e accesso del progetto al servizio. Nessun fallback.
2. Compilare contro un profilo del servizio verificato per la versione SDK
   nel lock. Validare registro, impulsi, limiti e opzioni supportate, senza
   ereditare automaticamente cap e impostazioni dell'emulatore locale.
   Prima dell'invio verificare che il target configurato coincida con quello
   compilato; esporre limiti e costi noti e richiedere consenso esplicito se
   è possibile un costo o se è ignoto. Verificare anche gli eventuali retry
   impliciti dell'SDK sulla creazione del batch.
3. Mantenere `solve()` sincrono per la pipeline, ma separare invio e attesa:
   leggere l'ID dalla risposta di creazione senza usare `submit()` (che
   ritenta e legge i job ID). Persistire `batch_id` appena
   disponibile e **prima di iniziare il polling**, senza aspettare eventuali
   `job_ids`. Predisporre e verificare un registro scrivibile prima dell'invio:
   un artefatto durevole per run, round e job compilato, indipendente dal
   successo del run. Salvare il riferimento al job, il servizio e il contesto
   necessario per decodificare i risultati, senza credenziali. Se la scrittura
   fallisce dopo l'invio, interrompere l'attesa, restituire l'ID in una
   diagnostica sicura e non reinviare.
4. Applicare il budget residuo all'attesa e distinguere rifiuto certo,
   esito di invio ignoto, timeout locale dopo la ricezione dell'ID e stato
   terminale remoto. Un timeout locale non implica cancellazione. Se l'esito
   dell'invio è ignoto, riconciliare con il provider prima di qualsiasi nuovo
   invio; nessun retry automatico o promessa di idempotenza.
5. Fornire un comando di recupero in sola lettura usando `batch_id` e lo
   stesso progetto Pasqal. Il comando recupera stato e risultati senza
   inviare job né rilanciare la pipeline. Per riportare i campioni nell'ordine
   canonico usare l'artefatto del job originale; senza tale contesto non
   attribuire i bit a nodi Qreduce.
6. Leggere i conteggi finali, verificare l'ordine degli atomi, la lunghezza
   dei bitstring e le occorrenze; registrare shot richiesti e ricevuti.
   Passare i campioni validati alla normalizzazione canonica, senza usare
   frequenze o score del provider come energia QUBO. Se interviene il
   presolve esatto, registrare provenienza e zero shot senza inviare un batch.

**Chiusura della Fase 2:** lock verificato su Python 3.12 e flusso CLI con
client simulato, su un grafo con almeno un arco per esercitare davvero la
submission. Verificare persistenza prima del polling, recupero in una nuova
sessione senza reinvio, timeout prima e dopo l'ID, fallimento della persistenza,
target errato, assenza di fallback e assenza di segreti in log e artefatti.
Lo smoke test sul servizio reale è un traguardo distinto, solo opt-in e
autorizzato: distinguere «validato con client simulato» da «validato su Pasqal
Cloud» nella documentazione.

## Fase 3 - QPU reale

1. Riutilizzare l'infrastruttura remota, mantenendo una modalità e provenienza
   distinte dall'emulatore. Interrogare dispositivi accessibili e specifiche
   effettive prima di compilare o inviare.
2. Validare layout, numero di atomi, impulsi, canali e vincoli del dispositivo;
   non assumere che una sequenza locale funzioni su qualunque QPU.
3. Gestire esplicitamente disponibilità, autorizzazioni, code, timeout,
   cancellazione, costi e risultati; registrare ID job e device effettivo.
4. Verificare separatamente la fattibilità di controlli per pesi MWIS e la
   qualità dei risultati; non promettere un numero di nodi garantito o un ottimo.
5. Validare su hardware solo con account abilitato e autorizzazione esplicita;
   distinguere codice predisposto, test simulati e job realmente completati.

## Credenziali locali in stile AWS

Riutilizzare il resolver di `pasqal_credentials.py` e il relativo file di
profili Qreduce, esterno al repository: `~/.pasqual/credentials`
(`%USERPROFILE%\.pasqual\credentials` su Windows). Non è un formato
nativo Pasqal. L'utente crea e compila il file in privato; non inserire
credenziali reali in conversazioni o repository.

Esempio indicativo, con soli segnaposto:

```ini
[default]
username = <username-pasqal>
password = <password-pasqal>
project_id = <project-id-pasqal>

[ricerca]
username = <username-pasqal>
password = <password-pasqal>
project_id = <project-id-pasqal>
```

- Selezionare il profilo per nome (predefinito: `default`). Usare una sola
  fonte per volta: credenziali fornite via API Python, altrimenti variabili
  d'ambiente, altrimenti il profilo locale. Una fonte presente ma incompleta
  produce un errore; non combinare credenziali di fonti diverse.
- Il project ID Pasqal va distinto dall'eventuale ID di progetto Google Cloud.
- Il file è in chiaro: limitare gli ACL Windows, evitare sincronizzazioni e
  backup non protetti e preferire credenziali dedicate, limitate e revocabili.
- Non inserire segreti in argomenti di comando, output, log, eccezioni, notebook,
  artefatti o metadati. Tradurre le eccezioni SDK in diagnostica sicura prima
  che raggiungano la pipeline, che può loggare `str(error)`. Mantenere la
  verifica TLS attiva.
- Documentare creazione manuale, percorso, profili, precedenza e revoca. La prima
  verifica con credenziali reali deve limitarsi, previa autorizzazione, alla
  connessione e all'elenco target: nessun job o spesa senza richiesta esplicita.

## Test e criteri di completamento

- Testare registry, capability, import lazy, SDK assente, configurazione e
  incompatibilità senza alterare gli altri backend.
- Testare grafi piccoli rappresentabili, layout con archi mancanti o aggiuntivi,
  coppie ai bordi e all'interno della fascia di margine, budget di ricerca
  esaurito e rifiuti dimostrabili del target.
- Testare ordine canonico, decodifica, conteggi, shot, deduplicazione, pesi,
  violazioni, normalizzazione, repair e assenza di pretese di ottimalità.
- Completare la verifica della Fase 1, oltre al run CLI già documentato, con
  un benchmark che riporti
  quota di grafi compilabili, quota di shot validi prima del repair (sul
  totale delle occorrenze ricevute, prima dei cap) e divario di peso tra il
  miglior candidato valido e l'ottimo esatto sulle istanze piccole. Riportare
  separatamente gli esiti con repair e i casi senza candidati validi; non
  richiedere che il metodo euristico trovi sempre l'ottimo.
- Testare CLI e pipeline, compresi parametri non supportati, budget e limiti.
  Verificare che la UIX Portfolio MV generi comandi accettati dalla CLI e
  ometta i flag cloud quando si cambia backend o si passa alla baseline.
- Usare client simulati per autenticazione, submission, polling, timeout
  prima e dopo l'ID, recupero senza reinvio, target non corrispondente e
  mancato fallback. Iniettare un segreto fittizio nel testo di un'eccezione
  SDK e verificarne l'assenza da log e artefatti. Test cloud reali solo opt-in.
- Verificare formato profili, precedenza e ACL consigliati con dati fittizi;
  nessun segreto reale nei test o nei log.
- Aggiornare specifiche, implementazione, test, README, documentazione ed esempi
  effettivamente impattati; mantenere i notebook di sola presentazione.

## Riferimenti tecnici

- Release: [Pulser](https://pypi.org/project/pulser/),
  [Pulser Core](https://pypi.org/project/pulser-core/),
  [Pulser Simulation](https://pypi.org/project/pulser-simulation/) e
  [Pasqal Cloud](https://pypi.org/project/pasqal-cloud/).
- API: [guida all'esecuzione locale e remota](https://docs.pasqal.com/pulser/quick_run_guide/),
  [`QutipBackendV2`](https://docs.pasqal.com/pulser/apidoc/_autosummary/pulser_simulation.QutipBackendV2/)
  e [`BitStrings`](https://docs.pasqal.com/pulser/apidoc/_autosummary/pulser.backend.BitStrings/).