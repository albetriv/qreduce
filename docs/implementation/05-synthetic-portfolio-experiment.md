# 05 - Synthetic mean-variance portfolio experiment

## Scopo

Definire un esperimento interno di ottimizzazione media-varianza di portafoglio che genera un MIQP residuo solver-agnostico. Il portfolio resta confinato negli esperimenti; i solver built-in `local_greedy`, `cplex` e `scip` appartengono invece alla libreria e non importano il dominio portfolio.

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
| Esperimento portfolio | Item ID, pesi, archi, fixing, compilazione MIQP generica e post-check di dominio |
| QReduce core | Pipeline MWIS, cataloghi solver, modello classico generico, traduzione backend, tempi e artifact comuni |
| Backend classici built-in | Traduzione lazy del modello generico verso CPLEX o SCIP senza dipendenza dal portfolio |
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

## Solver classici built-in

Nell'esperimento gli ID classici `cplex` e `scip` sono risolti dalle factory
built-in QReduce. Il residual problem portfolio implementa
`build_classical_model()` e restituisce variabili, obiettivo MIQP e vincoli in
forma solver-agnostica; il backend selezionato effettua la traduzione nativa.
L'integrazione deve almeno:

- configurare time limit, mip gap, seed e threads quando supportati;
- restituire status, feasible, objective, bound/gap quando disponibili e runtime;
- distinguere optimal, infeasible, failed e time limit con o senza incumbent;
- esportare il modello se richiesto;
- dichiarare indisponibilita` del binding o della licenza senza fallback.

I binding Python CPLEX e PySCIPOpt vengono installati tramite il gruppo Poetry
`experiments`. Il test live CPLEX richiede inoltre una licenza locale utilizzabile
e deve essere marcato come integrazione opzionale.

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

Usare istanze sintetiche piccole e deterministiche, costruite nei test o tramite factory Python. Non introdurre dataset esterni o notebook come fonte primaria della logica.

Test minimi:

- mapping stabile asset/item/variabili;
- fixing di asset esclusi applica `delta_i = 0` e `x_i = 0`;
- problema residuo conserva obiettivo e vincoli globali;
- CPLEX indisponibile restituisce failure esplicita;
- il percorso single-pass usa `local_greedy`, costruisce fixing e richiede `cplex`;
- soluzione CPLEX feasible supera il post-check;
- soluzione che viola fixing, integrality o budget non e` adottata;
- il solver puo` scegliere un sottoinsieme fattibile di `C_effective` che non coincide con una candidate MWIS sorgente.

## Moduli Python indicativi

```text
src/qreduce/experiments/portfolio_domain/models.py
src/qreduce/experiments/portfolio_domain/adapter.py
src/qreduce/classical/model.py
src/qreduce/classical/contracts.py
src/qreduce/classical/registry.py
src/qreduce/classical/cplex_backend.py
src/qreduce/classical/scip_backend.py
src/qreduce/pipeline/single_pass.py
src/qreduce/experiments/portfolio_domain/postcheck.py
```

I moduli finanziari restano confinati negli esperimenti e possono evolvere senza cambiare il contratto di `ReducibleProblemAdapter`.

## Criteri di completamento

- L'esperimento portfolio percorre `local_greedy`, restriction, solve `cplex` o
  `scip` e post-check tramite cataloghi solver built-in QReduce.
- L'adapter fornisce mapping completo e auditabile fra item e variabili fissate.
- Il fixing euristico non viene presentato come preservazione dell'ottimo originale.
- L'indisponibilita` CPLEX e le infeasibility sono serializzate come esiti espliciti.