# Regola: convenzione simbolica delle variabili di ottimizzazione

Sintesi
- In tutto il progetto, usare una simbologia coerente per distinguere il dominio delle variabili.

Convenzione obbligatoria
- `x`  -> variabile continua
- `δ`  -> variabile booleana/binaria `{0,1}`
- `z`  -> variabile intera binaria in codifica ising `{-1,+1}`

Quando applicarla
- In script Python, notebook, esempi, pseudocodice e documentazione.
- Nella definizione di QP/QUBO/Ising e nei vincoli di collegamento tra variabili.

Linee guida pratiche
- Usare nomi espliciti quando possibile:
  - `x_weights`, `x_opt` per continue
  - `δ_select`, `δ_opt` per binarie `{0,1}`
  - `z_spin`, `z_opt` per variabili `{-1,+1}`
- Se si converte tra `δ` e `z`, dichiarare sempre la mappa in modo esplicito:
  - `δ = (1 + z) / 2`
  - `z = 2δ - 1`
- Evitare di riusare la stessa lettera per domini diversi nello stesso file/modulo.

Checklist revisione (prima del commit)
- Ogni `x` rappresenta davvero una variabile continua.
- Ogni `δ` rappresenta davvero una variabile `{0,1}`.
- Ogni `z` rappresenta davvero una variabile `{-1,+1}`.
- Eventuali conversioni `δ <-> z` sono documentate vicino al codice.

Eccezioni
- Codice di terze parti, API esterne o notebook importati che impongono naming differente.
- In caso di eccezione, aggiungere un commento breve che spieghi la deviazione.
