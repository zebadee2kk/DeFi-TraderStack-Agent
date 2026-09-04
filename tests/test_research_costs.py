from datetime import UTC, datetime

from traderstack.candles import Candle
from traderstack.research.costs import FlatCostModel, VolumeAwareSlippageModel


def make_candle(*, close: float = 100.0, volume: float = 1_000.0) -> Candle:
    return Candle(
        symbol="BTC/USD",
        interval="1h",
        opened_at=datetime(2026, 1, 1, tzinfo=UTC),
        open=close,
        high=close * 1.001,
        low=close * 0.999,
        close=close,
        volume=volume,
    )


def test_flat_cost_model_ignores_notional_and_bar() -> None:
    model = FlatCostModel(fee_bps=10.0, slippage_bps=5.0)
    small = model.cost_bps(make_candle(), notional_usd=100.0)
    large = model.cost_bps(make_candle(), notional_usd=1_000_000.0)
    assert small == large == 15.0


def test_volume_aware_slippage_grows_with_order_size() -> None:
    model = VolumeAwareSlippageModel(
        fee_bps=10.0, base_slippage_bps=5.0, participation_sensitivity_bps=200.0, max_slippage_bps=250.0
    )
    candle = make_candle(close=100.0, volume=1_000.0)  # bar notional = 100,000
    small_order = model.cost_bps(candle, notional_usd=1_000.0)
    medium_order = model.cost_bps(candle, notional_usd=20_000.0)
    large_order = model.cost_bps(candle, notional_usd=100_000.0)
    assert small_order < medium_order < large_order


def test_volume_aware_slippage_is_capped() -> None:
    model = VolumeAwareSlippageModel(
        fee_bps=10.0, base_slippage_bps=5.0, participation_sensitivity_bps=200.0, max_slippage_bps=50.0
    )
    candle = make_candle(close=100.0, volume=100.0)  # tiny bar notional
    cost = model.cost_bps(candle, notional_usd=10_000_000.0)
    assert cost == 10.0 + 50.0


def test_volume_aware_slippage_handles_zero_bar_volume() -> None:
    model = VolumeAwareSlippageModel()
    candle = make_candle(volume=0.0)
    cost = model.cost_bps(candle, notional_usd=1_000.0)
    assert cost >= model.fee_bps + model.base_slippage_bps
