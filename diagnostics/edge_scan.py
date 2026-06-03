#!/usr/bin/env python3
"""edge_scan.py — Does a simple, robust trend edge clear REAL futures costs?

This is the verdict tool, ported from au2's htf_backtest discipline but rebuilt
in DOLLAR terms with the futures cost model (commission per contract + slippage
in ticks), not bps of notional.

Hypothesis under test (the only one au2 left standing): at minutes/hours scale,
real index/commodity moves dwarf the ~$2-3 round-turn micro cost, so a vol-gated
Donchian breakout can show positive NET $ per trade. If it can't even here, a
prop challenge on this instrument is -EV by construction (au2's conclusion) and
we do NOT build execution infra.

Strategy: Donchian(N) breakout, ATR-trailing stop, exit on opposite Donchian(exitN)
or stop. Vol gate skips bars where ATR% < min_atr_pct (dead market — costs win).

Outputs $ stats per 1 contract and exposes `run_best()` for prop_mc.py.

Usage:
  python -m diagnostics.edge_scan MES 1h 60d
  python -m diagnostics.edge_scan MNQ 15m 60d
"""
from __future__ import annotations

import sys

from core.instruments import Instrument, get as get_instrument
from data.fetch import fetch_bars, span_days


def _atr(bars: list[tuple], i: int, n: int) -> float | None:
    if i < n:
        return None
    s = 0.0
    for j in range(i - n + 1, i + 1):
        h, l, pc = bars[j][2], bars[j][3], bars[j - 1][4]
        s += max(h - l, abs(h - pc), abs(l - pc))
    return s / n


def donchian_backtest(bars: list[tuple], inst: Instrument, N: int, exitN: int,
                      min_atr_pct: float, atr_stop_mult: float) -> dict:
    """Run one Donchian config. Returns $ stats per 1 contract + trade list."""
    trades: list[dict] = []
    pos: dict | None = None

    for i in range(N + 1, len(bars)):
        c = bars[i][4]
        hi_n = max(b[2] for b in bars[i - N:i])
        lo_n = min(b[3] for b in bars[i - N:i])
        hi_x = max(b[2] for b in bars[i - exitN:i])
        lo_x = min(b[3] for b in bars[i - exitN:i])
        a = _atr(bars, i, N)
        if a is None:
            continue
        atr_pct = a / c * 100.0

        if pos:
            if pos["side"] == "LONG":
                pos["stop"] = max(pos["stop"], c - atr_stop_mult * a)
                if c <= pos["stop"] or c <= lo_x:
                    _close(trades, pos, c, inst, bars[i][0])
                    pos = None
            else:
                pos["stop"] = min(pos["stop"], c + atr_stop_mult * a)
                if c >= pos["stop"] or c >= hi_x:
                    _close(trades, pos, c, inst, bars[i][0])
                    pos = None
            if pos:
                continue

        if atr_pct < min_atr_pct:        # vol gate: skip dead markets
            continue
        if c > hi_n:
            pos = dict(side="LONG", entry=c, t0=bars[i][0], stop=c - atr_stop_mult * a)
        elif c < lo_n:
            pos = dict(side="SHORT", entry=c, t0=bars[i][0], stop=c + atr_stop_mult * a)

    return _report(trades, bars)


def _close(trades: list[dict], pos: dict, exit_px: float, inst: Instrument, t1: int) -> None:
    move = (exit_px - pos["entry"]) if pos["side"] == "LONG" else (pos["entry"] - exit_px)
    net = inst.pnl_net(move, contracts=1)
    trades.append(dict(net=net, gross=inst.pnl_gross(move, 1), side=pos["side"],
                       t0=pos["t0"], t1=t1))


def _report(trades: list[dict], bars: list[tuple]) -> dict:
    if not trades:
        return dict(n=0, trades=[])
    nets = [t["net"] for t in trades]
    n = len(nets)
    tot = sum(nets)
    wins = [x for x in nets if x > 0]
    losses = [x for x in nets if x <= 0]
    cum = peak = mdd = 0.0
    for x in nets:
        cum += x
        peak = max(peak, cum)
        mdd = min(mdd, cum - peak)
    sd = span_days(bars)
    gross_loss = abs(sum(losses)) if losses else 0.0
    return dict(
        n=n, net_total=tot, net_mean=tot / n,
        win_rate=len(wins) / n,
        avg_win=sum(wins) / len(wins) if wins else 0.0,
        avg_loss=sum(losses) / len(losses) if losses else 0.0,
        mdd=mdd, span_days=sd,
        pf=(sum(wins) / gross_loss) if gross_loss else float("inf"),
        trades=trades,
    )


