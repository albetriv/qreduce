# M07 - Runner e artifact di esperimento

Il runner interno pubblica in modo atomico i JSON del run e il manifest con
hash, configurazione e policy provenance redatta. Il loader controlla gli hash
dei file interni, incluso l'eventuale modello esportato. I notebook leggono gli
artifact e non eseguono la pipeline. Export esterni non fanno parte della stessa
transazione atomica; il loro hash e` registrato ma non verificato dal loader.

Evidenze: `tests/experiments/test_runner.py`, test integrazione SCIP/CPLEX e
`src/qreduce/experiments/artifacts.py`. Le failure normalizzate sono persistite;
una failure di serializzazione impedisce la pubblicazione finale.

Stato: **parziale**. Il manifest di fixing contiene ora round, candidate,
versione policy e garanzie per entry. Restano la verifica completa degli hash
di input opachi e le matrici di round-trip per tutti gli esiti. Le semantiche
multi-round restano M08.