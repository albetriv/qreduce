# Integrazione Pasqal: stato e limiti

QReduce offre tre backend distinti: `pasqal_local`,
`pasqal_cloud_emulator` e `pasqal_qpu`. Il gruppo Poetry `experiments`
installa Pulser e l'SDK cloud; il backend locale non richiede credenziali.
Per installare le dipendenze usare `poetry install --with experiments`.
La disponibilità effettiva dipende dalle versioni installate e dall'accesso
al servizio; le funzionalità cloud di Pasqal non sono tutte supportate da QReduce.

Il presolve Pasqal risolve esattamente i grafi senza archi prima del mapping.
Il risultato è deterministico e non rappresenta una misura fisica. I pesi MWIS
sono usati nel ranking classico, non codificati nell'Hamiltoniana. La
diagnostica del payload include geometria, impulso e confronto con l'ottimo
canonico per grafi piccoli; il completamento classico è opzionale e
disabilitato per default.

## Backend locale `pasqal_local`

Il backend usa Pulser/QuTiP con `AnalogDevice` ed esegue localmente.

## Mapping e geometria

Il mapping locale posiziona i nodi vicino ai vicini già collocati, con un
budget di tentativi, e verifica
gli archi e i non-archi con soglia 10 e margine 1 micrometro, oltre ai vincoli
del dispositivo. L'esaurimento della ricerca non dimostra che un grafo non
sia rappresentabile. La soglia geometrica e un'approssimazione, non una
garanzia di comportamento fisico. La sequenza e un'euristica MIS: i pesi MWIS
sono valutati classicamente e non sono codificati nella sequenza. Non sono
garantite fattibilita o ottimalita dei campioni.

## Limiti noti del modello fisico

Il controesempio a due nodi mostra che il modello fisico attuale può favorire
violazioni degli archi:
- Due nodi connessi da un arco, distanza 6.68 µm
- Interazione fisica: ~9.72 rad/µs (C6/r^6 con C6 = 862690)
- Detuning finale: 10 rad/µs
- Energia([1,0]) = -10, Energia([1,1]) = -20 + 9.72 = -10.27
- Lo stato fondamentale fisico è [1,1] (entrambi selezionati), che viola l'arco

**Conseguenza:** anche con evoluzione adiabatica perfetta, il sistema può
trovare stati che non sono independent set validi.

**Correzione applicata:** il backend usa il C6 effettivo di `AnalogDevice` e
limita il detuning finale standard alla metà dell'interazione sull'arco più
debole (senza aumentare il default). Per la coppia isolata serve:

```text
interaction_ab > final_detuning
```

Non il contrario. Per grafi generali questa disuguaglianza non basta a
certificare l'obiettivo MWIS o a trascurare le interazioni sui non-archi.
Il backend enumera tutti gli stati entro il limite locale e rifiuta la
compilazione se anche uno dei minimi diagonali fisici viola l'indipendenza.
Il rifiuto usa `MIS_DEVICE_MAPPING_FAILED`; non viene restituito un job valido.
`allow_unfaithful_physics=true` permette solo un'esecuzione sperimentale,
esplicitamente marcata nel payload. Il controllo non garantisce che la dinamica
finita produca campioni indipendenti o ottimi.

La diagnostica confronta tutti i minimi degeneri per indipendenza e qualità
dell'obiettivo, non l'uguaglianza con un singolo ottimo arbitrario. Il gap è
calcolato rispetto alla minima energia fisica tra tutti gli ottimi canonici.
Per l'impulso legacy con ampiezza finale non nulla, il confronto riguarda solo
la parte diagonale, non il vero ground state quantistico; questo ambito è
registrato in `physical_validation_scope`.

Il backend accetta `layout_attempts`, `layout_seed`, `use_legacy_pulse` e `allow_unfaithful_physics` in
compilazione e `shots` in esecuzione. In assenza di `shots`, usa il numero di
soluzioni richieste come numero di misure, non come numero di campioni distinti.
Nelle CLI portfolio MV e SR `--pasqal-shots` imposta il numero di misure
(default 100); il cap dei campioni distinti coincide con gli shot e non tronca
l'istogramma prima del ranking. Il limite locale è di 12 atomi, distinto dal
limite fisico del dispositivo. Il seed del layout non controlla il sampling.
Il backend non supporta seed di sampling, timeout o cancellazione. Nelle CLI
portfolio MV e SR, una riduzione con questo backend richiede esplicitamente
`--max-end-to-end-runtime-seconds=0`: l'emulatore non puo garantire il rispetto
di una scadenza.

