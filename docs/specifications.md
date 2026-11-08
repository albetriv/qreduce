# QReduce - Specifiche del framework

## 1. Scopo

QReduce e` un framework per ridurre il dominio combinatorio di grandi problemi di ottimizzazione mista prima della loro risoluzione classica.

Il framework usa Maximum Weight Independent Set (MWIS) come meccanismo di selezione strutturale. Il kernel costruisce una rappresentazione canonica del problema MWIS, comprensiva di grafo, QUBO e, quando utile, BQM o Ising. Un adapter di esecuzione la compila verso il formato richiesto dal backend configurato e ne normalizza gli esiti in sample binarie. Dopo validazione e possibile repair, tali sample diventano candidate di insiemi indipendenti da cui derivare un sottoinsieme di decisioni binarie da trattenere. Il problema residuo viene quindi risolto da un backend classico.

QReduce adotta uno schema di riduzione assimilabile a una **MIS invertita**: la MWIS non fissa direttamente la soluzione discreta finale del problema originale. Le candidate MWIS servono invece a costruire un dominio candidato ridotto; il backend classico sceglie poi i valori finali delle decisioni binarie ancora disponibili e delle eventuali variabili continue o discrete collegate, rispettando l'obiettivo e tutti i vincoli hard originali.

Il flusso principale e`:

```text
problema originale grande
  -> costruzione di un grafo di conflitto/ridondanza
  -> rappresentazione canonica MWIS: grafo, QUBO e/o BQM/Ising
  -> compilazione ed esecuzione con backend configurato
     (solver locale, simulatore, QPU annealing, gate-based, neutral-atom o hybrid)
  -> normalizzazione delle risposte in sample binarie canoniche
  -> repair, validazione e ranking delle candidate di insieme indipendente
  -> costruzione di un dominio combinatorio ridotto
  -> fissaggio esplicito delle decisioni escluse
  -> solve classico del problema residuo
```

QReduce supporta sia una riduzione in singolo passaggio sia una riduzione iterativa, in cui il processo viene ripetuto fino a quando il problema residuo rientra in un budget di complessita` o di tempo definito dall'utente.

## 2. Obiettivi

QReduce deve:

- supportare problemi grandi MIP, MIQP e MIQCP con decisioni binarie riducibili;
- usare MIS per proporre un dominio discreto piu` piccolo, non per sostituire automaticamente il problema originale ne` per fissare direttamente la selezione finale;
- mantenere il kernel indipendente da provider, SDK e modello computazionale del backend MIS;
- supportare backend MIS locali o remoti, classici o quantistici, tramite adapter che dichiarano capability e rappresentazioni accettate;
- consentire compilation da una rappresentazione MWIS canonica verso QUBO/BQM, Ising/Hamiltoniane, circuiti gate-based, rappresentazioni native di grafo o altri formati specifici del backend;
- mantenere il solve finale dei vincoli hard e dell'obiettivo originale in un backend classico;
- supportare riduzione single-pass e multi-round;
- distinguere in modo esplicito riduzione euristica, fixing sicuro e fixing imposto dall'utente;
- produrre artifact completi, deterministici quando possibile e auditabili;
- consentire adapter per diversi domini applicativi senza incorporare logica di dominio nel kernel;
- accettare policy di riduzione esplicite e rendere osservabili, serializzabili e riproducibili i parametri e gli esiti necessari affinche` un'applicazione esterna possa confrontare policy differenti.

## 3. Non-obiettivi

QReduce non deve:

- dichiarare ottimalita` globale del problema originale quando ha applicato esclusioni euristiche;
- assumere che qualsiasi problema MIP possa essere trasformato utilmente in MIS;
- interpretare la MIS come il complemento del grafo o come un'inversione dei segni/degli obiettivi della QUBO: l'inversione riguarda il flusso decisionale, dalla MIS al dominio candidato e poi al solve classico;
- trasformare automaticamente tutti i vincoli hard in penalita` QUBO;
- usare il valore di energia QUBO come unico criterio di qualita` della soluzione finale;
- reimplementare implicitamente primitive, compiler, transpiler, embedding o algoritmi proprietari gia` forniti da un SDK o servizio selezionato;
- assumere che tutti i backend accettino BQM/QUBO, usino `num_reads`, restituiscano energia QUBO o dispongano di un simulatore locale equivalente;
- nascondere fallback, rilassamenti, failure o indisponibilita` di backend;
- dipendere da uno specifico dominio, dataset, benchmark o applicazione finanziaria;
- definire o imporre dataset di calibrazione, benchmark, riferimento classico, funzione di qualita`, soglie di accettazione o regole universali per scegliere una policy migliore;
- eseguire automaticamente tuning, calibrazione o selezione di policy in base a risultati di run precedenti.

### 3.1 Perimetro della prima versione

La prima versione implementa il percorso end-to-end con i componenti obbligatori seguenti:

| Componente | Stato nella prima versione |
|---|---|
| Adapter di dominio dimostrativo | obbligatorio |
| Rappresentazione MWIS canonica: grafo, QUBO e conversione BQM/Ising quando applicabile; validazione, repair e candidate domain | obbligatorio |
| Contratto di compilation/esecuzione MIS provider-agnostic con dichiarazione delle capability | obbligatorio |
| Backend MIS locale concreto, euristico o simulato | obbligatorio; non deve rendere il kernel dipendente da uno specifico provider o SDK |
| Exact MIS/QUBO solver | obbligatorio, solo per diagnostica e test sotto una soglia configurabile |
| Backend classico SCIP **oppure** CPLEX | obbligatorio: almeno una integrazione concreta deve essere operativa |
| Secondo backend classico | interfaccia predisposta; implementazione opzionale nella prima versione |
| Adapter annealing/BQM, ad esempio D-Wave Ocean | opzionale nella prima versione; se implementato, puo` supportare simulatore locale, hybrid o QPU secondo capability dichiarate |
| Adapter gate-based, ad esempio IBM Qiskit o AWS Braket | opzionale nella prima versione; contratto predisposto |
| Adapter neutral-atom, ad esempio Pasqal/Pulser | opzionale nella prima versione; contratto predisposto |
| QPU remota, embedding o mapping fisico | non richiesti nella prima versione; richiesti soltanto dagli adapter che li dichiarano necessari |

La configurazione deve rifiutare esplicitamente un backend dichiarato ma non implementato o non disponibile. Uno stub o un contratto predisposto non costituisce un backend utilizzabile.

## 4. Classe di problemi supportata

La prima versione supporta problemi con la forma concettuale:

```text
minimize or maximize F(delta, x, y)

subject to:
    delta_i in {0, 1}                    for i in I
    x in X(delta)
    y in Y(delta, x)
    hard_constraints(delta, x, y) hold
```

dove:

- `delta` sono decisioni binarie di attivazione, selezione o inclusione;
- `x` sono eventuali variabili continue;
- `y` sono eventuali altre variabili discrete o continue;
- `I` e` il dominio delle decisioni binarie candidabili alla riduzione.

Il problema e` adatto a QReduce quando sono vere tutte le condizioni seguenti:

1. Esiste un insieme identificabile di decisioni binarie riducibili.
2. E` possibile assegnare a ogni decisione un punteggio di retention o utilita` locale.
3. E` possibile costruire una relazione utile di conflitto, incompatibilita`, ridondanza o sostituibilita` tra decisioni.
4. Fissare una decisione esclusa a zero produce un problema classico residuo semanticamente valido.
5. Il solver classico puo` ottimizzare il problema residuo con l'obiettivo e i vincoli originali.

Esempi potenziali comprendono selezione di progetti, facility/service selection, sparse optimization, feature selection con secondo stadio, network design, scheduling con incompatibilita` e modelli di allocazione con variabili di attivazione.

## 5. Principio metodologico

MIS non risolve automaticamente il problema originale. MIS produce una proposta di riduzione del suo dominio combinatorio.

```text
MIS result != final solution of the original optimization problem

MIS result -> retained decision domain -> residual classical solve
```

Questo distingue QReduce da una MIS diretta. In una MIS diretta, un supporto `S` prodotto dalla MIS sarebbe gia` la selezione discreta da rifinire; gli elementi esterni a `S` non potrebbero rientrare. In QReduce, invece, piu` supporti MWIS validati e classificati `S_1, ..., S_m` vengono aggregati in un dominio `C_effective`: la MIS determina dove il solver classico puo` cercare, mentre il solver classico decide quali elementi di `C_effective` attivare effettivamente. Il portafoglio, piano o altra soluzione finale non deve quindi coincidere con una singola candidate MWIS ne` con la loro unione.

