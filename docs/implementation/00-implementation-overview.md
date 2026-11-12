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
| M02 | Contratti core, configurazione, stati e provenance | Parziale | Configurazione immutabile, capability, stati/failure, metadata e serializzazione | `config.py`, `models.py`, `status.py`, `capabilities.py`, `artifacts/metadata.py`, `domains/` e relativi test; `ProtectionDeclaration` e audit serializzabile delle candidate/protezioni per il single-pass | Coprire tutti i campi e le invarianti richiesti dalle sezioni 16-19 delle specifiche, con evidenze di serializzazione e provenance. |
| M03 | Grafo MWIS, QUBO, Ising ed exact diagnostics | Completata | Grafo canonico, QUBO MWIS, energia, conversione Ising, solver exact sotto soglia | `mwis/` e `tests/mwis/`; audit M03 del 2026-11-11 | Mantenere test di equivalenza, validazione, tutti i minimizzatori QUBO e soglia exact in caso di evoluzione del modello. |
| M04 | Esecuzione MWIS, cataloghi e backend locali | Completata | Capability, compile/solve, normalizzazione, `local_greedy`, `dwave_simulated_annealing`, registry esplicite | `solving/mwis/`, `capabilities.py` e `tests/solving/mwis/`; audit M04 del 2026-11-11 | Mantenere validazione pre-compilation, clamping dei timeout, decoding rigoroso e failure esplicite per dipendenze o capability indisponibili. |
| M05 | Pipeline single-pass, candidate domain e fixing | Parziale | Orchestrazione end-to-end, ranking/diversita`, repair, fixing manifest, budget e failure parziali | `pipeline/single_pass.py`, `domains/`, test pipeline e integrazione; `CandidateRecord`, audit per item e `ProtectionDeclaration` registrano repair, scarti, cap e categorie/protezione `best_effort`; il kernel verifica minimo, cap e coerenza del fixing manifest | Verificare tutte le metriche e invarianti delle sezioni 7, 8, 12 e 20, completare gli eventuali dati di policy/configurazione ancora non rappresentati e mappare requisito-per-requisito le evidenze del single-pass. |
| M06 | Solve residuo, post-check ed esperimento portfolio | Parziale | Modello classico generico, backend `cplex` e `scip`, post-check, adapter portfolio dimostrativo | `solving/residual/`, `experiments/portfolio_domain/` e test associati; export esplicito e verificato con SCIP nel runner | Verificare gli esiti opzionali dei solver e l'export CPLEX nel rispettivo ambiente, senza introdurre side effect impliciti nel kernel. |
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

## Documenti di milestone ed evidenze

| Area | Documento o posizione | Ruolo |
|---|---|---|
| M01 | `01-project-setup-and-python-compatibility.md` | Packaging, runtime e dipendenze opzionali. |
| M02 | `02-core-domain-models-and-configuration.md` | Contratti dati, stati, configurazione e metadata. |
| M03 | `03-canonical-mwis-graph-and-qubo.md` | Rappresentazione MWIS canonica ed exact diagnostics. |
| M04 | `04-mwis-execution-backends-and-adapter-contracts.md` | Contratti e backend per l'esecuzione MWIS. |
| M05-M06 | `05-synthetic-portfolio-experiment.md` | Esperimento portfolio, backend classici e post-check; la pipeline single-pass e` inoltre in `src/qreduce/pipeline/single_pass.py`. |
| M07 | `src/qreduce/experiments/` | Runner, artifact, loader e notebook; richiede un documento di milestone dedicato prima della dichiarazione di completamento. |
| M08 | Da creare | Design multi-round/recovery, compatibile con sezioni 9 e 20.6 delle specifiche. |

## Decisioni tecniche correnti e aperte

| Tema | Decisione o stato corrente |
|---|---|
| Runtime supportato | Python 3.12. |
| Kernel | Indipendente da provider, SDK e oggetti runtime proprietari. |
| Solver standard | Cataloghi built-in; registry del chiamante solo per estensioni esplicite. |
| Adapter di dominio | Fornito dall'applicazione oppure confinato in un esperimento interno. |
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