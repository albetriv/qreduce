# Prompt Templates for Better Cline Usage

## Planning-first coding task

```text
Lavora in PLAN MODE. Analizza il codice rilevante e proponi un piano prima di modificare file.
Obiettivo: <obiettivo>
File/moduli rilevanti: <percorsi>
Vincoli: <vincoli>
Criteri di successo: <test/validazioni>
Non modificare: <non-goals>
```

## Implementation task

```text
Implementa <feature/fix> in ACT MODE.
Prima esplora i file rilevanti, poi modifica solo ciò che serve.
Esegui i test/controlli disponibili e riepiloga file modificati, verifiche e rischi residui.
```

## Documentation-guided Cline usage

```text
Usa la skill cline-usage-guide e consulta la documentazione Cline tramite cline-docs.
Voglio capire come usare Cline per: <scenario>.
Dammi workflow consigliato, fonti e un prompt riutilizzabile.
```
