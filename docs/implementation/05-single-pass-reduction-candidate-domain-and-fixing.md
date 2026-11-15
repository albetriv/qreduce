# M05 - Riduzione single-pass, candidate domain e fixing

## Stato

**Completata.** La verifica del 2026-11-12 ha confermato il percorso single-pass: normalizzazione delle sample, repair, ranking, diversita`, protezioni, candidate domain, fixing manifest e failure con dati parziali auditabili.

## Scopo e confini

M05 trasforma gli esiti MWIS normalizzati in un dominio candidato effettivo `C_effective`, quindi costruisce un manifest esplicito per fissare gli item esclusi. Il dominio e` una proposta di ricerca: il solver classico puo` scegliere un sottoinsieme fattibile degli item trattenuti e non deve coincidere con una candidate MWIS sorgente.

Questa milestone non definisce il backend MWIS (M04), il solve residuo o il post-check (M06), la persistenza degli artifact (M07), ne` la semantica inter-round o il recovery (M08).

## Riferimenti normativi

- Sezioni 7, 8, 10, 13, 16.2, 18, 20.4 e 20.5 di `../specifications.md`.
- `00-implementation-overview.md`.

## Dipendenze

**Prerequisiti:** M02 fornisce configurazione risolta, contratti adapter, stati,
reason e metriche; M03 fornisce grafo MWIS e metriche canoniche per le sample;
M04 produce sample binarie normalizzate nel `node_order` canonico.

**Integrazione a valle:** M06 riceve il problema ristretto e il fixing manifest
per solve residuo e post-check.

## Implementazione ed evidenze

L'orchestrazione single-pass e` in `src/qreduce/pipeline/single_pass.py`. Dopo deduplicazione e validazione strutturale, il percorso esegue repair deterministico quando abilitato, costruisce `CandidateRecord`, seleziona candidate soggette alla diversita` Jaccard e aggrega il loro contenuto in `C_effective`.

Prima del cap, l'adapter puo` dichiarare `mandatory`, `user_locked`, `safe_retained` e `incumbent_supported` tramite `ProtectionDeclaration`. Le prime tre categorie, e gli incumbent configurati come `required`, hanno precedenza sul cap. Gli incumbent `best_effort` restano auditabili anche se esclusi con reason `best_effort_protection_excluded_by_cap`. Protezioni obbligatorie oltre il cap terminano con `protected_items_exceed_candidate_domain_cap`, prima del fixing.

Il `FixingManifest` conserva item trattenuti ed esclusi, `round_index`, candidate sorgenti, versione di policy, origine e livello di garanzia per ogni entry. Il kernel verifica la corrispondenza esatta tra manifest e dominio effettivo prima della restriction; l'adapter conserva la responsabilita` di tradurre il fixing sulle variabili di dominio collegate.

La ratio misura gli item del grafo dopo protezioni e cap; nel single-pass
`round_reduction_ratio` e `cumulative_reduction_ratio` coincidono.

### Metriche di riduzione, sample e candidate

| Requisito/osservazione | Campo nel risultato | Disponibilita` | Evidenza principale |
|---|---|---|---|
| Tempo end-to-end | `end_to_end_runtime_seconds` | Sempre, anche in failure prima del grafo | `_run_metrics` in `src/qreduce/pipeline/single_pass.py`; `tests/experiments/portfolio/test_portfolio_single_pass.py` |
| Compilation ed esecuzione MIS | `mis_compilation_runtime_seconds`, `mis_execution_runtime_seconds`, `mis_runtime_seconds` | Dopo compilation/esecuzione MIS raggiunta | `_run_metrics`; `tests/solving/mwis/test_pipeline_capability_gate.py` |
| Backend MIS effettivo | `mis_provider_id`, `mis_backend_id`, `mis_backend_family`, `mis_execution_mode`, `mis_device_id` | Dopo esecuzione MIS | `_run_metrics`; `tests/solving/mwis/test_contracts.py` |
| Sample raw e distinte | `raw_sample_count`, `unique_sample_count` | Dopo normalizzazione; le distinte sono contate prima del cap | `_run_metrics`; `tests/experiments/portfolio/test_portfolio_single_pass.py` |
| Sample elaborate e repair | `processed_unique_sample_count`, `repaired_candidate_count` | Dopo applicazione di cap e repair | post-elaborazione dei `CandidateRecord`; `tests/experiments/portfolio/test_portfolio_single_pass.py` |
| Candidate e dominio | `valid_candidate_count`, `selected_candidate_count`, `candidate_domain_size` | Dopo ranking, diversita`, protezioni e cap | `_candidate_metrics`; `tests/pipeline/test_single_pass_selection.py` |
| Riduzione e conteggi logici | `round_reduction_ratio`, `cumulative_reduction_ratio`, `original_variable_counts`, `residual_variable_counts` | Dopo costruzione del dominio; i conteggi residui richiedono restriction | `LogicalVariableCounts`; `tests/domains/test_logical_variable_counts.py` |

Le metriche sono progressive: una failure iniziale espone solo il tempo
end-to-end; i campi MIS compaiono solo se la relativa fase e` stata raggiunta;
sample, candidate e dominio compaiono soltanto dopo l'elaborazione corrispondente.
Le metriche di solve e post-check sono documentate in M06.

## Test e verifica

- `tests/pipeline/test_single_pass_selection.py` verifica ranking, diversita`, cap, protezioni e reason di esclusione.
- `tests/experiments/portfolio/test_portfolio_single_pass.py` verifica il percorso end-to-end e i rami di failure con dati intermedi.
- `tests/domains/test_fixing_guarantees.py` verifica provenienza e garanzia delle entry del manifest.
- `tests/domains/test_logical_variable_counts.py` e `tests/domains/test_evaluation_metrics.py` verificano conteggi e metriche esposte dagli adapter.

## Criteri di completamento

- Sample non valide, duplicate e riparate restano distinguibili nel risultato.
- `C_effective` applica in ordine aggregazione, protezioni dichiarate, precheck e cap, senza aggiunte implicite.
- Il fixing manifest e` completo, serializzabile e coerente con il dominio.
- Failure di pipeline preservano le metriche e i dati gia` prodotti quando disponibili.
- Il fixing euristico non dichiara preservazione dell'ottimo originale.

## Esclusioni e lavoro successivo

M05 e` un singolo round. Monotonicita` fra round, recovery con espansione del dominio e manifest cumulativi sono responsabilita` di M08. Il modo unificato che seleziona single-pass, multi-round o baseline e` documentato in M09.

## Riferimenti correlati

- [M02 - Contratti core](02-core-contracts-configuration-status-and-provenance.md)
- [M04 - Backend MWIS](04-mwis-execution-backends-and-adapter-contracts.md)
- [M06 - Solve residuo e post-check](06-residual-solving-post-check-and-portfolio-experiment.md)
- [M08 - Riduzione multi-round e recovery](08-multi-round-reduction-and-recovery.md)
- [M09 - Pipeline unificata e baseline](09-unified-pipeline-and-classical-baseline.md)