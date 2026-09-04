from datetime import UTC, datetime, timedelta

import pytest

from traderstack.candles import Candle
from traderstack.market_features import CandleMarketFeatureBuilder
from traderstack.research.leakage import (
    LookaheadBiasError,
    assert_no_lookahead,
    assert_no_lookahead_under_shuffled_future,
)
from traderstack.strategies import StrategyEnsemble


def make_candles(count: int = 120, *, symbol: str = "BTC/USD") -> tuple[Candle, ...]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    candles: list[Candle] = []
    price = 100.0
    for index in range(count):
        previous = price
        price = price + ((index % 5) - 2) * 0.4 + 0.1
        candles.append(
            Candle(
                symbol=symbol,
                interval="1h",
                opened_at=start + timedelta(hours=index),
                open=previous,
                high=max(previous, price) * 1.002,
                low=min(previous, price) * 0.998,
                close=price,
                volume=500.0 + index,
            )
        )
    return tuple(candles)


def test_strategy_ensemble_has_no_lookahead() -> None:
    ensemble = StrategyEnsemble()
    candles = make_candles()

    def fn(window: tuple[Candle, ...]) -> object:
        return ensemble.evaluate(window)

    assert_no_lookahead(fn, candles, min_index=40, step=5)


def test_strategy_ensemble_has_no_lookahead_under_shuffled_future() -> None:
    ensemble = StrategyEnsemble()
    candles = make_candles()

    def fn(window: tuple[Candle, ...]) -> object:
        return ensemble.evaluate(window)

    assert_no_lookahead_under_shuffled_future(fn, candles, min_index=40, step=5)


def test_candle_market_feature_builder_has_no_lookahead() -> None:
    builder = CandleMarketFeatureBuilder()
    candles = make_candles()

    def fn(window: tuple[Candle, ...]) -> object:
        return builder.build(window, spread_bps=4.0)

    assert_no_lookahead(fn, candles, min_index=30, step=5)


def test_candle_market_feature_builder_has_no_lookahead_under_shuffled_future() -> None:
    builder = CandleMarketFeatureBuilder()
    candles = make_candles()

    def fn(window: tuple[Candle, ...]) -> object:
        return builder.build(window, spread_bps=4.0)

    assert_no_lookahead_under_shuffled_future(fn, candles, min_index=30, step=5)


def test_assert_no_lookahead_catches_a_stateful_leak() -> None:
    """A realistic lookahead-adjacent bug: a "signal" implemented as a streaming
    accumulator (e.g. an EMA kept between calls) instead of being purely
    recomputed from the window each time. Its answer for a given window then
    depends on what other windows -- including ones representing a different
    possible future -- it happened to see first. `assert_no_lookahead` must
    catch it."""
    candles = make_candles()
    state = {"ema": 0.0}

    def leaky_streaming_ema(window: tuple[Candle, ...]) -> float:
        state["ema"] = 0.9 * state["ema"] + 0.1 * window[-1].close
        return state["ema"]

    with pytest.raises(LookaheadBiasError):
        assert_no_lookahead(leaky_streaming_ema, candles, min_index=10, step=10)


def test_assert_no_lookahead_under_shuffled_future_catches_the_same_bug() -> None:
    candles = make_candles()
    state = {"ema": 0.0}

    def leaky_streaming_ema(window: tuple[Candle, ...]) -> float:
        state["ema"] = 0.9 * state["ema"] + 0.1 * window[-1].close
        return state["ema"]

    with pytest.raises(LookaheadBiasError):
        assert_no_lookahead_under_shuffled_future(
            leaky_streaming_ema, candles, min_index=10, step=10
        )


def test_a_pure_function_of_its_window_passes() -> None:
    """Sanity check: a correctly point-in-time function (no shared state at all)
    always passes, however aggressively it is probed."""
    candles = make_candles()

    def pure_last_close(window: tuple[Candle, ...]) -> float:
        return window[-1].close

    assert_no_lookahead(pure_last_close, candles, min_index=10, step=10)
    assert_no_lookahead_under_shuffled_future(pure_last_close, candles, min_index=10, step=10)
