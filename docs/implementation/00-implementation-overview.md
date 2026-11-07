# QReduce - Implementation overview

## Scopo

Questo documento e` la roadmap tecnica iniziale della prima versione di QReduce.
Traduce `docs/specifications.md` in milestone implementative, senza sostituirla:
le specifiche restano la fonte normativa per requisiti funzionali, confini di
responsabilita`, garanzie, stati, failure reason e criteri di accettazione.

I documenti in `docs/implementation/` registrano invece decisioni tecniche
operative, assunzioni temporanee e contratti da verificare durante lo sviluppo.
Una decisione qui descritta puo` essere rivista se non modifica i requisiti
normativi o se la revisione delle specifiche viene approvata esplicitamente.

## Decisioni gia` stabilite per la v1

| Tema | Decisione |
|---|---|
| Runtime supportato | Python 3.12 |
| Backend classico concreto | IBM ILOG CPLEX |
| Adapter dimostrativo obbligatorio | Ottimizzazione media-varianza di portafoglio |
| Primo percorso completo | Riduzione single-pass |
| Provider quantistici/remoti | Non richiesti per la prima milestone |
| Kernel | Indipendente da provider, SDK e oggetti runtime proprietari |

CPLEX e l'adapter di portafoglio rendono dimostrabile il requisito della v1 di
un solve residuo MIQP con variabili binarie e continue. Non rendono il kernel
dipendente da CPLEX o dal dominio finanziario.

## Principio di progettazione

La prima milestone deve produrre un vertical slice locale e auditabile:

```text
portfolio problem
  -> domain adapter builds ReductionGraph
  -> canonical MWIS/QUBO
  -> local MIS backend
  -> sample validation, repair, ranking and candidate domain
  -> explicit fixing manifest
  -> CPLEX residual MIQP solve
  -> adapter post-check
  -> versioned artifacts and run summary
```

Il risultato MWIS restringe il dominio delle decisioni binarie. Non e` il
portafoglio finale e non trasferisce ottimalita` globale dal problema residuo al
problema originale dopo fixing euristico.

## Documentazione e fonti di verita`

| Contenuto | Posizione | Regola |
|---|---|---|
| Requisiti, garanzie e non-obiettivi | `docs/specifications.md` | Normativo |
| Roadmap e decisioni tecniche correnti | `docs/implementation/` | Revisionabile e tracciabile |
| Logica riutilizzabile | `src/qreduce/` | Nessuna business logic nei notebook |
| Test permanenti | `tests/` | Ogni milestone aggiunge test proporzionati |
| Artefatti di run | `outputs/{run_id}/` | Generati dalla pipeline, non usati come file temporanei |
| File temporanei dell'agente | `.cline-tmp/` | Mai importati dal codice applicativo |

## Sequenza implementativa proposta

| Ordine | Documento | Risultato verificabile |
|---:|---|---|
| 01 | `01-project-setup-and-python-compatibility.md` | Ambiente Python 3.12 e convenzioni allineati |
| 02 | `02-core-domain-models-and-configuration.md` | Configurazione, stati, metadata e contratti serializzabili |
| 03 | `03-canonical-mwis-graph-and-qubo.md` | Grafo, QUBO, energia, Ising ed exact diagnostics |
| 04 | `04-mis-backends-and-adapter-contracts.md` | Contratto MIS e backend locale concreto |
| 05 | `05-mean-variance-portfolio-domain-adapter.md` | Adapter MIQP, CPLEX, fixing e post-check |
| 06 | Futura orchestrazione single-pass | Pipeline concreta, artifact e test di integrazione |
| 07 | Future estensioni | Multi-round, recovery e adapter remoti/provider-specifici |

## Rappresentazioni MWIS e indipendenza dal provider

Il core deve distinguere livelli diversi:

```text
ReductionGraph
  -> canonical QUBO over delta_i in {0, 1}
  -> optional canonical Ising form over z_i in {-1, +1}
  -> adapter-specific compilation, if required
```

QUBO e` la formulazione matematica binaria quadratica del MWIS. BQM e` una
struttura dati usata da alcuni ecosistemi per rappresentare termini lineari e
quadratici binari o spin. Ising e` una formulazione equivalente su spin.

Il kernel non deve richiedere un SDK BQM e non deve esporre oggetti runtime di
un provider. Un adapter puo` costruire un BQM, una Hamiltoniana, un circuito o
una rappresentazione nativa soltanto quando la propria capability lo richiede.

## Decisioni volutamente rinviate

Le seguenti scelte saranno documentate quando il codice ne richiedera` una
definizione concreta:

- libreria per dataclass/configurazione e validazione;
- formato interno definitivo delle strutture QUBO e Ising;
- algoritmo del backend MIS locale concreto;
- schema esatto di tutti i file JSON e CSV;
- binding Python CPLEX e strategia di packaging/licenza;
- API pubblica finale di `QReduce.run(...)`;
- CLI, notebook e schema di input utente;
- BQM/annealing, gate-based, neutral-atom o adapter remoti;
- multi-round, recovery, rollback e fallback espliciti futuri.

Ogni scelta dovra` rispettare la capability validation, il divieto di fallback
silenzioso e l'auditabilita` richiesti dalle specifiche.

## Criteri per passare dalla documentazione al codice

L'implementazione puo` iniziare quando ogni task ha:

1. confini di responsabilita` chiari;
2. input, output e failure osservabili;
3. un piano di test minimo;
4. dipendenze dichiarate e non implicite;
5. una decisione esplicita su cio` che resta fuori dalla milestone.