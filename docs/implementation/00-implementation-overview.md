# QReduce - Implementation overview

## Scopo e autorita` documentale

Questo documento e` la roadmap tecnica verso il completamento delle feature
previste in `docs/specifications.md`. Le specifiche sono la fonte normativa per
requisiti funzionali, garanzie, confini di responsabilita`, stati, failure reason
e criteri di accettazione; questa roadmap stabilisce invece ordine, dipendenze,
stato ed evidenze delle milestone necessarie a soddisfarli.

Una milestone non puo` introdurre un nuovo requisito funzionale o modificare una
garanzia stabilita dalle specifiche. Se una scelta tecnica richiede un cambio di
requisito, deve essere prima approvato e documentato in
`docs/specifications.md`, poi riflesso in questa roadmap e nei documenti di
milestone interessati.

Il README e` una guida sintetica per utenti e contributori: rimanda a questi due
documenti, riporta solo uno stato generale della roadmap e non ne duplica le
milestone.

## Regole di stato

| Stato | Significato |
|---|---|
| Completata | Codice, test e documentazione disponibili; i criteri della milestone sono stati verificati nel repository. |
| Parziale | Parte del percorso e` implementata, ma restano requisiti, evidenze o allineamenti documentali da completare. |
| Da verificare | Codice e test pertinenti sono presenti, ma non e` stata ancora completata la verifica requisito-per-requisito contro le specifiche. |
| Da implementare | La milestone e` richiesta dalle specifiche ma non possiede ancora un percorso implementato verificabile. |
| Condizionale | Capacita` opzionale prevista dalle specifiche; non blocca il completamento del nucleo finche` non viene resa obbligatoria da una decisione esplicita. |

Lo stato qui riportato e` una fotografia del repository alla revisione della
roadmap. Una milestone passa a `Completata` soltanto dopo la verifica dei propri
criteri di completamento, compresi i test proporzionati.

## Architettura di riferimento

```text
application problem
  -> application domain adapter builds ReductionGraph
  -> canonical MWIS/QUBO/Ising representation
  -> selected built-in or explicitly registered MIS backend
  -> normalization, validation, repair and candidate-domain construction
  -> explicit fixing manifest and restricted problem
  -> selected built-in or explicitly registered residual classical backend
  -> adapter post-check
  -> complete in-memory run result

repository experiment runner
  -> persists complete artifacts under outputs/{experiment_id}/{run_id}/
  -> notebooks load artifacts without rerunning the pipeline
```

Il risultato MWIS restringe il dominio delle decisioni binarie; non e` la
soluzione finale e non trasferisce l'ottimalita` del problema residuo al problema
originale dopo fixing euristico.

## Roadmap delle feature obbligatorie

