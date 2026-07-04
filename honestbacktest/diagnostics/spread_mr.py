#!/usr/bin/env python3
"""spread_mr.py — cointegrated SPREAD mean-reversion (judged OOS only).

The genuinely different category: not predicting one asset's direction, but
betting that two ECONOMICALLY LINKED futures revert to their normal relationship.
The common factor (the whole market) cancels between the two legs; what remains
is a cointegrated spread that reverts for structural reasons (physical arbitrage,
substitution, calendar carry) rather than by luck.

Signal: rolling z-score of the log-ratio  s = ln(A) - ln(B).
  z >= +k_entry  -> A rich vs B -> SHORT spread (short A, long B)
  z <= -k_entry  -> A cheap vs B -> LONG  spread (long A, short B)
Exit on revert (|z| <= k_exit) or stop (|z| >= k_stop).

Sizing: notional-neutral — 1 contract of A hedged by h = round(notionalA/notionalB)
contracts of B (computed at entry). Costs charged on BOTH legs (1 + h contracts);
double slippage is the real enemy of spread trading and is modeled honestly.

Verdict = anchored walk-forward net_mean (out-of-sample), reported whatever the sign.

Classic pairs (need both legs fetchable; deep data via Databento recommended):
  MES MNQ   equity index RV
  GC  SI    gold/silver ratio
  GC  HG    gold/copper (risk-on/off)

Usage:
  python -m honestbacktest.diagnostics.spread_mr MES MNQ 5m 1y --folds 8
  python -m honestbacktest.diagnostics.spread_mr GC SI 15m 2y
"""
from __future__ import annotations

import argparse
import math

from honestbacktest.core.instruments import get as get_instrument
from honestbacktest.data.fetch import fetch_bars, span_days

# (N, k_entry, k_stop); k_exit fixed near the mean
PARAM_GRID = [(N, ke, ks)
              for N in (30, 60, 120)
              for ke in (1.5, 2.0, 2.5)
              for ks in (3.0, 4.0)]
K_EXIT = 0.5
PRIMARY = (60, 2.0, 4.0)


def _align(barsA, barsB):
    """Inner-join two bar lists on epoch_ms. Returns [(ts, closeA, closeB), ...]."""
    a = {b[0]: b[4] for b in barsA}
    out = []
    for b in barsB:
        ts = b[0]
        if ts in a:
            out.append((ts, a[ts], b[4]))
    out.sort(key=lambda r: r[0])
    return out


def spread_backtest(rows, instA, instB, N, k_entry, k_stop, k_exit=K_EXIT):
    """rows = aligned [(ts, pxA, pxB)]. Returns $ stats + trade list."""
    trades = []
    pos = None
    buf = []  # rolling log-ratio
    for i, (ts, pa, pb) in enumerate(rows):
        if pa <= 0 or pb <= 0:
            continue
        s = math.log(pa) - math.log(pb)
        buf.append(s)
        if len(buf) > N:
            buf.pop(0)

        if pos:
            z = (s - pos["mean"]) / pos["std"] if pos["std"] > 0 else 0.0
            hit_exit = abs(z) <= k_exit
            hit_stop = abs(z) >= k_stop
            # "long spread" wants z to rise back to 0 from below; revert covers both
            if hit_exit or hit_stop:
                _close(trades, pos, pa, pb, instA, instB, ts)
                pos = None
            continue

        if len(buf) < N:
            continue
        mean = sum(buf) / N
        var = sum((x - mean) ** 2 for x in buf) / N
        std = math.sqrt(var)
        if std <= 0:
            continue
        z = (s - mean) / std
        if abs(z) < k_entry:
            continue
        # notional-neutral hedge computed at entry
        notA = pa * instA.point_value
        notB = pb * instB.point_value
        h = max(1, round(notA / notB))
        side = "SHORT" if z >= k_entry else "LONG"   # SHORT spread = short A / long B
        pos = dict(side=side, eA=pa, eB=pb, h=h, mean=mean, std=std, t0=ts)
    return _report(trades, rows)


def _close(trades, pos, xA, xB, instA, instB, t1):
    dirA = -1 if pos["side"] == "SHORT" else +1
    dirB = +1 if pos["side"] == "SHORT" else -1
    h = pos["h"]
    pnl = dirA * (xA - pos["eA"]) * instA.point_value \
        + dirB * (xB - pos["eB"]) * instB.point_value * h
    cost = instA.rt_cost(1) + instB.rt_cost(h)
    trades.append(dict(net=pnl - cost, gross=pnl, side=pos["side"],
                       h=h, t0=pos["t0"], t1=t1))


