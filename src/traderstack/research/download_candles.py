"""`traderstack-download-candles`: page Kraken's public Spot OHLC REST endpoint
into the JSON candle format `traderstack-research --candles` expects.

**Verified** against Kraken's public API documentation
(https://docs.kraken.com/api/docs/rest-api/get-ohlc-data, fetched 2026-09-04):

- Endpoint: ``GET https://api.kraken.com/0/public/OHLC``
- Query params: ``pair`` (e.g. ``XBTUSD``), ``interval`` (minutes: 1, 5, 15, 30,
  60, 240, 1440, 10080, 21600), and optional ``since`` (unix seconds).
- Response: ``{"error": [...], "result": {"<pair>": [[time, open, high, low,
  close, vwap, volume, count], ...], "last": <unix seconds>}}``.
- Cap, quoted verbatim: "Returns up to 720 of the most recent entries (older
  data cannot be retrieved, regardless of the value of `since`)." -- i.e.
  ``since``/``last`` page **forward** toward the present, not backward past the
  most recent 720 bars; there is no way to reach further back in history through
  this endpoint alone.
- The documentation also notes the final row of every response is "the current,
  not-yet-committed timeframe" -- this script drops it, since a backtest must
  never persist a candle whose close price can still change.

This script therefore starts at ``--since`` (default: let Kraken return its most
recent window) and walks forward, using each page's ``last`` as the next
``since``, merging pages by timestamp (a later page's version of a bar wins,
since it may have been "not yet committed" in an earlier page) until it reaches
the present, runs out of new data, or hits ``--max-candles``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from traderstack.candles import Candle, interval_to_seconds

KRAKEN_REST_BASE_URL = "https://api.kraken.com"
KRAKEN_OHLC_PATH = "/0/public/OHLC"
MAX_CANDLES_PER_CALL = 720

# Kraken's `interval` query parameter is in minutes and only accepts this fixed set.
_INTERVAL_MINUTES: dict[str, int] = {
    "1m": 1,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "4h": 240,
    "1d": 1440,
    "1w": 10080,
}


def _kraken_pair(symbol: str) -> str:
    base, _, quote = symbol.upper().partition("/")
    if not quote:
        raise ValueError(f"symbol must be formatted BASE/QUOTE, got {symbol!r}")
    return f"{base}{quote}"


async def fetch_ohlc_page(
    client: httpx.AsyncClient, *, pair: str, interval_minutes: int, since: int | None
) -> tuple[list[list[Any]], int]:
    """One call to Kraken's public OHLC endpoint; returns (rows, last-cursor)."""
    params: dict[str, str | int] = {"pair": pair, "interval": interval_minutes}
    if since is not None:
        params["since"] = since
    response = await client.get(KRAKEN_OHLC_PATH, params=params)
    response.raise_for_status()
    payload = response.json()
    errors = payload.get("error") or []
    if errors:
        raise RuntimeError(f"Kraken OHLC error: {errors}")
    result = dict(payload["result"])
    last = int(result.pop("last"))
    if len(result) != 1:
        raise TypeError(f"unexpected Kraken OHLC result shape: {sorted(result)}")
    (rows,) = result.values()
    if not isinstance(rows, list):
        raise TypeError("unexpected Kraken OHLC row payload")
    return rows, last


async def download_candles(
    symbol: str,
    resolution: str,
    *,
    since: int | None = None,
    max_candles: int = 5_000,
    base_url: str = KRAKEN_REST_BASE_URL,
    client: httpx.AsyncClient | None = None,
) -> tuple[Candle, ...]:
    """Page Kraken OHLC forward from `since`, capped at `max_candles`."""
    if resolution not in _INTERVAL_MINUTES:
        raise ValueError(
            f"unsupported resolution {resolution!r}; use one of {sorted(_INTERVAL_MINUTES)}"
        )
    interval_minutes = _INTERVAL_MINUTES[resolution]
    pair = _kraken_pair(symbol)
    # Sanity-check the interval parses; also keeps candles.py's parser exercised here.
    interval_to_seconds(resolution)

    collected: dict[int, Candle] = {}
    cursor = since

    async def _run(active_client: httpx.AsyncClient) -> None:
        nonlocal cursor
        while len(collected) < max_candles:
            rows, last = await fetch_ohlc_page(
                active_client, pair=pair, interval_minutes=interval_minutes, since=cursor
            )
            if not rows:
                break
            new_count = 0
            for row in rows:
                timestamp = int(row[0])
                candle = Candle(
                    symbol=symbol.upper(),
                    interval=resolution,
                    opened_at=datetime.fromtimestamp(timestamp, tz=UTC),
                    open=float(row[1]),
                    high=float(row[2]),
                    low=float(row[3]),
                    close=float(row[4]),
                    volume=float(row[6]),
                )
                if timestamp not in collected:
                    new_count += 1
                collected[timestamp] = candle
            if last == cursor or new_count == 0:
                # No forward progress -- we've caught up to the present.
                break
            cursor = last

    if client is not None:
        await _run(client)
    else:
        async with httpx.AsyncClient(base_url=base_url, timeout=15) as owned_client:
            await _run(owned_client)

    ordered = sorted(collected.values(), key=lambda candle: candle.opened_at)
    if ordered:
        # The last bar of the last page fetched is always "not yet committed" per
        # Kraken's docs -- never persist a candle whose close price can still change.
        ordered = ordered[:-1]
    if max_candles and len(ordered) > max_candles:
        ordered = ordered[-max_candles:]
    return tuple(ordered)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download Kraken OHLC candles into the traderstack-research JSON format"
    )
    parser.add_argument("symbol", help="e.g. BTC/USD")
    parser.add_argument("--resolution", default="1h", choices=sorted(_INTERVAL_MINUTES))
    parser.add_argument(
        "--since",
        default=None,
        help="ISO8601 timestamp or unix seconds to page forward from; default: Kraken's most recent window",
    )
    parser.add_argument("--max-candles", type=int, default=5_000)
    parser.add_argument("--out", type=Path, required=True, help="output JSON file path")
    return parser


def _parse_since(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        pass
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return int(parsed.timestamp())


async def _run_cli(args: argparse.Namespace) -> None:
    since = _parse_since(args.since)
    candles = await download_candles(
        args.symbol, args.resolution, since=since, max_candles=args.max_candles
    )
    payload = [json.loads(candle.model_dump_json()) for candle in candles]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2))
    print(f"wrote {len(candles)} candles to {args.out}")


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    asyncio.run(_run_cli(args))


if __name__ == "__main__":
    main()
