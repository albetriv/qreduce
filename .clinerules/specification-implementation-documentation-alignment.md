---
globs:
  - "specifications.md"
  - "README.md"
  - "docs/**/*.md"
  - "src/**/*.py"
  - "tests/**/*.py"
---

# Regola: allineamento tra specifiche, implementazione e documentazione

## Obiettivo

- Mantenere coerenti specifiche, implementazione Python, test, README,
  documentazione ed esempi quando una modifica altera comportamento,
  interfacce o assunzioni del progetto.

## Quando applicarla

- La regola si attiva quando viene modificato un file coperto dal frontmatter.
- Il frontmatter determina quando eseguire la verifica, non limita i file che
  possono dover essere controllati o aggiornati in seguito.

## Verifica obbligatoria

Per ogni modifica, valutare esplicitamente se essa modifica una o più delle
seguenti aree:

- comportamento funzionale;
- API pubbliche, firme di funzioni o classi;
- input, output, formati dati o configurazioni;
- vincoli, formule, assunzioni di dominio o convenzioni simboliche;
- esempi di utilizzo, comandi di esecuzione o risultati attesi.

Se una o più aree sono coinvolte:

1. aggiornare le specifiche, l'implementazione Python, i test, il README, la
   documentazione e gli esempi effettivamente impattati;
2. aggiungere o aggiornare test coerenti con il nuovo comportamento;
3. verificare che esempi, snippet, nomi di variabili e istruzioni di esecuzione
   corrispondano al codice;
4. verificare che notebook ed esempi presentino logica importata dai moduli
   Python, senza duplicare business logic;
5. riportare nel riepilogo finale quali artefatti sono stati controllati e quali
   sono stati modificati.

## Nessun aggiornamento necessario

- Non aggiornare documentazione, README o specifiche in modo artificiale o
  puramente cosmetico.
- Se un artefatto correlato non richiede modifiche, dichiarare nel riepilogo
  finale che è stato verificato e perché risulta ancora coerente.

## Priorita e ambiguita

- Non dichiarare nel README, nella documentazione o nelle specifiche una
  funzionalita che non sia implementata e verificata.
- In caso di contrasto, le specifiche approvate prevalgono sulle interpretazioni
  implicite del codice.
- Se le specifiche sono ambigue e la modifica richiede una scelta di
  comportamento osservabile, chiedere chiarimento prima di implementarla.

## Checklist di completamento

- Specifiche: aggiornate oppure verificate senza modifiche necessarie.
- Implementazione Python: coerente con il comportamento previsto.
- Test: aggiornati quando il comportamento osservabile e cambiato ed eseguiti
  quando possibile.
- README e documentazione: aggiornati oppure verificati senza modifiche
  necessarie.
- Esempi e notebook: aggiornati se impattati e coerenti con i moduli Python.
