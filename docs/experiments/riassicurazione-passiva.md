# Riassicurazione passiva

## 1. Descrizione del problema

La proposta, non ancora eseguibile, seleziona offerte indivisibili di
riassicurazione in eccesso di sinistro, usando premi, perdite e indennizzi per
scenario. L'obiettivo è ridurre la perdita trattenuta negli scenari gravi,
rimanendo nel budget e impedendo doppi recuperi.

## 2. Formulazione matematica

Siano \(I\) le offerte, \(S\) un insieme non vuoto di scenari e \(G\) gli
strati di rischio disgiunti. Ogni offerta appartiene a uno strato; \(I_g\) è
l'insieme delle offerte per lo strato \(g\). La variabile
\(\delta_i \in \{0,1\}\) indica l'acquisto, mentre \(x_{\mathrm{worst}}\) è
continua e libera. Come scelta modellistica proposta, si minimizza la massima
perdita trattenuta sugli scenari, senza includere i premi nella perdita:

\[
\begin{aligned}
\min\quad & x_{\mathrm{worst}} \\
\text{s.t.}\quad
& x_{\mathrm{worst}} \ge L_s - \sum_{i\in I} r_{si}\delta_i && s\in S, \\
& \sum_{i\in I} p_i\delta_i \le B, \\
& \sum_{i\in I_g}\delta_i \le 1 && g\in G.
\end{aligned}
\]

Tutti i vincoli sono attivi. Per ogni scenario, sia \(L_{sg}\ge 0\) la
perdita attribuita allo strato disgiunto \(g\). I dati devono soddisfare:

\[
\sum_{g\in G} L_{sg}\le L_s,\qquad
0\le r_{si}\le L_{sg}\quad (g\in G,\ i\in I_g,\ s\in S).
\]

Gli indennizzi sono precalcolati. Questi limiti e la mutua esclusione delle
offerte alternative impediscono doppi recuperi e assicurano che l'indennizzo
complessivo non superi la perdita lorda.

## 3. CLI unificata

Non disponibile: l’esperimento non è ancora eseguibile.

## 4. Parametri

- \(L_s \ge 0\): perdita lorda nello scenario \(s\).
- \(L_{sg} \ge 0\): perdita dello strato \(g\) nello scenario \(s\), con somma
  sugli strati non superiore a \(L_s\).
- \(r_{si} \ge 0\): indennizzo dell'offerta \(i\) nello scenario \(s\),
  precalcolato secondo soglia e limite contrattuale.
- \(p_i \ge 0\): premio dell'offerta; \(B \ge 0\): budget totale dei premi.
- \(I\), \(S\), \(G\) e \(I_g\): offerte, scenari, strati e assegnazione
  delle offerte agli strati.

## 5. Directory degli artifact

Non applicabile: l’esperimento non produce ancora artifact.

## 6. Note specifiche

Archi di un grafo ausiliario tra offerte con rimborsi simili rappresentano
ridondanza euristica, non necessariamente incompatibilità contrattuale. Le
incompatibilità effettive sono invece vincoli del modello; eliminare offerte
simili può peggiorare l'ottimo.

## 7. Riferimenti

- [Glossario IVASS](https://www.ivass.it/pubblicazioni-e-statistiche/pubblicazioni/relazione-annuale/2023/Relazione_Annuale_2022_glossario_en.pdf?language_id=3): terminologia assicurativa e riassicurativa.
- [Banca dati dei quesiti IVASS](https://www.ivass.it/operatori/intermediari/prova-idoneita/database-quesiti/DATABASE_QUESITI_PROVA_RUI.pdf): contesto sulle coperture riassicurative.
