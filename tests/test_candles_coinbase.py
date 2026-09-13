"""Coinbase Exchange pager (#133): windows, edges, 429 posture, skips."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from traderstack.research.candles_coinbase import (
    COINBASE_GRANULARITY,
    COINBASE_MAX_CANDLES_PER_REQUEST,
    COINBASE_SOURCE,
    coinbase_granularity,
    coinbase_product,
    fetch_coinbase_candles,
    parse_coinbase_rows,
)

DAY = 86_400
T0 = int(datetime(2016, 1, 1, tzinfo=UTC).timestamp())
BASE = "https://api.exchange.coinbase.com"


def _row(time: int, close: float = 100.0) -> list[float]:
    # [time, low, high, open, close, volume]
    return [time, close - 2, close + 3, close - 1, close, 10.0]


def _iso(seconds: int) -> str:
    return datetime.fromtimestamp(seconds, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(value: str) -> int:
    return int(datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).timestamp())


def test_product_and_granularity_mapping() -> None:
    assert coinbase_product("BTC/USD") == "BTC-USD"
    assert coinbase_product("eth-usd") == "ETH-USD"
    with pytest.raises(ValueError):
        coinbase_product("BTCUSD")
    assert coinbase_granularity("1d") == 86_400
    assert set(COINBASE_GRANULARITY.values()) == {60, 300, 900, 3600, 21600, 86400}
    with pytest.raises(ValueError, match="no 4h"):
        coinbase_granularity("4h")


def test_parse_rows_puts_low_high_open_close_in_the_right_fields() -> None:
    candles = parse_coinbase_rows(
        [[T0 + DAY, 90.0, 110.0, 95.0, 105.0, 7.0], [T0, 80.0, 120.0, 100.0, 100.0, 1.0]],
        symbol="BTC/USD",
        interval="1d",
    )
    assert [c.opened_at.timestamp() for c in candles] == [T0, T0 + DAY]
    second = candles[1]
    assert (second.low, second.high, second.open, second.close, second.volume) == (
        90.0,
        110.0,
        95.0,
        105.0,
        7.0,
    )
    with pytest.raises(TypeError):
        parse_coinbase_rows({"message": "NotFound"}, symbol="BTC/USD", interval="1d")
    with pytest.raises(TypeError):
        parse_coinbase_rows([[T0, 1.0]], symbol="BTC/USD", interval="1d")
    with pytest.raises(ValueError):
        parse_coinbase_rows([[T0, 0.0, 1.0, 1.0, 1.0, 1.0]], symbol="BTC/USD", interval="1d")


@pytest.mark.asyncio
async def test_pager_walks_exact_300_bar_windows_and_skips_over_empty_windows() -> None:
    """Three windows; the middle one is empty (pre-listing style) and must be
    skipped over, not treated as end-of-data. Every window asks for exactly
    300 bars (end = start + 299 g) so it never sits on the venue's 301-row edge."""
    windows: list[tuple[int, int]] = []
    total_days = 3 * COINBASE_MAX_CANDLES_PER_REQUEST
    end = T0 + (total_days - 1) * DAY
    now = datetime.fromtimestamp(end + 10 * DAY, tz=UTC)

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/products/BTC-USD/candles"
        assert request.url.params["granularity"] == "86400"
        start_s = _parse_iso(request.url.params["start"])
        end_s = _parse_iso(request.url.params["end"])
        windows.append((start_s, end_s))
        assert (end_s - start_s) // DAY + 1 <= COINBASE_MAX_CANDLES_PER_REQUEST
        if len(windows) == 2:
            return httpx.Response(200, json=[])
        rows = [_row(t) for t in range(end_s, start_s - 1, -DAY)]  # newest first
        # Duplicate the boundary bar of the first window inside the third page.
        if len(windows) == 3:
            rows.append(_row(windows[0][1], close=999.0))
        return httpx.Response(200, json=rows)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(base_url=BASE, transport=transport) as client:
        fetch = await fetch_coinbase_candles(
            "BTC/USD", "1d", start=T0, end=end, client=client, page_pause_seconds=0, now=now
        )

    assert fetch.status == "ok"
    assert fetch.source == COINBASE_SOURCE
    assert len(windows) == 3
    assert windows[0] == (T0, T0 + 299 * DAY)
    assert windows[1] == (T0 + 300 * DAY, T0 + 599 * DAY)
    assert windows[2] == (T0 + 600 * DAY, T0 + 899 * DAY)
    # 600 bars from two non-empty windows; boundary duplicate deduped (later wins).
    assert len(fetch.candles) == 600
    assert fetch.first is not None and int(fetch.first.timestamp()) == T0
    assert fetch.last is not None and int(fetch.last.timestamp()) == end
    boundary = next(c for c in fetch.candles if int(c.opened_at.timestamp()) == windows[0][1])
    assert boundary.close == 999.0
    # The empty middle window is a 300-bar gap, reported not interpolated.
    assert fetch.gap_entries_total == 1
    assert fetch.missing_bars_total == 300
    assert fetch.candles == tuple(sorted(fetch.candles, key=lambda c: c.opened_at))


