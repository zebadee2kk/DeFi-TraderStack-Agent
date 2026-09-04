import json
import math
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any, Self

import pytest

from traderstack.candles import Candle
from traderstack.config import Settings
from traderstack.market.models import MarketSource, ReferencePrice
from traderstack.market.robinhood_chain_feed import (
    UNISWAP_V3_SWAP_TOPIC,
    UNISWAP_V4_SWAP_TOPIC,
    OnChainFeedError,
    PoolConfig,
    RobinhoodChainSwapFeed,
    event_topic,
    keccak256,
    parse_pool_specs,
    parse_swap_log,
    pool_price,
    swap_feed_from_settings,
    tick_from_swap,
)
from traderstack.models import PortfolioSnapshot
from traderstack.pipeline import VerticalSlicePipeline
from traderstack.pretrade import PreTradeBacktestGate
from traderstack.risk import RiskEngine
from traderstack.runtime import PaperRuntime

V3_POOL = "0x1111111111111111111111111111111111111111"
V4_POOL_ID = "0x" + "ab" * 32
POOL_MANAGER = "0x8366a39cc670b4001a1121b8f6a443a643e40951"


def word_int(value: int) -> bytes:
    return (value % (1 << 256)).to_bytes(32, "big")


def sqrt_price_for(price_token1_per_token0: float, dec0: int, dec1: int) -> int:
    raw = price_token1_per_token0 * 10 ** (dec1 - dec0)
    return int(math.sqrt(raw) * (1 << 96))


def v3_pool() -> PoolConfig:
    return PoolConfig(
        symbol="ETH/USDG",
        version="v3",
        pool=V3_POOL,
        token0_decimals=18,
        token1_decimals=6,
        base_is_token0=True,
        fee_bps=5,
    )


def v4_pool() -> PoolConfig:
    # USDG is token0 here, so the base (ETH) is token1.
    return PoolConfig(
        symbol="ETH/USDG",
        version="v4",
        pool=V4_POOL_ID,
        token0_decimals=6,
        token1_decimals=18,
        base_is_token0=False,
        fee_bps=30,
    )


def v3_swap_log(
    amount0: int, amount1: int, sqrt_price: int, *, removed: bool = False
) -> dict[str, Any]:
    data = (
        word_int(amount0)
        + word_int(amount1)
        + word_int(sqrt_price)
        + word_int(10**20)
        + word_int(-12345)
    )
    return {
        "address": V3_POOL,
        "topics": [
            UNISWAP_V3_SWAP_TOPIC,
            "0x" + "00" * 12 + "11" * 20,
            "0x" + "00" * 12 + "22" * 20,
        ],
        "data": "0x" + data.hex(),
        "blockNumber": "0x10",
        "transactionHash": "0xabc",
        "logIndex": "0x2",
        "removed": removed,
    }


def v4_swap_log(amount0: int, amount1: int, sqrt_price: int) -> dict[str, Any]:
    data = (
        word_int(amount0)
        + word_int(amount1)
        + word_int(sqrt_price)
        + word_int(10**20)
        + word_int(777)
        + word_int(3000)
    )
    return {
        "address": POOL_MANAGER,
        "topics": [UNISWAP_V4_SWAP_TOPIC, V4_POOL_ID, "0x" + "00" * 12 + "33" * 20],
        "data": "0x" + data.hex(),
        "blockNumber": "0x11",
        "transactionHash": "0xdef",
        "logIndex": "0x0",
    }


# --- keccak / topics -----------------------------------------------------------


def test_keccak_known_answers() -> None:
    assert (
        keccak256(b"").hex() == "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470"
    )
    assert (
        event_topic("Transfer(address,address,uint256)")
        == "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
    )
    assert (
        UNISWAP_V3_SWAP_TOPIC
        == "0xc42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca67"
    )
    assert UNISWAP_V4_SWAP_TOPIC.startswith("0x") and len(UNISWAP_V4_SWAP_TOPIC) == 66


# --- decoding ------------------------------------------------------------------


def test_pool_price_handles_decimals_and_base_orientation() -> None:
    sqrt_price = sqrt_price_for(3000.0, 18, 6)
    assert pool_price(v3_pool(), sqrt_price) == pytest.approx(3000.0, rel=1e-6)

    inverted = sqrt_price_for(1 / 3000.0, 6, 18)
    assert pool_price(v4_pool(), inverted) == pytest.approx(3000.0, rel=1e-6)


def test_parse_v3_swap_log_buy() -> None:
    pools = {V3_POOL: v3_pool()}
    sqrt_price = sqrt_price_for(3000.0, 18, 6)
    event = parse_swap_log(v3_swap_log(-(10**18), 3_000_000_000, sqrt_price), pools)
    assert event is not None
    assert event.symbol == "ETH/USDG"
    assert event.version == "v3"
    assert event.side == "buy"
    assert event.base_amount == pytest.approx(1.0)
    assert event.quote_amount == pytest.approx(3000.0)
    assert event.price == pytest.approx(3000.0, rel=1e-6)
    assert event.tick == -12345
    assert event.block_number == 16 and event.log_index == 2


