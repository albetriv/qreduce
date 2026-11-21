# Cessione di crediti deteriorati

**Stato: famiglia sperimentale, anteprima non eseguibile.** Questa pagina descrive
una proposta di esperimento su dati sintetici, non un processo della banca.

## Caso d'uso

Una banca riceve offerte indivisibili per lotti di crediti deteriorati. Le
offerte possono riguardare lotti parzialmente sovrapposti. Occorre selezionare
quelle che massimizzano il ricavo netto atteso, raggiungono un volume minimo
di crediti ceduti e non assegnano lo stesso credito a più acquirenti. Come
contesto, Intesa Sanpaolo documenta cessioni di portafogli deteriorati nel suo
[bilancio consolidato 2025](https://group.intesasanpaolo.com/content/dam/portalgroup/repository-documenti/investor-relations/bilanci-relazioni-it/2025/Bilanci_2025.pdf).

## Ruolo del kernel QReduce

È un problema di *set packing* con un vincolo aggiuntivo sul volume. Ogni
offerta è un nodo, pesato con una stima del valore netto. Due nodi sono
incompatibili se condividono almeno un credito. Il kernel usa le soluzioni
MWIS per proporre un dominio di offerte; l'adapter fissa a zero le escluse e
il MILP residuo mantiene il divieto di doppia cessione e il volume minimo.
Un'offerta poco remunerativa può essere necessaria per raggiungere il volume:
la sola selezione MWIS non garantisce un residuo fattibile. Il *set packing*
puro è già rappresentabile come MWIS: il vincolo di volume rende la demo un
test distinto del contributo della pipeline completa.

## Confronto sperimentale

Usare lo stesso modello e solver sui cataloghi completo e ridotto: misurare
fattibilità, ricavo netto, volume ceduto, offerte eliminate e tempo totale
inclusa la riduzione. Il tag [set packing di MIPLIB 2017](https://miplib.zib.de/tag_set_packing.html)
è un filtro iniziale per il benchmark strutturale, non una prova che ogni
istanza sia compatibile con l'adapter. Il riferimento interno è la
[roadmap N05](../implementation/00-implementation-overview.md#nice-to-have-benchmark-suite-pubblica-esterna).