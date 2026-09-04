"""Real-time Robinhood Chain swap feed (Uniswap v3 pools and the v4 PoolManager).

Subscribes to ``eth_subscribe("logs")`` over a websocket JSON-RPC endpoint,
decodes Uniswap ``Swap`` events for operator-configured pools, and emits them
as ``MarketTick``s so the existing validation pipeline (staleness, spread,
independent-reference divergence) applies unchanged.

Read-only. It verifies the endpoint's chain id before subscribing, and only
ever watches pools the operator listed — it never discovers or trades tokens
on its own (universe expansion is configuration, per ADR-0001).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal

import websockets
from pydantic import BaseModel, Field, field_validator

from traderstack.market.models import MarketSource, MarketTick

if TYPE_CHECKING:
    from traderstack.config import Settings


class OnChainFeedError(RuntimeError):
    """Raised when the feed cannot be trusted (wrong chain, bad config, bad payload)."""


# --- keccak-256 --------------------------------------------------------------
# hashlib ships SHA3 (different padding), not the Keccak that Ethereum uses, so
# a compact keccak-f[1600] lives here. It runs once per event signature at
# import time; topics are derived from the human-readable signature rather than
# pasted as magic constants.

_ROUND_CONSTANTS = (
    0x0000000000000001,
    0x0000000000008082,
    0x800000000000808A,
    0x8000000080008000,
    0x000000000000808B,
    0x0000000080000001,
    0x8000000080008081,
    0x8000000000008009,
    0x000000000000008A,
    0x0000000000000088,
    0x0000000080008009,
    0x000000008000000A,
    0x000000008000808B,
    0x800000000000008B,
    0x8000000000008089,
    0x8000000000008003,
    0x8000000000008002,
    0x8000000000000080,
    0x000000000000800A,
    0x800000008000000A,
    0x8000000080008081,
    0x8000000000008080,
    0x0000000080000001,
    0x8000000080008008,
)
_ROTATIONS = (
    (0, 36, 3, 41, 18),
    (1, 44, 10, 45, 2),
    (62, 6, 43, 15, 61),
    (28, 55, 25, 21, 56),
    (27, 20, 39, 8, 14),
)
_MASK = (1 << 64) - 1


def _rotl(value: int, shift: int) -> int:
    shift %= 64
    return ((value << shift) | (value >> (64 - shift))) & _MASK if shift else value


def _keccak_f(state: list[int]) -> None:
    for rc in _ROUND_CONSTANTS:
        c = [
            state[x] ^ state[x + 5] ^ state[x + 10] ^ state[x + 15] ^ state[x + 20]
            for x in range(5)
        ]
        d = [c[(x - 1) % 5] ^ _rotl(c[(x + 1) % 5], 1) for x in range(5)]
        for x in range(5):
            for y in range(5):
                state[x + 5 * y] ^= d[x]
        b = [0] * 25
        for x in range(5):
            for y in range(5):
                b[y + 5 * ((2 * x + 3 * y) % 5)] = _rotl(state[x + 5 * y], _ROTATIONS[x][y])
        for x in range(5):
            for y in range(5):
                state[x + 5 * y] = b[x + 5 * y] ^ (
                    (~b[(x + 1) % 5 + 5 * y]) & b[(x + 2) % 5 + 5 * y]
                )
        state[0] ^= rc


def keccak256(data: bytes) -> bytes:
    rate = 136
    padded = bytearray(data)
    padded.append(0x01)
    while len(padded) % rate:
        padded.append(0x00)
    padded[-1] |= 0x80
    state = [0] * 25
    for offset in range(0, len(padded), rate):
        block = padded[offset : offset + rate]
        for lane in range(rate // 8):
            state[lane] ^= int.from_bytes(block[lane * 8 : lane * 8 + 8], "little")
        _keccak_f(state)
    return b"".join(lane.to_bytes(8, "little") for lane in state[:4])


def event_topic(signature: str) -> str:
    return "0x" + keccak256(signature.encode("ascii")).hex()


UNISWAP_V3_SWAP_TOPIC = event_topic("Swap(address,address,int256,int256,uint160,uint128,int24)")
UNISWAP_V4_SWAP_TOPIC = event_topic(
    "Swap(bytes32,address,int128,int128,uint160,uint128,int24,uint24)"
)

# --- configuration -------------------------------------------------------------


class PoolConfig(BaseModel):
    """One operator-allowlisted Uniswap pool to watch."""

    symbol: str
    version: Literal["v3", "v4"]
    pool: str
    token0_decimals: int = Field(ge=0, le=36)
    token1_decimals: int = Field(ge=0, le=36)
    base_is_token0: bool
    fee_bps: float = Field(ge=0, le=1_000)

    @field_validator("pool")
    @classmethod
    def _normalise_pool(cls, value: str) -> str:
        value = value.lower()
        if not value.startswith("0x"):
            raise ValueError("pool must be 0x-prefixed")
        if len(value) not in (42, 66):
            raise ValueError("pool must be a 20-byte address (v3) or 32-byte pool id (v4)")
        return value

    @property
    def key(self) -> str:
        return self.pool


class SwapEvent(BaseModel):
    symbol: str
    pool: str
    version: Literal["v3", "v4"]
    block_number: int = Field(ge=0)
    transaction_hash: str
    log_index: int = Field(ge=0)
    observed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    amount0: int
    amount1: int
    sqrt_price_x96: int = Field(gt=0)
    liquidity: int = Field(ge=0)
    tick: int
    price: float = Field(gt=0)
    base_amount: float = Field(ge=0)
    quote_amount: float = Field(ge=0)
    side: Literal["buy", "sell"]


# --- decoding ------------------------------------------------------------------


def _word(data: bytes, index: int) -> bytes:
    start = index * 32
    if len(data) < start + 32:
        raise OnChainFeedError("swap log data is truncated")
    return data[start : start + 32]


def _uint(data: bytes, index: int) -> int:
    return int.from_bytes(_word(data, index), "big")


def _int(data: bytes, index: int, bits: int) -> int:
    value = int.from_bytes(_word(data, index), "big")
    if value >= 1 << 255:
        value -= 1 << 256
    bound = 1 << (bits - 1)
    if not -bound <= value < bound:
        raise OnChainFeedError(f"int{bits} out of range in swap log")
    return value


def _hex_bytes(value: str) -> bytes:
    return bytes.fromhex(value.removeprefix("0x"))


def pool_price(pool: PoolConfig, sqrt_price_x96: int) -> float:
    """Price of the base token in quote-token units from the pool's sqrtPriceX96."""
    ratio = (sqrt_price_x96 / (1 << 96)) ** 2  # token1 per token0, raw units
    token1_per_token0 = ratio * 10 ** (pool.token0_decimals - pool.token1_decimals)
    if pool.base_is_token0:
        return token1_per_token0
    if token1_per_token0 <= 0:
        raise OnChainFeedError("pool price is zero")
    return 1.0 / token1_per_token0


