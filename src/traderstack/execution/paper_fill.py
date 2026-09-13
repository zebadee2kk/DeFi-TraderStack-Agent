"""In-process paper fill simulation.

Paper soak runs were recording RiskEngine ``allow`` + ``paper_order`` intents
without ever moving cash, positions or NAV. Fills only landed when
``HummingbotExecutionReconciler`` saw venue trade rows, and paper connectors
typically never emit those. This module is the paper book of record:

* TRADING_MODE=paper only — live/shadow raise ``ExecutionSafetyError``;
* fill at the primary mid plus documented adverse slippage;
* charge ``PAPER_FEE_BPS`` as a modelled fee (same path as #66 / #88);
* ledger-backed: one decision produces at most one fill, including after restart.

It never talks to a venue and never relaxes risk, the kill switch, or a
meta-agent veto (those already null ``paper_order`` before this is called).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from traderstack.execution.hummingbot import ExecutionSafetyError
from traderstack.execution.ledger import (
    TERMINAL_ORDER_STATES,
    ExecutionFill,
    ExecutionLedger,
    ExecutionOrder,
    FeeSource,
    OrderLifecycleState,
)
from traderstack.execution.planner import (
    ExecutionPlan,
    ExecutionPlanner,
    ExecutionPlanRejected,
    ExitSizingRejected,
)
from traderstack.models import Side
from traderstack.pipeline import PaperOrderIntent
from traderstack.portfolio import InMemoryPortfolioBook

# Deterministic fill id so a restart re-applies the same key and ``record_fill``
# is a no-op. Distinct from any venue trade id.
_PAPER_FILL_ID_PREFIX = "paper-fill:"


class PaperFillStatus(StrEnum):
    """Outcome of one paper-fill attempt, stamped on ``RuntimeResult``."""

    FILLED = "paper_filled"
    DUPLICATE = "paper_fill_duplicate"
    PLAN_REJECTED = "plan_rejected"
    REJECTED = "paper_fill_rejected"
    WITHHELD = "paper_fill_withheld"
    # --- protective-exit sizing (#130) ---
    # A reducing-only exit that could not be sized at or below the held
    # quantity. Deliberately distinct from PLAN_REJECTED (venue/data
    # bounds: lot step, min notional, slippage) and REJECTED (book or
    # ledger state), so an operator can tell invalid exit sizing apart
    # from a venue/data rejection in traderstack_paper_fills_total.
    INVALID_EXIT_SIZE = "paper_fill_invalid_exit_size"


@dataclass(frozen=True)
class PaperFillOutcome:
    status: PaperFillStatus
    reason: str | None = None
    fill: ExecutionFill | None = None
    plan: ExecutionPlan | None = None
    fee_usd: float = 0.0

    @property
    def applied(self) -> bool:
        return self.status is PaperFillStatus.FILLED


def paper_fill_id(client_order_id: str) -> str:
    return f"{_PAPER_FILL_ID_PREFIX}{client_order_id}"


def is_paper_simulated_fill(fill_id: str) -> bool:
    return fill_id.startswith(_PAPER_FILL_ID_PREFIX)


def is_local_paper_fill(order: ExecutionOrder) -> bool:
    """True when this ledger order was filled by the in-process paper simulator.

    Venue reconciliation must not treat that FILLED state as a conflict with an
    still-open Hummingbot row, and must not apply a second venue trade.
    """

    return order.state is OrderLifecycleState.FILLED and order.fee_source is FeeSource.MODELLED


def adverse_fill_price_usd(side: Side, mid_usd: float, slippage_bps: float) -> float:
    """Mid plus documented adverse slippage: buys pay up, sells receive down."""

    if mid_usd <= 0:
        raise ValueError("mid price must be positive")
    if slippage_bps < 0:
        raise ValueError("slippage_bps must not be negative")
    adjustment = slippage_bps / 10_000.0
    if side is Side.BUY:
        return mid_usd * (1.0 + adjustment)
    return mid_usd * (1.0 - adjustment)


@dataclass
class PaperFillSimulator:
    """Books a single paper fill for an already-approved ``PaperOrderIntent``."""

    planner: ExecutionPlanner = field(default_factory=ExecutionPlanner)
    paper_fee_bps: float = 10.0
    paper_slippage_bps: float = 5.0
    trading_mode: str = "paper"

    def __post_init__(self) -> None:
        if self.paper_fee_bps < 0:
            raise ValueError("paper_fee_bps must not be negative")
        if self.paper_slippage_bps < 0:
            raise ValueError("paper_slippage_bps must not be negative")

    def apply(
        self,
        intent: PaperOrderIntent,
        *,
        mid_usd: float,
        ledger: ExecutionLedger,
        portfolio: InMemoryPortfolioBook,
    ) -> PaperFillOutcome:
        if self.trading_mode != "paper":
            raise ExecutionSafetyError("paper fill simulator cannot operate outside paper mode")
        if mid_usd <= 0:
            return PaperFillOutcome(
                status=PaperFillStatus.REJECTED, reason="primary mid must be positive"
            )

        existing = self._existing_order(ledger, intent.decision_id)
        if existing is not None:
            duplicate = self._duplicate_if_already_filled(existing, ledger)
            if duplicate is not None:
                return duplicate
            if (
                existing.state in TERMINAL_ORDER_STATES
                and existing.state is not OrderLifecycleState.FILLED
            ):
                return PaperFillOutcome(
                    status=PaperFillStatus.REJECTED,
                    reason=f"decision {intent.decision_id} is already {existing.state}",
                )

        fill_price = adverse_fill_price_usd(intent.side, mid_usd, self.paper_slippage_bps)
        # --- protective-exit sizing (#130) ---
        reduce_only_cap = self._reduce_only_cap(portfolio, intent)
        try:
            plan = self.planner.plan(
                intent,
                execution_price_usd=fill_price,
                reference_price_usd=mid_usd,
                max_quantity=reduce_only_cap,
            )
        except ExitSizingRejected as exc:
            return PaperFillOutcome(status=PaperFillStatus.INVALID_EXIT_SIZE, reason=exc.reason)
        except ExecutionPlanRejected as exc:
            return PaperFillOutcome(status=PaperFillStatus.PLAN_REJECTED, reason=exc.reason)

        order = existing if existing is not None else self._register(ledger, plan)
        if existing is not None:
            # Honour the already-planned size (submitter may have planned at
            # ask/bid). Never increase quantity on a restart or re-plan.
            quantity = existing.requested_quantity
            client_order_id = existing.client_order_id or existing.order_id
            if reduce_only_cap is not None:
                # --- protective-exit sizing (#130) ---
                # Both candidates are already at or below the held quantity or
                # were planned earlier; taking the smaller keeps the reducing-
                # only invariant without ever increasing a replanned order.
                quantity = min(quantity, plan.quantity)
        else:
            quantity = plan.quantity
            client_order_id = plan.client_order_id

        fill_id = paper_fill_id(client_order_id)
        if fill_id in ledger.processed_fill_ids:
            return PaperFillOutcome(
                status=PaperFillStatus.DUPLICATE,
                reason=f"paper fill {fill_id} already booked",
                plan=plan,
            )

        short = self._short_sale_reason(portfolio, intent, quantity)
        if short is not None:
            return PaperFillOutcome(status=PaperFillStatus.REJECTED, reason=short, plan=plan)

        fee_usd = quantity * fill_price * self.paper_fee_bps / 10_000.0
        fill = ExecutionFill(
            fill_id=fill_id,
            order_id=order.order_id,
            asset=intent.asset.upper(),
            side=intent.side,
            quantity=quantity,
            price_usd=fill_price,
            fee_usd=fee_usd,
            fee_source=FeeSource.MODELLED,
        )
        if not ledger.record_fill(fill):
            return PaperFillOutcome(
                status=PaperFillStatus.DUPLICATE,
                reason=f"paper fill {fill_id} already booked",
                plan=plan,
            )
        portfolio.apply_fill(
            fill.asset, fill.side, fill.quantity, fill.price_usd, fee_usd=fill.fee_usd
        )
        return PaperFillOutcome(
            status=PaperFillStatus.FILLED,
            fill=fill,
            plan=plan,
            fee_usd=fee_usd,
        )

    @staticmethod
    def _existing_order(ledger: ExecutionLedger, decision_id: str) -> ExecutionOrder | None:
        orders = ledger.orders_for_decision(decision_id)
        return orders[0] if orders else None

    @staticmethod
    def _duplicate_if_already_filled(
        order: ExecutionOrder, ledger: ExecutionLedger
    ) -> PaperFillOutcome | None:
        client_order_id = order.client_order_id or order.order_id
        fill_id = paper_fill_id(client_order_id)
        if order.state is OrderLifecycleState.FILLED or fill_id in ledger.processed_fill_ids:
            return PaperFillOutcome(
                status=PaperFillStatus.DUPLICATE,
                reason=f"decision {order.decision_id} already has a paper fill",
            )
        return None

    def _register(self, ledger: ExecutionLedger, plan: ExecutionPlan) -> ExecutionOrder:
        order = ExecutionOrder(
            order_id=plan.client_order_id,
            decision_id=plan.decision_id,
            asset=plan.asset,
            side=plan.side,
            requested_quantity=plan.quantity,
            state=OrderLifecycleState.PLANNED,
            client_order_id=plan.client_order_id,
            correlation_id=plan.correlation_id,
        )
        ledger.register_order(order)
        return order

    # --- protective-exit sizing (#130) ---
    @staticmethod
    def _reduce_only_cap(
        portfolio: InMemoryPortfolioBook, intent: PaperOrderIntent
    ) -> float | None:
        """Held quantity a reducing-only SELL may not exceed, or ``None``.

        ``None`` for every order that is not a protective exit, so the clamp
        can never become a way to resize an entry: it exists only to hold a
        reducing order at or below the position it is closing.
        """

        if not intent.reduce_only or intent.side is not Side.SELL:
            return None
        held = portfolio.positions.get(intent.asset.upper())
        return held.quantity if held is not None else 0.0

    @staticmethod
    def _short_sale_reason(
        portfolio: InMemoryPortfolioBook, intent: PaperOrderIntent, quantity: float
    ) -> str | None:
        if intent.side is not Side.SELL:
            return None
        held = portfolio.positions.get(intent.asset.upper())
        available = held.quantity if held is not None else 0.0
        if quantity > available + 1e-12:
            return f"cannot sell {quantity} {intent.asset.upper()} with paper position {available}"
        return None