def test_parse_v3_swap_log_sell_and_ignores_unknown_pool() -> None:
    pools = {V3_POOL: v3_pool()}
    sqrt_price = sqrt_price_for(2900.0, 18, 6)
    event = parse_swap_log(v3_swap_log(10**18, -2_900_000_000, sqrt_price), pools)
    assert event is not None and event.side == "sell"

    foreign = v3_swap_log(10**18, -2_900_000_000, sqrt_price)
    foreign["address"] = "0x9999999999999999999999999999999999999999"
    assert parse_swap_log(foreign, pools) is None


def test_parse_ignores_removed_reorged_logs_and_other_topics() -> None:
    pools = {V3_POOL: v3_pool()}
    sqrt_price = sqrt_price_for(3000.0, 18, 6)
    assert (
        parse_swap_log(v3_swap_log(-(10**18), 3_000_000_000, sqrt_price, removed=True), pools)
        is None
    )
    other = v3_swap_log(-(10**18), 3_000_000_000, sqrt_price)
    other["topics"][0] = event_topic("Transfer(address,address,uint256)")
    assert parse_swap_log(other, pools) is None


def test_parse_v4_swap_log_uses_pool_id_topic() -> None:
    pools = {V4_POOL_ID: v4_pool()}
    sqrt_price = sqrt_price_for(1 / 3000.0, 6, 18)
    # USDG (token0) into the pool, ETH (token1) out => buy of ETH.
    event = parse_swap_log(v4_swap_log(3_000_000_000, -(10**18), sqrt_price), pools, POOL_MANAGER)
    assert event is not None
    assert event.version == "v4"
    assert event.side == "buy"
    assert event.price == pytest.approx(3000.0, rel=1e-6)
    assert event.base_amount == pytest.approx(1.0)
    assert event.tick == 777

    wrong_id = v4_swap_log(3_000_000_000, -(10**18), sqrt_price)
    wrong_id["topics"][1] = "0x" + "cd" * 32
    assert parse_swap_log(wrong_id, pools, POOL_MANAGER) is None


def test_tick_from_swap_uses_fee_as_spread() -> None:
    pool = v3_pool()
    event = parse_swap_log(
        v3_swap_log(-(10**18), 3_000_000_000, sqrt_price_for(3000.0, 18, 6)), {V3_POOL: pool}
    )
    assert event is not None
    tick = tick_from_swap(event, pool)
    assert tick.source is MarketSource.ROBINHOOD_CHAIN
    assert tick.symbol == "ETH/USDG"
    assert tick.last == pytest.approx(3000.0, rel=1e-6)
    assert tick.spread_bps == pytest.approx(5.0, rel=1e-6)


# --- feed ----------------------------------------------------------------------