Lo schema non costruisce il complemento del grafo e non inverte l'obiettivo della QUBO. Gli archi sono usati per produrre candidate di retention strutturalmente non conflittuali; il loro significato e la loro eventuale relazione con i vincoli hard restano di competenza dell'adapter di dominio.

Il solver classico resta responsabile di:

- valutare l'obiettivo originale;
- far rispettare tutti i vincoli hard del modello;
- scegliere i valori finali delle variabili non fissate;
- restituire status, bound, gap e prova di fattibilita` secondo le capacita` del backend.

### 5.1 Esempio concettuale di integrazione da parte di un'applicazione esterna

Un'applicazione esterna possiede un problema di dominio e usa QReduce come componente di riduzione, non come sostituto del proprio modello o del proprio solver classico.

```text
Applicazione esterna
  1. carica o costruisce il problema originale;
  2. seleziona una policy esplicita di grafo, MIS, repair e riduzione;
  3. costruisce adapter di dominio, backend MIS e backend classico;
  4. invoca QReduce con tali dipendenze e con la configurazione risolta;
  5. riceve risultato, fixing manifest, post-check e artifact;
  6. applica decisioni di business o metriche di dominio esterne.

Adapter di dominio
  - identifica le decisioni binarie riducibili;
  - costruisce il grafo con pesi e ragioni degli archi;
  - traduce il candidate domain in fixing del problema originale;
  - costruisce il problema residuo;
  - verifica la soluzione finale rispetto alla semantica del dominio.

QReduce
  - orchestra la pipeline MWIS e la riduzione;
  - seleziona il candidate domain secondo la policy ricevuta;
  - non interpreta il significato di dominio di nodi, pesi e archi;
  - non sceglie la policy migliore;
  - non dichiara che il fixing euristico preservi l'ottimo originale.

Backend classico
  - risolve il problema ristretto;
  - mantiene objective e vincoli hard originali;
  - restituisce risultato, bound/gap e stato secondo le sue capability.
```

Il flusso concettuale di una singola richiesta e`:

```text
original_problem
  + domain_adapter
  + reduction_policy
  + mis_solver_id
  + classical_solver_id
  + artifact_configuration
  -> QReduce.run(...)
  -> reduction_result

reduction_result
  -> candidate_domain
  -> fixing_manifest
  -> residual_classical_result
  -> postcheck_result
  -> run_manifest and artifacts
```

La firma `QReduce.run(...)` e` concettuale e non costituisce ancora un'API Python pubblica. L'API concreta deve mantenere gli stessi confini di responsabilita`.

La scelta della policy appartiene al chiamante. Per esempio, il chiamante puo` passare una policy fornita manualmente, sperimentale o calibrata da un workflow esterno. QReduce serializza i relativi metadata di provenance, ma non confronta run precedenti e non modifica la policy durante il run.

L'applicazione adotta una soluzione soltanto se il risultato classico e` feasible e il post-check dell'adapter e` positivo. In caso contrario deve trattare l'esito come failure o partial result secondo le proprie regole di dominio; QReduce conserva comunque artifact, metriche e failure reason.

## 6. Modello MIS

### 6.1 Grafo di riduzione

Per ogni round di riduzione il framework costruisce un grafo non orientato:

```text
G_t = (V_t, E_t)
```

dove:

- ogni nodo `i in V_t` rappresenta una decisione binaria ancora attivabile ed e` identificato da un `item_id` canonico e stabile nel run;
- un peso finito e non negativo `w_i` rappresenta la priorita` di retention del nodo;
- un arco `(i, j) in E_t` indica che le decisioni non dovrebbero essere trattenute insieme nella stessa candidate di insieme indipendente.

Il significato esatto di peso e arco appartiene all'adapter di dominio. Il framework impone soltanto che sia esplicito, riproducibile e serializzato negli artifact. L'ordine dei nodi deve essere dichiarato una sola volta per round; ogni vettore `delta` usa quell'ordine. Ogni arco deve essere normalizzato come coppia non ordinata senza self-loop ne` duplicati, con endpoint ordinati lessicograficamente per `item_id`.

Un arco puo` rappresentare, ad esempio:

- incompatibilita` logica gia` presente nel modello;
- ridondanza tecnica o statistica;
- competizione per una risorsa scarsa;
- sovrapposizione eccessiva di copertura;
- dominanza euristica;
- correlazione o similarita` oltre una soglia;
- una relazione di mutua esclusione stimata dal dominio.

Il grafo e` una struttura di riduzione, non necessariamente una codifica completa del modello originale. In particolare, dopo l'aggregazione di piu` candidate indipendenti, il candidate domain puo` contenere endpoint di uno stesso arco provenienti da candidate diverse. Il solve classico residuo non deve quindi assumere che `C_effective` sia a sua volta un insieme indipendente; deve mantenere l'obiettivo e i vincoli originali applicabili.

### 6.2 QUBO weighted MIS

La formulazione QUBO di base deve essere:

```text
minimize Q(delta)

Q(delta) =
    - sum_i w_i * delta_i
    + lambda_edge * sum_(i,j) in E delta_i * delta_j

delta_i in {0, 1}
lambda_edge > max_i(w_i), for non-empty V
```

Il modello QUBO deve contenere esclusivamente:

- un termine lineare `-w_i * delta_i` per ogni nodo;
- un termine quadratico positivo `lambda_edge * delta_i * delta_j` per ogni arco.

Con pesi finiti e non negativi e con `lambda_edge > max_i(w_i)`, ogni minimizzatore globale della QUBO corrisponde a un insieme indipendente: se una selezione contiene un arco violato, rimuovere uno dei suoi endpoint diminuisce strettamente l'energia. Il sampling euristico puo` comunque produrre sample non indipendenti e deve quindi passare dalla validazione strutturale.

Il problema MWIS e gli esiti di un backend MWIS devono essere distinti. Un solver exact puo` restituire un solo optimum globale, oppure piu` optimum se e` configurato per enumerarli e ne esistono diversi con lo stesso peso massimo. Un backend euristico o stocastico puo` invece restituire molte sample distinte nella stessa esecuzione o in esecuzioni con seed diversi; tali sample possono essere subottimali, non massimali o persino non indipendenti prima del repair. Anche un backend deterministico puo` restituire piu` esiti se supporta l'enumerazione di soluzioni ottime o near-optimal. In tutti i casi, QReduce normalizza ogni esito come `RawMISSample`: il nome non certifica che la sample sia un MWIS globale.

`lambda_edge_policy` deve essere serializzata e dichiarare almeno:

```text
policy identifier and version
weight normalization, if any
formula used to derive lambda_edge
effective lambda_edge
proof condition satisfied: true | false
intended behavior when the proof condition is false
```

La prima versione deve rifiutare una configurazione standard MWIS in cui `lambda_edge <= max_i(w_i)`, salvo una policy sperimentale esplicitamente marcata `allow_noncertifying_penalty=true`; quest'ultima non puo` dichiarare la garanzia strutturale sopra descritta.

La cardinalita` non deve entrare nella QUBO standard tramite penalita` quadrate, hinge penalties o termini equivalenti. Eventuali requisiti di cardinalita` del problema originale devono essere gestiti dal problema classico residuo e, se necessario, da filtri o repair post-sampling espliciti.

### 6.3 Convenzioni delle variabili

```text
x       variabile continua
delta   variabile binaria in {0, 1}
z       spin Ising in {-1, +1}
```

Se e` necessaria una conversione tra QUBO binaria e Ising, deve essere dichiarata:

```text
delta = (1 + z) / 2
z = 2 * delta - 1
```

## 7. Pipeline single-pass

La pipeline single-pass deve seguire questi stadi. Il termine `RawMISSample` indica solo una sample binaria prodotta dal backend: non implica che sia indipendente, massimale o di peso massimo. Piu` `RawMISSample` distinte possono provenire da sampling euristico/stocastico, da esecuzioni con seed diversi oppure da un backend deterministico configurato per enumerare piu` soluzioni; il framework non assume una sola di tali origini.

