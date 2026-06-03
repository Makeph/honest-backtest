# Au2fut — A Quantitative Edge-Validation Harness (and an honest negative result)

> **What this project demonstrates:** disciplined quantitative research that
> *falsifies* trading hypotheses instead of curve-fitting them into false
> winners. Across 8 strategy/market combinations on institutional-grade data, it
> reaches a defensible verdict — **no retail-accessible edge clears costs** — and,
> more importantly, shows the methodology that makes that verdict trustworthy.
>
> A backtest that always "wins" proves nothing. A harness that can say **no** —
> and explains exactly why — is the rarer and more valuable instrument.

---

## The problem

Retail systematic trading is dominated by survivorship bias and overfitting:
sweep enough parameters and one configuration always looks profitable in-sample.
The goal here was the opposite of optimism — to build tooling rigorous enough to
**kill my own ideas** before any capital is risked, specifically for **CME micro
futures** and **futures prop-firm challenges** (Topstep/Apex).

## Methodology (the part that matters)

| Principle | Implementation |
|---|---|
| **Honest cost model** | P&L in dollars from exact contract specs (tick value, point value) minus commission *and* slippage in ticks — not bps of notional. Cost is configurable and stress-tested. |
| **Pre-registered hypotheses** | Each strategy's primary config is written down *before* seeing results, to prevent data-mining a lucky winner. |
| **Out-of-sample only** | The verdict is **never** an in-sample number. Parameters are selected on a training slice and judged by an **anchored walk-forward** on held-out data. |
| **Deep, multi-regime data** | A pluggable data layer (Yahoo / Databento / IBKR / CSV) lets the same code run on a full year of clean CME minute data — hundreds of independent OOS trades, not a lucky 60-day window. |
| **Adversarial robustness** | Slippage-sensitivity sweeps, prop-rule Monte Carlo, and sample-size honesty (`[n=…, read honestly]`) on every result. |

## Results

All figures are **out-of-sample** (anchored walk-forward), net of realistic
futures costs, on 1 year of Databento CME minute data unless noted.

| Hypothesis | Market | OOS trades | Net/trade | PF | Verdict |
|---|---|---:|---:|---:|---|
| Donchian breakout | MES 5m | 247 | −$4.78 | 0.89 | rejected |
| Session mean-reversion | MES 5m | 184 | −$5.76 | 0.84 | rejected |
| Session mean-reversion | MNQ 5m | 279 | −$2.68 | 0.96 | rejected |
| Session mean-reversion | MGC (gold) | 164 | +$1.67 | 1.03 | noise (dies at +0.5 tick) |
| Session mean-reversion | MCL (crude) | 589 | −$2.38 | 0.89 | rejected |
| Cointegrated spread MR | MES/MNQ 5m | 1084 | −$2.01 | 0.95 | rejected (arbitraged) |
| Cointegrated spread MR | GC/SI daily | ~11 | — | — | statistically underpowered |
| Prop challenge (Monte Carlo) | — | — | — | — | −EV by construction without a directional edge |

Earlier work on BTC perpetuals (predecessor project) independently reached the
same conclusion: directional signal anti-predictive, mean-reversion dead, HTF
trend eaten by fees, funding carry below the risk-free rate.

## Three findings worth highlighting

1. **The shallow-data trap, caught in the act.** On a 60-day window, session
   mean-reversion looked like a *genuine* edge (positive OOS across four
   instrument/timeframe combinations). A full year of deep data revealed it as a
   **regime artifact** — gone. This is a textbook demonstration of why short
   backtests and in-sample sweeps cannot be trusted, and why the data layer was
   built to scale.

2. **Execution dominates signal.** The thin apparent edge survived 1–2 ticks of
   slippage and **died at 3 ticks**. The entire effect lived inside the
   bid/ask — exactly where a momentum-fade strategy pays the most. Quantified, not
   assumed.

3. **The spread dilemma.** Fast spreads (equity-index relative value) have ample
   data but are arbitraged to zero; the economically-real slow cointegrated
   spreads (gold/silver ratio) mean-revert over weeks, yielding ~a dozen trades in
   two years — **statistically unfalsifiable** with retail data. A structural
   ceiling, identified rather than hand-waved.

## Architecture

```
core/instruments.py   exact CME micro specs + dollar cost model (env-overridable)
core/prop_rules.py    Topstep/Apex trailing-DD / daily-loss / target engine (9 tests)
data/fetch.py         pluggable bars: yahoo | databento | ibkr | csv, 1m→Nm resampling
diagnostics/
  edge_scan.py        Donchian breakout, $-net verdict
  mr_session.py       pre-registered session mean-reversion
  spread_mr.py        cointegrated spread MR, notional-neutral, costs on both legs
  oos_validate.py     train/test + anchored walk-forward
  prop_mc.py          Monte Carlo of P(pass)/EV through the prop-rule engine
validate.py           one CLI: honest OOS verdict for any strategy × instrument
```

Clean, tested, source-agnostic. Switching from a free feed to institutional data
changes one environment variable; the strategy code never moves.

## Skills demonstrated

- **Quantitative research discipline** — pre-registration, out-of-sample
  validation, anti-overfitting, the intellectual honesty to publish a negative
  result.
- **Market microstructure & cost modeling** — futures contract mechanics, prop
  firm trailing-drawdown geometry, slippage as a first-class variable.
- **Software engineering** — modular Python, pluggable data abstraction,
  Monte Carlo simulation, a tested rule engine, a unified CLI, CI-ready layout.
- **Data engineering** — integrating Databento / IBKR / Yahoo, timestamp
  alignment, resampling, caching, handling sparse and degraded feeds.

## The honest bottom line

The system works. Its repeated answer — *no edge that clears costs on liquid
markets retail can access* — is the correct one, and it saved real capital from
chasing a mirage. The value delivered is not a money-printer (those are sold by
people who don't have one); it is a **rigorous instrument for telling the
difference between signal and noise**, and the discipline to trust it.

---

*Stack: Python · pandas/numpy · Databento · pytest. Research-only; no live
execution code exists by design until an edge is proven OOS and forward.*
