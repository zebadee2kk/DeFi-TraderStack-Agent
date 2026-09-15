"""Coin Metrics community regime adapter (#139): bounded reduction, frozen
derivation, point-in-time lookup, paging, per-day cache, fail-closed."""

from __future__ import annotations

import json
import math
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from traderstack.market.coinmetrics import (
    ASSET_METRICS_PATH,
    COINMETRICS_SOURCE_ID,
    ONCHAIN_REGIME_FEATURE_VERSION,
    ONCHAIN_REGIME_MAX_STALE_DAYS,
    ONCHAIN_REGIME_MIN_POINTS,
    ONCHAIN_REGIME_WINDOW_DAYS,
    CoinMetricsRegimeProvider,
    OnChainDailyRow,
    derive_regime_series,
    drop_uncommitted_rows,
    fetch_asset_metric_rows,
    load_regime_rows_json,
    parse_asset_metric_rows,
    regime_point_before,
    save_regime_rows_json,
)


def _row(day: str, mvrv: str | float, mcap: str | float, asset: str = "btc") -> dict[str, object]:
    return {
        "asset": asset,
        "time": f"{day}T00:00:00.000000000Z",
        "CapMVRVCur": mvrv,
        "CapMrktCurUSD": mcap,
    }


def _rows(count: int, *, start: date = date(2020, 1, 1)) -> tuple[OnChainDailyRow, ...]:
    out: list[OnChainDailyRow] = []
    for index in range(count):
        # Rising cap with a mild cycle so the window stdev is non-zero.
        cap = 1e11 + 2e8 * index + 5e9 * math.sin(index / 37.0)
        mvrv = 1.2 + 0.6 * math.sin(index / 53.0)
        out.append(
            OnChainDailyRow(
                asset="btc",
                day=start + timedelta(days=index),
                mvrv=mvrv,
                market_cap_usd=cap,
            )
        )
    return tuple(out)


# --- parse ---------------------------------------------------------------------


def test_parse_converts_strings_drops_bad_rows_dedupes_and_sorts() -> None:
    payload = {
        "data": [
            _row("2024-01-03", "1.5", "1000"),
            _row("2024-01-01", "2.0", "900"),
            _row("2024-01-02", "0", "950"),  # non-positive mvrv → dropped
            _row("2024-01-04", "nan", "1000"),  # non-finite → dropped
            _row("2024-01-05", "1.1", "-5"),  # non-positive cap → dropped
            _row("2024-01-06", None, "1000"),  # missing → dropped
            _row("2024-01-07", "1.3", "1200", asset="eth"),  # other asset → dropped
            _row("2024-01-01", "2.5", "910"),  # duplicate day → last wins
            {"asset": "btc", "time": "not-a-date", "CapMVRVCur": "1", "CapMrktCurUSD": "1"},
            "garbage",
        ]
    }
    rows = parse_asset_metric_rows(payload, asset="BTC")
    assert [row.day.isoformat() for row in rows] == ["2024-01-01", "2024-01-03"]
    assert rows[0].mvrv == 2.5 and rows[0].market_cap_usd == 910.0
    assert rows[0].realized_cap_usd == pytest.approx(910.0 / 2.5)


def test_parse_raises_type_error_on_community_403_error_body() -> None:
    body = {
        "error": {
            "type": "forbidden",
            "message": (
                "Requested metric 'CapRealUSD' with frequency '1d' for asset 'btc' is not "
                "available with supplied credentials."
            ),
        }
    }
    with pytest.raises(TypeError, match="not available with supplied credentials"):
        parse_asset_metric_rows(body, asset="btc")
    with pytest.raises(TypeError):
        parse_asset_metric_rows(["not", "an", "object"], asset="btc")
    with pytest.raises(TypeError):
        parse_asset_metric_rows({"rows": []}, asset="btc")


# --- derive --------------------------------------------------------------------


def test_nupl_identity_and_realized_cap_identity() -> None:
    rows = _rows(5)
    series = derive_regime_series(rows, window_days=10, min_points=3)
    for row, point in zip(rows, series, strict=True):
        assert point.realized_cap_usd == pytest.approx(row.market_cap_usd / row.mvrv)
        assert point.nupl == pytest.approx(1 - 1 / row.mvrv)


