# Esperimento facility location

L'esperimento facility location verifica la pipeline QReduce con istanze del
problema capacitated facility location. È sperimentale ed escluso dal wheel.

## Problema di dominio

Il modello usa domanda frazionabile, collegamenti completi, costi fissi e
costi di allocazione per l'intera domanda. L'adapter facility location:

- identifica ogni sede (facility) come item riducibile;
- costruisce il grafo di ridondanza basato su profili di costo e capacità;
- fissa a chiuse le sedi escluse;
- compila un MILP residuo con vincoli di domanda e capacità.

Gli archi indicano ridondanza euristica, non incompatibilità. I fixing non
sono certificati e l'ottimalità residua non dimostra quella originale.

## Dataset

Le istanze OR-Library sono benchmark pubblici. Devono essere acquisite
localmente dall'utente; non sono previsti download automatici.

Percorso atteso:

```text
data/benchmarks/or_library/capacitated_facility_location/
├── cap41.txt
├── cap42.txt
├── ...
```

Le istanze sono escluse da Git tramite `.gitignore`. Il manifest descrive i
byte locali, non certifica autenticità o diritti di redistribuzione.

## Esecuzione

### Baseline (senza riduzione)

```bash
poetry run python -m qreduce.experiments.facility_location.run \
  data/benchmarks/or_library/capacitated_facility_location/cap41.txt \
  --run-id cap41-baseline
```

`--rounds 0` (default): il problema è risolto direttamente senza riduzione.

### Single-pass con recovery

```bash
poetry run python -m qreduce.experiments.facility_location.run \
  data/benchmarks/or_library/capacitated_facility_location/cap41.txt \
  --run-id cap41-recovery \
  --rounds 1 \
  --recovery-attempts 15
```

`--recovery-attempts`: tentativi di allargare il dominio se insufficiente.

### Multi-round

```bash
poetry run python -m qreduce.experiments.facility_location.run \
  data/benchmarks/or_library/capacitated_facility_location/cap41.txt \
  --run-id cap41-multi \
  --rounds 3 \
  --recovery-attempts 15
```

La pipeline si arresta al primo successo o successo parziale.

## Opzioni CLI

| Opzione                | Descrizione                                  | Default |
|------------------------|----------------------------------------------|---------|
| `instance`             | Percorso file istanza OR-Library             | obblig. |
| `--run-id`             | Identificatore unico del run                 | obblig. |
| `--output-root`        | Directory base per artifact                  | outputs/facility_location |
| `--rounds`             | Numero massimo di round di riduzione         | 0       |
| `--solver`             | Backend classico: `scip` o `cplex`           | scip    |
| `--mis-solver`         | Backend MIS                                  | local_greedy |
| `--seed`               | Seed random                                  | 7       |
| `--budget`             | Time limit in secondi                        | 60      |
| `--cap`                | Max items nel dominio candidato              | #sedi   |
| `--protect-all`        | Proteggi tutte le sedi (verifica baseline)   | false   |
| `--recovery-attempts`  | Tentativi di recovery                        | 0       |
| `--min-reduction-ratio`| Ratio minima di riduzione                    | 0.1     |
| `--model-export`       | Esporta modello residuo                      | false   |

### Opzioni graph policy

| Opzione                | Descrizione                                  | Default |
|------------------------|----------------------------------------------|---------|
| `--alpha`              | Peso capacità nello score                    | 0.5     |
| `--epsilon`            | Floor dello score                            | 0.01    |
| `--profile-fraction`   | Quota profilo per overlap                    | 0.5     |
| `--overlap-threshold`  | Soglia overlap pesato per arco               | 0.5     |
| `--capacity-difference`| Max differenza relativa capacità             | 0.25    |

## Policy del grafo (versione 1)

Lo score combina capacità utile e costo indicativo:

```text
D = sum_j d_j
effective_i = min(u_i, D)
proxy_i = f_i + effective_i * sum_j(c_ij) / D
max_proxy = max_k(proxy_k)

cost_component_i = 1 - proxy_i / max_proxy   se max_proxy > 0
cost_component_i = 1                          se max_proxy = 0

w_i = epsilon + (1 - epsilon) * (
    alpha * effective_i / max_k(effective_k)
    + (1 - alpha) * cost_component_i
)
```

Quando tutti i costi proxy sono zero, il componente costo vale 1 per tutte
le sedi (nessuna penalizzazione basata sul costo).

I profili sono costruiti sull'istanza originale, ordinando i clienti per
costo unitario e indice. Gli archi collegano sedi con overlap elevato e
capacità simile.

## Directory degli artifact

```text
outputs/facility_location/{run_id}/
├── run_result.json
├── config_used.json
├── problem.json
├── experiment_metadata.json
├── run_manifest.json
├── round_NN_result.json      # uno per ogni round di riduzione completato
└── recovery_attempts.json    # se sono stati eseguiti tentativi di recovery
```

## Notebook

I notebook sono in `notebooks/experiments/facility_location/`. Caricano
artifact già prodotti.

Il notebook individua la root del repository cercando `pyproject.toml` nella
directory corrente e nei genitori. Eseguire il notebook dalla root o da una
sottodirectory del repository.

## Codici di uscita

- `0`: success o partial_success
- `1`: altri stati (failed, adapter_failure, etc.)

Un run fallito (failure normalizzata della pipeline) viene comunque pubblicato
come artifact analizzabile. Errori di parsing o configurazione prima
dell'invocazione del runner non producono artifact.

## Risultati esplorativi

Valutazione su quattro istanze cap41-44 (SCIP, seed 7, budget 60s, 15
recovery attempts):

| Istanza | Baseline     | Single-pass | Con recovery   | Differenza    |
|---------|-------------:|-------------|---------------:|--------------:|
| cap41   | 1040444.375  | fallito     | 1157583.050    | +117138.675   |
| cap42   | 1098000.450  | fallito     | 1212583.050    | +114582.600   |
| cap43   | 1153000.450  | fallito     | 1267583.050    | +114582.600   |
| cap44   | 1235500.450  | fallito     | 1350083.050    | +114582.600   |

Questi risultati non dimostrano vantaggi: la policy è sperimentale e le
differenze mostrano perdite di qualità rispetto alla baseline.

## Riferimenti

- Adapter: `src/qreduce/experiments/facility_location/adapter.py`
- Graph policy: `src/qreduce/experiments/facility_location/graph_policy.py`
- Parser: `src/qreduce/experiments/facility_location/datasets.py`
- Documentazione architetturale: [`facility-location-experiment.md`](../implementation/facility-location-experiment.md)