| ID | Milestone | Stato | Requisiti principali | Evidenze correnti | Uscita richiesta per il completamento |
|---|---|---|---|---|---|
| M01 | Fondazioni di progetto e compatibilita` | Completata | Python 3.12, packaging provider-agnostic, dipendenze lazy, convenzioni di sviluppo | `pyproject.toml`, `poetry.lock`, test di indipendenza runtime e verifica locale del 2026-11-12 | Mantenere coerenti README e packaging ed eseguire localmente test e lint; la CI automatica non e` richiesta. |
| M02 | Contratti core, configurazione, stati e provenance | Completata | Configurazione immutabile, capability, stati/failure, metadata e serializzazione | `config.py`, `models.py`, `status.py`, `capabilities.py`, `artifacts/metadata.py`, `domains/` e relativi test; protezioni, audit candidate, conteggi logici e metriche di dominio; verifica del 2026-11-12 | Mantenere coerenti i contratti e le invarianti; le policy di recovery restano bloccate a M08. |
| M03 | Grafo MWIS, QUBO, Ising ed exact diagnostics | Completata | Grafo canonico, QUBO MWIS, energia, conversione Ising, solver exact sotto soglia | `mwis/` e `tests/mwis/`; audit M03 del 2026-11-11 | Mantenere test di equivalenza, validazione, tutti i minimizzatori QUBO e soglia exact in caso di evoluzione del modello. |
| M04 | Esecuzione MWIS, cataloghi e backend locali | Completata | Capability, compile/solve, normalizzazione, `local_greedy`, `dwave_simulated_annealing`, registry esplicite | `solving/mwis/`, `capabilities.py` e `tests/solving/mwis/`; audit M04 del 2026-11-11 | Mantenere validazione pre-compilation, clamping dei timeout, decoding rigoroso e failure esplicite per dipendenze o capability indisponibili. |
| M05 | Pipeline single-pass, candidate domain e fixing | Completata | Orchestrazione end-to-end, ranking/diversita`, repair, fixing manifest, budget e failure parziali | `pipeline/single_pass.py`, `domains/`, test pipeline e integrazione; audit 06 del 2026-11-12 | Mantenere coerenti metriche e contratti; M08 per multi-round. |
| M06 | Solve residuo, post-check ed esperimento portfolio | Parziale | Modello classico generico, backend `cplex` e `scip`, post-check, adapter portfolio dimostrativo | `solving/residual/`, test associati; integrazioni SCIP, CPLEX ed export CPLEX eseguite localmente il 2026-11-12 | Completare la matrice degli esiti e le invarianti del post-check, senza introdurre side effect impliciti nel kernel. |
| M07 | Runner, artifact e notebook di analisi | Parziale | Persistenza atomica degli esperimenti, manifest, loader e notebook che leggono artifact | `experiments/runner.py`, `experiments/artifacts.py`, notebook e test runner | Verificare la copertura completa di provenance, hash e dati per-round/candidate richiesta dalle sezioni 16-17. |
| M08 | Riduzione multi-round e recovery | Da implementare | Domini monotoni, criteri di stop, recovery dal medesimo round, artifact per round | La configurazione modella `max_reduction_rounds`, ma `config.py` accetta oggi solo `1` | Definire un documento di milestone dedicato, implementare il runner multi-round e aggiungere i test della sezione 20.6. |

Le milestone M01-M07 descrivono il nucleo obbligatorio previsto dalle
specifiche. M08 e` anch'essa obbligatoria per dichiarare completo il progetto,
ma non blocca la disponibilita` del percorso single-pass gia` implementato in
modo parziale.

## Capacita` opzionali previste

Le specifiche prevedono contratti in grado di supportare adapter MIS remoti,
gate-based o neutral-atom, ma non impongono un provider specifico. Queste
capacita` restano `Condizionali`: entrano in una milestone esecutiva solo quando
viene scelta esplicitamente una famiglia di backend, un adapter e un ambiente di
verifica.

| ID | Capacita` | Stato | Condizione per pianificarla |
|---|---|---|---|
| O01 | Adapter annealing remoto, Leap Hybrid o QPU | Condizionale | Provider, credenziali, gestione di embedding e ambiente di test dichiarati. |
| O02 | Adapter gate-based | Condizionale | Scelta di SDK, compilazione/decoding, gestione shots e transpilation dichiarati. |
| O03 | Adapter neutral-atom | Condizionale | Scelta di SDK o servizio, mapping geometrico e criteri di audit dichiarati. |

Le idee raccolte nella sezione 22 delle specifiche non appartengono a questa
tabella: non sono requisiti e non ricevono una milestone fino a promozione
esplicita nelle specifiche.

## Nice to have: benchmark suite pubblica esterna

La sezione 22.1 delle specifiche registra una proposta non vincolante di suite
esterna per il benchmark del core MWIS e della riduzione end-to-end. Non e` una
milestone e non modifica il perimetro del kernel: dataset, parser, adapter,
policy di grafo, metriche di qualita` e soglie restano responsabilita` del
workflow esterno.

| ID | Iniziativa | Stato | Condizione per pianificarla |
|---|---|---|---|
| N01 | Benchmark MWIS DIMACS-like | Nice to have | Scegliere una collezione, una licenza, parser e protocollo per confrontare backend MIS senza trattarla come benchmark end-to-end. |
| N02 | Adapter OR-Library set packing | Nice to have | Definire formato di input, mapping item/colonne, conflitti at-most-one, solve residuo e confronto con il modello completo. |
| N03 | Adapter OR-Library facility location e set covering | Nice to have | Dichiarare score, conflitti, precheck di capacita` o copertura, fixing delle variabili collegate e post-check. |
| N04 | Adapter QPLIB filtrata a MIQP lineare nei vincoli | Nice to have | Definire parser e filtri per binarie/mixed-binary, obiettivo quadratico e soli vincoli lineari; escludere MIQCP fino a estensione del contratto residuale. |
| N05 | Adapter MIPLIB 2017 per famiglie strutturali | Nice to have | Selezionare una famiglia con semantica esplicita, parser MPS/LP, criteri di inclusione e policy di grafo; non inferire conflitti dalla sola co-occorrenza nei vincoli. |

