# Piano di implementazione: esperimento Capacitated Facility Location

## Stato e obiettivo

Data del piano: 15 novembre 2026.

Questo documento registra il piano di implementazione del nuovo esperimento.
Non attesta funzionalita gia implementate e non sostituisce le specifiche
normative del progetto. L'approvazione del piano autorizza la pianificazione
del solo esperimento descritto, non l'intera iniziativa N03.

Il nuovo esperimento sara Capacitated Facility Location con domanda
frazionabile, basato sulle istanze pubbliche OR-Library.

L'interpretazione applicativa sara selezione di sedi di servizio e allocazione
della domanda territoriale. Questa interpretazione restera separata dai dati:
i benchmark non saranno presentati come dati di Intesa Sanpaolo, ne i risultati
come raccomandazioni operative per la banca.

L'esperimento dovra consentire di confrontare:

1. baseline classica sul problema completo;
2. riduzione QReduce single-pass;
3. riduzione multi-round, con recovery esplicito;
4. controllo con tutte le sedi mantenute.

Il kernel non verra esteso: parser, modello, policy di grafo, metriche e analisi
resteranno nella nuova famiglia di esperimenti.

## 1. Evidenze raccolte e decisioni preliminari

Sono stati ispezionati i contratti dell'adapter, il runner condiviso, la
pipeline unificata, il portfolio, gli artifact e le convenzioni dei test.

L'ambiente locale verificato dispone di Python 3.12.10, Poetry e dei binding di
SCIP, CPLEX e D-Wave simulated annealing. La presenza dei binding non certifica
l'eseguibilita dei solver o la disponibilita delle licenze: saranno verificate
durante gli smoke test.

Precisazioni rispetto alla proposta iniziale:

- La pagina ufficiale OR-Library dichiara l'applicazione della licenza MIT al
  materiale disponibile. Si pianifica quindi l'inclusione di un sottoinsieme
  di dati, conservando attribuzione e testo della licenza. Prima della copia
  verificare nuovamente i termini applicabili ai file acquisiti.
- Il percorso unificato corrente permette di configurare il recovery anche
  con un solo round. Distinguere single-pass senza recovery e single-pass con
  recovery, senza introdurre un nuovo meccanismo.

### Decisioni per la prima versione

| Aspetto | Decisione |
|---|---|
| Famiglia | Capacitated facility location |
| Assegnazioni | Continue e frazionabili |
| Collegamenti | Ogni cliente puo essere servito da ogni sede |
| Obiettivo | Costi fissi piu costi di allocazione |
| Item riducibile | Sede candidata |
| Solver classico predefinito | SCIP |
| Backend MIS predefinito | `local_greedy` |
| Backend opzionali | CPLEX e D-Wave simulated annealing |
| Download automatici | Nessuno durante test o run |
| Dipendenze nuove | Nessuna prevista |
| Garanzia dei fixing | Euristica, non certificata |
| Ottimalita originale | Non dedotta dall'ottimalita del residuo |

Restano fuori dalla prima versione:

- assegnazioni indivisibili;
- distanze massime e collegamenti vietati;
- vincoli geografici;
- numero obbligatorio di sedi;
- dati bancari reali.

## 2. Dataset e riproducibilita

### 2.1 Sottoinsieme iniziale

Includere `cap41`-`cap44` come primo gruppo riproducibile, mantenendo il parser
utilizzabile per gli altri file numerici dello stesso formato.

La documentazione ufficiale identifica questo gruppo come problem set IV e
descrive capacita, costi fissi, domanda e costi di assegnazione. I file `capa`,
`capb` e `capc` richiedono sostituzioni di capacita definite separatamente:
saranno rifiutati esplicitamente nella prima versione.

`cap41` sara l'istanza di accettazione iniziale: contiene 16 sedi e 50 clienti;
il riferimento pubblicato e 1040444.375. La raccolta avverte che i valori
possono presentare piccoli scostamenti dovuti agli arrotondamenti.

### 2.2 File previsti

```text
D:\DATADIR\Programmazione\python\qreduce\data\benchmarks\or_library\capacitated_facility_location\
```

La directory conterra:

- istanze originali, senza riscrittura dei numeri;
- manifest delle istanze;
- riferimenti ottimi del sottoinsieme;
- attribuzione e licenza MIT.

