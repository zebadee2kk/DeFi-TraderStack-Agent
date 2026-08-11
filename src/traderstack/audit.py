import asyncio
import json
from dataclasses import dataclass
from pathlib import Path

from traderstack.runtime import RuntimeResult


@dataclass(frozen=True)
class JsonlAuditSink:
    path: Path

    async def __call__(self, result: RuntimeResult) -> None:
        payload = result.model_dump(mode="json")
        line = json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n"
        await asyncio.to_thread(self._append, line)

    def _append(self, line: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()
