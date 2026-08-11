from dataclasses import dataclass
from typing import Literal

import httpx
from pydantic import BaseModel, Field

from traderstack.models import Side
from traderstack.pipeline import PaperOrderIntent


class ExecutionSafetyError(RuntimeError):
    """Raised when an execution request violates a hard safety boundary."""


class HummingbotOrderRequest(BaseModel):
    account_name: str
    connector_name: str
    trading_pair: str
    trade_type: Literal["BUY", "SELL"]
    amount: float = Field(gt=0)
    order_type: Literal["MARKET"] = "MARKET"
    position_action: Literal["OPEN"] = "OPEN"


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

    def build_request(
        self,
        intent: PaperOrderIntent,
        execution_price_usd: float,
        trading_mode: str = "paper",
    ) -> HummingbotOrderRequest:
        if trading_mode != "paper":
            raise ExecutionSafetyError("paper executor cannot operate outside paper mode")
        if not self.connector_name.endswith("_paper_trade"):
            raise ExecutionSafetyError("paper executor requires a _paper_trade connector")
        if execution_price_usd <= 0:
            raise ExecutionSafetyError("execution price must be positive")
        if intent.venue != self.connector_name:
            raise ExecutionSafetyError("order intent venue does not match executor connector")

        amount = intent.notional_usd / execution_price_usd
        return HummingbotOrderRequest(
            account_name=self.account_name,
            connector_name=self.connector_name,
            trading_pair=f"{intent.asset.upper()}-USD",
            trade_type="BUY" if intent.side is Side.BUY else "SELL",
            amount=amount,
        )

    async def submit(
        self,
        intent: PaperOrderIntent,
        execution_price_usd: float,
        trading_mode: str = "paper",
    ) -> HummingbotOrderReceipt:
        order = self.build_request(intent, execution_price_usd, trading_mode)
        payload = order.model_dump(exclude_none=True)
        if self.client is not None:
            response = await self.client.post("/trading/orders", json=payload)
        else:
            async with httpx.AsyncClient(
                base_url=self.base_url.rstrip("/"),
                auth=(self.username, self.password),
                timeout=10,
            ) as client:
                response = await client.post("/trading/orders", json=payload)

        if response.status_code != 201:
            raise ExecutionSafetyError(
                f"Hummingbot rejected paper order with HTTP {response.status_code}"
            )
        try:
            return HummingbotOrderReceipt.model_validate(response.json())
        except ValueError as exc:
            raise ExecutionSafetyError("malformed Hummingbot order response") from exc