```text
1. Validare il problema e identificare le decisioni binarie riducibili.
2. Costruire il grafo G = (V, E) e i pesi nodali w.
3. Costruire la rappresentazione canonica MWIS: grafo, QUBO e, quando richiesto dalla compilation, BQM e/o Ising.
4. Validare la configurazione rispetto alle capability del backend MIS configurato.
5. Compilare la rappresentazione canonica nel formato del backend e registrare il tempo residuo disponibile.
6. Eseguire il job MIS tramite backend configurato e normalizzare gli esiti in `RawMISSample` secondo il `node_order` canonico.
7. Deduplicare le sample binarie per vettore delta.
8. Validare la fattibilita` strutturale delle `RawMISSample` rispetto al grafo e ricalcolare le metriche canoniche disponibili.
9. Riparare deterministicamente le sample non indipendenti, quando abilitato, e validare di nuovo l'esito.
10. Trasformare gli esiti validi in `IndependentSetCandidate`, applicare filtri hard, score e ranking dichiarati.
11. Selezionare fino a `num_source_mis_candidates` `RankedRetentionCandidate`, soggette alla policy di diversita`.
12. Aggregare le candidate, applicare la protezione dichiarata, il precheck e il cap per ottenere il candidate domain effettivo `C_effective`; tale dominio e` una proposta di ricerca e non una selezione finale.
13. Fissare fuori da `C_effective` le decisioni binarie escluse.
14. Risolvere il problema residuo con un solver classico entro il budget residuo, lasciando al solver la scelta delle decisioni binarie non fissate e delle altre variabili del modello.
15. Validare la soluzione finale rispetto ai vincoli originali, alle tolleranze e al fixing manifest.
16. Salvare artifact, provenance, metriche e failure reason, anche in caso di terminazione anticipata.
```

La pipeline non puo` adottare una soluzione finale se il post-check del modello originale fallisce.

## 8. Candidate domain e riduzione

### 8.1 Candidate domain

Il candidate domain effettivo `C_effective` e` un insieme di decisioni che restano disponibili nel problema residuo:

```text
C_effective subseteq V
```

La costruzione standard ha due fasi:

```text
C_raw = union(S_1, S_2, ..., S_m)
C_effective = apply_protection_and_cap(C_raw, protected_items, V)
```

dove `S_1, ..., S_m` sono `RankedRetentionCandidate` riparate se necessario, validate, ordinate e selezionate secondo la policy di diversita`.

Usare l'unione di piu` candidate e` preferibile al fissaggio del singolo MIS migliore, poiche` riduce la sensibilita` al sampling stocastico e preserva alternative combinatorie per il solver classico. Questa e` la realizzazione operativa dello schema MIS invertita: `C_effective` delimita il dominio in cui il solver classico puo` scegliere, ma non impone di selezionare tutti i suoi item e non richiede che la soluzione finale coincida con una candidate MIS sorgente.

Ogni candidate deve essere serializzata come `CandidateRecord` con almeno:

```text
candidate_id
raw_sample_id
selected_item_ids in canonical order
raw_energy
energy_recomputed_after_repair, if repaired
selection_weight
num_selected
num_violated_edges_before_repair
repair_status
repair_actions
adapter_domain_score, if supplied
candidate_rank_key
```

### 8.2 Ranking degli elementi

Gli elementi del candidate domain devono essere ordinati con una policy dichiarata. La policy iniziale obbligatoria per la prima versione usa solo candidate selezionate dopo deduplicazione, validazione, repair e filtro di diversita`. Per ogni item, `selection_frequency` e` il numero di candidate selezionate che lo contengono; `mean_candidate_quality` e` la media aritmetica del `candidate_quality_score` delle candidate selezionate che lo contengono.

Salvo una policy dell'adapter esplicitamente versionata, `candidate_quality_score` e` il valore scalare `selection_weight`. La `candidate_rank_key`, usata per ordinare e selezionare le candidate, e` invece la tupla lessicografica:

```text
1. selection_weight decrescente;
2. num_selected decrescente;
3. energy_recomputed_after_repair crescente;
4. candidate_id crescente.
```

Il ranking degli item usa la chiave lessicografica seguente:

```text
1. selection_frequency decrescente;
2. mean_candidate_quality decrescente;
3. node_weight decrescente;
4. item_id crescente.
```

Il framework deve consentire ad adapter e policy di definire score ulteriori, senza rendere tali score universali o impliciti. La policy deve registrare la formula, i dati di input, la direzione di ordinamento, i tie-breaker e la relativa versione.

### 8.3 Cap e dominio minimo

La policy deve definire:

```text
candidate_domain_max_items
candidate_domain_min_items
num_source_mis_candidates
```

Gli item protetti devono appartenere al dominio di input `V`. Non e` ammesso riattivare un item fissato a zero in un round precedente senza una policy esplicita di rollback e ricostruzione del modello; la prima versione non supporta il rollback.

Gli item `mandatory_items`, `user_locked_items` e `safe_retained_items` hanno precedenza sul cap. Se il loro numero supera `candidate_domain_max_items`, il round fallisce con `protected_items_exceed_candidate_domain_cap`; il framework non deve scartare silenziosamente un item protetto. Gli `incumbent_supported_items` seguono la politica configurata `incumbent_protection_mode: required | best_effort`: nel primo caso producono lo stesso failure, nel secondo possono essere scartati solo secondo il ranking e con reason code esplicita.

Se il dominio effettivo supera il cap, vengono mantenuti prima tutti gli item protetti che ne hanno precedenza e poi gli altri item secondo il ranking dichiarato. Se `C_effective` e` inferiore alla dimensione minima globale o a quella richiesta dal precheck dell'adapter, il round fallisce con stato esplicito e non deve applicare fixing parziale silenzioso.

### 8.4 Fissaggio delle decisioni escluse

Data una riduzione da dominio `V` a dominio `C_effective`, il problema residuo deve imporre:

```text
delta_i = 0    for every i in V \ C_effective
```

Le eventuali variabili collegate a `delta_i` devono essere fissate o vincolate coerentemente dall'adapter di dominio. Per esempio, se `x_i` e` una variabile continua attiva solo quando `delta_i = 1`, il modello residuo deve assicurare:

```text
x_i = 0        for every i in V \ C_effective
```

Il modello deve mantenere l'obiettivo originale e tutti i vincoli globali applicabili. La riduzione non autorizza a omettere vincoli che coinvolgono elementi esclusi, come bilanci, demand satisfaction, costi di switching o condizioni di stato iniziale. Il backend classico puo` pertanto scegliere qualsiasi combinazione fattibile degli item in `C_effective`, incluse combinazioni che non coincidono con una singola candidate MWIS, purche` rispetti il modello originale e il fixing manifest.

## 9. Riduzione iterativa

### 9.1 Stato iniziale

```text
P_0 = problema originale
V_0 = dominio completo delle decisioni riducibili
```

Il budget end-to-end inizia prima della validazione iniziale e termina dopo la scrittura degli artifact terminali. Include validazione, costruzione del grafo, sampling, repair, solve classico, post-check e serializzazione obbligatoria; non include soltanto attese esterne non attribuibili al processo, che devono comunque essere registrate separatamente quando misurabili.

### 9.2 Round t

Per ogni round `t`:

```text
G_t = build_graph(P_t, V_t)
samples_t = solve_mis(G_t)
C_t_raw = build_candidate_domain(samples_t, G_t)
C_t_effective = apply_protection_and_cap(C_t_raw, protected_items_t, V_t)
P_(t+1) = restrict(P_t, C_t_effective)
V_(t+1) = C_t_effective
```

L'implementazione deve registrare la relazione tra domini:

```text
original domain V_0
input domain V_t
raw retained domain C_t_raw
effective retained domain C_t_effective
excluded items V_t \ C_t_effective
cumulative retained domain V_(t+1)
```

Esempio di un singolo round seguito da una possibile iterazione. Se il dominio iniziale e`:

```text
V_0 = {A, B, C, D, E, F}
```

le candidate di insieme indipendente ottenute da un backend MWIS e selezionate nel solo round `0` possono essere, ad esempio:

```text
S_1 = {A, C}
S_2 = {A, D}
S_3 = {B, D, E}
```

I tre set dell'esempio non sono necessariamente tre MWIS globali. Nel caso usuale di un backend euristico o stocastico rappresentano sample/candidate distinte, ad esempio generate nella stessa esecuzione o con seed diversi, poi validate, eventualmente riparate e classificate. Con un backend exact potrebbero invece rappresentare piu` optimum di pari peso soltanto se il backend e` configurato per enumerarli. In entrambi i casi, la pluralita` di candidate serve a preservare alternative per il dominio del solve classico, non a dichiarare che ogni candidate sia ottima per MWIS.

