import asyncio
from dataclasses import dataclass
from pathlib import Path

from traderstack.execution.ledger import ExecutionLedger, LedgerState
from traderstack.portfolio import InMemoryPortfolioBook, PortfolioState


def _write_atomic(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(payload, encoding="utf-8")
    temporary.replace(path)


@dataclass(frozen=True)
class JsonPortfolioCheckpointStore:
    path: Path

    async def save(self, portfolio: InMemoryPortfolioBook) -> None:
        payload = portfolio.state().model_dump_json(indent=2)
        await asyncio.to_thread(_write_atomic, self.path, payload)

    async def load(self) -> InMemoryPortfolioBook | None:
        if not self.path.exists():
            return None
        payload = await asyncio.to_thread(self.path.read_text, encoding="utf-8")
        return InMemoryPortfolioBook.from_state(PortfolioState.model_validate_json(payload))


@dataclass(frozen=True)
class JsonLedgerCheckpointStore:
    """Persists the execution ledger so restarts can reconcile prior fills."""

    path: Path

    async def save(self, ledger: ExecutionLedger) -> None:
        payload = ledger.state().model_dump_json(indent=2)
        await asyncio.to_thread(_write_atomic, self.path, payload)

    async def load(self) -> ExecutionLedger | None:
        if not self.path.exists():
            return None
        payload = await asyncio.to_thread(self.path.read_text, encoding="utf-8")
        return ExecutionLedger.from_state(LedgerState.model_validate_json(payload))