## Audit delle trasformazioni e presolve

Il presolve controlla versione, ordine dei nodi, valori binari, peso, cardinalità,
motivo e certificazione confrontandoli con il risultato esatto ricalcolato.
Non accetta un vettore subottimo o un payload alterato. Le opzioni di compilazione
sono validate anche quando non viene costruito un impulso.
Provider effettivo e sorgente del risultato sono `qreduce`, backend
`presolve_exact`; il backend richiesto resta registrato. Gli shot richiesti sono
conservati ma `effective_shots=0`: viene prodotto un solo risultato deterministico
(`deterministic_result_count=1`, `occurrence_count=1`), non una misura fisica.
Il presolve è per ora attivato nel backend Pasqal, non è un bypass universale
delle verifiche di disponibilità/capacità della pipeline per tutti i solver.

Il completamento è disabilitato per default e richiede flag e policy coerenti.
Il candidate record conserva vettori raw, dopo repair e dopo completamento,
energie distinte, nodi rimossi/aggiunti, policy e tempo di completamento.
La deduplicazione dopo le trasformazioni somma le occorrenze e unisce gli ID
delle sorgenti prima di occupare gli slot di selezione.
Il confronto UI mostra presolve, codifica dei pesi, strategia, esito del controllo
di indipendenza e aggiunte classiche; negli artefatti precedenti i dati assenti
restano non disponibili, senza ricostruzioni arbitrarie.

I nuovi payload usano versione 3. Payload Pasqal precedenti devono essere
ricompilati: non vengono eseguiti implicitamente senza le nuove verifiche fisiche.
Questo riguarda il contratto di esecuzione, non la lettura UI degli artefatti storici.


## Emulatore cloud `pasqal_cloud_emulator`

QReduce implementa l'esecuzione remota su emulatori Pasqal Cloud tramite il
backend `pasqal_cloud_emulator`. Questo backend è separato da `pasqal_local` e
richiede:
- Le dipendenze del gruppo Poetry `experiments`
- Credenziali Pasqal Cloud configurate
- Selezione esplicita del servizio emulatore

### Installazione

```bash
# Pulser/QuTiP e SDK Pasqal Cloud
poetry install --with experiments
```

### Backend `pasqal_cloud_emulator`

Il backend `pasqal_cloud_emulator` compila localmente con Pulser ed esegue
remotamente su Pasqal Cloud. Caratteristiche:

- **Compilazione locale**: usa Pulser/AnalogDevice come il backend locale
- **Presolve**: grafi senza archi sono risolti esattamente senza invio cloud
- **Servizio esplicito**: richiede `_emulator_service` (solo `emu_free` supportato)
- **Solo servizio gratuito**: nessun consenso sintetico e nessun fallback a servizi a pagamento
- **Persistenza pre-polling**: il batch ID viene salvato atomicamente prima della prima lettura

### Architettura invio/polling

L'architettura separa esplicitamente:
1. **Invio** (`submit_sequence`): usa il formato e il trasporto di `pasqal-cloud`
   0.24.0 senza passare da `submit()` o dai retry del POST; non segue redirect
2. **Callback persistenza**: chiamato tra invio e polling, scrive atomicamente
   il job reference su file
3. **Polling** (`wait_for_completion`): attende completamento con budget monotono
4. **Lettura** (`read_batch_results`): recupera i risultati dal batch completato
5. **Decodifica** (`decode_results_to_samples`): converte a RawMISSample,
   condivisa tra esecuzione diretta e recupero

Questo design garantisce che:
- Non partano letture del batch prima della scrittura durevole dell'ID
- Se la persistenza fallisce, l'errore include il batch_id per recupero manuale
- Il recupero usa la stessa logica di lettura/decodifica dell'esecuzione diretta

### Budget monotono

Il timeout per il polling viene calcolato come budget residuo:
```
budget_residuo = budget_iniziale - tempo_già_speso_in_solve()
```
Il budget limita nuove letture e pause del polling. Non interrompe una chiamata
SDK già in corso, inclusi i retry delle letture: non è una deadline rigida.

