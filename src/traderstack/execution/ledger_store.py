"""Durable execution-ledger state, persisted alongside the portfolio checkpoint.

Same shape and atomic-write discipline as ``traderstack.checkpoint``. The ledger
is the idempotency record: without it a process restart could resubmit a
decision whose order is already live at the venue.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from traderstack.execution.ledger import ExecutionLedger, ExecutionLedgerState


@dataclass(frozen=True)
class JsonExecutionLedgerStore:
    path: Path

    async def save(self, ledger: ExecutionLedger) -> None:
        payload = ledger.state().model_dump_json(indent=2)
        await asyncio.to_thread(self._write_atomic, payload)

    async def load(self) -> ExecutionLedger | None:
        if not self.path.exists():
            return None
        payload = await asyncio.to_thread(self.path.read_text, encoding="utf-8")
        return ExecutionLedger.from_state(ExecutionLedgerState.model_validate_json(payload))

    def _write_atomic(self, payload: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(payload, encoding="utf-8")
        temporary.replace(self.path)
