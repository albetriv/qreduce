# 01 - Project setup and Python compatibility

## Scopo

Allineare l'infrastruttura di sviluppo della v1 a Python 3.12 e preparare il
progetto a dipendenze opzionali o runtime-specifiche senza compromettere
l'indipendenza del kernel QReduce.

## Riferimenti alle specifiche

- Sezioni 3.1, 11, 17, 18, 19 e 21 di `docs/specifications.md`.
- `docs/implementation/00-implementation-overview.md`.

## Decisioni applicate

- La v1 supporta Python `>=3.12,<3.13`.
- IBM ILOG CPLEX e` il backend classico concreto della v1.
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
| Classical backend | Binding Python CPLEX | Isolato dal core |
| MIS adapter | Algoritmo locale o SDK provider | Dichiarato tramite capability |
| Domain adapter | Librerie numeriche per il portfolio | Isolate dal kernel |

## CPLEX come capability runtime

La scelta di CPLEX non autorizza fallback automatici. Il runtime dovra` rilevare
in modo esplicito almeno:

```text
requested backend: cplex
binding importable: true | false
license/environment available: true | false | unknown
MIQP support available: true | false | unknown
effective backend: cplex | unavailable
```

Il binding Python CPLEX e` dichiarato come dipendenza runtime del backend
classico dimostrativo con vincolo `cplex (>=22.2.0.0,<23.0.0.0)`. Rimane isolato
dal kernel tramite import lazy nel backend concreto: la dichiarazione di
packaging rende riproducibile l'installazione, ma non implica che licenza e
capacita` MIQP siano disponibili in ogni runtime.

## Convenzioni di progetto

```text
src/qreduce/        package applicativo
tests/              test permanenti
docs/               specifiche e decisioni di implementazione
outputs/{run_id}/   artifact della pipeline
.cline-tmp/         file temporanei dell'agente, ignorati da Git
```

Le funzioni, classi e algoritmi devono essere implementati in moduli Python.
Eventuali notebook futuri possono caricare artefatti, visualizzare risultati e
orchestrare chiamate leggere, ma non sono la fonte primaria della business
logic.

## Deliverable implementativi iniziali

- Allineamento README e `pyproject.toml` sulla compatibilita` Python 3.12.
- Configurazione test e lint riproducibile tramite Poetry.
- Meccanismo per dichiarare capability installate senza importarle dal core.
- Verifica controllata del binding CPLEX prima di dichiarare operativo il backend.
- Regole di packaging per dipendenze core, development e opzionali.

## Criteri di completamento

- `poetry run pytest` e `poetry run ruff check .` sono eseguibili in Python 3.12.
- README, `pyproject.toml` e CI futura dichiarano la stessa versione supportata.
- Nessuna dipendenza provider-specifica e` richiesta dal package core soltanto
  per importare `qreduce`.
- L'indisponibilita` di CPLEX puo` essere rappresentata come capability/failure
  esplicita e non come selezione automatica di un solver alternativo.
- `.cline-tmp/` continua a essere ignorata e non contiene codice applicativo.