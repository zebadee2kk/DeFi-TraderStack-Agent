from datetime import UTC, datetime

import httpx
import pytest

from traderstack.research.download_candles import (
    _kraken_pair,
    _parse_since,
    download_candles,
    fetch_ohlc_page,
)


def test_kraken_pair_formats_symbol() -> None:
    assert _kraken_pair("BTC/USD") == "BTCUSD"
    assert _kraken_pair("eth/usd") == "ETHUSD"


def test_kraken_pair_rejects_malformed_symbol() -> None:
    with pytest.raises(ValueError):
        _kraken_pair("BTCUSD")


def test_parse_since_accepts_unix_seconds_and_iso() -> None:
    assert _parse_since(None) is None
    assert _parse_since("1700000000") == 1_700_000_000
    parsed = _parse_since("2026-01-01T00:00:00+00:00")
    assert parsed == int(datetime(2026, 1, 1, tzinfo=UTC).timestamp())


def _row(time: int, price: float) -> list[object]:
    return [time, f"{price}", f"{price + 1}", f"{price - 1}", f"{price}", f"{price}", "10.0", 5]


@pytest.mark.asyncio
async def test_fetch_ohlc_page_parses_kraken_response() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/0/public/OHLC"
        assert request.url.params["pair"] == "BTCUSD"
        assert request.url.params["interval"] == "60"
        return httpx.Response(
            200,
            json={
                "error": [],
                "result": {
                    "BTCUSD": [_row(1_700_000_000, 100.0), _row(1_700_003_600, 101.0)],
                    "last": 1_700_003_600,
                },
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(base_url="https://api.kraken.com", transport=transport) as client:
        rows, last = await fetch_ohlc_page(client, pair="BTCUSD", interval_minutes=60, since=None)

    assert last == 1_700_003_600
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_fetch_ohlc_page_raises_on_kraken_error() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"error": ["EQuery:Unknown asset pair"], "result": {}})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(base_url="https://api.kraken.com", transport=transport) as client:
        with pytest.raises(RuntimeError):
            await fetch_ohlc_page(client, pair="NOPE", interval_minutes=60, since=None)


@pytest.mark.asyncio
async def test_download_candles_pages_forward_and_drops_the_uncommitted_bar() -> None:
    """Three calls: an initial page, a page that walks forward via `since`/`last`
    and reveals one genuinely new candle, and a final page with no forward
    progress that stops the walk -- verifying pages are merged by timestamp and
    the very last (always "not yet committed") candle is dropped from the result."""
    base = 1_700_000_000
    pages = [
        ([_row(base, 100.0), _row(base + 3600, 101.0), _row(base + 2 * 3600, 102.0)], base + 2 * 3600),
        ([_row(base + 2 * 3600, 102.0), _row(base + 3 * 3600, 103.0)], base + 3 * 3600),
        ([_row(base + 2 * 3600, 102.0), _row(base + 3 * 3600, 103.0)], base + 3 * 3600),
    ]
    calls: list[int | None] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        since_param = request.url.params.get("since")
        since = int(since_param) if since_param else None
        calls.append(since)
        rows, last = pages[min(len(calls) - 1, len(pages) - 1)]
        return httpx.Response(200, json={"error": [], "result": {"BTCUSD": rows, "last": last}})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(base_url="https://api.kraken.com", transport=transport) as client:
        candles = await download_candles("BTC/USD", "1h", client=client, max_candles=100)

    assert calls == [None, base + 2 * 3600, base + 3 * 3600]
    # 4 distinct timestamps observed (0,1,2,3 hours in) minus the always-dropped
    # final (uncommitted) bar.
    assert len(candles) == 3
    assert candles[0].opened_at < candles[-1].opened_at
    assert candles[-1].close == 102.0  # the (now committed) second-page value wins
