import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Protocol

from traderstack.execution.ledger import ExecutionLedger, ExecutionOrder
from traderstack.execution.reconcile import ExecutionReconciliationResult
from traderstack.health import RuntimeHealth
from traderstack.portfolio import InMemoryPortfolioBook
from traderstack.reconciliation import ReconciliationResult
from traderstack.runtime import PaperRuntime, RuntimeResult

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
    # --- execution hardening (Epic 8) ---
    execution_reconciler: ExecutionReconcilerProtocol | None = None
    portfolio_reconciler: PortfolioReconcilerProtocol | None = None
    ledger_store: LedgerPersistence | None = None
    reconcile_interval_seconds: float = 60.0
    _stop_event: asyncio.Event = field(default_factory=asyncio.Event, init=False)
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

    async def _run_symbol_safely(self, symbol: str) -> None:
        try:
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

            if self.on_result is not None:
                await self.on_result(result)
            if self.on_portfolio is not None:
                await self.on_portfolio(self.portfolio)
            self.health.record_success(symbol)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - service boundary records and backs off.
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
