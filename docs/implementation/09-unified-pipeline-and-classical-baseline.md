# M09 - Pipeline unificata e baseline classical-only

## Stato

**Completata.** La verifica del 2026-11-14 conferma `run_pipeline` come entry point raccomandato, `PipelineRunResult` come risultato unificato e una baseline classical-only che evita completamente grafo e backend MIS.

## Scopo e confini

M09 unifica le modalita` operative controllate da `config.reduction.max_reduction_rounds`:

```text
0  = baseline classical-only
1  = una riduzione single-pass
>1 = riduzione multi-round con recovery configurabile
```

La milestone preserva compatibilita` transitoria delle funzioni legacy, ma non altera le responsabilita` di M05, M06 e M08. La baseline e` un confronto operativo senza riduzione, non una garanzia di ottimalita` o una sostituzione del protocollo di benchmark dell'applicazione.

## Riferimenti normativi

- Sezioni 7, 9, 13, 14, 15, 17, 18, 20.6 e 21 di `../specifications.md`.
- `00-implementation-overview.md`.

## Dipendenze

- M02: validazione della configurazione e tipi di risultato.
- M05: percorso a un round.
- M06: solve classico e post-check.
- M07: artifact uniformi per riduzione e baseline.
- M08: percorso a piu` round e recovery.

## Implementazione ed evidenze

`src/qreduce/pipeline/unified.py` espone `run_pipeline`, che delega al percorso coerente con `max_reduction_rounds` e restituisce `PipelineRunResult`. Il risultato unifica `round_results`, recovery attempt, manifest cumulativo, conteggi, risultato classico, post-check, metriche e proprieta` `is_classical_only`, `has_reduction` e `reduction_round_count`.

Con valore zero, il percorso classical-only non costruisce il grafo, non invoca il solver MIS, mantiene tutti gli item e risolve il problema completo. Il manifest ha origine `no_reduction`, `round_results` e` vuoto e il runner non pubblica file `round_XX_result.json`.

`run_single_pass` e `run_multi_round` restano disponibili per compatibilita`, ma emettono `DeprecationWarning`; il codice nuovo deve usare `run_pipeline`. I tipi legacy rimangono disponibili dove necessari alla rappresentazione interna, mentre `PipelineRunResult` e` il tipo pubblico raccomandato.

## Test e verifica

- `tests/pipeline/test_classical_only_baseline.py` verifica assenza di grafo e MIS, manifest `no_reduction`, conservazione degli item, conteggi e solve del problema completo.
- La suite include integrazione SCIP, failure del solver e problema infeasible nel modo classical-only.
- `tests/experiments/test_runner.py` verifica il round-trip degli artifact della baseline.
- `tests/pipeline/test_multi_round.py` e i test single-pass verificano i modi positivi instradati dalla pipeline unificata.

## Criteri di completamento

- Un solo entry point seleziona in modo esplicito baseline, single-pass o multi-round dalla configurazione risolta.
- Il modo zero non esegue alcuna riduzione MWIS.
- Risultati e artifact distinguono chiaramente baseline e run con riduzione.
- Le API legacy avvisano della deprecazione senza cambiare silenziosamente il contratto osservabile.
- `PipelineRunResult` conserva le evidenze necessarie per audit di tutti i modi.

## Esclusioni e lavoro successivo

La baseline non definisce metriche di benchmark, soglie di accettazione o una policy di confronto full-versus-reduced: tali decisioni rimangono di competenza dell'applicazione o di un adapter di dominio. Una futura API pubblica o CLI non deve modificare i confini contrattuali senza aggiornamento delle specifiche.

## Riferimenti correlati

- [M02 - Contratti core](02-core-contracts-configuration-status-and-provenance.md)
- [M05 - Riduzione single-pass](05-single-pass-reduction-candidate-domain-and-fixing.md)
- [M06 - Solve residuo e post-check](06-residual-solving-post-check-and-portfolio-experiment.md)
- [M07 - Runner e artifact](07-experiment-runner-artifacts-and-analysis-notebooks.md)
- [M08 - Riduzione multi-round e recovery](08-multi-round-reduction-and-recovery.md)