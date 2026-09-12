"""Durable execution-ledger state, persisted alongside the portfolio checkpoint.

Same shape and atomic-write discipline as ``traderstack.checkpoint``. The ledger
is the idempotency record: without it a process restart could resubmit a
decision whose order is already live at the venue.

Writes go through ``write_atomic`` (temp → fsync → replace → directory fsync)
so a host crash cannot leave a zero-length file that a restart would treat as
a fresh start. An existing-but-empty or unparsable file raises
``DurableStateError``; the caller must halt, never mint a new ledger.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from traderstack._fs import DurableStateError, read_text_strict, write_atomic
from traderstack.execution.ledger import ExecutionLedger, ExecutionLedgerState


@dataclass(frozen=True)
class JsonExecutionLedgerStore:
    path: Path

    async def save(self, ledger: ExecutionLedger) -> None:
        payload = ledger.state().model_dump_json(indent=2)
        await asyncio.to_thread(write_atomic, self.path, payload)

    async def load(self) -> ExecutionLedger | None:
        payload = await asyncio.to_thread(read_text_strict, self.path, what="execution ledger")
        if payload is None:
            return None
        try:
            return ExecutionLedger.from_state(ExecutionLedgerState.model_validate_json(payload))
        except DurableStateError:
            raise
        except Exception as exc:
            raise DurableStateError(
                f"execution ledger at {self.path} is unparsable: {exc}"
            ) from exc
