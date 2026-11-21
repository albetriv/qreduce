# Pianificazione degli audit interni

**Stato: famiglia sperimentale, anteprima non eseguibile.** Questa pagina descrive
una proposta di esperimento, non un piano operativo di revisione interna.

## Caso d'uso

Ogni intervento candidato richiede un certo numero di giornate e può verificare
una o più aree di rischio. Su dati sintetici, l'obiettivo è scegliere gli
interventi che coprono tutte le aree obbligatorie con il minimo impegno totale.
Il modello riprende una decisione concreta del processo di audit: Intesa Sanpaolo
descrive la propria pianificazione e riporta 320 audit completati nel 2025 nella
sezione [Attività di audit](https://group.intesasanpaolo.com/it/sostenibilita/governo-sostenibilita/integrita-nella-condotta-aziendale).

## Ruolo del kernel QReduce

È un problema di *set covering*. Ogni intervento è un nodo: gli archi tra
interventi con copertura simile indicano ridondanza, non un divieto di
selezionarli insieme. Le soluzioni MWIS propongono un dominio candidato.
L'adapter protegge gli interventi indispensabili, per esempio l'unico che copre
una certa area, e controlla prima del fixing che ogni area resti copribile.
Se la verifica fallisce, occorre ampliare il dominio o registrare il fallimento.
Il MILP residuo sceglie il piano a costo minimo tra gli interventi rimasti,
mantenendo tutti i vincoli di copertura. Conservare la fattibilità non garantisce
di conservare il piano meno costoso.

## Confronto sperimentale

Confrontare lo stesso modello e solver sui due insiemi di candidati. Registrare
aree coperte, giornate di audit, interventi eliminati, eventuali fallimenti di
fattibilità e tempo totale inclusa la riduzione. Come benchmark matematico,
distinto dalla demo aziendale, [OR-Library](https://people.brunel.ac.uk/~mastjjb/jeb/orlib/scpinfo.html)
offre istanze di *set covering* come `scp41`; si veda la
[roadmap N03](../implementation/00-implementation-overview.md#nice-to-have-benchmark-suite-pubblica-esterna).