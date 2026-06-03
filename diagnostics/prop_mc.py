#!/usr/bin/env python3
"""prop_mc.py — Monte Carlo: what is P(pass) of the prop challenge, given the edge?

Chains the two honest pieces:
  1. edge_scan.run_best() -> empirical per-trade $ distribution (per 1 contract).
  2. core.prop_rules AccountState -> the firm's trailing-DD / daily-loss / target
     machine.

We bootstrap synthetic trading days from the empirical trades, scale to `contracts`,
and run thousands of challenge attempts. Output: P(pass), P(fail by trailing DD),
P(fail by daily limit), and a crude EV vs the challenge fee.

This is the number that matters. au2's prop_mc concluded crypto challenges are -EV
*by construction* because passing requires the directional edge that is absent.
If edge_scan shows net_mean <= 0 here, this will show P(pass) at or below the
break-even-on-noise rate — confirming the same verdict for this instrument.

Usage:
  python -m diagnostics.prop_mc MES 1h 60d topstep_50k --contracts 4 --fee 165
"""
from __future__ import annotations

import argparse
import random
from collections import defaultdict

from core.prop_rules import PRESETS, AccountState, Outcome
from diagnostics.edge_scan import run_best
from diagnostics.mr_session import run_primary as run_mr_primary


def _empirical_days(trades: list[dict]) -> list[list[float]]:
    """Group per-trade net $ (1 contract) into calendar trading days by exit time."""
    by_day: dict[int, list[float]] = defaultdict(list)
    for t in trades:
        day = t["t1"] // 86_400_000      # exit epoch-ms -> day bucket
        by_day[day].append(t["net"])
    return [pnls for _, pnls in sorted(by_day.items())]


def _simulate_attempt(day_pool: list[list[float]], rules, contracts: int,
                      max_days: int, rng: random.Random) -> Outcome:
    state = AccountState(rules)
    for _ in range(max_days):
        day = rng.choice(day_pool)
        # scale to contracts; intraday low = worst running cumulative within the day
        running = 0.0
        low = 0.0
        for net in day:
            running += net * contracts
            low = min(low, running)
        day_pnl = running
        intraday_low = state.balance + low
        intraday_high = state.balance + max(0.0, running)
        out = state.apply_day(day_pnl, intraday_low=intraday_low,
                              intraday_high=intraday_high)
        if out is not Outcome.ACTIVE:
            return out
    return state.outcome


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("symbol", nargs="?", default="MES")
    ap.add_argument("interval", nargs="?", default="1h")
    ap.add_argument("period", nargs="?", default="60d")
    ap.add_argument("preset", nargs="?", default="topstep_50k")
    ap.add_argument("--contracts", type=int, default=4)
    ap.add_argument("--max-days", type=int, default=40)
    ap.add_argument("--trials", type=int, default=20_000)
    ap.add_argument("--fee", type=float, default=165.0, help="challenge fee $ (sunk)")
    ap.add_argument("--funded-ev", type=float, default=2_000.0,
                    help="expected $ realized from a PASSED account (payouts, net)")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--strategy", choices=["breakout", "mr"], default="breakout",
                    help="breakout=edge_scan Donchian; mr=session mean-reversion")
    args = ap.parse_args()

    if args.preset not in PRESETS:
        raise SystemExit(f"unknown preset {args.preset!r}; known: {sorted(PRESETS)}")
    rules = PRESETS[args.preset]

    if args.strategy == "mr":
        best, best_p = run_mr_primary(args.symbol, args.interval, args.period)
    else:
        best, best_p = run_best(args.symbol, args.interval, args.period)
    if best["n"] < 10:
        raise SystemExit("strategy produced too few trades; widen period/interval.")
    trades = best["trades"]
    day_pool = _empirical_days(trades)

    print(f"== prop_mc: {args.symbol} {args.interval}/{args.period} -> {rules.firm_name} "
          f"${rules.account_size:,.0f} ==")
    print(f"edge: best Donchian {best_p}  n={best['n']}  "
          f"net_mean=${best['net_mean']:+.2f}/trade (1 ct)  PF={best['pf']:.2f}")
    print(f"sizing: {args.contracts} contracts  |  {len(day_pool)} empirical days in pool")
    print(f"rules: target=${rules.profit_target:,.0f}  trail=${rules.max_trailing_loss:,.0f} "
          f"({rules.trailing_mode})  daily_limit=${rules.daily_loss_limit:,.0f}\n")

    rng = random.Random(args.seed)
    counts = {Outcome.PASSED: 0, Outcome.FAILED_TRAILING: 0,
              Outcome.FAILED_DAILY: 0, Outcome.ACTIVE: 0}
    for _ in range(args.trials):
        counts[_simulate_attempt(day_pool, rules, args.contracts, args.max_days, rng)] += 1

    n = args.trials
    p_pass = counts[Outcome.PASSED] / n
    p_trail = counts[Outcome.FAILED_TRAILING] / n
    p_daily = counts[Outcome.FAILED_DAILY] / n
    p_active = counts[Outcome.ACTIVE] / n
    print(f"P(pass)            = {p_pass*100:6.2f}%")
    print(f"P(fail trailing)   = {p_trail*100:6.2f}%")
    print(f"P(fail daily)      = {p_daily*100:6.2f}%")
    print(f"P(unresolved/{args.max_days}d) = {p_active*100:6.2f}%")

    ev = p_pass * args.funded_ev - args.fee
    print(f"\nEV per attempt = P(pass)*${args.funded_ev:,.0f} - fee ${args.fee:,.0f} "
          f"= ${ev:+,.2f}")
    if ev > 0:
        print("EV > 0 -- but this rides on an in-sample best-of-sweep edge. Confirm OOS +")
        print("forward live-paper before risking real challenge fees.")
    else:
        print("EV <= 0 -- buying this challenge loses money in expectation. (au2's verdict.)")


if __name__ == "__main__":
    main()
