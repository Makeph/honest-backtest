# Au2fut — Un harnais de validation d'edge quantitatif (et un résultat négatif honnête)

> **Ce que ce projet démontre :** une recherche quantitative rigoureuse qui
> *réfute* des hypothèses de trading au lieu de les sur-ajuster en faux gagnants.
> Sur 8 combinaisons stratégie/marché, avec des données de qualité
> institutionnelle, il aboutit à un verdict défendable — **aucun edge accessible
> au retail ne couvre les coûts** — et, surtout, expose la méthodologie qui rend
> ce verdict fiable.
>
> Un backtest qui « gagne » toujours ne prouve rien. Un harnais capable de dire
> **non** — et d'expliquer précisément pourquoi — est l'instrument plus rare et
> plus précieux.

---

## Le problème

Le trading systématique retail est dominé par le biais du survivant et le
sur-apprentissage : balayez assez de paramètres et une configuration paraît
toujours rentable en in-sample. L'objectif ici était l'inverse de l'optimisme :
construire un outillage assez rigoureux pour **tuer mes propres idées** avant de
risquer le moindre capital — spécifiquement sur les **micro-futures CME** et les
**challenges de prop firms futures** (Topstep/Apex).

## Méthodologie (la partie qui compte)

| Principe | Mise en œuvre |
|---|---|
| **Modèle de coût honnête** | P&L en dollars à partir des specs exactes du contrat (valeur du tick, valeur du point) moins commission *et* slippage en ticks — pas des bps de notionnel. Coût configurable et stress-testé. |
| **Hypothèses pré-enregistrées** | La config primaire de chaque stratégie est écrite *avant* de voir les résultats, pour empêcher le data-mining d'un gagnant chanceux. |
| **Out-of-sample uniquement** | Le verdict n'est **jamais** un chiffre in-sample. Les paramètres sont sélectionnés sur un échantillon d'entraînement et jugés par **walk-forward ancré** sur des données jamais vues. |
| **Données profondes, multi-régimes** | Une couche de données pluggable (Yahoo / Databento / IBKR / CSV) permet de faire tourner le même code sur une année complète de données minute CME propres — des centaines de trades OOS indépendants, pas une fenêtre chanceuse de 60 jours. |
| **Robustesse adversariale** | Balayages de sensibilité au slippage, Monte-Carlo des règles prop, et honnêteté sur la taille d'échantillon (`[n=…, read honestly]`) sur chaque résultat. |

## Résultats

Tous les chiffres sont **out-of-sample** (walk-forward ancré), nets de coûts
futures réalistes, sur 1 an de données minute CME Databento sauf indication.

| Hypothèse | Marché | Trades OOS | Net/trade | PF | Verdict |
|---|---|---:|---:|---:|---|
| Breakout Donchian | MES 5m | 247 | −$4.78 | 0.89 | rejeté |
| Mean-reversion de session | MES 5m | 184 | −$5.76 | 0.84 | rejeté |
| Mean-reversion de session | MNQ 5m | 279 | −$2.68 | 0.96 | rejeté |
| Mean-reversion de session | MGC (or) | 164 | +$1.67 | 1.03 | bruit (meurt à +0.5 tick) |
| Mean-reversion de session | MCL (pétrole) | 589 | −$2.38 | 0.89 | rejeté |
| Spread MR co-intégré | MES/MNQ 5m | 1084 | −$2.01 | 0.95 | rejeté (arbitré) |
| Spread MR co-intégré | GC/SI daily | ~11 | — | — | statistiquement sous-puissant |
| Challenge prop (Monte-Carlo) | — | — | — | — | −EV par construction sans edge directionnel |

Les travaux antérieurs sur les perpétuels BTC (projet précédent) ont
indépendamment abouti à la même conclusion : signal directionnel anti-prédictif,
mean-reversion morte, tendance HTF mangée par les frais, carry de funding sous le
taux sans risque.

## Trois trouvailles à souligner

1. **Le piège des données courtes, pris en flagrant délit.** Sur une fenêtre de
   60 jours, la mean-reversion de session ressemblait à un *vrai* edge (positif en
   OOS sur quatre combinaisons instrument/timeframe). Une année complète de
   données profondes l'a révélé comme un **artefact de régime** — disparu.
   Démonstration manuelle de pourquoi les backtests courts et les balayages
   in-sample ne sont pas fiables, et pourquoi la couche de données a été conçue
   pour passer à l'échelle.

2. **L'exécution domine le signal.** Le mince edge apparent survivait à 1–2 ticks
   de slippage et **mourait à 3 ticks**. Tout l'effet vivait à l'intérieur du
   bid/ask — exactement là où une stratégie de fade du momentum paie le plus.
   Chiffré, pas supposé.

3. **Le dilemme des spreads.** Les spreads rapides (valeur-relative entre indices)
   ont des données en abondance mais sont arbitrés à zéro ; les spreads lents
   économiquement réels (ratio or/argent) reviennent à la moyenne sur des
   semaines, donnant ~une douzaine de trades en deux ans — **statistiquement
   infalsifiables** avec des données retail. Un plafond structurel, identifié
   plutôt qu'éludé.

## Architecture

```
core/instruments.py   specs exactes micros CME + modèle de coût $ (surchargeable env)
core/prop_rules.py    moteur trailing-DD / daily-loss / target Topstep/Apex (9 tests)
data/fetch.py         barres pluggables : yahoo | databento | ibkr | csv, resampling 1m→Nm
diagnostics/
  edge_scan.py        breakout Donchian, verdict net $
  mr_session.py       mean-reversion de session pré-enregistrée
  spread_mr.py        spread MR co-intégré, notional-neutre, coûts sur les deux jambes
  oos_validate.py     train/test + walk-forward ancré
  prop_mc.py          Monte-Carlo de P(pass)/EV via le moteur de règles prop
validate.py           une CLI : verdict OOS honnête pour toute stratégie × instrument
```

Propre, testé, agnostique à la source. Passer d'un flux gratuit à des données
institutionnelles ne change qu'une variable d'environnement ; le code stratégie
ne bouge jamais.

## Compétences démontrées

- **Discipline de recherche quantitative** — pré-enregistrement, validation
  out-of-sample, anti-sur-apprentissage, l'honnêteté intellectuelle de publier un
  résultat négatif.
- **Microstructure de marché & modélisation des coûts** — mécanique des contrats
  futures, géométrie du trailing-drawdown prop, slippage comme variable de
  premier ordre.
- **Ingénierie logicielle** — Python modulaire, abstraction de données pluggable,
  simulation Monte-Carlo, moteur de règles testé, CLI unifiée, structure prête
  pour la CI.
- **Ingénierie des données** — intégration Databento / IBKR / Yahoo, alignement
  des timestamps, resampling, caching, gestion des flux creux et dégradés.

## La conclusion honnête

Le système fonctionne. Sa réponse répétée — *aucun edge qui couvre les coûts sur
les marchés liquides accessibles au retail* — est la bonne, et elle a évité de
risquer du capital réel à courir après un mirage. La valeur livrée n'est pas une
machine à billets (celles-ci sont vendues par des gens qui n'en ont pas) ; c'est
un **instrument rigoureux pour distinguer le signal du bruit**, et la discipline
de lui faire confiance.

---

*Stack : Python · pandas/numpy · Databento · pytest. Recherche uniquement ;
aucun code d'exécution live n'existe par conception tant qu'un edge n'est pas
prouvé en OOS et en forward.*