def parse_swap_log(log: dict[str, Any], pools: dict[str, PoolConfig]) -> SwapEvent | None:
    if log.get("removed"):
        return None
    topics = log.get("topics")
    if not isinstance(topics, list) or not topics:
        return None
    topic0 = str(topics[0]).lower()
    address = str(log.get("address", "")).lower()

    if topic0 == UNISWAP_V3_SWAP_TOPIC:
        pool = pools.get(address)
        if pool is None or pool.version != "v3":
            return None
        data = _hex_bytes(str(log["data"]))
        amount0 = _int(data, 0, 256)
        amount1 = _int(data, 1, 256)
        sqrt_price = _uint(data, 2)
        liquidity = _uint(data, 3)
        tick = _int(data, 4, 24)
    elif topic0 == UNISWAP_V4_SWAP_TOPIC:
        if len(topics) < 2:
            return None
        pool = pools.get(str(topics[1]).lower())
        if pool is None or pool.version != "v4":
            return None
        data = _hex_bytes(str(log["data"]))
        amount0 = _int(data, 0, 128)
        amount1 = _int(data, 1, 128)
        sqrt_price = _uint(data, 2)
        liquidity = _uint(data, 3)
        tick = _int(data, 4, 24)
    else:
        return None

    if sqrt_price <= 0:
        return None

    base_raw, quote_raw = (amount0, amount1) if pool.base_is_token0 else (amount1, amount0)
    base_decimals = pool.token0_decimals if pool.base_is_token0 else pool.token1_decimals
    quote_decimals = pool.token1_decimals if pool.base_is_token0 else pool.token0_decimals
    base_amount = abs(base_raw) / 10**base_decimals
    quote_amount = abs(quote_raw) / 10**quote_decimals
    # In both v3 and v4 a negative amount means the pool paid that token out,
    # i.e. the trader received it. Base flowing out of the pool is a buy.
    side: Literal["buy", "sell"] = "buy" if base_raw < 0 else "sell"

    return SwapEvent(
        symbol=pool.symbol,
        pool=pool.key,
        version=pool.version,
        block_number=int(str(log.get("blockNumber", "0x0")), 16),
        transaction_hash=str(log.get("transactionHash", "")),
        log_index=int(str(log.get("logIndex", "0x0")), 16),
        amount0=amount0,
        amount1=amount1,
        sqrt_price_x96=sqrt_price,
        liquidity=liquidity,
        tick=tick,
        price=pool_price(pool, sqrt_price),
        base_amount=base_amount,
        quote_amount=quote_amount,
        side=side,
    )


