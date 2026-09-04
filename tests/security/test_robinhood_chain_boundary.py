"""Invariant 6: the Robinhood Chain path is read-only and trusts nothing.

Covers SEC-2026-09-07 (a Uniswap v4 `Swap` log carries only a pool id in
`topics[1]`, which any contract can emit, so the decoder accepted a spoofed
swap from an arbitrary address as a real price for an allowlisted pool).

`keccak256` is cross-checked against publicly published digests rather than
against itself. Every vector below was independently reproduced with
PyCryptodome's `Crypto.Hash.keccak` (509 cases, including all sponge-padding
boundaries) before being pinned here.
"""

from __future__ import annotations

import inspect
import math
from typing import Any

import pytest

from traderstack.execution import robinhood_chain as chain_execution
from traderstack.market import robinhood_chain_feed as feed_module
from traderstack.market.robinhood_chain_feed import (
    UNISWAP_V3_SWAP_TOPIC,
    UNISWAP_V4_SWAP_TOPIC,
    OnChainFeedError,
    PoolConfig,
    RobinhoodChainSwapFeed,
    event_topic,
    keccak256,
    parse_swap_log,
    pool_price,
)

POOL_MANAGER = "0x8366a39cc670b4001a1121b8f6a443a643e40951"
V4_POOL_ID = "0x" + "11" * 32
V3_POOL = "0x" + "bb" * 20
HOSTILE_CONTRACT = "0x" + "ff" * 20

# Published Keccak-256 digests (NOT SHA3-256, which uses different padding).
KNOWN_KECCAK_VECTORS = {
    b"": "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470",
    b"abc": "4e03657aea45a94fc7d47ba826c8d667c0d1e6e33a64a036ec44f58fa12d6c45",
    b"testing": "5f16f4c7f149ac4f9510d9cf8cf384038ad348b3bcdc01915f95de12df9d1b02",
    b"a" * 135: "34367dc248bbd832f4e3e69dfaac2f92638bd0bbd18f2912ba4ef454919cf446",
    b"a" * 136: "a6c4d403279fe3e0af03729caada8374b5ca54d8065329a3ebcaeb4b60aa386e",
    b"a" * 200: "96ea54061def936c4be90b518992fdc6f12f535068a256229aca54267b4d084d",
}
# Well-known event topic hashes, independently verifiable on any block explorer.
KNOWN_EVENT_TOPICS = {
    "Transfer(address,address,uint256)": (
        "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
    ),
    "Approval(address,address,uint256)": (
        "0x8c5be1e5ebec7d5bd14f71427d1e84f3dd0314c0f7b2291e5b200ac8c7c3b925"
    ),
    "Swap(address,address,int256,int256,uint160,uint128,int24)": (
        "0xc42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca67"
    ),
}


@pytest.mark.parametrize(("data", "digest"), sorted(KNOWN_KECCAK_VECTORS.items()))
def test_keccak256_matches_published_digests(data: bytes, digest: str) -> None:
    assert keccak256(data).hex() == digest


@pytest.mark.parametrize(("signature", "topic"), sorted(KNOWN_EVENT_TOPICS.items()))
def test_event_topics_match_published_values(signature: str, topic: str) -> None:
    assert event_topic(signature) == topic


def test_the_uniswap_v3_topic_constant_is_the_published_one() -> None:
    assert (
        UNISWAP_V3_SWAP_TOPIC
        == KNOWN_EVENT_TOPICS["Swap(address,address,int256,int256,uint160,uint128,int24)"]
    )


# --- decoding -------------------------------------------------------------


def _word(value: int) -> str:
    return format(value & ((1 << 256) - 1), "064x")


def _pools() -> dict[str, PoolConfig]:
    v4 = PoolConfig(
        symbol="ETH/USDG",
        version="v4",
        pool=V4_POOL_ID,
        token0_decimals=18,
        token1_decimals=6,
        base_is_token0=True,
        fee_bps=5,
    )
    v3 = PoolConfig(
        symbol="BTC/USDG",
        version="v3",
        pool=V3_POOL,
        token0_decimals=8,
        token1_decimals=6,
        base_is_token0=True,
        fee_bps=5,
    )
    return {v4.key: v4, v3.key: v3}


def _sqrt_price() -> int:
    return int((3000 * 10 ** (6 - 18)) ** 0.5 * (1 << 96))