@pytest.mark.asyncio
async def test_pager_terminates_at_end_clamps_last_window_and_honours_max_candles() -> None:
    windows: list[tuple[int, int]] = []
    end = T0 + 10 * DAY  # 11 bars total

    async def handler(request: httpx.Request) -> httpx.Response:
        start_s = _parse_iso(request.url.params["start"])
        end_s = _parse_iso(request.url.params["end"])
        windows.append((start_s, end_s))
        return httpx.Response(200, json=[_row(t) for t in range(end_s, start_s - 1, -DAY)])

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(base_url=BASE, transport=transport) as client:
        fetch = await fetch_coinbase_candles(
            "BTC/USD",
            "1d",
            start=T0 + 3600,  # mid-bar start is floored, not passed through
            end=end,
            client=client,
            page_pause_seconds=0,
            now=datetime.fromtimestamp(end + 5 * DAY, tz=UTC),
        )
    assert windows == [(T0, end)]  # clamped to end; never past it
    assert fetch.status == "ok"
    assert len(fetch.candles) == 11

    windows.clear()
    async with httpx.AsyncClient(base_url=BASE, transport=transport) as client:
        capped = await fetch_coinbase_candles(
            "BTC/USD",
            "1d",
            start=T0,
            end=T0 + 1000 * DAY,
            client=client,
            max_candles=5,
            page_pause_seconds=0,
            now=datetime.fromtimestamp(T0 + 2000 * DAY, tz=UTC),
        )
    assert len(windows) == 1  # stopped after the first page once max_candles was reached
    assert capped.status == "ok"
    assert len(capped.candles) == 5

    async with httpx.AsyncClient(base_url=BASE, transport=transport) as client:
        inverted = await fetch_coinbase_candles(
            "BTC/USD", "1d", start=end, end=T0, client=client, page_pause_seconds=0
        )
    assert inverted.status == "skipped"
    assert "after end" in inverted.reason


