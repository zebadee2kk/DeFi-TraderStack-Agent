"""Unit tests for overnight/session gap SPOT overlay."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from traderstack.candles import Candle
from traderstack.research.session_gap import (
    CONTROL_IDS,
    CORE_IDS,
    SESS_GAP_CATALOG,
    SESS_GAP_IDS,
    build_gap_features,
    overnight_gap_series,
    sess_gap_candidates,
    session_return_series,
    skipped_sess_gap_families,
)


def make_candles(
    prices: list[float],
    *,
    symbol: str = "BTC/USD",
    start: datetime | None = None,
    gap_frac: float = 0.0,
) -> tuple[Candle, ...]:
    opened = start or datetime(2024, 1, 1, tzinfo=UTC)
    candles: list[Candle] = []
    for index, price in enumerate(prices):
        previous = prices[index - 1] if index else price
        open_px = previous * (1.0 + gap_frac) if index else previous
        candles.append(
            Candle(
                symbol=symbol,
                interval="1d",
                opened_at=opened + timedelta(days=index),
                open=open_px,
                high=max(open_px, price) * 1.002,
                low=min(open_px, price) * 0.998,
                close=price,
                volume=1_000 + index,
            )
        )
    return tuple(candles)


def test_catalog_ids_frozen() -> None:
    assert len(SESS_GAP_CATALOG) == 12
    assert len(SESS_GAP_IDS) == 12
    assert SESS_GAP_IDS[0] == "sess_gap_on_fade_1_0"
    assert SESS_GAP_IDS[-1] == "sess_gap_sess_follow_2_0"
    assert "ma_cross_10_30" in CONTROL_IDS
    assert set(SESS_GAP_IDS).isdisjoint(CONTROL_IDS)
    assert len(CORE_IDS) == 13


def test_overnight_gap_skip_not_invent() -> None:
    candles = make_candles([100.0, 102.0, 101.0], gap_frac=0.01)
    series = overnight_gap_series(candles)
    assert len(series) == 2
    assert abs(series[0][1] - 0.01) < 1e-12


def test_session_return_series() -> None:
    candles = make_candles([100.0, 110.0], gap_frac=0.0)
    series = session_return_series(candles)
    assert len(series) == 2
    assert abs(series[1][1] - 0.10) < 1e-12


def test_build_gap_features_requires_both_symbols() -> None:
    btc = make_candles([100.0 + i for i in range(40)], symbol="BTC/USD")
    eth = make_candles([50.0 + i * 0.5 for i in range(40)], symbol="ETH/USD")
    overnight, session, notes = build_gap_features({"BTC/USD": btc, "ETH/USD": eth})
    assert "BTC/USD" in overnight and "ETH/USD" in overnight
    assert "BTC/USD" in session and "ETH/USD" in session
    assert any(note["status"] == "ok" for note in notes)


def test_candidates_and_skipped() -> None:
    btc = make_candles([100.0 + i for i in range(40)], symbol="BTC/USD")
    eth = make_candles([50.0 + i * 0.5 for i in range(40)], symbol="ETH/USD")
    overnight, session, _ = build_gap_features({"BTC/USD": btc, "ETH/USD": eth})
    catalog = sess_gap_candidates(overnight_by_symbol=overnight, session_by_symbol=session)
    assert len(catalog) == 13  # 12 + control
    assert skipped_sess_gap_families(overnight_by_symbol=overnight, session_by_symbol=session) == []
    skipped = skipped_sess_gap_families(overnight_by_symbol=None, session_by_symbol=None)
    assert len(skipped) == 12
