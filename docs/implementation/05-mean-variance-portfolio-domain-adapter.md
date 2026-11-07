# 05 - Mean-variance portfolio domain adapter

## Scopo

Definire l'adapter dimostrativo della v1: un problema di ottimizzazione media-varianza di portafoglio risolto come MIQP residuo tramite CPLEX. L'adapter dimostra il percorso end-to-end senza rendere il kernel dipendente da finanza, CPLEX o da una rappresentazione universale dei problemi.

## Riferimenti alle specifiche

- Sezioni 3.1, 4, 5.1, 8, 13, 14, 15, 17 e 21.
- `docs/implementation/00-implementation-overview.md`.
- `docs/implementation/02-core-domain-models-and-configuration.md`.

## Problema dimostrativo

Per ciascun asset `i`, `delta_i` indica se l'asset resta selezionabile e `x_i` il peso continuo. Una formulazione iniziale e`:

```text
minimize:
    risk_aversion * x^T * Sigma * x
    - expected_return^T * x

subject to:
    sum_i x_i = 1
    lower_bound_i * delta_i <= x_i <= upper_bound_i * delta_i
    delta_i in {0, 1}
    x_i >= 0
```

Questa e` una forma iniziale per dati sintetici e test. Vincoli ulteriori, limiti di cardinalita`, budget, turnover, esposizioni o costi possono essere aggiunti solo se rimangono espliciti nell'adapter e nel post-check.

## Confini di responsabilita`

| Componente | Responsabilita` |
|---|---|
| Portfolio adapter | Item ID, pesi, archi, fixing, modello residuo e post-check di dominio |
| QReduce core | Pipeline MWIS, candidate domain, manifest, tempi e artifact comuni |
| CPLEX backend | Solve del modello MIQP ristretto e risultato solver uniforme |
| Chiamante | Policy, dati/istanza, adozione di business e valutazione esterna |

Il core riceve problemi opachi costruiti dall'adapter. Non deve conoscere classi CPLEX, formule finanziarie o strutture dati dell'istanza.

## Item, fixing e modello residuo

Ogni asset deve avere un `item_id` unico e stabile almeno per il run. Se un asset viene escluso dal candidate domain, il fixing manifest deve fare applicare:

```text
delta_i = 0
x_i = 0
```

Il secondo fixing puo` essere ottenuto dalle linking constraints gia` presenti, ma l'adapter deve dimostrarne e verificarne l'effetto. Obiettivo e tutti i vincoli globali devono restare nel modello residuo.

## Policy iniziale del grafo

La policy di costruzione del grafo e` esterna/versionata e non e` una legge finanziaria universale. Per la prima implementazione puo` usare dati sintetici e una regola semplice, auditabile e sostituibile, per esempio:

- peso nodale da rendimento atteso, rischio individuale o score di retention dichiarato;
- arco per correlazione assoluta sopra una soglia esplicita;
- reason dell'arco che includa metrica e soglia applicata.

La policy deve registrare input, formula, soglie, versione e qualunque normalizzazione. Il grafo di riduzione non sostituisce Sigma, il modello MIQP o i vincoli hard di portafoglio.

## CPLEX backend

Il backend CPLEX deve esporre il contratto classico delle specifiche e almeno:

- configurare time limit, mip gap, seed e threads quando supportati;
- restituire status, feasible, objective, bound/gap quando disponibili e runtime;
- distinguere optimal, infeasible, failed e time limit con o senza incumbent;
- esportare il modello se richiesto;
- dichiarare indisponibilita` del binding o della licenza senza fallback.

La scelta del binding Python CPLEX e la strategia di installazione saranno fissate soltanto dopo una verifica dell'ambiente e documentate nel task del backend classico.

## Post-check indipendente

L'adapter deve validare la soluzione senza fidarsi soltanto dello status del solver. Il controllo deve includere almeno:

- conformita` a tutti i fixing del manifest;
- budget `sum_i x_i = 1` entro tolleranza;
- bounds e linking constraints;
- integrality delle variabili `delta`;
- non negativita` dei pesi, se attivata;
- ricomputazione obiettivo quando supportata;
- failure reasons di dominio.

Una soluzione e` adottabile soltanto con solve feasible, post-check positivo e fixing rispettati.

## Dati e test iniziali

La prima milestone deve usare istanze sintetiche piccole e deterministiche, costruite nei test o tramite factory Python. Non introdurre dataset esterni o notebook come fonte primaria della logica.

Test minimi:

- mapping stabile asset/item/variabili;
- fixing di asset esclusi applica `delta_i = 0` e `x_i = 0`;
- problema residuo conserva obiettivo e vincoli globali;
- CPLEX indisponibile restituisce failure esplicita;
- soluzione CPLEX feasible supera il post-check;
- soluzione che viola fixing, integrality o budget non e` adottata;
- il solver puo` scegliere un sottoinsieme fattibile di `C_effective` che non coincide con una candidate MWIS sorgente.

## Moduli Python indicativi

```text
src/qreduce/domains/portfolio/models.py
src/qreduce/domains/portfolio/adapter.py
src/qreduce/classical/contracts.py
src/qreduce/classical/cplex_backend.py
src/qreduce/domains/portfolio/postcheck.py
```

I moduli finanziari restano separati dal core e possono evolvere senza cambiare il contratto di `ReducibleProblemAdapter`.

## Criteri di completamento

- Una piccola istanza MIQP media-varianza percorre il flusso di restriction, solve CPLEX e post-check.
- L'adapter fornisce mapping completo e auditabile fra item e variabili fissate.
- Il fixing euristico non viene presentato come preservazione dell'ottimo originale.
- L'indisponibilita` CPLEX e le infeasibility sono serializzate come esiti espliciti.