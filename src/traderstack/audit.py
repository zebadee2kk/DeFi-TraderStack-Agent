import asyncio
import json
from dataclasses import dataclass
from pathlib import Path

from traderstack._fs import append_jsonl
from traderstack.runtime import RuntimeResult


@dataclass(frozen=True)
class JsonlAuditSink:
    path: Path

    async def __call__(self, result: RuntimeResult) -> None:
        payload = result.model_dump(mode="json")
        line = json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n"
        await asyncio.to_thread(self._append, line)

    def _append(self, line: str) -> None:
        append_jsonl(self.path, line)
