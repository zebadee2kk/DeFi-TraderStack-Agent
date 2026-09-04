import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from traderstack.config import Settings
from traderstack.execution.ledger import ExecutionLedger, ExecutionOrder
from traderstack.health import RuntimeHealth

# --- risk plane (Epic 7) ---
from traderstack.killswitch import KillSwitch
from traderstack.portfolio import InMemoryPortfolioBook
from traderstack.risk_audit import JsonlRiskAuditTrail
from traderstack.runtime import PaperRuntime, RuntimeResult

ResultHandler = Callable[[RuntimeResult], Awaitable[None]]
PortfolioHandler = Callable[[InMemoryPortfolioBook], Awaitable[None]]


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
    _stop_event: asyncio.Event = field(default_factory=asyncio.Event, init=False)

    def stop(self) -> None:
        self._stop_event.set()

    async def run(self) -> None:
        if not self.symbols:
            raise ValueError("at least one symbol is required")
        while not self._stop_event.is_set():
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
        try:
            await self._refresh_kill_switch()  # --- risk plane (Epic 7) ---
            result = await self.runtime.run_once(
                symbol,
                self.portfolio.snapshot(),
                submit=self.submit,
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
                await self.on_result(result)
            if self.on_portfolio is not None:
                await self.on_portfolio(self.portfolio)
            self.health.record_success(symbol)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - service boundary records and backs off.
            self.health.record_error(symbol, exc)
            await self._sleep_or_stop(self.error_backoff_seconds)

    async def _sleep_or_stop(self, seconds: float) -> None:
        if seconds <= 0:
            await asyncio.sleep(0)
            return
        try:
            await asyncio.wait_for(self._stop_event.wait(), timeout=seconds)
        except TimeoutError:
            pass
