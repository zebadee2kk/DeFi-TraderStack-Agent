"""Coinbase Exchange multi-year candles (#133; research-only).

**Verified 2026-09-13** (unauthenticated GET from the session environment):

* ``GET https://api.exchange.coinbase.com/products/{id}/candles`` with
  ``granularity``, ``start``, ``end`` (ISO8601). Rows are
  ``[time, low, high, open, close, volume]``, newest first, ``time`` in unix
  seconds. BTC-USD daily is available from 2015; ETH-USD hourly from 2020.
* Documented granularities: ``{60, 300, 900, 3600, 21600, 86400}``.
  ``4h`` is **not** offered (``granularity=14400`` → HTTP 400 "Unsupported
  granularity"); it is rejected here rather than derived from 1h. Binance
  Vision ships native 4h.
* Hard window edge: an inclusive ``start..start+300*g`` window returns 301
  rows, and ``start+301*g`` returns HTTP 400 "granularity too small for the
  requested time range. Count of aggregations requested exceeds 300". This
  pager therefore asks for exactly 300 bars per page
  (``end = start + 299*g``) and never sits on the edge.
* A window before the product listed returns ``[]`` with HTTP 200 — that is
  a skipped window, not the end of data; the pager advances until it
  reaches ``end`` (default: now) or ``max_candles``.
* Documented public rate limit: 10 requests/second per IP (bursts to 15).
  Pages are paced at ``COINBASE_PAGE_PAUSE_SECONDS`` (≤ 4 rps). **A single
  HTTP 429 ends the fetch as ``skipped``** ("rerun later"); there is no retry
  loop and no partial file.

Quote is USD. Research input only: nothing here reaches ``RiskEngine`` or a
``PAPER_PROMOTE_*`` default.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import httpx

from traderstack.candles import Candle
from traderstack.research.candle_fetch import (
    CandleFetch,
    drop_uncommitted_last,
    finish_fetch,
    floor_to_interval,
    http_skip,
    iso_utc,
    skip_fetch,
)

COINBASE_EXCHANGE_BASE = "https://api.exchange.coinbase.com"
COINBASE_CANDLES_PATH = "/products/{product}/candles"
COINBASE_MAX_CANDLES_PER_REQUEST = 300
# Inclusive window: start .. start + (300 - 1) * granularity = exactly 300 rows.
COINBASE_WINDOW_BARS = COINBASE_MAX_CANDLES_PER_REQUEST - 1
COINBASE_GRANULARITY: dict[str, int] = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "1h": 3600,
    "6h": 21600,
    "1d": 86400,
}
COINBASE_PUBLIC_RATE_LIMIT_RPS = 10
COINBASE_PAGE_PAUSE_SECONDS = 0.25
COINBASE_SOURCE = "coinbase_exchange_candles"
COINBASE_QUOTE = "USD"
_EXCEEDS_300_MARKER = "exceeds 300"


def coinbase_product(symbol: str) -> str:
    """``BTC/USD`` -> ``BTC-USD`` (Coinbase product id)."""
    key = symbol.strip().upper()
    if "-" in key and "/" not in key:
        base, _, quote = key.partition("-")
    else:
        base, _, quote = key.partition("/")
    if not base or not quote or not base.isalnum() or not quote.isalnum():
        raise ValueError(f"malformed symbol {symbol!r}; expected BASE/QUOTE such as BTC/USD")
    return f"{base}-{quote}"


def coinbase_granularity(resolution: str) -> int:
    if resolution not in COINBASE_GRANULARITY:
        raise ValueError(
            f"Coinbase Exchange does not offer {resolution!r} candles; "
            f"supported: {sorted(COINBASE_GRANULARITY)} (no 4h — use binance_vision)"
        )
    return COINBASE_GRANULARITY[resolution]


def parse_coinbase_rows(payload: object, *, symbol: str, interval: str) -> tuple[Candle, ...]:
    """Reduce ``[[time, low, high, open, close, volume], ...]`` to ascending Candles."""
    if isinstance(payload, dict):
        message = payload.get("message") or str(payload)
        raise TypeError(f"Coinbase candles error: {message}")
    if not isinstance(payload, list):
        raise TypeError("Coinbase candles payload must be a JSON array")
    candles: list[Candle] = []
    for row in payload:
        if not isinstance(row, list) or len(row) < 6:
            raise TypeError("Coinbase candle row must be [time, low, high, open, close, volume]")
        opened_seconds = int(row[0])
        low_f = float(row[1])
        high_f = float(row[2])
        open_f = float(row[3])
        close_f = float(row[4])
        volume_f = float(row[5])
        if open_f <= 0 or high_f <= 0 or low_f <= 0 or close_f <= 0:
            raise ValueError("Coinbase candle prices must be positive")
        high_f = max(high_f, open_f, close_f)
        low_f = min(low_f, open_f, close_f)
        candles.append(
            Candle(
                symbol=symbol.upper(),
                interval=interval,
                opened_at=datetime.fromtimestamp(opened_seconds, tz=UTC),
                open=open_f,
                high=high_f,
                low=low_f,
                close=close_f,
                volume=volume_f,
            )
        )
    candles.sort(key=lambda candle: candle.opened_at)
    return tuple(candles)


async def fetch_coinbase_candles(
    symbol: str,
    resolution: str,
    *,
    start: int,
    end: int | None = None,
    client: httpx.AsyncClient | None = None,
    max_candles: int | None = None,
    page_pause_seconds: float = COINBASE_PAGE_PAUSE_SECONDS,
    now: datetime | None = None,
) -> CandleFetch:
    """Page forward from ``start`` (unix seconds) in exact-300-bar windows.

    ``start``/``end`` are floored to the granularity. The walk ends at
    ``end`` (default: now), or once ``max_candles`` distinct bars have been
    merged. Any HTTP error, a 429, a malformed row or a misaligned bar
    yields ``status="skipped"`` — never a partial file, never a raise.
    """
    granularity = coinbase_granularity(resolution)
    product = coinbase_product(symbol)
    name = f"{symbol.upper()}@{resolution}"
    reference_now = now or datetime.now(UTC)
    now_seconds = int(reference_now.timestamp())
    window_start = floor_to_interval(start, resolution)
    end_bound = floor_to_interval(end if end is not None else now_seconds, resolution)
    if window_start > end_bound:
        return skip_fetch(
            name,
            source=COINBASE_SOURCE,
            reason=f"start {iso_utc(window_start)} is after end {iso_utc(end_bound)}",
        )
    limit = max_candles if max_candles is not None and max_candles > 0 else None
    path = COINBASE_CANDLES_PATH.format(product=product)
    merged: dict[int, Candle] = {}
    pages = 0
    empty_windows = 0

    async def _walk(active: httpx.AsyncClient) -> CandleFetch | None:
        nonlocal window_start, pages, empty_windows
        while window_start <= end_bound:
            if limit is not None and len(merged) >= limit:
                break
            window_end = min(window_start + COINBASE_WINDOW_BARS * granularity, end_bound)
            params: dict[str, str | int] = {
                "granularity": granularity,
                "start": iso_utc(window_start),
                "end": iso_utc(window_end),
            }
            if pages and page_pause_seconds > 0:
                await asyncio.sleep(page_pause_seconds)
            response = await active.get(path, params=params)
            pages += 1
            if response.status_code == 429:
                return skip_fetch(
                    name,
                    source=COINBASE_SOURCE,
                    reason=(
                        f"HTTP 429 after {pages} page(s) (rate limited; rerun later — "
                        "no retry, no partial file)"
                    ),
                )
            if response.status_code == 400 and _EXCEEDS_300_MARKER in response.text:
                return skip_fetch(
                    name,
                    source=COINBASE_SOURCE,
                    reason=(
                        f"HTTP 400 window exceeds {COINBASE_MAX_CANDLES_PER_REQUEST} bars "
                        f"({params['start']}..{params['end']}) — pager bug, not a venue outage"
                    ),
                )
            response.raise_for_status()
            rows = parse_coinbase_rows(response.json(), symbol=symbol, interval=resolution)
            if not rows:
                empty_windows += 1
            for candle in rows:
                merged[int(candle.opened_at.timestamp())] = candle
            window_start = window_end + granularity
        return None

    try:
        if client is not None:
            skipped = await _walk(client)
        else:
            async with httpx.AsyncClient(base_url=COINBASE_EXCHANGE_BASE, timeout=30) as owned:
                skipped = await _walk(owned)
    except httpx.HTTPError as exc:
        return http_skip(name, source=COINBASE_SOURCE, exc=exc)
    except (TypeError, ValueError) as exc:
        return skip_fetch(name, source=COINBASE_SOURCE, reason=f"parse failed: {exc}")
    if skipped is not None:
        return skipped

    ordered = tuple(merged[key] for key in sorted(merged))
    ordered = drop_uncommitted_last(ordered, resolution, now=reference_now)
    if limit is not None and len(ordered) > limit:
        ordered = ordered[:limit]
    pace = f"{1 / page_pause_seconds:g}" if page_pause_seconds > 0 else "unpaced"
    notes = (
        (
            f"quote={COINBASE_QUOTE}; product={product}; pages={pages}; "
            f"empty_windows={empty_windows}; window_bars={COINBASE_MAX_CANDLES_PER_REQUEST}; "
            f"pace<={pace} rps (documented public limit {COINBASE_PUBLIC_RATE_LIMIT_RPS} rps/IP)"
        ),
    )
    try:
        return finish_fetch(
            name,
            source=COINBASE_SOURCE,
            candles=ordered,
            interval=resolution,
            ok_reason=f"{len(ordered)} committed {resolution} bars over {pages} page(s)",
            notes=notes,
            fetched_at=reference_now,
        )
    except ValueError as exc:
        return skip_fetch(name, source=COINBASE_SOURCE, reason=f"alignment failed: {exc}")
