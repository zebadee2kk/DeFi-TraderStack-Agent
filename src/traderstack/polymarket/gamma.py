"""Read-only Polymarket Gamma market discovery. GET only; no credentials."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import httpx

from traderstack.market.registry import ProviderRegistry

_ALLOWED_PATHS = frozenset({"/events", "/markets"})


def _require_get_path(path: str) -> None:
    if path not in _ALLOWED_PATHS:
        raise RuntimeError(f"Gamma client refuses path {path!r}; only {_ALLOWED_PATHS} are allowed")


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
        if isinstance(payload, list):
            return tuple(row for row in payload if isinstance(row, dict))
        if isinstance(payload, dict):
            rows = payload.get("events") or payload.get("data") or payload.get("results")
            if isinstance(rows, list):
                return tuple(row for row in rows if isinstance(row, dict))
        raise TypeError("unexpected Gamma events payload")

    # --- crypto-threshold wedge tape (#142) ---
    async def list_events_by_slug(self, *, slug: str) -> tuple[dict[str, Any], ...]:
        """Fetch one event by its deterministic slug. GET only.

        An empty list is a normal result (the daily event does not exist yet),
        not an error: a missing event is a skip, never a fabricated row.
        """

        if self.registry is not None:
            return await self.registry.call(
                self._list_events_by_slug,
                slug=slug,
                cache_key=("gamma", "events_slug", slug),
            )
        return await self._list_events_by_slug(slug=slug)

    async def _list_events_by_slug(self, *, slug: str) -> tuple[dict[str, Any], ...]:
        payload = await self._get("/events", params={"slug": slug})
        if isinstance(payload, list):
            return tuple(row for row in payload if isinstance(row, dict))
        if isinstance(payload, dict):
            rows = payload.get("events") or payload.get("data") or payload.get("results")
            if isinstance(rows, list):
                return tuple(row for row in rows if isinstance(row, dict))
        raise TypeError("unexpected Gamma events payload")

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
