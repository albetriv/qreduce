# Audit metriche single-pass - specifiche 16.2

## Ambito e metodo

Audit statico del 2026-11-12 sui requisiti della sezione 16.2 di
`docs/specifications.md`: risultato in memoria, percorso single-pass, contratti
adapter/backend, persistenza e test. Gli stati `Parziale` e `Assente` indicano
lacune o evidenze insufficienti, non una certificazione di non conformita` per
ogni possibile backend esterno. Le metriche non disponibili per uno stage non
raggiunto non devono essere confuse con valori zero.

Il risultato e` serializzato interamente in `run_result.json` dal runner; dati
in campi diversi da `metrics` restano comunque disponibili ai consumer. I test
citati sono evidenze puntuali, non necessariamente test esaustivi del requisito.

Aggiornamento successivo: i conteggi logici obbligatori originali e residui
sono implementati da `LogicalVariableCounts` e dall'adapter portfolio. Le prime
tre righe sottostanti descrivono i gap individuati al momento dell'audit,
ora coperti dal contratto e dai test; il resto della matrice resta da verificare.
Anche il contratto delle metriche di dominio e` ora implementato per il
single-pass: la relativa riga descrive il gap storico, non lo stato corrente.
Le eccezioni e i risultati invalidi del post-check sono ora normalizzati come
`adapter_failure`, preservando il risultato classico e i dati precedenti.
Ratio single-pass, conteggi pre/post cap e repair, timer end-to-end e
`policy_hash` fornito sono ora esposti; le righe storiche corrispondenti non
attestano lo stato corrente. Restano da verificare tutti i rami di failure.

## Matrice requisito -> evidenza -> gap

| Requisito 16.2 | Evidenza nel codice e nei test | Stato e intervento |
|---|---|---|
| Binarie originali | Il grafo fornisce item/nodi; `ReducibleProblemAdapter` non espone un conteggio delle variabili binarie originali. | Assente come contratto generale: definire una sorgente adapter; non equiparare nodi a variabili senza garanzia di mapping. |
| Binarie residue | `ClassicalSolveResult.variable_count` e` un totale del modello solver; il manifest elenca item trattenuti/esclusi. | Assente il conteggio distinto di binarie residue del problema; non dedurlo dal numero di item. |
| Continue/intere residue | `variable_count` e` totale; SCIP e CPLEX lo leggono dal modello tradotto. SCIP puo` introdurre una variabile ausiliaria di epigrafo. | Assente la distinzione per tipo nel contratto comune. Specificare se si contano variabili del modello logico o anche ausiliarie del backend. |
| Ratio per round e cumulativa | La sezione 9.3 definisce la ratio marginale sugli item del grafo e sul dominio effettivo. `single_pass.py` non la espone; `test_pipeline_enforces_adapter_minimum_before_building_a_manifest` copre il dominio minimo, non la ratio. | Assente. Per un solo round verificare come rappresentare la cumulativa e definire il caso di grafo vuoto senza divisione per zero; il multi-round resta M08. |
| Tempo MIS, compilation ed execution | `_run_metrics` espone `mis_runtime_seconds` e tempi distinti quando riceve i rispettivi risultati; i contratti MIS conservano `runtime_seconds`. | Parziale: verificare i rami di failure e le fasi non raggiunte; non attribuire a una fase tempi non misurati. |
| Provider, famiglia, modalita`, device | `_run_metrics` usa gli ID e i metadati effettivi di `MISBackendResult`; risultati MIS sono serializzati. `tests/solving/mwis/test_contracts.py` verifica i contratti. | Parziale: coperti dopo risultato execution, non necessariamente prima o in ogni failure; distinguere richiesto da effettivo. |
| Tempo classico | `classical_result.runtime_seconds` e `metrics.classical_runtime_seconds`, quando il backend restituisce un risultato. | Parziale: coprire con test successo, indisponibilita` e failure successive alla costruzione del modello. |
| Tempo end-to-end | `_run_metrics` misura dall'avvio successivo alla validazione; diversi ritorni iniziali da `_failed` non forniscono `metrics`. | Parziale: non copre validazione e tutti i rami; definire e testare il perimetro del timer, inclusi i fallimenti iniziali. |
| Sample raw e uniche | `_run_metrics` espone `raw_sample_count` e `unique_sample_count`; `tests/experiments/test_portfolio_single_pass.py` verifica il primo. | Parziale: `unique_sample_count` deriva da `deduplicated.samples` dopo il limite configurato; verificare se serva anche il numero distinto prima del cap e testare scarti e failure. |
| Candidate valide e riparate | `valid_candidate_count` conta `valid_samples`, anche dopo eventuale repair. `CandidateRecord.repair_status` registra gli esiti; `tests/pipeline/test_single_pass_selection.py` verifica record riparati. | Parziale: manca un conteggio esplicito delle riparate; precisare popolazione e rapporto con le candidate valide, incluse candidate duplicate o scartate. |
| Dimensione candidate domain | `metrics.candidate_domain_size` usa `retained_item_ids`; `tests/experiments/test_portfolio_single_pass.py` verifica il valore. | Parziale: verificare disponibilita` nei failure dopo costruzione e che uno stage precedente non produca uno zero ingannevole. |
| Fattibilita` solve residuo | `classical_solver_claimed_feasible` e `classical_result.solver_claimed_feasible`; status classico separato in `RunResult`. | Parziale: aggiungere test di persistenza per soluzione fattibile, infeasible e backend indisponibile; non interpretare `not_run` come infeasible. |
| Fattibilita` post-check | `postcheck_feasible` e `postcheck_result`; `RunResult.postcheck_status` distingue `not_run`. Test di dominio in `tests/experiments/portfolio_domain/test_postcheck.py`. | Parziale: verificare serializzazione per successo e failure, mantenendo distinta l'assenza di post-check. |
| Obiettivo | `classical_result.objective_value` e `metrics.objective_value`; `postcheck_result.objective_recomputed` puo` contenere il valore dell'adapter. | Parziale: l'obiettivo ricalcolato non confluisce automaticamente nella metrica comune se quello del solver manca; definire precedenza e provenienza. |
| Bound e gap | `classical_result.best_bound` e `gap`, riportati in `metrics` quando esiste il risultato. | Parziale: testare persistenza dei valori disponibili e `None` senza attribuire bound del residuo all'originale. |
| Seed e metadati stocastici | Seed richiesti in `resolved_config`; `MISBackendResult.effective_execution_parameters` e risultati classici conservano parametri effettivi. | Parziale: verificare per backend e failure quali parametri effettivi siano realmente registrati, senza assumere che il seed richiesto sia stato usato. |
| Metriche di valutazione del dominio | Il protocollo adapter e la configurazione non definiscono una collezione di metriche con identificatore, unita`, convenzione di confronto e provenance. | Assente: progettare un contratto provider-agnostic per dati forniti da adapter/chiamante, con redazione e serializzazione; non scegliere policy di business nel kernel. |
| Run status e terminal reason | `RunResult.run_status` e `terminal_reason` sono serializzati anche in `_failed`; `tests/experiments/test_runner.py` controlla un risultato fallito persistito. | Presente nel risultato, non necessariamente nel dizionario `metrics`; estendere i test per esiti terminali pertinenti. |

## Disponibilita` nei risultati parziali

