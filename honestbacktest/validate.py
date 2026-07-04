#!/usr/bin/env python3
"""validate.py — one honest verdict, any strategy, any instrument.

The single entry point that ties the harness together. Its whole value is the
discipline: it NEVER reports an in-sample number as the verdict. It selects
parameters on a training slice and judges them on held-out data via anchored
walk-forward — the out-of-sample net result is the only number that decides.

    honest-backtest edge   MES 5m 1y          # Donchian breakout
    honest-backtest mr     MES 5m 1y          # session mean-reversion
    honest-backtest spread MES MNQ 5m 1y      # cointegrated spread MR

Set the data source first (yahoo default; databento for deep multi-regime data):
    FUT_DATA_SOURCE=databento  DATABENTO_API_KEY=...

This tool's job is to say NO when the answer is no. On every liquid market and
strategy tested so far (see README), it has. That honesty is the product.
"""
from __future__ import annotations

import argparse

from honestbacktest.core.instruments import get as get_instrument
from honestbacktest.data.fetch import fetch_bars, span_days


# ── generic anchored walk-forward ────────────────────────────────────────────
def anchored_wf(items, select_fn, bt_fn, folds, min_test):
    """Select params on [0:k], trade fold k, stitch the out-of-sample trades."""
    n = len(items)
    seg = n // (folds + 1)
    oos = []
    for k in range(1, folds + 1):
        train, test = items[: seg * k], items[seg * k: seg * (k + 1)]
        if len(test) < min_test:
            continue
        p = select_fn(train)
        if p is None:
            continue
        oos.extend(bt_fn(test, p)["trades"])
    return oos


def _stats(trades):
    if not trades:
        return None
    nets = [t["net"] for t in trades]
    wins = [x for x in nets if x > 0]
    losses = [x for x in nets if x <= 0]
    gl = abs(sum(losses)) if losses else 0.0
    cum = peak = mdd = 0.0
    for x in nets:
        cum += x
        peak = max(peak, cum)
        mdd = min(mdd, cum - peak)
    return dict(n=len(nets), total=sum(nets), mean=sum(nets) / len(nets),
                win=len(wins) / len(nets), mdd=mdd,
                pf=(sum(wins) / gl) if gl else float("inf"))


# ── strategy adapters ────────────────────────────────────────────────────────
def _setup_edge(args):
    from honestbacktest.diagnostics import edge_scan, oos_validate
    inst = get_instrument(args.legA)
    bars = fetch_bars(args.legA, args.interval, args.period)
    select = lambda b: oos_validate._select_best(b, inst, min_trades=6)[1]
    bt = lambda b, p: edge_scan.donchian_backtest(b, inst, *p)
    return bars, select, bt, 30, f"{inst.symbol} Donchian breakout"


def _setup_mr(args):
    from honestbacktest.diagnostics import mr_session as mr
    inst = get_instrument(args.legA)
    bars = fetch_bars(args.legA, args.interval, args.period)
    select = lambda b: mr._select_best(b, inst, 6, mr.RTH_START, mr.RTH_END)[1]
    bt = lambda b, p: mr.mr_backtest(b, inst, *p, mr.RTH_START, mr.RTH_END)
    return bars, select, bt, 50, f"{inst.symbol} session mean-reversion"


def _setup_spread(args):
    from honestbacktest.diagnostics import spread_mr as sp
    instA, instB = get_instrument(args.legA), get_instrument(args.legB)
    rows = sp._align(fetch_bars(args.legA, args.interval, args.period),
                     fetch_bars(args.legB, args.interval, args.period))
    select = lambda r: sp._select_best(r, instA, instB, 6)[1]
    bt = lambda r, p: sp.spread_backtest(r, instA, instB, *p)
    return rows, select, bt, 100, f"{instA.symbol}/{instB.symbol} cointegrated spread MR"


_SETUP = {"edge": _setup_edge, "mr": _setup_mr, "spread": _setup_spread}


def main():
    ap = argparse.ArgumentParser(description="Honest OOS edge verdict.")
    ap.add_argument("strategy", choices=sorted(_SETUP))
    ap.add_argument("legA")
    ap.add_argument("legB", nargs="?", default=None, help="second leg (spread only)")
    ap.add_argument("interval", nargs="?", default="5m")
    ap.add_argument("period", nargs="?", default="1y")
    ap.add_argument("--folds", type=int, default=8)
    args = ap.parse_args()

    if args.strategy == "spread" and not args.legB:
        ap.error("spread needs two legs, e.g. `honest-backtest spread MES MNQ 5m 1y`")
    # for non-spread, a value landing in legB is actually the interval/period
    if args.strategy != "spread" and args.legB:
        args.legB, args.interval, args.period = None, args.legB, args.interval

    items, select, bt, min_test, label = _SETUP[args.strategy](args)
    span = span_days(items if items and len(items[0]) >= 5
                     else [(r[0], 0, 0, 0, 0, 0) for r in items])
    print(f"== HONEST EDGE VERDICT: {label} ==")
    print(f"   {args.interval}/{args.period}  |  {len(items)} bars  |  {span:.0f}d\n")
    if len(items) < min_test * 2:
        print("   too little data to judge — widen period or use a deeper source.")
        return

    oos = anchored_wf(items, select, bt, args.folds, min_test)
    ws = _stats(oos)
    if not ws:
        print("   not enough out-of-sample trades to judge (signal too rare here).")
        return
    print(f"   OUT-OF-SAMPLE ({args.folds}-fold walk-forward):")
    print(f"     trades   {ws['n']}")
    print(f"     net/trade  ${ws['mean']:+.2f}")
    print(f"     total      ${ws['total']:+.2f}")
    print(f"     PF         {ws['pf']:.2f}      win {ws['win']*100:.0f}%      maxDD ${ws['mdd']:+.2f}")
    verdict = "EDGE SURVIVES OOS" if ws["mean"] > 0 and ws["pf"] > 1.0 else "NO EDGE (rejected)"
    print(f"\n   >>> {verdict}   [n={ws['n']}, read honestly]")
    if ws["mean"] > 0 and ws["pf"] > 1.0:
        print("   Next: stress slippage (FUT_SLIPPAGE_TICKS=2/3), more regimes, forward paper.")
    else:
        print("   This strategy/market does not clear costs out-of-sample. Do not deploy.")


if __name__ == "__main__":
    main()
