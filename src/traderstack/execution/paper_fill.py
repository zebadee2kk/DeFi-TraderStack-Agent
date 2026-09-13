"""In-process paper fill simulation.

Paper soak runs were recording RiskEngine ``allow`` + ``paper_order`` intents
without ever moving cash, positions or NAV. Fills only landed when
``HummingbotExecutionReconciler`` saw venue trade rows, and paper connectors
typically never emit those. This module is the paper book of record:

* TRADING_MODE=paper only — live/shadow raise ``ExecutionSafetyError``;
* fill at the primary mid plus documented adverse slippage;
* charge ``PAPER_FEE_BPS`` as a modelled fee (same path as #66 / #88);
* ledger-backed: one decision produces at most one fill, including after restart;
* protective exits fill at most the held quantity (#130): an ``exit-*`` intent
  carries ``max_quantity`` and the planner caps to it, so adverse slippage
  cannot turn a full stop into a short-sale rejection.

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
from traderstack.execution.planner import ExecutionPlan, ExecutionPlanner, ExecutionPlanRejected
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


# --- protective exit sizing (#130) ---
class PaperFillRejectReason(StrEnum):
    """Bounded reason code for a rejected paper fill (metric label).

    Distinguishes invalid exit sizing from venue/data rejections without
    adding a ``PaperFillStatus`` value (the status strings are consumed by the
    opportunity funnel, the soak report and the RUNBOOK status table).
    """

    INVALID_MID = "invalid_mid"
    DECISION_TERMINAL = "decision_terminal"
    PLAN_REJECTED = "plan_rejected"
    SHORT_SALE = "short_sale"
    # An ``exit-*`` intent carrying ``max_quantity`` would still sell more than
    # the book holds. Unreachable after #130; its appearance is the alarm.
    EXIT_SIZING_INVALID = "exit_sizing_invalid"


@dataclass(frozen=True)
class PaperFillOutcome:
    status: PaperFillStatus
    reason: str | None = None
    fill: ExecutionFill | None = None
    plan: ExecutionPlan | None = None
    fee_usd: float = 0.0
    # --- protective exit sizing (#130) --- set on every REJECTED / PLAN_REJECTED.
    reason_code: PaperFillRejectReason | None = None

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
                status=PaperFillStatus.REJECTED,
                reason=f"{PaperFillRejectReason.INVALID_MID}: primary mid must be positive",
                reason_code=PaperFillRejectReason.INVALID_MID,
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
                    reason=(
                        f"{PaperFillRejectReason.DECISION_TERMINAL}: decision "
                        f"{intent.decision_id} is already {existing.state}"
                    ),
                    reason_code=PaperFillRejectReason.DECISION_TERMINAL,
                )

        fill_price = adverse_fill_price_usd(intent.side, mid_usd, self.paper_slippage_bps)
        try:
            plan = self.planner.plan(
                intent,
                execution_price_usd=fill_price,
                reference_price_usd=mid_usd,
            )
        except ExecutionPlanRejected as exc:
            return PaperFillOutcome(
                status=PaperFillStatus.PLAN_REJECTED,
                reason=f"{PaperFillRejectReason.PLAN_REJECTED}: {exc.reason}",
                reason_code=PaperFillRejectReason.PLAN_REJECTED,
            )

        order = existing if existing is not None else self._register(ledger, plan)
        if existing is not None:
            # Honour the already-planned size (submitter may have planned at
            # ask/bid). Never increase quantity on a restart or re-plan.
            quantity = existing.requested_quantity
            client_order_id = existing.client_order_id or existing.order_id
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
            reason, code = short
            return PaperFillOutcome(
                status=PaperFillStatus.REJECTED, reason=reason, plan=plan, reason_code=code
            )

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

    @staticmethod
    def _short_sale_reason(
        portfolio: InMemoryPortfolioBook, intent: PaperOrderIntent, quantity: float
    ) -> tuple[str, PaperFillRejectReason] | None:
        if intent.side is not Side.SELL:
            return None
        held = portfolio.positions.get(intent.asset.upper())
        available = held.quantity if held is not None else 0.0
        if quantity > available + 1e-12:
            # --- protective exit sizing (#130) ---
            # An intent that carried the held quantity and *still* exceeds the
            # book is an exit-sizing bug, not a venue/data rejection; a plain
            # discretionary SELL larger than the book is the pre-existing
            # short-sale guard.
            code = (
                PaperFillRejectReason.EXIT_SIZING_INVALID
                if intent.max_quantity is not None
                else PaperFillRejectReason.SHORT_SALE
            )
            reason = (
                f"{code}: cannot sell {quantity} {intent.asset.upper()} "
                f"with paper position {available}"
            )
            return reason, code
        return None
