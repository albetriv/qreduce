# Piano di migrazione delle formule Markdown per GitHub

**Stato:** migrazione e verifiche locali eseguite; verifica visiva su GitHub
in sospeso.

## 1. Obiettivo e perimetro

Renderizzare correttamente le formule nella vista Markdown di GitHub, sia
in linea sia a blocco, senza cambiare il contenuto matematico delle guide.
GitHub supporta già LaTeX tramite MathJax, ma la sintassi documentata per
la sua interfaccia Markdown usa delimitatori diversi da quelli attuali.
Riferimento: [Writing mathematical expressions — GitHub Docs][github-math].

- **Da aggiornare:** sette guide degli esperimenti, il loro test di contratto
  e una breve nota d'uso nel README degli esperimenti.
- **Da lasciare invariati:** formule e convenzioni simboliche, titoli e
  ancore, tabelle, bibliografia, comandi CLI, percorsi e nomi delle guide.
  Non modificare specifiche, codice applicativo, notebook, configuratori
  UIX, dipendenze o file di lock. Non reintrodurre il generatore HTML.
- **Non è un obiettivo:** fornire il rendering aprendo i file Markdown con
  un browser via `file://`. Il catalogo UIX continua a puntare ai Markdown.

## 2. Inventario iniziale

Conteggio rilevato nei Markdown tracciati al momento della stesura. Prima
di implementare, rieseguire l'inventario sul branch di lavoro: se cambia,
aggiornare la baseline e spiegare la differenza, senza forzare questi numeri.

| Guida in `docs/experiments/` | Formule in linea | Blocchi |
| --- | ---: | ---: |
| `asset-liability-management.md` | 13 | 1 |
| `cessione-crediti-deteriorati.md` | 14 | 1 |
| `facility-location.md` | 18 | 2 |
| `pianificazione-audit-interni.md` | 11 | 1 |
| `portfolio-mv.md` | 9 | 3 |
| `portfolio-sr.md` | 21 | 5 |
| `riassicurazione-passiva.md` | 24 | 2 |
| **Totale** | **110** | **15** |

Il file del Portfolio Media-Varianza si chiama già `portfolio-mv.md`.
`docs/experiments/README.md` non contiene formule con i delimitatori da
migrare: va toccata solo la nota sul visualizzatore.

## 3. Convenzione da adottare

Usare `$...$` senza spazi aggiunti subito dopo l'apertura o prima della
chiusura, e `$$` su due righe dedicate per i blocchi, con una riga vuota
tra il blocco e la prosa adiacente. Conservare l'ordine e le righe del
contenuto LaTeX. Non aggiungere `<script>` o configurazioni MathJax.

**Prima — sorgente Markdown:**

```markdown
Il peso dell'asset è \(x_i\).

\[
\begin{aligned}
\sum_i x_i &= 1, \\
x_i &\geq 0.
\end{aligned}
\]
```

**Dopo — sorgente Markdown:**

```markdown
Il peso dell'asset è $x_i$.

$$
\begin{aligned}
\sum_i x_i &= 1, \\
x_i &\geq 0.
\end{aligned}
$$
```

Se la verifica su GitHub mostra un conflitto con la sintassi Markdown in
una formula in linea, usare per quella formula la variante GitHub con
backtick interni (per esempio `` $`x_i`$ ``). Se un blocco multilinea non
viene renderizzato correttamente con `$$`, usare un blocco con apertura
` ```math ` e chiusura ` ``` `, senza `$$` al suo interno. In entrambi i
casi mantenere il corpo LaTeX e adeguare il test per riconoscere
l'eccezione adottata. Documentare nel diff il motivo della scelta.
Se compare un dollaro letterale, distinguerlo dal delimitatore: seguire
le indicazioni di GitHub Docs sul contesto del simbolo, senza sostituzioni
globali di caratteri `$`.

## 4. Sequenza operativa

1. **Registrare la baseline.** Dalla root del workspace, eseguire
   `git status --short` e la ricerca qui sotto. Contare formule in linea
   e coppie di blocco per file, verificando anche le chiusure. Annotare
   eventuali modifiche preesistenti senza sovrascriverle. Eseguire il test
   di contratto prima della modifica per distinguere problemi preesistenti.

   ```bash
   git grep -n -F -e '\(' -e '\)' -e '\[' -e '\]' -- docs/experiments/*.md
   ```

2. **Provare due guide prima della conversione completa.** In
   `portfolio-mv.md` convertire una formula in linea e i blocchi; in
   `portfolio-sr.md` includere almeno un blocco con `aligned`. Verificare
   anche un paragrafo con più formule sulla stessa riga. Se possibile,
   controllare questo campione nella vista `Preview` del file su GitHub
   prima di replicare la sintassi sul resto delle guide.
3. **Convertire tutte e sette le guide.** Sostituire solo le coppie `\(`
   e `\)` che delimitano formule e le righe di delimitazione `\[` e
   `\]` dei blocchi. Evitare una sostituzione dell'intero repository.
   Proteggere blocchi e span di codice, link, parentesi letterali e
   qualsiasi esempio di sintassi scritto come testo; se si automatizza,
   interrompere in presenza di una coppia inattesa o non bilanciata.
   Conservare macro, operatori, `&`, interruzioni di riga LaTeX (`\\`),
   pedici, backslash e ordine delle formule.