### Verifica TLS

Il backend **rifiuta** la connessione se la variabile `PASQAL_SKIP_SSL_VERIFY`
è impostata. Questa è una protezione contro configurazioni insicure che
disabilitano la verifica TLS. Il check si applica sia a `solve()` che a
`recover_job_results()`.

Il modulo condiviso `qreduce.cloud_tls` può fornire a un SDK un bundle
temporaneo con le CA pubbliche di `certifi` e la CA di `~/.cato/cato-ca.pem`.
Pasqal lo applica tramite `REQUESTS_CA_BUNDLE` per tutta l'operazione cloud,
dall'autenticazione alla lettura dei risultati, anche in recupero. Se
`REQUESTS_CA_BUNDLE` o `CURL_CA_BUNDLE` sono già impostate a un valore non
vuoto, vengono rispettate. Se la CA locale manca si usa il comportamento
standard; se è presente ma non valida, il backend restituisce un errore.
Il bundle temporaneo viene rimosso e l'ambiente del processo ripristinato
al termine. Durante l'operazione la variabile è visibile a tutto il processo;
non vengono modificati il contesto `ssl` globale, la shell o i file di sistema.

### Uso dalla CLI

In UIX, **Portfolio MV → 03 · Solver → Backend MIS → Pasqal QPU (hardware reale)**
genera lo stesso comando di esecuzione con un round, device, shot e consenso
espliciti. Il browser non usa credenziali e non interroga il cloud. I preferiti
non salvano il consenso né il comando QPU già autorizzato.

```bash
python -m qreduce.experiments.portfolio_mv \
  --run-id test-cloud \
  --asset-count 6 --graph-edge-mode correlation_only --correlation-threshold 0.9 \
  --mis-solver-id pasqal_cloud_emulator \
  --pasqal-emulator-service emu_free \
  --pasqal-shots 100
```

Questo comando invia un batch reale se il grafo richiede esecuzione remota.

Il configuratore Portfolio MV offre **Pasqal Cloud (EMU_FREE)** solo con la
riduzione attiva. Usa lo stesso campo Shot di Pasqal locale, ma accetta anche
un budget positivo. La UIX genera il comando senza leggere credenziali, inviare
batch o recuperarli; per il recupero si usa il sottocomando CLI `recover-pasqal`.

### Credenziali

Le credenziali sono risolte in ordine:
1. Variabili d'ambiente: `PASQAL_USERNAME`, `PASQAL_PASSWORD`, `PASQAL_PROJECT_ID`
2. File profilo: `~/.pasqual/credentials`

Esempio di file profilo (da creare manualmente, NON committare):

```ini
[default]
username = <your-pasqal-email>
password = <your-pasqal-password>
project_id = <your-project-id>
```

Proteggere il file con ACL appropriati e non sincronizzarlo su cloud.

### Persistenza e recupero dei job

Il backend salva le informazioni del job (batch_id, node_order, shots,
atom_to_node_map) **immediatamente dopo l'invio, prima di iniziare il polling**.
Questo consente il recupero dei risultati in una sessione successiva senza
reinviare il job.

Il riferimento si trova in `<output-root>/.pasqal-cloud-jobs/<run-id>/`,
fuori dagli artefatti pubblicati a fine run. Per recuperare campioni canonici:

```bash
poetry run python -m qreduce.experiments.portfolio_mv recover-pasqal \
  --reference "$OUTPUT_ROOT/.pasqal-cloud-jobs/$RUN_ID/pasqal_cloud_job_$BATCH_ID.json"
```

Senza riferimento, usare `--batch-id` e `--project-id` insieme: verranno
restituiti solo i conteggi grezzi e l'ordine degli atomi. Il progetto deve
coincidere con quello delle credenziali. Il comando restituisce JSON e usa
i codici `0` per successo, `2` per batch ancora pendente o attesa scaduta,
e `1` per errori di recupero o stati terminali non riusciti.

Funzioni di persistenza disponibili:
- `save_job_reference()`: salva prima del polling
- `load_job_reference()`: carica un riferimento salvato
- `recover_job_results()`: recupera risultati da batch_id senza reinvio
- `recover_job_to_samples()`: recupero completo con decodifica a RawMISSample
- `find_job_references()`: cerca riferimenti in una directory

