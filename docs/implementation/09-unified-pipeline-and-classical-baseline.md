# M09 - Pipeline unificata e baseline classical-only

## Stato

**Completata.** La pulizia conferma `run_pipeline`
come unico entry point di esecuzione, `PipelineRunResult` come unico risultato
di un run completo e una baseline classical-only che evita completamente grafo
e backend MIS.

## Scopo e confini

M09 unifica le modalita` operative controllate da `config.reduction.max_reduction_rounds`:

```text
0  = baseline classical-only
1  = una riduzione single-pass
>1 = riduzione multi-round con recovery configurabile
```

La milestone non espone wrapper, alias o percorsi alternativi per le modalita`
single-pass e multi-round: entrambe sono configurazioni della stessa pipeline.
La baseline e` un confronto operativo senza riduzione, non una garanzia di
ottimalita` o una sostituzione del protocollo di benchmark dell'applicazione.

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

La baseline usa la stessa validazione del risultato del backend e la stessa
normalizzazione del percorso di export dei round. Il post-check deve restituire
un `FinalSolutionValidationResult`; le metriche di dominio sono validate anche
dopo un post-check negativo. Un errore nelle metriche produce `adapter_failure`
senza scartare il risultato classico o il post-check e impedisce l'adozione.

`run_pipeline` e` l'unico entry point pubblico di esecuzione. Il componente
interno del round produce `RoundExecutionResult`, convertito dall'orchestratore
in `ReductionRoundResult`; `PipelineRunResult` espone i dati finali con
`final_retained_item_ids` e `cumulative_fixing_manifest` e le evidenze per
round nella sequenza `round_results`. Non esistono accessor che selezionino
implicitamente il primo round.

`is_classical_only` indica la modalita` richiesta: e` vero solo per il valore
intero zero, anche quando un'altra parte della configurazione non e` valida.
`has_reduction` indica invece se almeno un round e` stato eseguito. La durata
di ogni round comprende i suoi tentativi di recovery; il budget end-to-end usa
il cronometro globale. La dichiarazione delle protezioni e` conservata nel
risultato del round quando disponibile.

## Test e verifica

- `tests/pipeline/test_classical_only_baseline.py` verifica assenza di grafo e MIS, manifest `no_reduction`, conservazione degli item, conteggi e solve del problema completo.
- La suite include integrazione SCIP, failure del solver e problema infeasible nel modo classical-only.
- `tests/experiments/test_runner.py` verifica il round-trip degli artifact della baseline.
- `tests/pipeline/test_multi_round.py` e i test single-pass verificano i modi positivi instradati dalla pipeline unificata.
- La verifica finale ha eseguito la suite completa: 354 test passati.
- L'hash dell'input e la validazione dei conteggi logici sono condivisi; il tipo
  `RecoveryAttempt` risiede nel modulo di recovery, senza ciclo di import tra
  orchestratore e risultato unificato. Il componente di round mantiene una
  validazione difensiva quando viene invocato direttamente nei test interni.

## Criteri di completamento

- Un solo entry point pubblico seleziona in modo esplicito baseline, un round o piu` round dalla configurazione risolta.
- Il modo zero non esegue alcuna riduzione MWIS.
- Risultati e artifact distinguono chiaramente baseline e run con riduzione.
- Non esistono API legacy, alias o conversioni di compatibilita` per percorsi di pipeline concorrenti.
- `PipelineRunResult` conserva le evidenze necessarie per audit di tutti i modi.

## Esclusioni e lavoro successivo

La baseline non definisce metriche di benchmark, soglie di accettazione o una
policy di confronto full-versus-reduced: tali decisioni rimangono di competenza
dell'applicazione o di un adapter di dominio. I percorsi di restriction e
post-check della recovery restano distinti per gestire il dominio espanso e il
manifest cumulativo, mentre validazione del solve, export e metriche di dominio
sono condivisi.

## Riferimenti correlati

- [M02 - Contratti core](02-core-contracts-configuration-status-and-provenance.md)
- [M05 - Riduzione single-pass](05-single-pass-reduction-candidate-domain-and-fixing.md)
- [M06 - Solve residuo e post-check](06-residual-solving-post-check-and-portfolio-experiment.md)
- [M07 - Runner e artifact](07-experiment-runner-artifacts-and-analysis-notebooks.md)
- [M08 - Riduzione multi-round e recovery](08-multi-round-reduction-and-recovery.md)