Per ogni istanza registrare:

- identificatore e famiglia;
- fonte e data di acquisizione;
- SHA-256 dei byte originali;
- dimensioni dichiarate;
- versione del parser;
- riferimento ottimo e relativa fonte;
- precisione del riferimento pubblicato.

Il riconoscimento dell'istanza non dipendera dal solo nome del file: un file
modificato chiamato `cap41` non ereditera automaticamente il suo valore ottimo.

### 2.3 Criterio di completamento

Le istanze incluse devono essere verificabili tramite checksum e caricabili
senza rete. La redistribuzione deve conservare l'avviso di licenza richiesto
dalla fonte.

## 3. Modello di dominio e parser

### 3.1 Struttura Python

Nuovo package:

```text
D:\DATADIR\Programmazione\python\qreduce\src\qreduce\experiments\facility_location\
```

| Modulo previsto | Responsabilita |
|---|---|
| `models.py` | Contratti immutabili, mapping e problema residuo |
| `datasets.py` | Parser OR-Library, manifest e riferimenti |
| `formulation.py` | Costruzione del modello classico |
| `graph_policy.py` | Score e archi euristici |
| `adapter.py` | Implementazione del contratto QReduce |
| `postcheck.py` | Validazione aritmetica indipendente |
| `inputs.py` | Configurazioni e preset |
| `run.py` | Entry point Python e CLI |
| `benchmark.py` | Esecuzione controllata dei confronti |
| `analysis.py` | Lettura artifact, tabelle e aggregazioni |

Non copiare automaticamente la struttura a tre entry point del portfolio:
una CLI unica potra selezionare il numero di round.

### 3.2 Contratti principali

Prevedere:

- `FacilityLocationProblem`;
- `FacilityLocationVariableMapping`;
- `FacilityLocationResidualProblem`;
- `FacilityLocationGraphPolicy`;
- metadata separati per provenienza e riferimento pubblico.

Validazioni:

- identificatori univoci e ordine stabile;
- dimensioni coerenti;
- valori finiti;
- domanda e capacita strettamente positive nel perimetro iniziale;
- costi non negativi, inclusi costi nulli;
- nessuna matrice incompleta.

### 3.3 Parser

Il parser lavorera sui token separati da whitespace, non sul numero di righe.

Il formato ufficiale riporta i costi cliente per cliente e li definisce come
costo di allocare tutta la domanda del cliente alla sede. Preservare questa
semantica.

Rilevare:

- intestazioni non valide;
- file troncati;
- token aggiuntivi inattesi;
- valori non numerici o non finiti;
- placeholder di capacita non supportati;
- incongruenze fra dimensioni e contenuto.

Errore da prevenire con un test dedicato: moltiplicare nuovamente il costo per
la domanda.

## 4. Formulazione matematica

Variabili e dati:

- `delta_i`: sede aperta;
- `x_ij`: frazione della domanda del cliente assegnata alla sede;
- `f_i`: costo fisso;
- `c_ij`: costo di assegnazione dell'intera domanda;
- `d_j`: domanda;
- `u_i`: capacita.

```text
minimize:
    sum_i f_i * delta_i
    + sum_i,j c_ij * x_ij

subject to:
    sum_i x_ij = 1                         for each customer j

    sum_j d_j * x_ij <= u_i * delta_i       for each facility i

    x_ij <= delta_i                        for each pair i,j

    0 <= x_ij <= 1
    delta_i in {0, 1}
```

Compilare il modello nel `ClassicalOptimizationModel` esistente, senza oggetti
SCIP o CPLEX nel dominio.

### Strategia iniziale di fixing

Per mantenere il comportamento vicino al portfolio:

- conservare le variabili originali nel modello;
- applicare fixing espliciti alle variabili escluse;
- contare separatamente le variabili logiche libere.

Non dichiarare una riduzione fisica della matrice prima del presolve.
L'eliminazione strutturale delle variabili potra essere valutata in seguito,
separatamente.

### Criteri di completamento

- Una piccola istanza artificiale ha soluzione verificata manualmente.
- La baseline di `cap41` e coerente con il riferimento, entro tolleranze
  documentate.
