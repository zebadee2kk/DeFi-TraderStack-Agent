import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

import structlog

from traderstack.execution.ledger import ExecutionLedger, ExecutionOrder
from traderstack.health import RuntimeHealth
from traderstack.metrics import (  # --- observability (Epic 9) ---
    record_event_sink_failure,
    record_portfolio_snapshot,
)
from traderstack.portfolio import InMemoryPortfolioBook
from traderstack.runtime import PaperRuntime, RuntimeResult

_log = structlog.get_logger("traderstack.service")  # observability (Epic 9)

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
    _stop_event: asyncio.Event = field(default_factory=asyncio.Event, init=False)
    _cycle: int = field(default=0, init=False)  # observability (Epic 9): monotonic cycle counter

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

    async def _run_symbol_safely(self, symbol: str) -> None:
        self._cycle += 1  # observability (Epic 9)
        decision_id = None  # observability (Epic 9)
        log = _log.bind(symbol=symbol, cycle=self._cycle)  # observability (Epic 9)
        try:
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

    async def _sleep_or_stop(self, seconds: float) -> None:
        if seconds <= 0:
            await asyncio.sleep(0)
            return
        try:
            await asyncio.wait_for(self._stop_event.wait(), timeout=seconds)
        except TimeoutError:
            pass
