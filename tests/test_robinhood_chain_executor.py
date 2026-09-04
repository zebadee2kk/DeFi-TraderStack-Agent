import json
from typing import Any

import httpx
import pytest

from traderstack.config import Settings
from traderstack.execution.robinhood_chain import (
    ChainConfig,
    EvmJsonRpcClient,
    ExecutionSafetyError,
    RobinhoodChainExecutionPolicy,
    RobinhoodChainExecutor,
    TokenAllowlistEntry,
    chain_config_from_settings,
    policy_from_settings,
)
from traderstack.models import Side
from traderstack.pipeline import PaperOrderIntent

ROUTER = "0x1111111111111111111111111111111111111111"
TOKEN = "0x2222222222222222222222222222222222222222"
WALLET = "0x3333333333333333333333333333333333333333"


def intent(**overrides: Any) -> PaperOrderIntent:
    base = {
        "decision_id": "decision-1",
        "asset": "BTC",
        "side": Side.BUY,
        "notional_usd": 100,
        "venue": "robinhood_chain",
    }
    base.update(overrides)
    return PaperOrderIntent(**base)


def chain() -> ChainConfig:
    return ChainConfig(
        name="robinhood-chain", chain_id=13371, rpc_url="https://rpc.robinhood-chain.example"
    )


def policy(**overrides: Any) -> RobinhoodChainExecutionPolicy:
    base = {
        "allowed_tokens": {
            "BTC": TokenAllowlistEntry(symbol="BTC", contract_address=TOKEN, decimals=18)
        },
        "allowed_routers": frozenset({ROUTER.lower()}),
        "max_notional_usd": 1_000,
        "max_gas_limit": 300_000,
        "max_gas_price_gwei": 10,
    }
    base.update(overrides)
    return RobinhoodChainExecutionPolicy(**base)


def make_rpc(
    client: httpx.AsyncClient,
    chain_id: int = 13371,
    balance: int = 10**18,
    nonce: int = 5,
    gas_estimate: int = 21_000,
    gas_price: int = 2_000_000_000,
    call_error: str | None = None,
) -> EvmJsonRpcClient:
    return EvmJsonRpcClient(rpc_url="https://rpc.robinhood-chain.example", client=client)


def rpc_handler(
    chain_id: int = 13371,
    balance: int = 10**18,
    nonce: int = 5,
    gas_estimate: int = 21_000,
    gas_price: int = 2_000_000_000,
    call_error: str | None = None,
):
    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        method = payload["method"]
        if method == "eth_chainId":
            result = hex(chain_id)
        elif method == "eth_getBalance":
            result = hex(balance)
        elif method == "eth_getTransactionCount":
            result = hex(nonce)
        elif method == "eth_estimateGas":
            result = hex(gas_estimate)
        elif method == "eth_gasPrice":
            result = hex(gas_price)
        elif method == "eth_call":
            if call_error:
                return httpx.Response(
                    200, json={"jsonrpc": "2.0", "id": 1, "error": {"message": call_error}}
                )
            result = "0x"
        else:
            raise AssertionError(f"unexpected RPC method {method}")
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": result})

    return handler


@pytest.mark.asyncio
async def test_happy_path_prepares_unsigned_transaction() -> None:
    transport = httpx.MockTransport(rpc_handler())
    async with httpx.AsyncClient(transport=transport) as client:
        executor = RobinhoodChainExecutor(chain=chain(), policy=policy(), rpc=make_rpc(client))
        tx = await executor.prepare_swap(intent(), WALLET, ROUTER, "0xdeadbeef")
    assert tx.chain_id == 13371
    assert tx.to == ROUTER
    assert tx.data == "0xdeadbeef"
    assert tx.nonce == 5
    assert tx.gas_limit == 21_000
    assert tx.max_fee_per_gas_wei == 2_000_000_000


@pytest.mark.asyncio
async def test_rejects_live_trading_mode() -> None:
    transport = httpx.MockTransport(rpc_handler())
    async with httpx.AsyncClient(transport=transport) as client:
        executor = RobinhoodChainExecutor(chain=chain(), policy=policy(), rpc=make_rpc(client))
        with pytest.raises(ExecutionSafetyError, match="live execution is not enabled"):
            await executor.prepare_swap(intent(), WALLET, ROUTER, "0xdeadbeef", trading_mode="live")


@pytest.mark.asyncio
async def test_rejects_venue_mismatch() -> None:
    transport = httpx.MockTransport(rpc_handler())
    async with httpx.AsyncClient(transport=transport) as client:
        executor = RobinhoodChainExecutor(chain=chain(), policy=policy(), rpc=make_rpc(client))
        with pytest.raises(ExecutionSafetyError, match="venue does not match"):
            await executor.prepare_swap(
                intent(venue="kraken_paper_trade"), WALLET, ROUTER, "0xdeadbeef"
            )