L'aggregazione interna allo stesso round produce:

```text
C_0_raw = {A, B, C, D, E}
```

Se protezioni e cap determinano `C_0_effective = {A, B, C, D}`, gli item `E` e `F` sono esclusi e il problema `P_1` impone `delta_E = 0` e `delta_F = 0`. Se il processo termina dopo questo round, il solver classico sceglie una combinazione fattibile di `A`, `B`, `C` e `D`. Se invece viene avviato il round `1`, il suo dominio di input e` soltanto:

```text
V_1 = C_0_effective = {A, B, C, D}
```

Il grafo e le candidate MWIS del round `1` possono quindi contenere solo `A`, `B`, `C` e `D`; `E` e `F` non possono rientrare. L'unione di piu` candidate avviene dunque prima del fixing, all'interno di ciascun round, mentre la riduzione tra round e` monotona.

Per la prima versione vale l'invariante di monotonicita`:

```text
V_(t+1) subseteq V_t
protected_items_t subseteq V_t
```

Gli insiemi protetti devono essere applicati prima del fixing del round. Un item non puo` essere reinserito dopo essere stato escluso e fissato in un round precedente.

### 9.3 Criteri di stop

Il processo iterativo deve arrestarsi quando si verifica almeno una condizione:

```text
- il problema residuo soddisfa il budget di complessita` classica;
- il numero di variabili binarie residue e` <= target_binary_variables;
- e` raggiunto il numero massimo di round;
- la riduzione marginale e` inferiore a min_reduction_ratio;
- il candidate domain e` troppo piccolo per un precheck del problema;
- non e` prodotta alcuna candidate di insieme indipendente valida;
- viene superato il budget temporale end-to-end;
- una policy di sicurezza richiede di non applicare ulteriori fixing euristici.
```

Il budget di complessita` classica non deve basarsi solo sul numero di nodi. Deve poter combinare:

```text
number of binary variables
number of integer variables
number of continuous variables
number and type of quadratic constraints
model density or non-zero count
estimated memory
remaining classical time budget
optional probe-solve diagnostics
```

Per un round con `|V_t| > 0`, la riduzione marginale e` definita come:

```text
round_reduction_ratio_t = (|V_t| - |C_t_effective|) / |V_t|
```

Il controllo contro `min_reduction_ratio` usa il valore non negativo sopra definito dopo protezioni e cap. Se `|V_t| = 0`, non viene avviato un nuovo round MIS e il processo passa direttamente alla valutazione del budget/classical solve.

### 9.4 Politiche di conservazione

Prima del fixing, `C_t_raw` puo` essere unito a insiemi protetti espliciti appartenenti a `V_t`:

```text
C_t_effective =
    C_t_raw
    union mandatory_items
    union user_locked_items
    union safe_retained_items
    union incumbent_supported_items, if configured
```

Ogni elemento aggiunto deve riportare una reason code. Il framework non puo` aggiungere elementi protetti in modo implicito.

### 9.5 Policy di recovery

La prima versione non esegue rollback ne` riattiva item gia` fissati. Le policy di recovery ammesse sono configurabili e devono essere esplicite:

```text
on_candidate_domain_too_small:
    fail
    retain_more_ranked_items_before_fixing

on_reduced_problem_infeasible:
    fail
    retry_with_larger_domain_from_same_round

max_recovery_attempts >= 0
```

`retain_more_ranked_items_before_fixing` e `retry_with_larger_domain_from_same_round` possono essere usate soltanto prima di rendere terminale il fixing del round e devono ricostruire il problema a partire da `P_t`. Ogni tentativo deve avere artifact, reason code, durata e dominio propri. Se la policy e` `fail`, l'infeasibilita` del problema residuo termina il run senza fallback silenzioso.

## 10. Tipi di fixing e garanzie

### 10.1 Origine del fixing e livello di garanzia

Ogni entry del fixing manifest deve distinguere `fixing_origin` da `guarantee_level`:

```text
fixing_origin:
    mis_heuristic
    certified_rule
    user_mandated

guarantee_level:
    heuristic
    safe
    user_imposed
```

`user_imposed` significa che la restrizione e` stata richiesta esplicitamente dall'utente; non implica, da sola, una prova di sicurezza o una garanzia di ottimalita` rispetto al problema originale. Un fixing utente puo` avere `guarantee_level = safe` solo se possiede anche una prova o regola certificata separatamente registrata.

### 10.2 Fixing euristico

Una esclusione derivata da MIS e` per default euristica:

```text
fixing_reason = mis_heuristic_exclusion
fixing_origin = mis_heuristic
guarantee_level = heuristic
```

Un solve su un problema ridotto euristicamente non certifica l'ottimalita` rispetto al problema originale, anche se il solver classico certifica l'ottimalita` del problema residuo.

### 10.3 Fixing sicuro

Un fixing puo` essere marcato come sicuro solo se supportato da una prova o da una regola formalmente valida, ad esempio:

```text
- implication from model logic;
- certified dominance rule;
- valid reduced-cost fixing;
- solver presolve certificate;
- domain-specific proof accepted by the adapter.
```

```text
fixing_reason = one of the declared certified reasons
fixing_origin = certified_rule
guarantee_level = safe
```

MIS da sola non costituisce un certificato di fixing sicuro.

### 10.4 Bound e dichiarazioni ammesse

Ogni risultato deve indicare almeno:

```text
objective_sense:
    minimize
    maximize

original_primal_bound:
    numeric value | unavailable

original_dual_bound:
    numeric value | unavailable

original_bound_provenance:
    full_domain_classical_solve
    valid_relaxation
    certified_domain_rule
    none

original_problem_optimality_claim:
    none
    certified

residual_problem_optimality_claim:
    unavailable
    feasible_incumbent
    gap_bounded
    certified_optimal
```

Una soluzione classica feasible del problema ridotto e` anche una soluzione feasible del problema originale con i fixing applicati. Pertanto fornisce un bound primale sull'originale: un upper bound per minimizzazione e un lower bound per massimizzazione. Un dual bound o una certificazione di ottimalita` del problema ridotto non si trasferiscono automaticamente al problema originale dopo fixing euristico o user-imposed.

Un risultato puo` dichiarare `original_problem_optimality_claim = certified` soltanto se una procedura separata, un full-domain solve o una regola certificata dimostra la corrispondente garanzia rispetto al problema originale. In assenza di tale procedura, il risultato deve riportare la qualita` soltanto rispetto al problema residuo.

## 11. Backend MIS, compilation e adapter di provider

### 11.1 Principio di indipendenza dal provider

Il kernel QReduce non deve dipendere direttamente da classi, SDK, formati serializzati o semantiche operative di un provider specifico. La rappresentazione canonica del problema MWIS appartiene al kernel; la conversione verso BQM di uno specifico SDK, Hamiltoniane di Pauli, circuiti gate-based, sequenze neutral-atom, embedding hardware o job remoti appartiene esclusivamente a un adapter di compilation/esecuzione selezionato esplicitamente dalla configurazione.

Il framework non assume che ogni backend accetti un BQM, produca energia QUBO, supporti `num_reads`, richieda embedding, sia stocastico, sia remoto o restituisca risultati completi. Queste proprieta` devono essere dichiarate come capability dell'adapter. QUBO, BQM e Ising restano rappresentazioni canoniche utili per il modello MWIS, ma non costituiscono l'unica interfaccia di esecuzione ammessa.

### 11.2 Rappresentazione canonica e interfacce uniformi

Il framework deve esporre una rappresentazione serializzabile e indipendente dal provider, contenente almeno il grafo MWIS, il `node_order` canonico, la QUBO e le conversioni BQM/Ising quando applicabili. Gli oggetti canonici non possono essere oggetti runtime proprietari di un SDK.

```python
class MISExecutionAdapter:
    def capabilities(self) -> MISBackendCapabilities:
        ...

    def compile(
        self,
        problem: CanonicalMISProblem,
        request: MISCompilationRequest,
    ) -> CompiledMISJob:
        ...

    def solve(
        self,
        compiled_job: CompiledMISJob,
        request: MISBackendRequest,
    ) -> MISBackendResult:
        ...
```

La separazione tra `compile` e `solve` e` obbligatoria a livello contrattuale anche quando un adapter implementa internamente entrambe le fasi in una sola chiamata. Essa consente di distinguere in modo auditabile la costruzione di un BQM, Hamiltoniana, circuito, sequenza fisica, mapping geometrico, embedding o job remoto dalla sua esecuzione.