4. **Verificare l'identità delle formule.** Per ciascuna guida confrontare,
   nell'ordine, il contenuto delle formule prima e dopo, esclusi i soli
   delimitatori. Controllare invariati anche il numero per tipo e il testo
   non matematico, salvo eventuali righe vuote ai confini dei blocchi.
   Se serve uno script usa e getta per il confronto, tenerlo in
   `.cline-tmp/`; non aggiungere tooling permanente per la migrazione.
5. **Adeguare il README degli esperimenti.** Nella nota dopo il catalogo
   UIX, indicare che la vista Markdown di GitHub è la destinazione prevista
   per leggere le formule e che in locale serve un visualizzatore Markdown
   compatibile. Mantenere l'avvertenza su apertura o download del sorgente
   da browser; non cambiare collegamenti né promettere supporto offline.
6. **Aggiornare il test di contratto e rieseguire le verifiche** illustrate
   nei paragrafi successivi. Se una guida richiede la sintassi alternativa,
   annotare il caso prima di considerare conclusa la migrazione.

## 5. Adeguamento dei test

Nel file `tests/test_experiment_documentation_contract.py`, aggiornare
`test_section_structure_and_formulation`:

- Sostituire la condizione che richiede `\[` e `\]` con un controllo
  sulle righe `$$` nella sezione 2. Verificare che esista almeno un blocco
  chiuso, che le righe delimitatrici siano in numero pari e che ciascuna
  coppia contenga almeno una riga non vuota. Il messaggio d'errore deve
  identificare la guida e, per quanto possibile, la riga o il blocco.
- Verificare in tutta la guida, fuori dal codice, che non restino formule
  con delimitatori precedenti, anche nelle note fuori dalla sezione 2.
  Controllare che non rimangano delimitatori in linea orfani: distinguere
  il dollaro singolo da `$$` e non contare dollari esplicitamente letterali.
  Se si introducono eccezioni GitHub con backtick, riconoscerle prima di
  escludere gli span di codice.
- Conservare i controlli su titoli, sezioni, CLI, riferimenti e link.
  Conservare anche il divieto di blocchi di codice ordinari nella sezione
  matematica; se si usa la sintassi `math`, consentire solo quel tipo di
  blocco e distinguerlo dai blocchi CLI nel conteggio dei fence delle guide.
- Se si introduce un validatore separato, coprire con casi mirati una
  formula valida, un blocco multilinea valido, un blocco non chiuso, un
  blocco vuoto e un delimitatore precedente nel testo. Non introdurre un
  parser Markdown completo né dipendenze aggiuntive per questo controllo.
- Tenere i conteggi dell'inventario come evidenza della migrazione, non
  come vincolo permanente nei test: le guide potranno aggiungere formule.

## 6. Verifica locale e visiva

### Locale

Eseguire dalla root con l'ambiente Python del progetto:

```bash
.venv/bin/python -m pytest tests/test_experiment_documentation_contract.py -q
git diff --check
git status --short
git diff --stat
git grep -n -F -e '\(' -e '\)' -e '\[' -e '\]' -- 'docs/experiments/*.md'
```

L'ultima ricerca deve dare zero corrispondenze di delimitatori obsoleti
nelle formule delle guide; `git grep` restituisce `1` se non trova nulla.
Gli esempi del presente piano sono deliberatamente fuori dal perimetro
della ricerca. Ricontrollare che non sia cambiato alcun file applicativo.
I test locali verificano struttura, link e contratto CLI: non verificano
il risultato visivo del renderer GitHub. Eventuali errori preesistenti
fuori perimetro vanno segnalati, non corretti in questa migrazione.

### GitHub

Quando il branch è disponibile, aprire i file direttamente nella vista
renderizzata GitHub, non in `Raw` e non soltanto nel diff della PR.
Controllare tutte le sette guide: almeno una formula in linea per guida
e tutti i blocchi della sezione 2. Dare priorità a questi casi:

| Guida | Controllo visivo |
| --- | --- |
| `portfolio-mv.md` | Formule in linea consecutive; tre blocchi separati. |
| `portfolio-sr.md` | Blocchi multilinea: righe, allineamento e pedici. |
| `facility-location.md` | Due blocchi, compresa la disposizione dei vincoli. |
| Quattro guide di anteprima | Formule in linea e tutti i blocchi, compresi quelli a più righe. |

Controllare che non si vedano delimitatori grezzi, che non compaiano
errori MathJax, che gli a capo matematici siano conservati e che le sezioni
adiacenti non vengano assorbite nella formula. Controllare inoltre che il
link dal README degli esperimenti apra la guida Portfolio Media-Varianza.
Registrare il branch o SHA, le pagine controllate e l'esito nella PR.
Se GitHub non è accessibile, indicare la verifica visiva come **in sospeso**;
non dedurre un esito positivo dai soli test locali.

## 7. Criteri di completamento e ripristino

- [ ] Tutte le formule inventariate sono migrate e il LaTeX interno è invariato.
- [ ] Le guide non contengono formule con delimitatori obsoleti.
- [ ] Il README indica come consultare le guide su GitHub e in locale.
- [ ] Il test di contratto e `git diff --check` passano.
- [ ] La vista GitHub è stata verificata, con esito registrato per ogni guida.
- [ ] Nessuna modifica a pipeline, notebook, configuratori o dipendenze.

Isolare l'implementazione in un commit dedicato. Se emergono regressioni
nel rendering dopo la pubblicazione, correggere la sintassi della guida
interessata e ripetere i controlli. Se serve annullare l'intera migrazione,
revertire il commit dedicato, senza coinvolgere modifiche estranee.

[github-math]: https://docs.github.com/en/get-started/writing-on-github/working-with-advanced-formatting/writing-mathematical-expressions