# Matrice di conformita` e backlog single-pass

## Scopo e limiti

Fotografia statica del 2026-11-12, comprensiva delle modifiche locali non ancora
committate. Questa matrice organizza i requisiti applicabili al single-pass:
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
| 8.4, 10, 13, 21.9-10 | Manifest, fixing e garanzie | Evidenza parziale: `src/qreduce/domains/contracts.py`, test pipeline e adapter portfolio | Verificare tassonomia origine/garanzia per fixing sicuri e user-imposed oltre al caso euristico; non inferire garanzie dal portfolio. |
| 13, 16.2 | Conteggi logici originali e residui | Evidenza: `LogicalVariableCounts`, `tests/domains/test_logical_variable_counts.py`, test single-pass e runner | Mantenere separati dai conteggi fisici del backend. |
| 13, 16.2 | Metriche di valutazione del dominio | Evidenza nelle modifiche locali: `DomainEvaluationMetric`, `evaluate_domain_metrics`, `tests/domains/test_evaluation_metrics.py`, `tests/experiments/test_runner.py` | Verificare anche percorso reale post-check e failure; non trattare i test con pipeline simulata come prova end-to-end. |
| 14, 15, 20.7, 21.8 | Backend classici, post-check e adozione | Evidenza parziale: `src/qreduce/solving/residual/`, `tests/solving/residual/`, test portfolio e integrazioni | Completare matrice esiti e verifiche runtime/export CPLEX; B04. |
| 7.16, 13, 15, 19 | Failure normalizzate e dati parziali | Gap circoscritto: la chiamata a `validate_final_solution` in `single_pass.py` non e` protetta da normalizzazione delle eccezioni | Riprodurre con test e gestire senza perdere solve/fixing; verificare gli altri confini adapter/backend. B02. |
| 16.2, 21.12-13 | Metriche single-pass e disponibilita` per stage | Gap: ratio del round e conteggio esplicito repair non esposti; altri casi parziali in `06-single-pass-metrics-audit.md` | Definire semantica, implementare e testare B01-B02. |
| 16.3, 18, 20.8 | Provenance policy in configurazione e manifest | Gap nel manifest: `PolicyProvenance` e` nella config, ma `_write_artifacts` non la inserisce nel manifest | Aggiungere e testare provenance e redazione senza confonderla con hash calcolati; B03. |
| 17, 21.12 | Identita`, hash, risultato e artifact riproducibili | Verifica: `RunResult` ha `input_hash` e `policy_hash` opzionali; il kernel non calcola l'hash dell'input opaco; runner calcola hash file | Confrontare obbligatorieta`, provenienza, redazione e disponibilita` con sezione 17; chiarire il contratto prima di cambiarlo. B03. |
| 17, 20.8 | Persistenza atomica, integrita`, loader e failure persistite | Evidenza parziale: `src/qreduce/experiments/runner.py`, `artifacts.py`, `tests/experiments/test_runner.py` | Verificare provenance, round-trip e manomissione nei vari esiti; creare milestone M07. B03. |
| 18-19 | Configurazione, stati, budget e reason | Evidenza parziale: `src/qreduce/config.py`, `status.py`, `tests/test_config.py` | Confrontare campi e transizioni applicabili e verificare timer e risultati parziali. B02. |
| 9, 20.6 | Round multipli, stop iterativi, recovery e rollback | Escluso: `config.py` accetta un solo round | M08; non reinterpretare come completato. |
| 11.5, 20.3 | Adapter remoti, gate-based e neutral-atom | Escluso finche` condizionale; nessun provider specifico imposto | Pianificare solo a seguito di scelta esplicita di backend e ambiente. |

## Backlog ordinato

### B01 - Metriche del round e candidate

- Definire popolazioni e disponibilita` dei conteggi prima/dopo cap, repair e
  filtri; distinguere metriche item da conteggi variabili logiche.
- Implementare ratio del round quando definita e conteggio repair; chiarire
  rapporto con ratio cumulativa nel single-pass e caso di grafo vuoto secondo
  le specifiche, senza simulare M08.
- Testare casi deterministici: protezioni/cap, duplicati, repair riuscito o
  fallito, valori assenti e serializzazione. Non inventare zero per stage non
  raggiunti. Allineare audit, specifiche e README se necessario.

### B02 - Failure, tempi e invarianti della pipeline

- Inventariare stage e dati disponibili, includendo exception e risultati
  invalidi di adapter e backend; testare il post-check che solleva eccezione.
- Definire inizio/fine del tempo end-to-end, coprire failure iniziali e
  preservare i risultati gia` ottenuti; verificare budget e timeout.
- Verificare obiettivo solver/adapter, provenance, bound/gap, seed effettivi,
  stati di adozione e failure; chiarire le scelte non specificate prima del codice.
- Uscita: test per stage raggiunti e non raggiunti e aggiornamento audit 16.2.

### B03 - Provenance e persistenza

- Verificare e completare policy provenance nel manifest; confrontare hash di
  configurazione, policy, input e file con i requisiti effettivi. Non calcolare
  hash di input opachi senza un contratto concordato.
- Testare integrita`, redazione, versionamento e round-trip di successi,
  infeasibility, indisponibilita`, failure adapter e post-check.
- Creare documento M07 dedicato con requisiti, failure, test e limiti.

### B04 - Solver e post-check

- Verificare traduzione modello, preservazione vincoli, tolleranze, esiti
  infeasible/time-limited e divieto di adozione dopo post-check negativo.
- Eseguire integrazioni reali disponibili per SCIP e CPLEX; verificare export
  CPLEX in ambiente idoneo. Se non disponibile, dichiarare il blocco e non
  attribuire ai test simulati il valore di una verifica live.

### B05 - Chiusura e allineamento

- Risolvere eventuali ambiguita` normative prima delle scelte osservabili; ad
  esempio la sezione 14 menziona sia cataloghi built-in sia registrazione del
  backend da parte del chiamante: chiarire il testo rispetto a 21.8.
- Controllare tutte le righe e i criteri applicabili delle sezioni 20-21;
  eseguire suite e lint, verificare esempi e notebook, aggiornare roadmap e
  dichiarare completate le milestone solo con evidenze sufficienti.
- Restano esplicitamente fuori M08 e gli adapter condizionali. Una verifica
  incompleta o un ambiente indisponibile non e` un criterio superato.