import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from traderstack.models import Side
from traderstack.portfolio import InMemoryPortfolioBook
from traderstack.runtime import PaperRuntime, RuntimeResult


ResultHandler = Callable[[RuntimeResult], Awaitable[None]]


@dataclass
class ContinuousPaperService:
    runtime: PaperRuntime
    portfolio: InMemoryPortfolioBook
    symbols: tuple[str, ...]
    submit: bool = False
    cycle_interval_seconds: float = 5.0
    error_backoff_seconds: float = 5.0
    on_result: ResultHandler | None = None
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
            if not self._stop_event.is_set():
                await self._sleep_or_stop(self.cycle_interval_seconds)

    async def _run_symbol_safely(self, symbol: str) -> None:
        try:
            result = await self.runtime.run_once(
                symbol,
                self.portfolio.snapshot(),
                submit=self.submit,
            )
            self.portfolio.mark(result.pipeline.feature_vector.asset, result.tick.last) if (
                result.pipeline.feature_vector is not None
            ) else self.portfolio.mark(symbol.split("/", 1)[0], result.tick.last)
            if result.execution_receipt is not None and result.pipeline.paper_order is not None:
                receipt = result.execution_receipt
                fill_price = receipt.price or result.tick.last
                self.portfolio.apply_fill(
                    result.pipeline.paper_order.asset,
                    result.pipeline.paper_order.side,
                    receipt.amount,
                    fill_price,
                )
            if self.on_result is not None:
                await self.on_result(result)
        except asyncio.CancelledError:
            raise
        except Exception:
            await self._sleep_or_stop(self.error_backoff_seconds)

    async def _sleep_or_stop(self, seconds: float) -> None:
        if seconds <= 0:
            await asyncio.sleep(0)
            return
        try:
            await asyncio.wait_for(self._stop_event.wait(), timeout=seconds)
        except TimeoutError:
            pass
