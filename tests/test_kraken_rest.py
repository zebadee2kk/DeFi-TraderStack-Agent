from datetime import UTC, datetime

import httpx
import pytest

from traderstack.checkpoint import JsonPortfolioCheckpointStore
from traderstack.cli import build_service
from traderstack.config import Settings
from traderstack.market.kraken_candles import KRAKEN_REST_BASE_URL
from traderstack.market.kraken_rest import (
    KRAKEN_TICKER_PATH,
    KrakenRestTickerProvider,
    parse_kraken_rest_ticker,
    require_paper_kraken_rest,
)
from traderstack.market.models import MarketSource
from traderstack.portfolio import InMemoryPortfolioBook


def _ticker_row(*, bid: str, ask: str, last: str) -> dict[str, object]:
    return {
        "a": [ask, "1", "1.000"],
        "b": [bid, "1", "1.000"],
        "c": [last, "0.01"],
        "v": ["1", "2"],
        "p": ["1", "2"],
        "t": [1, 2],
        "l": ["1", "1"],
        "h": ["2", "2"],
        "o": "1",
    }


def test_parse_kraken_rest_ticker_reads_bid_ask_last() -> None:
    ticks = parse_kraken_rest_ticker(
        {
            "error": [],
            "result": {"XXBTZUSD": _ticker_row(bid="999.0", ask="1001.0", last="1000.5")},
        },
        symbols=("BTC/USD",),
        observed_at=datetime(2026, 9, 12, tzinfo=UTC),
    )
    assert len(ticks) == 1
    tick = ticks[0]
    assert tick.source is MarketSource.KRAKEN
    assert tick.symbol == "BTC/USD"
    assert tick.bid == 999.0
    assert tick.ask == 1001.0
    assert tick.last == 1000.5


def test_parse_kraken_rest_ticker_rejects_error_array() -> None:
    with pytest.raises(RuntimeError, match="Unknown asset pair"):
        parse_kraken_rest_ticker(
            {"error": ["EQuery:Unknown asset pair"], "result": {}},
            symbols=("BTC/USD",),
        )


def test_parse_kraken_rest_ticker_rejects_missing_sides() -> None:
    with pytest.raises(TypeError, match="bid/ask/last"):
        parse_kraken_rest_ticker(
            {"error": [], "result": {"BTCUSD": {"a": ["1"], "b": ["1"]}}},
            symbols=("BTC/USD",),
        )


def test_require_paper_kraken_rest_rejects_non_paper() -> None:
    require_paper_kraken_rest("paper", "kraken_rest")
    require_paper_kraken_rest("shadow", "kraken")
    with pytest.raises(RuntimeError, match="paper-only"):
        require_paper_kraken_rest("shadow", "kraken_rest")
    with pytest.raises(RuntimeError, match="paper-only"):
        require_paper_kraken_rest("live", "kraken_rest")


@pytest.mark.asyncio
async def test_kraken_rest_provider_hits_public_ticker_path() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.kraken.com"
        assert request.url.path == KRAKEN_TICKER_PATH
        assert request.url.params["pair"] == "BTCUSD"
        return httpx.Response(
            200,
            json={
                "error": [],
                "result": {"XXBTZUSD": _ticker_row(bid="10", ask="11", last="10.5")},
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(base_url=KRAKEN_REST_BASE_URL, transport=transport) as client:
        provider = KrakenRestTickerProvider(client=client, poll_interval_seconds=0.01)
        ticks = []
        async for tick in provider.stream_ticks(("BTC/USD",)):
            ticks.append(tick)
            break

    assert len(ticks) == 1
    assert ticks[0].last == 10.5


async def _noop(_: object) -> None:
    return None


def test_build_service_wires_kraken_rest_in_paper(tmp_path) -> None:
    settings = Settings(
        kill_switch=False,
        pretrade_backtest_enabled=False,
        venue_feed="kraken_rest",
        kraken_rest_poll_seconds=2.5,
    )
    service = build_service(
        settings,
        submit=False,
        cycle_seconds=5.0,
        portfolio=InMemoryPortfolioBook(settings.paper_starting_nav_usd),
        on_result=_noop,
        checkpoint_store=JsonPortfolioCheckpointStore(tmp_path / "portfolio.json"),
    )
    assert isinstance(service.runtime.venue, KrakenRestTickerProvider)
    assert service.runtime.venue.poll_interval_seconds == 2.5
    assert service.runtime.book is None


def test_build_service_rejects_kraken_rest_outside_paper(tmp_path) -> None:
    settings = Settings(
        kill_switch=False,
        pretrade_backtest_enabled=False,
        venue_feed="kraken_rest",
        trading_mode="shadow",
    )
    with pytest.raises(RuntimeError, match="paper"):
        build_service(
            settings,
            submit=False,
            cycle_seconds=5.0,
            portfolio=InMemoryPortfolioBook(settings.paper_starting_nav_usd),
            on_result=_noop,
            checkpoint_store=JsonPortfolioCheckpointStore(tmp_path / "portfolio.json"),
        )
