from dataclasses import dataclass
from typing import Literal

import httpx
from pydantic import BaseModel, Field

from traderstack.models import Side
from traderstack.pipeline import PaperOrderIntent


class ExecutionSafetyError(RuntimeError):
    """Raised when an execution request violates a hard safety boundary."""


# --- execution hardening (Epic 8) ---
class HummingbotHttpError(ExecutionSafetyError):
    """A non-201 response from the Hummingbot API, carrying the status code.

    The status code is what lets the submitter separate a *permanent* rejection
    (4xx: the venue understood us and said no) from an *uncertain* one (5xx: the
    request may or may not have reached the venue).
    """

    def __init__(self, status_code: int) -> None:
        super().__init__(f"Hummingbot rejected paper order with HTTP {status_code}")
        self.status_code = status_code

    @property
    def uncertain(self) -> bool:
        return self.status_code >= 500


class HummingbotOrderRequest(BaseModel):
    account_name: str
    connector_name: str
    trading_pair: str
    trade_type: Literal["BUY", "SELL"]
    amount: float = Field(gt=0)
    order_type: Literal["MARKET"] = "MARKET"
    position_action: Literal["OPEN"] = "OPEN"
    # --- execution hardening (Epic 8) ---
    # ASSUMED FIELD NAME. hummingbot-api's TradeRequest (models/trading.py,
    # verified Sept 2026) has no client-order-id field at all: it accepts only
    # account_name / connector_name / trading_pair / trade_type / amount /
    # order_type / price / position_action and mints its own order_id. The field
    # is sent anyway under the conventional name `client_order_id` so the
    # idempotency key reaches any connector or future API version that honours
    # it; today's API ignores unknown fields, so it is inert but harmless.
    # Idempotency therefore does NOT depend on the venue: the authoritative
    # duplicate guard is the persistent ExecutionLedger decision index.
    client_order_id: str | None = None


class HummingbotOrderReceipt(BaseModel):
    order_id: str
    account_name: str
    connector_name: str
    trading_pair: str
    trade_type: str
    amount: float
    order_type: str
    price: float | None = None
    status: str


@dataclass
class HummingbotPaperExecutor:
    base_url: str
    username: str
    password: str
    account_name: str = "paper_account"
    connector_name: str = "kraken_paper_trade"
    client: httpx.AsyncClient | None = None
    timeout_seconds: float = 10.0

    def build_request(
        self,
        intent: PaperOrderIntent,
        execution_price_usd: float,
        trading_mode: str = "paper",
        *,
        quantity: float | None = None,
        client_order_id: str | None = None,
    ) -> HummingbotOrderRequest:
        if trading_mode != "paper":
            raise ExecutionSafetyError("paper executor cannot operate outside paper mode")
        if not self.connector_name.endswith("_paper_trade"):
            raise ExecutionSafetyError("paper executor requires a _paper_trade connector")
        if execution_price_usd <= 0:
            raise ExecutionSafetyError("execution price must be positive")
        if intent.venue != self.connector_name:
            raise ExecutionSafetyError("order intent venue does not match executor connector")

        # A planner-supplied quantity is already lot-rounded and notional-checked;
        # without one, fall back to the naive notional/price conversion.
        amount = quantity if quantity is not None else intent.notional_usd / execution_price_usd
        if amount <= 0:
            raise ExecutionSafetyError("order quantity must be positive")
        return HummingbotOrderRequest(
            account_name=self.account_name,
            connector_name=self.connector_name,
            trading_pair=f"{intent.asset.upper()}-USD",
            trade_type="BUY" if intent.side is Side.BUY else "SELL",
            amount=amount,
            client_order_id=client_order_id,
        )

    async def submit(
        self,
        intent: PaperOrderIntent,
        execution_price_usd: float,
        trading_mode: str = "paper",
        *,
        quantity: float | None = None,
        client_order_id: str | None = None,
    ) -> HummingbotOrderReceipt:
        order = self.build_request(
            intent,
            execution_price_usd,
            trading_mode,
            quantity=quantity,
            client_order_id=client_order_id,
        )
        payload = order.model_dump(exclude_none=True)
        if self.client is not None:
            response = await self.client.post("/trading/orders", json=payload)
        else:
            async with httpx.AsyncClient(
                base_url=self.base_url.rstrip("/"),
                auth=(self.username, self.password),
                timeout=self.timeout_seconds,
            ) as client:
                response = await client.post("/trading/orders", json=payload)

        if response.status_code != 201:
            raise HummingbotHttpError(response.status_code)
        try:
            return HummingbotOrderReceipt.model_validate(response.json())
        except ValueError as exc:
            raise ExecutionSafetyError("malformed Hummingbot order response") from exc
