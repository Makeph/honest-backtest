# Au2fut — Methodology

> Ported discipline from the au2 / Au2qwen edge investigation (June 2026).
> The one rule that matters: **prove the edge net of REAL costs, out-of-sample
> and forward, BEFORE building execution infra or buying a challenge.**

## Why this project exists

au2 spent months on a BTC scalper and concluded — rigorously, on 8,000+ live
entries — that **no edge cleared costs on BTC retail**, and that prop challenges
were **−EV by construction**: passing requires the directional edge that was
proven absent. The expensive lesson was that they tuned exits for weeks while the
*entry* pointed the wrong way, and that **fees dominated P&L at every timescale**.

Au2fut applies that lesson to a different instrument class — **CME micro futures**
(MES/MNQ/MGC) and **futures prop firms** (Topstep/Apex) — where the cost structure
is genuinely different:

- Futures cost is a few dollars round-turn per micro contract, not bps of a
  notional that scales with leverage.
- Equity-index futures carry a real long-run drift and trend persistence that
  BTC's seconds-scale microstructure did not offer.

That does **not** guarantee an edge. It only means the question is worth re-asking
with an honest model. This repo is that honest model.

## The pipeline (run in order)

1. **`data/fetch.py`** — pull OHLC bars (Yahoo continuous front-month). Cached.
   Good for HTF validation, NOT tick-accurate. Swap for Databento/IBKR/Rithmic
   when validating seriously — the rest is source-agnostic.

2. **`core/instruments.py`** — exact contract specs (tick value, point value) and
   the **dollar cost model** (`pnl_net = gross − commission − slippage_ticks`).
   This is where honesty lives. Set `FUT_RT_COMMISSION` to your real plan rate.

3. **`diagnostics/edge_scan.py`** — vol-gated Donchian breakout + ATR trail,
   swept over a small robust grid, scored in **net $ per contract**. Verdict:
   - `net_mean > 0` across *most* configs (not just best-of-sweep) → edge may be real.
   - `net_mean ≤ 0` → no edge clears costs here; **stop**, do not build.

4. **`core/prop_rules.py`** — the firm's trailing-DD / daily-loss / target machine.
   Tested in `tests/test_prop_rules.py`.

5. **`diagnostics/prop_mc.py`** — bootstrap the empirical trade distribution
   through the prop-rules machine: **P(pass), P(fail), EV vs the challenge fee**,
   as a function of contracts. This is the number that decides whether to proceed.

## Guardrails (non-negotiable)

- **No execution code exists in this phase.** `LIVE_ENABLED=false`. Do not write a
  live executor until step 5 is positive on **out-of-sample** data AND confirmed in
  **forward live-paper** (not just backtest).
- **Best-of-sweep is overfit until proven otherwise.** A positive `edge_scan` on
  60–70 days and 15–40 trades is a hypothesis, not an edge. Re-run on disjoint
  windows and multiple instruments.
- **Calibrate costs to your actual fee schedule** before trusting any EV number.
- **The trailing drawdown, not the daily limit, is usually the real account-killer
  at correct sizing** — let `prop_mc.py --contracts` find the sizing that survives.

## What a positive result must clear before any real money

1. `edge_scan` positive on ≥ 2 disjoint historical windows per instrument.
2. `prop_mc` P(pass) and EV positive at a sizing where P(fail-daily) ≈ 0.
3. A **forward** live-paper run reproducing the backtest's net $/trade within noise.
4. Costs set to the real, contracted fee schedule — not the optimistic default.

Only then does building an executor + prop-risk guard become +EV rather than a
repeat of the au2 mistake.
