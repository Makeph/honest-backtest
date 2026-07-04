"""data/fetch.py — pluggable bar fetcher for CME micro futures.

ONE entry point, `fetch_bars(symbol, interval, period)`, dispatched by the
`FUT_DATA_SOURCE` env var to a backend:

    yahoo      (default) free, but intraday capped ~60d -> tiny OOS samples
    databento  CME Globex minute/tick, multi-year, clean   (needs DATABENTO_API_KEY)
    ibkr       Interactive Brokers historical bars          (needs TWS/Gateway running)
    csv        any CSV you export yourself                  (FUT_CSV_PATH or data/csv/)

Every backend returns the SAME contract so nothing downstream changes:
    list of (epoch_ms, open, high, low, close, volume), ascending, NaN-free.

Sub-hourly intervals (5m/15m/30m) for databento/ibkr are aggregated from 1m base
bars via `resample_bars`, aligned to midnight UTC so RTH filtering stays correct.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from honestbacktest.core.instruments import get as get_instrument

CACHE_DIR = Path(os.environ.get("HONESTBACKTEST_CACHE", str(Path.home() / ".cache" / "honestbacktest")))
CSV_DIR = Path(__file__).resolve().parent / "csv"

# bar tuple layout: (epoch_ms, open, high, low, close, volume)


# ── interval / period helpers ────────────────────────────────────────────────
def interval_minutes(interval: str) -> int:
    iv = interval.strip().lower()
    if iv.endswith("m"):
        return int(iv[:-1])
    if iv.endswith("h"):
        return int(iv[:-1]) * 60
    if iv.endswith("d"):
        return int(iv[:-1]) * 1440
    raise ValueError(f"bad interval {interval!r}")


def period_to_start(period: str, end: datetime) -> datetime:
    p = period.strip().lower()
    if p == "max":
        return end - timedelta(days=365 * 10)
    n = int(p[:-1])
    unit = p[-1]
    days = {"d": n, "m": n * 30, "y": n * 365}.get(unit)
    if days is None:
        raise ValueError(f"bad period {period!r}")
    return end - timedelta(days=days)


def resample_bars(bars: list[tuple], target_min: int) -> list[tuple]:
    """Aggregate fine bars into target_min buckets, aligned to midnight UTC."""
    if not bars:
        return bars
    bucket_ms = target_min * 60_000
    out: list[tuple] = []
    cur_key = None
    o = h = l = c = v = None
    t0 = None
    for ts, bo, bh, bl, bc, bv in bars:
        key = ts // bucket_ms
        if key != cur_key:
            if cur_key is not None:
                out.append((t0, o, h, l, c, v))
            cur_key, t0 = key, key * bucket_ms
            o, h, l, c, v = bo, bh, bl, bc, bv
        else:
            h = max(h, bh)
            l = min(l, bl)
            c = bc
            v += bv
    if cur_key is not None:
        out.append((t0, o, h, l, c, v))
    return out


def _clean(rows: list[tuple]) -> list[tuple]:
    """Drop NaN bars, sort ascending by time."""
    good = [r for r in rows if not any(x != x for x in r[1:5])]
    good.sort(key=lambda r: r[0])
    return good


# ── YAHOO backend ────────────────────────────────────────────────────────────
def _yahoo(symbol: str, interval: str, period: str) -> list[tuple]:
    inst = get_instrument(symbol)
    import yfinance as yf
    df = yf.download(inst.data_symbol, interval=interval, period=period,
                     progress=False, auto_adjust=False)
    if df is None or len(df) == 0:
        raise RuntimeError(f"yahoo: no data for {inst.data_symbol} {interval}/{period}")
    rows = []
    for ts, row in df.iterrows():
        def col(name: str) -> float:
            v = row[name]
            return float(v.iloc[0] if hasattr(v, "iloc") else v)
        try:
            vol = col("Volume")
        except Exception:
            vol = 0.0
        rows.append((int(ts.timestamp() * 1000), col("Open"), col("High"),
                     col("Low"), col("Close"), vol))
    return _clean(rows)


# ── DATABENTO backend ────────────────────────────────────────────────────────
def _databento(symbol: str, interval: str, period: str) -> list[tuple]:
    key = os.getenv("DATABENTO_API_KEY")
    if not key:
        raise RuntimeError("databento: set DATABENTO_API_KEY")
    import databento as db
    inst = get_instrument(symbol)
    minutes = interval_minutes(interval)
    # native schemas: ohlcv-1m / -1h / -1d. Sub-hour -> pull 1m and resample.
    if minutes == 1440:
        schema, base_min = "ohlcv-1d", 1440
    elif minutes >= 60 and minutes % 60 == 0:
        schema, base_min = "ohlcv-1h", 60
    else:
        schema, base_min = "ohlcv-1m", 1
    end = datetime.now(timezone.utc)
    start = period_to_start(period, end)
    client = db.Historical(key)
    try:
        data = client.timeseries.get_range(
            dataset="GLBX.MDP3",
            symbols=[f"{inst.symbol}.c.0"],   # continuous front month, calendar roll
            stype_in="continuous",
            schema=schema,
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
        )
        df = data.to_df()
    except Exception as e:
        msg = str(e)
        if "auth" in msg.lower() or "401" in msg:
            raise RuntimeError(
                "databento: authentication failed -- set a real DATABENTO_API_KEY "
                "(yours is missing/placeholder). See databento.com/docs/portal/api-keys"
            ) from None
        raise RuntimeError(f"databento fetch failed for {inst.symbol} {schema}: {msg}") from None
    if df is None or len(df) == 0:
        raise RuntimeError(f"databento: no data for {inst.symbol} {schema}")
    rows = []
    for ts, row in df.iterrows():
        epoch_ms = int(ts.timestamp() * 1000)
        rows.append((epoch_ms, float(row["open"]), float(row["high"]),
                     float(row["low"]), float(row["close"]),
                     float(row.get("volume", 0.0))))
    rows = _clean(rows)
    if base_min != minutes and minutes < 1440:
        rows = resample_bars(rows, minutes)
    return rows


# ── IBKR backend ─────────────────────────────────────────────────────────────
_IB_BARSIZE = {5: "5 mins", 15: "15 mins", 30: "30 mins", 60: "1 hour",
               120: "2 hours", 1440: "1 day"}


def _ibkr(symbol: str, interval: str, period: str) -> list[tuple]:
    try:
        from ib_async import IB, ContFuture
    except ImportError:
        from ib_insync import IB, ContFuture  # fallback to older package
    inst = get_instrument(symbol)
    minutes = interval_minutes(interval)
    base_min = minutes if minutes in _IB_BARSIZE else 1
    bar_size = _IB_BARSIZE.get(base_min, "1 min")
    # duration string from period
    p = period.strip().lower()
    n, unit = int(p[:-1]) if p != "max" else 5, p[-1]
    duration = {"d": f"{n} D", "m": f"{n} M", "y": f"{n} Y", "x": "5 Y"}.get(
        unit if p != "max" else "x", "60 D")

    ib = IB()
    host = os.getenv("IBKR_HOST", "127.0.0.1")
    port = int(os.getenv("IBKR_PORT", "7497"))
    cid = int(os.getenv("IBKR_CLIENT_ID", "17"))
    ib.connect(host, port, clientId=cid, timeout=20)
    try:
        contract = ContFuture(inst.symbol, exchange=inst.exchange)
        ib.qualifyContracts(contract)
        use_rth = os.getenv("IBKR_USE_RTH", "false").lower() == "true"
        bars = ib.reqHistoricalData(
            contract, endDateTime="", durationStr=duration,
            barSizeSetting=bar_size, whatToShow="TRADES",
            useRTH=use_rth, formatDate=2)
    finally:
        ib.disconnect()
    rows = [(int(b.date.timestamp() * 1000), float(b.open), float(b.high),
             float(b.low), float(b.close), float(b.volume)) for b in bars]
    rows = _clean(rows)
    if base_min != minutes and minutes < 1440:
        rows = resample_bars(rows, minutes)
    return rows


# ── CSV backend ──────────────────────────────────────────────────────────────
def _parse_ts(val: str) -> int:
    """Parse a timestamp cell to epoch_ms. Accepts unix s/ms or ISO datetime."""
    s = str(val).strip()
    try:
        f = float(s)
        return int(f if f > 1e11 else f * 1000)   # >1e11 => already ms
    except ValueError:
        pass
    s = s.replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def _csv(symbol: str, interval: str, period: str) -> list[tuple]:
    import csv as _csvmod
    inst = get_instrument(symbol)
    path = os.getenv("FUT_CSV_PATH") or str(CSV_DIR / f"{inst.symbol}_{interval}.csv")
    p = Path(path)
    if not p.exists():
        raise RuntimeError(f"csv: file not found: {path}")
    rows = []
    with p.open(newline="") as f:
        reader = _csvmod.DictReader(f)
        cols = {c.lower().strip(): c for c in (reader.fieldnames or [])}

        def pick(*names):
            for nm in names:
                if nm in cols:
                    return cols[nm]
            raise RuntimeError(f"csv: missing column among {names}; have {list(cols)}")

        tcol = pick("timestamp", "time", "datetime", "date")
        ocol, hcol, lcol, ccol = pick("open", "o"), pick("high", "h"), pick("low", "l"), pick("close", "c")
        try:
            vcol = pick("volume", "vol", "v")
        except RuntimeError:
            vcol = None
        for r in reader:
            rows.append((_parse_ts(r[tcol]), float(r[ocol]), float(r[hcol]),
                         float(r[lcol]), float(r[ccol]),
                         float(r[vcol]) if vcol and r.get(vcol) else 0.0))
    rows = _clean(rows)
    minutes = interval_minutes(interval)
    # CSV is assumed already at `interval`; only resample if the file is finer.
    return rows


_BACKENDS = {"yahoo": _yahoo, "databento": _databento, "ibkr": _ibkr, "csv": _csv}


# ── dispatcher + cache ───────────────────────────────────────────────────────
def _cache_path(source: str, symbol: str, interval: str, period: str) -> Path:
    return CACHE_DIR / f"{source}_{symbol}_{interval}_{period}.json"


def fetch_bars(symbol: str, interval: str = "1h", period: str = "60d",
               use_cache: bool = True, max_age_s: int = 3600,
               source: str | None = None) -> list[tuple]:
    """Fetch OHLCV bars via the configured backend. See module docstring."""
    inst = get_instrument(symbol)
    src = (source or os.getenv("FUT_DATA_SOURCE", "yahoo")).lower()
    if src not in _BACKENDS:
        raise ValueError(f"unknown FUT_DATA_SOURCE {src!r}; known: {sorted(_BACKENDS)}")
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cp = _cache_path(src, inst.symbol, interval, period)
    # csv is local & cheap -> always re-read; others honor the cache.
    if use_cache and src != "csv" and cp.exists() and (time.time() - cp.stat().st_mtime) < max_age_s:
        with cp.open() as f:
            return [tuple(r) for r in json.load(f)]
    rows = _BACKENDS[src](symbol, interval, period)
    if not rows:
        raise RuntimeError(f"{src}: empty result for {inst.symbol} {interval}/{period}")
    with cp.open("w") as f:
        json.dump(rows, f)
    return rows


def span_days(bars: list[tuple]) -> float:
    if len(bars) < 2:
        return 0.0
    return (bars[-1][0] - bars[0][0]) / 86_400_000.0


if __name__ == "__main__":
    import sys
    sym = sys.argv[1] if len(sys.argv) > 1 else "MES"
    iv = sys.argv[2] if len(sys.argv) > 2 else "1h"
    pd = sys.argv[3] if len(sys.argv) > 3 else "60d"
    src = sys.argv[4] if len(sys.argv) > 4 else None
    bars = fetch_bars(sym, iv, pd, use_cache=False, source=src)
    print(f"[{src or os.getenv('FUT_DATA_SOURCE','yahoo')}] {sym} {iv}/{pd}: "
          f"{len(bars)} bars over {span_days(bars):.0f}d, last close={bars[-1][4]:.2f}")
