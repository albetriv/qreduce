# Regola: formattazione degli output di Cline CLI

Sintesi
- Quando Cline viene utilizzato tramite CLI, gli output destinati all'utente devono essere formattati in modo corretto, leggibile e coerente.
- Non inviare testo Markdown malformato, blocchi di codice incompleti, elenchi spezzati o contenuti privi di separazione visiva.

Quando attivare
- Per ogni risposta, piano, riepilogo, risultato di comando, spiegazione tecnica o istruzione fornita attraverso Cline CLI.
- La regola si applica sia agli output intermedi visibili all'utente sia alla risposta finale.

Regole operative
- Usare titoli Markdown solo quando migliorano la leggibilità e mantenere una gerarchia coerente (`#`, `##`, `###`).
- Separare paragrafi, sezioni, elenchi e blocchi di codice con righe vuote appropriate.
- Usare elenchi puntati o numerati con indentazione e marcatori coerenti; non mescolare formati senza motivo.
- Racchiudere ogni comando, snippet, percorso o output multilinea in blocchi di codice con delimitatori di apertura e chiusura correttamente bilanciati.
- Specificare il linguaggio del blocco di codice quando noto (ad esempio `powershell`, `python`, `text`, `json` o `markdown`).
- Usare il codice inline solo per elementi brevi, quali comandi, percorsi, nomi di file, opzioni e identificatori.
- Usare tabelle Markdown solo se i dati sono realmente tabellari e verificarne intestazioni, separatori e numero di colonne.
- Distinguere chiaramente tra esito dell'operazione, dettagli tecnici, avvisi, errori e prossimi passi.
- Preservare caratteri speciali, accenti, virgolette e simboli tecnici senza introdurre escape, troncamenti o spaziature errate.

Formule ed espressioni matematiche
- Le formule destinate all'utente tramite CLI devono usare esclusivamente caratteri ASCII stampabili; non usare simboli matematici Unicode o rendering LaTeX/MathJax.
- Per formule su una o piu righe, usare sempre un blocco `text` completo, per mantenere allineamento e leggibilita nel terminale.
- Usare operatori e notazione ASCII convenzionali: `+`, `-`, `*`, `/`, `^`, `=`, `<=`, `>=`, `!=`, `sqrt(...)`, `sum_i`, `in`, parentesi e parentesi quadre.
- Sostituire simboli greci e notazioni non ASCII con identificatori ASCII espliciti: `alpha` per alpha, `Sigma` per la matrice di covarianza, `delta_i` per la variabile binaria e `z_i` per lo spin Ising.
- Non usare nelle formule caratteri quali `alpha`, `Sigma`, `delta`, `sum`, `sqrt`, `<=`, `>=`, `in`, `x^T` in versione Unicode o simboli tipografici equivalenti. Usare invece una forma ASCII, per esempio:

```text
objective = -alpha^T * x
portfolio_variance = x^T * Sigma * x
TEV(x, b) = sqrt((x - b)^T * Sigma * (x - b))
sum_i x_i = 1
delta_i in {0, 1}
z_i in {-1, +1}
```

- Se una formula e complessa, definire prima le variabili in prosa e poi privilegiare piu righe brevi rispetto a un'espressione lunga che va a capo automaticamente.

Output di comandi e diagnostica
- Riportare solo l'output necessario per comprendere l'esito; riassumere i log molto lunghi e indicare eventuali parti omesse.
- Non presentare testo di log come istruzione da eseguire: usare un'etichetta chiara, ad esempio `Output`, `Errore` o `Diagnostica`.
- Per errori o warning, indicare in modo leggibile il comando o l'azione interessata, la causa rilevata e l'impatto sul task.

Verifica prima dell'invio
- Controllare che ogni delimitatore Markdown aperto sia chiuso, in particolare i blocchi delimitati da tre backtick.
- Controllare che non vi siano elenchi interrotti, tabelle disallineate, titoli vuoti o righe concatenate involontariamente.
- Controllare che la risposta possa essere letta correttamente in un terminale a larghezza ridotta, evitando righe inutilmente lunghe e strutture complesse quando non necessarie.
- Controllare che ogni formula destinata alla CLI contenga solo caratteri ASCII stampabili e che gli identificatori matematici siano leggibili senza rendering speciale.
- Se la formattazione degrada durante la generazione, rigenerare o correggere l'output prima di inviarlo all'utente.

Eccezioni
- Per messaggi estremamente brevi, una frase semplice è preferibile a una struttura Markdown artificiosa.
- L'output grezzo è ammesso solo se l'utente lo richiede esplicitamente; va comunque racchiuso in un blocco `text` completo.