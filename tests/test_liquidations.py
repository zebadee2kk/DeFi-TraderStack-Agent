"""Binance USDT-M forceOrder adapter — recorded fixtures, no network."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Self

import pytest

from traderstack.market.liquidations import (
    BINANCE_FORCE_ORDER_URL,
    BinanceForceOrderProvider,
    LiquidationAggregator,
    parse_force_order_message,
)
from traderstack.market.models import LiquidationEvent, LiquidationSide, MarketSource
from traderstack.market.streaming import FeedExhausted

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "edge" / "binance_force_order.json"


def _fixtures() -> dict[str, Any]:
    return json.loads(FIXTURES.read_text(encoding="utf-8"))


def test_parse_single_force_order_is_a_long_liquidation() -> None:
    events = parse_force_order_message(_fixtures()["single"], assets=("BTC", "ETH"))
    assert len(events) == 1
    event = events[0]
    assert event.source is MarketSource.BINANCE
    assert event.asset == "BTC"
    assert event.symbol == "BTCUSDT"
    assert event.side is LiquidationSide.LONG
    assert event.qty == pytest.approx(0.014)
    assert event.price == pytest.approx(9910)
    assert event.notional == pytest.approx(0.014 * 9910)


def test_parse_buy_force_order_is_a_short_liquidation() -> None:
    events = parse_force_order_message(_fixtures()["short_liq"], assets=("ETH",))
    assert events[0].asset == "ETH"
    assert events[0].side is LiquidationSide.SHORT
    assert events[0].notional == pytest.approx(2.5 * 3500.5)


def test_parse_array_and_combined_wrapper_shapes() -> None:
    array_events = parse_force_order_message(
        _fixtures()["array"], assets=("BTC", "ETH", "SOL")
    )
    assert {e.asset for e in array_events} == {"BTC", "SOL"}
    combined = parse_force_order_message(_fixtures()["combined"], assets=("BTC",))
    assert len(combined) == 1
    assert combined[0].side is LiquidationSide.SHORT


def test_parse_drops_assets_outside_the_allowlist() -> None:
    assert parse_force_order_message(_fixtures()["ignored_asset"], assets=("BTC",)) == []


def test_parse_ignores_malformed_rows() -> None:
    assert parse_force_order_message({"e": "forceOrder", "o": {"s": "BTCUSDT"}}) == []
    assert parse_force_order_message("not-json-object") == []
    assert parse_force_order_message({"result": None, "id": 1}) == []


def _event(
    *,
    asset: str = "BTC",
    side: LiquidationSide = LiquidationSide.LONG,
    notional: float = 1000.0,
    observed_at: datetime,
) -> LiquidationEvent:
    price = 10_000.0
    qty = notional / price
    return LiquidationEvent(
        source=MarketSource.BINANCE,
        symbol=f"{asset}USDT",
        asset=asset,
        observed_at=observed_at,
        side=side,
        qty=qty,
        price=price,
        notional=notional,
    )


def test_aggregator_bounded_counts_and_zscore_after_baseline() -> None:
    start = datetime(2026, 9, 12, 10, 0, tzinfo=UTC)
    aggregator = LiquidationAggregator(window_seconds=60, baseline_seconds=300, count_cap=4)
    # Three completed 60s windows with different notionals, then a live burst.
    for offset, notional in ((0, 500.0), (60, 1_000.0), (120, 1_500.0)):
        aggregator.ingest(
            _event(notional=notional, observed_at=start + timedelta(seconds=offset))
        )
    burst_at = start + timedelta(seconds=180)
    aggregator.ingest(_event(notional=4_000, observed_at=burst_at))

    snap = aggregator.snapshot("BTC", now=burst_at)
    assert snap.long_notional == pytest.approx(4_000)
    assert snap.liq_count_long == pytest.approx(1.0 / 4)  # one event, cap 4
    assert snap.liq_notional_long_z is not None
    assert snap.liq_notional_long_z > 0
    assert snap.liq_count_short == 0.0
    assert snap.source_id == "binance_liq"


def test_aggregator_quiet_window_reports_zero_counts() -> None:
    start = datetime(2026, 9, 12, 10, 0, tzinfo=UTC)
    aggregator = LiquidationAggregator(window_seconds=60, baseline_seconds=300, count_cap=10)
    aggregator.ingest(_event(notional=500, observed_at=start))
    later = aggregator.snapshot("BTC", now=start + timedelta(seconds=120))
    assert later.long_notional == 0.0
    assert later.liq_count_long == 0.0


# --- streaming with reconnect (fake sockets, no network) ----------------------


class FakeSocket:
    def __init__(self, messages: list[str]) -> None:
        self.sent: list[str] = []
        self._messages = list(messages)

    async def send(self, raw: str) -> None:
        self.sent.append(raw)

    async def recv(self) -> str:
        if not self._messages:
            raise ConnectionResetError("peer closed")
        return self._messages.pop(0)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


def _connect_sequence(items: list[Any]) -> Any:
    calls = {"n": 0}

    def connect(url: str, **kwargs: object) -> Any:
        item = items[calls["n"]]
        calls["n"] += 1
        if isinstance(item, BaseException):
            raise item
        return item

    connect.calls = calls  # type: ignore[attr-defined]
    return connect


def _instant_sleep(_: float) -> Any:
    return asyncio.sleep(0)


@pytest.mark.asyncio
async def test_force_order_provider_reconnects_and_collects_from_fixtures() -> None:
    payload = json.dumps(_fixtures()["single"])
    first = FakeSocket([payload])
    second = FakeSocket([json.dumps(_fixtures()["combined"])])
    connect = _connect_sequence([OSError("refused"), first, second])
    provider = BinanceForceOrderProvider(
        assets=("BTC",),
        connect=connect,
        sleep=_instant_sleep,
        random_jitter=lambda: 0.0,
        stale_after_seconds=0,
    )

    events = []
    async for event in provider.stream_events():
        events.append(event)
        if len(events) == 2:
            break

    assert [e.side for e in events] == [LiquidationSide.LONG, LiquidationSide.SHORT]
    assert connect.calls["n"] == 3
    assert provider.url == BINANCE_FORCE_ORDER_URL


@pytest.mark.asyncio
async def test_force_order_collect_updates_snapshot_without_network() -> None:
    payload = json.dumps(_fixtures()["single"])
    connect = _connect_sequence([FakeSocket([payload])])
    provider = BinanceForceOrderProvider(
        assets=("BTC",),
        connect=connect,
        sleep=_instant_sleep,
        random_jitter=lambda: 0.0,
        max_reconnect_attempts=0,
    )

    with pytest.raises(FeedExhausted):
        await provider.collect()

    snap = provider.snapshot("BTC")
    assert snap is not None
    assert snap.long_notional == pytest.approx(0.014 * 9910)
    assert snap.liq_count_long > 0


@pytest.mark.asyncio
async def test_force_order_gives_up_after_max_reconnects() -> None:
    connect = _connect_sequence([OSError("down")] * 6)
    provider = BinanceForceOrderProvider(
        assets=("BTC",),
        connect=connect,
        sleep=_instant_sleep,
        random_jitter=lambda: 0.0,
        max_reconnect_attempts=2,
    )
    with pytest.raises(FeedExhausted):
        async for _event in provider.stream_events():
            pass
    assert connect.calls["n"] == 3
