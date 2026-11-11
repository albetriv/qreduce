# 03 - Canonical MWIS graph and QUBO

## Scopo

Implementare il nucleo provider-independent del problema Maximum Weight Independent Set: grafo di riduzione, validazione, QUBO canonica, energia locale, conversione dichiarata a Ising ed exact solver diagnostico per piccole istanze.

## Riferimenti alle specifiche

- Sezioni 6, 7, 11.1, 11.2, 17 e 20.1.
- `docs/implementation/00-implementation-overview.md`.

## Confine del task

Questo task non costruisce il grafo da un dominio applicativo, non esegue un backend MIS remoto e non sceglie il candidate domain. Riceve un grafo gia` definito dall'adapter e produce una rappresentazione MWIS canonica, serializzabile e controllabile localmente.

## Stato dell'audit

**Stato: Completata.** L'audit del 2026-11-11 ha verificato requisito per
requisito il grafo canonico, la QUBO MWIS standard, l'energia locale, la
conversione QUBO-Ising e l'exact diagnostic bounded. Le evidenze riproducibili
sono in `tests/mwis/`: invarianti e serializzazione del grafo, termini QUBO e
policy della penalita`, equivalenza di energia QUBO-Ising, e enumerazione exact
con rifiuto esplicito oltre `exact_solver_max_variables`. Il test exact verifica
inoltre che tutti i minimizzatori globali della QUBO standard siano indipendenti
e di peso MWIS, non soltanto il minimizzatore restituito nel risultato
diagnostico.

## ReductionGraph canonico

Il modello deve contenere almeno `node_ids`, `node_weights`, `edges`, `edge_reasons`, `graph_policy_id` e `graph_policy_version`.

Invarianti:

- `node_ids` stabilisce il solo `node_order` del round;
- ogni item ID e` unico, serializzabile e stabile nel run;
- ogni peso e` finito e non negativo;
- ogni arco ha endpoint esistenti, distinti e ordinati lessicograficamente;
- non sono ammessi self-loop o archi duplicati;
- ogni arco ha almeno una reason serializzabile.

## QUBO MWIS obbligatoria

Per `delta_i in {0, 1}`, la formulazione standard e`:

```text
minimize Q(delta)

Q(delta) =
    - sum_i w_i * delta_i
    + lambda_edge * sum_(i,j) in E delta_i * delta_j
```

Il costruttore standard deve generare soltanto:

- un termine lineare `-w_i` per ogni nodo;
- un termine quadratico `lambda_edge` per ogni arco;
- un offset esplicito, inizialmente zero se non richiesto dalla conversione.

Non sono ammessi termini di cardinalita` o penalita` equivalenti. I vincoli di cardinalita` appartengono al problema classico residuo e agli eventuali filtri post-sampling dichiarati dalla policy.

La policy standard deve validare:

```text
lambda_edge > max_i(w_i)
```

Una policy non certificante richiede l'opt-in esplicito previsto dalle specifiche e non puo` dichiarare la garanzia strutturale della QUBO standard.

## QUBO, BQM e Ising

QUBO e` la formulazione matematica binaria quadratica. BQM e` un contenitore generico di termini lineari/quadratici, con variabili binarie o spin, usato da alcuni SDK. Ising usa spin `z_i in {-1, +1}` invece di `delta_i in {0, 1}`.

La conversione deve dichiarare la convenzione:

```text
delta_i = (1 + z_i) / 2
z_i = 2 * delta_i - 1
```

Il kernel deve poter rappresentare QUBO e Ising con oggetti propri e serializzabili. La produzione di un BQM di una libreria esterna e` opzionale e appartiene a un adapter che ne dichiari la capability.

## Exact solver diagnostico

Un solver exact per MWIS/QUBO e` obbligatorio soltanto per test e diagnostica sotto `exact_solver_max_variables`. Deve:

- rifiutare esplicitamente istanze sopra soglia;
- enumerare o risolvere esattamente tutte le assegnazioni sotto soglia;
- distinguere un optimum certificato da una `RawMISSample` ordinaria;
- consentire test della condizione strutturale e dell'energia QUBO.

Non e` il backend destinato alle grandi istanze o al normale percorso operativo.

## Moduli Python indicativi

```text
src/qreduce/mwis/graph.py
src/qreduce/mwis/qubo.py
src/qreduce/mwis/ising.py
src/qreduce/mwis/energy.py
src/qreduce/mwis/exact.py
src/qreduce/mwis/validation.py
```

La struttura e` indicativa e puo` evolvere senza cambiare i contratti descritti.

## Test minimi

- Ogni nodo genera un solo termine lineare corretto.
- Ogni arco genera un solo termine quadratico corretto.
- Non sono presenti termini di cardinalita`.
- La policy standard rifiuta `lambda_edge <= max_i(w_i)`.
- L'energia locale coincide con l'energia esportata su piccoli grafi.
- Su grafi enumerabili, un minimo QUBO certificato e` indipendente e MWIS.
- La conversione QUBO-Ising preserva argmin e differenze di energia, a offset dichiarato.
- Grafo non valido: duplicati, pesi non finiti, endpoint assenti o reason mancanti producono failure esplicita.

## Criteri di completamento

- Gli oggetti canonici non contengono classi runtime proprietarie di SDK.
- Grafo, QUBO e Ising sono serializzabili con ordine dei nodi esplicito.
- Il solver exact e` confinato a diagnostica/test piccoli.
- Il task successivo puo` compilare la stessa rappresentazione per backend diversi.

L'audit ha confermato i criteri sopra senza introdurre dipendenze runtime da SDK
di provider: gli oggetti canonici rimangono serializzabili e l'exact solver non
e` incluso nel percorso operativo dei backend MWIS.