"""Read-only Polymarket Gamma market discovery. GET only; no credentials."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import httpx

from traderstack.market.registry import ProviderRegistry

# ``/events/keyset`` added for #141: Gamma answers ``/events`` with
# ``deprecation: true``, a ``sunset`` date and ``warning: 299 - "use
# /events/keyset"`` (observed 2026-09-15) while still returning 200.
_ALLOWED_PATHS = frozenset({"/events", "/markets", "/events/keyset"})


def _require_get_path(path: str) -> None:
    if path not in _ALLOWED_PATHS:
        raise RuntimeError(f"Gamma client refuses path {path!r}; only {_ALLOWED_PATHS} are allowed")


def _events_from_payload(payload: Any) -> tuple[dict[str, Any], ...]:
    if isinstance(payload, list):
        return tuple(row for row in payload if isinstance(row, dict))
    if isinstance(payload, dict):
        # Key presence, not truthiness: an empty keyset page is a legitimate
        # "no more events" answer, not an unexpected payload (#141).
        for key in ("events", "data", "results"):
            if key in payload and isinstance(payload[key], list):
                return tuple(row for row in payload[key] if isinstance(row, dict))
    raise TypeError("unexpected Gamma events payload")


@dataclass
class GammaClient:
    base_url: str = "https://gamma-api.polymarket.com"
    client: httpx.AsyncClient | None = None
    registry: ProviderRegistry | None = None
    timeout_seconds: float = 10.0

    async def list_weather_events(self, *, tag_slug: str, limit: int) -> tuple[dict[str, Any], ...]:
        if self.registry is not None:
            return await self.registry.call(
                self._list_weather_events,
                tag_slug=tag_slug,
                limit=limit,
                cache_key=("gamma", "events", tag_slug, limit),
            )
        return await self._list_weather_events(tag_slug=tag_slug, limit=limit)

    async def _list_weather_events(
        self, *, tag_slug: str, limit: int
    ) -> tuple[dict[str, Any], ...]:
        payload = await self._get(
            "/events",
            params={
                "tag_slug": tag_slug,
                "closed": "false",
                "limit": str(max(1, min(limit, 100))),
            },
        )
        return _events_from_payload(payload)

    # --- polymarket weather PIT tape (#141) ---
    async def list_weather_events_page(
        self,
        *,
        tag_slug: str,
        limit: int,
        offset: int,
        order: str = "id",
        ascending: bool = False,
    ) -> tuple[dict[str, Any], ...]:
        """One offset page of open weather events, newest first."""

        payload = await self._get(
            "/events",
            params={
                "tag_slug": tag_slug,
                "closed": "false",
                "limit": str(max(1, min(limit, 100))),
                "offset": str(max(0, offset)),
                "order": order,
                "ascending": "true" if ascending else "false",
            },
        )
        return _events_from_payload(payload)

    async def list_weather_events_keyset(
        self, *, tag_slug: str, limit: int, cursor: str | None = None
    ) -> tuple[tuple[dict[str, Any], ...], str | None]:
        """One keyset page plus the next cursor (None when exhausted)."""

        params = {
            "tag_slug": tag_slug,
            "closed": "false",
            "limit": str(max(1, min(limit, 100))),
        }
        if cursor:
            params["cursor"] = cursor
        payload = await self._get("/events/keyset", params=params)
        events = _events_from_payload(payload)
        next_cursor: str | None = None
        if isinstance(payload, dict):
            raw = payload.get("next_cursor")
            if isinstance(raw, str) and raw.strip():
                next_cursor = raw
        return events, next_cursor

    async def _get(self, path: str, params: Mapping[str, str]) -> Any:
        _require_get_path(path)
        if self.client is not None:
            response = await self.client.get(path, params=dict(params))
        else:
            async with httpx.AsyncClient(
                base_url=self.base_url, timeout=self.timeout_seconds
            ) as client:
                response = await client.get(path, params=dict(params))
        response.raise_for_status()
        return response.json()
