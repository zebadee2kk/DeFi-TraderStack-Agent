"""Append-only JSONL tape of crypto-threshold wedge observations (#142).

Not an execution venue and not an intent ledger: every row is an observation
with ``venue_submitted=false`` and ``execution=paper_tape_only``. Nothing here
is read by the crypto paper loop or by ``IdempotentSubmitter``.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path

from traderstack.polymarket.crypto_models import CryptoWedgeRow


@dataclass(frozen=True)
class CryptoWedgeTape:
    path: Path

    async def append(self, row: CryptoWedgeRow) -> None:
        if row.venue_submitted:
            raise RuntimeError("crypto wedge tape refuses venue_submitted=true")
        if row.trading_mode != "paper":
            raise RuntimeError("crypto wedge tape refuses non-paper trading_mode")
        payload = row.model_dump(mode="json")
        payload["venue_submitted"] = False
        payload["execution"] = "paper_tape_only"
        line = json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n"
        await asyncio.to_thread(self._append, line)

    def _append(self, line: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()


@dataclass(frozen=True)
class TapeReadResult:
    rows: tuple[CryptoWedgeRow, ...]
    malformed_lines: int


def read_rows(path: Path) -> TapeReadResult:
    """Read a tape, counting (not raising on) malformed lines.

    A missing file is an empty, successful read: an empty tape is a result.
    """

    if not path.exists():
        return TapeReadResult(rows=(), malformed_lines=0)
    rows: list[CryptoWedgeRow] = []
    malformed = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            rows.append(CryptoWedgeRow.model_validate_json(text))
        except ValueError:
            malformed += 1
    return TapeReadResult(rows=tuple(rows), malformed_lines=malformed)
