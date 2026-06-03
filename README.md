# Au2fut — CME Micro Futures Prop Edge Harness

> **Research only. No live trading, no execution code.** This phase answers one
> question honestly: *does a tradeable edge survive real futures costs and a prop
> firm's drawdown rules?* Built on the discipline of the au2 / Au2qwen edge
> investigation (see [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md)).

## Why

au2 proved on BTC that a prop challenge is **−EV by construction** when no edge
clears costs. Au2fut re-asks the question on **CME micro futures** (MES/MNQ/MGC)
and **futures prop firms** (Topstep/Apex), where costs are a few $ per contract
and equity indices carry real trend — but it refuses to build any trading infra
until the edge is proven net of costs, out-of-sample and forward.

## Install

```bash
pip install -r requirements.txt
cp .env.example .env      # research-only; no live keys
```

## The pipeline

```
data/fetch.py        bars — pluggable source (yahoo|databento|ibkr|csv), cached
  └─ core/instruments.py    exact tick value + $ cost model (env-overridable)
       └─ diagnostics/edge_scan.py   breakout net $/contract verdict
       └─ diagnostics/mr_session.py  session mean-reversion (pre-registered, OOS)
            └─ diagnostics/oos_validate.py   train/test + walk-forward OOS
                 └─ core/prop_rules.py    Topstep/Apex trailing-DD machine
                      └─ diagnostics/prop_mc.py   P(pass), EV (--strategy mr|breakout)
```

## Data sources (set `FUT_DATA_SOURCE`)

| Source | Depth | Setup |
|---|---|---|
| `yahoo` (default) | intraday ~60d (tiny OOS) | none |
| `databento` | CME Globex minute/tick, multi-year | `pip install databento`, `DATABENTO_API_KEY` |
| `ibkr` | IBKR historical (pacing-limited) | `pip install ib_async`, TWS/Gateway running |
| `csv` | whatever you export | `data/csv/<SYM>_<interval>.csv` or `FUT_CSV_PATH` |

Sub-hourly bars (5m/15m/30m) for databento/ibkr are aggregated from 1m, aligned
to midnight UTC so RTH filtering stays correct. **All diagnostics are
source-agnostic** — switching `FUT_DATA_SOURCE` changes nothing in the strategy
code. The whole point: re-run the MR OOS verdict on years of multi-regime data
the moment you plug in Databento/IBKR.

## Run it

One command, any strategy, honest out-of-sample verdict (never an in-sample number):

```bash
python validate.py edge   MES 5m 1y        # Donchian breakout
python validate.py mr     MES 5m 1y        # session mean-reversion
python validate.py spread MES MNQ 5m 1y    # cointegrated spread MR
```

For deep multi-regime data (the only way to trust the verdict), set the source:

```bash
# PowerShell:  $env:FUT_DATA_SOURCE="databento"; $env:DATABENTO_API_KEY="db-..."
FUT_DATA_SOURCE=databento DATABENTO_API_KEY=db-... python validate.py mr MNQ 5m 1y
```

Lower-level tools the CLI wraps:

```bash
python -m data.fetch MES 1h 60d                                   # sanity-check data
python -m diagnostics.edge_scan  MES 1h 60d                       # in-sample sweep (context)
python -m diagnostics.prop_mc    MES 5m 1y topstep_50k --strategy mr --contracts 2
python -m pytest tests/ -q                                        # trust the rule engine
```

## First read — and why it did NOT survive honest OOS

In-sample (`edge_scan`, whole window) looked encouraging:

| Metric | In-sample result |
|---|---|
| MES 1h Donchian | positive across ~22/24 configs, best ~$48/trade PF 1.54 |
| MNQ 1h Donchian | strongly positive (~$21k/yr/contract best) |
| Topstep 50K P(pass) @ 2 ct (`prop_mc`) | ~59% |

Then `oos_validate.py` (select params on train, trade held-out test) deflated it:

| Test | OOS result | Verdict |
|---|---|---|
| MES 1h walk-forward | net_mean **−$0.19**, PF **1.00** (n=20) | **edge gone** — in-sample was a fit |
| MNQ 1h walk-forward | net_mean +$75, PF 1.39 (n=18) | weakly positive, **too thin** |
| MES/MNQ/MGC 1d 2y | n=4–12 per slice, signs flip | **noise — inconclusive** |

Pushing Yahoo to its limit (5m/60d ≈ 13k bars) gave a statistically real OOS sample
— and it was conclusive:

| Instrument | TF | OOS n | net_mean | PF | win% |
|---|---|---|---|---|---|
| MES | 5m | **162** | **−$7.88** | 0.73 | 31% |
| MNQ | 5m | **160** | **−$15.38** | 0.80 | 41% |
| MES | 30m | 33 | −$6.61 | 0.93 | 30% |
| MNQ | 30m | 37 | −$59.51 | 0.73 | 30% |

