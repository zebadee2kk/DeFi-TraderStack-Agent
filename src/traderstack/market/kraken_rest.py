"""Paper-only Kraken Spot REST ticker (`VENUE_FEED=kraken_rest`).

Public, unauthenticated fallback when Kraken WS v2 hangs or is unreachable
from the operator's network. **Verified** against
https://docs.kraken.com/api/docs/rest-api/get-ticker-information:

- Endpoint: ``GET https://api.kraken.com/0/public/Ticker``
- Query: ``pair`` (comma-separated, e.g. ``BTCUSD`` / ``XBTUSD``)
- Each result row: ``a`` ask, ``b`` bid, ``c`` last-trade (first element is
  the price). ``error`` is a list; a non-empty list is a hard failure.

This feed is **paper-only**. ``require_paper_kraken_rest`` rejects shadow/live
so a REST poll can never become an execution-quality live source by accident.
It does not sign, submit, or talk to private Kraken endpoints.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx

from traderstack.market.kraken_candles import KRAKEN_REST_BASE_URL, kraken_pair
from traderstack.market.models import MarketSource, MarketTick

KRAKEN_TICKER_PATH = "/0/public/Ticker"

# Kraken's REST book still uses XBT for bitcoin on some pair keys.
_BASE_ALIASES: dict[str, tuple[str, ...]] = {
    "BTC": ("BTC", "XBT", "XXBT"),
    "XBT": ("BTC", "XBT", "XXBT"),
}

SleepFn = Callable[[float], Awaitable[None]]


def require_paper_kraken_rest(trading_mode: str, venue_feed: str) -> None:
    """Reject any non-paper mode for the REST ticker fallback."""
    if venue_feed == "kraken_rest" and trading_mode != "paper":
        raise RuntimeError(
            f"VENUE_FEED=kraken_rest is paper-only; refusing TRADING_MODE={trading_mode!r}"
        )


def _first_price(side: object) -> float | None:
    if isinstance(side, list | tuple) and side:
        side = side[0]
    if isinstance(side, (int, float)) and not isinstance(side, bool):
        return float(side)
    if isinstance(side, str):
        try:
            return float(side)
        except ValueError:
            return None
    return None


def _pair_candidates(symbol: str) -> set[str]:
    pair = kraken_pair(symbol)
    candidates = {pair, pair.upper()}
    base, _, quote = symbol.upper().partition("/")
    for alias in _BASE_ALIASES.get(base, (base,)):
        candidates.add(f"{alias}{quote}")
        candidates.add(f"X{alias}Z{quote}")
    return {item.upper() for item in candidates}


def parse_kraken_rest_ticker(
    payload: object,
    *,
    symbols: tuple[str, ...],
    observed_at: datetime | None = None,
) -> list[MarketTick]:
    """Reduce a Kraken Spot Ticker JSON body to typed ticks for ``symbols``."""
    if not isinstance(payload, dict):
        raise TypeError("unexpected Kraken ticker response")
    errors = payload.get("error") or []
    if errors:
        raise RuntimeError(f"Kraken ticker error: {errors}")
    result = payload.get("result")
    if not isinstance(result, dict) or not result:
        raise TypeError("unexpected Kraken ticker result shape")

    now = observed_at or datetime.now(UTC)
    ticks: list[MarketTick] = []
    unused: dict[str, Any] = dict(result)
    for symbol in symbols:
        row = _pop_ticker_row(unused, symbol)
        if row is None:
            continue
        bid = _first_price(row.get("b"))
        ask = _first_price(row.get("a"))
        last = _first_price(row.get("c"))
        if bid is None or ask is None or last is None:
            raise TypeError(f"Kraken ticker missing bid/ask/last for {symbol}")
        ticks.append(
            MarketTick(
                source=MarketSource.KRAKEN,
                symbol=symbol.upper(),
                observed_at=now,
                bid=bid,
                ask=ask,
                last=last,
            )
        )
    if not ticks:
        raise RuntimeError(f"Kraken ticker missing requested pairs: {symbols}")
    return ticks


def _pop_ticker_row(result: dict[str, Any], symbol: str) -> dict[str, Any] | None:
    wanted = _pair_candidates(symbol)
    for key in list(result):
        if str(key).upper() in wanted and isinstance(result[key], dict):
            row = result.pop(key)
            return row if isinstance(row, dict) else None
    # Single leftover pair after requesting one symbol: accept it (XXBTZUSD).
    if len(result) == 1:
        (row,) = result.values()
        result.clear()
        return row if isinstance(row, dict) else None
    return None


@dataclass
class KrakenRestTickerProvider:
    """Polls public Spot ``/0/public/Ticker`` and yields ``MarketTick``s.

    ``stream_ticks`` is a polling loop so ``PaperRuntime._next_tick`` (which
    takes the first tick then returns) gets a fresh REST quote each cycle.
    """

    base_url: str = KRAKEN_REST_BASE_URL
    poll_interval_seconds: float = 1.0
    client: httpx.AsyncClient | None = None
    sleep: SleepFn = field(default=asyncio.sleep)

    async def stream_ticks(self, symbols: tuple[str, ...]) -> AsyncIterator[MarketTick]:
        if not symbols:
            raise ValueError("symbols must not be empty")
        while True:
            ticks = await self.fetch_ticks(symbols)
            for tick in ticks:
                yield tick
            await self.sleep(self.poll_interval_seconds)

    async def fetch_ticks(self, symbols: tuple[str, ...]) -> list[MarketTick]:
        pairs = ",".join(kraken_pair(symbol) for symbol in symbols)
        if self.client is not None:
            response = await self.client.get(KRAKEN_TICKER_PATH, params={"pair": pairs})
        else:
            async with httpx.AsyncClient(
                base_url=self.base_url.rstrip("/"),
                timeout=15,
            ) as client:
                response = await client.get(KRAKEN_TICKER_PATH, params={"pair": pairs})
        response.raise_for_status()
        return parse_kraken_rest_ticker(response.json(), symbols=symbols)
