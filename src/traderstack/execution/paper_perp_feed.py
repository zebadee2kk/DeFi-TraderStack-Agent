"""Current perp mid + recent funding for the paper hedge path.

Forward paper soaks only. Invariants:

* ``TRADING_MODE=paper`` — live/shadow raise ``ExecutionSafetyError``;
* mid is an explicit venue snapshot (Hyperliquid ``midPx`` or BitMEX
  ``midPrice``). The Kraken spot mid is never a substitute;
* ``markPx`` / ``markPrice`` / last-trade / funding premium are not mids
  and are not used as fallbacks;
* funding settlements come from the **same** venue as the mid;
* a missing or unparsable mid is a skip, not an invented number;
* snapshot mids are **not** a historical PIT mark−index or
  perp-mid−spot-mid series and must not be written into research
  scoring.

This feed exists so ``PAPER_PERP_HEDGE=true`` can exercise
``PaperPerpBook`` with real mid + funding inputs. It does not unlock
``can_promote`` while historical PIT basis is UNAVAILABLE.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal, Protocol

import httpx

from traderstack.execution.hummingbot import ExecutionSafetyError
from traderstack.research.edge_series import (
    BITMEX_BASE,
    HYPERLIQUID_BASE,
    bitmex_contract,
    bitmex_current_mid_usd,
    fetch_bitmex_funding,
    fetch_hyperliquid_funding,
    hyperliquid_coin,
    hyperliquid_current_mid_usd,
    hyperliquid_post_info,
)

PaperPerpVenueName = Literal["hyperliquid", "bitmex"]
PaperPerpVenuePreference = Literal["auto", "hyperliquid", "bitmex"]

_HL_MID_SOURCE = "hyperliquid:/info metaAndAssetCtxs midPx"
_BITMEX_MID_SOURCE = "bitmex:/api/v1/instrument midPrice"


@dataclass(frozen=True)
class PaperPerpQuote:
    venue: PaperPerpVenueName
    asset: str
    symbol: str
    mid_usd: float
    observed_at: datetime
    source: str


@dataclass(frozen=True)
class PaperPerpFundingTape:
    venue: PaperPerpVenueName
    asset: str
    settlements: tuple[tuple[datetime, float], ...]
    source: str


class PaperPerpFeed(Protocol):
    """Cycle-facing surface. Tests may supply a fake."""

    async def fetch_mid(self, symbol: str) -> PaperPerpQuote | None: ...

    async def fetch_funding_since(
        self,
        symbol: str,
        *,
        venue: PaperPerpVenueName,
        since: datetime,
    ) -> PaperPerpFundingTape: ...


def _asset_from_symbol(symbol: str) -> str:
    return symbol.split("/", 1)[0].upper()


def _venues_for(preference: PaperPerpVenuePreference) -> tuple[PaperPerpVenueName, ...]:
    if preference == "hyperliquid":
        return ("hyperliquid",)
    if preference == "bitmex":
        return ("bitmex",)
    return ("hyperliquid", "bitmex")


@dataclass
class PaperPerpVenueFeed:
    """Public REST snapshot mid + recent same-venue funding. Paper only."""

    trading_mode: str = "paper"
    venue_preference: PaperPerpVenuePreference = "auto"
    timeout_seconds: float = 10.0
    hyperliquid_client: httpx.AsyncClient | None = None
    bitmex_client: httpx.AsyncClient | None = None
    mid_cache_seconds: float = 15.0
    funding_lookback_hours: float = 48.0
    _mid_cache: dict[str, PaperPerpQuote] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.trading_mode != "paper":
            raise ExecutionSafetyError("paper perp feed cannot operate outside paper mode")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self.funding_lookback_hours <= 0:
            raise ValueError("funding_lookback_hours must be positive")

    async def fetch_mid(self, symbol: str) -> PaperPerpQuote | None:
        """Current perp mid. Skip (None) if every preferred venue fails."""

        if self.trading_mode != "paper":
            raise ExecutionSafetyError("paper perp feed cannot operate outside paper mode")
        cached = self._mid_cache.get(symbol.upper())
        if cached is not None:
            age = datetime.now(UTC) - cached.observed_at
            if age.total_seconds() <= self.mid_cache_seconds:
                return cached
        for venue in _venues_for(self.venue_preference):
            quote = await self._fetch_mid_venue(symbol, venue)
            if quote is not None:
                self._mid_cache[symbol.upper()] = quote
                return quote
        return None

    async def fetch_funding_since(
        self,
        symbol: str,
        *,
        venue: PaperPerpVenueName,
        since: datetime,
    ) -> PaperPerpFundingTape:
        """Public settlements from ``venue`` only. Empty tape if the pull fails."""

        if self.trading_mode != "paper":
            raise ExecutionSafetyError("paper perp feed cannot operate outside paper mode")
        asset = _asset_from_symbol(symbol)
        empty = PaperPerpFundingTape(venue=venue, asset=asset, settlements=(), source="")
        lookback_days = max(1, int(self.funding_lookback_hours / 24) + 1)
        try:
            if venue == "hyperliquid":
                client = self.hyperliquid_client
                if client is None:
                    async with httpx.AsyncClient(
                        base_url=HYPERLIQUID_BASE, timeout=max(self.timeout_seconds, 15.0)
                    ) as owned:
                        result = await fetch_hyperliquid_funding(
                            symbol,
                            client=owned,
                            lookback_days=lookback_days,
                            limit_pages=1,
                        )
                else:
                    result = await fetch_hyperliquid_funding(
                        symbol,
                        client=client,
                        lookback_days=lookback_days,
                        limit_pages=1,
                    )
                source = "hyperliquid:/info fundingHistory"
            else:
                client = self.bitmex_client
                if client is None:
                    async with httpx.AsyncClient(
                        base_url=BITMEX_BASE, timeout=max(self.timeout_seconds, 15.0)
                    ) as owned:
                        result = await fetch_bitmex_funding(
                            symbol,
                            client=owned,
                            lookback_days=lookback_days,
                            limit_pages=1,
                        )
                else:
                    result = await fetch_bitmex_funding(
                        symbol,
                        client=client,
                        lookback_days=lookback_days,
                        limit_pages=1,
                    )
                source = "bitmex:/api/v1/funding"
        except (httpx.HTTPError, TypeError, ValueError, KeyError):
            return empty
        if result.status != "ok":
            return PaperPerpFundingTape(
                venue=venue,
                asset=asset,
                settlements=(),
                source=result.source or source,
            )
        settlements = settlements_after(result.points, since=since)
        return PaperPerpFundingTape(
            venue=venue,
            asset=asset,
            settlements=settlements,
            source=result.source or source,
        )

    async def _fetch_mid_venue(
        self, symbol: str, venue: PaperPerpVenueName
    ) -> PaperPerpQuote | None:
        observed_at = datetime.now(UTC)
        asset = _asset_from_symbol(symbol)
        try:
            if venue == "hyperliquid":
                mid = await self._hyperliquid_mid(symbol)
                source = _HL_MID_SOURCE
            else:
                mid = await self._bitmex_mid(symbol)
                source = _BITMEX_MID_SOURCE
        except (httpx.HTTPError, TypeError, ValueError, KeyError):
            return None
        if mid is None or mid <= 0:
            return None
        return PaperPerpQuote(
            venue=venue,
            asset=asset,
            symbol=symbol.upper(),
            mid_usd=mid,
            observed_at=observed_at,
            source=source,
        )

    async def _hyperliquid_mid(self, symbol: str) -> float | None:
        coin = hyperliquid_coin(symbol)
        client = self.hyperliquid_client
        if client is None:
            async with httpx.AsyncClient(
                base_url=HYPERLIQUID_BASE, timeout=self.timeout_seconds
            ) as owned:
                response = await hyperliquid_post_info(owned, {"type": "metaAndAssetCtxs"})
                return hyperliquid_current_mid_usd(response.json(), coin)
        response = await hyperliquid_post_info(client, {"type": "metaAndAssetCtxs"})
        return hyperliquid_current_mid_usd(response.json(), coin)

    async def _bitmex_mid(self, symbol: str) -> float | None:
        contract = bitmex_contract(symbol)
        client = self.bitmex_client
        if client is None:
            async with httpx.AsyncClient(
                base_url=BITMEX_BASE, timeout=self.timeout_seconds
            ) as owned:
                response = await owned.get("/api/v1/instrument", params={"symbol": contract})
                response.raise_for_status()
                return bitmex_current_mid_usd(response.json())
        response = await client.get("/api/v1/instrument", params={"symbol": contract})
        response.raise_for_status()
        return bitmex_current_mid_usd(response.json())


def settlements_after(
    settlements: tuple[tuple[datetime, float], ...],
    *,
    since: datetime,
) -> tuple[tuple[datetime, float], ...]:
    """Keep prints strictly after ``since``. Does not invent a rate."""

    return tuple((ts, rate) for ts, rate in settlements if ts > since)
