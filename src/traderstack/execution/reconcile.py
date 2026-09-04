from __future__ import annotations

from dataclasses import dataclass

import httpx
from pydantic import BaseModel, Field

from traderstack.execution.ledger import (
    TERMINAL_ORDER_STATES,
    ExecutionFill,
    ExecutionLedger,
    ExecutionOrder,
    OrderLifecycleState,
    is_legal_transition,
)
from traderstack.models import Side
from traderstack.portfolio import InMemoryPortfolioBook

# --- execution hardening (Epic 8) ---
# hummingbot-api's TradeRequest carries no client order id (verified Sept 2026),
# so a connector that does echo one may surface it under any of these keys. All
# are checked before concluding the venue does not know an uncertain submission.
CLIENT_ORDER_ID_KEYS: tuple[str, ...] = (
    "client_order_id",
    "clientOrderId",
    "client_id",
    "custom_id",
    "order_id",
    "id",
)


class ExecutionReconciliationResult(BaseModel):
    """Outcome of one venue-state reconciliation pass."""

    applied_fills: int = Field(default=0, ge=0)
    venue_orders: int = Field(default=0, ge=0)
    conflicts: list[str] = Field(default_factory=list)

    @property
    def matched(self) -> bool:
        return not self.conflicts


@dataclass
class HummingbotExecutionReconciler:
    base_url: str
    username: str
    password: str
    account_name: str = "paper_account"
    connector_name: str = "kraken_paper_trade"
    client: httpx.AsyncClient | None = None
    timeout_seconds: float = 10.0

    async def reconcile(self, ledger: ExecutionLedger, portfolio: InMemoryPortfolioBook) -> int:
        """Backwards-compatible entry point returning only the applied fill count."""

        return (await self.reconcile_state(ledger, portfolio)).applied_fills

    async def reconcile_state(
        self, ledger: ExecutionLedger, portfolio: InMemoryPortfolioBook
    ) -> ExecutionReconciliationResult:
        orders_payload, trades_payload = await self._fetch_state()
        rows = self._rows(orders_payload)
        # Fills are applied before venue statuses so a status of "filled" lands on
        # an order whose quantities already reflect the trades behind it.
        applied = self._reconcile_trades(ledger, portfolio, trades_payload)
        conflicts = self._reconcile_orders(ledger, rows)
        return ExecutionReconciliationResult(
            applied_fills=applied,
            venue_orders=len(rows),
            conflicts=conflicts,
        )

    async def venue_knows_order(
        self,
        ledger: ExecutionLedger,
        *,
        client_order_id: str,
        trading_pair: str,
        trade_type: str,
        quantity: float,
        quantity_tolerance: float = 1e-9,
    ) -> bool:
        """Does the venue know about an uncertain submission?

        Returns ``True`` when the venue reports an order carrying our client
        order id, or an order this ledger cannot account for that matches the
        planned pair/side/quantity — the fail-closed reading, since the API does
        not persist client order ids. Any transport or HTTP failure propagates:
        the caller must keep the submission uncertain rather than treat an
        unanswered question as "the venue never saw it".
        """

        rows = self._rows(await self._fetch_orders())
        for row in rows:
            for key in CLIENT_ORDER_ID_KEYS:
                value = row.get(key)
                if isinstance(value, str) and value == client_order_id:
                    return True

            identifier = self._text(row, "order_id", "id", required=False)
            if identifier and ledger.find_order(identifier) is not None:
                continue
            if self._matches_plan(row, trading_pair, trade_type, quantity, quantity_tolerance):
                return True
        return False

    def _matches_plan(
        self,
        row: dict[str, object],
        trading_pair: str,
        trade_type: str,
        quantity: float,
        tolerance: float,
    ) -> bool:
        pair = self._text(row, "trading_pair", "symbol", required=False)
        side = self._text(row, "trade_type", "side", required=False)
        if not pair or not side:
            return False
        if self._asset(pair) != self._asset(trading_pair):
            return False
        if side.upper() != trade_type.upper():
            return False
        amount = self._number(row, "amount", "quantity", required=False)
        return abs(amount - quantity) <= max(tolerance, abs(quantity) * 1e-6)

    async def _fetch_state(self) -> tuple[object, object]:
        payload = self._search_payload()
        if self.client is not None:
            orders = await self.client.post("/trading/orders/search", json=payload)
            trades = await self.client.post("/trading/trades", json=payload)
        else:
            async with self._new_client() as client:
                orders = await client.post("/trading/orders/search", json=payload)
                trades = await client.post("/trading/trades", json=payload)
        orders.raise_for_status()
        trades.raise_for_status()
        return orders.json(), trades.json()

    async def _fetch_orders(self) -> object:
        payload = self._search_payload()
        if self.client is not None:
            orders = await self.client.post("/trading/orders/search", json=payload)
        else:
            async with self._new_client() as client:
                orders = await client.post("/trading/orders/search", json=payload)
        orders.raise_for_status()
        return orders.json()

    def _search_payload(self) -> dict[str, str]:
        return {
            "account_name": self.account_name,
            "connector_name": self.connector_name,
        }

    def _new_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.base_url.rstrip("/"),
            auth=(self.username, self.password),
            timeout=self.timeout_seconds,
        )

    def _reconcile_orders(
        self, ledger: ExecutionLedger, rows: list[dict[str, object]]
    ) -> list[str]:
        conflicts: list[str] = []
        for row in rows:
            identifier = self._text(row, "order_id", "id")
            order = ledger.find_order(identifier)
            if order is None:
                continue
            raw_status = self._text(row, "status", required=False).lower()
            state = self._map_state(raw_status)
            if state is None:
                continue
            if is_legal_transition(order.state, state):
                ledger.update_order_state(order.order_id, state)
                continue
            if order.state in TERMINAL_ORDER_STATES:
                # We consider this order closed and the venue does not: real
                # divergence, and the service must stop taking new risk.
                conflicts.append(
                    f"order {order.order_id} is {order.state} locally but "
                    f"{raw_status or 'unknown'} at the venue"
                )
            # Otherwise the venue snapshot simply lags our fill-derived state
            # (e.g. still "open" while we already booked a partial fill).
        return conflicts

    def _reconcile_trades(
        self,
        ledger: ExecutionLedger,
        portfolio: InMemoryPortfolioBook,
        payload: object,
    ) -> int:
        applied = 0
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
            if ledger.record_fill(fill):
                portfolio.apply_fill(fill.asset, fill.side, fill.quantity, fill.price_usd)
                applied += 1
        return applied

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
            "acknowledged": OrderLifecycleState.ACKNOWLEDGED,
            "created": OrderLifecycleState.ACKNOWLEDGED,
            "open": OrderLifecycleState.OPEN,
            "partially_filled": OrderLifecycleState.PARTIALLY_FILLED,
            "partial": OrderLifecycleState.PARTIALLY_FILLED,
            "filled": OrderLifecycleState.FILLED,
            "completed": OrderLifecycleState.FILLED,
            "cancelled": OrderLifecycleState.CANCELLED,
            "canceled": OrderLifecycleState.CANCELLED,
            "rejected": OrderLifecycleState.REJECTED,
            "failed": OrderLifecycleState.REJECTED,
            "expired": OrderLifecycleState.EXPIRED,
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
            if isinstance(value, int | float):
                return float(value)
            if isinstance(value, str):
                try:
                    return float(value)
                except ValueError:
                    pass
        if required:
            raise ValueError(f"missing numeric field from {keys}")
        return 0.0
