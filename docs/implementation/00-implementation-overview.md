# QReduce - Stato di implementazione

Le [specifiche](../specifications.md) definiscono requisiti, garanzie e
criteri di accettazione. Questa pagina riassume lo stato di implementazione;
la presenza di un requisito nelle specifiche non implica che sia disponibile.
Le valutazioni delle milestone sono basate sulle verifiche documentate in
precedenza, non costituiscono una nuova esecuzione dei test.

## Milestone del nucleo

Le milestone obbligatorie M01–M09 risultano completate:

| ID | Ambito | Evidenze nel repository |
| --- | --- | --- |
| M01 | Fondazioni, Python 3.12 e packaging | `pyproject.toml`, test di indipendenza runtime |
| M02 | Configurazione, contratti, stati e provenance | `src/qreduce/config.py`, `models.py`, `domains/`, test associati |
| M03 | Grafo MWIS, QUBO, Ising e diagnostica esatta | `src/qreduce/mwis/`, `tests/mwis/` |
| M04 | Contratti e backend MWIS | `src/qreduce/solving/mwis/`, test dei backend e capability |
| M05 | Riduzione single-pass e fixing | `src/qreduce/pipeline/single_pass.py`, test di selezione |
| M06 | Solve residuo, post-check e portfolio | `src/qreduce/solving/residual/`, `src/qreduce/experiments/portfolio_mv/` |
| M07 | Runner, artifact e notebook | `src/qreduce/experiments/runner.py`, `artifacts.py`, notebook e test |
| M08 | Multi-round e recovery | `src/qreduce/pipeline/multi_round.py`, `recovery.py`, test pipeline |
| M09 | Pipeline unificata e baseline classica | `src/qreduce/pipeline/unified.py`, test della pipeline |

## Modalità e limiti

`run_pipeline` seleziona la modalità tramite `max_reduction_rounds`: zero
esegue la baseline classica senza MWIS, uno il single-pass e valori superiori
il multi-round con recovery configurabile. Un valore superiore a uno non
garantisce che siano eseguiti più round. Il recovery opera sul medesimo round;
gli item già esclusi nei round precedenti non vengono riattivati.

La riduzione costruisce un dominio candidato, non la soluzione finale. Il
solve residuo e il post-check verificano i vincoli del problema originale;
l'ottimalità del residuo dopo fixing euristico non certifica quella originale.
Il modello classico corrente supporta MILP e MIQP con vincoli lineari;
altre forme richiedono riformulazioni o estensioni esplicite.

Gli esperimenti del repository sono esclusi dal wheel e pubblicano artifact;
i notebook li leggono e usano logica definita nei moduli Python. Le verifiche
storiche e le precedenti schede delle milestone sono nella cronologia Git.

## Capacità e verifiche ulteriori

La disponibilità dei backend dipende da dipendenze, capability e ambiente.
Per il backend neutral-atom si vedano [integrazione Pasqal](pasqal-integration.md)
e i limiti delle singole CLI. Il [confronto UIX](uix-portfolio-comparison.md)
descrive controlli e limiti dell'analisi degli artifact. Altre estensioni e
benchmark opzionali sono descritti nelle specifiche: non sono requisiti
implementati solo perché vi compaiono.

Restano decisioni sull'API pubblica finale e sulle eventuali integrazioni
aggiuntive. Le verifiche su hardware remoto richiedono accesso e autorizzazioni
esplicite e non sono sostituite dai test con trasporto simulato.