Lo schema persistente (versione 1.1) include:
- batch_id e service
- project_id (non segreto, per audit)
- run_id, round_index, compiled_job_id
- node_order e atom_to_node_map per la decodifica risultati
- shots, timestamp, profilo e versione SDK

### Validazioni

Il backend valida:
- Disponibilità SDK (Pulser per compilazione, pasqal-cloud per esecuzione)
- Credenziali configurate
- Servizio emulatore supportato
- TLS non disabilitato
- Coerenza payload compilato vs esecuzione
- Target configurato vs compilato

### Limiti attuali

- Solo `emu_free` supportato (nessun MPS, SV, o QPU)
- Nessun fallback automatico tra servizi
- Il timeout locale non annulla il job remoto
- QReduce limita prudenzialmente l'invio a 12 atomi, come limite dell'integrazione QReduce. Il limite non si applica al presolve locale.
- Se la creazione fallisce senza ID e senza un rifiuto certo, l'esito è ignoto:
  riconciliare con Pasqal prima di qualsiasi nuovo invio.
- Lo smoke test su servizio reale richiede autorizzazione esplicita

### Test

I test non richiedono credenziali Pasqal Cloud. Il test end-to-end usa le
classi SDK reali e intercetta tutte le richieste HTTP:
- Validazioni di configurazione e parametri
- Presolve per grafi senza archi
- Persistenza job reference (schema 1.1)
- Sanitizzazione errori SDK (nessun segreto nei log)
- Tampering payload
- **End-to-end**: singola submission, persistenza pre-polling, recovery senza reinvio
- **Verifica TLS**: rifiuto connessione con TLS disabilitato

```bash
poetry run pytest tests/solving/mwis/test_pasqal_cloud_emulator_backend.py \
  tests/experiments/portfolio_mv/test_pasqal_cloud_flow.py -v
```


## QPU reale `pasqal_qpu`

QReduce implementa l'esecuzione su QPU reale tramite il backend `pasqal_qpu`.
Questo backend è separato da `pasqal_cloud_emulator` e richiede:
- Le dipendenze del gruppo Poetry `experiments`
- Credenziali Pasqal Cloud configurate
- Selezione esplicita del device QPU
- Consenso esplicito ai potenziali costi

### Backend `pasqal_qpu`

Il backend `pasqal_qpu` compila localmente con Pulser ed esegue remotamente su
QPU Pasqal Cloud. Caratteristiche:

- **Discovery dinamica**: interroga Pasqal Cloud per i device disponibili
- **Compilazione locale**: usa Pulser con specifiche del device target
- **Presolve**: grafi senza archi sono risolti esattamente senza invio QPU
- **Device esplicito**: richiede `--pasqal-device-id` (es. 'FRESNEL')
- **Consenso**: `--pasqal-cost-consent` è richiesto per l'invio e verificato
  nella richiesta di esecuzione; non serve per il preflight
- **Shot espliciti**: richiede `--pasqal-shots` esplicito (nessun default)
- **Persistenza pre-polling**: il batch ID viene salvato atomicamente prima della prima lettura

### Uso dalla CLI

```bash
# 1. Scoprire i device disponibili
python -m qreduce.experiments.portfolio_mv preflight --discover

# 2. Testare la compilazione senza invio
python -m qreduce.experiments.portfolio_mv preflight \
  --compile --device-id FRESNEL --asset-count 6

# 3. Eseguire un run completo
python -m qreduce.experiments.portfolio_mv \
  --run-id test-qpu \
  --asset-count 6 --graph-edge-mode correlation_only --correlation-threshold 0.9 \
  --mis-solver-id pasqal_qpu \
  --pasqal-device-id FRESNEL \
  --pasqal-shots 100 \
  --pasqal-cost-consent
```

### Differenze da EMU_FREE

| Aspetto | EMU_FREE | QPU |
|---------|----------|-----|
| Device ID | Fisso `cloud:emu_free` | Dinamico (es. `FRESNEL`) |
| Cost consent | Non richiesto | Obbligatorio |
| Shots | Default 100 | Esplicito, obbligatorio |
| Discovery | Non necessaria | Disponibile via preflight |
| max_runs | Non applicabile | Verificato vs limite device |

### Schema di persistenza

