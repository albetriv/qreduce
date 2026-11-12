# M07 - Runner e artifact di esperimento

Il runner interno pubblica in modo atomico i JSON del run e il manifest con
hash, configurazione e policy provenance redatta. Il loader controlla gli hash
dei file interni, incluso l'eventuale modello esportato. I notebook leggono gli
artifact e non eseguono la pipeline. Export esterni non fanno parte della stessa
transazione atomica; il loro hash e` registrato ma non verificato dal loader.

Evidenze: `tests/experiments/test_runner.py`, test integrazione SCIP/CPLEX e
`src/qreduce/experiments/artifacts.py`. Le failure normalizzate sono persistite;
una failure di serializzazione impedisce la pubblicazione finale.

## Stato della verifica

**Stato: Completata.** Verifica del 2025-01-15.

### Copertura test

| Requisito | Test | Evidenza |
|---|---|---|
| Pubblicazione atomica | `test_runner_persists_normalized_failure_for_notebook_analysis` | Directory pubblicata solo se completa |
| Verifica hash | `test_loader_rejects_artifacts_changed_after_publication` | Modifica post-pubblicazione rilevata |
| Rifiuto sovrascrittura | `test_runner_refuses_to_overwrite_a_published_experiment` | Secondo run stesso ID rifiutato |
| Round-trip esiti terminali | `test_terminal_outcomes_round_trip_through_artifact_serialization` | 4 scenari: success, partial_success, failed_postcheck, failed_classical |
| Policy provenance redatta | `test_manifest_preserves_redacted_policy_provenance` | Token redatto, provenance conservata |
| Model export interno | `test_model_export_is_published_and_auditable[False]` | Hash verificato, tamper rilevato |
| Model export esterno | `test_model_export_is_published_and_auditable[True]` | Registrato nel manifest |
| Domain metrics | `test_domain_metrics_persist_and_redact` | Metriche serializzate, provenance redatta |

### Semantiche escluse

Le semantiche multi-round restano M08. Il manifest di fixing contiene round,
candidate, versione policy e garanzie per entry.