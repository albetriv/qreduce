# Piano di integrazione del logging

Data: 2026-11-16.

Stato: piano concordato, implementazione non ancora eseguita.

## Obiettivo

Introdurre in QReduce un sistema simile, come impostazione, a Log4j:
logger gerarchici, livelli, formatter, filtri e destinazioni multiple.
Usare `logging` della libreria standard Python e un file YAML esterno
per separare le scelte operative dal codice applicativo.

Il logging deve affiancare gli artifact e i risultati strutturati esistenti,
senza sostituirli e senza cambiare risultati, eccezioni o policy di fallback.

## Contesto verificato

- Il progetto supporta Python `>=3.12,<3.13`.
- Il package principale non dichiara dipendenze runtime.
- Non risulta presente una configurazione di logging applicativo.
- Pipeline e runner dispongono già di run, round, solver, recovery e failure
  utilizzabili come contesto diagnostico.
- Il runner pubblica gli artifact attraverso staging e pubblicazione atomica.
- PyYAML compare nel lockfile, ma non è una dipendenza diretta del progetto.

## Architettura

### Logger nei moduli

Ogni modulo usa `logging.getLogger(__name__)`, senza configurare handler
o destinazioni localmente. I logger appartengono alla gerarchia `qreduce`.

Esempio:

```python
import logging

logger = logging.getLogger(__name__)

logger.info("Starting residual solve")
```

### Separazione tra libreria e applicazione

- All'import, aggiungere soltanto un `NullHandler` al logger `qreduce`.
- Non configurare il root logger e non caricare automaticamente file YAML
  quando QReduce viene usato come libreria.
- Le CLI degli esperimenti configurano il logging esplicitamente all'avvio.
- L'applicazione ospite mantiene il controllo della propria configurazione.
- Rendere la configurazione ripetibile senza duplicare handler o lasciare
  aperti handler precedentemente creati dal configuratore QReduce.

### Loader centralizzato

Introdurre `src/qreduce/logging_config.py` con responsabilità di:

1. Caricare il file tramite `yaml.safe_load()`.
2. Validare struttura, campi necessari ed errori di configurazione.
3. Risolvere i percorsi relativi dei file di log rispetto alla directory YAML.
4. Creare le directory di destinazione richieste.
5. Applicare la configurazione con `logging.config.dictConfig()`.
6. Restituire errori di avvio chiari per configurazioni non utilizzabili.

Non introdurre un parser o un framework di logging alternativo.
Dichiarare PyYAML come dipendenza esplicita del componente che lo usa,
aggiornando `pyproject.toml` e lockfile senza affidarsi alla presenza transitiva.

Il file YAML è una configurazione fidata: `safe_load()` limita la
deserializzazione YAML, ma `dictConfig()` può istanziare oggetti indicati
nel file. Non accettare configurazioni arbitrarie provenienti da utenti
o sorgenti non fidate.

## File YAML proposto

Percorso nel repository: `config/logging.yaml`.

```yaml
version: 1
disable_existing_loggers: false

formatters:
  standard:
    format: "%(asctime)s %(levelname)-8s %(name)s | %(message)s"
    datefmt: "%Y-%m-%dT%H:%M:%S%z"

handlers:
  console:
    class: logging.StreamHandler
    level: INFO
    formatter: standard
    stream: ext://sys.stderr

  file:
    class: logging.handlers.RotatingFileHandler
    level: DEBUG
    formatter: standard
    filename: "../logs/qreduce.log"
    maxBytes: 10485760
    backupCount: 5
    encoding: utf-8

loggers:
  qreduce:
    level: DEBUG
    handlers: [console, file]
    propagate: false

  qreduce.pipeline:
    level: DEBUG

  qreduce.solving:
    level: INFO
```

L'esempio è una base di configurazione, non un file già disponibile.
Il formatter iniziale non richiede campi personalizzati. Durante
l'implementazione aggiungere il contesto con valori predefiniti per gli
eventi che non appartengono a un run o a un round.

### Destinazioni

- Console su `stderr`, livello predefinito `INFO`.
- File abilitabile tramite configurazione, livello handler `DEBUG`.
- Rotazione iniziale: 10 MiB per file, cinque backup.
- Preservare `stdout` e gli output operativi attuali delle CLI.
- Tenere inizialmente i log fuori dalle directory degli artifact:
  un errore di pubblicazione non deve cancellare la diagnostica disponibile.
- Ignorare in Git i log generati, senza ignorare il file YAML versionato.

Il livello del singolo logger può limitare gli eventi prima che arrivino
agli handler: nell'esempio `qreduce.solving` registra da `INFO` in su.

## Selezione della configurazione

Precedenza proposta per le CLI:

1. Opzione esplicita `--log-config`.
2. Variabile d'ambiente `QREDUCE_LOG_CONFIG`.
3. File predefinito del repository per le CLI degli esperimenti.

Definire una risoluzione del file predefinito indipendente dalla directory
corrente e verificarla anche negli scenari di installazione supportati.
Il core importato come libreria non dipende dalla presenza del repository.

