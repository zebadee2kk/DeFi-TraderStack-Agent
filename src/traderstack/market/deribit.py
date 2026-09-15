"""Read-only Deribit public option quotes (#142; the read-only slice of #76).

GET only, and only the two public non-matching-engine paths the crypto-threshold
wedge tape needs. There is intentionally no method that could place, amend or
cancel anything: any path that looks like a private, auth or trading endpoint is
refused before a request is built.

Untrusted JSON-RPC payloads are reduced to bounded, typed pydantic rows here, at
the adapter, before anything downstream sees them (CLAUDE.md rule 6). A row that
fails validation is dropped, never guessed; a non-list ``result`` raises.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field

from traderstack.market.registry import ProviderRegistry

DEFAULT_DERIBIT_BASE_URL = "https://www.deribit.com/api/v2"

_ALLOWED_PATHS = frozenset({"/public/get_instruments", "/public/get_book_summary_by_currency"})
_FORBIDDEN_FRAGMENTS = (
    "private",
    "auth",
    "buy",
    "sell",
    "edit",
    "cancel",
    "withdraw",
    "subaccount",
)

# Plausible epoch-millisecond window (2000-01-01 .. 2100-01-01). Anything
# outside it is a malformed venue value, not a timestamp.
_MIN_EPOCH_MS = 946_684_800_000
_MAX_EPOCH_MS = 4_102_444_800_000


def assert_public_deribit_path(path: str) -> None:
    """Refuse anything that is not one of the two allowlisted public reads."""

    lowered = path.lower()
    for fragment in _FORBIDDEN_FRAGMENTS:
        if fragment in lowered:
            raise RuntimeError(
                f"Deribit path {path!r} looks like a private/trading endpoint; "
                "this client is read-only and never trades"
            )
    if path not in _ALLOWED_PATHS:
        raise RuntimeError(
            f"Deribit client refuses path {path!r}; only {sorted(_ALLOWED_PATHS)} are allowed"
        )


class OptionInstrument(BaseModel):
    """One listed option contract, reduced from ``public/get_instruments``."""

    instrument_name: str
    currency: str
    strike: float = Field(gt=0)
    option_type: Literal["call", "put"]
    expiry_at: datetime


class OptionQuote(BaseModel):
    """One option book summary row, reduced from the public summary endpoint."""

    instrument_name: str
    mark_iv: float = Field(ge=0)
    mark_price: float = Field(ge=0)
    best_bid: float | None = None
    best_ask: float | None = None
    underlying_price: float = Field(gt=0)
    underlying_index: str | None = None
    observed_at: datetime


def _epoch_ms(raw: object) -> datetime | None:
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
    if not _MIN_EPOCH_MS <= value <= _MAX_EPOCH_MS:
        return None
    return datetime.fromtimestamp(value / 1000.0, tz=UTC)


def _number(raw: object) -> float | None:
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int | float):
        return float(raw)
    if isinstance(raw, str) and raw.strip():
        try:
            return float(raw.strip())
        except ValueError:
            return None
    return None


def _rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        result = payload.get("result")
    else:
        result = payload
    if not isinstance(result, list):
        raise TypeError("unexpected Deribit payload: result is not a list")
    return [row for row in result if isinstance(row, dict)]


def reduce_instruments(payload: Any, *, currency: str) -> tuple[OptionInstrument, ...]:
    reduced: list[OptionInstrument] = []
    for row in _rows(payload):
        name = row.get("instrument_name")
        option_type = row.get("option_type")
        strike = _number(row.get("strike"))
        expiry = _epoch_ms(row.get("expiration_timestamp"))
        if not isinstance(name, str) or not name.strip():
            continue
        if option_type not in {"call", "put"}:
            continue
        if strike is None or strike <= 0 or expiry is None:
            continue
        reduced.append(
            OptionInstrument(
                instrument_name=name.strip(),
                currency=currency.upper(),
                strike=strike,
                option_type=option_type,
                expiry_at=expiry,
            )
        )
    return tuple(reduced)


def reduce_book_summary(payload: Any) -> tuple[OptionQuote, ...]:
    reduced: list[OptionQuote] = []
    for row in _rows(payload):
        name = row.get("instrument_name")
        mark_iv = _number(row.get("mark_iv"))
        mark_price = _number(row.get("mark_price"))
        underlying = _number(row.get("underlying_price"))
        observed_at = _epoch_ms(row.get("creation_timestamp"))
        if not isinstance(name, str) or not name.strip():
            continue
        if mark_iv is None or mark_iv < 0:
            continue
        if mark_price is None or mark_price < 0:
            continue
        if underlying is None or underlying <= 0 or observed_at is None:
            continue
        index = row.get("underlying_index")
        reduced.append(
            OptionQuote(
                instrument_name=name.strip(),
                mark_iv=mark_iv,
                mark_price=mark_price,
                best_bid=_number(row.get("bid_price")),
                best_ask=_number(row.get("ask_price")),
                underlying_price=underlying,
                underlying_index=index if isinstance(index, str) else None,
                observed_at=observed_at,
            )
        )
    return tuple(reduced)


@dataclass
class DeribitPublicClient:
    """Public option-chain reader. No auth, no trading surface, GET only."""

    base_url: str = DEFAULT_DERIBIT_BASE_URL
    client: httpx.AsyncClient | None = None
    registry: ProviderRegistry | None = None
    timeout_seconds: float = 10.0

    async def instruments(self, currency: str) -> tuple[OptionInstrument, ...]:
        symbol = currency.strip().upper()
        if not symbol:
            raise ValueError("currency is required")
        if self.registry is not None:
            return await self.registry.call(
                self._instruments,
                symbol,
                cache_key=("deribit", "instruments", symbol),
            )
        return await self._instruments(symbol)

    async def _instruments(self, currency: str) -> tuple[OptionInstrument, ...]:
        payload = await self._get(
            "/public/get_instruments",
            {"currency": currency, "kind": "option", "expired": "false"},
        )
        return reduce_instruments(payload, currency=currency)

    async def book_summary(self, currency: str) -> tuple[OptionQuote, ...]:
        symbol = currency.strip().upper()
        if not symbol:
            raise ValueError("currency is required")
        if self.registry is not None:
            return await self.registry.call(
                self._book_summary,
                symbol,
                cache_key=("deribit", "book_summary", symbol),
            )
        return await self._book_summary(symbol)

    async def _book_summary(self, currency: str) -> tuple[OptionQuote, ...]:
        payload = await self._get(
            "/public/get_book_summary_by_currency",
            {"currency": currency, "kind": "option"},
        )
        return reduce_book_summary(payload)

    async def _get(self, path: str, params: Mapping[str, str]) -> Any:
        assert_public_deribit_path(path)
        if self.client is not None:
            response = await self.client.get(path, params=dict(params))
        else:
            async with httpx.AsyncClient(
                base_url=self.base_url, timeout=self.timeout_seconds
            ) as client:
                response = await client.get(path, params=dict(params))
        response.raise_for_status()
        return response.json()