def tick_from_swap(event: SwapEvent, pool: PoolConfig) -> MarketTick:
    """An AMM has no order book; its marginal spread at small size is the fee tier."""
    half_fee = pool.fee_bps / 10_000 / 2
    return MarketTick(
        source=MarketSource.ROBINHOOD_CHAIN,
        symbol=event.symbol,
        observed_at=event.observed_at,
        bid=event.price * (1 - half_fee),
        ask=event.price * (1 + half_fee),
        last=event.price,
    )


# --- feed ----------------------------------------------------------------------

ConnectFactory = Callable[[str], Any]


@dataclass
class RobinhoodChainSwapFeed:
    ws_url: str
    expected_chain_id: int
    pools: tuple[PoolConfig, ...]
    v4_pool_manager: str | None = None
    connect: ConnectFactory = field(default=websockets.connect)
    _pools_by_key: dict[str, PoolConfig] = field(init=False, default_factory=dict)

    def __post_init__(self) -> None:
        if self.expected_chain_id <= 0:
            raise OnChainFeedError("expected_chain_id must be positive")
        if not self.pools:
            raise OnChainFeedError("at least one pool must be configured")
        for pool in self.pools:
            if pool.version == "v4" and not self.v4_pool_manager:
                raise OnChainFeedError("v4 pools require the PoolManager address")
            if pool.key in self._pools_by_key:
                raise OnChainFeedError(f"duplicate pool {pool.key}")
            self._pools_by_key[pool.key] = pool
        if self.v4_pool_manager is not None:
            self.v4_pool_manager = self.v4_pool_manager.lower()

    def _subscription_filter(self, symbols: tuple[str, ...]) -> dict[str, Any]:
        wanted = {symbol.upper() for symbol in symbols}
        addresses: set[str] = set()
        topics: set[str] = set()
        for pool in self.pools:
            if pool.symbol.upper() not in wanted:
                continue
            if pool.version == "v3":
                addresses.add(pool.pool)
                topics.add(UNISWAP_V3_SWAP_TOPIC)
            else:
                assert self.v4_pool_manager is not None
                addresses.add(self.v4_pool_manager)
                topics.add(UNISWAP_V4_SWAP_TOPIC)
        if not addresses:
            raise OnChainFeedError(f"no configured pools match symbols {sorted(wanted)}")
        return {"address": sorted(addresses), "topics": [sorted(topics)]}

    async def stream_swaps(self, symbols: tuple[str, ...]) -> AsyncIterator[SwapEvent]:
        log_filter = self._subscription_filter(symbols)
        wanted = {symbol.upper() for symbol in symbols}
        async with self.connect(self.ws_url) as ws:
            await ws.send(
                json.dumps({"jsonrpc": "2.0", "id": 1, "method": "eth_chainId", "params": []})
            )
            chain_response = json.loads(await ws.recv())
            if "error" in chain_response or "result" not in chain_response:
                raise OnChainFeedError(f"eth_chainId failed: {chain_response}")
            observed = int(str(chain_response["result"]), 16)
            if observed != self.expected_chain_id:
                raise OnChainFeedError(
                    f"chain id mismatch: endpoint reports {observed}, expected {self.expected_chain_id}"
                )

            await ws.send(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "eth_subscribe",
                        "params": ["logs", log_filter],
                    }
                )
            )
            subscribe_response = json.loads(await ws.recv())
            if "error" in subscribe_response or not subscribe_response.get("result"):
                raise OnChainFeedError(f"eth_subscribe failed: {subscribe_response}")
            subscription_id = subscribe_response["result"]

            async for raw in ws:
                message = json.loads(raw)
                if message.get("method") != "eth_subscription":
                    continue
                params = message.get("params") or {}
                if params.get("subscription") != subscription_id:
                    continue
                log = params.get("result")
                if not isinstance(log, dict):
                    continue
                event = parse_swap_log(log, self._pools_by_key)
                if event is not None and event.symbol.upper() in wanted:
                    yield event

    async def stream_ticks(self, symbols: tuple[str, ...]) -> AsyncIterator[MarketTick]:
        async for event in self.stream_swaps(symbols):
            yield tick_from_swap(event, self._pools_by_key[event.pool])


