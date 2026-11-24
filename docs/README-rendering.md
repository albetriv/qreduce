# Rendering statico delle guide esperimenti

Il generatore usa il gruppo di dipendenze opzionale `docs` e non modifica i
sorgenti Markdown. Installare il gruppo e generare le pagine con:

```bash
poetry install --with docs
poetry run python docs/render_experiments.py
poetry run python docs/render_experiments.py --check
```

Le pagine sono scritte in `docs/experiments/` e devono essere versionate insieme ai
sorgenti. Non modificarle a mano. Il controllo `--check` restituisce un errore
se una pagina manca o non corrisponde al sorgente; ripeterlo dopo ogni modifica
alle guide o al generatore.

Il catalogo collega le pagine HTML generate. Prima di versionare, verificare i sette link dal filesystem e
controllare le formule anche con MathJax non raggiungibile: testo, tabelle e
TeX devono rimanere visibili. MathJax 3.2.2 viene caricato da CDN; il rendering
tipografico offline non è garantito.