Lo schema 1.2 aggiunge:
- `target_type`: "emulator" o "qpu" per distinguere il tipo di job
- `device_id`: ID del device QPU (es. "FRESNEL")

I job reference esistenti (schema 1.0, 1.1) restano leggibili con valori
inferiti per i nuovi campi.

### Preflight

Il comando `preflight` esegue discovery o compilazione senza submission:

```bash
# Elencare i device QPU disponibili
python -m qreduce.experiments.portfolio_mv preflight --discover

# Compilare senza inviare il job
python -m qreduce.experiments.portfolio_mv preflight \
  --compile --device-id FRESNEL --asset-count 6
```

L'output è JSON leggibile da script per automazione. Usare un ID restituito
dalla discovery, che non conferma accesso al calcolo o disponibilità di crediti.
`--compile` genera un'istanza sintetica con le opzioni indicate e usa la
stessa costruzione canonica del run. Per conservare invece il problema
originale, usare `--from-artifacts`:

```bash
python -m qreduce.experiments.portfolio_mv preflight \
  --from-artifacts "$RUN_DIRECTORY" --device-id "$DEVICE_ID" \
  --compilation-time-limit-seconds 60
```

Il loader verifica gli hash del manifest e legge il modello canonico del
round 0 senza rigenerarlo. Il mapper cerca direttamente sulle trappole
calibrate idonee. Un registro rifiutato non esclude da solo l'intero layout.
L'output distingue `qpu_sequence_validated` (inclusa la misura) da
`presolve_only` e mostra diagnostica geometrica ed esito della ricerca.
La deadline è cooperativa: non interrompe una chiamata SDK già in corso.

Per un dispositivo con `accepts_new_layouts: true` nella discovery, aggiungere
`--layout-mode custom` per provare un layout generato dal grafo, senza
riusare le coordinate dell'emulatore. Il percorso normale resta calibrato.
`--sequence-output "$NEW_FILE"` conserva la sequenza misurata esatta; non
invia alcun job. Un preflight locale riuscito non prova che il nuovo layout
sia già calibrato né che il progetto possa eseguire il batch.

`submit-preflight --check-only` verifica offline il report, gli artefatti e
la sequenza salvata. Per un invio autorizzato, il comando usa gli stessi byte
e il journal registra l'intenzione prima del POST. In caso di esito ambiguo
non riutilizzare il run ID né crearne uno nuovo per ripetere il tentativo:
riconciliare prima il journal con Pasqal Cloud e, se c'è un riferimento,
usare `recover-pasqal --reference`.

### Validazioni

Il backend valida:
- Disponibilità SDK (Pulser per compilazione, pasqal-cloud per esecuzione)
- Credenziali configurate
- Device disponibile nel progetto
- TLS non disabilitato
- Coerenza payload compilato vs esecuzione
- Target configurato vs compilato
- Limiti del device (max_atoms, max_runs)
- Variazione delle specifiche tra compilazione ed esecuzione
- Archi, non-archi e margine geometrico sulle trappole finali

### Limiti attuali

- Un solo device alla volta (scelto esplicitamente)
- Nessun fallback automatico tra device o a EMU
- Un solo round e un solo tentativo di creazione. Se l'esito del POST è ignoto,
  riconciliare con Pasqal prima di un nuovo invio
- Il timeout locale non annulla il batch remoto
- La cancellazione automatica non è supportata
- La compilazione richiede connessione cloud per recuperare le specifiche del device
- Lo smoke test su QPU reale richiede autorizzazione esplicita e crediti

### Test

I test non richiedono credenziali Pasqal Cloud o accesso QPU:
- Capabilities e configurazione
- Discovery e preflight senza invio; compilazione su un layout Pulser e
  rifiuto delle assegnazioni fuori margine
- Invio con consenso, rifiuto se le specifiche cambiano e distinzione tra
  rifiuto certo ed esito ignoto, senza retry
- Flusso con trasporto simulato: un POST, journal prima del polling, lettura
  e recupero con verifica del device
- Esecuzione presolve
- Schema persistenza 1.2
- Verifica TLS

```bash
poetry run pytest tests/solving/mwis/test_pasqal_qpu_backend.py \
  tests/experiments/portfolio_mv/test_pasqal_cloud_flow.py -v
```