PARAM_GRID = [(N, exitN, ma, sx)
              for N in (20, 40, 60)
              for exitN in (N // 2, N // 4)
              for ma in (0.0, 0.15, 0.3)
              for sx in (2.0, 3.0)]


def run_best(symbol: str, interval: str, period: str) -> tuple[dict, tuple]:
    """Sweep the grid, return (best stats dict, best param tuple). For prop_mc."""
    inst = get_instrument(symbol)
    bars = fetch_bars(symbol, interval, period)
    best, best_p = None, None
    for (N, exitN, ma, sx) in PARAM_GRID:
        r = donchian_backtest(bars, inst, N, exitN, ma, sx)
        if r["n"] < 10:
            continue
        if best is None or r["net_total"] > best["net_total"]:
            best, best_p = r, (N, exitN, ma, sx)
    return (best or dict(n=0, trades=[]), best_p)


def main() -> None:
    sym = sys.argv[1] if len(sys.argv) > 1 else "MES"
    interval = sys.argv[2] if len(sys.argv) > 2 else "1h"
    period = sys.argv[3] if len(sys.argv) > 3 else "60d"

    inst = get_instrument(sym)
    print(f"fetching {inst.symbol} ({inst.name}) {interval}/{period} ...")
    bars = fetch_bars(sym, interval, period)
    print(f"got {len(bars)} bars over {span_days(bars):.0f} days")
    print(f"cost model: tick=${inst.tick_value:.2f}  RT commission=${inst.rt_commission:.2f}  "
          f"slippage={inst.slippage_ticks} ticks  => RT cost=${inst.rt_cost(1):.2f}/contract\n")

    print("DONCHIAN BREAKOUT + ATR-trail + vol-gate  ($ per 1 contract)")
    hdr = (f"{'N':>4} {'exitN':>5} {'minATR%':>7} {'stopx':>5} | {'n':>4} "
           f"{'net_mean':>9} {'win%':>5} {'avgW':>8} {'avgL':>8} {'PF':>5} "
           f"{'net_total':>10} {'maxDD':>9}")
    print(hdr)
    print("-" * len(hdr))

    best, best_p = None, None
    for (N, exitN, ma, sx) in PARAM_GRID:
        r = donchian_backtest(bars, inst, N, exitN, ma, sx)
        if r["n"] < 10:
            continue
        print(f"{N:>4} {exitN:>5} {ma:>7.2f} {sx:>5.1f} | {r['n']:>4} "
              f"{r['net_mean']:>+9.2f} {r['win_rate']*100:>4.0f}% {r['avg_win']:>+8.2f} "
              f"{r['avg_loss']:>+8.2f} {r['pf']:>5.2f} {r['net_total']:>+10.2f} {r['mdd']:>+9.2f}")
        if best is None or r["net_total"] > best["net_total"]:
            best, best_p = r, (N, exitN, ma, sx)

    if not best:
        print("\nNo config produced >= 10 trades. Inconclusive — widen period/interval.")
        return

    N, exitN, ma, sx = best_p
    ann = best["net_total"] * (365.0 / max(best["span_days"], 1.0))
    print(f"\nBEST: Donchian N={N} exitN={exitN} minATR%={ma} stopx={sx}")
    print(f"  n={best['n']} over {best['span_days']:.0f}d  "
          f"net_mean=${best['net_mean']:+.2f}/trade  win={best['win_rate']*100:.0f}%  "
          f"PF={best['pf']:.2f}")
    print(f"  net_total=${best['net_total']:+.2f}  maxDD=${best['mdd']:+.2f}  "
          f"~${ann:+.0f}/yr per 1 contract (no compounding)")
    print()
    if best["net_mean"] > 0 and best["pf"] > 1.0:
        print("  net_mean > 0 net of REAL futures costs => a trend edge MAY exist here.")
        print("  NEXT: this is best-of-sweep (overfit risk). Validate out-of-sample and")
        print("  forward in live-paper before ANY prop attempt. Then run prop_mc.py.")
    else:
        print("  net_mean <= 0 net of costs => no edge clears costs on this instrument/TF.")
        print("  A prop challenge here is -EV by construction (au2's verdict). Do NOT deploy.")


if __name__ == "__main__":
    main()
