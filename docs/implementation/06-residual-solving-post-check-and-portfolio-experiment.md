# M06 - Solve residuo, post-check ed esperimento portfolio

## Stato

**Completata.** Le evidenze nel repository coprono il modello residuale
solver-agnostic, i backend classici built-in `scip` e `cplex`, il post-check e
l'esperimento sintetico media-varianza. La suite completa e` stata rieseguita
nella revisione documentale del 2026-11-14; l'indisponibilita` di un binding e
l'infeasibility sono esiti serializzabili espliciti.

## Scopo e confini

M06 riceve il problema ristretto e il fixing manifest da M05, compila un `ClassicalOptimizationModel` indipendente dal provider, risolve il modello residuo e valida la soluzione rispetto al problema originale. L'adapter portfolio e` un esempio interno: non e` una policy finanziaria, un benchmark o una dipendenza del kernel.

M06 non sceglie candidate MWIS e non persiste i risultati. Il fixing resta una riduzione euristica; il solve residuale non trasferisce un certificato di ottimalita` al problema originale.

## Riferimenti normativi

- Sezioni 4, 10, 13, 14, 15, 16.2, 17, 20.5 e 20.7 di `../specifications.md`.
- `00-implementation-overview.md`.

## Dipendenze

**Prerequisiti:** M02 fornisce contratti, configurazione, stati, tolleranze e
metadata; M05 fornisce candidate domain, problema ristretto e fixing manifest.

**Integrazione a valle:** M07 persiste il risultato normalizzato e gli artifact
dell'esperimento portfolio.

## Implementazione ed evidenze

`src/qreduce/solving/residual/` definisce il modello classico generico, i contratti, il registry e le traduzioni lazy per CPLEX e SCIP. Il backend selezionato riceve solo il modello solver-agnostic e non conosce il dominio concreto. Binding non disponibili, capability incompatibili, time limit e infeasibility producono reason normalizzate senza fallback automatico.

L'adapter sintetico in `src/qreduce/experiments/portfolio_domain/` tratta ogni asset come item. Per gli asset esclusi applica `delta_i = 0` e `x_i = 0`, preserva obiettivo e vincoli globali nel MIQP residuo, ed esegue il post-check sul problema originale con il manifest applicato.

Il post-check separa stato del solver, fattibilita` dichiarata, fattibilita`
verificata e adozione. Eccezioni o risultati invalidi dell'adapter diventano
`adapter_failure` e preservano solve e manifest gia` disponibili; una soluzione
non supera l'adozione se il post-check non e` raggiunto o non e` fattibile.

Dopo un post-check raggiunto, `evaluate_domain_metrics` puo` produrre metriche
con identificatore, valore, unita`, convenzione e provenance. Un errore nella
valutazione genera `adapter_failure` senza scartare gli esiti precedenti.

### Metriche di solve, post-check e dominio

| Requisito/osservazione | Campo nel risultato | Disponibilita` | Evidenza principale |
|---|---|---|---|
| Tempo e fattibilita` del solve residuo | `classical_runtime_seconds`, `classical_solver_claimed_feasible` | Dopo invocazione del backend classico | `_run_metrics`; `tests/experiments/test_portfolio_single_pass.py` |
| Obiettivo, bound e gap | `objective_value`, `best_bound`, `solver_gap` | Quando il backend classico restituisce il risultato | `_run_metrics`; `test_time_limit_with_feasible_incumbent_produces_partial_success` |
| Fattibilita` del post-check | `postcheck_feasible`, `postcheck_failure_reasons` | Solo dopo post-check raggiunto | `_run_metrics`; `tests/experiments/portfolio_domain/test_postcheck.py` |
| Obiettivo ricalcolato | `objective_recomputed` | Solo se l'adapter lo supporta e il post-check lo calcola | `_run_metrics`; `tests/experiments/portfolio_domain/test_postcheck.py` |
| Metriche di dominio | `domain_evaluation_metrics` con valore, unita`, convenzione e provenance redatta | Solo dopo post-check raggiunto; `None` se il post-check non e` raggiunto | `evaluate_domain_metrics`; `test_domain_metrics_persist_and_redact` |
| Stati e dati parziali | `run_status`, `terminal_reason`, `classical_result`, `postcheck_result` | Progressivamente, senza cancellare dati di stage precedenti | `test_classical_solver_infeasible_is_serialized_with_candidate_data` e test di failure post-check |

Le metriche classiche non sono fabricate se il solve non viene raggiunto. Un
time limit con incumbent fattibile puo` produrre `partial_success` con bound e
gap; un solve infeasible conserva candidate e fixing manifest; failure o output
non valido del post-check conserva il risultato classico ma impedisce l'adozione.

## Test e verifica

- `tests/solving/residual/` verifica contratti, registry e backend classici.
- `tests/experiments/test_portfolio_scip_integration.py` verifica il percorso portfolio predefinito con SCIP.
- `tests/experiments/test_portfolio_single_pass.py` verifica backend CPLEX non disponibile, infeasibility e preservazione di manifest/candidate.
- `tests/experiments/portfolio_domain/test_postcheck.py` verifica il post-check.
- `tests/domains/test_evaluation_metrics.py` verifica le metriche di dominio.

## Criteri di completamento

- Il core e i backend classici non dipendono dal dominio portfolio.
- L'adapter fornisce un mapping completo e auditabile da item a variabili fissate.
- Il solve residuo conserva obiettivo e vincoli hard del problema originale.
- Infeasibility, indisponibilita` del backend e failure di post-check sono esiti espliciti con dati intermedi preservati quando disponibili.
- Nessuna soluzione e` adottata dopo un post-check fallito.

## Esclusioni e lavoro successivo

Il contratto residuale corrente copre MILP e MIQP con vincoli lineari. Vincoli quadratici, conici, indicatori o non lineari richiedono riformulazione o un'estensione esplicita. CPLEX richiede inoltre binding e licenza utilizzabili nell'ambiente locale.

## Riferimenti correlati

- [M02 - Contratti core](02-core-contracts-configuration-status-and-provenance.md)
- [M05 - Riduzione single-pass](05-single-pass-reduction-candidate-domain-and-fixing.md)
- [M07 - Runner e artifact](07-experiment-runner-artifacts-and-analysis-notebooks.md)
- [M09 - Pipeline unificata e baseline](09-unified-pipeline-and-classical-baseline.md)