# QReduce per Intesa Sanpaolo — obiezioni e risposte

Appunti per la presentazione. Le risposte sono formulate per essere dette a voce; distinguono ciò che è già stato verificato da ciò che va misurato nel pilot.

## Apertura: partire da un lavoro di Intesa

> «Per scegliere il primo caso d’uso siamo partiti da un vostro lavoro, con altri coautori, sullo Sharpe ratio e sulla diversificazione: il paper di Mattesi et al. Nel paper, la QUBO rappresenta il problema finanziario, i pesi sono codificati in bit e la diversificazione settoriale entra nell’obiettivo. Con QReduce usiamo l’hardware quantistico per un compito diverso: generare candidati per restringere l’universo dei titoli. Il solver classico calcola poi i pesi continui con i vincoli del modello. Vogliamo misurare quando questa divisione del lavoro porta a una soluzione accettabile prima, o a una soluzione migliore entro la stessa scadenza.»

`portfolio-sr` è **una variante ispirata al paper, non una replica**. L’impiego della QPU nella riduzione è lo scopo del progetto; i percorsi classici servono a misurarne il contributo.

## Obiezioni e risposte

### 1. «Abbiamo già QRPO. Perché dovremmo fare un altro progetto?»

> «Non proporrei un secondo progetto generico sul portafoglio quantistico. QReduce testa un’ipotesi circoscritta: usare la QPU per decidere quali alternative lasciare al solver, senza trasferire alla QPU l’intera formulazione finanziaria. Se QRPO esplora già un’idea simile, confrontiamoci sullo stesso caso: non ha senso duplicare ciò che già funziona meglio.»

Il paper è l’ispirazione dichiarata di `portfolio-sr`. QRPO è un’iniziativa distinta nel contesto della discussione: non presumere di conoscerne formulazione, benchmark o risultati interni.

### 2. «Non avete cambiato il problema rispetto al paper?»

> «Sì. Nel paper la diversificazione è una preferenza da bilanciare con lo Sharpe; nella demo QReduce, quando configurati, i limiti settoriali sono vincoli di ammissibilità. Anche la rappresentazione dei pesi è diversa. Non confronterei i valori delle due funzioni obiettivo come se fossero equivalenti. Concorderei prima il mandato, poi valuterei i portafogli con le stesse metriche, sugli stessi input, verificando gli stessi vincoli. Se una formulazione richiede un’approssimazione, la rendiamo esplicita.»

### 3. «Lo Sharpe si ottimizza già classicamente. Perché usare una QPU?»

> «Sul caso continuo semplice l’obiezione è corretta: il paper stesso riconosce che lo Sharpe, da solo, può essere ottimizzato efficientemente con solver classici. Lo userei come controllo. Per il pilot sceglierei una variante con una decisione discreta rilevante, ad esempio un limite sul numero di posizioni, e un collo di bottiglia già misurato. Non basta aggiungere cardinalità: è il comportamento del solver sul problema completo a giustificare il test.»

### 4. «Perché non usare direttamente `LeapHybridCQMSampler`?»

> «Sono due modi di integrare il quantistico. Con Leap sottoponiamo il modello CQM compatibile al servizio ibrido D-Wave. Con QReduce scegliamo esplicitamente cosa affidare alla QPU: generare candidati per un problema ausiliario su grafo. Possiamo ispezionare quali decisioni sono state fissate; il solve finale resta classico. Dove Leap accetta il modello e il cloud è autorizzato, lo includerei come benchmark end-to-end. Non abbiamo un confronto diretto documentato che dimostri quale convenga sul vostro caso.»

Da verificare sul solver Leap accessibile per account e regione: `maximum_number_of_quadratic_variables_real`. Il supporto delle variabili reali non implica il supporto dei termini quadratici che le coinvolgono. La documentazione mostra un esempio con valore zero. Se il solver effettivo non accetta la varianza quadratica nei pesi continui, dichiarare il confronto diretto non applicabile oppure documentare la riformulazione e valutarne l’output sul mandato originale. Il backend QReduce `dwave_simulated_annealing` è simulazione locale, non Leap né hardware.

### 5. «Perché non lasciare fare tutto al nostro solver e al suo presolve?»

