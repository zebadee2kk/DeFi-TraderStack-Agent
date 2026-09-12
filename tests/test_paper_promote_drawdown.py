"""Paper daily ema_9_21 promote path: align the DD gate with research.

Root cause of the post-#94 WSL soak (NAV stuck, 0 fills): every cycle
rejected ``backtest_drawdown_above_maximum`` because the shared
``PRETRADE_MAX_DRAWDOWN_PCT=0.15`` bar is calibrated for ~16-day 1h MA
lookbacks. Daily ``ema_9_21`` on Kraken Spot (#95/#96) realized WF maxDD
~23.35% (BTC+ETH mean). Units are already fractions in [0, 1]; the
mismatch is the ceiling, not the series.

The promote path therefore uses
``PAPER_PROMOTE_EMA_9_21_MAX_DRAWDOWN_PCT`` (default 0.30). Live/shadow
and the 1h non-promote paper path keep 0.15. The gate stays on.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from traderstack.candles import Candle
from traderstack.cli import build_pretrade_gate
from traderstack.config import (
    EMA_9_21_PAPER_MAX_DRAWDOWN_PCT,
    EMA_9_21_PAPER_RESEARCH_WF_MAX_DRAWDOWN_PCT,
    Settings,
)
from traderstack.models import Side

START = datetime(2024, 1, 1, tzinfo=UTC)


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "database_url": "postgresql+asyncpg://x:x@localhost/x",
        "redis_url": "redis://localhost:6379/0",
        "kill_switch": False,
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def _daily(prices: list[float], *, start: datetime = START) -> tuple[Candle, ...]:
    candles: list[Candle] = []
    for index, price in enumerate(prices):
        previous = prices[index - 1] if index else price
        candles.append(
            Candle(
                symbol="BTC/USD",
                interval="1d",
                opened_at=start + timedelta(days=index),
                open=previous,
                high=max(previous, price) * 1.002,
                low=min(previous, price) * 0.998,
                close=price,
                volume=1_000 + index,
            )
        )
    return tuple(candles)


def _hourly(prices: list[float], *, start: datetime = START) -> tuple[Candle, ...]:
    candles: list[Candle] = []
    for index, price in enumerate(prices):
        previous = prices[index - 1] if index else price
        candles.append(
            Candle(
                symbol="BTC/USD",
                interval="1h",
                opened_at=start + timedelta(hours=index),
                open=previous,
                high=max(previous, price) * 1.002,
                low=min(previous, price) * 0.998,
                close=price,
                volume=1_000 + index,
            )
        )
    return tuple(candles)


def _linspace(start: float, end: float, count: int) -> list[float]:
    if count <= 1:
        return [end]
    step = (end - start) / (count - 1)
    return [start + step * index for index in range(count)]


def daily_ema_end_crash(drop_pct: float, crash_bars: int) -> tuple[Candle, ...]:
    """Daily book whose *realized* ema_9_21 equity DD matches ``drop_pct``.

    The shared backtester only marks drawdown on rebalance, so a slow
    crash lets EMA 9/21 flip to short and recover. A 2–3 bar cliff at
    the end closes the long near the trough (warmup rise is inside the
    first 31 bars so buy-and-hold is also the crash — excess stays
    inside the paper floor).
    """
    peak = 180.0
    trough = peak * (1.0 - drop_pct)
    prices = (
        _linspace(100.0, peak, 32)
        + _linspace(peak, peak + 1.0, 325)
        + _linspace(peak + 1.0, trough, crash_bars)
    )
    return _daily(prices)


def _end(candles: tuple[Candle, ...]) -> datetime:
    return candles[-1].opened_at + timedelta(hours=12)


def test_research_envelope_is_above_the_1h_bar_and_below_the_paper_ceiling() -> None:
    assert EMA_9_21_PAPER_RESEARCH_WF_MAX_DRAWDOWN_PCT > 0.15
    assert EMA_9_21_PAPER_RESEARCH_WF_MAX_DRAWDOWN_PCT < EMA_9_21_PAPER_MAX_DRAWDOWN_PCT
    assert EMA_9_21_PAPER_MAX_DRAWDOWN_PCT == pytest.approx(0.30)


def test_promote_path_uses_dedicated_ceiling_not_the_1h_bar() -> None:
    promote = _settings(paper_promote_ema_9_21=True, pretrade_max_drawdown_pct=0.15)
    assert promote.effective_pretrade_max_drawdown_pct == EMA_9_21_PAPER_MAX_DRAWDOWN_PCT
    gate = build_pretrade_gate(promote)
    assert gate.max_drawdown == EMA_9_21_PAPER_MAX_DRAWDOWN_PCT
    assert gate.max_drawdown != promote.pretrade_max_drawdown_pct


def test_adx15_promote_path_uses_the_same_daily_dd_ceiling() -> None:
    promote = _settings(paper_promote_ema_9_21_adx15=True, pretrade_max_drawdown_pct=0.15)
    assert promote.paper_promote_ema_9_21 is False
    assert promote.effective_pretrade_max_drawdown_pct == EMA_9_21_PAPER_MAX_DRAWDOWN_PCT
    assert build_pretrade_gate(promote).max_drawdown == EMA_9_21_PAPER_MAX_DRAWDOWN_PCT


def test_live_and_shadow_ignore_the_paper_promote_dd_ceiling() -> None:
    for mode in ("live", "shadow"):
        settings = _settings(
            trading_mode=mode,
            paper_promote_ema_9_21=True,
            paper_promote_ema_9_21_max_drawdown_pct=0.30,
        )
        assert settings.effective_pretrade_max_drawdown_pct == 0.15
        assert build_pretrade_gate(settings).max_drawdown == 0.15


def test_zero_paper_promote_dd_ceiling_fails_closed_at_settings_load() -> None:
    with pytest.raises(ValidationError):
        _settings(paper_promote_ema_9_21=True, paper_promote_ema_9_21_max_drawdown_pct=0.0)


def test_promote_daily_fixture_below_aligned_ceiling_passes() -> None:
    candles = daily_ema_end_crash(0.35, crash_bars=3)
    settings = _settings(paper_promote_ema_9_21=True, pretrade_candle_interval="1h")
    gate = build_pretrade_gate(settings)
    check = gate.evaluate(candles, now=_end(candles))
    assert check.metrics is not None
    assert 0.15 < check.metrics.max_drawdown <= EMA_9_21_PAPER_MAX_DRAWDOWN_PCT
    assert check.confirmed_side in {Side.BUY, Side.SELL}
    assert "backtest_drawdown_above_maximum" not in check.reasons
    assert "walkforward_drawdown_above_maximum" not in check.reasons
    assert check.passed, check.reasons


def test_same_fixture_fails_the_1h_fifteen_percent_bar() -> None:
    """The soak failure: research-envelope DD vs the old shared 0.15 ceiling."""
    candles = daily_ema_end_crash(0.35, crash_bars=3)
    settings = _settings(
        paper_promote_ema_9_21=True,
        paper_promote_ema_9_21_max_drawdown_pct=0.15,
        pretrade_candle_interval="1h",
    )
    check = build_pretrade_gate(settings).evaluate(candles, now=_end(candles))
    assert check.metrics is not None
    assert check.metrics.max_drawdown > 0.15
    assert not check.passed
    assert "backtest_drawdown_above_maximum" in check.reasons or (
        "walkforward_drawdown_above_maximum" in check.reasons
    )


def test_promote_daily_fixture_above_aligned_ceiling_fails() -> None:
    candles = daily_ema_end_crash(0.40, crash_bars=2)
    settings = _settings(paper_promote_ema_9_21=True)
    check = build_pretrade_gate(settings).evaluate(candles, now=_end(candles))
    assert check.metrics is not None
    assert check.metrics.max_drawdown > EMA_9_21_PAPER_MAX_DRAWDOWN_PCT
    assert not check.passed
    assert "backtest_drawdown_above_maximum" in check.reasons or (
        "walkforward_drawdown_above_maximum" in check.reasons
    )


def test_1h_non_promote_path_still_uses_fifteen_percent() -> None:
    prices = [100.0 + index * 0.08 for index in range(400)]
    candles = _hourly(prices)
    settings = _settings()
    gate = build_pretrade_gate(settings)
    assert gate.max_drawdown == 0.15
    check = gate.evaluate(candles, now=candles[-1].opened_at + timedelta(minutes=30))
    assert check.passed, check.reasons
    assert check.metrics is not None
    assert check.metrics.max_drawdown <= 0.15
