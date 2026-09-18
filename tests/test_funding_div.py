"""Unit tests for HL-HTX funding-divergence spot overlay."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from traderstack.candles import Candle
from traderstack.config import Settings
from traderstack.research.funding_div import (
    CONTROL_IDS,
    CORE_IDS,
    FUND_DIV_CATALOG,
    FUND_DIV_IDS,
    align_funding_divergence,
    fund_div_candidates,
    run_funding_div,
    skipped_fund_div_families,
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


def funding_series(
    values: list[float], *, start: datetime | None = None, every_hours: int = 8
) -> tuple[tuple[datetime, float], ...]:
    opened = start or datetime(2024, 1, 1, tzinfo=UTC)
    return tuple(
        (opened + timedelta(hours=every_hours * index), value)
        for index, value in enumerate(values)
    )


def test_catalog_ids_frozen() -> None:
    assert FUND_DIV_IDS == (
        "fund_div_hl_htx_fade_1_0",
        "fund_div_hl_htx_fade_1_5",
        "fund_div_hl_htx_fade_2_0",
        "fund_div_hl_htx_follow_1_0",
        "fund_div_hl_htx_follow_1_5",
        "fund_div_hl_htx_follow_2_0",
    )
    assert "ma_cross_10_30" in CONTROL_IDS
    assert set(FUND_DIV_IDS).isdisjoint(CONTROL_IDS)
    assert len(CORE_IDS) == 7
    assert len(FUND_DIV_CATALOG) == 6


def test_align_funding_divergence_intersection_skip_not_invent() -> None:
    start = datetime(2024, 6, 1, tzinfo=UTC)
    # HL: 9 prints over 3 days (3x8h); HTX: only days 0 and 2
    hl_vals = [0.0001] * 9
    htx_btc = funding_series([0.0002] * 3, start=start, every_hours=24)
    # force HTX to miss middle day by using only day0 and day2
    htx_btc = (
        (start, 0.0002),
        (start + timedelta(days=2), 0.00005),
    )
    hl_btc = funding_series(hl_vals, start=start, every_hours=8)
    hl_eth = funding_series([0.0003] * 9, start=start, every_hours=8)
    htx_eth = (
        (start, 0.0001),
        (start + timedelta(days=2), 0.0004),
    )
    out, notes = align_funding_divergence(
        {"BTC/USD": hl_btc, "ETH/USD": hl_eth},
        {"BTC/USD": htx_btc, "ETH/USD": htx_eth},
    )
    assert "BTC/USD" in out
    assert "ETH/USD" in out
    # intersection days only (day0, day2) — middle day skipped, not zero-filled
    assert len(out["BTC/USD"]) == 2
    day0_div = out["BTC/USD"][0][1]
    # HL daily sum day0 = 0.0001*3 = 0.0003; HTX = 0.0002; div = 0.0001
    assert abs(day0_div - 0.0001) < 1e-12
    assert any(n["status"] == "ok" and "intersecting" in n["reason"] for n in notes)


def test_align_skips_missing_symbol() -> None:
    start = datetime(2024, 6, 1, tzinfo=UTC)
    hl = {"BTC/USD": funding_series([0.0001] * 6, start=start)}
    htx = {"BTC/USD": funding_series([0.0002] * 6, start=start)}
    out, notes = align_funding_divergence(hl, htx)
    assert "BTC/USD" in out
    assert "ETH/USD" not in out
    assert any(n["name"] == "funding_div:ETH/USD" and n["status"] == "skipped" for n in notes)


def test_candidates_require_divergence() -> None:
    assert fund_div_candidates(divergence_by_symbol=None) == ()
    assert skipped_fund_div_families(divergence_by_symbol=None)
    start = datetime(2024, 1, 1, tzinfo=UTC)
    div = {
        "BTC/USD": tuple((start + timedelta(days=i), 0.0001 * ((-1) ** i)) for i in range(40)),
        "ETH/USD": tuple((start + timedelta(days=i), 0.0002 * ((-1) ** i)) for i in range(40)),
    }
    cats = fund_div_candidates(divergence_by_symbol=div)
    ids = [c.candidate_id for c in cats]
    assert ids[:6] == list(FUND_DIV_IDS)
    assert ids[-1] == "ma_cross_10_30"


def test_run_funding_div_keep_flag_false_and_no_promote() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    n = 260
    prices = [100.0 + 0.1 * i for i in range(n)]
    histories = {
        "BTC/USD": make_candles(prices, symbol="BTC/USD", start=start),
        "ETH/USD": make_candles([p * 0.05 for p in prices], symbol="ETH/USD", start=start),
    }
    second = {
        "BTC/USD": make_candles([p * 1.001 for p in prices], symbol="BTC/USD", start=start),
        "ETH/USD": make_candles([p * 0.0501 for p in prices], symbol="ETH/USD", start=start),
    }
    # Dense 8h funding on both venues
    hl = {
        "BTC/USD": funding_series([0.0001 + 0.00001 * ((i % 7) - 3) for i in range(n * 3)], start=start),
        "ETH/USD": funding_series([0.0002 + 0.00001 * ((i % 5) - 2) for i in range(n * 3)], start=start),
    }
    htx = {
        "BTC/USD": funding_series([0.00005 + 0.00002 * ((i % 9) - 4) for i in range(n * 3)], start=start),
        "ETH/USD": funding_series([0.00015 + 0.00002 * ((i % 11) - 5) for i in range(n * 3)], start=start),
    }
    report = run_funding_div(
        histories,
        fee_bps=80.0,
        slippage_bps=5.0,
        hl_funding_by_symbol=hl,
        htx_funding_by_symbol=htx,
        second_histories=second,
        primary_candle_venue="kraken",
        second_candle_venue="coinbase",
    )
    assert report.keep_flag_false is True
    assert report.can_promote is False
    assert report.recommended_promote_flag is None
    assert report.print_kind == "dual_print"
    assert report.paper_path_ready is True
    cfg = settings()
    bool_flags = [
        name
        for name in type(cfg).model_fields
        if name.startswith("paper_promote") and isinstance(getattr(cfg, name), bool)
    ]
    assert bool_flags
    for name in bool_flags:
        assert getattr(cfg, name) is False, name


def test_paper_promote_defaults_untouched() -> None:
    cfg = settings()
    bool_flags = [
        name
        for name in type(cfg).model_fields
        if name.startswith("paper_promote") and isinstance(getattr(cfg, name), bool)
    ]
    assert bool_flags, "expected boolean paper_promote_* fields on Settings"
    for name in bool_flags:
        assert getattr(cfg, name) is False, name
