"""altFINS technical-signals adapter (Epic 3).

altFINS' public REST API (verified against
https://altfins.com/crypto-market-and-analytical-data-api/documentation/api/public-api/
and the real request/response shapes in
https://github.com/altfins-com/altfins-api-examples on 2026-09-04) exposes,
among other endpoints:

- ``POST /api/v2/public/signals-feed/search-requests`` - a paginated feed of
  discrete BULLISH/BEARISH trading signals per symbol within a time window
  (``{symbols, signals, direction, fromDate, toDate}`` in; a page of
  ``{symbol, signalKey, signalName, direction, timestamp}`` rows out).
- Auth via the ``X-API-KEY`` request header.
- Base URL ``https://altfins.com``.

altFINS does not publish a single normalised "technical signal score" field —
that's this adapter's own, clearly-flagged design choice (see
``AltFinsSignalProvider.fetch``), not something confirmed in their docs.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from traderstack.intelligence import AltFinsSignalSnapshot

SIGNALS_FEED_PATH = "/api/v2/public/signals-feed/search-requests"


@dataclass
class AltFinsSignalProvider:
    api_key: str
    base_url: str = "https://altfins.com"
    # How far back to look for signals each fetch. altFINS' own signal
    # intervals go down to 15m; a day gives a reasonably stable score without
    # over-weighting a single stale signal.
    lookback: timedelta = timedelta(days=1)
    page_size: int = 100
    client: httpx.AsyncClient | None = None

    async def fetch(self, asset: str) -> AltFinsSignalSnapshot:
        symbol = asset.upper()
        now = datetime.now(UTC)
        payload: dict[str, Any] = {
            "symbols": [symbol],
            "signals": [],
            "fromDate": (now - self.lookback).isoformat(),
            "toDate": now.isoformat(),
        }
        headers = {"X-API-KEY": self.api_key, "Content-Type": "application/json"}
        params = {"page": 0, "size": self.page_size}
        if self.client is not None:
            response = await self.client.post(
                SIGNALS_FEED_PATH, headers=headers, json=payload, params=params
            )
        else:
            async with httpx.AsyncClient(base_url=self.base_url.rstrip("/"), timeout=20) as client:
                response = await client.post(
                    SIGNALS_FEED_PATH, headers=headers, json=payload, params=params
                )
        response.raise_for_status()
        body = response.json()
        score = _score_from_signals_feed(body)
        return AltFinsSignalSnapshot(
            asset=symbol,
            score=score,
            source_id="altfins:signals-feed",
        )


def _score_from_signals_feed(body: object) -> float | None:
    """Map a page of altFINS signal rows to a single [-1, 1] score.

    DESIGN ASSUMPTION (altFINS does not define this): net bullish/bearish
    share of signals fired in the lookback window, i.e.
    ``(bullish_count - bearish_count) / total_count``, clipped to [-1, 1].
    None when no signals fired (no evidence either way, not neutral).
    """
    rows = body.get("content") if isinstance(body, dict) else None
    if not isinstance(rows, list):
        raise TypeError("unexpected altFINS signals-feed response")
    bullish = 0
    bearish = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        direction = row.get("direction")
        if direction == "BULLISH":
            bullish += 1
        elif direction == "BEARISH":
            bearish += 1
    total = bullish + bearish
    if total == 0:
        return None
    return max(-1.0, min(1.0, (bullish - bearish) / total))