def _report(trades, rows):
    if not trades:
        return dict(n=0, trades=[])
    nets = [t["net"] for t in trades]
    n = len(nets)
    wins = [x for x in nets if x > 0]
    losses = [x for x in nets if x <= 0]
    gl = abs(sum(losses)) if losses else 0.0
    cum = peak = mdd = 0.0
    for x in nets:
        cum += x
        peak = max(peak, cum)
        mdd = min(mdd, cum - peak)
    sd = (rows[-1][0] - rows[0][0]) / 86_400_000.0 if len(rows) > 1 else 0.0
    return dict(n=n, net_total=sum(nets), net_mean=sum(nets) / n,
                win_rate=len(wins) / n, mdd=mdd, span_days=sd,
                pf=(sum(wins) / gl) if gl else float("inf"),
                avg_h=sum(t["h"] for t in trades) / n, trades=trades)


def _select_best(rows, instA, instB, min_trades):
    best, bp = None, None
    for p in PARAM_GRID:
        r = spread_backtest(rows, instA, instB, *p)
        if r["n"] < min_trades:
            continue
        if best is None or r["net_total"] > best["net_total"]:
            best, bp = r, p
    return best, bp


def _stats(trades):
    if not trades:
        return None
    nets = [t["net"] for t in trades]
    wins = [x for x in nets if x > 0]
    losses = [x for x in nets if x <= 0]
    gl = abs(sum(losses)) if losses else 0.0
    return dict(n=len(nets), total=sum(nets), mean=sum(nets) / len(nets),
                win=len(wins) / len(nets), pf=(sum(wins) / gl) if gl else float("inf"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("legA")
    ap.add_argument("legB")
    ap.add_argument("interval", nargs="?", default="5m")
    ap.add_argument("period", nargs="?", default="1y")
    ap.add_argument("--folds", type=int, default=8)
    ap.add_argument("--train-frac", type=float, default=0.6)
    args = ap.parse_args()

    instA, instB = get_instrument(args.legA), get_instrument(args.legB)
    barsA = fetch_bars(args.legA, args.interval, args.period)
    barsB = fetch_bars(args.legB, args.interval, args.period)
    rows = _align(barsA, barsB)
    print(f"== SPREAD MR: {instA.symbol}/{instB.symbol} {args.interval}/{args.period} ==")
    print(f"aligned bars={len(rows)} over {span_days([(r[0],0,0,0,0,0) for r in rows]):.0f}d "
          f"| RT cost legA=${instA.rt_cost(1):.2f}/ct legB=${instB.rt_cost(1):.2f}/ct\n")
    if len(rows) < 200:
        print("too few aligned bars — check both legs exist on this source/period.")
        return

    pr = spread_backtest(rows, instA, instB, *PRIMARY)
    if pr["n"]:
        print(f"PRIMARY {PRIMARY} full-window (in-sample, context): n={pr['n']} "
              f"net_mean=${pr['net_mean']:+.2f} PF={pr['pf']:.2f} total=${pr['net_total']:+.2f} "
              f"win={pr['win_rate']*100:.0f}% avg_hedge={pr['avg_h']:.1f}")

    cut = int(len(rows) * args.train_frac)
    tr, bp = _select_best(rows[:cut], instA, instB, 8)
    if tr:
        te = spread_backtest(rows[cut:], instA, instB, *bp)
        ts = _stats(te["trades"])
        print(f"\nTRAIN/TEST: selected {bp} (train n={tr['n']} net_mean=${tr['net_mean']:+.2f} "
              f"PF={tr['pf']:.2f})")
        if ts:
            print(f"  TEST(held-out): n={ts['n']} net_mean=${ts['mean']:+.2f} "
                  f"PF={ts['pf']:.2f} total=${ts['total']:+.2f} win={ts['win']*100:.0f}%")

    n = len(rows)
    seg = n // (args.folds + 1)
    oos = []
    for k in range(1, args.folds + 1):
        train, test = rows[:seg * k], rows[seg * k: seg * (k + 1)]
        if len(test) < 100:
            continue
        _, p = _select_best(train, instA, instB, 6)
        if p is None:
            continue
        oos.extend(spread_backtest(test, instA, instB, *p)["trades"])
    ws = _stats(oos)
    print(f"\nANCHORED WALK-FORWARD ({args.folds} folds) -- THE VERDICT")
    if ws:
        print(f"  OOS: n={ws['n']} net_mean=${ws['mean']:+.2f} PF={ws['pf']:.2f} "
              f"total=${ws['total']:+.2f} win={ws['win']*100:.0f}%")
        v = "POSITIVE -- spread edge survives OOS" if ws["mean"] > 0 \
            else "NEGATIVE -- rejected"
        print(f"  -> {v}  [n={ws['n']}, read honestly]")
    else:
        print("  not enough OOS trades to judge.")


if __name__ == "__main__":
    main()
