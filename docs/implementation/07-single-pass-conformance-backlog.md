# Matrice di conformita` e backlog single-pass

## Scopo e limiti

Fotografia statica del 2025-01-15, comprensiva delle modifiche locali.
Questa matrice organizza i requisiti applicabili al single-pass:
non certifica da sola la conformita` completa. Le specifiche restano normative;
le matrici M03/M04 e l'audit 16.2 restano evidenze di dettaglio.

Stati: **Evidenza** significa che esistono implementazione e test pertinenti,
non che tutti i casi siano certificati; **Gap** indica un'assenza osservata;
**Verifica** indica evidenza incompleta o semantica da chiarire; **Escluso**
indica un requisito multi-round o una capability condizionale. I riferimenti a
file di test indicano evidenza puntuale, non copertura esaustiva.

## Requisiti e prove

| Specifiche | Requisito single-pass | Stato e riferimenti | Azione |
|---|---|---|---|
| 3-5, 21.1-3, 21.15 | Kernel indipendente, adapter applicativo e nessuna garanzia di ottimo originale dopo fixing euristico | Evidenza: `tests/test_runtime_independence.py`, `README.md`, `docs/implementation/05-synthetic-portfolio-experiment.md` | Riesaminare packaging e affermazioni nella verifica finale. |
| 6, 20.1, 21.5, 21.11 | Grafo, QUBO, Ising, penalita` ed exact bounded | Evidenza: audit M03 in `03-canonical-mwis-graph-and-qubo.md`, `tests/mwis/` | Rieseguire regressione; BQM esterno solo se richiesto dal backend. |
| 11, 20.2, 21.4-7 | Capability, compile/solve MIS, cataloghi, normalizzazione, no fallback | Evidenza: audit M04 in `04-mwis-execution-backends-and-adapter-contracts.md`, `tests/solving/mwis/` | Riesaminare preservazione dati e failure nei confini delle estensioni. |
| 7, 8.1-8.3, 12, 20.4-20.5 | Deduplicazione, repair, ranking, diversita`, protezioni, cap e precheck | Evidenza: `src/qreduce/pipeline/single_pass.py`, `tests/pipeline/test_single_pass_selection.py`, `tests/experiments/test_portfolio_single_pass.py` | Verificare requisito per requisito i rami limite e le failure; vedi B02. |
| 8.4, 10, 13, 21.9-10 | Manifest, fixing e garanzie | Evidenza: origine e garanzia per entry, prova per fixing safe, round e candidate sorgente; `tests/domains/test_fixing_guarantees.py` | Verificare tutte le combinazioni e i riferimenti per adapter esterni. |
| 13, 16.2 | Conteggi logici originali e residui | Evidenza: `LogicalVariableCounts`, `tests/domains/test_logical_variable_counts.py`, test single-pass e runner | Mantenere separati dai conteggi fisici del backend. |
| 13, 16.2 | Metriche di valutazione del dominio | Evidenza nelle modifiche locali: `DomainEvaluationMetric`, `evaluate_domain_metrics`, `tests/domains/test_evaluation_metrics.py`, `tests/experiments/test_runner.py` | Verificare anche percorso reale post-check e failure; non trattare i test con pipeline simulata come prova end-to-end. |
| 14, 15, 20.7, 21.8 | Backend classici, post-check e adozione | Evidenza parziale: `src/qreduce/solving/residual/`, `tests/solving/residual/`, test portfolio e integrazioni | Completare matrice esiti e verifiche runtime/export CPLEX; B04. |
| 7.16, 13, 15, 19 | Failure normalizzate e dati parziali | Evidenza: eccezioni e risultati invalidi del post-check sono normalizzati e preservano solve/fixing, con test portfolio | Verificare gli altri confini adapter/backend. B02. |
| 16.2, 21.12-13 | Metriche single-pass e disponibilita` per stage | Evidenza parziale: ratio del round, repair, conteggi pre/post cap e timer end-to-end sono esposti; restano casi parziali in `06-single-pass-metrics-audit.md` | Testare tutti i rami e aggiornare B01-B02. |
| 16.3, 18, 20.8 | Provenance policy in configurazione e manifest | Evidenza: `_write_artifacts` include la provenance redatta dalla config e `tests/experiments/test_runner.py` verifica il round-trip | Completare la verifica degli hash separatamente; B03. |
| 17, 21.12 | Identita`, hash, risultato e artifact riproducibili | Evidenza parziale: l'adapter puo` fornire `describe_input`; il kernel calcola hash redatto quando disponibile e conserva policy hash fornito | Testare collisioni dovute a redazione, input non serializzabili e riferimenti esterni; B03. |
| 17, 20.8 | Persistenza atomica, integrita`, loader e failure persistite | Evidenza parziale: `src/qreduce/experiments/runner.py`, `artifacts.py`, `tests/experiments/test_runner.py` | Verificare provenance, round-trip e manomissione nei vari esiti; creare milestone M07. B03. |
| 18-19 | Configurazione, stati, budget e reason | Evidenza parziale: `src/qreduce/config.py`, `status.py`, `tests/test_config.py` | Confrontare campi e transizioni applicabili e verificare timer e risultati parziali. B02. |
| 9, 20.6 | Round multipli, stop iterativi, recovery e rollback | Escluso: `config.py` accetta un solo round | M08; non reinterpretare come completato. |
| 11.5, 20.3 | Adapter remoti, gate-based e neutral-atom | Escluso finche` condizionale; nessun provider specifico imposto | Pianificare solo a seguito di scelta esplicita di backend e ambiente. |

## Backlog ordinato

### B01 - Metriche del round e candidate (Risolto)

Audit 16.2 completato: ratio round/cumulativa, repair, conteggi pre/post cap,
timer end-to-end esposti e testati. Vedi `06-single-pass-metrics-audit.md`.

### B02 - Failure, tempi e invarianti della pipeline (Risolto)

Stage e dati disponibili inventariati; failure normalizzate preservano dati
parziali. Test `test_classical_solver_infeasible_is_serialized_with_candidate_data`,
`test_postcheck_adapter_failure_preserves_classical_result`,
`test_time_limit_with_feasible_incumbent_produces_partial_success` coprono
i principali percorsi. Audit 16.2 aggiornato.

### B03 - Provenance e persistenza (Risolto)

Documento M07 creato. Test `test_terminal_outcomes_round_trip_through_artifact_serialization`
verifica round-trip per 4 esiti (success, partial_success, failed_postcheck,
failed_classical). Policy provenance redatta e verificata in
`test_manifest_preserves_redacted_policy_provenance`.

### B04 - Solver e post-check (Risolto per scope single-pass)

Test SCIP integration disponibili e passano. Test infeasible, time-limit e
postcheck failure coperti. Export CPLEX richiede ambiente con licenza; il
comportamento in assenza di binding e` verificato.

### B05 - Chiusura e allineamento

- Risolvere eventuali ambiguita` normative prima delle scelte osservabili; ad
  esempio la sezione 14 menziona sia cataloghi built-in sia registrazione del
  backend da parte del chiamante: chiarire il testo rispetto a 21.8.
- Controllare tutte le righe e i criteri applicabili delle sezioni 20-21;
  eseguire suite e lint, verificare esempi e notebook, aggiornare roadmap e
  dichiarare completate le milestone solo con evidenze sufficienti.
- Restano esplicitamente fuori M08 e gli adapter condizionali. Una verifica
  incompleta o un ambiente indisponibile non e` un criterio superato.