> «Il vostro solver sul modello completo, ben configurato, è il primo riferimento. QReduce non è semplicemente un altro presolve: può fissare scelte in modo euristico e quindi escludere soluzioni valide. Questo rischio ha senso solo se il beneficio è misurabile. Se il vostro solver trova già una soluzione adeguata entro la scadenza, non partirei da quell’istanza.»

### 6. «Come isolate il contributo dell’hardware, e non del grafo o del repair?»

> «Usiamo lo stesso grafo, le stesse regole per selezionare e correggere i candidati e lo stesso solver residuo. Cambiamo il backend: QPU reale contro una riduzione classica competitiva, non solo contro il greedy più semplice. Valutiamo il risultato finale e il tempo totale, non soltanto il punteggio sul grafo. Separiamo i run che hanno davvero usato hardware da quelli risolti dal presolve.»

Il confronto con il solver sul modello completo misura il valore della pipeline; quello a parità di pipeline misura il contributo della QPU sul test. Nessuno dei due, da solo, dimostra un vantaggio quantistico generale.

### 7. «Come sapete che non avete escluso i titoli più utili alla diversificazione?»

> «Non lo sappiamo a priori. Nella demo, lo Sharpe individuale pesa i titoli e la correlazione positiva è uno dei segnali usati per costruire il grafo. Nessuno dei due misura da solo il contributo marginale al portafoglio. Due titoli simili possono servire entrambi, per esempio se c’è un tetto per posizione. Possiamo tenere libere le scelte dichiarate obbligatorie e testare la sensibilità a soglie e cap, ma resta necessario misurare la qualità persa rispetto al modello completo.»

### 8. «Se il post-check passa, il risultato è ottimo? E se il residuo è infattibile?»

> «Il post-check verifica i vincoli sul modello originale; non vede le allocazioni migliori che abbiamo escluso. Un ottimo sul residuo non certifica l’ottimo globale, e un residuo infattibile non dimostra che lo sia il problema originale. In alcuni casi configurati possiamo ampliare il dominio nello stesso round; non c’è rollback automatico dei round precedenti né fallback silenzioso. Nel pilot manterrei indipendente il processo corrente della banca.»

Usare un ottimo o un bound valido sul problema completo dove disponibile; altrimenti parlare di scostamento dalla migliore soluzione nota, non di gap certificato.

### 9. «Che cosa avete già dimostrato, e a quale scala?»

> «Su Pasqal è documentato un pilota con invio e recupero di 100 shot su hardware reale, con layout custom. È evidenza del funzionamento di quel flusso, non di prestazioni end-to-end, validità del mapping calibrato o scala produttiva. Per la scala contano i nodi del grafo, la sua densità e la possibilità di rappresentarlo sul dispositivo. Misurerei anche quante istanze non compilano, non restituiscono candidati utili o non rientrano nella scadenza.»

Due esempi separati, entrambi su portfolio media-varianza, **non** prove hardware su `portfolio-sr`:

- **12 → 4 asset candidati:** stesso obiettivo della baseline nel run dimostrativo. Anche il greedy ottiene lo stesso risultato; l’emulatore locale è più lento end-to-end.
- **100 → 38 binarie libere:** soluzioni fattibili in entrambi i percorsi, ma obiettivo peggiore e circa 42,3 s contro 5,7 s nella baseline. Il backend era simulated annealing locale, non una QPU. Sono osservazioni su una singola istanza, non stime di performance.

### 10. «Risk e Audit riescono a ricostruire la decisione?»

> «Possiamo mostrare la policy di riduzione, quali scelte sono state lasciate libere o fissate, il backend usato e il controllo finale. Per il pilot concorderei una scheda per run con versione del modello, configurazione, motivi delle esclusioni e confronto con la baseline. È tracciabilità, non una certificazione di ottimalità o un sostituto della vostra validazione.»

### 11. «Che cosa esce dal perimetro quando usate la QPU?»

> «Mostrerei il payload effettivo del flusso proposto e i metadati e log associati. Anche senza nomi o identificativi, parametri, coefficienti e struttura possono rivelare informazioni. Il primo test su hardware può usare istanze sintetiche; prima di inviare input interni serve approvazione sul dispositivo, sul servizio, sui dati trasmessi e sulle condizioni di conservazione e accesso.»