# --- settings ------------------------------------------------------------------


def parse_pool_specs(raw: str) -> tuple[PoolConfig, ...]:
    """Parse ``SYMBOL:v3|v4:0xpool:dec0:dec1:token0|token1:fee_bps,...``."""
    pools: list[PoolConfig] = []
    for spec in raw.split(","):
        spec = spec.strip()
        if not spec:
            continue
        parts = spec.split(":")
        if len(parts) != 7:
            raise OnChainFeedError(f"malformed pool spec: {spec!r}")
        symbol, version, pool, dec0, dec1, base, fee = (part.strip() for part in parts)
        if base not in {"token0", "token1"}:
            raise OnChainFeedError(f"base must be token0 or token1 in pool spec: {spec!r}")
        pools.append(
            PoolConfig(
                symbol=symbol.upper(),
                version=version,  # type: ignore[arg-type]
                pool=pool,
                token0_decimals=int(dec0),
                token1_decimals=int(dec1),
                base_is_token0=base == "token0",
                fee_bps=float(fee),
            )
        )
    return tuple(pools)


def swap_feed_from_settings(settings: Settings) -> RobinhoodChainSwapFeed:
    if not settings.robinhood_chain_ws_url or not settings.robinhood_chain_id:
        raise OnChainFeedError(
            "robinhood_chain_ws_url and robinhood_chain_id must be configured before the "
            "Robinhood Chain swap feed can run"
        )
    pools = parse_pool_specs(settings.robinhood_chain_pools)
    if not pools:
        raise OnChainFeedError("robinhood_chain_pools must list at least one pool")
    return RobinhoodChainSwapFeed(
        ws_url=settings.robinhood_chain_ws_url,
        expected_chain_id=settings.robinhood_chain_id,
        pools=pools,
        v4_pool_manager=settings.robinhood_chain_v4_pool_manager or None,
    )
