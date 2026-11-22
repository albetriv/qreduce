# Piano di integrazione Pasqal in Qreduce

## Stato e obiettivi

Piano parzialmente implementato: `pasqal_local` e disponibile; benchmark e
test aggiuntivi restano aperti, mentre cloud e QPU non sono ancora implementati.
Dettagli in `docs/implementation/pasqal-local-status.md`. Integrare Pasqal come solver MIS
selezionabile, mantenendo separate tre modalità:

1. Emulazione locale Pulser/QuTiP, senza credenziali cloud.
2. Emulatori online Pasqal, con scelta esplicita del servizio disponibile.
3. QPU Pasqal reale, con scelta esplicita del dispositivo disponibile.

Gli ID remoti indicativi `pasqal_cloud_emulator` e `pasqal_qpu` sono proposte,
non ID attualmente disponibili. Nessun passaggio
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

Aggiungere a `CompiledMISJob` un payload opzionale con tipo e versione di
schema, opaco per il kernel. Per Pasqal contiene la sequenza nel formato JSON
astratto di Pulser (`Sequence.to_abstract_repr()`), il target effettivo,
coordinate, ordine, parametri, metodo ed eventuale seed del mapping, diagnostica
e versione SDK. L'adapter valida il payload e ricostruisce la sequenza in
`solve()`; testare il round trip. Lasciare invariato il campo BQM di D-Wave.
Non archiviare oggetti SDK vivi, né copiare il payload in ogni campione.

`compile()` non invia job. Per il remoto, propagare da config e CLI la scelta
esplicita del servizio emulatore o del dispositivo QPU fino alla richiesta di
compilazione e al job compilato. La pipeline oggi non inoltra
`MISCompilationRequest.requested_device_id`: cablarlo per il dispositivo QPU e
tenere distinto l'ID del servizio emulatore. Entrambe le modalità cloud usano
`ExecutionMode.REMOTE`; non serve introdurre un nuovo valore per distinguerle.

## Fase 0 - Verifica SDK

Usare le release più recenti non prerelease al momento dell'implementazione,
senza supportare API legacy. Baseline verificata su PyPI il 21 novembre 2026:
`pulser`, `pulser-core` e `pulser-simulation` **1.10.1** (17 novembre 2026);
per la Fase 2, `pasqal-cloud` **0.24.0**. Per il locale dichiarare
`pulser-simulation` come dipendenza opzionale: include `pulser-core` senza
installare l'SDK cloud. Aggiungere `pasqal-cloud` solo per il remoto.

Su Windows/Python 3.12, risolvere e fissare le dipendenze opzionali nel lock
all'avvio della fase pertinente. Per il locale, fare uno smoke test con
`QutipBackendV2`, una sequenza di pochi atomi e la lettura dei conteggi finali
tramite `BitStrings`. Verificare ordine dei bit e totale delle occorrenze.
La versione pubblicata non dimostra compatibilità con il lock del progetto:
se la risoluzione fallisce, documentare il conflitto senza downgrade silenziosi.

## Fase 1 - Mapping ed emulatore locale

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
6. Registrare il solver e renderlo selezionabile da configurazione e CLI per
   almeno un esperimento end-to-end, con parametri validati. Rimandare la UI
   finché il flusso CLI non è verificato; non blocca la chiusura dell'MVP.

## Fase 2 - Emulatori online Pasqal

1. Integrare `PasqalCloudConnection` e partire da un solo servizio selezionato
   esplicitamente, `RemoteEmuFreeBackend`, da verificare per il progetto
   Pasqal. Distinguere ciò che è supportato dall'adapter da ciò che risulta
   accessibile all'account. Non selezionare automaticamente un altro target.
2. Validare API, versioni, parametri, limiti, rumore, autorizzazioni e costi per
   ciascun servizio: non assumere gratuità, disponibilità o intercambiabilità.
3. Mantenere `solve()` sincrono e salvare negli artefatti del run, appena
   disponibili e prima del polling, `batch_id`, eventuali `job_ids` e target
   effettivo. Prevedere un comando di recupero per ID che non invii nuovi job;
   non serve un job manager. Distinguere timeout dell'attesa (il job può ancora
   essere attivo) da esito di submission ignoto (timeout prima di ricevere
   l'ID): in quest'ultimo caso non ritentare automaticamente, ma riconciliare
   con il provider prima di un eventuale nuovo invio.
4. Prima dell'invio, verificare che il target effettivo coincida con quello
   selezionato. Esporre costi e limiti ove disponibili e richiedere un consenso
   esplicito se il job può avere un costo o il costo è ignoto. Non effettuare
   job reali durante i test automatici standard.
5. Normalizzare bitstring e occorrenze sul grafo originale, senza confondere
   frequenze o score del provider con energia QUBO canonica.

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

Usare un file di profili gestito da Qreduce, esterno al repository, ad esempio
`%USERPROFILE%\.qreduce\pasqal-credentials` su Windows. È un formato proposto
per Qreduce, non un formato nativo Pasqal verificato. L'utente crea e compila il
file in privato; non inserire credenziali reali in conversazioni o repository.

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
- Chiudere la Fase 1 con un run CLI end-to-end e un benchmark che riporti
  quota di grafi compilabili, quota di shot validi prima del repair (sul
  totale delle occorrenze ricevute, prima dei cap) e divario di peso tra il
  miglior candidato valido e l'ottimo esatto sulle istanze piccole. Riportare
  separatamente gli esiti con repair e i casi senza candidati validi; non
  richiedere che il metodo euristico trovi sempre l'ottimo.
- Testare CLI e pipeline, compresi parametri non supportati, budget e limiti.
  Testare la UI quando verrà integrata.
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