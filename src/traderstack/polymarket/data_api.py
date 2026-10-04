"""Read-only Polymarket public Data API client for wallet research (#193).

The client intentionally exposes only GET routes needed for research. It has no
credential, signing, order, or POST capability. 429/503 responses honor
Retry-After with a bounded retry loop before surfacing the failure to the
ProviderRegistry circuit breaker.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import httpx

from traderstack.market.registry import ProviderRegistry

_ALLOWED_PATHS = frozenset(
    {
        "/v1/leaderboard",
        "/v2/positions",
        "/v2/user-pnl",
        "/v2/user-stats",
        "/v2/user-volume",
        "/v2/value",
        "/v2/trades",
        "/v2/activity",
        "/v2/status",
    }
)


def _require_path(path: str) -> None:
    if path not in _ALLOWED_PATHS:
        raise RuntimeError(f"Polymarket Data API client refuses path {path!r}")


def _rows(payload: Any) -> tuple[dict[str, Any], ...]:
    if isinstance(payload, list):
        return tuple(row for row in payload if isinstance(row, dict))
    if isinstance(payload, dict):
        for key in ("data", "leaderboard", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                return tuple(row for row in value if isinstance(row, dict))
    raise TypeError("unexpected Polymarket Data API list payload")


def _next_cursor(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    pagination = payload.get("pagination")
    if not isinstance(pagination, dict):
        return None
    value = pagination.get("next_cursor")
    return value if isinstance(value, str) and value.strip() else None


def wallet_from_leaderboard_row(row: dict[str, Any]) -> str | None:
    for key in ("proxy_wallet", "proxyWallet", "address"):
        value = row.get(key)
        if isinstance(value, str) and value.startswith("0x") and len(value) == 42:
            return value.lower()
    return None


@dataclass
class PolymarketDataClient:
    base_url: str = "https://data-api.polymarket.com"
    client: httpx.AsyncClient | None = None
    registry: ProviderRegistry | None = None
    timeout_seconds: float = 15.0
    max_retries: int = 2

    async def leaderboard(
        self,
        *,
        category: str = "OVERALL",
        time_period: str = "MONTH",
        order_by: str = "PNL",
        limit: int = 25,
    ) -> tuple[dict[str, Any], ...]:
        params = {
            "category": category.upper(),
            "timePeriod": time_period.upper(),
            "orderBy": order_by.upper(),
            "limit": str(max(1, min(limit, 50))),
            "offset": "0",
        }
        return _rows(await self._registered_get("/v1/leaderboard", params))

    async def user_stats(self, wallet: str) -> dict[str, Any] | None:
        payload = await self._registered_get("/v2/user-stats", {"user": wallet})
        if not isinstance(payload, dict):
            raise TypeError("unexpected user-stats payload")
        data = payload.get("data", payload)
        if data is None:
            return None
        if not isinstance(data, dict):
            raise TypeError("unexpected user-stats data")
        return data

    async def user_pnl(self, wallet: str) -> dict[str, Any]:
        payload = await self._registered_get(
            "/v2/user-pnl",
            {"user": wallet, "interval": "max", "fidelity": "1d"},
        )
        if not isinstance(payload, dict):
            raise TypeError("unexpected user-pnl payload")
        data = payload.get("data", payload)
        if not isinstance(data, dict):
            raise TypeError("unexpected user-pnl data")
        return data

    async def value(self, wallet: str) -> dict[str, Any]:
        payload = await self._registered_get("/v2/value", {"user": wallet})
        if not isinstance(payload, dict):
            raise TypeError("unexpected value payload")
        data = payload.get("data", payload)
        if not isinstance(data, dict):
            raise TypeError("unexpected value data")
        return data

    async def positions(
        self,
        wallet: str,
        *,
        status: str,
        max_pages: int = 3,
        page_size: int = 250,
    ) -> tuple[dict[str, Any], ...]:
        return await self._paged(
            "/v2/positions",
            {
                "user": wallet,
                "status": status.upper(),
                "sortBy": "TIMESTAMP",
                "sortDirection": "DESC",
                "limit": str(max(1, min(page_size, 1000))),
            },
            max_pages=max_pages,
            anchor={"user": wallet},
        )

    async def trades(
        self,
        wallet: str,
        *,
        max_pages: int = 3,
        page_size: int = 250,
    ) -> tuple[dict[str, Any], ...]:
        return await self._paged(
            "/v2/trades",
            {
                "user": wallet,
                "start": "1",
                "limit": str(max(1, min(page_size, 1000))),
            },
            max_pages=max_pages,
            anchor={"user": wallet},
        )

    async def _paged(
        self,
        path: str,
        params: dict[str, str],
        *,
        max_pages: int,
        anchor: dict[str, str],
    ) -> tuple[dict[str, Any], ...]:
        if max_pages <= 0:
            raise ValueError("max_pages must be positive")
        rows: list[dict[str, Any]] = []
        cursor: str | None = None
        for _ in range(max_pages):
            page_params = dict(params)
            if cursor is not None:
                page_params = dict(anchor)
                page_params["cursor"] = cursor
            payload = await self._registered_get(path, page_params)
            rows.extend(_rows(payload))
            cursor = _next_cursor(payload)
            if cursor is None:
                break
        return tuple(rows)

    async def _registered_get(self, path: str, params: dict[str, str]) -> Any:
        if self.registry is not None:
            return await self.registry.call(
                self._get,
                path,
                params,
                cache_key=("polymarket_data", path, tuple(sorted(params.items()))),
            )
        return await self._get(path, params)

    async def _get(self, path: str, params: dict[str, str]) -> Any:
        _require_path(path)
        for attempt in range(self.max_retries + 1):
            response = await self._request(path, params)
            if response.status_code not in {429, 503} or attempt >= self.max_retries:
                response.raise_for_status()
                return response.json()
            retry_after = response.headers.get("Retry-After", "1")
            try:
                delay = max(0.0, min(float(retry_after), 30.0))
            except ValueError:
                delay = 1.0
            await asyncio.sleep(delay)
        raise AssertionError("unreachable")

    async def _request(self, path: str, params: dict[str, str]) -> httpx.Response:
        if self.client is not None:
            return await self.client.get(path, params=params)
        async with httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout_seconds,
            follow_redirects=True,
        ) as client:
            return await client.get(path, params=params)
