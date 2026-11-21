# Riassicurazione passiva

**Stato: famiglia sperimentale, anteprima non eseguibile.** Questa pagina descrive
una proposta di esperimento, non un configuratore né un programma di copertura.

## Caso d'uso

Nella riassicurazione passiva, una compagnia cede a uno o più riassicuratori
parte dei rischi che ha assunto con le polizze dei propri clienti. La demo
considera un portafoglio sintetico di polizze danni e offerte in eccesso di
sinistro (*excess of loss*): ciascuna copre la parte della perdita sopra una
soglia, fino a un limite contrattuale. Per la terminologia e un esempio si
vedano il [glossario IVASS](https://www.ivass.it/pubblicazioni-e-statistiche/pubblicazioni/relazione-annuale/2023/Relazione_Annuale_2022_glossario_en.pdf?language_id=3)
e la [banca dati dei quesiti IVASS](https://www.ivass.it/operatori/intermediari/prova-idoneita/database-quesiti/DATABASE_QUESITI_PROVA_RUI.pdf).

La decisione è quali offerte acquistare per ridurre la perdita trattenuta negli
scenari più gravi, entro un budget di premi. Una prima formulazione MILP può
usare offerte indivisibili e indennizzi precalcolati per scenario, con regole
esplicite per evitare doppi recuperi, ad esempio trattando le offerte alternative
per lo stesso strato come mutuamente esclusive.

## Ruolo del kernel QReduce

Ogni offerta è un nodo. Offerte con profili di rimborso simili possono essere
collegate nel grafo per segnalare ridondanza; le incompatibilità contrattuali
effettive vanno rispettate anche nel modello residuo. Le soluzioni MWIS
propongono un insieme di candidati: l'adapter fissa a zero le offerte escluse e
il solver classico sceglie la combinazione finale. Due offerte simili ma
combinabili potrebbero essere entrambe necessarie per raggiungere la capacità
desiderata: la riduzione non garantisce di preservare la soluzione migliore.

## Confronto sperimentale

Confrontare lo stesso modello sul catalogo completo e su quello ridotto, a
parità di scenari, budget e solver. Registrare fattibilità, premi, perdite
trattenute negli scenari estremi, offerte eliminate e tempo totale inclusa la
riduzione. Il portafoglio senza riassicurazione è un riferimento per quantificare
il rischio trasferito, non per misurare l'efficacia del kernel.