`MISCompilationRequest` deve includere almeno `run_id`, `round_index`, `node_order`, il tempo residuo, il backend richiesto, la rappresentazione canonica disponibile e i parametri specifici di compilation. `MISBackendRequest` deve includere almeno `run_id`, `round_index`, `node_order`, `random_seed` se supportato, `requested_solution_count`, il tempo residuo, i parametri specifici di esecuzione e l'identificatore del job compilato. `num_reads`, `shots`, numero di ripetizioni, profondita` QAOA, optimizer classico, transpilation, embedding, mapping geometrico e opzioni di simulazione sono parametri opzionali, validi soltanto se supportati dall'adapter selezionato.

`MISBackendResult` deve includere almeno `samples`, `requested_backend`, `effective_backend`, `requested_provider`, `effective_provider`, `backend_family`, `execution_location`, `capability_status`, `runtime_seconds`, `effective_parameters`, `completion_status` e, in caso di failure, un `terminal_reason` normalizzato. Il backend non puo` restituire risultati parziali senza dichiarare se l'esecuzione e` completa, time-limited, cancellata o fallita.

### 11.3 Capability e compatibilita`

Ogni adapter deve dichiarare almeno:

```text
provider identifier
backend identifier
backend family: classical_exact | classical_heuristic | annealing | gate_based | neutral_atom | hybrid
execution location: local | remote
supported problem forms: mis_graph | qubo | bqm | ising
supports local simulator
supports remote QPU
supports random seed
supports num_reads
supports shots
supports asynchronous execution and cancellation
requires or supports embedding, transpilation, geometric mapping or device-specific compilation
size, topology, geometry or other resource limits, when known
```

Prima della compilation, il framework deve validare che il problema, i parametri e la modalita` di esecuzione richiesta siano compatibili con le capability dichiarate. Un parametro non supportato deve essere rifiutato per default; puo` essere ignorato solo se la configurazione imposta esplicitamente una policy versionata `unsupported_backend_parameter_policy = ignore_with_warning` e l'adapter registra il warning. Non e` ammesso trasformare implicitamente una richiesta di QPU remota in simulazione locale, o viceversa.

### 11.4 Normalizzazione dei risultati

Ogni adapter deve normalizzare gli esiti in `RawMISSample` con almeno:

```text
raw_sample_id stabile nel run
node order
delta vector
num occurrences, probability o count, if available
backend-reported score e score kind, if available
canonical QUBO energy, if computable
canonical Ising energy, if computable
runtime o timestamp disponibile
backend and provider identifiers
backend/version and SDK/version, if available
effective compilation and execution parameters
redacted raw backend metadata, if serializable
```

`backend_reported_score_kind` deve distinguere almeno `qubo_energy`, `ising_energy`, `hamiltonian_expectation`, `probability`, `objective_estimate`, `provider_specific` e `unavailable`. Uno score nativo non deve essere interpretato automaticamente come energia QUBO o come criterio universale di ranking. Il framework deve ricalcolare, quando le informazioni sono disponibili, la QUBO/Ising energy canonica, il peso di selezione, il numero di nodi selezionati e la validita` strutturale del set rispetto al `ReductionGraph`.

Il vettore binario deve essere validato rispetto al `node_order` serializzato nel `ReductionGraph`; un adapter deve dichiarare e applicare esplicitamente ogni convenzione di endianess, ordine dei bit, spin/binary conversion o decoding provider-specifico. I metadata grezzi non devono contenere credenziali, token, segreti, endpoint con parametri sensibili o dati personali.

### 11.5 Backend della prima versione e adapter futuri

La prima versione implementa almeno:

```text
un backend MIS locale concreto, euristico o simulato
un exact MIS/QUBO solver per diagnostica su istanze piccole
la rappresentazione e i contratti provider-agnostic definiti in questa sezione
```

L'exact solver deve rifiutare input oltre `exact_solver_max_variables`, senza tentare enumerazioni parziali o degradare silenziosamente a un altro backend.

I contratti possono supportare adapter operativi o futuri, inclusi ma non limitati a:

```text
local classical heuristic or simulated annealing solver
D-Wave Ocean local sampler, Leap Hybrid sampler or QPU sampler with embedding management
IBM Qiskit local simulator or IBM Quantum gate-based QPU
AWS Braket local/managed simulator, gate-based QPU or annealing target when disponibile
Pasqal/Pulser local emulator or neutral-atom QPU/service
```

L'elenco non impone l'adozione di un provider, non dichiara disponibili gli adapter non implementati e non implica che tutti gli adapter abbiano le stesse capability. L'assenza di credenziali, pacchetti, accesso remoto, topologia, geometria, quota o device compatibile deve produrre un errore o stato esplicito.

### 11.6 Selezione del backend, fallback e budget

La configurazione deve distinguere:

```text
requested provider and backend
available adapter and runtime capability
requested execution mode and device
effective provider, backend and device used
effective compilation and execution parameters
completion status
failure and fallback policy
```

Il backend effettivo e` una capacita` runtime e non un semplice valore dichiarativo di configurazione. La prima versione adotta `fallback_policy = fail`: un fallback a un provider, backend, device o modalita` differente e` vietato, salvo una policy futura esplicita, auditabile, versionata e disabilitata per default. Il budget end-to-end include validazione delle capability, compilation, submission, attesa attribuibile, recupero, normalizzazione e validazione dei risultati; eventuali attese esterne non attribuibili devono essere separate e registrate quando misurabili.

## 12. Repair, validazione e diversita`

### 12.1 Validazione strutturale

Una `RawMISSample` o una `IndependentSetCandidate` e` strutturalmente valida se:

```text
for every (i, j) in E:
    not (delta_i = 1 and delta_j = 1)
```

Il validatore deve produrre:

```text
is_independent_set
violated_edges
num_violated_edges
selection_weight
num_selected
node_order_version
```

### 12.2 Repair deterministico

Il repair puo` essere abilitato per trasformare sample strutturalmente infeasible in candidate indipendenti. Repair, trim e augment sono fasi distinte: il repair rimuove conflitti; il trim riduce la cardinalita` secondo policy; l'augment aggiunge solo nodi non in conflitto con il set corrente. Ogni fase deve essere riportata separatamente negli artifact.

La policy obbligatoria della prima versione per il repair e`:

```text
1. identificare gli archi violati;
2. scegliere l'arco violato con endpoint lessicograficamente minimi;
3. rimuovere l'endpoint con peso minore;
4. a parita` di peso, rimuovere l'endpoint con grado corrente maggiore nel sottografo indotto dai nodi selezionati;
5. a ulteriore parita`, rimuovere l'endpoint con item_id lessicograficamente maggiore;
6. ripetere fino a eliminare i conflitti o raggiungere repair_max_iterations;
7. rieseguire il validatore strutturale;
8. applicare eventuale trim o augment dichiarato e rieseguire il validatore dopo ogni fase;
9. registrare tutte le azioni, i tie-breaker e gli stati intermedi.
```

Il repair non puo` essere usato per nascondere una failure. Lo stato finale deve distinguere almeno:

```text
raw_valid
repaired_valid
repaired_but_domain_too_small
repair_limit_reached
invalid
```

### 12.3 Diversita`

Il framework deve poter selezionare candidate diverse, non solo quelle con energia minore. La distanza Jaccard e` una metrica iniziale raccomandata:

```text
JaccardDistance(A, B) = 1 - |A intersection B| / |A union B|
```

Per `A = B = empty set`, la distanza e` definita come `0`. La diversita` deve essere applicata dopo la validazione strutturale e prima dell'aggregazione del candidate domain, con policy e soglia registrate. La policy iniziale considera le candidate nel loro `candidate_rank_key` crescente e accetta una candidate soltanto se la sua distanza da ogni candidate gia` accettata e` maggiore o uguale a `minimum_candidate_jaccard_distance`; in caso contrario registra il motivo di scarto.

## 13. Adapter di dominio

Il kernel QReduce deve dipendere da contratti di dominio, non da formule specifiche di una singola applicazione. Nella prima versione, `problem` e `reduced_problem` sono oggetti opachi posseduti dall'adapter: il kernel non deve dipendere da docplex, PySCIPOpt, CPLEX, SCIP o da una rappresentazione matematica universale.

I contratti minimi serializzabili sono:

```python
@dataclass(frozen=True)
class ReductionGraph:
    node_ids: tuple[str, ...]  # ordine canonico e stabile del round
    node_weights: Mapping[str, float]
    edges: tuple[tuple[str, str], ...]  # endpoint normalizzati: left < right
    edge_reasons: Mapping[tuple[str, str], str]
    graph_policy_id: str
    graph_policy_version: str


