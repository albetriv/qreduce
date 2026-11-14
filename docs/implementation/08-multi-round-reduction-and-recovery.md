# M08 - Riduzione multi-round e recovery

## Stato

**Completata.** La verifica del 2026-11-12 conferma orchestrazione iterativa, domini monotoni, recovery esplicito dal medesimo round, manifest cumulativo, post-check sul problema originale e persistenza degli artifact per round.

## Scopo e confini

M08 estende la riduzione single-pass iterando sul problema residuo. Un round successivo puo` ricevere solo il dominio effettivo del round precedente: item gia` esclusi e fissati non possono rientrare. Il recovery ricostruisce dal problema di inizio del round corrente prima che il fixing sia reso terminale; non esegue rollback cross-round.

M08 non modifica la formulazione MWIS, il contratto dei backend o le regole single-pass interne. M09 espone i modi 0, 1 e piu` round attraverso un entry point unificato.

## Riferimenti normativi

- Sezioni 9, 13, 15, 18, 20.6 e 21.9-21.10 di `../specifications.md`.
- `00-implementation-overview.md`.

## Dipendenze

- M02: configurazione di recovery, stati, reason e budget.
- M05: esecuzione di un round, candidate domain e fixing manifest.
- M06: solve residuo e post-check di ciascun percorso tentato.
- M07: persistenza separata di round e recovery attempt.

## Implementazione ed evidenze

`src/qreduce/pipeline/multi_round.py` orchestra i round tramite il componente
interno `_execute_reduction_round_with_counts`. La configurazione ammette
`max_reduction_rounds >= 0`; per i round positivi applica i criteri di stop:
successo, numero massimo di round, ratio marginale insufficiente,
`target_binary_variables`, budget end-to-end, assenza di candidate valide o
candidate domain troppo piccolo.

`src/qreduce/pipeline/recovery.py` espande deterministamente il dominio con `expand_ranked_domain` e completa il ranking con `rank_recovery_items`. Quando le policy `retry_with_larger_domain` sono abilitate per dominio troppo piccolo o infeasibility, ogni tentativo registra trigger, dimensioni e outcome in `RecoveryAttempt`.

Dopo una restriction di recovery, i conteggi logici residui sono ricalcolati sul
nuovo problema. Il post-check cumulativo deve restituire un
`FinalSolutionValidationResult`; eccezioni o tipi non validi sono normalizzati
come `adapter_failure`. Dopo il post-check, anche in recovery, la valutazione
delle metriche di dominio usa lo stesso controllo del percorso ordinario.
I conteggi originali del run provengono dal primo round, non dall'ultimo.
Il solve di recovery usa la stessa validazione del risultato del backend e la
stessa normalizzazione del percorso di export del solve ordinario. Le metriche
relative al dominio e al solve descrivono il tentativo finale; le evidenze MIS
restano associate al round anche quando viene tentata una recovery.

`src/qreduce/pipeline/rounds.py` valida manifest di round, monotonicita` della sequenza e costruisce `cumulative_fixing_manifest`. Il post-check finale usa il problema originale e il manifest cumulativo, non soltanto l'ultimo manifest di round.

## Test e verifica

- `tests/pipeline/test_multi_round.py` copre stop, massimo numero di round, monotonicita`, item non reintrodotti, propagazione di `round_index`, manifest cumulativo e recovery.
- I test verificano che un recovery su infeasibility espanda realmente il dominio e che gli errori nella composizione del manifest siano espliciti.
- `tests/test_config.py` verifica i parametri e le combinazioni non valide delle policy di recovery.
- `tests/experiments/test_runner.py` verifica la persistenza di artifact multi-round e dei recovery attempt.

## Criteri di completamento

- Ogni nuovo dominio e` un sottoinsieme del dominio del round precedente.
- Item esclusi in un round non possono essere riattivati in un round successivo.
- Ogni recovery ricostruisce dal problema di inizio del medesimo round e registra il proprio outcome.
- Il manifest cumulativo non contiene conflitti e conserva la provenance.
- Il post-check finale considera problema originale e fixing cumulativi.

## Esclusioni e lavoro successivo

Non e` previsto rollback cross-round ne` il reinserimento di item gia` fissati. Politiche di recovery ulteriori o criteri di complessita` piu` sofisticati devono essere introdotti esplicitamente con test, metadata e failure osservabili.

## Riferimenti correlati

- [M05 - Riduzione single-pass](05-single-pass-reduction-candidate-domain-and-fixing.md)
- [M06 - Solve residuo e post-check](06-residual-solving-post-check-and-portfolio-experiment.md)
- [M07 - Runner e artifact](07-experiment-runner-artifacts-and-analysis-notebooks.md)
- [M09 - Pipeline unificata e baseline](09-unified-pipeline-and-classical-baseline.md)