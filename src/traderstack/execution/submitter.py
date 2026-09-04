"""Idempotent, reconciliation-gated order submission.

Implements the two execution rules the architecture treats as non-negotiable:

* one decision produces at most one venue order, across restarts, because the
  deterministic client order id is written to a persistent ledger *before* the
  venue is called;
* an API timeout or 5xx never means "the order failed". The decision is parked
  in ``SUBMISSION_UNCERTAIN`` and no retry is permitted until a reconciliation
  pass has confirmed the venue does not know the client order id.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

import httpx

from traderstack.execution.hummingbot import (
    ExecutionSafetyError,
    HummingbotHttpError,
    HummingbotOrderReceipt,
    HummingbotPaperExecutor,
)
from traderstack.execution.ledger import (
    ExecutionLedger,
    ExecutionOrder,
    OrderLifecycleState,
)
from traderstack.execution.planner import ExecutionPlan, ExecutionPlanner, ExecutionPlanRejected
from traderstack.models import Side
from traderstack.pipeline import PaperOrderIntent


class UncertaintyResolver(Protocol):
    """Answers "does the venue know this client order id?" from venue state."""

    async def venue_knows_order(
        self,
        ledger: ExecutionLedger,
        *,
        client_order_id: str,
        trading_pair: str,
        trade_type: str,
        quantity: float,
    ) -> bool: ...


class LedgerPersistence(Protocol):
    async def save(self, ledger: ExecutionLedger) -> None: ...


class SubmissionStatus(StrEnum):
    SUBMITTED = "submitted"
    #: The decision already has a ledger order; nothing was sent.
    DUPLICATE = "duplicate"
    #: An uncertain submission turned out to exist at the venue after all.
    ADOPTED = "adopted"
    #: The planner refused the order (lot/notional/slippage).
    PLAN_REJECTED = "plan_rejected"
    #: Permanent failure; the order is terminal in the ledger.
    REJECTED = "rejected"
    #: Venue truth unknown. No retry until reconciliation resolves it.
    UNCERTAIN = "uncertain"


@dataclass(frozen=True)
class SubmissionOutcome:
    status: SubmissionStatus
    reason: str | None = None
    receipt: HummingbotOrderReceipt | None = None
    plan: ExecutionPlan | None = None

    @property
    def submitted(self) -> bool:
        return self.status is SubmissionStatus.SUBMITTED


@dataclass
class IdempotentSubmitter:
    executor: HummingbotPaperExecutor
    ledger: ExecutionLedger
    planner: ExecutionPlanner = field(default_factory=ExecutionPlanner)
    resolver: UncertaintyResolver | None = None
    ledger_store: LedgerPersistence | None = None
    timeout_seconds: float = 10.0
    max_retries: int = 2
    backoff_seconds: float = 1.0
    backoff_multiplier: float = 2.0
    trading_mode: str = "paper"
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep

    async def submit(
        self,
        intent: PaperOrderIntent,
        *,
        execution_price_usd: float,
        reference_price_usd: float,
    ) -> SubmissionOutcome:
        resumed = self._resumable_order(intent.decision_id)
        if resumed is None and self.ledger.has_order_for_decision(intent.decision_id):
            return SubmissionOutcome(
                status=SubmissionStatus.DUPLICATE,
                reason=f"decision {intent.decision_id} already has a ledger order",
            )

        if resumed is not None:
            gate = await self._gate_retry(resumed)
            if gate is not None:
                return gate

        try:
            plan = self.planner.plan(
                intent,
                execution_price_usd=execution_price_usd,
                reference_price_usd=reference_price_usd,
            )
        except ExecutionPlanRejected as exc:
            if resumed is not None:
                self._transition(resumed, OrderLifecycleState.REJECTED, exc.reason)
                await self._persist()
            return SubmissionOutcome(status=SubmissionStatus.PLAN_REJECTED, reason=exc.reason)

        # Pre-flight the venue request before anything is written or sent, so a
        # paper-mode or connector violation can never create a ledger order.
        try:
            self.executor.build_request(
                intent,
                plan.execution_price_usd,
                self.trading_mode,
                quantity=plan.quantity,
                client_order_id=plan.client_order_id,
            )
        except ExecutionSafetyError as exc:
            reason = str(exc)
            if resumed is not None:
                self._transition(resumed, OrderLifecycleState.REJECTED, reason)
                await self._persist()
            return SubmissionOutcome(status=SubmissionStatus.REJECTED, reason=reason, plan=plan)

        order = resumed if resumed is not None else self._register(plan)
        if resumed is not None:
            # Re-planned at the current price after the venue disowned the order.
            order.requested_quantity = plan.quantity
        await self._persist()
        return await self._submit_with_retries(intent, plan, order)

    async def _submit_with_retries(
        self,
        intent: PaperOrderIntent,
        plan: ExecutionPlan,
        order: ExecutionOrder,
    ) -> SubmissionOutcome:
        delay = self.backoff_seconds
        while True:
            order.submission_attempts += 1
            await self._persist()
            try:
                receipt = await self._call(intent, plan)
            except HummingbotHttpError as exc:
                if not exc.uncertain:
                    self._transition(order, OrderLifecycleState.REJECTED, str(exc))
                    await self._persist()
                    return SubmissionOutcome(
                        status=SubmissionStatus.REJECTED, reason=str(exc), plan=plan
                    )
                reason = str(exc)
            except (TimeoutError, httpx.TimeoutException):
                reason = f"submission timed out after {self.timeout_seconds:g}s"
            except httpx.HTTPError as exc:
                reason = f"{type(exc).__name__}: {exc}"
            except ExecutionSafetyError as exc:
                # Raised after the venue already answered (e.g. malformed 201
                # body), so the order may well exist. Uncertain, not failed.
                reason = f"{type(exc).__name__}: {exc}"
            else:
                order.venue_order_id = receipt.order_id
                self._transition(order, OrderLifecycleState.SUBMITTED, None)
                await self._persist()
                return SubmissionOutcome(
                    status=SubmissionStatus.SUBMITTED,
                    receipt=receipt,
                    plan=plan,
                )

            self._transition(order, OrderLifecycleState.SUBMISSION_UNCERTAIN, reason)
            await self._persist()

            gate = await self._gate_retry(order, base_reason=reason)
            if gate is not None:
                return gate
            await self.sleep(delay)
            delay *= self.backoff_multiplier

    async def _gate_retry(
        self, order: ExecutionOrder, *, base_reason: str | None = None
    ) -> SubmissionOutcome | None:
        """Decide whether an uncertain order may be retried.

        Returns an outcome to hand back to the caller, or ``None`` when the
        venue has been positively confirmed not to know the order and a retry
        is therefore safe.
        """

        reason = base_reason or order.reason or "submission outcome unknown"
        if self.resolver is None:
            return SubmissionOutcome(
                status=SubmissionStatus.UNCERTAIN,
                reason=f"{reason}; no reconciler available to confirm venue state",
            )
        try:
            known = await self.resolver.venue_knows_order(
                self.ledger,
                client_order_id=order.client_order_id or order.order_id,
                trading_pair=f"{order.asset}-{self.planner.quote_currency}",
                trade_type="BUY" if order.side is Side.BUY else "SELL",
                quantity=order.requested_quantity,
            )
        except Exception as exc:  # noqa: BLE001 - unanswered means unknown means no retry.
            return SubmissionOutcome(
                status=SubmissionStatus.UNCERTAIN,
                reason=f"{reason}; reconciliation failed: {type(exc).__name__}: {exc}",
            )

        if known:
            self._transition(
                order,
                OrderLifecycleState.SUBMITTED,
                "venue confirmed the order during reconciliation",
            )
            await self._persist()
            return SubmissionOutcome(
                status=SubmissionStatus.ADOPTED,
                reason="venue already knows this client order id",
            )

        if order.submission_attempts > self.max_retries:
            exhausted = (
                f"{reason}; venue does not know client order id after "
                f"{order.submission_attempts} attempt(s)"
            )
            self._transition(order, OrderLifecycleState.REJECTED, exhausted)
            await self._persist()
            return SubmissionOutcome(status=SubmissionStatus.REJECTED, reason=exhausted)
        return None

    async def _call(self, intent: PaperOrderIntent, plan: ExecutionPlan) -> HummingbotOrderReceipt:
        async with asyncio.timeout(self.timeout_seconds):
            return await self.executor.submit(
                intent,
                plan.execution_price_usd,
                self.trading_mode,
                quantity=plan.quantity,
                client_order_id=plan.client_order_id,
            )

    def _resumable_order(self, decision_id: str) -> ExecutionOrder | None:
        for order in self.ledger.orders_for_decision(decision_id):
            if order.state is OrderLifecycleState.SUBMISSION_UNCERTAIN:
                return order
        return None

    def _register(self, plan: ExecutionPlan) -> ExecutionOrder:
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
        self.ledger.register_order(order)
        return order

    def _transition(
        self, order: ExecutionOrder, state: OrderLifecycleState, reason: str | None
    ) -> None:
        self.ledger.update_order_state(order.order_id, state)
        order.reason = reason

    async def _persist(self) -> None:
        if self.ledger_store is not None:
            await self.ledger_store.save(self.ledger)
