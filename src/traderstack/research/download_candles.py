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

import httpx

from traderstack.candles import Candle, interval_to_seconds
from traderstack.market.kraken_candles import (
    INTERVAL_MINUTES,
    KRAKEN_REST_BASE_URL,
    fetch_ohlc_page,
    kraken_pair,
    parse_ohlc_row,
)

# Research CLI / tests still use the underscored names from this module.
_INTERVAL_MINUTES = INTERVAL_MINUTES
_kraken_pair = kraken_pair

MAX_CANDLES_PER_CALL = 720


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
                candle = parse_ohlc_row(row, symbol=symbol, resolution=resolution)
                timestamp = int(candle.opened_at.timestamp())
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
    parser.add_argument(
        "--source",
        choices=("ohlc", "charts"),
        default="ohlc",
        help="ohlc = public Spot OHLC (720-bar cap). charts = futures charts spot PI_* (~180d 1h).",
    )
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
    if args.source == "charts":
        from traderstack.research.kraken_charts import download_kraken_charts

        candles = await download_kraken_charts(args.symbol, args.resolution, count=args.max_candles)
    else:
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
