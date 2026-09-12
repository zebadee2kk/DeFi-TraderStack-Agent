"""Paper daily ema_9_21 promote path: align the DD gate with research.

#98 raised the paper ceiling to 0.30 but still compared
``metrics.max_drawdown`` (full-history backtest) to a bar calibrated
to #95–#100 *walk-forward* maxDD (train=180 / test=60 / step=60,
warmup=train). On Kraken daily after #98, that longer series is ETH
~43% (400 bars) / ~36% (720 bars) while research WF maxDD is 28.77%.
BTC's 400-bar full-history DD (~20%) cleared; ETH never did
(``backtest_drawdown_above_maximum``).

The promote path therefore (1) applies 0.30 to research-style WF
worst_drawdown only, and (2) fetches 720 daily bars so the documented
ETH fold is in-window. Live/shadow and the 1h non-promote path keep
0.15 on the full-history book. The gate stays on. The ceiling is not
raised past the research envelope.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from traderstack.candles import Candle
from traderstack.cli import build_pretrade_gate
from traderstack.config import (
    EMA_9_21_PAPER_CANDLE_COUNT,
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
    # 360 bars so the last research WF fold (test 300–360) includes the cliff.
    middle = 360 - 32 - crash_bars
    prices = (
        _linspace(100.0, peak, 32)
        + _linspace(peak, peak + 1.0, middle)
        + _linspace(peak + 1.0, trough, crash_bars)
    )
    return _daily(prices)


def daily_ema_early_crash(drop_pct: float, crash_bars: int) -> tuple[Candle, ...]:
    """Cliff inside the first train window: full-history DD sees it, WF does not.

    Research WF uses warmup=train_size (180), so bars 32–100 are traded
    on the full-history book and only used as warmup on fold 1.
    """
    peak = 180.0
    trough = peak * (1.0 - drop_pct)
    rest = 360 - 32 - crash_bars
    prices = (
        _linspace(100.0, peak, 32)
        + _linspace(peak, trough, crash_bars)
        + _linspace(trough, trough + 20.0, rest)
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
    assert gate.compare_full_history_drawdown is False
    assert gate.walkforward is not None
    assert gate.walkforward.train_warmup is True


def test_promote_path_forces_research_candle_count() -> None:
    promote = _settings(paper_promote_ema_9_21=True, pretrade_candle_count=400)
    assert promote.pretrade_candle_count == 400
    assert promote.effective_pretrade_candle_count == EMA_9_21_PAPER_CANDLE_COUNT
    assert promote.effective_pretrade_candle_count == 720
    live = _settings(trading_mode="live", paper_promote_ema_9_21=True, pretrade_candle_count=400)
    assert live.effective_pretrade_candle_count == 400
    off = _settings(pretrade_candle_count=400)
    assert off.effective_pretrade_candle_count == 400


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
        assert settings.effective_pretrade_candle_count == 400
        gate = build_pretrade_gate(settings)
        assert gate.max_drawdown == 0.15
        assert gate.compare_full_history_drawdown is True
        assert gate.walkforward is None or gate.walkforward.train_warmup is False


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
    assert check.walkforward is not None
    assert check.walkforward.worst_drawdown > EMA_9_21_PAPER_MAX_DRAWDOWN_PCT
    assert not check.passed
    assert "walkforward_drawdown_above_maximum" in check.reasons
    assert "backtest_drawdown_above_maximum" not in check.reasons


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
    assert gate.compare_full_history_drawdown is True


def test_full_history_above_ceiling_passes_when_research_wf_clears() -> None:
    """Post-#98 ETH soak: full-history DD > 0.30, research WF maxDD is not."""
    candles = daily_ema_early_crash(0.45, crash_bars=3)
    settings = _settings(paper_promote_ema_9_21=True)
    gate = build_pretrade_gate(settings)
    check = gate.evaluate(candles, now=_end(candles))
    assert check.metrics is not None
    assert check.walkforward is not None
    assert check.metrics.max_drawdown > EMA_9_21_PAPER_MAX_DRAWDOWN_PCT
    assert check.walkforward.worst_drawdown <= EMA_9_21_PAPER_MAX_DRAWDOWN_PCT
    assert "backtest_drawdown_above_maximum" not in check.reasons
    assert "walkforward_drawdown_above_maximum" not in check.reasons


def test_non_promote_still_rejects_full_history_above_fifteen() -> None:
    """Live/shadow / flag-off paper keep comparing the full-history book."""
    candles = daily_ema_early_crash(0.45, crash_bars=3)
    settings = _settings(pretrade_max_candle_age_seconds=172_800.0)
    gate = build_pretrade_gate(settings)
    assert gate.compare_full_history_drawdown is True
    assert gate.max_drawdown == 0.15
    check = gate.evaluate(candles, now=_end(candles))
    assert check.metrics is not None
    assert check.metrics.max_drawdown > 0.15
    assert not check.passed
    assert "backtest_drawdown_above_maximum" in check.reasons
