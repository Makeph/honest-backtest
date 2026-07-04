#!/usr/bin/env python3
"""oos_validate.py — the test that separates a real edge from an overfit one.

edge_scan picks the BEST Donchian config on the whole window — that number is
optimistic by construction (best-of-sweep). This tool does the honest thing:

  • TRAIN/TEST split: select params ONLY on the train slice, then evaluate those
    exact params on the held-out test slice the selector never saw.
  • ANCHORED WALK-FORWARD: repeat across K folds — select on everything up to
    fold i, trade fold i+1 — and stitch the out-of-sample trades into one curve.

If the train-selected params stay net-positive on test/OOS, the edge is plausible.
If test collapses while train looked great, it was curve-fit (au2's trap).

Sample sizes on free Yahoo data are small — read the n_test honestly; a handful
of OOS trades is suggestive, not conclusive. Deeper data (Databento/IBKR) later.

Usage:
  python -m honestbacktest.diagnostics.oos_validate MES 1h 60d
  python -m honestbacktest.diagnostics.oos_validate MNQ 1d 2y --folds 4
"""
from __future__ import annotations

import argparse

from honestbacktest.core.instruments import get as get_instrument
from honestbacktest.data.fetch import fetch_bars, span_days
from honestbacktest.diagnostics.edge_scan import PARAM_GRID, donchian_backtest


def _select_best(bars, inst, min_trades=8):
    """Pick the param tuple with best net_total on `bars` (>= min_trades)."""
    best, best_p = None, None
    for p in PARAM_GRID:
        r = donchian_backtest(bars, inst, *p)
        if r["n"] < min_trades:
            continue
        if best is None or r["net_total"] > best["net_total"]:
            best, best_p = r, p
    return best, best_p


def train_test(symbol, interval, period, train_frac=0.6):
    inst = get_instrument(symbol)
    bars = fetch_bars(symbol, interval, period)
    cut = int(len(bars) * train_frac)
    train, test = bars[:cut], bars[cut:]
    tr_best, p = _select_best(train, inst, min_trades=6)
    if not tr_best:
        return None
    te = donchian_backtest(test, inst, *p)
    return dict(inst=inst, params=p, train=tr_best, test=te,
                train_days=span_days(train), test_days=span_days(test))


def walk_forward(symbol, interval, period, folds=4):
    """Anchored walk-forward: select on [0:i], trade fold i, stitch OOS trades."""
    inst = get_instrument(symbol)
    bars = fetch_bars(symbol, interval, period)
    n = len(bars)
    seg = n // (folds + 1)        # first segment is train-only seed
    oos_trades: list[dict] = []
    for k in range(1, folds + 1):
        train = bars[: seg * k]
        test = bars[seg * k: seg * (k + 1)]
        if len(test) < 30:
            continue
        _, p = _select_best(train, inst, min_trades=5)
        if p is None:
            continue
        r = donchian_backtest(test, inst, *p)
        oos_trades.extend(r["trades"])
    return inst, oos_trades


def _stats(trades):
    if not trades:
        return None
    nets = [t["net"] for t in trades]
    wins = [x for x in nets if x > 0]
    losses = [x for x in nets if x <= 0]
    gl = abs(sum(losses)) if losses else 0.0
    return dict(n=len(nets), total=sum(nets), mean=sum(nets) / len(nets),
                win=len(wins) / len(nets),
                pf=(sum(wins) / gl) if gl else float("inf"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("symbol", nargs="?", default="MES")
    ap.add_argument("interval", nargs="?", default="1h")
    ap.add_argument("period", nargs="?", default="60d")
    ap.add_argument("--train-frac", type=float, default=0.6)
    ap.add_argument("--folds", type=int, default=4)
    args = ap.parse_args()

    print(f"== OOS validation: {args.symbol} {args.interval}/{args.period} ==\n")

    tt = train_test(args.symbol, args.interval, args.period, args.train_frac)
    if tt is None:
        print("train slice produced too few trades — widen period/interval.")
    else:
        tr, te = tt["train"], tt["test"]
        print(f"TRAIN/TEST split ({args.train_frac:.0%} / {1-args.train_frac:.0%})")
        print(f"  selected params on TRAIN: Donchian {tt['params']}")
        print(f"  TRAIN ({tt['train_days']:.0f}d): n={tr['n']:>3}  "
              f"net_mean=${tr['net_mean']:+7.2f}  PF={tr['pf']:.2f}  total=${tr['net_total']:+9.2f}")
        ts = _stats(te["trades"])
        if ts:
            print(f"  TEST  ({tt['test_days']:.0f}d): n={ts['n']:>3}  "
                  f"net_mean=${ts['mean']:+7.2f}  PF={ts['pf']:.2f}  total=${ts['total']:+9.2f}  "
                  f"win={ts['win']*100:.0f}%")
            verdict = "HOLDS out-of-sample" if ts["mean"] > 0 else "COLLAPSES out-of-sample (overfit)"
            print(f"  -> edge {verdict}  [n_test={ts['n']}, read honestly]")
        else:
            print("  TEST: no trades on held-out slice (params too selective / slice too short)")

    print()
    inst, oos = walk_forward(args.symbol, args.interval, args.period, args.folds)
    ws = _stats(oos)
    print(f"ANCHORED WALK-FORWARD ({args.folds} folds, stitched OOS)")
    if ws:
        print(f"  OOS: n={ws['n']:>3}  net_mean=${ws['mean']:+7.2f}  PF={ws['pf']:.2f}  "
              f"total=${ws['total']:+9.2f}  win={ws['win']*100:.0f}%")
        verdict = "POSITIVE" if ws["mean"] > 0 else "NEGATIVE"
        print(f"  -> stitched out-of-sample edge is {verdict}  [n={ws['n']}, read honestly]")
    else:
        print("  not enough OOS trades to judge — need deeper data.")


if __name__ == "__main__":
    main()
