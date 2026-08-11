import asyncio
from dataclasses import dataclass
from pathlib import Path

from traderstack.portfolio import InMemoryPortfolioBook, PortfolioState


@dataclass(frozen=True)
class JsonPortfolioCheckpointStore:
    path: Path

    async def save(self, portfolio: InMemoryPortfolioBook) -> None:
        payload = portfolio.state().model_dump_json(indent=2)
        await asyncio.to_thread(self._write_atomic, payload)

    async def load(self) -> InMemoryPortfolioBook | None:
        if not self.path.exists():
            return None
        payload = await asyncio.to_thread(self.path.read_text, encoding="utf-8")
        return InMemoryPortfolioBook.from_state(PortfolioState.model_validate_json(payload))

    def _write_atomic(self, payload: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(payload, encoding="utf-8")
        temporary.replace(self.path)