@dataclass(frozen=True)
class DomainValidationResult:
    is_valid: bool
    minimum_required_items: int | None
    protected_items: tuple[str, ...]
    failure_reasons: tuple[str, ...]


@dataclass(frozen=True)
class FinalSolutionValidationResult:
    postcheck_feasible: bool
    fixed_variable_compliance: bool
    original_constraint_compliance: bool
    objective_recomputed: float | None
    failure_reasons: tuple[str, ...]
```

Un adapter deve fornire almeno:

```python
class ReducibleProblemAdapter:
    def identify_reducible_items(self, problem) -> list[str]:
        ...

    def build_conflict_graph(self, problem, state) -> ReductionGraph:
        ...

    def validate_candidate_domain(
        self,
        problem,
        retained_item_ids: tuple[str, ...],
    ) -> DomainValidationResult:
        ...

    def restrict_problem(
        self,
        problem,
        retained_item_ids: tuple[str, ...],
        fixing_manifest,
    ):
        ...

    def validate_final_solution(
        self,
        original_problem,
        solution,
        fixing_manifest,
        tolerances,
    ) -> FinalSolutionValidationResult:
        ...
```

La risoluzione classica appartiene al `ClassicalBackend`; l'adapter puo` preparare, esportare o ispezionare il proprio modello, ma non deve duplicare il contratto di solve del backend.

L'adapter e` responsabile di:

- definire la semantica di nodi, archi e pesi;
- preservare semantica, objective e vincoli del problema originale durante il fixing;
- eseguire precheck dominio-specifici;
- fornire mapping completi e stabili tra `item_id`, variabili binarie fissate e tutte le variabili collegate da fissare o vincolare;
- serializzare informazioni di dominio necessarie all'audit;
- validare la soluzione finale rispetto al problema originale.

Ogni `item_id` restituito dall'adapter deve essere unico, serializzabile e stabile almeno per tutta la durata del run. Il framework deve rifiutare item duplicati, pesi non finiti, archi con endpoint assenti e reason mancanti per archi o fixing.

## 14. Backend classici

QReduce deve avere un'interfaccia uniforme per la risoluzione residuale:

```python
class ClassicalBackend:
    def solve(
        self,
        reduced_problem,
        request: ClassicalSolveRequest,
    ) -> ClassicalSolveResult:
        ...
```

`ClassicalSolveRequest` deve includere almeno `run_id`, `round_index`, `time_limit_seconds`, `remaining_end_to_end_seconds`, `mip_gap_tolerance`, `random_seed`, `threads` e le opzioni di export. Il tempo effettivo assegnato al backend e` il minimo positivo tra `time_limit_seconds` e `remaining_end_to_end_seconds`; se non esiste tempo residuo positivo il backend non deve essere invocato e il run termina con `end_to_end_time_budget_exhausted`.

Il risultato deve includere almeno:

```text
solver status
feasibility status
objective value
best bound, if available
relative or absolute gap, if available
is optimal
is time limited
runtime
variable counts
constraint counts
effective solver parameters
model export path, if requested
remaining time budget at solve start
```

La prima versione implementa almeno uno tra SCIP e CPLEX. Il secondo backend puo` essere supportato dal contratto ma non deve essere dichiarato operativo se non implementato. L'indisponibilita` del backend richiesto deve produrre failure esplicita; non e` ammesso il fallback silenzioso da CPLEX a SCIP o viceversa.

## 15. Post-check della soluzione finale

Ogni soluzione restituita dal backend classico deve essere verificata indipendentemente attraverso l'adapter di dominio.

Il post-check deve distinguere:

```text
solver_claimed_feasible
postcheck_feasible
postcheck_failure_reasons
objective_recomputed, if supported
fixed_variable_compliance
original_constraint_compliance
integrality_compliance
tolerances_used
```

Le tolleranze devono essere configurate e serializzate:

```text
primal_feasibility_tolerance
integrality_tolerance
objective_recomputation_absolute_tolerance
objective_recomputation_relative_tolerance
postcheck_mode: strict | solver_tolerance_aligned
```

Una variabile binaria o intera e` conforme soltanto se la sua distanza dal valore intero/fissato richiesto non supera `integrality_tolerance`. Se l'adapter supporta la ricomputazione dell'obiettivo, la differenza tra obiettivo del solver e obiettivo ricomputato deve rispettare entrambe le tolleranze di ricomputazione.

Una soluzione e` adottabile soltanto se:

```text
classical result is feasible
and postcheck_feasible is true
and fixed variables respect the fixing manifest
```

Un solve time-limited con incumbent feasible puo` essere adottato se supera il post-check. In questo caso il run deve riportare `run_status = partial_success`, `classical_solver_status = time_limit_with_feasible_incumbent` e `residual_problem_optimality_claim = feasible_incumbent` o `gap_bounded` se il backend fornisce un gap valido.

## 16. Osservabilita` delle policy e supporto alla valutazione esterna

### 16.1 Confine di responsabilita`

QReduce esegue una riduzione usando la configurazione e le policy fornite dall'applicazione chiamante. Il kernel non seleziona, ottimizza o dichiara migliore una policy graph/MIS/reduction e non include un workflow obbligatorio di calibrazione.

La definizione di una benchmark suite, la disponibilita` di un riferimento classico, la metrica di qualita` della soluzione originale, le soglie di accettazione e l'eventuale split fra calibration, validation e final evaluation appartengono all'applicazione o all'adapter di dominio.

Se un'applicazione dichiara una policy come calibrata, raccomandata, congelata o adatta a una classe di istanze, tale dichiarazione deve essere supportata da un protocollo esterno riproducibile. QReduce deve consentire di registrarne identita` e provenance, ma non ne certifica la validita` metodologica.

### 16.2 Metriche tecniche minime per ogni run

Per ogni run QReduce deve rendere disponibili, direttamente negli artifact oppure nel run summary, almeno:

```text
original binary variable count
residual binary variable count
residual continuous/integer variable counts
per-round and cumulative reduction ratio
MIS runtime
MIS provider, backend family, execution mode and effective device, if applicable
MIS compilation runtime and execution runtime, when separable
classical residual runtime
end-to-end runtime
raw sample count
unique sample count
valid and repaired candidate counts
candidate-domain size
classical residual feasibility
postcheck feasibility
objective value, when supplied by the ClassicalBackend or adapter
best bound and solver gap, when available
stability-relevant seed and stochastic-execution metadata
domain-specific evaluation metrics supplied by the adapter or caller, with metric identifiers, units, comparison convention and provenance
run status and terminal reason
```

### 16.3 Provenance di policy fornita dall'esterno

La configurazione risolta deve poter includere metadata opzionali di provenance della policy, senza attribuire al kernel responsabilita` di calibrazione:

```text
policy_id
policy_version
policy_source
policy_hash
policy_selection_status
external_policy_selection_reference
external_evaluation_reference
declared_instance_class
declared_validity_scope
```

`policy_selection_status` e` informativo e puo` assumere valori quali `user_supplied`, `externally_calibrated`, `externally_validated`, `experimental` o `unknown`.

QReduce deve serializzare tali valori, ma non deve modificarli, verificarne il contenuto metodologico o dedurre che una policy sia superiore a un'altra.

### 16.4 Regole per workflow esterni di calibrazione

Quando un'applicazione esterna usa QReduce in un workflow di calibrazione o benchmarking, deve:

```text
1. fissare e serializzare prima dell'esecuzione policy candidate, budget, seed, classe di istanze e regole di confronto;
2. non usare dati di valutazione finale o informazioni future per scegliere una policy;
3. includere failure, infeasibility e post-check failed nelle metriche aggregate;
4. definire nel dominio dell'applicazione il riferimento e la convenzione dell'eventuale objective gap;
5. distinguere fra policy candidate, policy selezionata esternamente e policy usata in una final evaluation;
6. collegare gli artifact esterni alla configurazione e al run QReduce tramite identificatori e hash.
```

## 17. Artifact e riproducibilita`

Ogni esecuzione deve avere un identificatore di run immutabile e una configurazione risolta serializzata. Ogni artifact JSON o CSV strutturato deve dichiarare, direttamente o nel relativo manifest, `schema_version`, `producer_version`, `run_id`, `created_at`, `config_hash` e, quando applicabile, `input_hash`, `policy_hash` e `content_hash`.

