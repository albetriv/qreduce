# Integrazione Pasqal: stato e limiti

Il piano `PIANO_INTEGRAZIONE_PASQAL.md` descrive anche funzionalita future;
non e una dichiarazione che tutte le fasi siano completate. L'integrazione
locale usa il backend `pasqal_local`, con Pulser/QuTiP e dispositivo
`AnalogDevice`. Il gruppo Poetry `experiments` installa `pulser-simulation`,
`pulser-core` e `pasqal-cloud` con `poetry install --with experiments`.
Il backend locale non usa credenziali o servizi cloud. Per lo stato del
backend remoto, vedere la Fase 2; non è registrato un backend QPU.

## Miglioramenti implementati (Piano correzione MWIS)

A partire dalla versione corrente, il backend Pasqal include:

### Presolve esatto per grafi senza archi
Grafi senza archi (tutti i nodi compatibili) vengono risolti in modo esatto
senza invocare il backend. Per un grafo di 12 nodi senza archi, il presolve
seleziona tutti i 12 nodi (risolvendo il problema osservato dove l'impulso
costante selezionava solo 8/12). Il presolve è:
- Certificato ottimale
- Trasparente (dichiarato nel payload e nei sample metadata)
- Backend-agnostico (eseguito prima del mapping)

### Strategia di impulso parametrica
L'impulso costante originale è sostituito da un annealing parametrico:
- Durata: 4000 ns (4 µs)
- Ampiezza: rampa 0→max→max→0 (15% ramp-up, 15% ramp-down)
- Detuning: sweep lineare da -10 a +10 rad/µs
- L'impulso costante legacy è disponibile con `use_legacy_pulse=True`

### Codifica pesi dichiarata esplicitamente
Il backend dichiara `WeightEncodingMode.CLASSICAL_RANKING`:
- I pesi NON sono codificati fisicamente nell'Hamiltoniana
- I pesi sono usati solo per il ranking classico dei campioni
- Questa trasparenza evita fraintendimenti sulla natura del solver

### Diagnostica impulso e geometria
Il payload compilato include:
- Configurazione della strategia di impulso
- Diagnostica delle interazioni (distanza minima, rapporti)
- Diagnostica di geometria (fedeltà mapping, interazioni spurie)
- Confronto minimo fisico vs ottimo canonico (per grafi piccoli)
- Metadati per audit e debugging

### Correzioni builder e validazioni
- Builder pubblico (`build_pulse_sequence`): corretto per usare limiti canale-specifici
  invece di `device.max_amp`, e tempi normalizzati [0, 1] per `InterpolatedWaveform`
- Validazioni uniformi: identità job, shots, random_seed e time budget sono validati
  PRIMA del branch presolve/Pulser, garantendo comportamento coerente
- Provenienza presolve corretta: `occurrence_count=1` (risultato deterministico) e
  `source_provider_id="qreduce"` (computato da QReduce, non dal backend)

## Moduli aggiunti

- `audit.py`: Contratti per tre livelli di audit (raw sample, validated candidate, final domain)
- `presolve.py`: Presolve esatto per grafi trivialmente risolvibili
- `pulse_strategy.py`: Configurazioni parametriche per sequenze di impulso
- `completion.py`: Completamento classico opzionale (default disabilitato)
- `geometry_diagnostics.py`: Diagnostica fedeltà geometria-Hamiltoniana

## Integrazione diagnostica e completamento

### Diagnostica geometria nel payload compilato
Il payload di compilazione include:
- `geometry_diagnostics`: Analisi delle interazioni fisiche rispetto alla struttura del grafo
  - `is_valid`: Se tutti gli archi hanno interazioni forti e nessun non-arco ha interazioni spurie
  - `fidelity_score`: Score 0-1 che misura la corrispondenza geometria-grafo
  - `weak_edge_count`: Archi con interazione insufficiente per imporre indipendenza
  - `spurious_interaction_count`: Non-archi con interazione significativa
  - `warnings`: Problemi rilevati nel mapping

- `physical_vs_canonical`: Confronto stato fondamentale fisico vs ottimo MWIS canonico
  - Solo per grafi piccoli (≤12 nodi) dove l'enumerazione è trattabile
  - `ground_state_matches_optimum`: Se il minimo fisico coincide con l'ottimo
  - `energy_gap_to_optimum`: Gap energetico tra stato fondamentale e ottimo

### Completamento classico opzionale
Il completamento è integrato nella pipeline (`single_pass.py`):
- Disabilitato per default (`completion_enabled=False`)
- Configurabile in `MISExecutionOptions`:
  - `completion_enabled`: Abilita/disabilita il completamento
  - `completion_policy_id`: Policy da usare (default: "disabled")
- Applicato DOPO repair, solo a campioni validi
- Produce independent set massimali (non ottimali)

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

## Verifica locale e copertura residua

Un run CLI portfolio MV con 6 asset, 64 shot e solver residuo SCIP ha
completato anche il postcheck. Una verifica preliminare del solo backend ha
usato i grafi MV sintetici di 6, 8, 10 e 12 asset, con generazione e seed del
layout predefiniti. Con la policy `near_duplicate` predefinita i grafi erano
senza archi: tutti compilati, 400/400 shot validi senza repair o cap e divario
relativo dal peso esatto del 34,7%, 49,4%, 36,1% e 49,1% rispettivamente.
Con `correlation_only` e soglia 0,35 i grafi erano clique: nessuno è stato
compilato (`layout_search_exhausted`, non una prova di impossibilità).
Il mapper supera invece i test di regressione su C4 e K4.

**Con il presolve**, i grafi senza archi sono ora risolti in modo esatto con
divario 0% dall'ottimo.

Il primo confronto non prova utilità su grafi con conflitti reali. Per
chiudere la Fase 1 serve un corpus più rappresentativo, con densità intermedie
e più run stocastici: riportare separatamente rifiuti, shot validi prima del
repair, divario dall'esatto, assenza di candidati validi ed esiti con repair.

L'emulazione remota e l'uso di QPU restano fasi future; non eseguire job o
spese senza autorizzazione esplicita. I notebook restano strumenti di
presentazione e non ospitano l'implementazione del benchmark.

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


## Fase 2: Emulatori cloud Pasqal

La Fase 2 implementa l'esecuzione remota su emulatori Pasqal Cloud tramite il
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

### Uso dalla CLI

```bash
python -m qreduce.experiments.portfolio_mv \
  --run-id test-cloud \
  --asset-count 6 --graph-edge-mode correlation_only --correlation-threshold 0.9 \
  --mis-solver-id pasqal_cloud_emulator \
  --pasqal-emulator-service emu_free \
  --pasqal-shots 100
```

Questo comando invia un batch reale se il grafo richiede esecuzione remota.

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
- QReduce limita prudenzialmente l'invio a 12 atomi, seguendo la scheda
  dettagliata del catalogo Pasqal. Il limite non si applica al presolve locale.
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