Prima di promuovere una di queste iniziative a milestone, creare un documento
dedicato con dataset e licenza, filtro/versione delle istanze, adapter,
protocollo full-versus-reduced, metriche, limiti di tempo, solver di riferimento
e gestione riproducibile di infeasibility, failure e post-check failed.

## Documenti di milestone ed evidenze

| Area | Documento o posizione | Ruolo |
|---|---|---|
| M01 | `01-project-setup-and-python-compatibility.md` | Packaging, runtime e dipendenze opzionali. |
| M02 | `02-core-domain-models-and-configuration.md` | Contratti dati, stati, configurazione e metadata. |
| M03 | `03-canonical-mwis-graph-and-qubo.md` | Rappresentazione MWIS canonica ed exact diagnostics. |
| M04 | `04-mwis-execution-backends-and-adapter-contracts.md` | Contratti e backend per l'esecuzione MWIS. |
| M05-M06 | `05-synthetic-portfolio-experiment.md` | Esperimento portfolio, backend classici e post-check; la pipeline single-pass e` inoltre in `src/qreduce/pipeline/single_pass.py`. |
| M02, M05, M07 | `06-single-pass-metrics-audit.md` | Matrice di evidenze e gap delle metriche della sezione 16.2. |
| M01-M07 | `07-single-pass-conformance-backlog.md` | Mappa di conformita` single-pass e backlog di chiusura, esclusa M08. |
| M07 | `08-experiment-artifacts.md` | Runner, artifact, loader, notebook ed evidenze ancora necessarie. |
| M08 | Da creare | Design multi-round/recovery, compatibile con sezioni 9 e 20.6 delle specifiche. |

## Decisioni tecniche correnti e aperte

| Tema | Decisione o stato corrente |
|---|---|
| Runtime supportato | Python 3.12. |
| Kernel | Indipendente da provider, SDK e oggetti runtime proprietari. |
| Solver standard | Cataloghi built-in; registry del chiamante solo per estensioni esplicite. |
| Adapter di dominio | Fornito dall'applicazione oppure confinato in un esperimento interno. |
| Forme residuali correnti | Il `ClassicalOptimizationModel` rappresenta MILP e MIQP con vincoli lineari; MIQCP richiede un'estensione esplicita o una riformulazione. |
| Percorso attualmente eseguibile | Single-pass. Multi-round e recovery appartengono a M08. |
| Esperimenti repository | `qreduce.experiments` e` escluso dal wheel e pubblica artifact. |
| API pubblica finale e CLI | Decisione aperta; non deve alterare i confini contrattuali delle specifiche. |
| Formati aggiuntivi e provider remoti | Condizionali: richiedono una scelta esplicita di adapter e ambiente. |

## Regole di completamento delle milestone

Una milestone puo` iniziare quando possiede confini di responsabilita`, input,
output, failure osservabili, dipendenze dichiarate e un piano di test minimo.
Puo` essere dichiarata completata soltanto quando:

1. requisiti e criteri di accettazione rilevanti sono mappati alle evidenze;
2. implementazione Python e test permanenti sono coerenti;
3. README, esempi e notebook impattati sono aggiornati o verificati coerenti;
4. notebook ed esempi usano la logica dei moduli Python senza duplicare business
   logic;
5. le decisioni rimaste fuori dalla milestone sono esplicitamente riportate
   come dipendenze di una milestone successiva o come capacita` condizionali.

## Fonti di verita`

| Contenuto | Posizione | Regola |
|---|---|---|
| Feature previste, requisiti e non-obiettivi | `docs/specifications.md` | Normativo. |
| Sequenza, stato ed evidenze di implementazione | `docs/implementation/` | Roadmap tracciabile. |
| Logica riutilizzabile | `src/qreduce/` | Nessuna business logic nei notebook. |
| Test permanenti | `tests/` | Ogni modifica osservabile richiede test proporzionati. |
| Risultato di run | Oggetto Python serializzabile | Restituito in memoria dalla pipeline, senza side effect sul filesystem. |
| Esperimenti interni | `src/qreduce/experiments/` | Runner interno escluso dal wheel, con artifact in `outputs/{experiment_id}/{run_id}/`. |
| Notebook experiments | `notebooks/experiments/` | Leggono artifact dal filesystem e non invocano la pipeline. |
| File temporanei dell'agente | `.cline-tmp/` | Mai importati dal codice applicativo. |