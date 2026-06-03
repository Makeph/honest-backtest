"""instruments.py — CME micro futures contract specs.

The foundation of an HONEST cost model. On futures, P&L is not bps of notional —
it is (ticks moved) x (tick value $) x (contracts), minus commission per contract
and slippage measured in ticks. Getting these numbers right is the whole game:
au2 proved on crypto that execution cost > signal. Here we make cost explicit.

All specs are public, well-known CME contract specifications (2024-2026).
`data_symbol` is the Yahoo Finance continuous-front-month ticker used by
data/fetch.py — it is a stitched continuous series, fine for edge validation at
HTF, NOT for tick-accurate execution.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Instrument:
    symbol: str            # CME root, e.g. "MES"
    name: str
    data_symbol: str       # Yahoo Finance continuous ticker, e.g. "MES=F"
    tick_size: float       # minimum price increment (index pts / $ / etc.)
    tick_value: float      # $ per one tick per one contract
    exchange: str = "CME"  # listing exchange (CME/COMEX/NYMEX) for IBKR/Databento
    # Default frictions for a retail-via-prop micro fill. Override per firm/plan.
    rt_commission: float = 1.00   # $ round-turn commission per contract (entry+exit)
    slippage_ticks: float = 1.0   # ticks lost to slippage per round turn (both sides)

    @property
    def point_value(self) -> float:
        """$ per one full index/price point per contract."""
        return self.tick_value / self.tick_size

    def ticks(self, price_move: float) -> float:
        """Convert a raw price move into number of ticks."""
        return price_move / self.tick_size

    def pnl_gross(self, price_move: float, contracts: int = 1) -> float:
        """$ P&L before costs for a directional price move (sign = direction)."""
        return self.ticks(price_move) * self.tick_value * contracts

    def rt_cost(self, contracts: int = 1) -> float:
        """$ round-turn cost: commission + slippage, per `contracts`."""
        slip = self.slippage_ticks * self.tick_value
        return (self.rt_commission + slip) * contracts

    def pnl_net(self, price_move: float, contracts: int = 1) -> float:
        """$ P&L after commission + slippage for a round-turn trade."""
        return self.pnl_gross(price_move, contracts) - self.rt_cost(contracts)


# ── CME micro contract registry ──────────────────────────────────────────────
# tick_value and tick_size are exact contract specs. rt_commission defaults are
# conservative prop-plan micro rates (Topstep/Apex micros ~ $0.70-$1.34 RT);
# override via PropPlan / env when you know your fee schedule.

MES = Instrument("MES", "Micro E-mini S&P 500",     "MES=F", tick_size=0.25, tick_value=1.25, exchange="CME")
MNQ = Instrument("MNQ", "Micro E-mini Nasdaq-100",  "MNQ=F", tick_size=0.25, tick_value=0.50, exchange="CME")
M2K = Instrument("M2K", "Micro E-mini Russell 2000","M2K=F", tick_size=0.10, tick_value=0.50, exchange="CME")
MYM = Instrument("MYM", "Micro E-mini Dow",         "MYM=F", tick_size=1.00, tick_value=0.50, exchange="CBOT")
MGC = Instrument("MGC", "Micro Gold (10 oz)",       "MGC=F", tick_size=0.10, tick_value=1.00, exchange="COMEX")
MCL = Instrument("MCL", "Micro WTI Crude (100 bbl)","MCL=F", tick_size=0.01, tick_value=1.00, exchange="NYMEX")
GC  = Instrument("GC",  "Gold (100 oz)",            "GC=F",  tick_size=0.10, tick_value=10.00, exchange="COMEX")
SI  = Instrument("SI",  "Silver (5000 oz)",         "SI=F",  tick_size=0.005, tick_value=25.00, exchange="COMEX")
HG  = Instrument("HG",  "Copper (25000 lb)",        "HG=F",  tick_size=0.0005, tick_value=12.50, exchange="COMEX")

def _apply_env(inst: Instrument) -> Instrument:
    """Override commission/slippage from env (FUT_RT_COMMISSION / FUT_SLIPPAGE_TICKS).

    Calibrate these to YOUR real prop plan fee schedule before trusting any EV.
    Used to stress-test cost assumptions (e.g. doubling slippage).
    """
    import dataclasses
    import os
    comm = os.getenv("FUT_RT_COMMISSION")
    slip = os.getenv("FUT_SLIPPAGE_TICKS")
    if comm is None and slip is None:
        return inst
    return dataclasses.replace(
        inst,
        rt_commission=float(comm) if comm is not None else inst.rt_commission,
        slippage_ticks=float(slip) if slip is not None else inst.slippage_ticks,
    )


REGISTRY: dict[str, Instrument] = {x.symbol: x for x in
                                   (MES, MNQ, M2K, MYM, MGC, MCL, GC, SI, HG)}


def get(symbol: str) -> Instrument:
    """Look up an instrument by CME root (case-insensitive), with env cost overrides."""
    key = symbol.upper().replace("=F", "")
    if key not in REGISTRY:
        raise KeyError(f"unknown instrument {symbol!r}; known: {sorted(REGISTRY)}")
    return _apply_env(REGISTRY[key])
