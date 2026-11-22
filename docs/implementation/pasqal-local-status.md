# Integrazione Pasqal: stato e limiti

Il piano `PIANO_INTEGRAZIONE_PASQAL.md` descrive anche funzionalita future;
non e una dichiarazione che tutte le fasi siano completate. L'integrazione
locale usa il backend `pasqal_local`, con Pulser/QuTiP e dispositivo
`AnalogDevice`. Il gruppo opzionale Poetry `pasqal` installa Pulser con
`poetry install --with pasqal`. Non sono registrati backend Pasqal cloud o QPU
e il progetto non dichiara una dipendenza da `pasqal-cloud`.

Il mapping locale posiziona i nodi vicino ai vicini già collocati, con un
budget di tentativi, e verifica
gli archi e i non-archi con soglia 10 e margine 1 micrometro, oltre ai vincoli
del dispositivo. L'esaurimento della ricerca non dimostra che un grafo non
sia rappresentabile. La soglia geometrica e un'approssimazione, non una
garanzia di comportamento fisico. La sequenza e un'euristica MIS: i pesi MWIS
sono valutati classicamente e non sono codificati nella sequenza. Non sono
garantite fattibilita o ottimalita dei campioni.

Il backend accetta `layout_attempts` e `layout_seed` in compilazione e `shots`
in esecuzione. In assenza di `shots`, usa il numero di soluzioni richieste come
numero di misure, non come numero di campioni distinti. Nelle CLI portfolio
MV e SR `--pasqal-shots` imposta il numero di misure (default 100); il cap
dei campioni distinti coincide con gli shot e non tronca l'istogramma prima
del ranking. Il limite locale è di 12 atomi, distinto dal limite fisico del
dispositivo. Il seed del layout non
controlla il sampling. Il backend non supporta seed di sampling, timeout o
cancellazione. Nelle CLI portfolio MV e SR, una riduzione con questo backend
richiede esplicitamente `--max-end-to-end-runtime-seconds=0`: l'emulatore non
puo garantire il rispetto di una scadenza.

## Verifica locale e copertura residua

Un run CLI portfolio MV con 6 asset, 64 shot e solver residuo SCIP ha
completato anche il postcheck. Una verifica preliminare del solo backend ha
usato i grafi MV sintetici di 6, 8, 10 e 12 asset, con generazione e seed del
layout predefiniti. Con la policy `near_duplicate` predefinita i grafi erano
senza archi: tutti compilati, 400/400 shot validi senza repair o cap e divario
relativo dal peso esatto del 34,7%, 49,4%, 36,1% e 49,1% rispettivamente.
Con `correlation_only` e soglia 0,35 i grafi erano clique: nessuno è stato
compilato (`layout_search_exhausted`, non una prova di impossibilità).
Il mapper supera invece i test di regressione su C4 e K4.

Il primo confronto non prova utilità su grafi con conflitti reali. Per
chiudere la Fase 1 serve un corpus più rappresentativo, con densità intermedie
e più run stocastici: riportare separatamente rifiuti, shot validi prima del
repair, divario dall'esatto, assenza di candidati validi ed esiti con repair.

L'emulazione remota e l'uso di QPU restano fasi future; non eseguire job o
spese senza autorizzazione esplicita. I notebook restano strumenti di
presentazione e non ospitano l'implementazione del benchmark.