**Verdict (Donchian breakout, MES/MNQ intraday, this data): no edge.** Every TF
collapses OOS — TRAIN PF 1.4–19, TEST negative, the textbook overfit signature. The
n=162 5m sample is large enough to trust. The cheap futures cost structure did NOT
rescue it because the *signal itself* is non-predictive intraday — the same thing
au2 found for the seconds-scale BTC signal. The in-sample 59% prop pass-rate was a
complete mirage.

**Scope of this verdict:** it kills the *breakout* hypothesis on *these* instruments
on *this* data — not "no edge of any kind exists." Testing more strategy families is
possible but must be done OOS-first / pre-registered to avoid data-mining a false
winner (test enough strategies and one looks great in-sample by luck). Deeper minute
data (Databento/IBKR) would also let mean-reversion / session strategies be judged
on hundreds of OOS trades — see `docs/METHODOLOGY.md`.

## Session mean-reversion — the first hypothesis to SURVIVE OOS

`diagnostics/mr_session.py` (pre-registered: fade Bollinger extremes inside RTH,
flat at close — the *inverse* of breakout). Anchored walk-forward, OOS:

| Instrument | TF | OOS n | net_mean | PF | survives 2-tick slip? | 3-tick? |
|---|---|---|---|---|---|---|
| MES | 5m | 68 | +$5.67 → +$4.42 | 1.22 | **yes** (+$4.42) | **no** (−$2.14) |
| MNQ | 5m | 90 | +$3.13 → +$2.63 | 1.05 | yes (thin) | — |
| MES | 15m | 29 | +$16.76 | 1.86 | — | — |

On the shallow 60-71d Yahoo window this looked like the first thing across BTC
*and* futures to survive a pre-registered OOS test — but **deep data killed it.**

### Deep-data verdict (Databento, 1 full year, 5m) — MR EDGE IS DEAD

| Instrument | OOS n | net_mean | PF | verdict |
|---|---|---|---|---|
| MES 5m 1y | 184 | **−$5.76** | 0.84 | rejected |
| MNQ 5m 1y | 279 | **−$2.68** | 0.96 | rejected |

Both negative even in-sample (MES −$4.89, MNQ −$2.41 over 441/427 trades). The
summer-2026 positive was a **regime artifact** — gone on a multi-regime year. The
few euros of Databento bought certainty and saved a real-capital deposit. This is
the same verdict au2 reached on BTC: **no edge clears costs.** The line below about
"thin but real" applied only to the shallow window and no longer holds.

(Historical note — the shallow-data reading that did NOT survive:) the edge was
~3-4 ticks gross and died at 3-tick slippage; fading the open is where slippage is
worst.

**Does it pass a prop challenge? No, not reliably** (`prop_mc --strategy mr`, MES
5m, Topstep 50K, 2-tick slip): P(pass) ~0% at 1 ct, ~5% at 2 ct, ~28% at 4 ct —
but 4 ct carries a **64% blow-up rate**. The thin edge can't both hit a fixed-$
target and survive a fixed-$ trailing drawdown at the size required. Same
structural wall au2's crypto prop_mc found.

**Where it *could* matter:** a personal account (no deadline, no trailing DD,
small size, slow compounding) — not "fast cash," and only if real execution
slippage stays ≤ 2 ticks. Mandatory next steps before any money: deeper minute
data across multiple regimes, and forward live-paper measuring *actual* fill
slippage on the open fade.

## Layout

```
Au2fut/
├── core/
│   ├── instruments.py   CME micro specs + $ cost model
│   └── prop_rules.py    Topstep/Apex trailing-DD / daily-loss / target engine
├── data/
│   └── fetch.py         Yahoo bar fetcher (cached); swap for Databento/IBKR later
├── diagnostics/
│   ├── edge_scan.py     vol-gated Donchian backtest, net $ verdict
│   └── prop_mc.py       Monte Carlo P(pass)/EV through the prop rules
├── tests/               prop-rules engine tests (9, all green)
└── docs/METHODOLOGY.md  the discipline, ported from au2
```

## Status / next steps

- [x] Honest $ cost model + prop-rules engine (tested)
- [x] Edge-scan + prop Monte Carlo, runnable on real data
- [x] OOS validation (`oos_validate.py`) — **in-sample edge did NOT survive on free data**
- [ ] **Deeper data**: minute bars w/ years of history (Databento/IBKR) → swap `data/fetch.py`
- [ ] Re-run OOS for a statistically meaningful sample (target ≥ 100 OOS trades)
- [ ] Calibrate `FUT_RT_COMMISSION` to a real prop plan fee schedule
- [ ] Forward live-paper to confirm backtest net $/trade
- [ ] *Only then*: executor + prop-risk guard (port from au2 `prop_guard.py`)
```
