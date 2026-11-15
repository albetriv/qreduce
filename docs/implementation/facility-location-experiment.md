# Esperimento facility location capacitated

Esperimento repository, escluso dal wheel. Il modello usa domanda frazionabile,
collegamenti completi, costi fissi e costi di allocazione per l'intera domanda.
I dati OR-Library sono benchmark pubblici, non dati bancari ne raccomandazioni.

Le istanze sono dati esterni, esclusi da Git tramite `.gitignore` e acquisiti
separatamente dall'utente; le copie locali non vengono eliminate. Non sono
previsti download automatici. Il manifest descrive i byte locali, non certifica
autenticita o diritti di redistribuzione. Il riferimento di cap41 e 1040444.375,
soggetto ad arrotondamenti.

La policy versione 1 usa alpha 0.5, epsilon 0.01, quota profilo 0.5,
sovrapposizione pesata per domanda almeno 0.5 e differenza relativa di capacita
al massimo 0.25. I profili sono costruiti sull'istanza originale, ordinando i
clienti per costo unitario e indice. Gli archi indicano ridondanza euristica,
non incompatibilita. I fixing non sono certificati e l'ottimalita residua non
dimostra quella originale.

Lo score usa la capacita utile e un costo indicativo. Se tutti i costi proxy
sono zero, il punteggio di convenienza e 1 per tutte le sedi:

```text
D = sum_j d_j
effective_i = min(u_i, D)
proxy_i = f_i + effective_i * sum_j(c_ij) / D
w_i = epsilon + (1 - epsilon) * (
    alpha * effective_i / max_k(effective_k)
    + (1 - alpha) * (1 - proxy_i / max_k(proxy_k))
)
```

Il benchmark confronta baseline, tutte le sedi protette, single pass con e
senza recovery e configurazione multi-round con recovery. Usa seed, solver,
numero di thread e budget omogenei; riporta tutti gli esiti, inclusi fallimenti
di preparazione. La differenza dall'obiettivo baseline e disponibile solo per
soluzioni con post-check riuscito. Il gap solver sul residuo non e un gap
certificato rispetto al problema originale.

Per collegamenti completi e domanda frazionabile, capacita totale sufficiente
e anche sufficiente per costruire un'allocazione: si distribuisce la domanda
successivamente tra le capacita disponibili. Le protezioni preservano la
disponibilita delle sedi indispensabili, non ne impongono l'apertura.

Esempio dalla root del repository:

```powershell
$env:PYTHONPATH = 'src'
python -m qreduce.experiments.facility_location.run data/benchmarks/or_library/capacitated_facility_location/cap41.txt --run-id cap41-baseline
python -m qreduce.experiments.facility_location.run data/benchmarks/or_library/capacitated_facility_location/cap41.txt --run-id cap41-recovery --rounds 1 --recovery-attempts 15
```

Gli artifact sono salvati in `outputs/facility_location/<run-id>`; i fallimenti
normalizzati sono risultati validi da analizzare, non successi. Il recovery usa
la pipeline condivisa e non incrementa il cap. Il tempo della pipeline include
i tentativi; il caricamento viene registrato separatamente. Non confrontare il
solo tempo dell'ultimo solve con la baseline end-to-end.
La CLI restituisce codice 0 per success e partial_success, 1 per gli altri
stati normalizzati. Il report del benchmark viene aggiornato dopo ogni scenario
e distingue errori di preparazione, esecuzione e analisi.

In un test esplorativo su cap41, il single-pass con recovery ha mantenuto 12
sedi e prodotto 1157583.05 contro 1040444.375 della baseline: una perdita di
117138.675, circa 11.26%. Questo non dimostra alcuno speedup o vantaggio della
policy. Le istanze presenti localmente sono state fornite dall'utente; checksum
locali non dimostrano provenienza o diritti di redistribuzione.

Valutazione esplorativa sulle quattro istanze locali, SCIP, seed 7, budget 60 s,
policy predefinita, un thread e 15 tentativi massimi di recovery:

| Istanza | Baseline | Single-pass | Con recovery | Differenza |
| --- | ---: | --- | ---: | ---: |
| cap41 | 1040444.375 | fallito | 1157583.050 | +117138.675 |
| cap42 | 1098000.450 | fallito | 1212583.050 | +114582.600 |
| cap43 | 1153000.450 | fallito | 1267583.050 | +114582.600 |
| cap44 | 1235500.450 | fallito | 1350083.050 | +114582.600 |

In tutte le quattro istanze il controllo con tutte le sedi protette coincide
con la baseline. La configurazione multi-round si e fermata dopo un round e ha
prodotto lo stesso risultato del single-pass con recovery. Non si puo inferire
ne un vantaggio in qualita ne uno speedup da questi quattro singoli run.

La pipeline condivisa termina al primo round con successo o successo parziale:
configurare piu round non garantisce che siano eseguiti piu round. Questo limite
non viene modificato dall'esperimento e la monotonicita di round multipli non
e ancora dimostrata per questa famiglia.