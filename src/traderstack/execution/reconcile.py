from __future__ import annotations

import math
from dataclasses import dataclass

import httpx
from pydantic import BaseModel, Field

from traderstack.execution.ledger import (
    ExecutionFill,
    ExecutionLedger,
    ExecutionOrder,
    OrderLifecycleState,
)
from traderstack.models import Side
from traderstack.portfolio import InMemoryPortfolioBook


class ReconcileOutcome(BaseModel):
    applied_fills: int = Field(default=0, ge=0)
    skipped_orphan_fills: int = Field(default=0, ge=0)


@dataclass
class HummingbotExecutionReconciler:
    base_url: str
    username: str
    password: str
    account_name: str = "paper_account"
    connector_name: str = "kraken_paper_trade"
    client: httpx.AsyncClient | None = None

    async def reconcile(
        self,
        ledger: ExecutionLedger,
        portfolio: InMemoryPortfolioBook,
    ) -> ReconcileOutcome:
        orders_payload, trades_payload = await self._fetch_state()
        self._reconcile_orders(ledger, orders_payload)
        return self._reconcile_trades(ledger, portfolio, trades_payload)

    async def _fetch_state(self) -> tuple[object, object]:
        payload = {
            "account_name": self.account_name,
            "connector_name": self.connector_name,
        }
        if self.client is not None:
            orders = await self.client.post("/trading/orders/search", json=payload)
            trades = await self.client.post("/trading/trades", json=payload)
        else:
            async with httpx.AsyncClient(
                base_url=self.base_url.rstrip("/"),
                auth=(self.username, self.password),
                timeout=10,
            ) as client:
                orders = await client.post("/trading/orders/search", json=payload)
                trades = await client.post("/trading/trades", json=payload)
        orders.raise_for_status()
        trades.raise_for_status()
        return orders.json(), trades.json()

    def _reconcile_orders(self, ledger: ExecutionLedger, payload: object) -> None:
        rows = self._rows(payload)
        for row in rows:
            order_id = self._text(row, "order_id", "id")
            if order_id not in ledger.orders:
                continue
            raw_status = self._text(row, "status", required=False).lower()
            state = self._map_state(raw_status)
            if state is not None:
                ledger.update_order_state(order_id, state)

    def _reconcile_trades(
        self,
        ledger: ExecutionLedger,
        portfolio: InMemoryPortfolioBook,
        payload: object,
    ) -> ReconcileOutcome:
        outcome = ReconcileOutcome()
        for row in self._rows(payload):
            fill = ExecutionFill(
                fill_id=self._text(row, "trade_id", "id"),
                order_id=self._text(row, "order_id"),
                asset=self._asset(self._text(row, "trading_pair", "symbol")),
                side=self._side(self._text(row, "trade_type", "side")),
                quantity=self._number(row, "amount", "quantity"),
                price_usd=self._number(row, "price"),
                fee_usd=self._number(row, "fee", required=False),
            )
            # Trades for orders this ledger never registered (prior process
            # runs, other account activity) are skipped, not fatal: the venue
            # trades endpoint returns history without a filter, and one orphan
            # must not block the fills that follow it.
            if fill.order_id not in ledger.orders:
                outcome.skipped_orphan_fills += 1
                continue
            if not ledger.validate_fill(fill):
                continue
            # Apply to the book BEFORE consuming the fill id so a failed
            # application is retried on the next pass instead of vanishing.
            portfolio.apply_fill(fill.asset, fill.side, fill.quantity, fill.price_usd)
            ledger.commit_fill(fill)
            outcome.applied_fills += 1
        return outcome

    @staticmethod
    def register_submission(
        ledger: ExecutionLedger,
        *,
        order_id: str,
        decision_id: str,
        asset: str,
        side: Side,
        requested_quantity: float,
    ) -> None:
        ledger.register_order(
            ExecutionOrder(
                order_id=order_id,
                decision_id=decision_id,
                asset=asset,
                side=side,
                requested_quantity=requested_quantity,
            )
        )

    @staticmethod
    def _rows(payload: object) -> list[dict[str, object]]:
        if isinstance(payload, list):
            rows = payload
        elif isinstance(payload, dict):
            candidate = payload.get("data", payload.get("orders", payload.get("trades", [])))
            rows = candidate if isinstance(candidate, list) else []
        else:
            raise TypeError("unexpected Hummingbot response type")
        if not all(isinstance(row, dict) for row in rows):
            raise TypeError("unexpected Hummingbot row type")
        return [dict(row) for row in rows]

    @staticmethod
    def _map_state(status: str) -> OrderLifecycleState | None:
        normalized = status.replace("-", "_").replace(" ", "_")
        mapping = {
            "submitted": OrderLifecycleState.SUBMITTED,
            "pending": OrderLifecycleState.SUBMITTED,
            "open": OrderLifecycleState.OPEN,
            "partially_filled": OrderLifecycleState.PARTIALLY_FILLED,
            "partial": OrderLifecycleState.PARTIALLY_FILLED,
            "filled": OrderLifecycleState.FILLED,
            "completed": OrderLifecycleState.FILLED,
            "cancelled": OrderLifecycleState.CANCELLED,
            "canceled": OrderLifecycleState.CANCELLED,
            "rejected": OrderLifecycleState.REJECTED,
            "failed": OrderLifecycleState.REJECTED,
        }
        return mapping.get(normalized)

    @staticmethod
    def _asset(pair: str) -> str:
        return pair.replace("/", "-").split("-", 1)[0].upper()

    @staticmethod
    def _side(value: str) -> Side:
        normalized = value.upper()
        if normalized == "BUY":
            return Side.BUY
        if normalized == "SELL":
            return Side.SELL
        raise ValueError(f"unsupported trade side {value}")

    @staticmethod
    def _text(
        row: dict[str, object],
        *keys: str,
        required: bool = True,
    ) -> str:
        for key in keys:
            value = row.get(key)
            if isinstance(value, str) and value:
                return value
        if required:
            raise ValueError(f"missing text field from {keys}")
        return ""

    @staticmethod
    def _number(
        row: dict[str, object],
        *keys: str,
        required: bool = True,
    ) -> float:
        for key in keys:
            value = row.get(key)
            number: float | None = None
            if isinstance(value, int | float):
                number = float(value)
            elif isinstance(value, str):
                try:
                    number = float(value)
                except ValueError:
                    number = None
            # Non-finite values (e.g. "1e999" -> inf) are corrupt venue data,
            # not numbers; treat them as missing so they fail closed.
            if number is not None and math.isfinite(number):
                return number
        if required:
            raise ValueError(f"missing numeric field from {keys}")
        return 0.0
