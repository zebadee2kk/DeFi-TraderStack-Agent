import asyncio
from dataclasses import dataclass
from pathlib import Path

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
        await asyncio.to_thread(self._write_atomic, payload)

    async def load(self) -> InMemoryPortfolioBook | None:
        if not self.path.exists():
            return None
        payload = await asyncio.to_thread(self.path.read_text, encoding="utf-8")
        state = PortfolioState.model_validate_json(payload)
        if self.circuit_breaker is not None:  # --- risk plane (Epic 7) ---
            self.circuit_breaker.load(state.strategy_breakers)
        return InMemoryPortfolioBook.from_state(state)

    def _write_atomic(self, payload: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(payload, encoding="utf-8")
        temporary.replace(self.path)
