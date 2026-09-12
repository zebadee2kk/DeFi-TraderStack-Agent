from datetime import UTC, datetime, timedelta

import pytest

from traderstack.candles import Candle
from traderstack.garch import (
    close_returns,
    fit_garch11,
    forecast_at_window,
    forecast_series_for_candles,
    one_step_forecast,
    paper_risk_garch_factor,
    size_from_vol,
    walkforward_forecasts,
)
from traderstack.indicators import average_directional_index, ema, exponential_moving_average


def clustered_returns(count: int = 400) -> list[float]:
    """Quiet then a vol shock then quiet — GARCH should lift the forecast."""
    returns: list[float] = []
    for index in range(count):
        if 200 <= index < 210:
            returns.append(0.08 if index % 2 == 0 else -0.08)
        else:
            returns.append(0.002 if index % 2 == 0 else -0.002)
    return returns


def test_size_from_vol_clips_to_miles_caps() -> None:
    assert size_from_vol(0.10, 0.50) == 2.0
    assert size_from_vol(2.00, 0.50) == 0.25
    assert size_from_vol(0.50, 0.50) == pytest.approx(1.0)
    assert size_from_vol(0.0, 0.50) == 0.25


def test_paper_risk_garch_factor_never_scales_up() -> None:
    assert paper_risk_garch_factor(0.10, 0.50) == 1.0
    assert paper_risk_garch_factor(1.00, 0.50) == pytest.approx(0.50)
    assert paper_risk_garch_factor(None, 0.50) == 1.0
    assert paper_risk_garch_factor(0.0, 0.50) == 1.0


def test_fit_garch11_is_stationary_and_positive() -> None:
    params = fit_garch11(clustered_returns())
    assert params.omega > 0
    assert params.alpha >= 0
    assert params.beta >= 0
    assert params.alpha + params.beta < 1.0


def test_walkforward_forecast_rises_after_a_shock() -> None:
    series = walkforward_forecasts(
        clustered_returns(), periods=365.0, min_train=120, refit_every=21
    )
    before = series[199]
    after = series[210]
    assert before is not None and after is not None
    assert after.vol > before.vol


def test_walkforward_has_no_lookahead() -> None:
    base = clustered_returns(250)
    extra_a = [0.20] * 30
    extra_b = [-0.01] * 30
    a = walkforward_forecasts(base + extra_a, periods=365.0, min_train=120, refit_every=21)
    b = walkforward_forecasts(base + extra_b, periods=365.0, min_train=120, refit_every=21)
    for index in range(len(base)):
        left, right = a[index], b[index]
        if left is None and right is None:
            continue
        assert left is not None and right is not None
        assert left.vol == pytest.approx(right.vol)
        assert left.size_multiplier == pytest.approx(right.size_multiplier)


def test_one_step_forecast_matches_window_only() -> None:
    returns = clustered_returns(180)
    forecast = one_step_forecast(returns, periods=365.0, min_train=120)
    assert forecast is not None
    assert forecast.vol_ann > 0
    assert 0.25 <= forecast.size_multiplier <= 2.0


def test_forecast_at_window_uses_last_completed_return() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    prices = [100.0]
    for ret in clustered_returns(160):
        prices.append(prices[-1] * (1.0 + ret))
    candles = tuple(
        Candle(
            symbol="BTC/USD",
            interval="1d",
            opened_at=start + timedelta(days=index),
            open=price,
            high=price * 1.001,
            low=price * 0.999,
            close=price,
            volume=10.0,
        )
        for index, price in enumerate(prices)
    )
    series = forecast_series_for_candles(candles, min_train=120, refit_every=21)
    window = candles[:150]
    looked_up = forecast_at_window(series, window)
    assert looked_up is series[148]


def test_close_returns_reject_non_positive_prices() -> None:
    with pytest.raises(ValueError):
        close_returns([100.0, 0.0])


def test_ema_matches_closed_form_seed() -> None:
    values = [1.0, 2.0, 3.0]
    series = exponential_moving_average(values, span=2)
    assert series[0] == 1.0
    assert series[1] == pytest.approx(5.0 / 3.0)
    assert series[2] == pytest.approx(23.0 / 9.0)


def test_ema_on_candles_follows_an_uptrend() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    candles = tuple(
        Candle(
            symbol="BTC/USD",
            interval="1d",
            opened_at=start + timedelta(days=index),
            open=100 + index,
            high=101 + index,
            low=99 + index,
            close=100 + index,
            volume=1.0,
        )
        for index in range(30)
    )
    assert ema(candles, 9) > ema(candles, 21)


def test_adx_is_high_on_a_persistent_trend() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    candles = []
    price = 100.0
    for index in range(60):
        nxt = price + 1.5
        candles.append(
            Candle(
                symbol="BTC/USD",
                interval="1d",
                opened_at=start + timedelta(days=index),
                open=price,
                high=nxt + 0.2,
                low=price - 0.1,
                close=nxt,
                volume=1.0,
            )
        )
        price = nxt
    assert average_directional_index(tuple(candles), 14) > 40.0


def test_adx_is_lower_in_a_chop() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    candles = []
    price = 100.0
    for index in range(60):
        nxt = price + (1.0 if index % 2 == 0 else -1.0)
        high = max(price, nxt) + 0.05
        low = min(price, nxt) - 0.05
        candles.append(
            Candle(
                symbol="BTC/USD",
                interval="1d",
                opened_at=start + timedelta(days=index),
                open=price,
                high=high,
                low=low,
                close=nxt,
                volume=1.0,
            )
        )
        price = nxt
    assert average_directional_index(tuple(candles), 14) < 25.0
