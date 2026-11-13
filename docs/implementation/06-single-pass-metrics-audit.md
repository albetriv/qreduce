# Audit metriche single-pass - specifiche 16.2

> **Nota**: Questo documento è un audit storico per la milestone single-pass.
> Con l'unificazione della pipeline (M09), le metriche sono ora accessibili
> tramite `PipelineRunResult` e `ReductionRoundResult`. I tipi legacy rimangono
> disponibili per compatibilità.

## Scopo

Verifica dei requisiti della sezione 16.2 di `docs/specifications.md` per il
percorso single-pass. L'audit traccia implementazione, test ed evidenze per
ogni metrica richiesta.

## Stato della verifica

**Stato: Completata.** Verifica del 2026-11-12.

## Matrice requisito -> stato

Ogni riga indica se il requisito e` **Risolto** (implementato e testato),
**Escluso** (fuori dal perimetro single-pass) o **Residuo** (gap ancora aperto).

| Requisito 16.2 | Stato | Implementazione | Test/Evidenza |
|---|---|---|---|
| Conteggi binarie originali | Risolto | `LogicalVariableCounts.binary_free`; `describe_logical_variables` obbligatorio | `tests/domains/test_logical_variable_counts.py`; `test_default_portfolio_path_solves_with_scip` |
| Conteggi binarie residue | Risolto | `residual_variable_counts.binary_free` nel risultato | `test_default_portfolio_path_solves_with_scip` verifica `residual_variable_counts.binary_free == len(retained_item_ids)` |
| Conteggi continue/intere residue | Risolto | `LogicalVariableCounts.continuous_free`, `integer_free` | `test_default_portfolio_path_solves_with_scip` |
| Ratio per round | Risolto | `round_reduction_ratio` in `metrics` | `test_portfolio_single_pass_reaches_explicit_cplex_unavailable_failure` |
| Ratio cumulativa | Risolto | `cumulative_reduction_ratio` (coincide con round nel single-pass) | `test_portfolio_single_pass_reaches_explicit_cplex_unavailable_failure` |
| Tempo MIS totale | Risolto | `mis_runtime_seconds` in `metrics` | `_run_metrics` espone il campo |
| Tempo MIS compilation | Risolto | `mis_compilation_runtime_seconds` in `metrics` | `_run_metrics` espone il campo |
| Tempo MIS execution | Risolto | `mis_execution_runtime_seconds` in `metrics` | `_run_metrics` espone il campo |
| Provider, famiglia, modalita`, device | Risolto | Campi `mis_provider_id`, `mis_backend_id`, `mis_backend_family`, `mis_execution_mode`, `mis_device_id` | `tests/solving/mwis/test_contracts.py` |
| Tempo classico | Risolto | `classical_runtime_seconds` in `metrics` | `_run_metrics` espone quando `classical_result` disponibile |
| Tempo end-to-end | Risolto | `end_to_end_runtime_seconds` misurato per ogni esito | `test_missing_counts_method_fails_before_graph` verifica disponibilita` anche su failure iniziale |
| Sample raw | Risolto | `raw_sample_count` in `metrics` | `test_portfolio_single_pass_reaches_explicit_cplex_unavailable_failure` |
| Sample uniche | Risolto | `unique_sample_count` in `metrics` | `test_portfolio_single_pass_reaches_explicit_cplex_unavailable_failure` |
| Sample elaborate | Risolto | `processed_unique_sample_count` in `metrics` | `test_portfolio_single_pass_reaches_explicit_cplex_unavailable_failure` |
| Candidate riparate | Risolto | `repaired_candidate_count` in `metrics` | `test_portfolio_single_pass_reaches_explicit_cplex_unavailable_failure` |
| Candidate valide | Risolto | `valid_candidate_count` in `metrics` | `_candidate_metrics` |
| Candidate selezionate | Risolto | `selected_candidate_count` in `metrics` | `_candidate_metrics` |
| Dimensione candidate domain | Risolto | `candidate_domain_size` in `metrics` | `test_portfolio_single_pass_reaches_explicit_cplex_unavailable_failure` |
| Fattibilita` solve residuo | Risolto | `classical_solver_claimed_feasible` in `metrics`; `ClassicalSolverStatus` | `test_classical_solver_infeasible_is_serialized_with_candidate_data`; `test_time_limit_with_feasible_incumbent_produces_partial_success`; test SCIP integration |
| Fattibilita` post-check | Risolto | `postcheck_feasible` in `metrics`; `PostcheckStatus` in `RunResult` | `tests/experiments/portfolio_domain/test_postcheck.py` |
| Obiettivo solver | Risolto | `objective_value` in `metrics` e `classical_result` | Test SCIP integration |
| Obiettivo ricalcolato | Risolto | `objective_recomputed` in `metrics` quando disponibile | `original_primal_bound` in `SinglePassRunResult` |
| Bound e gap | Risolto | `best_bound`, `solver_gap` in `metrics` | Campi in `ClassicalSolveResult`; `test_time_limit_with_feasible_incumbent_produces_partial_success` verifica gap > 0 |
| Seed e parametri effettivi | Risolto | `effective_execution_parameters` in `MISBackendResult` e `ClassicalSolveResult` | `tests/solving/mwis/test_contracts.py` |
| Metriche di dominio | Risolto | `DomainEvaluationMetric`, `evaluate_domain_metrics` | `tests/domains/test_evaluation_metrics.py` |
| Run status | Risolto | `RunResult.run_status` | Tutti i test end-to-end |
| Terminal reason | Risolto | `RunResult.terminal_reason` | `test_classical_solver_infeasible_is_serialized_with_candidate_data`; tutti i test failure |
| Multi-round artifact | Escluso | Richiede M08 | N/A |
| Recovery e rollback | Escluso | Richiede M08 | N/A |

## Note implementative

### Conteggi variabili logiche

I conteggi in `LogicalVariableCounts` rappresentano variabili logiche libere del
problema, escluse le variabili esplicitamente fissate e le ausiliarie dei
backend. Non coincidono necessariamente con `variable_count` del solver, che
puo` includere variabili ausiliarie (es. epigrafo SCIP per obiettivo quadratico).

### Ratio di riduzione

La formula e` `(total_items - retained_items) / total_items` dove `total_items`
e` il numero di item nel grafo e `retained_items` il numero di item nel dominio
effettivo. Nel single-pass `round_reduction_ratio` e `cumulative_reduction_ratio`
coincidono.

### Disponibilita` per stage

Le metriche sono disponibili progressivamente: una failure iniziale (validazione,
lookup solver) produce `metrics` con solo `end_to_end_runtime_seconds`. Le
metriche MIS, candidate e classiche sono presenti solo se lo stage corrispondente
e` stato raggiunto.
