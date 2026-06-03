#!/usr/bin/env python3
"""mr_session.py — PRE-REGISTERED session mean-reversion test (judged OOS only).

Hypothesis (registered BEFORE seeing results, see README/this docstring):
  During the US cash session (RTH), index futures over-extend and revert to a
  session mean. Fade Bollinger extremes: SHORT when close > mean + k*std,
  LONG when close < mean - k*std; exit on revert to mean, stop beyond, and force
  FLAT at the session close (no overnight -> prop-friendly). This is the INVERSE
  of the (net-negative) Donchian breakout and has a real microstructure basis
  (open auction over-reaction, dealer hedging).

Discipline: the in-sample sweep is NOT the verdict. The verdict is the anchored
walk-forward net_mean (out-of-sample). Reported honestly whatever the sign.

Registered primary config: N=20, k_entry=2.0, k_stop=3.5, interval=15m.
Robustness grid swept around it; selection on TRAIN only.

RTH window is UTC minutes. US cash open 09:30 ET = 13:30 UTC under EDT (the recent
data window is summer 2026 -> EDT). Override via --rth-start/--rth-end if needed.

Usage:
  python -m diagnostics.mr_session MES 15m 60d
  python -m diagnostics.mr_session MNQ 5m 60d --folds 5
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone

from core.instruments import Instrument, get as get_instrument
from data.fetch import fetch_bars, span_days

# registered defaults
RTH_START = 13 * 60 + 30      # 13:30 UTC = 09:30 ET (EDT)
RTH_END = 20 * 60            # 20:00 UTC = 16:00 ET (EDT)

# (N, k_entry, k_stop) — primary registered config first
PARAM_GRID = [(N, ke, ks)
              for N in (14, 20, 30)
              for ke in (1.5, 2.0, 2.5)
              for ks in (2.5, 3.5)]
PRIMARY = (20, 2.0, 3.5)


def _min_of_day_utc(epoch_ms: int) -> int:
    dt = datetime.fromtimestamp(epoch_ms / 1000, tz=timezone.utc)
    return dt.hour * 60 + dt.minute


def _session_id(epoch_ms: int) -> int:
    return int(epoch_ms // 86_400_000)


def _in_rth(epoch_ms: int, rth_start: int, rth_end: int) -> bool:
    m = _min_of_day_utc(epoch_ms)
    return rth_start <= m < rth_end


def mr_backtest(bars: list[tuple], inst: Instrument, N: int, k_entry: float,
                k_stop: float, rth_start: int = RTH_START, rth_end: int = RTH_END) -> dict:
    """Bollinger session-fade. Flat at session close. $ per 1 contract."""
    trades: list[dict] = []
    pos: dict | None = None
    closes: list[float] = []      # rolling session closes, reset each session
    cur_session = None

    for i, b in enumerate(bars):
        ts, c = b[0], b[4]
        in_rth = _in_rth(ts, rth_start, rth_end)
        sid = _session_id(ts)

        # session boundary -> force flat + reset rolling stats
        new_session = (sid != cur_session)
        next_in_rth = (i + 1 < len(bars)) and _in_rth(bars[i + 1][0], rth_start, rth_end) \
            and _session_id(bars[i + 1][0]) == sid
        if new_session:
            if pos:  # safety: shouldn't carry across sessions, but enforce
                _close(trades, pos, c, inst, ts)
                pos = None
            closes = []
            cur_session = sid

        if not in_rth:
            continue

        closes.append(c)
        if len(closes) > N:
            closes.pop(0)

        # manage open position first
        if pos:
            hit_stop = (c <= pos["stop"]) if pos["side"] == "LONG" else (c >= pos["stop"])
            hit_target = (c >= pos["mean"]) if pos["side"] == "LONG" else (c <= pos["mean"])
            if hit_stop or hit_target or not next_in_rth:
                _close(trades, pos, c, inst, ts)
                pos = None
            continue

        if len(closes) < N:
            continue
        mean = sum(closes) / N
        var = sum((x - mean) ** 2 for x in closes) / N
        std = var ** 0.5
        if std <= 0 or not next_in_rth:   # don't open on the last RTH bar
            continue

        z = (c - mean) / std
        if z >= k_entry:                  # too high -> fade short
            pos = dict(side="SHORT", entry=c, t0=ts, mean=mean, stop=c + k_stop * std)
        elif z <= -k_entry:               # too low -> fade long
            pos = dict(side="LONG", entry=c, t0=ts, mean=mean, stop=c - k_stop * std)

    return _report(trades, bars)


def _close(trades, pos, exit_px, inst, t1):
    move = (exit_px - pos["entry"]) if pos["side"] == "LONG" else (pos["entry"] - exit_px)
    trades.append(dict(net=inst.pnl_net(move, 1), side=pos["side"], t0=pos["t0"], t1=t1))


def _report(trades, bars):
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
    return dict(n=n, net_total=sum(nets), net_mean=sum(nets) / n,
                win_rate=len(wins) / n, mdd=mdd,
                pf=(sum(wins) / gl) if gl else float("inf"),
                span_days=span_days(bars), trades=trades)


def run_primary(symbol, interval, period):
    """Full-window backtest of the registered PRIMARY config. For prop_mc.

    Returns a dict with 'trades' (each having t1/net), comparable to edge_scan.
    In-sample — read P(pass) built on this as optimistic; the OOS verdict lives
    in main()'s walk-forward.
    """
    inst = get_instrument(symbol)
    bars = fetch_bars(symbol, interval, period)
    r = mr_backtest(bars, inst, *PRIMARY, RTH_START, RTH_END)
    return r, PRIMARY


def _select_best(bars, inst, min_trades, rs, re):
    best, bp = None, None
    for p in PARAM_GRID:
        r = mr_backtest(bars, inst, *p, rs, re)
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
    ap.add_argument("symbol", nargs="?", default="MES")
    ap.add_argument("interval", nargs="?", default="15m")
    ap.add_argument("period", nargs="?", default="60d")
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--train-frac", type=float, default=0.6)
    ap.add_argument("--rth-start", type=int, default=RTH_START)
    ap.add_argument("--rth-end", type=int, default=RTH_END)
    args = ap.parse_args()

    inst = get_instrument(args.symbol)
    bars = fetch_bars(args.symbol, args.interval, args.period)
    print(f"== session MR (PRE-REGISTERED): {inst.symbol} {args.interval}/{args.period} ==")
    print(f"RTH {args.rth_start//60:02d}:{args.rth_start%60:02d}-{args.rth_end//60:02d}:{args.rth_end%60:02d} UTC  "
          f"| {len(bars)} bars / {span_days(bars):.0f}d | RT cost ${inst.rt_cost(1):.2f}\n")

    # registered primary config, full-window (context only, NOT the verdict)
    pr = mr_backtest(bars, inst, *PRIMARY, args.rth_start, args.rth_end)
    if pr["n"]:
        print(f"PRIMARY {PRIMARY} full-window (in-sample, context only): "
              f"n={pr['n']} net_mean=${pr['net_mean']:+.2f} PF={pr['pf']:.2f} "
              f"total=${pr['net_total']:+.2f} win={pr['win_rate']*100:.0f}%")

    # train/test
    cut = int(len(bars) * args.train_frac)
    tr_best, bp = _select_best(bars[:cut], inst, 8, args.rth_start, args.rth_end)
    if tr_best:
        te = mr_backtest(bars[cut:], inst, *bp, args.rth_start, args.rth_end)
        ts = _stats(te["trades"])
        print(f"\nTRAIN/TEST: selected {bp} on train (n={tr_best['n']}, "
              f"net_mean=${tr_best['net_mean']:+.2f}, PF={tr_best['pf']:.2f})")
        if ts:
            print(f"  TEST(held-out): n={ts['n']} net_mean=${ts['mean']:+.2f} "
                  f"PF={ts['pf']:.2f} total=${ts['total']:+.2f} win={ts['win']*100:.0f}%")

    # anchored walk-forward — THE VERDICT
    n = len(bars)
    seg = n // (args.folds + 1)
    oos = []
    for k in range(1, args.folds + 1):
        train, test = bars[:seg * k], bars[seg * k: seg * (k + 1)]
        if len(test) < 50:
            continue
        _, p = _select_best(train, inst, 6, args.rth_start, args.rth_end)
        if p is None:
            continue
        oos.extend(mr_backtest(test, inst, *p, args.rth_start, args.rth_end)["trades"])
    ws = _stats(oos)
    print(f"\nANCHORED WALK-FORWARD ({args.folds} folds) -- THE VERDICT")
    if ws:
        print(f"  OOS: n={ws['n']} net_mean=${ws['mean']:+.2f} PF={ws['pf']:.2f} "
              f"total=${ws['total']:+.2f} win={ws['win']*100:.0f}%")
        v = "POSITIVE -- hypothesis survives OOS" if ws["mean"] > 0 \
            else "NEGATIVE -- hypothesis rejected"
        print(f"  -> {v}  [n={ws['n']}, read honestly]")
    else:
        print("  not enough OOS trades to judge.")


if __name__ == "__main__":
    main()