La pipeline produce metriche progressivamente: i fallimenti di validazione,
lookup solver o grafo possono avere `metrics` vuoto; failure di compilation
e successive preservano solo i dati passati esplicitamente a `_failed`.
La presenza nel risultato di compilation, execution, candidate e solve dipende
dallo stage raggiunto. La serializzazione del runner non ricostruisce metriche
mancanti. Un audit esaustivo dei rami deve verificare anche che dati gia`
disponibili non vengano persi durante la failure.

## Priorita` e confini

1. **M02/M05:** mantenere verificati conteggi logici e contratto delle metriche
   di dominio implementati, distinti dalle ausiliarie dei backend.
2. **M05:** definire le metriche del singolo round, inclusi ratio, conteggi
   repair e tempi/failure, poi aggiungere test deterministici per stage raggiunti
   e non raggiunti. La formula marginale e` gia` nella sezione 9.3; non
   assumere che la ratio dei nodi misuri automaticamente le variabili binarie.
3. **M07:** verificare round-trip e integrita` degli stessi dati in
   `run_result.json`, inclusi esiti negativi. Non inventare campi persistiti dal
   solo runner che non rappresentino dati disponibili nel risultato.
4. **M08:** estendere per round e tentativo, cumulative e recovery, una volta
   definite le relative semantiche; non simulare iterazione nel single-pass.

Le scelte osservabili ancora non definite dalle specifiche devono essere
chiarite prima dell'implementazione. Questo audit non cambia API o comportamento.