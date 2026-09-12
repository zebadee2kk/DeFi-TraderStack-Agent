import asyncio
from dataclasses import dataclass
from pathlib import Path

from traderstack._fs import DurableStateError, read_text_strict, write_atomic

# --- risk plane (Epic 7) ---
from traderstack.circuit_breaker import StrategyCircuitBreaker
from traderstack.portfolio import InMemoryPortfolioBook, PortfolioState


@dataclass(frozen=True)
class JsonPortfolioCheckpointStore:
    path: Path
    # --- risk plane (Epic 7) ---
    # Optional: when supplied, per-strategy circuit-breaker state is persisted
    # in the same checkpoint document so a tripped strategy stays tripped
    # across a restart.
    circuit_breaker: StrategyCircuitBreaker | None = None

    async def save(self, portfolio: InMemoryPortfolioBook) -> None:
        state = portfolio.state()
        if self.circuit_breaker is not None:  # --- risk plane (Epic 7) ---
            state = state.model_copy(update={"strategy_breakers": self.circuit_breaker.export()})
        payload = state.model_dump_json(indent=2)
        await asyncio.to_thread(write_atomic, self.path, payload)

    async def load(self) -> InMemoryPortfolioBook | None:
        payload = await asyncio.to_thread(read_text_strict, self.path, what="portfolio checkpoint")
        if payload is None:
            return None
        try:
            state = PortfolioState.model_validate_json(payload)
        except Exception as exc:
            raise DurableStateError(
                f"portfolio checkpoint at {self.path} is unparsable: {exc}"
            ) from exc
        if self.circuit_breaker is not None:  # --- risk plane (Epic 7) ---
            self.circuit_breaker.load(state.strategy_breakers)
        return InMemoryPortfolioBook.from_state(state)
