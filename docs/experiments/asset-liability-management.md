# Asset Liability Management (ALM)

## 1. Descrizione del problema

La proposta, non ancora eseguibile, seleziona swap di tasso e ne dimensiona i
nozionali usando scenari di rischio, impatti EVE e NII e limiti operativi.
L'obiettivo è minimizzare la perdita EVE nello scenario peggiore, limitando il
calo NII, il nozionale complessivo e il numero di operazioni.

## 2. Formulazione matematica

Siano \(I\) gli swap e \(S\) un insieme non vuoto di scenari. Le variabili sono
il nozionale continuo \(x_i \ge 0\), l'attivazione binaria
\(\delta_i \in \{0,1\}\) e la perdita massima continua libera \(x_{\mathrm{worst}}\).
Con impatti additivi per unità di nozionale, il modello proposto è:

\[
\begin{aligned}
\min\quad & x_{\mathrm{worst}} \\
\text{s.t.}\quad
& x_{\mathrm{worst}} \ge L_s - \sum_{i\in I} a_{si}x_i && s\in S, \\
& N_s + \sum_{i\in I} b_{si}x_i \ge -D_s && s\in S, \\
& 0 \le x_i \le U_i\delta_i && i\in I, \\
& \sum_{i\in I} x_i \le B, \qquad \sum_{i\in I}\delta_i \le K.
\end{aligned}
\]

Tutti i vincoli indicati sono attivi. Una perdita massima negativa rappresenta
un guadagno EVE anche nello scenario peggiore; non si impone un minimo nozionale
per un'attivazione.

## 3. CLI unificata

Non disponibile: l’esperimento non è ancora eseguibile.

## 4. Parametri

- \(L_s\): perdita EVE iniziale nello scenario; \(N_s\): variazione NII iniziale.
- \(a_{si}\): variazione EVE e \(b_{si}\): variazione NII per unità di
  nozionale dello swap, con segno; \(D_s \ge 0\): calo NII massimo ammesso.
- \(U_i \ge 0\): nozionale massimo individuale; \(B \ge 0\): tetto totale;
  \(K\): numero massimo intero non negativo di operazioni.

## 5. Directory degli artifact

Non applicabile: l’esperimento non produce ancora artifact.

## 6. Note specifiche

Un grafo ausiliario può collegare swap con profili simili: tali archi indicano
ridondanza euristica, non incompatibilità. Escludere candidati in base a tale
grafo può peggiorare l'ottimo o rendere il problema residuo infattibile.

## 7. Riferimenti

- [Relazione finanziaria annuale 2025 di Intesa Sanpaolo](https://group.intesasanpaolo.com/content/dam/portalgroup/repository-documenti/investor-relations/bilanci-relazioni-it/2025/Bilanci_2025.pdf): contesto IRRBB, EVE e NII.
