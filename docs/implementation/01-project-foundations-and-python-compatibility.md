# M01 - Fondazioni di progetto e compatibilita` Python

## Stato

**Completata.** La verifica locale del 2026-11-12 ha confermato Python 3.12.12
tramite Poetry, coerenza del lock con `poetry check --lock`, pytest (143 test
superati) e Ruff. I test di indipendenza runtime, capability e registry coprono
l'assenza di SDK opzionali e failure esplicite senza fallback.

## Scopo e confini

Allineare l'infrastruttura di sviluppo a Python 3.12 e preparare il
progetto a dipendenze opzionali o runtime-specifiche senza compromettere
l'indipendenza del kernel QReduce.

## Riferimenti normativi

- Sezioni 3.1, 11, 17, 18, 19 e 21 di `docs/specifications.md`.
- `00-implementation-overview.md`.

## Dipendenze

- Poetry, `pyproject.toml` e `poetry.lock` sono la fonte per packaging e
  dipendenze risolte.
- I backend concreti possono richiedere binding opzionali, ma il package core
  non deve importarli per rendere disponibile `qreduce`.

## Implementazione ed evidenze

- QReduce supporta Python `>=3.12,<3.13`.
- Il kernel include cataloghi di ID solver standard, ma non impone quale ID debba
  essere selezionato da una run.
- I backend built-in concreti e gli esperimenti interni possono richiedere
  dipendenze opzionali proprie.
- Il kernel non importa direttamente SDK di provider MIS.
- Un backend richiesto ma indisponibile deve produrre failure esplicita.
- La CI automatica non e` richiesta: test e lint sono verificati localmente.

`poetry.lock` e` versionato; `.cline-tmp/` e` ignorata da Git e da Cline e non
fa parte del codice applicativo. Il README dichiara Python 3.12 e rimane
coerente con il vincolo in `pyproject.toml`.

### Allineamento documentale

Il valore in `pyproject.toml` e` la fonte tecnica della compatibilita` Python.
Il README dichiara Python 3.12, coerentemente con il vincolo di packaging.

Il README descrive inoltre `poetry.lock` come file risolto e versionato;
la sua creazione o rigenerazione e` responsabilita` di `poetry lock`, mentre
`poetry install` installa le dipendenze risolte.

### Tassonomia delle dipendenze

| Categoria | Esempi | Regola |
|---|---|---|
| Core | Librerie strettamente necessarie al kernel | Provider-agnostic |
| Development | pytest, ruff | Qualita` e test |
| Experimental classical solver | Binding Python CPLEX o PySCIPOpt | Gruppo Poetry `experiments`, import lazy dai backend core |
| MIS solver | `local_greedy`, `dwave_simulated_annealing` o SDK provider | i due ID locali sono built-in; D-Wave Ocean e` nel gruppo `experiments` e importato lazy; provider ulteriori tramite registry e capability |
| Domain adapter | Librerie di dominio | Fornito dal chiamante o confinato negli esperimenti |

### CPLEX come capability sperimentale

La scelta di CPLEX non autorizza fallback automatici. Il runtime dovra` rilevare
in modo esplicito almeno:

```text
requested solver: cplex
binding importable: true | false
license/environment available: true | false | unknown
MIQP support available: true | false | unknown
effective solver: cplex | unavailable
```

I binding Python CPLEX, PySCIPOpt e D-Wave Ocean sono dichiarati nel gruppo
Poetry `experiments`. Sono importati lazy dai backend core `cplex`, `scip` e
`dwave_simulated_annealing`, quindi non sono richiesti per importare QReduce.
L'installazione del gruppo rende disponibili i binding opzionali, ma non implica
che la licenza CPLEX, le capacita` MIQP o un backend esterno siano utilizzabili in
ogni ambiente.

### Convenzioni di progetto

```text
src/qreduce/        package applicativo
src/qreduce/experiments/ runner interno al repository, escluso dal wheel
tests/              test permanenti
docs/               specifiche e decisioni di implementazione
notebooks/tasks/    notebook didattici in memoria
notebooks/experiments/ notebook di analisi di artifact persistiti
outputs/{run_id}/ artifact prodotti dal runner interno
.cline-tmp/         file temporanei dell'agente, ignorati da Git
```

Le funzioni, classi e algoritmi devono essere implementati in moduli Python.
Eventuali notebook possono caricare artefatti, visualizzare risultati e
orchestrare chiamate leggere, ma non sono la fonte primaria della business
logic.

### Deliverable implementativi iniziali

- Allineamento README e `pyproject.toml` sulla compatibilita` Python 3.12.
- Configurazione test e lint riproducibile tramite Poetry.
- Meccanismo per dichiarare capability installate senza importarle dal core.
- Verifica controllata del binding CPLEX prima di dichiarare operativo il backend.
- Cataloghi solver built-in, registry di estensione espliciti e regole di
  packaging per dipendenze core, development ed esperimenti opzionali.

## Test e verifica

- `poetry check --lock`, `poetry run pytest` e `poetry run ruff check .` sono
  i controlli locali previsti.
- I test di runtime independence e registry verificano import lazy e failure
  esplicite quando un binding o una capability non sono disponibili.

## Criteri di completamento

- `poetry run pytest` e `poetry run ruff check .` sono eseguibili in Python 3.12.
- README e `pyproject.toml` dichiarano la stessa compatibilita` supportata.
- Nessuna dipendenza provider-specifica e` necessaria per importare il core.
- Un solver non disponibile e` rappresentato da capability o failure esplicita.

## Esclusioni e lavoro successivo

La CI automatica non e` richiesta. L'aggiunta di provider o SDK ulteriori resta
condizionale a una milestone che ne dichiari contratto, capability e ambiente di
verifica.

## Riferimenti correlati

- [README](../../README.md)
- [Configurazione del progetto](../../pyproject.toml)
- [Overview di implementazione](00-implementation-overview.md)
