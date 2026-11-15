# Organizzazione degli esperimenti

## Stato

La famiglia facility location e descritta in `facility-location-experiment.md`;
e sperimentale ed esclusa dal wheel.

Decisione architetturale approvata nel piano di riorganizzazione. La migrazione
del portfolio e implementata; test, CLI, notebook, wheel e smoke test locali sono
stati verificati. Non erano disponibili artifact storici locali per una verifica
diretta dei loader. Questo consolidamento non costituisce una milestone funzionale.

## Decisione

Gli esperimenti interni sono organizzati per famiglia di problemi, non per run
o variante. Ogni adapter rappresenta una semantica di riduzione e puo essere
riutilizzato da piu esperimenti e origini di dati. Parser e loader sono separati
dagli adapter; non si inferisce un adapter universale da modelli MIP generici.
Gli adapter sperimentali rimangono nel repository e sono esclusi dal wheel.

Runner e lettura generica degli artifact sono condivisi e indipendenti dalle
famiglie concrete. I benchmark del solo core MWIS sono distinti dagli esperimenti
end-to-end. Non sono richiesti moduli identici per tutte le famiglie, ne un
registry o una nuova gerarchia di classi. I benchmark pubblici restano opzionali.

## Migrazione implementata

Il package `qreduce.experiments.portfolio` raccoglie dominio, generazione, input
condivisi, analisi e tre entry point. I chiamanti sono migrati direttamente,
senza wrapper legacy, inclusi test, notebook, documentazione e interfacce che
producono comandi. Algoritmi e formato degli artifact restano invariati.
I notebook portfolio si trovano in `notebooks/experiments/portfolio/` e le tre
modalita pubblicano per default in `outputs/portfolio/{run_id}/`. Un
`output_root` esplicito sostituisce questo default senza aggiunte implicite.
Gli artifact esistenti non sono spostati e restano leggibili al percorso originale.

## Criteri di accettazione

- Le tre modalita condividono adapter e costruzione degli input; l'infrastruttura
  comune non dipende dal portfolio.
- Import, CLI, test, notebook e documentazione operativa usano i nuovi percorsi.
- Identita, formati, pubblicazione e verifica degli artifact restano invariati;
  gli output esistenti non vengono riscritti.
- Test, lint, smoke test dei backend disponibili e contenuto del wheel sono
  verificati; eventuali limitazioni sono riportate esplicitamente.
- I notebook rimangono dedicati a presentazione e lettura degli artifact.