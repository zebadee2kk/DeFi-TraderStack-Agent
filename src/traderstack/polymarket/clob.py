"""Read-only Polymarket CLOB public mids. GET only; never signs or posts orders."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from traderstack.market.registry import ProviderRegistry

# Public book/price reads. Anything that looks like an order or auth path is
# refused before a request is built — this client has no POST method.
_ALLOWED_PATHS = frozenset({"/midpoint", "/book", "/price"})
_FORBIDDEN_FRAGMENTS = ("order", "orders", "auth", "api-key", "private", "sign", "derive")


def assert_public_clob_path(path: str) -> None:
    lowered = path.lower()
    if any(fragment in lowered for fragment in _FORBIDDEN_FRAGMENTS):
        raise RuntimeError(
            f"CLOB path {path!r} looks like an order/auth endpoint; "
            "the paper weather module never signs or submits"
        )
    if path not in _ALLOWED_PATHS:
        raise RuntimeError(f"CLOB client refuses path {path!r}; only {_ALLOWED_PATHS} are allowed")


def _parse_mid(payload: Any) -> float:
    if isinstance(payload, dict):
        raw = payload.get("mid")
        if raw is None:
            raw = payload.get("price")
        if isinstance(raw, int | float):
            return float(raw)
        if isinstance(raw, str) and raw.strip():
            return float(raw)
    raise TypeError("unexpected CLOB midpoint payload")


@dataclass
class ClobPublicClient:
    """Public midpoint reader. There is intentionally no ``post`` / ``order``."""

    base_url: str = "https://clob.polymarket.com"
    client: httpx.AsyncClient | None = None
    registry: ProviderRegistry | None = None
    timeout_seconds: float = 10.0

    async def midpoint(self, token_id: str) -> float:
        if not token_id or not token_id.strip():
            raise ValueError("token_id is required")
        if self.registry is not None:
            return await self.registry.call(
                self._midpoint, token_id, cache_key=("clob", "midpoint", token_id)
            )
        return await self._midpoint(token_id)

    async def _midpoint(self, token_id: str) -> float:
        payload = await self._get("/midpoint", {"token_id": token_id})
        mid = _parse_mid(payload)
        if not 0.0 <= mid <= 1.0:
            raise ValueError(f"CLOB mid {mid} is not a probability-like price")
        return mid

    async def _get(self, path: str, params: dict[str, str]) -> Any:
        assert_public_clob_path(path)
        if self.client is not None:
            response = await self.client.get(path, params=params)
        else:
            async with httpx.AsyncClient(
                base_url=self.base_url, timeout=self.timeout_seconds
            ) as client:
                response = await client.get(path, params=params)
        response.raise_for_status()
        return response.json()
