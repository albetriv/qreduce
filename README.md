# QReduce

QReduce e` un framework per ridurre il dominio combinatorio di grandi problemi di ottimizzazione mista prima del solve classico del problema residuo.

Usa **Maximum Weight Independent Set (MWIS)** per selezionare un sottoinsieme di decisioni binarie da mantenere attive. Le decisioni escluse vengono fissate esplicitamente; obiettivo e vincoli hard del problema originale restano responsabilita` del solver classico.

> **Stato**: progetto in fase iniziale di implementazione. E` disponibile una pipeline single-pass dimostrativa per il portfolio sintetico; artifact completi, recovery e multi-round restano fuori dalla prima milestone.

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

Per installare il solver classico opzionale CPLEX:

```powershell
poetry install --extras cplex
```

`poetry lock` risolve le dipendenze e crea o rigenera il file `poetry.lock`, che
e` versionato. `poetry install` crea o riusa l'ambiente virtuale e installa il
package in modalita` editable insieme alle dipendenze gia` risolte.

Le dipendenze core restano provider-agnostic. Test e lint appartengono al gruppo
di sviluppo. Il binding Python CPLEX appartiene all'extra `cplex`, perche` e`
richiesto soltanto dal solver classico opzionale `cplex`. Il binding e` importato
lazy da `CplexClassicalBackend`, quindi `import qreduce` non lo carica. Se il
binding, la licenza o l'ambiente CPLEX non sono utilizzabili, QReduce produce una
failure esplicita e non seleziona automaticamente un solver alternativo.

## Selezione dei solver

L'applicazione seleziona i solver tramite ID pubblici e serializzabili; QReduce
risolve internamente il relativo backend Python attraverso registry espliciti.

```text
mis_solver_id = "local_greedy"
classical_solver_id = "cplex"
```

`local_greedy` risolve il MWIS usato per la riduzione del dominio. `cplex`
risolve il MILP/MIQP residuo dopo l'applicazione dei fixing. Le classi interne
`LocalGreedyMISBackend` e `CplexClassicalBackend` non sono la scelta primaria
dell'utente. Un ID sconosciuto, non disponibile o incompatibile fallisce in modo
esplicito; non e` previsto fallback silenzioso.

## Policy e valutazione esterna

QReduce esegue policy graph/MIS/riduzione fornite dall'applicazione chiamante e ne registra configurazione, provenance ed esiti. Non include un workflow di calibrazione, benchmark o selezione automatica della policy: riferimenti classici, metriche di qualita`, soglie e separazione fra tuning e valutazione finale restano responsabilita` dell'applicazione o dell'adapter di dominio.

## Integrazione concettuale

```text
applicazione esterna
  -> problema originale + policy esplicita
  -> adapter di dominio + MIS solver + solver classico
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
  -> compilation ed esecuzione del MIS solver
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