def test_z_and_percentile_are_none_below_min_points_then_bounded() -> None:
    rows = _rows(ONCHAIN_REGIME_MIN_POINTS + 40)
    series = derive_regime_series(rows)
    for point in series[: ONCHAIN_REGIME_MIN_POINTS - 1]:
        assert point.mvrv_z is None
        assert point.mvrv_z_percentile is None
    # z appears once the window has min_points rows; percentile needs
    # min_points z values → strictly later.
    first_z = next(index for index, point in enumerate(series) if point.mvrv_z is not None)
    assert first_z == ONCHAIN_REGIME_MIN_POINTS - 1
    assert all(point.mvrv_z_percentile is None for point in series[first_z : first_z + 10])
    for point in series:
        if point.mvrv_z is not None:
            assert -10.0 <= point.mvrv_z <= 10.0
        if point.mvrv_z_percentile is not None:
            assert 0.0 <= point.mvrv_z_percentile <= 1.0
        assert -5.0 <= point.nupl <= 1.0
        assert point.points <= ONCHAIN_REGIME_WINDOW_DAYS
        assert point.feature_version == ONCHAIN_REGIME_FEATURE_VERSION


def test_percentile_becomes_available_and_reflects_rank_in_window() -> None:
    rows = _rows(2 * ONCHAIN_REGIME_MIN_POINTS + 5)
    series = derive_regime_series(rows)
    with_pct = [point for point in series if point.mvrv_z_percentile is not None]
    assert with_pct, "percentile should appear once min_points z values exist"
    # A hand-check on the last point: share of trailing-window z values <= its z.
    last = series[-1]
    assert last.mvrv_z is not None
    window = [
        point.mvrv_z for point in series[-ONCHAIN_REGIME_WINDOW_DAYS:] if point.mvrv_z is not None
    ]
    expected = sum(1 for value in window if value <= last.mvrv_z) / len(window)
    assert last.mvrv_z_percentile == pytest.approx(expected)


def test_derive_is_point_in_time_later_rows_do_not_change_earlier_points() -> None:
    rows = _rows(60)
    full = derive_regime_series(rows, window_days=20, min_points=5)
    prefix = derive_regime_series(rows[:40], window_days=20, min_points=5)
    assert full[:40] == prefix


def test_derive_rejects_bad_window() -> None:
    with pytest.raises(ValueError):
        derive_regime_series(_rows(3), window_days=0, min_points=1)


def test_drop_uncommitted_rows_drops_today_and_later() -> None:
    rows = _rows(3, start=date(2026, 9, 12))
    kept = drop_uncommitted_rows(rows, today=date(2026, 9, 14))
    assert [row.day.isoformat() for row in kept] == ["2026-09-12", "2026-09-13"]


# --- point-in-time lookup -------------------------------------------------------


def test_regime_point_before_is_strict_and_stale_bounded() -> None:
    rows = _rows(10, start=date(2024, 1, 1))
    series = derive_regime_series(rows, window_days=5, min_points=2)
    decision = datetime(2024, 1, 5, tzinfo=UTC)
    point = regime_point_before(series, decision)
    assert point is not None and point.day == date(2024, 1, 4)  # not 2024-01-04 == bar
    later = regime_point_before(series, decision + timedelta(hours=1))
    assert later is not None and later.day == date(2024, 1, 5)
    # Newest row older than max_stale_days → None (no forward-fill).
    far = datetime(2024, 1, 10, tzinfo=UTC) + timedelta(days=ONCHAIN_REGIME_MAX_STALE_DAYS + 1)
    assert regime_point_before(series, far) is None
    assert regime_point_before(series, datetime(2023, 12, 31, tzinfo=UTC)) is None
    assert regime_point_before((), decision) is None


# --- fetch / paging -------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_follows_next_page_url_and_sleeps_between_pages() -> None:
    calls: list[str] = []
    sleeps: list[float] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if "next_page_token" in request.url.params:
            return httpx.Response(200, json={"data": [_row("2024-01-02", "1.5", "1000")]})
        assert request.url.path == ASSET_METRICS_PATH
        assert request.url.params["metrics"] == "CapMVRVCur,CapMrktCurUSD"
        assert request.url.params["assets"] == "btc"
        return httpx.Response(
            200,
            json={
                "data": [_row("2024-01-01", "1.4", "900")],
                "next_page_url": (
                    "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics"
                    "?assets=btc&next_page_token=abc"
                ),
            },
        )

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    async with httpx.AsyncClient(
        base_url="https://community-api.coinmetrics.io", transport=httpx.MockTransport(handler)
    ) as client:
        rows = await fetch_asset_metric_rows(client, asset="btc", sleep=sleep)
    assert [row.day.isoformat() for row in rows] == ["2024-01-01", "2024-01-02"]
    assert len(calls) == 2 and sleeps == [0.7]


