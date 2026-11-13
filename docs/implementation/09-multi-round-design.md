# M08: riduzione multi-round e recovery

Stato: **implementata**. L'orchestratore multi-round è eseguibile e coperto da test.

## Requisiti delle specifiche

Il runner applica le sezioni 9 delle specifiche: ogni round parte dal problema
residuo precedente e dal relativo dominio, senza reintrodurre item esclusi.
I tentativi di recovery ricostruiscono dal problema di inizio round e sono
registrati separatamente; il post-check finale considera il problema originale
e tutti i fixing cumulativi.

## Implementazione

### Configurazione (`src/qreduce/models.py`)

`ReductionPolicy` include i parametri di recovery:

```python
max_reduction_rounds: int                      # >= 1, default 1
recovery_policy_on_domain_too_small: str       # "fail" | "retry_with_larger_domain"
recovery_policy_on_infeasible: str             # "fail" | "retry_with_larger_domain"
max_recovery_attempts: int                     # >= 0
```

La validazione in `config.py` verifica:
- `max_reduction_rounds >= 1` (rimosso il vincolo single-pass)
- Policy di recovery valide
- `max_recovery_attempts > 0` richiede almeno una policy diversa da `fail`

### Orchestratore (`src/qreduce/pipeline/multi_round.py`)

`run_multi_round` implementa l'iterazione:

1. **Loop sui round**: chiama `_run_single_pass_with_counts` con `_round_index`
   corretto, passando il problema residuo del round precedente.

2. **Criteri di stop**:
   - Success o partial success
   - `max_reduction_rounds` raggiunto
   - `min_reduction_ratio` non soddisfatto (stallo del dominio)
   - `target_binary_variables` raggiunto
   - Budget temporale end-to-end esaurito
   - Dominio candidato troppo piccolo

3. **Recovery operativa**: quando una failure è recuperabile (`CANDIDATE_DOMAIN_TOO_SMALL`
   o `CLASSICAL_SOLVER_INFEASIBLE` con policy `retry_with_larger_domain`):
   - Espande il dominio usando `expand_ranked_domain` e `rank_recovery_items`
   - Ricostruisce P_t con il dominio espanso tramite `_run_with_expanded_domain`
   - Ri-esegue fixing, solve classico e post-check con il nuovo dominio
   - Registra ogni tentativo in `RecoveryAttempt` con trigger, dimensioni e outcome

4. **Manifest cumulativo**: `cumulative_fixing_manifest` da `rounds.py` unisce
   i manifest di tutti i round, verificando monotonicità e assenza di conflitti.
   Gli errori di validazione non sono silenziati e causano failure esplicita.

5. **Post-check con fixing cumulativi**: il post-check finale valida contro il
   problema **originale** con il manifest **cumulativo**, non solo quello del round.

### Risultato (`MultiRoundRunResult`)

```python
@dataclass(frozen=True, slots=True)
class MultiRoundRunResult:
    run_result: RunResult
    resolved_config: ResolvedRunConfig
    round_results: tuple[SinglePassRunResult, ...]
    recovery_attempts: tuple[RecoveryAttempt, ...]  # ogni tentativo registrato
    cumulative_fixing_manifest: FixingManifest | None
    original_variable_counts: LogicalVariableCounts | None
    residual_variable_counts: LogicalVariableCounts | None
    final_retained_item_ids: tuple[str, ...]
    classical_result: ClassicalSolveResult | None
    metrics: Mapping[str, object]  # include round_count, recovery_attempt_count
```

### `RecoveryAttempt`

```python
@dataclass(frozen=True, slots=True)
class RecoveryAttempt:
    attempt_index: int
    trigger_reason: TerminalReason
    expanded_domain_size: int
    previous_domain_size: int
    outcome: str  # "success", "exhausted", "retry", "failed"
```

### Primitive di supporto

- `recovery.py`:
  - `expand_ranked_domain`: aggiunge un item per tentativo, deterministico
  - `rank_recovery_items`: completa il ranking con item non selezionati per peso

- `rounds.py`:
  - `validate_round_manifest`: verifica partizione corretta del dominio di round
  - `validate_manifest_sequence`: verifica monotonicità inter-round
  - `cumulative_fixing_manifest`: unisce i manifest preservando provenance

### Propagazione round_index

Il parametro `_round_index` viene propagato attraverso la pipeline single-pass a:
- `MISCompilationRequest.round_index`
- `MISBackendRequest.round_index`
- `FixingManifest.round_index`
- `ClassicalSolveRequest.round_index`

## Test

21 test in `tests/pipeline/test_multi_round.py` coprono:
- Single round equivalente a single-pass
- Stop on success
- Max rounds limit
- Manifest cumulativo
- Monotonicità del dominio
- Item esclusi che non riappaiono
- Propagazione round_index ai backend
- Validazione recovery policy
- Validazione recovery attempts
- Metriche round_count
- Serializzazione risultato
- **Recovery espande effettivamente il dominio su infeasible** (con assert su `expanded_domain_size > previous_domain_size`)
- **RecoveryAttempt registrati con metadati corretti**
- **Recovery si ferma quando il dominio non può espandersi**
- **Errori cumulative manifest sollevano ValueError** (verifica diretta su `cumulative_fixing_manifest`)
- **Post-check usa problema originale** (verifica tipo `SimpleProblem`)
- **Infeasible senza recovery termina immediatamente**
- **Adapter failure in `build_fixing_manifest` durante recovery**
- **Adapter failure in `restrict_problem` durante recovery**
- **Adapter failure in `validate_candidate_domain` durante recovery**

Test di configurazione in `tests/test_config.py` coprono i nuovi parametri.

Test del runner in `tests/experiments/test_runner.py`:
- **`test_multi_round_experiment_persists_round_artifacts`**: verifica persistenza
  artifact multi-round, manifest con `run_mode`, `round_count`, `recovery_attempt_count`

## Integrazione Runner M07

Il runner `run_experiment` supporta `mode="multi_round"`:
- Esegue `run_multi_round` invece di `run_single_pass`
- Persiste `round_XX_result.json` per ogni round
- Persiste `recovery_attempts.json` se presenti
- Il manifest include `run_mode`, `round_count`, `recovery_attempt_count`

## Esportazione

`run_multi_round`, `MultiRoundRunResult` e `RecoveryAttempt` sono esportati da
`qreduce.pipeline`.

## Invarianti garantite

- **Monotonicità**: `V_(t+1) ⊆ V_t` - il dominio non cresce mai tra round
- **Esclusione permanente**: un item escluso non può rientrare in round successivi
- **Partizione**: ogni manifest partiziona esattamente il dominio di input del round
- **Provenance**: i manifest di round sono preservati per auditabilità
- **Recovery operativa**: l'espansione del dominio modifica effettivamente P_t
- **Post-check cumulativo**: validazione finale contro problema originale + tutti i fixing
- **Failure path espliciti**: errori adapter in recovery producono `ADAPTER_FAILURE`