- Il modello completo e il residuo senza esclusioni sono equivalenti.
- L'assegnazione frazionabile e verificata da un caso che non ammette
  assegnazione indivisibile.

## 5. Policy MWIS iniziale

Questa e la parte sperimentale: gli archi esprimeranno ridondanza, non
incompatibilita hard.

### 5.1 Score dei nodi

Implementare una policy semplice, deterministica e versionata.

Per ogni sede calcolare un costo indicativo di servizio usando la
distribuzione della domanda e la capacita utile:

```text
D = sum_j d_j

mean_unit_cost_i = sum_j c_ij / D
effective_capacity_i = min(u_i, D)

proxy_cost_i =
    f_i + effective_capacity_i * mean_unit_cost_i
```

Lo score combinera capacita utile e convenienza del costo, entrambe
normalizzate sull'istanza originale:

```text
capacity_score_i =
    effective_capacity_i / max_k(effective_capacity_k)

affordability_score_i =
    1 - proxy_cost_i / max_k(proxy_cost_k)

w_i =
    epsilon
    + (1 - epsilon) * (
        alpha * capacity_score_i
        + (1 - alpha) * affordability_score_i
      )
```

Definire esplicitamente il caso di costi tutti nulli. Valori iniziali proposti:

- `alpha = 0.5`;
- `epsilon = 0.01`;
- pesi nell'intervallo positivo fino a 1;
- `lambda_edge = 2.0`.

Lo score non e un bound ne una stima certificata del valore marginale della
sede.

### 5.2 Archi di ridondanza

Per ciascuna sede costruire l'insieme dei clienti piu convenienti da servire,
ordinati per costo unitario, fino a una quota di domanda parametrizzata.

Due sedi saranno collegate quando:

1. la sovrapposizione dei profili supera una soglia;
2. le loro capacita sono sufficientemente simili.

Parametri iniziali da fissare nel documento dedicato:

- quota di domanda del profilo;
- soglia di sovrapposizione;
- massima differenza relativa di capacita.

Il profilo usera solo costi e domanda: non inventare coordinate o distanze
geografiche assenti dai dati.

### 5.3 Stabilita fra round

Score e profili saranno calcolati rispetto all'istanza originale; nei round
successivi usare il sottografo indotto dalle sedi ancora disponibili.

Questo evita cambiamenti impliciti della policy dovuti alla rinormalizzazione
dopo ogni esclusione.

### Criterio di completamento

Stessa istanza e stessa policy devono produrre stessi pesi, archi e tie-break.
Il caso senza archi sara valido e non verra corretto per forzare una riduzione.

## 6. Adapter, fattibilita e fixing

L'adapter implementera tutti i metodi richiesti, compresi conteggi logici,
provenance dell'input e metriche di dominio.

### 6.1 Precheck di fattibilita

Nel perimetro scelto, domanda frazionabile, collegamenti completi e nessun
limite al numero di aperture, la capacita totale disponibile consente un
controllo completo di fattibilita del dominio, entro tolleranza:

```text
sum_i_in_C u_i >= sum_j d_j
```

La sufficienza sara motivata nel documento e verificata con test costruttivi.

Il numero minimo di sedi sara calcolato accumulando le capacita in ordine
decrescente. Non usare il solo numero di sedi per validare un dominio: sedi
diverse possono avere capacita diverse.

### 6.2 Protezioni

Dichiarare obbligatorie le sedi la cui esclusione rende insufficiente la
capacita:

```text
sum_k u_k - u_i < total_demand
```

Ripetere la verifica sul dominio disponibile a ogni round.

Le protezioni rappresenteranno disponibilita nel residuo, non apertura
forzata.

### 6.3 Fixing collegati

Per ogni sede esclusa:

```text
delta_i = 0
x_ij = 0       for every customer j
```

Ogni entry registrera:

- origine `mis_heuristic`;
- garanzia `heuristic`;
- motivo;
- versione della policy;
- provenance delle candidate e del round.

Nei round successivi i fixing saranno cumulativi, senza duplicazioni o
riattivazioni implicite.

### 6.4 Recovery

Usare esclusivamente il recovery esistente:

- espansione dal dominio di inizio round;
- limite esplicito di tentativi;
- rispetto del cap;
- conservazione dei tentativi falliti;
- nessun rollback cross-round.

