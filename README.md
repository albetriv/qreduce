# QReduce

QReduce e` un framework per ridurre il dominio combinatorio di grandi problemi di ottimizzazione mista prima del solve classico del problema residuo.

Usa **Maximum Weight Independent Set (MWIS)** per selezionare un sottoinsieme di decisioni binarie da mantenere attive. Le decisioni escluse vengono fissate esplicitamente; obiettivo e vincoli hard del problema originale restano responsabilita` del solver classico.

> **Stato**: progetto in fase di specifica e progettazione. Non sono ancora disponibili un pacchetto installabile o comandi di esecuzione.

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

La specifica completa e normativa e` disponibile in [`docs/specifications.md`](docs/specifications.md).