@pytest.mark.asyncio
async def test_rejects_notional_over_policy_cap() -> None:
    transport = httpx.MockTransport(rpc_handler())
    async with httpx.AsyncClient(transport=transport) as client:
        executor = RobinhoodChainExecutor(
            chain=chain(), policy=policy(max_notional_usd=50), rpc=make_rpc(client)
        )
        with pytest.raises(ExecutionSafetyError, match="exceeds on-chain policy cap"):
            await executor.prepare_swap(intent(notional_usd=100), WALLET, ROUTER, "0xdeadbeef")


@pytest.mark.asyncio
async def test_rejects_token_not_on_allowlist() -> None:
    transport = httpx.MockTransport(rpc_handler())
    async with httpx.AsyncClient(transport=transport) as client:
        executor = RobinhoodChainExecutor(chain=chain(), policy=policy(), rpc=make_rpc(client))
        with pytest.raises(ExecutionSafetyError, match="not on the on-chain allowlist"):
            await executor.prepare_swap(intent(asset="DOGE"), WALLET, ROUTER, "0xdeadbeef")


@pytest.mark.asyncio
async def test_rejects_router_not_on_allowlist() -> None:
    transport = httpx.MockTransport(rpc_handler())
    async with httpx.AsyncClient(transport=transport) as client:
        executor = RobinhoodChainExecutor(chain=chain(), policy=policy(), rpc=make_rpc(client))
        with pytest.raises(ExecutionSafetyError, match="not on the on-chain allowlist"):
            await executor.prepare_swap(
                intent(), WALLET, "0x9999999999999999999999999999999999999999", "0xdeadbeef"
            )


@pytest.mark.asyncio
async def test_rejects_chain_id_mismatch() -> None:
    transport = httpx.MockTransport(rpc_handler(chain_id=1))
    async with httpx.AsyncClient(transport=transport) as client:
        executor = RobinhoodChainExecutor(chain=chain(), policy=policy(), rpc=make_rpc(client))
        with pytest.raises(ExecutionSafetyError, match="chain id mismatch"):
            await executor.prepare_swap(intent(), WALLET, ROUTER, "0xdeadbeef")


@pytest.mark.asyncio
async def test_fails_closed_on_zero_balance() -> None:
    transport = httpx.MockTransport(rpc_handler(balance=0))
    async with httpx.AsyncClient(transport=transport) as client:
        executor = RobinhoodChainExecutor(chain=chain(), policy=policy(), rpc=make_rpc(client))
        with pytest.raises(ExecutionSafetyError, match="balance unavailable or zero"):
            await executor.prepare_swap(intent(), WALLET, ROUTER, "0xdeadbeef")


@pytest.mark.asyncio
async def test_rejects_gas_estimate_over_cap() -> None:
    transport = httpx.MockTransport(rpc_handler(gas_estimate=1_000_000))
    async with httpx.AsyncClient(transport=transport) as client:
        executor = RobinhoodChainExecutor(chain=chain(), policy=policy(), rpc=make_rpc(client))
        with pytest.raises(ExecutionSafetyError, match="estimated gas"):
            await executor.prepare_swap(intent(), WALLET, ROUTER, "0xdeadbeef")


@pytest.mark.asyncio
async def test_rejects_gas_price_over_cap() -> None:
    transport = httpx.MockTransport(rpc_handler(gas_price=50_000_000_000))
    async with httpx.AsyncClient(transport=transport) as client:
        executor = RobinhoodChainExecutor(chain=chain(), policy=policy(), rpc=make_rpc(client))
        with pytest.raises(ExecutionSafetyError, match="gas price"):
            await executor.prepare_swap(intent(), WALLET, ROUTER, "0xdeadbeef")


@pytest.mark.asyncio
async def test_fails_closed_on_simulation_revert() -> None:
    transport = httpx.MockTransport(rpc_handler(call_error="execution reverted"))
    async with httpx.AsyncClient(transport=transport) as client:
        executor = RobinhoodChainExecutor(chain=chain(), policy=policy(), rpc=make_rpc(client))
        with pytest.raises(ExecutionSafetyError, match="simulation reverted"):
            await executor.prepare_swap(intent(), WALLET, ROUTER, "0xdeadbeef")


def test_settings_fail_closed_without_configuration() -> None:
    settings = Settings()
    with pytest.raises(ExecutionSafetyError, match="must be configured"):
        chain_config_from_settings(settings)
    with pytest.raises(ExecutionSafetyError, match="must be configured"):
        policy_from_settings(settings)


def test_settings_parse_allowlists_and_config() -> None:
    settings = Settings(
        robinhood_chain_rpc_url="https://rpc.robinhood-chain.example",
        robinhood_chain_id=13371,
        robinhood_chain_allowed_tokens=f"BTC:{TOKEN}:18",
        robinhood_chain_allowed_routers=ROUTER,
        robinhood_chain_max_notional_usd=250,
    )
    resolved_chain = chain_config_from_settings(settings)
    resolved_policy = policy_from_settings(settings)
    assert resolved_chain.chain_id == 13371
    assert resolved_policy.allowed_tokens["BTC"].contract_address == TOKEN
    assert ROUTER.lower() in resolved_policy.allowed_routers
    assert resolved_policy.max_notional_usd == 250