Un cap incompatibile con la capacita richiesta produrra un esito esplicito,
non un aumento silenzioso del limite.

## 7. Post-check e metriche

Il post-check ricalcolera indipendentemente:

1. presenza e finitezza delle variabili;
2. dominio delle binarie;
3. limiti delle allocazioni;
4. soddisfacimento della domanda;
5. capacita delle sedi;
6. linking apertura-allocazione;
7. rispetto dei fixing;
8. obiettivo e coerenza con quello del solver.

I confronti useranno le tolleranze configurate, senza arrotondare
preventivamente la soluzione.

### Metriche di dominio

- Sedi effettivamente aperte.
- Costo fisso e costo di allocazione.
- Capacita aperta e utilizzazione.
- Clienti serviti da piu sedi.
- Massimo residuo dei vincoli.
- Scostamento dal riferimento pubblico, se riconosciuto.

Tenere distinte:

- gap dichiarato dal solver sul residuo;
- scostamento dal riferimento originale;
- differenza rispetto alla baseline sperimentale.

Un riferimento pubblico non verra inserito automaticamente nei campi dei bound
certificati della pipeline.

## 8. Runner, CLI e artifact

Entry point previsto:

```text
D:\DATADIR\Programmazione\python\qreduce\src\qreduce\experiments\facility_location\run.py
```

Opzioni principali:

- file dell'istanza;
- run ID e output root;
- numero massimo di round;
- solver classico e backend MIS;
- seed e budget;
- cap e soglia minima di riduzione;
- parametri della policy;
- recovery;
- export del modello.

Output predefinito:

```text
D:\DATADIR\Programmazione\python\qreduce\outputs\facility_location\{run_id}\
```

Riutilizzare lo schema artifact corrente. Nei metadata aggiungere provenienza,
checksum, formulazione, policy e riferimento pubblico.

Riutilizzare i tempi gia disponibili; misurare il tempo di costruzione del
grafo nel livello sperimentale. Distinguere:

- caricamento e parsing;
- pipeline end-to-end;
- persistenza degli artifact.

I fallimenti normalizzati della pipeline saranno persistiti dal runner. Gli
errori precedenti alla pipeline, come parsing fallito, saranno registrati dal
benchmark come errori di preparazione, senza inventare un risultato QReduce.

## 9. Protocollo di benchmark

### Matrice iniziale

| Percorso | Scopo |
|---|---|
| Classical-only | Riferimento operativo |
| Tutte le sedi protette | Controllo di equivalenza |
| Single-pass senza recovery | Effetto diretto della policy |
| Single-pass con recovery | Recupero di capacita |
| Multi-round con recovery | Monotonicita e fixing cumulativi |
| Simulated annealing opzionale | Sensibilita al backend MIS |

### Regole di confronto

- Stessa istanza e stesso solver classico.
- Stesso numero di thread.
- Budget end-to-end confrontabile.
- Costo di tutti i round e tentativi incluso.
- Policy predefinita prima di leggere i risultati.
- Seed espliciti.
- Nessuna selezione del solo risultato migliore.

Una piccola sensitivity analysis della policy sara etichettata come
esplorativa, non come conferma indipendente.

### Indicatori principali

- Riduzione logica delle binarie e delle continue.
- Qualita della soluzione.
- Tempo end-to-end.
- Tasso di successo e recovery.
- Failure e post-check failed.

Lo speedup sara riportato solo per confronti validi, indicando sempre la
qualita ottenuta. Non confrontare il solo ultimo solve residuo contro l'intero
tempo della baseline.

## 10. Piano dei test

Directory prevista:

```text
D:\DATADIR\Programmazione\python\qreduce\tests\experiments\facility_location\
```

### Test unitari senza solver

- Parsing e orientamento dei costi.
- Costi nulli, file troncati e token inattesi.
- Immutabilita e validazione.
- Score, archi e determinismo.
- Precheck di capacita.
- Sedi indispensabili.
- Fixing completi e cumulativi.
- Conteggi logici.
- Post-check con violazioni isolate.

### Test di pipeline con backend controllati

- Baseline.
- Nessuna riduzione.
- Riduzione valida.
- Dominio insufficiente.
- Recovery riuscito ed esaurito.
- Timeout con e senza incumbent.
- Post-check failed.
- Dipendenza indisponibile.
- Provenance e artifact.

