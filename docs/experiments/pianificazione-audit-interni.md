# Pianificazione degli audit interni

## 1. Descrizione del problema

La proposta, non ancora eseguibile, seleziona interventi di audit sulla base
delle giornate richieste e delle aree di rischio coperte. L'obiettivo è coprire
tutte le aree obbligatorie minimizzando le giornate complessive.

## 2. Formulazione matematica

Siano $I$ gli interventi candidati e $R$ le aree obbligatorie. La variabile
$\delta_i \in \{0,1\}$ indica la selezione dell'intervento $i$. Il modello
proposto di copertura è:

$$
\begin{aligned}
\min\quad & \sum_{i\in I} c_i\delta_i \\
\text{s.t.}\quad & \sum_{i\in I} a_{ri}\delta_i \ge 1 && r\in R.
\end{aligned}
$$

Tutti i vincoli di copertura sono attivi. Se un'area non è coperta da alcun
intervento candidato, il modello è infattibile.

## 3. CLI unificata

Non disponibile: l’esperimento non è ancora eseguibile.

## 4. Parametri

- $c_i \ge 0$: giornate richieste dall'intervento $i$.
- $a_{ri} \in \{0,1\}$: indica se l'intervento $i$ copre l'area $r$.
- $I$ e $R$: catalogo degli interventi e insieme delle aree obbligatorie.

## 5. Directory degli artifact

Non applicabile: l’esperimento non produce ancora artifact.

## 6. Note specifiche

Nel grafo ausiliario, archi tra interventi simili indicano ridondanza, non
incompatibilità. Una riduzione può proteggere gli interventi indispensabili e
verificare che ogni area resti copribile; in caso contrario occorre ampliare il
dominio o segnalare il fallimento. La copribilità non preserva necessariamente
il piano a costo minimo.

## 7. Riferimenti

- [OR-Library, set covering](https://people.brunel.ac.uk/~mastjjb/jeb/orlib/scpinfo.html): istanze e formulazione del problema di copertura.
- [Attività di audit, Intesa Sanpaolo](https://group.intesasanpaolo.com/it/sostenibilita/governo-sostenibilita/integrita-nella-condotta-aziendale): contesto della pianificazione degli audit.
