import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Protocol

import structlog

from traderstack.config import Settings
from traderstack.execution.ledger import ExecutionLedger, ExecutionOrder
from traderstack.execution.reconcile import ExecutionReconciliationResult
from traderstack.health import RuntimeHealth

# --- risk plane (Epic 7) ---
from traderstack.killswitch import KillSwitch
from traderstack.metrics import (  # --- observability (Epic 9) ---
    record_event_sink_failure,
    record_portfolio_snapshot,
)
from traderstack.portfolio import InMemoryPortfolioBook
from traderstack.reconciliation import ReconciliationResult
from traderstack.risk_audit import JsonlRiskAuditTrail
from traderstack.runtime import PaperRuntime, RuntimeResult

_log = structlog.get_logger("traderstack.service")  # observability (Epic 9)

ResultHandler = Callable[[RuntimeResult], Awaitable[None]]
PortfolioHandler = Callable[[InMemoryPortfolioBook], Awaitable[None]]


# --- execution hardening (Epic 8) ---
class ExecutionReconcilerProtocol(Protocol):
    async def reconcile_state(
        self, ledger: ExecutionLedger, portfolio: InMemoryPortfolioBook
    ) -> ExecutionReconciliationResult: ...


class PortfolioReconcilerProtocol(Protocol):
    async def reconcile(self, portfolio: InMemoryPortfolioBook) -> ReconciliationResult: ...


class LedgerPersistence(Protocol):
    async def save(self, ledger: ExecutionLedger) -> None: ...