### Test live opzionali

- SCIP sulle istanze artificiali.
- SCIP su `cap41`.
- Confronto con CPLEX quando utilizzabile.
- Simulated annealing con seed dichiarato.

I test ordinari non richiederanno rete. La riproduzione del valore pubblico
sara un test di integrazione numerico, non un test sui tempi.

## 11. Documentazione e notebook

Documento dedicato da creare:

```text
D:\DATADIR\Programmazione\python\qreduce\docs\implementation\facility-location-experiment.md
```

Descrivera perimetro, dati, licenza, formulazione, policy, failure e criteri di
accettazione.

Artefatti da allineare:

```text
D:\DATADIR\Programmazione\python\qreduce\docs\specifications.md
D:\DATADIR\Programmazione\python\qreduce\docs\implementation\00-implementation-overview.md
D:\DATADIR\Programmazione\python\qreduce\docs\implementation\experiment-organization.md
D:\DATADIR\Programmazione\python\qreduce\README.md
```

La promozione riguardera solo questo esperimento, non tutta N03.

Notebook previsto:

```text
D:\DATADIR\Programmazione\python\qreduce\notebooks\experiments\facility_location\001_or_library_comparison.ipynb
```

Leggera artifact persistiti e mostrera costi, capacita, riduzione, tempi e
fallimenti. Nessun solve o business logic nelle celle.

UI e altre interfacce non verranno estese implicitamente.

## 12. Sequenza esecutiva e gate

| Fase | Deliverable | Condizione per procedere |
|---|---|---|
| 1 | Specifica dell'esperimento e dati con licenza | Perimetro e manifest definiti |
| 2 | Parser, contratti e formulazione | Test unitari e baseline corretti |
| 3 | Post-check indipendente | Violazioni rilevate e obiettivo coerente |
| 4 | Grafo e adapter | Fixing e capacita verificati |
| 5 | Runner e CLI | Run e artifact ricaricabili |
| 6 | Recovery e multi-round | Monotonicita e tentativi verificati |
| 7 | Benchmark e notebook | Confronti riproducibili |
| 8 | Regressione e documentazione | Suite, lint e packaging verificati |

Gate principale: non avviare la valutazione della riduzione finche la baseline
non riproduce correttamente la semantica del benchmark.

## 13. Criteri finali di accettazione

L'esperimento sara completato quando:

- dataset e riferimenti hanno provenienza verificabile;
- la baseline di `cap41` e coerente con il riferimento;
- il controllo senza esclusioni e equivalente alla baseline;
- i fixing coprono aperture e allocazioni;
- ogni soluzione adottata supera il post-check originale;
- recovery e multi-round rispettano i contratti esistenti;
- artifact e notebook funzionano senza rieseguire il solve;
- il portfolio non presenta regressioni;
- l'esperimento resta escluso dal wheel;
- risultati negativi e limiti sono documentati.

Non sara richiesto dimostrare uno speedup: l'assenza di beneficio su queste
istanze sara comunque un risultato valido.

## 14. Fonti esterne di riferimento

Riferimenti ufficiali da conservare nella provenance dei dati acquisiti:

```text
OR-Library: licenza e attribuzione
https://people.brunel.ac.uk/~mastjjb/jeb/orlib/legal.html

OR-Library: formato e raccolta capacitated warehouse location
https://people.brunel.ac.uk/~mastjjb/jeb/orlib/capinfo.html

OR-Library: istanza cap41
https://people.brunel.ac.uk/~mastjjb/jeb/orlib/files/cap41.txt

OR-Library: riferimenti ottimi
https://people.brunel.ac.uk/~mastjjb/jeb/orlib/files/capopt.txt
```

## 15. Stato della verifica alla redazione

Alla redazione del piano sono state svolte ispezioni del repository e
dell'ambiente. Non e stata implementata la famiglia facility location e non
sono stati eseguiti test del nuovo esperimento.

Questo file e un deliverable documentale richiesto nella root del workspace,
non un file temporaneo strumentale. Eventuali file temporanei dell'agente
durante l'implementazione dovranno restare confinati nella directory dedicata:

```text
D:\DATADIR\Programmazione\python\qreduce\.cline-tmp\
```