@pytest.mark.asyncio
async def test_fetch_403_surfaces_community_plan_message() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            json={"error": {"type": "forbidden", "message": "not available with credentials"}},
        )

    async with httpx.AsyncClient(
        base_url="https://community-api.coinmetrics.io", transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(httpx.HTTPStatusError, match="not available"):
            await fetch_asset_metric_rows(client, asset="btc")


# --- provider ------------------------------------------------------------------


def _payload(count: int, *, end: date) -> dict[str, object]:
    start = end - timedelta(days=count - 1)
    rows = _rows(count, start=start)
    return {
        "data": [_row(row.day.isoformat(), str(row.mvrv), str(row.market_cap_usd)) for row in rows]
    }


@pytest.mark.asyncio
async def test_provider_builds_snapshot_drops_today_and_caches_per_utc_day() -> None:
    today = date(2026, 9, 14)
    now = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)
    hits = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal hits
        hits += 1
        return httpx.Response(200, json=_payload(2 * ONCHAIN_REGIME_MIN_POINTS + 10, end=today))

    async with httpx.AsyncClient(
        base_url="https://community-api.coinmetrics.io", transport=httpx.MockTransport(handler)
    ) as client:
        provider = CoinMetricsRegimeProvider(client=client, clock=lambda: now)
        first = await provider.fetch("btc")
        second = await provider.fetch("ETH")
    assert hits == 1, "second call the same UTC day must not hit the network"
    assert first.asset == "BTC" and second.asset == "ETH"
    assert first.source_asset == "btc" and second.source_asset == "btc"
    assert first.as_of == today - timedelta(days=1), "today's row is uncommitted"
    assert first.source_id == COINMETRICS_SOURCE_ID
    assert first.feature_version == ONCHAIN_REGIME_FEATURE_VERSION
    assert first.window_days == ONCHAIN_REGIME_WINDOW_DAYS
    assert first.mvrv_z is not None and first.mvrv_z_percentile is not None
    assert 0.0 <= first.mvrv_z_percentile <= 1.0
    assert first.nupl is not None and -5.0 <= first.nupl <= 1.0
    assert first.observed_at == now


@pytest.mark.asyncio
async def test_provider_refetches_on_a_new_utc_day() -> None:
    hits = 0
    clock_now = datetime(2026, 9, 14, 23, 0, tzinfo=UTC)

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal hits
        hits += 1
        return httpx.Response(200, json=_payload(40, end=clock_now.date()))

    async with httpx.AsyncClient(
        base_url="https://community-api.coinmetrics.io", transport=httpx.MockTransport(handler)
    ) as client:
        provider = CoinMetricsRegimeProvider(client=client, clock=lambda: clock_now)
        snapshot = await provider.fetch("btc")
        assert snapshot.mvrv_z is None, "short history → None, never invented"
        clock_now = clock_now + timedelta(hours=2)
        await provider.fetch("btc")
    assert hits == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [403, 500])
async def test_provider_http_error_raises_and_invents_nothing(status: int) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": {"type": "x", "message": "down"}})

    async with httpx.AsyncClient(
        base_url="https://community-api.coinmetrics.io", transport=httpx.MockTransport(handler)
    ) as client:
        provider = CoinMetricsRegimeProvider(client=client)
        with pytest.raises(httpx.HTTPStatusError):
            await provider.fetch("btc")
        assert provider._cache == {}


@pytest.mark.asyncio
async def test_provider_empty_payload_raises() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": []})

    async with httpx.AsyncClient(
        base_url="https://community-api.coinmetrics.io", transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(ValueError, match="no committed rows"):
            await CoinMetricsRegimeProvider(client=client).fetch("btc")


# --- offline rows ----------------------------------------------------------------


def test_rows_json_round_trip(tmp_path: Path) -> None:
    rows = _rows(4)
    path = tmp_path / "rows.json"
    save_regime_rows_json(path, rows)
    assert load_regime_rows_json(path) == rows
    # Hostile / malformed entries are dropped, not invented.
    path.write_text(
        json.dumps(
            [
                {"day": "2024-01-01", "mvrv": "1.2", "market_cap_usd": "100"},
                {"day": "2024-01-02", "mvrv": "-1", "market_cap_usd": "100"},
                {"day": "bad", "mvrv": 1, "market_cap_usd": 1},
                "junk",
            ]
        )
    )
    loaded = load_regime_rows_json(path)
    assert [row.day.isoformat() for row in loaded] == ["2024-01-01"]
    path.write_text(json.dumps({"not": "a list"}))
    with pytest.raises(TypeError):
        load_regime_rows_json(path)
