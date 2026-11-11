# 01 - Project setup and Python compatibility

## Scopo

Allineare l'infrastruttura di sviluppo a Python 3.12 e preparare il
progetto a dipendenze opzionali o runtime-specifiche senza compromettere
l'indipendenza del kernel QReduce.

## Riferimenti alle specifiche

- Sezioni 3.1, 11, 17, 18, 19 e 21 di `docs/specifications.md`.
- `docs/implementation/00-implementation-overview.md`.

## Decisioni applicate

- QReduce supporta Python `>=3.12,<3.13`.
- Il kernel non impone ne` include un solver MIS o classico concreto.
- Gli esperimenti interni possono scegliere solver e dipendenze opzionali proprie.
- Il kernel non importa direttamente SDK di provider MIS.
- Un backend richiesto ma indisponibile deve produrre failure esplicita.

## Allineamento documentale richiesto

Il valore in `pyproject.toml` e` la fonte tecnica della compatibilita` Python.
Il README dichiara Python 3.12, coerentemente con il vincolo di packaging.

Il README dovra` inoltre descrivere `poetry.lock` come file risolto e versionato;
la sua creazione o rigenerazione e` responsabilita` di `poetry lock`, mentre
`poetry install` installa le dipendenze risolte.

## Tassonomia delle dipendenze

| Categoria | Esempi | Regola |
|---|---|---|
| Core | Librerie strettamente necessarie al kernel | Provider-agnostic |
| Development | pytest, ruff | Qualita` e test |
| Experimental classical solver | Binding Python CPLEX o PySCIPOpt | Gruppo Poetry `experiments`, import lazy dai backend core |
| MIS solver | `local_greedy`, `dwave_simulated_annealing` o SDK provider | i due ID locali sono built-in; D-Wave Ocean e` nel gruppo `experiments` e importato lazy; provider ulteriori tramite registry e capability |
| Domain adapter | Librerie di dominio | Fornito dal chiamante o confinato negli esperimenti |

## CPLEX come capability sperimentale

La scelta di CPLEX non autorizza fallback automatici. Il runtime dovra` rilevare
in modo esplicito almeno:

```text
requested solver: cplex
binding importable: true | false
license/environment available: true | false | unknown
MIQP support available: true | false | unknown
effective solver: cplex | unavailable
```

disponibili in ogni ambiente.
I binding Python CPLEX e PySCIPOpt sono dichiarati nel gruppo Poetry
`experiments`. Sono importati lazy dai backend core `cplex` e `scip`, quindi non
sono richiesti per importare QReduce. L'installazione del gruppo rende disponibili
i binding opzionali, ma non implica che la licenza CPLEX o le capacita` MIQP siano
utilizzabili in ogni ambiente.

## Convenzioni di progetto

```text
src/qreduce/        package applicativo
src/qreduce/experiments/ runner interno al repository, escluso dal wheel
tests/              test permanenti
docs/               specifiche e decisioni di implementazione
notebooks/tasks/    notebook didattici in memoria
notebooks/experiments/ notebook di analisi di artifact persistiti
outputs/{experiment_id}/{run_id}/ artifact prodotti dal runner interno
.cline-tmp/         file temporanei dell'agente, ignorati da Git
```

Le funzioni, classi e algoritmi devono essere implementati in moduli Python.
Eventuali notebook possono caricare artefatti, visualizzare risultati e
orchestrare chiamate leggere, ma non sono la fonte primaria della business
logic.

## Deliverable implementativi iniziali

- Allineamento README e `pyproject.toml` sulla compatibilita` Python 3.12.
- Configurazione test e lint riproducibile tramite Poetry.
- Meccanismo per dichiarare capability installate senza importarle dal core.
- Verifica controllata del binding CPLEX prima di dichiarare operativo il backend.
- Cataloghi solver built-in, registry di estensione espliciti e regole di
  packaging per dipendenze core, development ed esperimenti opzionali.

## Criteri di completamento

- `poetry run pytest` e `poetry run ruff check .` sono eseguibili in Python 3.12.
- README, `pyproject.toml` e CI dichiarano la stessa versione supportata.
- Nessuna dipendenza provider-specifica e` richiesta dal package core soltanto
  per importare `qreduce`.
- Un solver richiesto e non disponibile puo` essere rappresentato come
  capability/failure esplicita e non come selezione automatica di un'alternativa.
- `.cline-tmp/` continua a essere ignorata e non contiene codice applicativo.