@dataclass
class ContinuousPaperService:
    runtime: PaperRuntime
    portfolio: InMemoryPortfolioBook
    symbols: tuple[str, ...]
    submit: bool = False
    cycle_interval_seconds: float = 5.0
    error_backoff_seconds: float = 5.0
    on_result: ResultHandler | None = None
    on_portfolio: PortfolioHandler | None = None
    execution_ledger: ExecutionLedger | None = None
    health: RuntimeHealth = field(default_factory=RuntimeHealth)
    # --- risk plane (Epic 7) ---
    # Out-of-process operator halt, re-probed at the start of every cycle and
    # consulted live by the risk engine.
    kill_switch: KillSwitch | None = None
    # Append-only hash-chained record of every risk decision the cycle produced.
    risk_audit: JsonlRiskAuditTrail | None = None
    # The limits in force, stamped into each audit record.
    settings: Settings | None = None
    # --- execution hardening (Epic 8) ---
    execution_reconciler: ExecutionReconcilerProtocol | None = None
    portfolio_reconciler: PortfolioReconcilerProtocol | None = None
    ledger_store: LedgerPersistence | None = None
    reconcile_interval_seconds: float = 60.0
    _stop_event: asyncio.Event = field(default_factory=asyncio.Event, init=False)
    _cycle: int = field(default=0, init=False)  # observability (Epic 9): monotonic cycle counter
    _last_reconcile_at: float | None = field(default=None, init=False)

    def stop(self) -> None:
        self._stop_event.set()

    async def run(self) -> None:
        if not self.symbols:
            raise ValueError("at least one symbol is required")
        while not self._stop_event.is_set():
            # --- execution hardening (Epic 8) ---
            await self._maybe_reconcile()
            for symbol in self.symbols:
                if self._stop_event.is_set():
                    break
                await self._run_symbol_safely(symbol)
                if not self.health.healthy:
                    self.stop()
                    break
            if not self._stop_event.is_set():
                await self._sleep_or_stop(self.cycle_interval_seconds)

    # --- risk plane (Epic 7) ---
    async def _refresh_kill_switch(self) -> None:
        """Re-evaluate the operator halt at the start of every cycle."""

        if self.kill_switch is not None:
            await self.kill_switch.refresh()

    async def _record_risk_decision(self, result: RuntimeResult) -> None:
        """Append this cycle's risk decision to the immutable audit trail."""

        if self.risk_audit is None or self.settings is None:
            return
        proposal = result.pipeline.proposal
        risk_result = result.pipeline.risk_result
        if proposal is None or risk_result is None:
            return
        await self.risk_audit.arecord(proposal, risk_result, self.settings)

    async def _run_symbol_safely(self, symbol: str) -> None:
        self._cycle += 1  # observability (Epic 9)
        decision_id = None  # observability (Epic 9)
        log = _log.bind(symbol=symbol, cycle=self._cycle)  # observability (Epic 9)
        try:
            await self._refresh_kill_switch()  # --- risk plane (Epic 7) ---
            result = await self.runtime.run_once(
                symbol,
                self.portfolio.snapshot(),
                # --- execution hardening (Epic 8) ---
                submit=self.submission_enabled,
            )
            asset = (
                result.pipeline.feature_vector.asset
                if result.pipeline.feature_vector is not None
                else symbol.split("/", 1)[0].upper()
            )
            self.portfolio.mark(asset, result.tick.last)
            # --- observability (Epic 9): portfolio gauges + one structured log line/cycle ---
            snapshot = self.portfolio.snapshot()
            record_portfolio_snapshot(snapshot.nav_usd, snapshot.cash_usd, snapshot.peak_nav_usd)
            if result.pipeline.proposal is not None:
                decision_id = str(result.pipeline.proposal.decision_id)
            log = log.bind(decision_id=decision_id)
            log.info(
                "runtime_cycle_completed",
                outcome="accepted" if result.pipeline.accepted_market_data else "rejected",
                rejection_reasons=result.pipeline.rejection_reasons,
                risk_decision=(
                    result.pipeline.risk_result.decision.value
                    if result.pipeline.risk_result is not None
                    else None
                ),
            )
            # --- end observability (Epic 9) ---

            if (
                result.execution_receipt is not None
                and result.pipeline.paper_order is not None
                and self.execution_ledger is not None
                # --- execution hardening (Epic 8) ---
                # The submitter registers the order under its client order id
                # before the venue call; only the bare-executor path needs this.
                and not self.execution_ledger.has_order_for_decision(
                    result.pipeline.paper_order.decision_id
                )
            ):
                receipt = result.execution_receipt
                intent = result.pipeline.paper_order
                self.execution_ledger.register_order(
                    ExecutionOrder(
                        order_id=receipt.order_id,
                        decision_id=intent.decision_id,
                        asset=intent.asset,
                        side=intent.side,
                        requested_quantity=receipt.amount,
                    )
                )

            await self._record_risk_decision(result)  # --- risk plane (Epic 7) ---

            if self.on_result is not None:
                try:
                    await self.on_result(result)
                except Exception:  # observability (Epic 9): count sink failures, keep failing loudly
                    record_event_sink_failure("on_result")
                    raise
            if self.on_portfolio is not None:
                await self.on_portfolio(self.portfolio)
            self.health.record_success(symbol)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - service boundary records and backs off.
            log.warning("runtime_cycle_failed", error=f"{type(exc).__name__}: {exc}")  # observability (Epic 9)
            self.health.record_error(symbol, exc)
            await self._sleep_or_stop(self.error_backoff_seconds)

    # --- execution hardening (Epic 8) ---
    @property
    def submission_enabled(self) -> bool:
        """New risk is only allowed when venue state is known to be reconciled.

        A block stops *submission* only: market data, decisions and auditing all
        keep running, and existing positions are untouched.
        """

        return self.submit and not self.health.reconciliation_blocked

    async def _maybe_reconcile(self) -> None:
        if self.execution_reconciler is None and self.portfolio_reconciler is None:
            return
        now = time.monotonic()
        if (
            self._last_reconcile_at is not None
            and now - self._last_reconcile_at < self.reconcile_interval_seconds
        ):
            return
        self._last_reconcile_at = now
        await self.reconcile_now()

    async def reconcile_now(self) -> bool:
        """Run one reconciliation pass; returns True when state is clean.

        Any failure — transport error, order-state divergence or NAV drift past
        the configured threshold — blocks submission until a later pass is clean.
        """

        reasons: list[str] = []
        try:
            if self.execution_reconciler is not None and self.execution_ledger is not None:
                execution = await self.execution_reconciler.reconcile_state(
                    self.execution_ledger, self.portfolio
                )
                reasons.extend(execution.conflicts)
                if self.ledger_store is not None:
                    await self.ledger_store.save(self.execution_ledger)
                if execution.applied_fills and self.on_portfolio is not None:
                    await self.on_portfolio(self.portfolio)
            if self.portfolio_reconciler is not None:
                portfolio_state = await self.portfolio_reconciler.reconcile(self.portfolio)
                reasons.extend(portfolio_state.reasons)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - an unanswered venue is unreconciled state.
            self.health.record_reconciliation_failure(f"{type(exc).__name__}: {exc}")
            return False

        if reasons:
            self.health.record_reconciliation_failure("; ".join(reasons))
            return False
        self.health.record_reconciliation_success()
        return True

    async def _sleep_or_stop(self, seconds: float) -> None:
        if seconds <= 0:
            await asyncio.sleep(0)
            return
        try:
            await asyncio.wait_for(self._stop_event.wait(), timeout=seconds)
        except TimeoutError:
            pass