def _data() -> str:
    return (
        "0x"
        + _word(-(10**18))
        + _word(3000 * 10**6)
        + _word(_sqrt_price())
        + _word(10**20)
        + _word(0)
    )


def _v4_log(**overrides: Any) -> dict[str, Any]:
    log = {
        "address": POOL_MANAGER,
        "topics": [UNISWAP_V4_SWAP_TOPIC, V4_POOL_ID],
        "data": _data(),
        "blockNumber": "0x1",
        "transactionHash": "0x" + "ab" * 32,
        "logIndex": "0x0",
    }
    log.update(overrides)
    return log


def test_a_v4_swap_from_a_contract_other_than_the_pool_manager_is_rejected() -> None:
    pools = _pools()
    assert parse_swap_log(_v4_log(), pools, POOL_MANAGER) is not None
    # Any contract can emit an event whose topics claim an allowlisted pool id.
    assert parse_swap_log(_v4_log(address=HOSTILE_CONTRACT), pools, POOL_MANAGER) is None
    assert parse_swap_log(_v4_log(address=""), pools, POOL_MANAGER) is None
    # No pool manager configured means no v4 log can be trusted at all.
    assert parse_swap_log(_v4_log(), pools, None) is None


def test_pool_addresses_and_ids_are_matched_case_insensitively() -> None:
    pools = _pools()
    assert (
        parse_swap_log(
            _v4_log(
                address=POOL_MANAGER.upper(), topics=[UNISWAP_V4_SWAP_TOPIC, V4_POOL_ID.upper()]
            ),
            pools,
            POOL_MANAGER,
        )
        is not None
    )
    v3_log = {
        "address": V3_POOL.upper(),
        "topics": [UNISWAP_V3_SWAP_TOPIC.upper()],
        "data": _data(),
        "blockNumber": "0x1",
        "transactionHash": "0x0",
        "logIndex": "0x0",
    }
    assert parse_swap_log(v3_log, pools, POOL_MANAGER) is not None


def test_a_v3_swap_from_an_unlisted_pool_is_rejected() -> None:
    log = {
        "address": HOSTILE_CONTRACT,
        "topics": [UNISWAP_V3_SWAP_TOPIC],
        "data": _data(),
        "blockNumber": "0x1",
        "transactionHash": "0x0",
        "logIndex": "0x0",
    }
    assert parse_swap_log(log, _pools(), POOL_MANAGER) is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"removed": True},
        {"topics": []},
        {"topics": None},
        {"topics": [UNISWAP_V4_SWAP_TOPIC]},  # v4 needs a pool-id topic
        {"topics": [event_topic("Transfer(address,address,uint256)")]},
    ],
)
def test_structurally_wrong_logs_are_dropped_rather_than_guessed_at(
    overrides: dict[str, Any],
) -> None:
    assert parse_swap_log(_v4_log(**overrides), _pools(), POOL_MANAGER) is None


@pytest.mark.parametrize("data", ["0x", "0x00", "0x" + _word(1) * 4])
def test_truncated_log_data_raises_rather_than_decoding_garbage(data: str) -> None:
    with pytest.raises(OnChainFeedError, match="truncated"):
        parse_swap_log(_v4_log(data=data), _pools(), POOL_MANAGER)


def test_a_zero_sqrt_price_produces_no_event() -> None:
    data = "0x" + _word(-(10**18)) + _word(3000 * 10**6) + _word(0) + _word(1) + _word(0)
    assert parse_swap_log(_v4_log(data=data), _pools(), POOL_MANAGER) is None


def test_an_out_of_range_signed_amount_is_rejected() -> None:
    # int128 field carrying a value only an int256 could hold.
    data = "0x" + _word(1 << 200) + _word(3000 * 10**6) + _word(_sqrt_price()) + _word(1) + _word(0)
    with pytest.raises(OnChainFeedError, match="out of range"):
        parse_swap_log(_v4_log(data=data), _pools(), POOL_MANAGER)


@pytest.mark.parametrize("sqrt_price", [1, 2**96, (1 << 160) - 1, (1 << 256) - 1])
def test_pool_price_never_overflows_or_returns_a_non_positive_price(sqrt_price: int) -> None:
    pool = _pools()[V4_POOL_ID]
    price = pool_price(pool, sqrt_price)
    assert price > 0
    assert not math.isnan(price)
    assert math.isfinite(price)


