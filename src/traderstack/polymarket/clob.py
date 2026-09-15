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


# --- polymarket weather PIT tape (#141) ---
@dataclass(frozen=True)
class BookTop:
    """Top of the public order book, reduced to bounded probabilities."""

    best_bid: float
    best_ask: float
    mid: float
    half_spread: float


def _book_side(payload: Any, key: str) -> list[float]:
    if not isinstance(payload, dict):
        raise TypeError("unexpected CLOB book payload")
    rows = payload.get(key)
    if not isinstance(rows, list):
        raise TypeError(f"CLOB book payload missing {key}")
    prices: list[float] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        raw = row.get("price")
        if isinstance(raw, int | float):
            prices.append(float(raw))
        elif isinstance(raw, str) and raw.strip():
            try:
                prices.append(float(raw))
            except ValueError:
                continue
    return prices


def book_top_from_payload(payload: Any) -> BookTop:
    """Reduce an untrusted ``/book`` payload to a typed top of book.

    The arrays are not sorted in a documented direction, so the best bid is
    the maximum bid and the best ask the minimum ask. A one-sided or
    crossed book raises: there is no decision-time mid to record, and a
    fabricated one would be the worst kind of research input.
    """

    bids = _book_side(payload, "bids")
    asks = _book_side(payload, "asks")
    if not bids or not asks:
        raise ValueError("CLOB book is one-sided; no mid to record")
    best_bid = max(bids)
    best_ask = min(asks)
    if not 0.0 <= best_bid <= 1.0 or not 0.0 <= best_ask <= 1.0:
        raise ValueError("CLOB book prices are not probability-like")
    if best_ask < best_bid:
        raise ValueError("CLOB book is crossed")
    return BookTop(
        best_bid=best_bid,
        best_ask=best_ask,
        mid=(best_bid + best_ask) / 2.0,
        half_spread=(best_ask - best_bid) / 2.0,
    )


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

    # --- polymarket weather PIT tape (#141) ---
    async def book_top(self, token_id: str) -> BookTop:
        """Best bid/ask/mid from the public ``/book`` GET. Never posts."""

        if not token_id or not token_id.strip():
            raise ValueError("token_id is required")
        # Only the HTTP read goes through the registry. A legitimately
        # one-sided book is not a provider failure: counting it as one would
        # trip the circuit breaker after three out-of-the-money buckets and
        # silently skip the rest of the cycle.
        if self.registry is not None:
            payload = await self.registry.call(
                self._book_payload, token_id, cache_key=("clob", "book", token_id)
            )
        else:
            payload = await self._book_payload(token_id)
        return book_top_from_payload(payload)

    async def _book_payload(self, token_id: str) -> Any:
        return await self._get("/book", {"token_id": token_id})

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
