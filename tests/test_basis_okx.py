"""OKX daily mark−index basis adapter (#134): pagination, guards, backoff."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from traderstack.research.basis import refuse_forbidden_basis_source
from traderstack.research.basis_okx import (
    OKX_BAR,
    OKX_INDEX_CANDLES_PATH,
    OKX_MARK_CANDLES_PATH,
    fetch_okx_basis,
    fetch_okx_daily_closes,
    okx_index_id,
    parse_okx_candle_page,
    parse_okx_candle_rows,
)

DAY_MS = 86_400_000
BASE_DAY = datetime(2024, 3, 1, tzinfo=UTC)


def ts_ms(day_offset: int) -> int:
    return int((BASE_DAY + timedelta(days=day_offset)).timestamp() * 1000)


def row(day_offset: int, close: float, *, confirm: str = "1") -> list[str]:
    return [str(ts_ms(day_offset)), "1", "2", "0.5", str(close), confirm]


async def no_sleep(_seconds: float) -> None:
    return None


class PagedOkx:
    """Serve descending pages of daily closes, honouring ``after``."""

    def __init__(
        self,
        *,
        mark_days: int,
        index_days: int,
        page_size: int = 100,
        fail_statuses: list[int] | None = None,
    ) -> None:
        self.mark_days = mark_days
        self.index_days = index_days
        self.page_size = page_size
        self.fail_statuses = list(fail_statuses or [])
        self.requests: list[httpx.Request] = []

    def _rows(self, path: str) -> list[list[str]]:
        days = self.mark_days if "mark-price" in path else self.index_days
        closes = 100.0 if "mark-price" in path else 99.0
        # newest first, newest row uncommitted
        rows = [row(offset, closes + offset * 0.01) for offset in range(days)]
        rows[-1] = row(days - 1, closes, confirm="0")
        return list(reversed(rows))

    async def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.fail_statuses:
            return httpx.Response(self.fail_statuses.pop(0), text="rate limited")
        params = dict(request.url.params)
        assert params["bar"] == OKX_BAR
        rows = self._rows(request.url.path)
        after = params.get("after")
        if after is not None:
            rows = [item for item in rows if int(item[0]) < int(after)]
        return httpx.Response(200, json={"code": "0", "data": rows[: self.page_size]})


@pytest.fixture
def okx_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url="https://www.okx.com")


def test_index_id_drops_swap_suffix() -> None:
    assert okx_index_id("BTC/USD") == "BTC-USDT"
    assert okx_index_id("ETH/USD") == "ETH-USDT"
    with pytest.raises(ValueError):
        okx_index_id("DOGE/USD")


def test_parse_drops_unconfirmed_and_malformed_rows() -> None:
    payload = {
        "code": "0",
        "data": [
            row(2, 101.0, confirm="0"),
            row(1, 100.5),
            ["bad"],
            [str(ts_ms(0)), "1", "2", "0.5", "nan", "1"],
            [str(ts_ms(0)), "1", "2", "0.5", "-5", "1"],
            "not-a-list",
        ],
    }
    rows, oldest = parse_okx_candle_page(payload)
    assert rows == [(ts_ms(1), 100.5)]
    assert oldest == ts_ms(0)
    assert parse_okx_candle_rows(payload) == rows


def test_parse_rejects_non_zero_code_and_bad_shapes() -> None:
    with pytest.raises(ValueError):
        parse_okx_candle_page({"code": "51001", "msg": "Instrument ID doesn't exist", "data": []})
    with pytest.raises(TypeError):
        parse_okx_candle_page(["not", "an", "object"])
    with pytest.raises(TypeError):
        parse_okx_candle_page({"code": "0", "data": "nope"})


@pytest.mark.asyncio
async def test_pagination_walks_after_older_and_stops_on_empty_page() -> None:
    server = PagedOkx(mark_days=250, index_days=250, page_size=100)
    async with httpx.AsyncClient(
        base_url="https://www.okx.com", transport=httpx.MockTransport(server.handler)
    ) as client:
        result = await fetch_okx_daily_closes(
            client, OKX_MARK_CANDLES_PATH, "BTC-USDT-SWAP", pause_seconds=0, sleep=no_sleep
        )
    # 249 confirmed rows (the newest is uncommitted); three full pages then an empty one
    assert len(result.closes) == 249
    assert result.truncated is False
    afters = [dict(r.url.params).get("after") for r in server.requests]
    assert afters[0] is None
    assert all(a is not None for a in afters[1:])
    assert [int(a) for a in afters[1:] if a] == sorted(
        (int(a) for a in afters[1:] if a), reverse=True
    )


@pytest.mark.asyncio
async def test_page_limit_marks_truncated_not_filled() -> None:
    server = PagedOkx(mark_days=250, index_days=250, page_size=100)
    async with httpx.AsyncClient(
        base_url="https://www.okx.com", transport=httpx.MockTransport(server.handler)
    ) as client:
        result = await fetch_okx_daily_closes(
            client,
            OKX_MARK_CANDLES_PATH,
            "BTC-USDT-SWAP",
            limit_pages=1,
            pause_seconds=0,
            sleep=no_sleep,
        )
    assert len(result.closes) == 99
    assert result.truncated is True
    assert "truncated" in (result.note or "")


@pytest.mark.asyncio
async def test_since_until_bound_the_walk() -> None:
    server = PagedOkx(mark_days=250, index_days=250, page_size=100)
    async with httpx.AsyncClient(
        base_url="https://www.okx.com", transport=httpx.MockTransport(server.handler)
    ) as client:
        result = await fetch_okx_daily_closes(
            client,
            OKX_MARK_CANDLES_PATH,
            "BTC-USDT-SWAP",
            since=BASE_DAY + timedelta(days=200),
            until=BASE_DAY + timedelta(days=220),
            pause_seconds=0,
            sleep=no_sleep,
        )
    days = sorted(result.closes)
    assert days[0] == BASE_DAY + timedelta(days=200)
    assert days[-1] == BASE_DAY + timedelta(days=220)
    assert len(days) == 21
    # the first request carried after=until+1d so newer rows were never asked for
    assert dict(server.requests[0].url.params)["after"] == str(ts_ms(221))


@pytest.mark.asyncio
async def test_non_utc_midnight_rows_are_skipped_not_relabelled() -> None:
    shifted = [str(ts_ms(1) + 16 * 3_600_000), "1", "2", "0.5", "100", "1"]

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": "0", "data": [shifted, row(0, 99.0)]})

    async with httpx.AsyncClient(
        base_url="https://www.okx.com", transport=httpx.MockTransport(handler)
    ) as client:
        result = await fetch_okx_daily_closes(
            client, OKX_MARK_CANDLES_PATH, "BTC-USDT-SWAP", limit_pages=1, sleep=no_sleep
        )
    assert result.closes == {BASE_DAY: 99.0}
    assert result.misaligned == 1


@pytest.mark.asyncio
async def test_basis_is_mark_minus_index_and_one_sided_days_are_skipped() -> None:
    server = PagedOkx(mark_days=40, index_days=30)
    async with httpx.AsyncClient(
        base_url="https://www.okx.com", transport=httpx.MockTransport(server.handler)
    ) as client:
        result = await fetch_okx_basis("BTC/USD", client=client, pause_seconds=0, sleep=no_sleep)
    assert result.status == "ok"
    # index has 29 confirmed days, mark 39: only the 29 shared days survive
    assert len(result.points) == 29
    day, value = result.points[0]
    assert day == BASE_DAY
    assert value == pytest.approx((100.0 - 99.0) / 99.0)
    assert "premium" not in result.source
    assert "one_sided_days_skipped=10" in result.reason
    index_requests = [r for r in server.requests if r.url.path == OKX_INDEX_CANDLES_PATH]
    assert all(dict(r.url.params)["instId"] == "BTC-USDT" for r in index_requests)


@pytest.mark.asyncio
async def test_403_then_200_retries_with_backoff_and_repeated_403_skips() -> None:
    sleeps: list[float] = []

    async def record_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    server = PagedOkx(mark_days=20, index_days=20, fail_statuses=[403, 429])
    async with httpx.AsyncClient(
        base_url="https://www.okx.com", transport=httpx.MockTransport(server.handler)
    ) as client:
        result = await fetch_okx_basis(
            "ETH/USD", client=client, pause_seconds=0, retry_base_seconds=1.0, sleep=record_sleep
        )
    assert result.status == "ok"
    assert sleeps[:2] == [1.0, 2.0]

    always = PagedOkx(mark_days=20, index_days=20, fail_statuses=[403] * 20)
    async with httpx.AsyncClient(
        base_url="https://www.okx.com", transport=httpx.MockTransport(always.handler)
    ) as client:
        result = await fetch_okx_basis(
            "ETH/USD",
            client=client,
            pause_seconds=0,
            max_retries=2,
            retry_base_seconds=0.0,
            sleep=no_sleep,
        )
    assert result.status == "skipped"
    assert result.points == ()
    assert "HTTP 403" in result.reason
    assert "not an empty tape" in result.reason


@pytest.mark.asyncio
async def test_non_zero_code_payload_is_a_skip() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": "51001", "msg": "no such instrument", "data": []})

    async with httpx.AsyncClient(
        base_url="https://www.okx.com", transport=httpx.MockTransport(handler)
    ) as client:
        result = await fetch_okx_basis("BTC/USD", client=client, pause_seconds=0, sleep=no_sleep)
    assert result.status == "skipped"
    assert "51001" in result.reason


@pytest.mark.asyncio
async def test_forbidden_paths_are_refused_before_any_request(
    okx_client: httpx.AsyncClient,
) -> None:
    async with okx_client as client:
        with pytest.raises(ValueError):
            await fetch_okx_daily_closes(client, "/api/v5/market/candles", "BTC-USDT-SWAP")
        with pytest.raises(ValueError):
            await fetch_okx_daily_closes(client, "/api/v5/public/funding-rate-history", "BTC-USDT")
        with pytest.raises(ValueError):
            await fetch_okx_daily_closes(client, "/api/v5/market/premium-history", "BTC-USDT-SWAP")
    for label in (
        "/api/v5/market/candles",
        "/api/v5/market/history-candles",
        "premiumIndexKlines",
        "/fapi/v1/premiumIndex",
        "fundingHistory.premium",
        "candleSnapshot",
        "/api/v1/trade/bucketed?symbol=.XBTUSDPI",
    ):
        with pytest.raises(ValueError):
            refuse_forbidden_basis_source(label)
    refuse_forbidden_basis_source(OKX_MARK_CANDLES_PATH)
    refuse_forbidden_basis_source(OKX_INDEX_CANDLES_PATH)
    refuse_forbidden_basis_source("markPriceKlines")
    refuse_forbidden_basis_source("indexPriceKlines")
