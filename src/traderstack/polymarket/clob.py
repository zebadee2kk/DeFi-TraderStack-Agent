"""Read-only Polymarket CLOB public mids. GET only; never signs or posts orders."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
from pydantic import BaseModel, Field

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


# --- crypto-threshold wedge tape (#142) ---
class ClobBook(BaseModel):
    """Top of book reduced from an untrusted ``/book`` payload."""

    best_bid: float | None = Field(default=None, ge=0, le=1)
    best_ask: float | None = Field(default=None, ge=0, le=1)
    venue_timestamp: datetime | None = None
    tick_size: float | None = Field(default=None, gt=0)

    @property
    def mid(self) -> float | None:
        """Mid only when both sides exist; a one-sided book has no mid."""

        if self.best_bid is None or self.best_ask is None:
            return None
        return 0.5 * (self.best_bid + self.best_ask)


def _levels(raw: Any) -> list[float]:
    prices: list[float] = []
    if not isinstance(raw, list):
        return prices
    for level in raw:
        if not isinstance(level, dict):
            continue
        price = level.get("price")
        if isinstance(price, bool):
            continue
        if isinstance(price, int | float):
            value = float(price)
        elif isinstance(price, str) and price.strip():
            try:
                value = float(price.strip())
            except ValueError:
                continue
        else:
            continue
        if 0.0 <= value <= 1.0:
            prices.append(value)
    return prices


def _book_timestamp(raw: Any) -> datetime | None:
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int | float):
        value = float(raw)
    elif isinstance(raw, str) and raw.strip():
        try:
            value = float(raw.strip())
        except ValueError:
            return None
    else:
        return None
    # Milliseconds since epoch, bounded to a plausible 2000..2100 window.
    if not 946_684_800_000 <= value <= 4_102_444_800_000:
        return None
    return datetime.fromtimestamp(value / 1000.0, tz=UTC)


def reduce_book(payload: Any) -> ClobBook:
    """Reduce an untrusted ``/book`` payload to bounded typed values."""

    if not isinstance(payload, dict):
        raise TypeError("unexpected CLOB book payload")
    bids = _levels(payload.get("bids"))
    asks = _levels(payload.get("asks"))
    tick = payload.get("tick_size")
    tick_size: float | None = None
    if isinstance(tick, int | float) and not isinstance(tick, bool) and tick > 0:
        tick_size = float(tick)
    elif isinstance(tick, str) and tick.strip():
        try:
            parsed = float(tick.strip())
        except ValueError:
            parsed = 0.0
        tick_size = parsed if parsed > 0 else None
    return ClobBook(
        best_bid=max(bids) if bids else None,
        best_ask=min(asks) if asks else None,
        venue_timestamp=_book_timestamp(payload.get("timestamp")),
        tick_size=tick_size,
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

    # --- crypto-threshold wedge tape (#142) ---
    async def book(self, token_id: str) -> ClobBook:
        """Best bid/ask and the venue timestamp for one token. GET only.

        A one-sided or unparseable book yields ``mid=None`` (and the caller
        records a non-ok row); it never becomes a zero or a guessed mid.
        """

        if not token_id or not token_id.strip():
            raise ValueError("token_id is required")
        if self.registry is not None:
            return await self.registry.call(
                self._book, token_id, cache_key=("clob", "book", token_id)
            )
        return await self._book(token_id)

    async def _book(self, token_id: str) -> ClobBook:
        return reduce_book(await self._get("/book", {"token_id": token_id}))
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
