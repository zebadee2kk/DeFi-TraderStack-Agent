"""Tests for weekly low-turnover trend dual-print (Hypothesis C)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from traderstack.candles import Candle
from traderstack.research.weekly_trend import (
    WEEKLY_IDS,
    ma_position_series,
    resample_daily_to_friday_weekly,
    run_weekly_trend_search,
    tsmom_position_series,
)


def _daily(symbol: str, n: int, start: datetime, *, drift: float = 0.001) -> tuple[Candle, ...]:
    out: list[Candle] = []
    px = 100.0
    for i in range(n):
        opened = start + timedelta(days=i)
        o = px
        c = px * (1.0 + drift)
        h = max(o, c) * 1.001
        lo = min(o, c) * 0.999
        out.append(
            Candle(
                symbol=symbol,
                interval="1d",
                opened_at=opened,
                open=o,
                high=h,
                low=lo,
                close=c,
                volume=1.0,
            )
        )
        px = c
    return tuple(out)


def test_catalog_size_and_ids() -> None:
    assert len(WEEKLY_IDS) == 6
    assert all(i.startswith("wk_trend_") for i in WEEKLY_IDS)


def test_friday_resample_skips_weeks_without_friday() -> None:
    # Build Mon-Thu only for one week, then a full week
    start = datetime(2024, 1, 1, tzinfo=UTC)  # Monday
    bars: list[Candle] = []
    px = 100.0
    # week 1: Mon-Thu only (no Friday) — should be skipped
    for i in range(4):
        opened = start + timedelta(days=i)
        bars.append(
            Candle(
                symbol="BTC/USD",
                interval="1d",
                opened_at=opened,
                open=px,
                high=px * 1.01,
                low=px * 0.99,
                close=px,
                volume=1.0,
            )
        )
    # week 2: Mon-Fri
    week2 = start + timedelta(days=7)
    for i in range(5):
        opened = week2 + timedelta(days=i)
        bars.append(
            Candle(
                symbol="BTC/USD",
                interval="1d",
                opened_at=opened,
                open=px,
                high=px * 1.01,
                low=px * 0.99,
                close=px + 1,
                volume=1.0,
            )
        )
        px += 1
    weekly = resample_daily_to_friday_weekly(tuple(bars))
    assert len(weekly) == 1
    assert weekly[0].opened_at.weekday() == 4
    assert weekly[0].interval == "1w"


def test_ma_and_tsmom_positions_long_only() -> None:
    start = datetime(2024, 1, 5, tzinfo=UTC)  # Friday
    # fabricate weekly bars directly
    candles = []
    px = 100.0
    for i in range(30):
        opened = start + timedelta(weeks=i)
        c = px * 1.02
        candles.append(
            Candle(
                symbol="BTC/USD",
                interval="1w",
                opened_at=opened,
                open=px,
                high=c * 1.01,
                low=px * 0.99,
                close=c,
                volume=1.0,
            )
        )
        px = c
    series = tuple(candles)
    ma = ma_position_series(series, fast=4, slow=12)
    assert ma
    assert all(v in (0.0, 1.0) for _, v in ma)
    # uptrend -> mostly long after warmup
    assert sum(v for _, v in ma) > 0
    ts = tsmom_position_series(series, lookback=12)
    assert ts
    assert all(v == 1.0 for _, v in ts)  # pure uptrend


def test_candidates_build_and_empty_second_print_is_success() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    # ~730 daily bars (~2y) so weekly >= 102
    btc = _daily("BTC/USD", 730, start, drift=0.001)
    eth = _daily("ETH/USD", 730, start, drift=0.0008)
    kraken = {
        "BTC/USD@1d": btc,
        "ETH/USD@1d": eth,
    }
    report = run_weekly_trend_search(kraken, coinbase_daily=None, recipe_commit="test")
    # without second print: single_print or unavailable; passers 0
    assert report.dual_print_passers == 0
    assert report.can_promote is False
    assert report.keep_flag_false is True
    assert report.print_kind in {"single_print", "unavailable", "dual_print"}


def test_dual_print_on_synthetic_concurrent() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    btc = _daily("BTC/USD", 730, start, drift=0.002)
    eth = _daily("ETH/USD", 730, start, drift=0.0015)
    # mild differing second venue
    btc2 = _daily("BTC/USD", 730, start, drift=0.0018)
    eth2 = _daily("ETH/USD", 730, start, drift=0.0012)
    report = run_weekly_trend_search(
        {"BTC/USD@1d": btc, "ETH/USD@1d": eth},
        {"BTC/USD@1d": btc2, "ETH/USD@1d": eth2},
        recipe_commit="test",
    )
    assert report.print_kind == "dual_print"
    assert report.keep_flag_false is True
    assert report.can_promote is False
    assert set(report.core_ids) == set(WEEKLY_IDS)
    # empty or non-empty both OK; must not invent
    assert report.dual_print_passers == len(report.dual_print_passer_ids)