def test_pool_price_refuses_to_invert_a_zero_price() -> None:
    inverted = PoolConfig(
        symbol="X/Y",
        version="v3",
        pool=V3_POOL,
        token0_decimals=0,
        token1_decimals=36,
        base_is_token0=False,
        fee_bps=5,
    )
    with pytest.raises(OnChainFeedError, match="pool price is zero"):
        pool_price(inverted, 0)


# --- feed identity --------------------------------------------------------


def test_the_subscription_filter_only_ever_asks_for_allowlisted_addresses() -> None:
    pools = tuple(_pools().values())
    feed = RobinhoodChainSwapFeed(
        ws_url="wss://x", expected_chain_id=4663, pools=pools, v4_pool_manager=POOL_MANAGER
    )
    assert feed._subscription_filter(("ETH/USDG",)) == {
        "address": [POOL_MANAGER.lower()],
        "topics": [[UNISWAP_V4_SWAP_TOPIC]],
    }
    with pytest.raises(OnChainFeedError, match="no configured pools match"):
        feed._subscription_filter(("DOGE/USDG",))


def test_a_v4_pool_without_a_pool_manager_refuses_to_build() -> None:
    v4 = _pools()[V4_POOL_ID]
    with pytest.raises(OnChainFeedError, match="PoolManager"):
        RobinhoodChainSwapFeed(ws_url="wss://x", expected_chain_id=4663, pools=(v4,))
    with pytest.raises(OnChainFeedError, match="expected_chain_id"):
        RobinhoodChainSwapFeed(
            ws_url="wss://x", expected_chain_id=0, pools=(v4,), v4_pool_manager=POOL_MANAGER
        )


@pytest.mark.parametrize(
    "pool",
    ["0xshort", "no-0x-prefix", "0x" + "aa" * 21, "0x" + "aa" * 31],
)
def test_a_malformed_pool_identifier_is_refused_at_configuration_time(pool: str) -> None:
    with pytest.raises(ValueError):
        PoolConfig(
            symbol="X/Y",
            version="v3",
            pool=pool,
            token0_decimals=18,
            token1_decimals=6,
            base_is_token0=True,
            fee_bps=5,
        )


def test_the_chain_id_is_verified_on_the_same_connection_that_subscribes() -> None:
    """A separate connection could be answered by a different chain."""

    source = inspect.getsource(RobinhoodChainSwapFeed.stream_swaps)
    chain_check = source.index("eth_chainId")
    mismatch = source.index("chain id mismatch")
    subscribe = source.index("eth_subscribe")
    assert chain_check < mismatch < subscribe
    assert source.count("self.connect(") == 1


# --- nothing signs or broadcasts -----------------------------------------


FORBIDDEN_RPC_METHODS = (
    "eth_sendTransaction",
    "eth_sendRawTransaction",
    "eth_sign",
    "eth_signTransaction",
    "personal_sign",
    "eth_signTypedData",
)


@pytest.mark.parametrize("module", [chain_execution, feed_module])
def test_no_signing_or_broadcasting_rpc_is_reachable(module: Any) -> None:
    source = inspect.getsource(module)
    for method in FORBIDDEN_RPC_METHODS:
        assert method not in source, f"{module.__name__} references {method}"
    for word in ("private_key", "PRIVATE_KEY", "mnemonic", "keystore", "account.sign"):
        assert word not in source, f"{module.__name__} references {word}"


def test_the_executor_stops_at_an_unsigned_transaction() -> None:
    returned = inspect.signature(
        chain_execution.RobinhoodChainExecutor.prepare_swap
    ).return_annotation
    assert returned in ("UnsignedSwapTransaction", chain_execution.UnsignedSwapTransaction)
    assert not hasattr(chain_execution.UnsignedSwapTransaction, "signature")
    assert not hasattr(chain_execution.RobinhoodChainExecutor, "send")
    assert not hasattr(chain_execution.RobinhoodChainExecutor, "broadcast")
    # The JSON-RPC client exposes reads and simulation only.
    public = {
        name
        for name in dir(chain_execution.EvmJsonRpcClient)
        if not name.startswith("_") and callable(getattr(chain_execution.EvmJsonRpcClient, name))
    }
    assert public == {
        "chain_id",
        "get_transaction_count",
        "get_balance",
        "gas_price",
        "estimate_gas",
        "simulate_call",
    }