Struttura minima raccomandata:

```text
outputs/{run_id}/
  config_used.json
  run_manifest.json
  problem/
    original_problem_manifest.json
  rounds/
    round_000/
      graph.json
      node_weights.csv
      edge_reasons.csv
      qubo.json
      bqm.*
      ising.json
      mis_backend_capabilities.json
      mis_compilation_request.json
      mis_compilation_result.json
      mis_execution_request.json
      mis_execution_result.json
      raw_provider_result.*
      raw_samples.json
      repaired_samples.json
      scored_candidates.csv
      candidate_domain.json
      candidate_domain_items.csv
      fixed_variables.csv
      fixing_manifest.json
      reduction_metrics.json
    round_001/
      ...
  classical/
    residual_problem_manifest.json
    solver_result.json
    model_export.*
  validation/
    postcheck.json
  reports/
    run_summary.json
    diagnostics.md
```

Il fixing manifest deve includere almeno:

```text
round index
item identifier
fixed variable name or names
fixed value
fixing reason
fixing origin
guarantee level
source candidate IDs
policy version
proof or user-request reference, if applicable
```

I formati `qubo.json`, `bqm.*`, `ising.json`, gli artifact di compilation/esecuzione MIS, `raw_samples.json` e `solver_result.json` devono avere schema e versione dichiarati. I formati concreti degli artifact provider-specifici devono essere registrati nel manifest; un consumer non puo` dedurli dall'estensione del file. Per ogni esecuzione MIS devono essere serializzati provider e backend richiesti/effettivi, famiglia del backend, modalita` locale/remota, device se applicabile, capability risolte, rappresentazione compilata, mapping/embedding/transpilation se applicabili, parametri effettivi, stato di completion e decisione di fallback. Gli artifact devono preservare failure e candidate non adottate; non e` ammesso eliminare risultati negativi per produrre statistiche apparentemente migliori. I metadata serializzati devono essere redatti da credenziali, token, segreti e dati personali.

Riferimenti a benchmark, calibration run, validation run o policy selection eseguiti esternamente possono essere registrati nel `run_manifest.json` come provenance opaca. Il kernel li conserva e li collega a `config_hash` e `policy_hash`, ma non legge dataset esterni, non aggrega risultati di piu` run e non determina la policy migliore.

## 18. Configurazione

La configurazione deve essere divisa concettualmente in:

```text
problem adapter configuration
graph construction configuration
MIS/QUBO configuration
MIS backend selection and capability configuration
MIS compilation and execution configuration
provider-specific backend configuration
candidate and repair configuration
candidate-domain reduction configuration
iteration and stopping configuration
classical backend configuration
artifact and reproducibility configuration
```

Parametri minimi di riduzione:

```text
max_reduction_rounds
candidate_domain_min_items
candidate_domain_max_items
num_source_mis_candidates
min_reduction_ratio
target_binary_variables
max_end_to_end_runtime_seconds
retain_mandatory_items
retain_incumbent_supported_items
incumbent_protection_mode
on_candidate_domain_too_small
on_reduced_problem_infeasible
max_recovery_attempts
```

Parametri minimi MIS:

```text
lambda_edge
lambda_edge_policy
allow_noncertifying_penalty
mis_provider_id
mis_backend_id
mis_backend_family
execution_mode
device_id, if applicable
fallback_policy
unsupported_backend_parameter_policy
requested_solution_count
random_seed
max_distinct_samples
repair_enabled
repair_max_iterations
minimum_candidate_jaccard_distance
exact_solver_max_variables
```

Parametri di execution comuni e parametri condizionali per famiglia di backend:

```text
execution_time_limit_seconds
compilation_policy
provider_parameters

# annealing/BQM, se supportati
num_reads
annealing_time
embedding_policy

# gate-based, se supportati
shots
algorithm
qaoa_repetitions
classical_optimizer
optimizer_max_iterations
transpiler_options
noise_model

# neutral-atom, se supportati
geometric_mapping_policy
device_constraints_policy
sequence_parameters
emulator_noise_model
```

Parametri minimi solver classico:

```text
classical_solver_id
time_limit_seconds
mip_gap_tolerance
random_seed
threads
model_export_enabled
primal_feasibility_tolerance
integrality_tolerance
objective_recomputation_absolute_tolerance
objective_recomputation_relative_tolerance
postcheck_mode
```

Parametri minimi di artifact e riproducibilita`:

```text
run_id or run_id_generation_policy
artifact_schema_version
software_version
resolved_config_hash
input_hash_policy
metadata_redaction_enabled
policy_id
policy_version
policy_source
policy_hash
policy_selection_status
external_policy_selection_reference
external_evaluation_reference
```

I riferimenti esterni di policy sono metadata di provenance e non abilitano comportamenti adattivi. Una run QReduce non puo` modificare la configurazione risolta ne` selezionare una policy differente in base ai propri risultati, salvo futura funzionalita` esplicita, versionata e disabilitata per default.

## 19. Stati e failure reason

La pipeline deve distinguere `run_status`, `stage`, `terminal_reason`, `classical_solver_status`, `postcheck_status` e `adoption_status`. `run_status` non sostituisce il motivo specifico di terminazione.

```text
run_status:
    success
    partial_success
    failed

stage:
    validation
    graph
    mis
    candidate_domain
    restriction
    classical
    postcheck
    artifacts

adoption_status:
    adopted
    not_adopted
    unavailable
```

`terminal_reason` deve usare almeno i seguenti valori normalizzati:

```text
invalid_configuration
adapter_failure
graph_construction_failed
mis_backend_unavailable
mis_provider_unavailable
mis_backend_capability_mismatch
mis_problem_representation_unsupported
mis_sdk_dependency_unavailable
mis_credentials_unavailable
mis_compilation_failed
mis_embedding_failed
mis_transpilation_failed
mis_device_mapping_failed
mis_remote_submission_failed
mis_execution_failed
mis_result_normalization_failed
mis_execution_time_budget_exhausted
no_valid_mis_candidate
candidate_domain_too_small
candidate_domain_no_meaningful_reduction
protected_items_exceed_candidate_domain_cap
reduction_round_limit_reached
end_to_end_time_budget_exhausted
classical_backend_unavailable
classical_solver_failed
classical_solver_infeasible
classical_solver_time_limited
postcheck_failed
artifact_write_failed
unsupported_problem_structure
```

Uno stato `success` richiede un risultato classico post-check feasible senza time limit e con adozione della soluzione. Uno stato `partial_success` deve descrivere precisamente quale parte del workflow ha prodotto artifact validi e quale garanzia manca; include almeno il caso di incumbent feasible adottato dopo time limit. Uno stato `failed` richiede `adoption_status = not_adopted` o `unavailable`, salvo failure di scrittura artifact successiva a una soluzione gia` validata, che deve preservare il risultato in memoria e segnalare separatamente `artifact_write_failed`.

## 20. Requisiti di test

### 20.1 QUBO e BQM

- Ogni nodo produce un termine lineare corretto.
- Ogni arco produce esattamente un termine quadratico corretto.
- La QUBO non contiene penalita` di cardinalita`.
- La configurazione standard rifiuta `lambda_edge <= max_i(w_i)` e registra la policy effettiva.
- Su grafi piccoli enumerabili, con `lambda_edge > max_i(w_i)`, ogni minimizzatore globale della QUBO corrisponde a un insieme indipendente di peso massimo.
- I test distinguono un optimum MWIS certificato da una `RawMISSample`: una sample restituita da un backend euristico, stocastico o deterministico con enumerazione non e` trattata automaticamente come soluzione di peso massimo.
- Una policy non certificante richiede `allow_noncertifying_penalty=true` e non dichiara la garanzia strutturale del modello standard.
- La conversione QUBO -> BQM preserva termini e domini.
- L'energia calcolata localmente coincide con il modello esportato su casi piccoli.

### 20.2 Backend MIS provider-agnostic