@pytest.mark.asyncio
async def test_pager_default_end_is_now_and_drops_the_uncommitted_bar() -> None:
    now = datetime.fromtimestamp(T0 + 3 * DAY + 3600, tz=UTC)  # day 3 still open
    windows: list[tuple[int, int]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        start_s = _parse_iso(request.url.params["start"])
        end_s = _parse_iso(request.url.params["end"])
        windows.append((start_s, end_s))
        return httpx.Response(200, json=[_row(t) for t in range(end_s, start_s - 1, -DAY)])

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(base_url=BASE, transport=transport) as client:
        fetch = await fetch_coinbase_candles(
            "BTC/USD", "1d", start=T0, client=client, page_pause_seconds=0, now=now
        )
    assert windows == [(T0, T0 + 3 * DAY)]
    assert fetch.status == "ok"
    assert len(fetch.candles) == 3  # day 3 dropped: its close is still in the future
    assert fetch.fetched_at == now


@pytest.mark.asyncio
async def test_http_429_is_a_skip_with_exactly_one_request_and_no_retry() -> None:
    calls = {"n": 0}

    async def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(429, text="Slow down")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(base_url=BASE, transport=transport) as client:
        fetch = await fetch_coinbase_candles(
            "BTC/USD",
            "1d",
            start=T0,
            end=T0 + 1000 * DAY,
            client=client,
            page_pause_seconds=0,
            now=datetime.fromtimestamp(T0 + 2000 * DAY, tz=UTC),
        )
    assert calls["n"] == 1
    assert fetch.status == "skipped"
    assert "rate limited" in fetch.reason
    assert "429" in fetch.reason
    assert fetch.candles == ()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "needle"),
    [
        (httpx.Response(500, text="upstream"), "500"),
        (httpx.Response(200, text="not json"), "parse failed"),
        (httpx.Response(200, json=[[T0, "x", 1, 1, 1, 1]]), "parse failed"),
        (
            httpx.Response(
                400,
                json={
                    "message": "granularity too small for the requested time range. "
                    "Count of aggregations requested exceeds 300"
                },
            ),
            "exceeds 300",
        ),
        (httpx.Response(404, json={"message": "NotFound"}), "NotFound"),
    ],
)
async def test_http_and_parse_failures_are_skips_never_raises(
    response: httpx.Response, needle: str
) -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return response

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(base_url=BASE, transport=transport) as client:
        fetch = await fetch_coinbase_candles(
            "BTC/USD", "1d", start=T0, end=T0 + DAY, client=client, page_pause_seconds=0
        )
    assert fetch.status == "skipped"
    assert needle in fetch.reason
    assert fetch.candles == ()


@pytest.mark.asyncio
async def test_transport_error_is_a_skip() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(base_url=BASE, transport=transport) as client:
        fetch = await fetch_coinbase_candles(
            "BTC/USD", "1d", start=T0, end=T0 + DAY, client=client, page_pause_seconds=0
        )
    assert fetch.status == "skipped"
    assert "boom" in fetch.reason


@pytest.mark.asyncio
async def test_misaligned_venue_row_is_a_skip_not_a_traceback() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[_row(T0 + 43_200), _row(T0)])

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(base_url=BASE, transport=transport) as client:
        fetch = await fetch_coinbase_candles(
            "BTC/USD",
            "1d",
            start=T0,
            end=T0 + 2 * DAY,
            client=client,
            page_pause_seconds=0,
            now=datetime.fromtimestamp(T0 + 10 * DAY, tz=UTC),
        )
    assert fetch.status == "skipped"
    assert "alignment failed" in fetch.reason


@pytest.mark.asyncio
async def test_unsupported_4h_raises_before_any_request() -> None:
    calls = {"n": 0}

    async def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json=[])

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(base_url=BASE, transport=transport) as client:
        with pytest.raises(ValueError, match="4h"):
            await fetch_coinbase_candles("BTC/USD", "4h", start=T0, client=client)
    assert calls["n"] == 0


@pytest.mark.asyncio
async def test_pager_paces_between_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr("traderstack.research.candles_coinbase.asyncio.sleep", fake_sleep)
    end = T0 + 599 * DAY

    async def handler(request: httpx.Request) -> httpx.Response:
        start_s = _parse_iso(request.url.params["start"])
        end_s = _parse_iso(request.url.params["end"])
        return httpx.Response(200, json=[_row(t) for t in range(end_s, start_s - 1, -DAY)])

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(base_url=BASE, transport=transport) as client:
        fetch = await fetch_coinbase_candles(
            "BTC/USD",
            "1d",
            start=T0,
            end=end,
            client=client,
            page_pause_seconds=0.25,
            now=datetime.fromtimestamp(end + timedelta(days=5).total_seconds(), tz=UTC),
        )
    assert fetch.status == "ok"
    assert sleeps == [0.25]  # one pause between two pages, none before the first