### 12. «Chi risponde se il job non torna in tempo, e quanto costa?»

> «Il pilot lavora in parallelo e non blocca il processo della banca. Concordiamo cap di costo, criteri di timeout, gestione dei job incerti e chi è responsabile del run. Misuriamo il costo per ottenere una soluzione accettabile entro la scadenza, non il costo per shot. Contiamo anche coda, job rifiutati e tentativi senza esito.»

### 13. «Cosa ci rimane se l’hardware non aggiunge valore?»

> «Un protocollo ripetibile, risultati per istanza e un’indicazione di dove si perde il beneficio: costruzione del grafo, mapping, accesso alla QPU o solve finale. Se la riduzione aiuta ma l’hardware non migliora il risultato, lo diciamo esplicitamente. E se serve un altro caso d’uso, scegliamolo con l’owner del processo: ALM e cessione di crediti deteriorati sono oggi proposte sperimentali, non moduli operativi pronti.»

### 14. «Perché non usare Qiskit ADMM per separare le binarie dai pesi?»

> «Con ADMM il blocco binario propone quali titoli selezionare e il solve continuo dà un riscontro: al giro successivo le scelte binarie possono cambiare. Con QReduce la QPU propone invece quali titoli lasciare disponibili. Il solver classico sceglie, tra quelli rimasti, quali comprare e con quali pesi. La differenza non è se ci sono più round, ma che cosa rappresenta il risultato della QPU: una proposta di selezione in ADMM, un insieme di candidati alla riduzione in QReduce.»

## Scheda tecnica: Leap CQM, Qiskit ADMM e QReduce

| Approccio | Problemi affrontati | Ruolo della QPU | Euristica e garanzie |
| --- | --- | --- | --- |
| **D-Wave `LeapHybridCQMSampler`** | Modelli quadratici vincolati (CQM) con variabili binarie, intere e reali, nei limiti del solver. I vincoli si dichiarano nel modello. | Si invia il modello completo a Leap. Il servizio combina metodi classici e quantum annealing; non si specifica quale blocco affidare alla QPU. | Ricerca ibrida euristica: non certifica l’ottimo globale né garantisce un campione fattibile entro il budget. |
| **Qiskit `ADMMOptimizer`** | Problemi misti con blocchi binario e continuo separabili nell’obiettivo e collegabili dai vincoli; la formulazione di riferimento assume un sottoproblema continuo convesso. Le intere possono essere codificate in binario. | Alterna una QUBO per il blocco binario e un solve classico per il continuo. Il blocco binario può usare QAOA su hardware a circuiti, un simulatore o un solver classico (il default è classico). | La decomposizione è euristica anche se la QUBO viene risolta esattamente a ogni passo. Il risultato va verificato sul modello originale. |
| **QReduce** | Nel perimetro attuale, MILP o MIQP con vincoli lineari e decisioni binarie da restringere. | La QPU genera candidati per un problema ausiliario su grafo (MWIS). Il solver residuo ottimizza sul dominio ridotto, con obiettivo e vincoli originali. | Il fixing è euristico. Il post-check verifica la fattibilità della soluzione restituita, ma un ottimo sul residuo non certifica l’ottimo globale. |

**Esempio `portfolio-sr` con cardinalità.** Le binarie indicano quali titoli selezionare; i pesi sono continui. Il termine di varianza è quadratico nei pesi e il collegamento con le binarie avviene nei vincoli: questa struttura è in linea di principio adatta ad ADMM, senza discretizzare i pesi. Per Leap va prima verificato il supporto dei termini quadratici reali, come spiegato sopra. Un confronto tra i tre approcci misura il valore delle strategie complete, non soltanto quello delle rispettive QPU.

### QUBO e QAOA: il problema e un modo per risolverlo

- **QUBO** (*Quadratic Unconstrained Binary Optimization*) è un **formato di problema**: una funzione quadratica di variabili binarie da minimizzare, senza vincoli espliciti oltre al dominio binario. Ad esempio, può premiare singoli titoli e penalizzare certe coppie. Se si parte da un problema con altri vincoli, questi possono essere incorporati nell’obiettivo tramite penalità, dove appropriato.
- **QAOA** (*Quantum Approximate Optimization Algorithm*) è un **algoritmo ibrido**: un circuito quantistico parametrico genera candidati e un ottimizzatore classico aggiorna i parametri. Può essere usato per affrontare una QUBO, ma la stessa QUBO può essere affrontata con metodi classici o con il quantum annealing. QAOA e quantum annealing non sono la stessa tecnica.

