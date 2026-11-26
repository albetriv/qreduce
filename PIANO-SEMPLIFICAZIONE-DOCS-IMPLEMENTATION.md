# Piano di semplificazione di `docs/implementation`

## Obiettivo e perimetro

Ridurre da 15 a 3 i documenti attivi in `docs/implementation`, eliminando i doppioni senza perdere informazioni ancora utili. Le nove schede M01–M09 e le tre vecchie note sugli esperimenti saranno rimosse dal ramo corrente dopo aver trasferito gli eventuali contenuti ancora validi e non documentati altrove. Le versioni precedenti resteranno consultabili nella cronologia Git/GitHub: **nessuna cartella di archivio, nessuna copia e nessuna pagina segnaposto**.

Il piano si basa sulla revisione `82082dc` di `main`. Le milestone obbligatorie risultano documentate come completate; questo non equivale a una nuova esecuzione della suite. L'intervento è solo documentale: non cambia codice, test, notebook, configurazioni, formati degli artifact o requisiti funzionali.

## Assetto finale

```text
docs/implementation/
├── 00-implementation-overview.md
├── pasqal-integration.md
└── uix-portfolio-comparison.md
```

Le specifiche rimangono la fonte normativa per requisiti e garanzie. L'overview riporta lo stato dell'implementazione. Le note Pasqal e UIX spiegano come usare e interpretare funzionalità specifiche; le guide degli esperimenti restano nelle loro sedi attuali.

## Interventi per documento

1. **`00-implementation-overview.md` — mantenere il percorso e riscrivere.** Lasciare una riga di sintesi per ciascuna milestone M01–M09, senza link alle schede rimosse. Riassumere baseline classica, single-pass e multi-round; distinguere funzionalità disponibili, limiti e verifiche aperte. Correggere il riferimento obsoleto a `portfolio_domain` in favore di `portfolio_mv`. Eliminare i contatori storici dei test e rimandare alle specifiche per i requisiti e le estensioni opzionali.
2. **Schede di milestone `01`–`09` — rimuovere.** Prima della rimozione, verificare che ogni invariante ancora rilevante sia già descritta nelle specifiche o nei contratti del codice e coperta dai test pertinenti. Se manca una spiegazione utile nella documentazione attiva, trasferirla nella sede appropriata dopo averla verificata. Date, audit, risultati storici e vecchi piani di lavoro restano nella cronologia Git.
3. **`experiment-organization.md` — consolidare e rimuovere.** Integrare nell'indice delle guide degli esperimenti solo le decisioni ancora valide e mancanti: separazione tra parser e adapter, esclusione degli esperimenti dal wheel e distinzione tra benchmark del core MWIS ed esperimenti end-to-end. Non ripubblicare la cronaca della migrazione del portfolio.
4. **`facility-location-experiment.md` — consolidare e rimuovere.** Integrare nelle note della guida attiva l'origine esterna dei dati, i limiti del recovery e del confronto dei tempi, senza ripetere quanto già presente. Mantenere chiaro che l'ottimalità del residuo non certifica quella originale. Protocollo, configurazioni e risultati esplorativi `cap41`–`cap44` restano nella cronologia Git, senza farne una prova di speedup. Mantenere distinto l'esperimento Facility Location dall'intera iniziativa opzionale N03.
5. **`portfolio-sr-experiment.md` — consolidare e rimuovere.** Usare la guida esistente per la CLI e il README del package per metodologia e validazione degli artifact. Verificare se dettagli come esposizioni a zero, soglia di visualizzazione e assenza di rinormalizzazione siano ancora corretti e non già documentati; aggiungerli al README del package solo se utili e confermati.
6. **`pasqal-local-status.md` — rinominare in `pasqal-integration.md`.** Organizzare per backend locale, emulatore cloud e QPU; rimuovere la cronologia delle fasi e l'affermazione obsoleta secondo cui non esiste un backend QPU. Conservare prerequisiti, limiti, diagnostica, preflight senza invio, verifica offline, consenso ai costi, persistenza, recupero e gestione degli esiti di invio incerti. Distinguere test a trasporto simulato, compilazione senza invio e pilota hardware riportato nel README. Il file di evidenza del pilota citato nel README non è tracciato nella revisione di riferimento: se non si trova una fonte durevole, attribuire esplicitamente il resoconto al README e non presentarlo come verifica indipendente.
7. **`uix-portfolio-comparison-findings.md` — rinominare in `uix-portfolio-comparison.md`.** Conservare requisiti degli artifact, criteri di comparabilità, limiti di validazione del browser e verifiche mancanti. Mantenere una sezione stabile per il caso da 100 a 38 variabili, citato nel Q&A Intesa: output locali non tracciati, annealing simulato e nessuna inferenza causale su prestazioni o qualità. Non mantenere come istruzioni operative gli appunti specifici di una macchina o i percorsi sotto `.cline-tmp`.

## Sequenza di lavoro

1. Confrontare il contenuto delle pagine da rimuovere con guide, specifiche, codice e test. Trasferire solo le informazioni uniche, attuali e verificabili prima di eliminare i file sorgente.
2. Riscrivere l'overview e le due note tecniche. Nelle guide degli esperimenti preservare la struttura numerata, i delimitatori matematici e il singolo blocco CLI con `--help`; non aggiungere esempi storici che violino il contratto editoriale.
3. Rimuovere le dodici pagine e aggiornare i riferimenti nello stesso passaggio:
   - README principale: mantenere il collegamento all'overview e aggiornare quelli alle note Pasqal e UIX.
   - Specifiche: puntare alla guida attiva di Facility Location e all'overview per lo stato, senza cambiare i requisiti.
   - Indice degli esperimenti: sostituire il rimando a `experiment-organization.md` con le decisioni operative pertinenti.
   - Q&A Intesa: aggiornare il riferimento al caso da 100 a 38 variabili, preferibilmente con un'ancora alla sezione dedicata.
4. Verificare le differenze prima di chiudere l'intervento. Non pubblicare dati, output locali o credenziali e non inviare job cloud o QPU.

## Verifica e criteri di chiusura

- Restano esattamente tre file in `docs/implementation`; non viene creata alcuna copia di archivio.
- Nei file attivi non rimangono riferimenti ai percorsi rimossi. Cercare nei file tracciati con `git grep` e controllare link relativi e ancore nei Markdown modificati.
- Dalla root, eseguire `poetry run pytest tests/test_experiment_documentation_contract.py -q` e `git diff --check`. Verificare gli eventuali esempi CLI aggiornati via `--help` o test locali pertinenti, senza avviare calcoli remoti.
- Il diff finale contiene solo modifiche documentali. I limiti ancora validi sono leggibili nella documentazione attiva; le versioni storiche dei file rimossi sono recuperabili dalla cronologia Git/GitHub alla revisione precedente alla rimozione.