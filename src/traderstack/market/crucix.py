"""Crucix local-intel scaffold.

Crucix is an operator-hosted alert service (typically reached from Docker via
``host.docker.internal``). This adapter is a **read-only** news/narrative
source: high-tier alerts become ``NewsSnapshot.adverse_event`` / event and
narrative scores. It cannot authorise risk.

The HTTP contract is this adapter's own documented assumption (Crucix does
not publish a stable public schema here). Expected shape, any of:

- ``{"alerts": [ ... ]}`` / ``{"data": [ ... ]}`` / a bare list
- each item: ``tier``/``severity``/``level`` (string or number), optional
  ``score``/``narrative``/``sentiment``, optional ``adverse`` bool

High-tier strings: ``high``, ``critical``, ``severe``, ``p0``, ``p1``.
Numeric tier >= ``high_tier_min`` (default 4 on a 1–5 scale) also counts.

Register only when ``CRUCIX_ENABLED=true`` or a URL / API key is set — a
copied ``.env.example`` with blanks must not open a connection every cycle.

When registered, a provider timeout / HTTP error / unexpected payload is
fail-closed: the orchestrator marks ``provider_unavailable`` and the
pipeline rejects new risk with ``intelligence_provider_unavailable``.
High-tier alerts still map to ``adverse_event``. Opting in does not
enable Crucix by default.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from traderstack.intelligence import NewsSnapshot

DEFAULT_CRUCIX_BASE_URL = "http://host.docker.internal:8787"
CRUCIX_ALERTS_PATH = "/alerts"

_HIGH_TIER_LABELS = frozenset({"high", "critical", "severe", "p0", "p1", "urgent"})


def crucix_should_register(
    *,
    enabled: bool,
    base_url: str,
    api_key: str | None,
) -> bool:
    """Opt-in: flag, a non-blank URL, or a usable key."""
    if enabled:
        return True
    if api_key and api_key.strip():
        return True
    return bool(base_url.strip())


def crucix_effective_base_url(base_url: str) -> str:
    return base_url.strip() or DEFAULT_CRUCIX_BASE_URL


def _clip_unit(value: float) -> float:
    return max(0.0, min(1.0, value))


def _clip_signed(value: float) -> float:
    return max(-1.0, min(1.0, value))


def _as_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _tier_label(alert: dict[str, Any]) -> str:
    for key in ("tier", "severity", "level", "priority"):
        raw = alert.get(key)
        if isinstance(raw, str) and raw.strip():
            return raw.strip().lower()
    return ""


def _tier_number(alert: dict[str, Any]) -> float | None:
    for key in ("tier", "severity", "level", "priority"):
        number = _as_float(alert.get(key))
        if number is not None:
            return number
    return None


def is_high_tier(alert: dict[str, Any], *, high_tier_min: float = 4.0) -> bool:
    if alert.get("adverse") is True or alert.get("adverse_event") is True:
        return True
    label = _tier_label(alert)
    if label in _HIGH_TIER_LABELS:
        return True
    number = _tier_number(alert)
    return number is not None and number >= high_tier_min


def _alert_score(alert: dict[str, Any]) -> float | None:
    for key in ("score", "event_score", "narrative", "narrative_score", "confidence"):
        number = _as_float(alert.get(key))
        if number is not None:
            return _clip_unit(number if number <= 1.0 else number / 100.0)
    return None


def _alert_sentiment(alert: dict[str, Any]) -> float | None:
    for key in ("sentiment", "narrative_sentiment"):
        number = _as_float(alert.get(key))
        if number is not None:
            return _clip_signed(number if abs(number) <= 1.0 else number / 100.0)
    return None


def _alert_rows(payload: object) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        raise TypeError("unexpected Crucix response")
    for key in ("alerts", "data", "items", "results"):
        rows = payload.get(key)
        if isinstance(rows, list):
            return [item for item in rows if isinstance(item, dict)]
    if any(key in payload for key in ("tier", "severity", "level", "adverse")):
        return [payload]
    raise TypeError("unexpected Crucix alert payload")


def parse_crucix_alerts(
    payload: object,
    *,
    asset: str,
    high_tier_min: float = 4.0,
) -> NewsSnapshot:
    """Map Crucix alerts to a bounded ``NewsSnapshot``.

    High-tier / explicit-adverse items set ``adverse_event``. Scores only
    raise ``event_score`` (and never clear an adverse flag). Failures in the
    caller stay isolated — this function never relaxes risk policy.
    """
    rows = _alert_rows(payload)
    symbol = asset.upper()
    matched = [
        row
        for row in rows
        if str(row.get("asset") or row.get("symbol") or symbol).upper() == symbol
    ]
    if not matched:
        matched = rows

    adverse = any(is_high_tier(row, high_tier_min=high_tier_min) for row in matched)
    scores = [_alert_score(row) for row in matched]
    numeric_scores = [score for score in scores if score is not None]
    sentiments = [s for row in matched if (s := _alert_sentiment(row)) is not None]
    event_score = max(numeric_scores, default=0.0)
    if adverse:
        event_score = max(event_score, 0.8)
    elif sentiments:
        # Narrative intensity without a high-tier flag still informs event_score
        # but cannot set adverse_event by itself.
        event_score = max(event_score, max(abs(item) for item in sentiments))

    return NewsSnapshot(
        asset=symbol,
        event_score=_clip_unit(event_score),
        adverse_event=adverse,
        item_count=len(matched),
        source_id="crucix:alerts",
    )


@dataclass
class CrucixIntelProvider:
    base_url: str = DEFAULT_CRUCIX_BASE_URL
    api_key: str | None = None
    alerts_path: str = CRUCIX_ALERTS_PATH
    high_tier_min: float = 4.0
    client: httpx.AsyncClient | None = None

    async def fetch(self, asset: str) -> NewsSnapshot:
        symbol = asset.upper()
        headers: dict[str, str] = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        params = {"asset": symbol}
        if self.client is not None:
            response = await self.client.get(self.alerts_path, params=params, headers=headers)
        else:
            async with httpx.AsyncClient(
                base_url=self.base_url.rstrip("/"),
                timeout=20,
            ) as client:
                response = await client.get(self.alerts_path, params=params, headers=headers)
        response.raise_for_status()
        return parse_crucix_alerts(
            response.json(),
            asset=symbol,
            high_tier_min=self.high_tier_min,
        )
