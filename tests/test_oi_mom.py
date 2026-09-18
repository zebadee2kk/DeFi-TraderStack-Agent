"""Unit tests for HL/Bybit OI-momentum spot overlay."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from traderstack.candles import Candle
from traderstack.config import Settings
from traderstack.research.oi_mom import (
    CONTROL_IDS,
    CORE_IDS,
    OI_MOM_CATALOG,
    OI_MOM_IDS,
    dual_oi_gate,
    oi_mom_candidates,
    oi_momentum_series,
    run_oi_mom,
    skipped_oi_mom_families,
)


def settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "database_url": "postgresql+asyncpg://x:x@localhost/x",
        "redis_url": "redis://localhost:6379/0",
    }
    values.update(overrides)
    return Settings(**values)


def make_candles(
    prices: list[float],
    *,
    symbol: str = "BTC/USD",
    start: datetime | None = None,
) -> tuple[Candle, ...]:
    opened = start or datetime(2024, 1, 1, tzinfo=UTC)
    candles: list[Candle] = []
    for index, price in enumerate(prices):
        previous = prices[index - 1] if index else price
        candles.append(
            Candle(
                symbol=symbol,
                interval="1d",
                opened_at=opened + timedelta(days=index),
                open=previous,
                high=max(previous, price) * 1.002,
                low=min(previous, price) * 0.998,
                close=price,
                volume=1_000 + index,
            )
        )
    return tuple(candles)


def oi_series(values: list[float], *, start: datetime | None = None) -> tuple[tuple[datetime, float], ...]:
    opened = start or datetime(2024, 1, 1, tzinfo=UTC)
    return tuple((opened + timedelta(days=index), value) for index, value in enumerate(values))


def test_catalog_ids_frozen() -> None:
    assert OI_MOM_IDS == (
        "oi_mom_fade_7",
        "oi_mom_fade_14",
        "oi_mom_fade_30",
        "oi_mom_follow_7",
        "oi_mom_follow_14",
        "oi_mom_follow_30",
    )
    assert "ma_cross_10_30" in CONTROL_IDS
    assert set(OI_MOM_IDS).isdisjoint(CONTROL_IDS)
    assert len(CORE_IDS) == 7
    assert len(OI_MOM_CATALOG) == 6
    for _cid, _fade, entry_z, lookback_n in OI_MOM_CATALOG:
        assert entry_z == 2.0
        assert lookback_n in {7, 14, 30}


def test_oi_momentum_series_math() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    series = oi_series([100 + i for i in range(20)], start=start)
    mom = oi_momentum_series(series, 7)
    assert len(mom) == 13
    # day 7 vs day 0: (107/100)-1
    assert abs(mom[0][1] - 0.07) < 1e-12


def test_dual_oi_gate_fail_closed() -> None:
    short = oi_series([100.0] * 100)
    ok, notes = dual_oi_gate({"BTC/USD": short, "ETH/USD": short}, {"BTC/USD": short, "ETH/USD": short})
    assert ok is False
    assert any(n.get("name") == "oi_gate:dual" and n.get("status") == "unavailable" for n in notes)


def test_dual_oi_gate_pass() -> None:
    long = oi_series([100.0 + i for i in range(800)])
    ok, notes = dual_oi_gate(
        {"BTC/USD": long, "ETH/USD": long},
        {"BTC/USD": long, "ETH/USD": long},
    )
    assert ok is True
    assert any(n.get("name") == "oi_gate:dual" and n.get("status") == "ok" for n in notes)


def test_skipped_when_no_oi() -> None:
    skipped = skipped_oi_mom_families(oi_by_symbol=None)
    assert len(skipped) == 6
    assert oi_mom_candidates(oi_by_symbol=None) == ()


def test_run_oi_mom_never_promotes_and_unavailable_without_dual_gate() -> None:
    prices = [100 + (i % 7) for i in range(250)]
    histories = {
        "BTC/USD": make_candles(prices, symbol="BTC/USD"),
        "ETH/USD": make_candles(prices, symbol="ETH/USD"),
    }
    report = run_oi_mom(
        histories,
        fee_bps=80.0,
        slippage_bps=5.0,
        hl_oi_by_symbol={"BTC/USD": oi_series([1.0] * 10), "ETH/USD": oi_series([1.0] * 10)},
        bybit_oi_by_symbol={"BTC/USD": oi_series([1.0] * 10), "ETH/USD": oi_series([1.0] * 10)},
        second_histories=histories,
    )
    assert report.print_kind == "unavailable"
    assert report.can_promote is False
    assert report.keep_flag_false is True
    assert report.dual_print_passers == 0
    assert report.recommended_promote_flag is None


def test_paper_promote_defaults_untouched() -> None:
    s = settings()
    assert s.paper_promote_searched_strategies is False
    assert s.paper_promote_ema_9_21 is False
    assert s.paper_promote_ema_9_21_adx15 is False
