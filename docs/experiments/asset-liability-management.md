# Asset Liability Management (ALM)

**Stato: famiglia sperimentale, anteprima non eseguibile.** Questa pagina descrive
una proposta di esperimento, non un configuratore né un modello operativo.

## Caso d'uso

La demo isola il rischio di tasso del portafoglio bancario (IRRBB) su un
bilancio sintetico. La decisione è quali swap di tasso attivare, tra più scadenze
e direzioni, e con quale nozionale. Nella [Relazione finanziaria annuale
2025](https://group.intesasanpaolo.com/content/dam/portalgroup/repository-documenti/investor-relations/bilanci-relazioni-it/2025/Bilanci_2025.pdf),
Intesa Sanpaolo descrive l'IRRBB attraverso il valore economico del patrimonio
(EVE) e il margine di interesse (NII). La demo usa queste due prospettive senza
replicare i dati o i modelli della banca.

Il modello proposto minimizza la perdita di EVE nello scenario peggiore, limita
il calo di NII in ciascuno scenario e impone tetti al nozionale totale e al
numero di operazioni. Con impatti per unità di nozionale precalcolati e additivi,
si può formulare come MILP: attivazioni binarie e nozionali continui.

## Ruolo del kernel QReduce

Ogni swap è un nodo. Gli archi segnalano profili d'impatto simili nei diversi
scenari, non divieti di acquisto congiunto. Il kernel usa le soluzioni MWIS
(insiemi indipendenti di peso massimo) per costruire un dominio candidato.
L'adapter fissa a zero attivazione e nozionale degli esclusi; il solver residuo
sceglie e dimensiona gli swap rimasti, mantenendo i vincoli originali. Due swap
simili possono servire entrambi se i limiti per strumento rendono insufficiente
uno solo: il fixing è euristico e può perdere qualità o fattibilità.

## Confronto sperimentale

Confrontare lo stesso modello sul catalogo completo e su quello ridotto, con lo
stesso solver, misurando fattibilità, perdita EVE peggiore, rispetto dei limiti
NII, variabili eliminate e tempo totale inclusa la riduzione. Il confronto senza
nuove coperture è un riferimento di rischio, non un test dell'effetto di QReduce.