- Ogni adapter dichiara provider, backend, famiglia, modalita` di esecuzione, capability e rappresentazioni supportate.
- Il framework rifiuta prima della compilation un problema, una modalita` di esecuzione o un parametro incompatibile con le capability dichiarate.
- Un backend locale concreto restituisce sample binarie con ordine nodo stabile.
- Il framework accetta e normalizza piu` sample distinte sia da backend stocastici/euristici sia da backend deterministici configurati per enumerare piu` soluzioni, senza assumere che tutte siano MWIS globali.
- Il backend exact e` rifiutato sopra una soglia esplicita di variabili.
- Ogni adapter normalizza le risposte in `RawMISSample` e preserva `node_order`, `delta`, identificatore stabile e metadata redatti.
- Il framework ricalcola, quando possibile, energia canonica, peso di selezione e validita` strutturale; uno score nativo provider-specifico non viene trattato automaticamente come energia QUBO.
- Indisponibilita` di SDK, credenziali, pacchetti, device, topologia, geometria o accesso remoto produce failure esplicita.
- I metadata dichiarano provider/backend richiesti ed effettivi, device/modalita`, capability, parametri di compilation ed esecuzione e stato di completion.
- Metadata e artifact non serializzano credenziali, token o segreti.
- Uno adapter dichiarato ma non implementato o non disponibile e` rifiutato esplicitamente; non e` ammesso fallback silenzioso verso provider, device, simulatore o QPU differente.

### 20.3 Compilation per famiglie di backend

- La conversione dalla QUBO/BQM/Ising canonica al formato di un adapter annealing conserva termini, offset e convenzioni dichiarate.
- Per un adapter gate-based, la conversione QUBO/Ising -> Hamiltoniana e il decoding delle bitstring preservano la semantica e il `node_order` canonico.
- Per un adapter gate-based, `shots`, optimizer, profondita` dell'algoritmo e opzioni di transpilation sono validati e serializzati solo quando supportati.
- Per un adapter neutral-atom, il mapping del grafo o della formulazione canonica verso geometria/sequenza fisica e` auditabile; l'impossibilita` di mapping produce failure esplicita.
- Per un adapter che richiede embedding, il mapping e i failure di embedding sono serializzati e non attivano fallback impliciti.

### 20.4 Candidate e repair

- La validazione rileva correttamente archi violati.
- Il repair elimina conflitti secondo tie-breaker deterministici.
- Un repair non puo` introdurre nuovi conflitti.
- Il repair usa nell'ordine peso, grado indotto e `item_id` come tie-breaker e registra ogni rimozione.
- Trim e augment sono verificati separatamente; l'augment non puo` aggiungere un nodo in conflitto.
- La diversita` Jaccard e` simmetrica e ha diagonale zero.
- La distanza Jaccard dell'insieme vuoto con se stesso e` zero.
- Candidate duplicate sono aggregate in modo deterministico.

### 20.5 Candidate domain e fixing

- L'unione delle candidate selezionate produce il dominio atteso.
- Il candidate domain aggregato e` trattato come dominio di ricerca e non come selezione finale: il solver classico puo` attivare un sottoinsieme fattibile di `C_effective` che non coincide con alcuna candidate MIS sorgente.
- L'aggregazione di candidate MIS non induce l'assunzione che `C_effective` sia un insieme indipendente o che il grafo sostituisca i vincoli hard del problema originale.
- Il ranking di cap e` stabile.
- Il framework fallisce esplicitamente se il dominio e` sotto il minimo richiesto.
- Gli item protetti non sono scartati silenziosamente quando eccedono il cap.
- Gli item user-mandated, safe e mandatory devono appartenere al dominio del round prima del fixing.
- Tutte le decisioni fuori dominio sono fissate nel modello residuo.
- Tutte le variabili collegate rispettano il fixing tramite adapter.
- Ogni fixing ha reason, origin e guarantee level.

### 20.6 Iterazione

- I domini sono monotoni: `V_(t+1)` deve essere sottoinsieme di `V_t`; gli elementi protetti sono applicati prima del fixing e devono appartenere a `V_t`.
- Il processo si arresta su target dimension, riduzione marginale insufficiente, limite di round e time budget.
- Il recovery con dominio maggiore ricostruisce da `P_t`, rispetta `max_recovery_attempts` e non riattiva item fissati in round precedenti.
- Gli artifact sono completi per ogni round, incluse failure.

### 20.7 Solver classico e post-check

- Il risultato classico espone status, objective, bound/gap quando disponibili e runtime.
- Un risultato post-check infeasible non puo` essere adottato.
- Il post-check verifica il fixing manifest e i vincoli originali delegati all'adapter.
- Il post-check applica e registra tolleranze di fattibilita`, integrality e ricomputazione dell'obiettivo.
- Un incumbent feasible dopo time limit puo` essere adottato solo con `partial_success` e post-check positivo.

### 20.8 Provenance della policy e valutazione esterna

- La configurazione risolta serializza `policy_id`, `policy_version`, `policy_hash`, `policy_source` e `policy_selection_status` quando sono forniti dal chiamante.
- Gli stessi metadata di policy sono riportati nel `run_manifest.json` e collegabili agli artifact del run.
- QReduce esegue la stessa policy risolta in modo riproducibile a parita` di input, seed, capability e backend effettivo.
- Il kernel registra failure, infeasibility e post-check failed nel run summary e non elimina artifact negativi.
- Le metriche tecniche obbligatorie sono disponibili anche quando il chiamante non fornisce riferimento classico, objective gap o metriche di dominio.
- QReduce non espone una funzione che scelga automaticamente una policy migliore sulla base di benchmark o risultati di run precedenti.

## 21. Criteri di accettazione della prima versione

La prima versione di QReduce e` accettata quando:

1. Esiste un adapter di dominio dimostrativo per un problema MIQP o MIQCP con variabili binarie e continue, contratti serializzabili e mapping completo item/variabili.
2. Il framework esegue il percorso completo `graph -> MIS -> candidate domain -> restricted classical solve -> post-check`.
3. Il kernel non dipende da SDK, provider, QPU, simulatore o formato di job specifico e la rappresentazione MWIS canonica e` serializzabile.
4. E` operativo almeno un backend MIS locale concreto; un adapter D-Wave Ocean, IBM Qiskit, AWS Braket, Pasqal/Pulser o altro backend compatibile puo` costituire un'implementazione, ma non una dipendenza del kernel.
5. Il backend exact e` disponibile solo per test diagnostici piccoli.
6. La configurazione valida capability, rappresentazione, parametri e modalita` di esecuzione prima della compilation e rifiuta esplicitamente adapter o capability non disponibili.
7. Il framework normalizza i risultati del backend in sample binarie canoniche e ricalcola le metriche strutturali necessarie all'audit.
8. Il framework supporta concretamente almeno uno tra SCIP e CPLEX per il residual solve; l'interfaccia e` predisposta per entrambi.
9. La riduzione applica fixing espliciti e serializza un fixing manifest.
10. Il framework distingue origine e garanzia di fixing euristico, sicuro e imposto dall'utente.
11. La configurazione standard impone la condizione certificante `lambda_edge > max_i(w_i)` e i test piccoli ne verificano la proprieta`.
12. Tutti gli artifact minimi, incluse capability, compilation ed esecuzione MIS, le versioni di schema, gli hash richiesti e il fixing manifest sono prodotti per un run single-pass.
13. Il framework serializza la provenance opzionale della policy fornita dal chiamante e le metriche tecniche necessarie per confronti esterni, senza implementare o imporre un workflow di calibrazione o selezione automatica della policy.
14. I test unitari e di integrazione elencati nelle sezioni rilevanti passano.
15. La documentazione dichiara chiaramente che il solve ottimo del problema residuo non implica ottimalita` del problema originale dopo fixing euristico o user-imposed.

## 22. Evoluzioni successive

Le evoluzioni pianificate, ma non richieste nella prima versione, includono:

- implementazione di ulteriori adapter per D-Wave Leap Hybrid e QPU, IBM Quantum/Qiskit, AWS Braket, Pasqal/Pulser e altri provider;
- portfolio e selezione automatica di backend, device e simulatori compatibili per classe di istanze;
- politiche di graph construction apprese o data-driven;
- integrazione con certificate di presolve e reduced-cost fixing;
- adaptive selection del numero di round e della dimensione di `C`;
- package opzionale o applicazione esterna per benchmark, tuning e selezione di portfolio di policy MIS per classi di istanze dichiarate;
- utility opzionali per orchestrare in parallelo run QReduce richieste da un workflow esterno di valutazione delle policy;
- supporto a decomposizione per blocchi e piu` grafi nello stesso round;
- integrazione di warm start classici tra round;
- bound globali per quantificare la perdita introdotta dalla riduzione euristica;
- fallback espliciti e auditabili tra backend, se richiesti da una futura policy;
- rollback cross-round e riattivazione controllata di item gia` fissati.