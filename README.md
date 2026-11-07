# QReduce

QReduce e` un framework per ridurre il dominio combinatorio di grandi problemi di ottimizzazione mista prima del solve classico del problema residuo.

Usa **Maximum Weight Independent Set (MWIS)** per selezionare un sottoinsieme di decisioni binarie da mantenere attive. Le decisioni escluse vengono fissate esplicitamente; obiettivo e vincoli hard del problema originale restano responsabilita` del solver classico.

> **Stato**: progetto in fase iniziale di implementazione. Il package Python e la configurazione di sviluppo sono disponibili; i workflow di riduzione non sono ancora implementati.

## Sviluppo

Il progetto usa [Poetry](https://python-poetry.org/) e adotta un layout `src/`.
La compatibilita` tecnica supportata e` Python `>=3.12,<3.13`; il valore in
`pyproject.toml` e` la fonte autorevole.

```powershell
poetry lock
poetry install
poetry run pytest
poetry run ruff check .
```

`poetry lock` risolve le dipendenze e crea o rigenera il file `poetry.lock`, che
e` versionato. `poetry install` crea o riusa l'ambiente virtuale e installa il
package in modalita` editable insieme alle dipendenze gia` risolte.

Le dipendenze core restano provider-agnostic. Test e lint appartengono al gruppo
di sviluppo; binding del backend classico, SDK MIS e librerie di dominio saranno
isolati nei rispettivi adapter solo quando la loro installazione e il loro
contratto runtime saranno verificati. In particolare, CPLEX non e` una
dipendenza del package core: se il backend richiesto non e` disponibile, QReduce
deve produrre una failure esplicita e non selezionare automaticamente un solver
alternativo.

## Policy e valutazione esterna

QReduce esegue policy graph/MIS/riduzione fornite dall'applicazione chiamante e ne registra configurazione, provenance ed esiti. Non include un workflow di calibrazione, benchmark o selezione automatica della policy: riferimenti classici, metriche di qualita`, soglie e separazione fra tuning e valutazione finale restano responsabilita` dell'applicazione o dell'adapter di dominio.

## Integrazione concettuale

```text
applicazione esterna
  -> problema originale + policy esplicita
  -> adapter di dominio + backend MIS + backend classico
  -> QReduce
  -> candidate domain + fixing manifest + solve residuo + post-check
  -> decisione dell'applicazione
```

L'applicazione mantiene la responsabilita` del modello di dominio, della scelta della policy, delle metriche di qualita` e dell'adozione del risultato. QReduce gestisce la riduzione e ne produce artifact auditabili. La descrizione completa del flusso e dei confini di responsabilita` e` nella sezione 5.1 delle specifiche.

## Flusso

```text
problema MIP/MIQP/MIQCP
  -> grafo di conflitto/ridondanza
  -> MWIS canonico: grafo, QUBO e/o BQM/Ising
  -> compilation ed esecuzione del backend MIS
  -> validazione, repair e candidate domain
  -> fixing delle decisioni escluse
  -> solve classico del problema residuo
  -> post-check della soluzione finale
```

## Backend indipendenti dal provider

Il kernel e` indipendente da QPU, simulatore e SDK specifici. Un adapter compila ed esegue il problema MWIS sul backend configurato, che puo` essere un solver locale, un simulatore o una QPU annealing, gate-based, neutral-atom o hybrid.

Esempi di adapter previsti: D-Wave, IBM Qiskit/Quantum, AWS Braket e Pasqal/Pulser. Nessun provider e` richiesto dal kernel e non sono ammessi fallback silenziosi fra backend o modalita` di esecuzione.

## Garanzie

- MWIS propone una riduzione del dominio; non e` la soluzione finale del problema originale.
- Un fixing derivato euristicamente non certifica l'ottimalita` globale dell'originale.
- Ogni soluzione residua deve superare un post-check rispetto ai fixing e ai vincoli del problema originale.
- Configuration, risultati intermedi, failure e provenance del backend devono essere auditabili.

## Documentazione

La specifica completa e normativa e` disponibile in [`docs/specifications.md`](./docs/specifications.md).
