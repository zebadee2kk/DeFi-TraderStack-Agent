"""Robinhood Chain (EVM-compatible) on-chain execution scaffolding.

This module prepares policy-checked, simulated, but UNSIGNED swap transactions.
It never holds a private key and never signs or broadcasts anything: per
docs/RISK-PRINCIPLES.md ("Key custody") and docs/SECURITY-THREAT-MODEL.md
("On-Chain Custody"), signing must happen behind an isolated, policy-controlled
signing/smart-account service (Zone D), outside the agent runtime.

Network identity (chain id, RPC URL) and the token/router allowlists are always
operator-supplied configuration (see Settings in traderstack.config) — nothing
here hardcodes a Robinhood Chain endpoint, chain id or contract address.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import httpx
from pydantic import BaseModel, Field, field_validator

if TYPE_CHECKING:
    from traderstack.config import Settings
    from traderstack.pipeline import PaperOrderIntent


class ExecutionSafetyError(RuntimeError):
    """Raised when a Robinhood Chain execution request violates a hard safety boundary."""


def _is_address(value: str) -> bool:
    return value.startswith("0x") and len(value) == 42


class ChainConfig(BaseModel):
    """Network identity for an EVM-compatible chain such as Robinhood Chain."""

    name: str
    chain_id: int = Field(gt=0)
    rpc_url: str
    native_currency: str = "ETH"
    explorer_url: str | None = None


class TokenAllowlistEntry(BaseModel):
    symbol: str
    contract_address: str
    decimals: int = Field(ge=0, le=36)

    @field_validator("contract_address")
    @classmethod
    def _validate_address_shape(cls, value: str) -> str:
        if not _is_address(value):
            raise ValueError("contract_address must be a 20-byte 0x-prefixed address")
        return value


class RobinhoodChainExecutionPolicy(BaseModel):
    """Deterministic on-chain safety policy. Never relaxed by an LLM at runtime."""

    allowed_tokens: dict[str, TokenAllowlistEntry] = Field(default_factory=dict)
    allowed_routers: frozenset[str] = Field(default_factory=frozenset)
    max_notional_usd: float = Field(gt=0)
    max_gas_limit: int = Field(gt=0)
    max_gas_price_gwei: float = Field(gt=0)

    def require_token_allowed(self, symbol: str) -> TokenAllowlistEntry:
        entry = self.allowed_tokens.get(symbol.upper())
        if entry is None:
            raise ExecutionSafetyError(f"token {symbol} is not on the on-chain allowlist")
        return entry

    def require_router_allowed(self, router_address: str) -> None:
        if router_address.lower() not in self.allowed_routers:
            raise ExecutionSafetyError(f"router {router_address} is not on the on-chain allowlist")


class UnsignedSwapTransaction(BaseModel):
    """A fully policy-checked and simulated, but UNSIGNED, transaction.

    Hand this to the isolated signing/custody boundary. Nothing in this repo
    signs or broadcasts it.
    """

    decision_id: str
    chain_id: int
    to: str
    data: str
    value_wei: int = Field(ge=0)
    gas_limit: int = Field(gt=0)
    max_fee_per_gas_wei: int = Field(gt=0)
    nonce: int = Field(ge=0)


@dataclass
class EvmJsonRpcClient:
    """Minimal read-only/simulation JSON-RPC client. Never signs or broadcasts."""

    rpc_url: str
    client: httpx.AsyncClient | None = None
    timeout: float = 10.0

    async def _call(self, method: str, params: list[Any]) -> Any:
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        if self.client is not None:
            response = await self.client.post(self.rpc_url, json=payload)
        else:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(self.rpc_url, json=payload)
        response.raise_for_status()
        body = response.json()
        if "error" in body:
            raise ExecutionSafetyError(f"RPC error calling {method}: {body['error']}")
        return body["result"]

    async def chain_id(self) -> int:
        return int(await self._call("eth_chainId", []), 16)

    async def get_transaction_count(self, address: str) -> int:
        return int(await self._call("eth_getTransactionCount", [address, "pending"]), 16)

    async def get_balance(self, address: str) -> int:
        return int(await self._call("eth_getBalance", [address, "latest"]), 16)

    async def gas_price(self) -> int:
        return int(await self._call("eth_gasPrice", []), 16)

    async def estimate_gas(self, tx: dict[str, str]) -> int:
        return int(await self._call("eth_estimateGas", [tx]), 16)

    async def simulate_call(self, tx: dict[str, str]) -> str:
        try:
            return await self._call("eth_call", [tx, "latest"])
        except ExecutionSafetyError as exc:
            raise ExecutionSafetyError(f"transaction simulation reverted: {exc}") from exc


@dataclass
class RobinhoodChainExecutor:
    """Prepares policy-checked, simulated unsigned swap transactions for Robinhood Chain."""

    chain: ChainConfig
    policy: RobinhoodChainExecutionPolicy
    rpc: EvmJsonRpcClient
    connector_name: str = "robinhood_chain"

    async def prepare_swap(
        self,
        intent: PaperOrderIntent,
        wallet_address: str,
        router_address: str,
        calldata: str,
        trading_mode: str = "paper",
        value_wei: int = 0,
    ) -> UnsignedSwapTransaction:
        if trading_mode == "live":
            raise ExecutionSafetyError(
                "on-chain live execution is not enabled: signing/custody controls "
                "(docs/ROADMAP.md Phase 8) are not yet built"
            )
        if trading_mode not in {"paper", "shadow"}:
            raise ExecutionSafetyError(f"unsupported trading mode: {trading_mode}")
        if intent.venue != self.connector_name:
            raise ExecutionSafetyError("order intent venue does not match executor connector")
        if intent.notional_usd > self.policy.max_notional_usd:
            raise ExecutionSafetyError("requested notional exceeds on-chain policy cap")
        if not _is_address(wallet_address):
            raise ExecutionSafetyError("wallet_address is not a well-formed address")

        self.policy.require_token_allowed(intent.asset)
        self.policy.require_router_allowed(router_address)

        observed_chain_id = await self.rpc.chain_id()
        if observed_chain_id != self.chain.chain_id:
            raise ExecutionSafetyError(
                f"chain id mismatch: RPC endpoint reports {observed_chain_id}, "
                f"expected {self.chain.chain_id}"
            )

        balance_wei = await self.rpc.get_balance(wallet_address)
        if balance_wei <= 0:
            raise ExecutionSafetyError("wallet balance unavailable or zero; failing closed")

        nonce = await self.rpc.get_transaction_count(wallet_address)

        tx = {
            "from": wallet_address,
            "to": router_address,
            "data": calldata,
            "value": hex(value_wei),
        }

        gas_limit = await self.rpc.estimate_gas(tx)
        if gas_limit > self.policy.max_gas_limit:
            raise ExecutionSafetyError(
                f"estimated gas {gas_limit} exceeds policy cap {self.policy.max_gas_limit}"
            )

        gas_price_wei = await self.rpc.gas_price()
        gas_price_gwei = gas_price_wei / 1_000_000_000
        if gas_price_gwei > self.policy.max_gas_price_gwei:
            raise ExecutionSafetyError(
                f"gas price {gas_price_gwei:.2f} gwei exceeds policy cap "
                f"{self.policy.max_gas_price_gwei} gwei"
            )

        await self.rpc.simulate_call(tx)

        return UnsignedSwapTransaction(
            decision_id=intent.decision_id,
            chain_id=self.chain.chain_id,
            to=router_address,
            data=calldata,
            value_wei=value_wei,
            gas_limit=gas_limit,
            max_fee_per_gas_wei=gas_price_wei,
            nonce=nonce,
        )


def chain_config_from_settings(settings: Settings) -> ChainConfig:
    if not settings.robinhood_chain_rpc_url or not settings.robinhood_chain_id:
        raise ExecutionSafetyError(
            "robinhood_chain_rpc_url and robinhood_chain_id must be configured from "
            "Robinhood Chain's official documentation before on-chain execution can run"
        )
    return ChainConfig(
        name="robinhood-chain",
        chain_id=settings.robinhood_chain_id,
        rpc_url=settings.robinhood_chain_rpc_url,
        native_currency=settings.robinhood_chain_native_currency,
        explorer_url=settings.robinhood_chain_explorer_url,
    )


def policy_from_settings(settings: Settings) -> RobinhoodChainExecutionPolicy:
    if settings.robinhood_chain_max_notional_usd <= 0:
        raise ExecutionSafetyError(
            "robinhood_chain_max_notional_usd must be configured (>0) before "
            "on-chain execution can run"
        )

    tokens: dict[str, TokenAllowlistEntry] = {}
    for raw in settings.robinhood_chain_allowed_tokens.split(","):
        entry = raw.strip()
        if not entry:
            continue
        symbol, address, decimals = entry.split(":")
        symbol = symbol.strip().upper()
        tokens[symbol] = TokenAllowlistEntry(
            symbol=symbol,
            contract_address=address.strip(),
            decimals=int(decimals),
        )

    routers = frozenset(
        router.strip().lower()
        for router in settings.robinhood_chain_allowed_routers.split(",")
        if router.strip()
    )

    return RobinhoodChainExecutionPolicy(
        allowed_tokens=tokens,
        allowed_routers=routers,
        max_notional_usd=settings.robinhood_chain_max_notional_usd,
        max_gas_limit=settings.robinhood_chain_max_gas_limit,
        max_gas_price_gwei=settings.robinhood_chain_max_gas_price_gwei,
    )