class FakeSocket:
    def __init__(self, chain_id_hex: str, logs: list[dict[str, Any]]) -> None:
        self.sent: list[dict[str, Any]] = []
        self._responses = [
            {"jsonrpc": "2.0", "id": 1, "result": chain_id_hex},
            {"jsonrpc": "2.0", "id": 2, "result": "0xsub1"},
        ]
        self._logs = logs

    async def send(self, raw: str) -> None:
        self.sent.append(json.loads(raw))

    async def recv(self) -> str:
        return json.dumps(self._responses.pop(0))

    async def __aiter__(self) -> AsyncIterator[str]:
        for log in self._logs:
            yield json.dumps(
                {
                    "jsonrpc": "2.0",
                    "method": "eth_subscription",
                    "params": {"subscription": "0xsub1", "result": log},
                }
            )
        yield json.dumps(
            {
                "jsonrpc": "2.0",
                "method": "eth_subscription",
                "params": {"subscription": "0xother", "result": {}},
            }
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


def feed_with(
    socket: FakeSocket, pools: tuple[PoolConfig, ...], chain_id: int = 4663
) -> RobinhoodChainSwapFeed:
    return RobinhoodChainSwapFeed(
        ws_url="wss://example",
        expected_chain_id=chain_id,
        pools=pools,
        v4_pool_manager=POOL_MANAGER,
        connect=lambda url: socket,
    )


@pytest.mark.asyncio
async def test_feed_verifies_chain_subscribes_and_streams_ticks() -> None:
    sqrt_price = sqrt_price_for(3000.0, 18, 6)
    socket = FakeSocket(hex(4663), [v3_swap_log(-(10**18), 3_000_000_000, sqrt_price)])
    feed = feed_with(socket, (v3_pool(), v4_pool()))

    ticks = [tick async for tick in feed.stream_ticks(("ETH/USDG",))]

    assert len(ticks) == 1
    assert ticks[0].last == pytest.approx(3000.0, rel=1e-6)
    assert socket.sent[0]["method"] == "eth_chainId"
    subscribe = socket.sent[1]
    assert subscribe["method"] == "eth_subscribe"
    assert subscribe["params"][0] == "logs"
    assert set(subscribe["params"][1]["address"]) == {V3_POOL, POOL_MANAGER}
    assert set(subscribe["params"][1]["topics"][0]) == {
        UNISWAP_V3_SWAP_TOPIC,
        UNISWAP_V4_SWAP_TOPIC,
    }


@pytest.mark.asyncio
async def test_feed_fails_closed_on_chain_id_mismatch() -> None:
    socket = FakeSocket(hex(1), [])
    feed = feed_with(socket, (v3_pool(),))
    with pytest.raises(OnChainFeedError, match="chain id mismatch"):
        async for _ in feed.stream_ticks(("ETH/USDG",)):
            pass
    assert len(socket.sent) == 1  # never subscribed


@pytest.mark.asyncio
async def test_feed_rejects_symbols_with_no_configured_pool() -> None:
    feed = feed_with(FakeSocket(hex(4663), []), (v3_pool(),))
    with pytest.raises(OnChainFeedError, match="no configured pools"):
        async for _ in feed.stream_ticks(("SOL/USDG",)):
            pass


def test_feed_requires_pool_manager_for_v4_pools() -> None:
    with pytest.raises(OnChainFeedError, match="PoolManager"):
        RobinhoodChainSwapFeed(ws_url="wss://x", expected_chain_id=4663, pools=(v4_pool(),))


# --- runtime integration -------------------------------------------------------


class StableReference:
    async def get_prices(self, assets: tuple[str, ...]) -> list[ReferencePrice]:
        return [ReferencePrice(source=MarketSource.COINGECKO, asset=assets[0], price=3000.0)]


class RecordingCandles:
    def __init__(self) -> None:
        self.requested: list[str] = []

    async def fetch(
        self, symbol: str, resolution: str = "1h", *, count: int = 400
    ) -> tuple[Candle, ...]:
        self.requested.append(symbol)
        start = datetime.now(UTC) - timedelta(hours=count)
        candles: list[Candle] = []
        previous = 1000.0
        for index in range(count):
            close = 1000.0 + index * 10.0
            candles.append(
                Candle(
                    symbol=symbol,
                    interval=resolution,
                    opened_at=start + timedelta(hours=index),
                    open=previous,
                    high=max(previous, close) * 1.001,
                    low=min(previous, close) * 0.999,
                    close=close,
                    volume=1_000.0,
                )
            )
            previous = close
        return tuple(candles)


@pytest.mark.asyncio
async def test_runtime_accepts_swap_feed_as_primary_venue() -> None:
    sqrt_price = sqrt_price_for(3000.0, 18, 6)
    socket = FakeSocket(hex(4663), [v3_swap_log(-(10**18), 3_000_000_000, sqrt_price)])
    candles = RecordingCandles()
    runtime = PaperRuntime(
        venue=feed_with(socket, (v3_pool(),)),
        references=(StableReference(),),
        pipeline=VerticalSlicePipeline(
            risk_engine=RiskEngine(Settings(kill_switch=False)),
            pretrade_gate=PreTradeBacktestGate(
                min_excess_return=-1.0,
                max_drawdown=1.0,
                min_sharpe=-100.0,
                min_trades=0,
                require_walkforward=False,
                min_walkforward_excess_return=-1.0,
            ),
        ),
        candles=candles,
        candle_count=300,
    )
    portfolio = PortfolioSnapshot(
        nav_usd=10_000, cash_usd=10_000, daily_pnl_usd=0, peak_nav_usd=10_000
    )

    result = await runtime.run_once("ETH/USDG", portfolio)

    assert result.tick.source is MarketSource.ROBINHOOD_CHAIN
    assert result.pipeline.accepted_market_data is True
    assert result.pipeline.rejection_reasons == []
    assert result.pipeline.proposal is not None and result.pipeline.proposal.asset == "ETH"
    assert candles.requested == ["ETH/USD"]


# --- settings ------------------------------------------------------------------


def test_parse_pool_specs() -> None:
    pools = parse_pool_specs(
        f"eth/usdg:v3:{V3_POOL}:18:6:token0:5, BTC/USDG:v4:{V4_POOL_ID}:8:6:token0:30"
    )
    assert [p.symbol for p in pools] == ["ETH/USDG", "BTC/USDG"]
    assert pools[0].base_is_token0 is True and pools[0].fee_bps == 5
    assert pools[1].version == "v4" and pools[1].token0_decimals == 8
    with pytest.raises(OnChainFeedError, match="malformed"):
        parse_pool_specs("ETH/USDG:v3:0xabc")


def test_swap_feed_from_settings_fails_closed_when_unconfigured() -> None:
    with pytest.raises(OnChainFeedError, match="must be configured"):
        swap_feed_from_settings(Settings())
    with pytest.raises(OnChainFeedError, match="at least one pool"):
        swap_feed_from_settings(Settings(robinhood_chain_ws_url="wss://x", robinhood_chain_id=4663))


def test_swap_feed_from_settings_builds_feed() -> None:
    feed = swap_feed_from_settings(
        Settings(
            robinhood_chain_ws_url="wss://x",
            robinhood_chain_id=4663,
            robinhood_chain_pools=f"ETH/USDG:v3:{V3_POOL}:18:6:token0:5",
        )
    )
    assert feed.expected_chain_id == 4663
    assert feed.pools[0].pool == V3_POOL