**In una frase:** QUBO descrive *che cosa* ottimizzare; QAOA è uno dei modi per cercare una soluzione. Nel confronto qui sopra, la QUBO di ADMM aggiorna le decisioni binarie del modello, mentre la QUBO di QReduce serve a restringere il dominio.

## Pilot da proporre

1. **Scegliere un caso e concordare le soglie.** Chiedere a Intesa una famiglia di istanze in cui il metodo corrente fatica a raggiungere la qualità richiesta entro la scadenza. Definire prima vincoli, tolleranza sulla qualità, tempo e costo massimi. Calibrare su un insieme e congelare la policy prima delle istanze di verifica.
2. **Eseguire tre percorsi principali:** solver classico sul modello completo; QReduce con riduzione classica e lo stesso solver residuo; QReduce con riduzione su QPU reale e lo stesso solver residuo. Come confronti aggiuntivi, considerare il metodo del paper o di Intesa se confrontabile, Leap se il modello è compatibile e il servizio autorizzato, e Qiskit ADMM se il modello si presta alla decomposizione. Per ADMM, distinguere le prove classiche, simulate e su hardware reale; quando osservabile, riportare anche il numero di chiamate alla QPU.
3. **Valutare tutti sul mandato originale.** Riportare fattibilità e scostamenti con metriche comuni, tempo e costo fino alla soluzione verificata, esiti di mapping, timeout e run senza soluzione utilizzabile. Includere costruzione del grafo, conversioni, coda ed eventuale recupero; il budget del solver non sostituisce il tempo end-to-end. Ripetere i run stocastici.
4. **Decidere sulla base dei risultati.** Proseguire se il beneficio della QPU rispetto alla riduzione classica è misurabile e si ripete sulle istanze di verifica. Se ne beneficia solo la pipeline classica, presentarlo come risultato sulla riduzione, non sull’hardware quantistico.

**Domanda di chiusura:** «Tra le istanze che avete già studiato, ce n’è una in cui qualità e tempo sono ancora in tensione? Possiamo usare il vostro mandato per misurare se affidare alla QPU la riduzione del dominio aggiunge valore?»

## Riferimenti per la preparazione

- Mattesi et al., *Diversifying Investments and Maximizing Sharpe Ratio: A Novel Quadratic Unconstrained Binary Optimization Formulation*, *Quantum Reports*, 2024: [preprint arXiv:2302.12291](https://arxiv.org/abs/2302.12291), [articolo pubblicato](https://doi.org/10.3390/quantum6020018).
- Intesa Sanpaolo Innovation Center: [comunicazione pubblica che menziona il progetto QRPO](https://www.intesasanpaoloinnovationcenter.com/it/news-ed-eventi/news/2026/02/what-if-quantum-computing/).
- D-Wave: [proprietà del solver CQM](https://docs.dwavequantum.com/en/latest/industrial_optimization/solver_cqm_properties.html), [API `sample_cqm`](https://docs.dwavequantum.com/en/latest/ocean/api_ref_system/generated/dwave.system.samplers.LeapHybridCQMSampler.sample_cqm.html).
- Qiskit Optimization: [API `ADMMOptimizer`](https://qiskit-community.github.io/qiskit-optimization/stubs/qiskit_optimization.algorithms.ADMMOptimizer.html) e [codice sorgente](https://qiskit-community.github.io/qiskit-optimization/_modules/qiskit_optimization/algorithms/admm_optimizer.html); IBM Quantum: [tutorial su QAOA](https://quantum.cloud.ibm.com/docs/en/tutorials/quantum-approximate-optimization-algorithm).
- Repository: confronto metodologico in `src/qreduce/experiments/portfolio_sr/README.md`; pilota hardware in `README.md`; dimostrazione a 12 asset in `docs/experiments/portfolio.md`; caso 100 → 38 in `docs/implementation/uix-portfolio-comparison-findings.md`.