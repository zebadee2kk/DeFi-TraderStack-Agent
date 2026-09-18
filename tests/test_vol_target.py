"""Unit tests for vol-target overlay on ma_cross_10_30."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from traderstack.candles import Candle
from traderstack.research.vol_target import (
    CONTROL_ID,
    CONTROL_IDS,
    OVERLAY_IDS,
    VOL_TARGET_CATALOG,
    VOL_TARGET_IDS,
    VolTargetMaStrategy,
    ann_realised_vol,
    vol_scalar,
    vol_target_candidates,
)
from traderstack.strategies import Regime


def make_candles(
    prices: list[float],
    *,
    symbol: str = "BTC/USD",
    start: datetime | None = None,
) -> tuple[Candle, ...]:
    opened = start or datetime(2024, 1, 1, tzinfo=UTC)
    candles: list[Candle] = []
    for index, price in enumerate(prices):
        candles.append(
            Candle(
                symbol=symbol,
                interval="1d",
                opened_at=opened + timedelta(days=index),
                open=price,
                high=price * 1.002,
                low=price * 0.998,
                close=price,
                volume=1_000 + index,
            )
        )
    return tuple(candles)


def test_catalog_frozen() -> None:
    assert len(VOL_TARGET_CATALOG) == 4
    assert VOL_TARGET_IDS[0] == CONTROL_ID
    assert OVERLAY_IDS == ("ma_cross_10_30_vt15", "ma_cross_10_30_vt25", "ma_cross_10_30_vt50")
    assert CONTROL_ID in CONTROL_IDS
    assert set(OVERLAY_IDS).isdisjoint(CONTROL_IDS)
    catalog = vol_target_candidates()
    assert len(catalog) == 4
    assert all(item.weight_from_score for item in catalog)
    assert all(not item.garch_sizing for item in catalog)


def test_vol_scalar_reduce_only() -> None:
    assert vol_scalar(None, None) == 1.0
    assert vol_scalar(None, 0.25) is None
    assert abs(vol_scalar(0.50, 0.25) - 0.5) < 1e-12
    assert vol_scalar(0.10, 0.50) == 1.0  # capped


def test_ann_realised_vol_skip_not_invent() -> None:
    short = make_candles([100.0 + i for i in range(10)])
    assert ann_realised_vol(short, lookback=20) is None
    long = make_candles([100.0 * (1.01 if i % 2 == 0 else 0.99) for i in range(40)])
    vol = ann_realised_vol(long, lookback=20)
    assert vol is not None and vol > 0


def test_strategy_encodes_scalar_in_score() -> None:
    prices = [100.0 + i * 0.5 for i in range(40)]
    candles = make_candles(prices)
    control = VolTargetMaStrategy(strategy_id="ma_cross_10_30", vol_target_ann=None)
    overlay = VolTargetMaStrategy(strategy_id="ma_cross_10_30_vt25", vol_target_ann=0.25)
    c_sig = control.evaluate(candles, Regime.TRENDING_UP)
    o_sig = overlay.evaluate(candles, Regime.TRENDING_UP)
    assert c_sig.side is not None
    assert abs(c_sig.score - 1.0) < 1e-12
    assert o_sig.side is not None
    assert 0.0 < o_sig.score <= 1.0
