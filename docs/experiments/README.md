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
- CLI delle famiglie (convenzione): `outputs/<famiglia>` (es. `outputs/portfolio`)

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

L'architettura comune è descritta in
[`docs/implementation/experiment-organization.md`](../implementation/experiment-organization.md).

## Famiglie disponibili

| Famiglia            | Stato         | Guida                                    |
|---------------------|---------------|------------------------------------------|
| portfolio           | completo      | [portfolio.md](./portfolio.md)           |
| facility_location   | sperimentale  | [facility-location.md](./facility-location.md) |

Ogni guida descrive: comandi CLI, parametri specifici, convenzioni dei run ID,
posizione dei notebook, interpretazione dei risultati.
