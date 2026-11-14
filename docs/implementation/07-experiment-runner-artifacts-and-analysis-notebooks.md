# M07 - Runner di esperimento, artifact e notebook di analisi

## Stato

**Completata.** Le evidenze nel repository coprono pubblicazione atomica,
manifest con provenance redatta, loader con verifica hash e notebook orientati
alla lettura degli artifact gia` prodotti. La suite completa e` stata rieseguita
nella revisione documentale del 2026-11-14.

## Scopo e confini

M07 rende analizzabili e riproducibili gli esperimenti interni del repository. Il runner persiste il risultato in memoria prodotto dalla pipeline, mentre i notebook caricano gli artifact dal filesystem e non invocano direttamente la pipeline. Gli artifact sono del repository e non costituiscono un'API di storage generica del kernel.

## Riferimenti normativi

- Sezioni 16.2, 16.3, 17, 20.8 e 21.12-21.13 di `../specifications.md`.
- `00-implementation-overview.md`.

## Dipendenze

**Prerequisiti:** M02 definisce identita`, metadata, hash, redazione e risultato
serializzabile; M05 e M06 producono candidate, fixing, solve, post-check e
metriche da persistere.

**Integrazioni a valle:** M08 aggiunge risultati per round e recovery attempt;
M09 aggiunge la baseline classical-only. Entrambi usano il medesimo formato di
artifact senza rendere M07 dipendente dai loro modi operativi.

## Implementazione ed evidenze

`src/qreduce/experiments/runner.py` esegue `run_pipeline` e pubblica gli artifact sotto `outputs/{run_id}/`. La pubblicazione e` atomica: una failure di serializzazione non rende disponibile una directory finale incompleta, mentre un esito normalizzato `failed` resta un risultato persistito e analizzabile.

Il manifest conserva configurazione, hash, policy provenance redatta, stato e metadati. Il loader `load_experiment_run` controlla gli hash dei file interni, incluso l'eventuale modello esportato internamente; un export esterno viene registrato ma non fa parte della stessa garanzia di verifica. Il runner rifiuta di sovrascrivere un run gia` pubblicato.

Gli artifact multi-round includono un risultato per ciascun round e gli eventuali recovery attempt. Per la baseline classical-only registrano zero round, nessun file `round_XX_result.json` e un manifest con origine `no_reduction`.

I notebook in `notebooks/experiments/` leggono artifact attraverso `qreduce.experiments.load_experiment_run`. I notebook didattici in `notebooks/tasks/` richiamano la logica presente nei moduli Python e non sono la fonte della business logic.

## Test e verifica

- `tests/experiments/test_runner.py` verifica pubblicazione atomica, hash, rifiuto di sovrascrittura, redazione, metriche e round-trip di esiti terminali.
- `test_loader_rejects_artifacts_changed_after_publication` verifica il rifiuto di artifact manomessi.
- `test_terminal_outcomes_round_trip_through_artifact_serialization` copre success, partial success, failure di post-check e failure classica.
- `tests/experiments/test_portfolio_multi_round.py` e il test della baseline classical-only verificano artifact dei modi aggiuntivi della pipeline.

## Criteri di completamento

- Ogni run pubblicato e` completo o non e` pubblicato.
- Manifest e risultati preservano provenance e redigono metadata sensibili.
- Il loader rifiuta modifiche ai file interni protetti da hash.
- Notebook ed esempi analizzano artifact o usano moduli Python, senza duplicare logica di pipeline.
- Gli esiti non riusciti ma serializzabili rimangono disponibili all'analisi.

## Esclusioni e lavoro successivo

Dataset esterni, benchmark pubblici e formati di export di terze parti richiedono un protocollo dedicato. L'hash di un export esterno non prova l'integrita` del suo contenuto dopo la pubblicazione.

## Riferimenti correlati

- [M02 - Contratti core](02-core-contracts-configuration-status-and-provenance.md)
- [M06 - Solve residuo e post-check](06-residual-solving-post-check-and-portfolio-experiment.md)
- [M08 - Riduzione multi-round e recovery](08-multi-round-reduction-and-recovery.md)
- [M09 - Pipeline unificata e baseline](09-unified-pipeline-and-classical-baseline.md)
- [README](../../README.md)