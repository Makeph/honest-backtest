"""prop_rules.py — Futures prop-firm challenge rules + account state engine.

Futures prop firms (Topstep, Apex, TakeProfitTrader, …) do NOT use the percentage
daily/total drawdown model of crypto CFD firms. They use:

  • A **trailing maximum loss** in dollars that follows the account's high-water
    mark UP but never down. Two flavors:
      - EOD-trailing (Topstep): the peak used to trail is end-of-day balance.
      - intraday-trailing (Apex): the peak includes intraday unrealized highs.
    Once balance dips below (peak - max_loss), the account is FAILED.
  • An optional **daily loss limit** in dollars (Topstep has one; Apex does not).
  • A **profit target** in dollars to pass the evaluation.
  • A **consistency rule**: no single day may exceed X% of total profit.
  • A **minimum number of trading days**.

This module is the auditable rulebook + a stateful evaluator. It is market-agnostic
($ in / $ out); diagnostics/prop_mc.py drives it with a trade distribution to
estimate P(pass) vs P(blow). NO trade logic lives here.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum


class Outcome(str, Enum):
    ACTIVE = "active"
    PASSED = "passed"
    FAILED_TRAILING = "failed_trailing_drawdown"
    FAILED_DAILY = "failed_daily_loss_limit"


@dataclass(frozen=True)
class PropRules:
    """Immutable rule set for one futures prop evaluation account."""

    firm_name: str = "Topstep"
    account_size: float = 50_000.0

    # ── Trailing maximum loss (the account-killer) ──────────────────────────
    max_trailing_loss: float = 2_000.0      # $ below the trailing peak = fail
    trailing_mode: str = "eod"              # "eod" | "intraday"
    # Once the trailing threshold has climbed to the starting balance + buffer,
    # some firms freeze it (Topstep freezes once it reaches start+ the max loss).
    trail_freeze_at_start: bool = True

    # ── Daily loss limit ────────────────────────────────────────────────────
    daily_loss_limit: float = 1_000.0       # 0 = no daily limit (e.g. Apex)

    # ── Profit target ─────────────────────────────────────────────────────────
    profit_target: float = 3_000.0

    # ── Consistency / day-count constraints ────────────────────────────────
    min_trading_days: int = 2
    consistency_pct: float = 0.0            # max % of total profit from one day; 0 = off

    # ── Our own safety buffers (stricter than the firm, like au2's AMBER/RED) ─
    daily_stop_buffer: float = 0.0          # stop trading this day if daily PnL <= -(limit - buffer)
    trailing_stop_buffer: float = 0.0       # halt if within this $ of the trailing wall

    @property
    def fail_balance_floor_initial(self) -> float:
        """The balance level that fails the account at the very start."""
        return self.account_size - self.max_trailing_loss

    @property
    def pass_balance(self) -> float:
        return self.account_size + self.profit_target


@dataclass
class AccountState:
    """Mutable evaluation state, driven trade-by-trade or day-by-day."""

    rules: PropRules
    balance: float = field(init=False)
    peak_balance: float = field(init=False)   # high-water mark that drives the trail
    trailing_floor: float = field(init=False)  # current fail level (peak - max_loss)
    day_start_balance: float = field(init=False)
    trading_days: int = 0
    best_day_profit: float = 0.0
    total_profit_at_best_day: float = 0.0
    outcome: Outcome = Outcome.ACTIVE

    def __post_init__(self) -> None:
        r = self.rules
        self.balance = r.account_size
        self.peak_balance = r.account_size
        self.trailing_floor = r.account_size - r.max_trailing_loss
        self.day_start_balance = r.account_size

    # ── trailing-floor maintenance ──────────────────────────────────────────
    def _update_trail(self, equity: float) -> None:
        """Raise the trailing floor as equity makes new highs (never lowers)."""
        r = self.rules
        if equity > self.peak_balance:
            self.peak_balance = equity
            new_floor = self.peak_balance - r.max_trailing_loss
            # Topstep-style: trail freezes once it reaches the starting balance.
            if r.trail_freeze_at_start:
                new_floor = min(new_floor, r.account_size)
            self.trailing_floor = max(self.trailing_floor, new_floor)

    def mark_intraday_high(self, equity: float) -> None:
        """For intraday-trailing firms, feed the running unrealized high."""
        if self.rules.trailing_mode == "intraday":
            self._update_trail(equity)

    # ── the core transition ───────────────────────────────────────────────
    def apply_day(self, day_pnl: float, intraday_low: float | None = None,
                  intraday_high: float | None = None) -> Outcome:
        """Apply one trading day's realized PnL plus optional intraday extremes.

        intraday_low/high are equity excursions WITHIN the day (balance units).
        Returns the (possibly terminal) outcome.
        """
        if self.outcome is not Outcome.ACTIVE:
            return self.outcome

        r = self.rules
        self.day_start_balance = self.balance
        self.trading_days += 1

        # intraday peak can raise the trail before we check the floor (Apex)
        if intraday_high is not None:
            self.mark_intraday_high(intraday_high)

        # check the worst intraday excursion against the trailing wall + daily limit
        low_equity = intraday_low if intraday_low is not None else self.balance + min(day_pnl, 0.0)
        if low_equity <= self.trailing_floor:
            self.balance = low_equity
            self.outcome = Outcome.FAILED_TRAILING
            return self.outcome
        if r.daily_loss_limit > 0 and (low_equity - self.day_start_balance) <= -r.daily_loss_limit:
            self.balance = self.day_start_balance - r.daily_loss_limit
            self.outcome = Outcome.FAILED_DAILY
            return self.outcome

        # settle the day
        self.balance += day_pnl
        if r.trailing_mode == "eod":
            self._update_trail(self.balance)
        else:
            self._update_trail(self.balance)  # close also counts as a high

        # consistency bookkeeping
        if day_pnl > self.best_day_profit:
            self.best_day_profit = day_pnl
            self.total_profit_at_best_day = self.balance - r.account_size

        # pass check (must also satisfy min days + consistency)
        if self.balance >= r.pass_balance and self._passes_constraints():
            self.outcome = Outcome.PASSED
        return self.outcome

    def _passes_constraints(self) -> bool:
        r = self.rules
        if self.trading_days < r.min_trading_days:
            return False
        if r.consistency_pct > 0:
            total = self.balance - r.account_size
            if total > 0 and self.best_day_profit > r.consistency_pct / 100.0 * total:
                return False
        return True


# ── Presets (public eval specs, 2024-2026; verify against current firm terms) ─

TOPSTEP_50K = PropRules(
    firm_name="Topstep", account_size=50_000.0,
    max_trailing_loss=2_000.0, trailing_mode="eod", trail_freeze_at_start=True,
    daily_loss_limit=1_000.0, profit_target=3_000.0,
    min_trading_days=2, consistency_pct=0.0,
)

TOPSTEP_150K = PropRules(
    firm_name="Topstep", account_size=150_000.0,
    max_trailing_loss=4_500.0, trailing_mode="eod", trail_freeze_at_start=True,
    daily_loss_limit=3_300.0, profit_target=9_000.0,
    min_trading_days=2,
)

APEX_50K = PropRules(
    firm_name="Apex", account_size=50_000.0,
    max_trailing_loss=2_500.0, trailing_mode="intraday", trail_freeze_at_start=False,
    daily_loss_limit=0.0, profit_target=3_000.0,
    min_trading_days=1, consistency_pct=30.0,
)

APEX_100K = PropRules(
    firm_name="Apex", account_size=100_000.0,
    max_trailing_loss=3_000.0, trailing_mode="intraday", trail_freeze_at_start=False,
    daily_loss_limit=0.0, profit_target=6_000.0,
    min_trading_days=1, consistency_pct=30.0,
)

PRESETS: dict[str, PropRules] = {
    "topstep_50k": TOPSTEP_50K,
    "topstep_150k": TOPSTEP_150K,
    "apex_50k": APEX_50K,
    "apex_100k": APEX_100K,
}


def load_rules_from_env() -> PropRules:
    """Load a preset by FUT_PROP_PRESET, with $-value env overrides on top."""
    name = os.getenv("FUT_PROP_PRESET", "topstep_50k").lower()
    base = PRESETS.get(name, TOPSTEP_50K)
    return PropRules(
        firm_name=os.getenv("FUT_PROP_FIRM", base.firm_name),
        account_size=float(os.getenv("FUT_PROP_ACCOUNT_SIZE", base.account_size)),
        max_trailing_loss=float(os.getenv("FUT_PROP_MAX_TRAILING_LOSS", base.max_trailing_loss)),
        trailing_mode=os.getenv("FUT_PROP_TRAILING_MODE", base.trailing_mode),
        trail_freeze_at_start=os.getenv(
            "FUT_PROP_TRAIL_FREEZE", str(base.trail_freeze_at_start)).lower() == "true",
        daily_loss_limit=float(os.getenv("FUT_PROP_DAILY_LOSS_LIMIT", base.daily_loss_limit)),
        profit_target=float(os.getenv("FUT_PROP_PROFIT_TARGET", base.profit_target)),
        min_trading_days=int(os.getenv("FUT_PROP_MIN_DAYS", base.min_trading_days)),
        consistency_pct=float(os.getenv("FUT_PROP_CONSISTENCY_PCT", base.consistency_pct)),
    )
