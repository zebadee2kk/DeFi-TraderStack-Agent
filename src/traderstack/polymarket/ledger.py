"""Append-only paper/shadow ledger for Polymarket weather would-trade intents.

This is *not* an execution venue. Records are research artifacts: every row
has ``venue_submitted=false`` and ``execution=paper_intent_only``. Nothing
here is read by the crypto ``IdempotentSubmitter``.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path

from traderstack.polymarket.models import PaperIntent


@dataclass(frozen=True)
class PolymarketWeatherPaperLedger:
    path: Path

    async def append(self, intent: PaperIntent) -> None:
        if intent.venue_submitted:
            raise RuntimeError("paper weather ledger refuses venue_submitted=true")
        if intent.trading_mode != "paper":
            raise RuntimeError("paper weather ledger refuses non-paper trading_mode")
        payload = intent.model_dump(mode="json")
        payload["venue_submitted"] = False
        payload["execution"] = "paper_intent_only"
        line = json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n"
        await asyncio.to_thread(self._append, line)

    def _append(self, line: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()
