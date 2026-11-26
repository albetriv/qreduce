# Cessione di crediti deteriorati

## 1. Descrizione del problema

La proposta, non ancora eseguibile, seleziona offerte indivisibili su lotti di
crediti deteriorati, potenzialmente sovrapposti. Dati i ricavi netti attesi e
i volumi dei crediti, si massimizza il ricavo rispettando un volume minimo e
impedendo che un credito sia ceduto più volte.

## 2. Formulazione matematica

Siano $I$ le offerte e $C$ i crediti. La variabile
$\delta_i \in \{0,1\}$ indica la selezione dell'offerta $i$. Assumendo
che il volume sia additivo per credito, il modello proposto è:

$$
\begin{aligned}
\max\quad & \sum_{i\in I} r_i\delta_i \\
\text{s.t.}\quad
& \sum_{i\in I} a_{ci}\delta_i \le 1 && c\in C, \\
& \sum_{i\in I}\left(\sum_{c\in C} v_c a_{ci}\right)\delta_i \ge V.
\end{aligned}
$$

Entrambi i vincoli sono attivi. Il primo impedisce la doppia cessione; grazie
ad esso il volume nel secondo non conta due volte lo stesso credito.

## 3. CLI unificata

Non disponibile: l’esperimento non è ancora eseguibile.

## 4. Parametri

- $r_i$: ricavo netto atteso dell'offerta $i$, eventualmente negativo.
- $a_{ci} \in \{0,1\}$: indica se il credito $c$ appartiene al lotto
  dell'offerta $i$.
- $v_c \ge 0$: volume del credito $c$; $V \ge 0$: volume minimo richiesto,
  nella stessa unità.
- $I$ e $C$: catalogo delle offerte e insieme dei crediti.

## 5. Directory degli artifact

Non applicabile: l’esperimento non produce ancora artifact.

## 6. Note specifiche

Le sovrapposizioni dei lotti costituiscono conflitti reali, rappresentabili con
archi tra offerte; il vincolo di volume resta necessario nel modello. Una
riduzione euristica del catalogo non equivale a imporre questi conflitti e può
eliminare offerte necessarie a raggiungere il volume, causando infattibilità.

## 7. Riferimenti

- [MIPLIB 2017, set packing](https://miplib.zib.de/tag_set_packing.html): istanze con struttura di selezione incompatibile.
- [Relazione finanziaria annuale 2025 di Intesa Sanpaolo](https://group.intesasanpaolo.com/content/dam/portalgroup/repository-documenti/investor-relations/bilanci-relazioni-it/2025/Bilanci_2025.pdf): contesto sulle cessioni di crediti deteriorati.
