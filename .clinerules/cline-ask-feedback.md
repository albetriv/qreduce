# Regola: chiedere feedback al completamento di un task

Sintesi
- Dopo aver completato un task visibile all'utente, Cline deve chiedere un feedback esplicito.

Quando attivare
- Al termine di qualsiasi task che produce un risultato rilevante per l'utente (risposta, modifica, file creato, azione eseguita).
- Non chiedere per messaggi intermedi o conferme tecniche non percepibili come "task completato".

Messaggio standard (esempi)
- "Ho completato il task. Puoi darmi un feedback su questo risultato?"
- "Task completato. Il risultato va bene o vuoi modifiche?"
- "Ho finito — come valuti questa soluzione (ok / modifiche / non soddisfatto)?"

Cosa registrare
- Timestamp della richiesta, contenuto del task e risposta dell'utente (se fornita).
- Non memorizzare dati sensibili oltre quanto strettamente necessario.

Eccezioni
- Operazioni automatiche interne o di manutenzione non esposte all'utente.
- Se l'utente ha esplicitamente disattivato le richieste di feedback.

Esempi
- Task: generazione di un file -> Messaggio: "Ho creato il file X. Puoi darmi un feedback?"
- Task: risposta a una domanda complessa -> Messaggio: "Ho risposto alla tua domanda. Ti è stato utile?"

Linee guida di tono
- Breve, neutro, orientato all'azione (chiedere se serve modifica o se va bene).
- Offrire opzioni rapide quando possibile (es. "ok / modifiche / non soddisfatto").

Implementazione
- Trigger post-task che invoca il template standard.
- Log del feedback opzionale per miglioramenti futuri, rispettando la privacy.