Un percorso esplicitamente selezionato ma inesistente, illeggibile o non
valido deve produrre un errore chiaro all'avvio, senza fallback silenzioso.
Il file predefinito previsto dalle CLI deve essere distribuito o individuato
in modo coerente; documentare e testare gli errori se non disponibile.

Nella prima versione caricare la configurazione una sola volta all'avvio.
Non introdurre hot reload. Livelli e destinazioni si controllano dal YAML;
eventuali ulteriori override CLI non sono necessari nella prima versione.

## Contesto e contenuto degli eventi

Prevedere i seguenti campi quando applicabili:

- `run_id`;
- `round_index`;
- `stage`;
- `solver_id`;
- durata, conteggi ed esito.

Isolare il contesto per esecuzione, valutando `contextvars`, senza dizionari
globali mutabili condivisi e senza aggiungere parametri di logging a tutte
le API. Ripristinare sempre il contesto al termine di un'esecuzione.

Non promettere propagazione automatica tra thread o processi: eventuali
esecuzioni concorrenti richiedono gestione e test espliciti. La rotazione
di un unico file condiviso da più processi non è un requisito iniziale;
per quel caso prevedere in seguito un writer centralizzato o file separati.

### Livelli

| Livello | Utilizzo |
|---|---|
| DEBUG | Conteggi intermedi e dettagli diagnostici non sensibili |
| INFO | Inizio/fine run, round, fasi principali ed esito solver |
| WARNING | Recovery, anomalie recuperabili e risultati degradati |
| ERROR | Failure terminali e problemi di persistenza |

Un problema infeasible non è automaticamente un errore software:
scegliere il livello secondo il significato dell'evento.

### Vincoli

- Non registrare matrici complete, dataset o configurazioni integrali.
- Riutilizzare, dove appropriato, le regole di redazione dei metadati.
- Controllare anche messaggi e traceback: la sola redazione dei campi
  strutturati non garantisce l'assenza di informazioni sensibili.
- Evitare duplicazione dello stesso errore a ogni livello della chiamata.
- Usare traceback per eccezioni diagnostiche pertinenti, non per normali
  esiti del solver.
- Evitare calcoli costosi per messaggi disabilitati.
- Non sostituire indiscriminatamente i `print` di presentazione o output CLI.
- Tenere distinta la diagnostica Python dall'output nativo dei solver;
  l'eventuale cattura dei log nativi richiede integrazione dedicata.

## Sequenza di implementazione

1. Verificare specifiche e convenzioni correnti prima di modificare il codice.
2. Aggiungere dipendenza YAML, loader, configurazione di esempio e gestione
   non invasiva del logger di libreria.
3. Aggiungere supporto al contesto e al formato con campi opzionali.
4. Strumentare pipeline unificata, round, recovery e failure terminali.
5. Strumentare il runner, inclusi persistenza e pubblicazione artifact.
6. Integrare selezione YAML nelle CLI portfolio e facility location.
7. Aggiornare, se impattati, i configuratori HTML e i relativi test.
8. Aggiornare documentazione e completare le verifiche.

## Test e criteri di accettazione

- Importare QReduce non configura console, file o root logger.
- Il logger della libreria si integra con la configurazione dell'host.
- YAML valido, malformato, vuoto o con struttura errata è gestito chiaramente.
- Percorsi inesistenti o non utilizzabili producono errori comprensibili.
- I percorsi relativi si risolvono rispetto al YAML, anche cambiando cwd.
- La precedenza CLI, ambiente e default è verificata.
- Le configurazioni ripetute non duplicano messaggi o handler.
- Livelli per logger e handler, propagazione e rotazione sono verificati.
- I messaggi privi di contesto non causano errori di formattazione.
- Il contesto di run e round non passa a esecuzioni successive.
- Failure e recovery producono eventi coerenti senza duplicazioni inutili.
- `stdout`, risultati, eccezioni e artifact esistenti restano compatibili.
- I test ripristinano lo stato globale del logging e usano directory temporanee
  gestite dalle fixture per i propri file.
- Eseguire test mirati, suite pertinente e controlli Ruff nell'ambiente progetto.

## Allineamento documentale

Verificare e aggiornare soltanto gli artefatti effettivamente impattati:

- specifiche e documentazione di implementazione;
- README e guide operative degli esperimenti;
- dipendenze e lockfile;
- esempi CLI, configuratori HTML e test;
- esempi e notebook eventualmente interessati.

I notebook devono continuare a importare logica Python, senza contenere
implementazioni del loader o business logic di logging.

Nel riepilogo dell'implementazione indicare artefatti modificati, documenti
verificati senza modifiche necessarie e risultati dei controlli eseguiti.

## Fuori ambito iniziale

- Framework aggiuntivi come Loguru o structlog.
- Hot reload della configurazione.
- Invio a servizi remoti o piattaforme di osservabilità.
- Logging JSON strutturato come formato predefinito.
- Gestione multiprocesso con writer centralizzato.
- Modifiche ai contratti dei risultati o allo schema degli artifact.

## Stato del presente intervento

Questo documento salva il piano nella root del workspace.
Non introduce moduli Python, dipendenze, configurazioni operative o nuove
funzionalità. L'implementazione e i relativi test restano da eseguire.