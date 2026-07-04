"""Tests for the futures prop-rules trailing-drawdown engine.

The trailing-DD machine is the most error-prone piece (peak tracking, freeze,
intraday vs EOD). These pin its behavior so prop_mc's P(pass) is trustworthy.
"""
from __future__ import annotations

import pytest

from honestbacktest.core.prop_rules import (APEX_50K, TOPSTEP_50K, AccountState,
                                            Outcome, PropRules)


def test_initial_floor():
    s = AccountState(TOPSTEP_50K)
    assert s.trailing_floor == 48_000.0      # 50k - 2k
    assert s.balance == 50_000.0


def test_pass_requires_target_and_min_days():
    s = AccountState(TOPSTEP_50K)
    # one huge day clears the $3k target but min_trading_days=2 -> still active
    s.apply_day(3_500.0)
    assert s.outcome is Outcome.ACTIVE
    s.apply_day(100.0)
    assert s.outcome is Outcome.PASSED


def test_fail_by_daily_limit():
    s = AccountState(TOPSTEP_50K)
    out = s.apply_day(-1_200.0, intraday_low=50_000.0 - 1_200.0)
    assert out is Outcome.FAILED_DAILY


def test_daily_limit_off_for_apex():
    s = AccountState(APEX_50K)  # daily_loss_limit = 0
    out = s.apply_day(-1_200.0, intraday_low=50_000.0 - 1_200.0)
    # Apex has no daily limit and 1.2k loss is within the 2.5k trail -> survives
    assert out is Outcome.ACTIVE


def test_trailing_floor_rises_with_profit_then_freezes_topstep():
    s = AccountState(TOPSTEP_50K)  # trail_freeze_at_start=True
    s.apply_day(1_000.0)           # balance 51k -> floor would be 49k
    assert s.trailing_floor == 49_000.0
    s.apply_day(1_000.0)           # balance 52k -> floor caps at start (50k)
    assert s.trailing_floor == 50_000.0
    s.apply_day(5_000.0)           # balance 57k -> floor stays frozen at 50k
    assert s.trailing_floor == 50_000.0


def test_apex_intraday_high_raises_trail_no_freeze():
    s = AccountState(APEX_50K)     # intraday mode, no freeze
    # an intraday spike to +4k raises the peak even if we close flat
    s.apply_day(0.0, intraday_low=50_000.0, intraday_high=54_000.0)
    assert s.peak_balance == 54_000.0
    assert s.trailing_floor == 54_000.0 - 2_500.0


def test_trailing_fail_after_runup():
    s = AccountState(TOPSTEP_50K)
    s.apply_day(1_500.0)           # 51.5k, floor 49.5k
    out = s.apply_day(-2_000.0, intraday_low=49_400.0)
    assert out is Outcome.FAILED_TRAILING


def test_terminal_state_is_sticky():
    s = AccountState(TOPSTEP_50K)
    s.apply_day(-1_200.0, intraday_low=48_800.0)
    assert s.outcome is Outcome.FAILED_DAILY
    # further days are ignored
    assert s.apply_day(5_000.0) is Outcome.FAILED_DAILY


def test_consistency_blocks_pass():
    rules = PropRules(firm_name="X", account_size=50_000.0, max_trailing_loss=2_500.0,
                      trailing_mode="intraday", daily_loss_limit=0.0,
                      profit_target=3_000.0, min_trading_days=1, consistency_pct=30.0)
    s = AccountState(rules)
    # single day makes the whole target -> 100% from one day > 30% -> not passed
    s.apply_day(3_200.0)
    assert s.outcome is Outcome.ACTIVE


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
