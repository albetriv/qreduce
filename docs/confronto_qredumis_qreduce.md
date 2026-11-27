# Selezione di portafoglio: qReduMIS e QReduce a confronto

**Nel paper il MIS è il problema da risolvere; in QReduce il MWIS serve a ridurre il dominio di un altro problema.** Entrambi usano un insieme indipendente per restringere la ricerca, ma «scegliere un titolo» ha conseguenze diverse nei due metodi.

## Dal grafo alla decisione

- **qReduMIS.** Ogni nodo è un titolo; un arco collega due titoli se la loro correlazione in valore assoluto supera una soglia. Anche una forte anticorrelazione può quindi impedire la selezione congiunta. Si cerca un insieme indipendente di cardinalità massima (MIS): la risposta è una lista di titoli, non la ripartizione del capitale. L'algoritmo applica riduzioni classiche esatte; quando queste si arrestano, usa le frequenze di inclusione nei campioni QAOA per scegliere un nodo da fissare. Includere quel nodo esclude i suoi vicini e può sbloccare nuove riduzioni esatte sul grafo residuo.
- **QReduce.** Il grafo rappresenta conflitti o ridondanze tra decisioni binarie. Un insieme indipendente di peso massimo (MWIS) guida la costruzione del dominio candidato. Dopo la validazione e l'eventuale correzione dei campioni, le decisioni escluse vengono fissate. Un solver classico risolve il modello originale ristretto, con il suo obiettivo e i suoi vincoli. I pesi del MWIS non sono pesi di investimento e la sua QUBO non viene sommata all'obiettivo finanziario. Il backend MWIS non deve necessariamente essere quantistico; i round di QReduce non equivalgono alla ricorsione di qReduMIS sullo stesso MIS.

**Esempio.** Se qReduMIS fissa il titolo A come incluso, A fa parte della soluzione in costruzione. Se QReduce mantiene A nel dominio candidato, il solver può ancora scartarlo, per esempio perché un altro portafoglio offre un compromesso rischio-rendimento migliore. Se invece A viene escluso, il solver non può recuperarlo in quel solve residuo.

## Garanzie e criteri di successo

Nel paper le riduzioni classiche esatte preservano l'ottimo del grafo a cui vengono applicate. Non correggono però una scelta euristica precedente che abbia escluso tutti gli ottimi originali. Le metriche pertinenti sono quindi la probabilità di trovare un MIS ottimo e il rapporto tra cardinalità ottenuta e ottima.

In QReduce, anche un MWIS ausiliario ottimo e un solve residuo esatto non garantiscono l'ottimo del modello originale. Il post-check verifica che la soluzione rispetti i fixing e i vincoli originali, non che nessuna soluzione migliore sia stata scartata. Per valutare la riduzione occorre misurare sia le variabili logiche libere eliminate sia la qualità dell'obiettivo originale rispetto a un solve senza riduzione.

## Che cosa dimostra il paper

- **Hardware Helios, Tabella III.** Sulle istanze S&P 100 e Nikkei 225, qReduMIS trova l'ottimo rispettivamente nel 40% e nel 95% delle prove; il QAOA usato da solo non lo trova nelle prove osservate. Nel caso Nikkei, i 225 titoli iniziali danno un primo grafo residuo di 78 nodi: non è un circuito da 225 qubit.
- **Emulazione, Figura 5.** Su 73 istanze, con due strati QAOA, il fattore 3,2 confronta gli esponenti stimati di crescita del tempo alla soluzione di QAOA e qReduMIS. Non è un fattore di accelerazione misurato su hardware rispetto a un solver classico.

Questi risultati riguardano il MIS sulle istanze studiate. Non misurano la qualità di un portafoglio fuori campione e non costituiscono un benchmark di QReduce.

## Da 100.000 titoli a 100: dimensione del residuo e qualità della soluzione

**Domanda:** se il solver gestisce al massimo 100 titoli, si possono escludere 99.900 candidati (il 99,9% dell'universo) conservando un portafoglio ottimo, o almeno uno sufficientemente buono?

Il paper non esclude che una riduzione così forte sia possibile su certe istanze, ma non garantisce di raggiungere una dimensione residua prefissata. Le riduzioni esatte si applicano quando la struttura del grafo lo permette, non in funzione del budget del solver. Sul Nikkei si passa da 225 titoli a un primo kernel di 78 nodi (Tabella I); sui grafi 3-regolari considerati in un altro esperimento la prima riduzione non elimina alcun nodo. I 78 nodi del Nikkei sono quindi un risultato osservato, non un obiettivo garantito.

### Due significati di «restano 100»

1. **Restano 100 decisioni aperte dopo riduzioni esatte.** Nel MIS si può ricostruire un ottimo originale da un ottimo del residuo e dalle informazioni registrate durante la riduzione. I 99.900 nodi rimossi dal problema residuo non sono necessariamente 99.900 titoli esclusi dal risultato: alcuni possono essere già stati inclusi. La garanzia vale per le riduzioni esatte, non per eventuali fixing euristici.
2. **Restano 100 titoli acquistabili dopo una selezione.** In QReduce, se il portafoglio finale deve contenere 30 titoli, restringere l'universo a 100 conserva l'ottimo originale solo se tra i titoli mantenuti c'è l'intera selezione di almeno un portafoglio ottimo e i relativi pesi restano ammissibili. Anche un solve esatto può quindi restituire un risultato peggiore: è ottimo tra i candidati rimasti, non necessariamente nell'universo iniziale. Il residuo può anche diventare inammissibile se la selezione rende impossibile soddisfare i vincoli originali.

### Limite operativo e criterio di valutazione

Nel flusso del paper, QAOA entra in gioco dopo la prima riduzione classica. Se questa lasciasse 5.000 nodi e il backend potesse gestirne solo 100, QAOA non potrebbe operare direttamente su quel kernel. Servirebbe un passaggio ulteriore; il risultato sul Nikkei non dimostra come gestire questo caso.

Per QReduce la domanda sperimentale è quindi: **dato un limite di 100 candidati, quanta qualità del modello originale rimane?** Verificare separatamente dimensione effettiva del residuo (titoli candidati e variabili logiche libere), ammissibilità rispetto ai vincoli originali e valore dell'obiettivo originale. Se il modello completo non è risolvibile all'ottimo, un confronto con una soluzione ammissibile di riferimento resta empirico; un limite valido sull'ottimo può invece quantificare la distanza massima dall'ottimo. Il paper non fornisce né una garanzia né un benchmark per il passaggio da 100.000 a 100 titoli.

## Ipotesi da verificare in QReduce

Usare la frequenza di inclusione di un titolo nei campioni come segnale per **mantenerlo selezionabile**, non per imporne l'acquisto. Per verificare se il segnale è utile, confrontare questa politica con quella attuale sulle stesse istanze, a parità di budget e di riduzione effettiva delle variabili libere. Per entrambe, registrare gli eventuali casi non ammissibili e confrontare l'obiettivo delle soluzioni ammissibili con la stessa baseline senza riduzione. Si tratta di una proposta sperimentale, non di un beneficio dimostrato.

## Fonti

- R. Yalovetzky et al., *Quantum-Informed Portfolio Selection: An End-to-End Pipeline Validated on Trapped-Ion Hardware with Real Market Data*, arXiv:2607.01037v2. Per il segnale di frequenza si veda la Figura 4; per i risultati, la Figura 5 e la Tabella III.
- QReduce: [descrizione della pipeline](../README.md) e [specifiche del MWIS ausiliario, del problema residuo e del post-check](specifications.md).