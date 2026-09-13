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

Multi-year venues (#133; ``--venue`` / ``--source``):

* ``coinbase`` — Coinbase Exchange ``/products/{id}/candles`` paged forward
  in exact-300-bar windows from ``--since`` to ``--end`` (default now).
  Public limit 10 rps/IP documented; paced at ≤ 4 rps. One HTTP 429 ends
  the fetch as ``skipped`` (rerun later) — no retry storm, no partial file.
  No 4h granularity on Coinbase; it is rejected, never derived.
* ``binance_vision`` — monthly spot kline zips from data.binance.vision,
  sha256-verified against the published ``.CHECKSUM`` (mismatch fails
  closed). Quote is USDT. 404 months are skipped, not invented.
* ``kraken_archive`` — the manually downloaded Kraken OHLCVT CSV drop in
  ``RESEARCH_KRAKEN_ARCHIVE_DIR`` / ``--archive-dir``; a partial or
  unparsable file is refused.

For these venues the candle file stays the bare JSON list every
``--candles`` consumer loads, and the fetch header (venue, first/last bar,
bar count, gaps, fetched_at, divergence flags) is written to a sidecar
``<out>.meta.json`` (``x.json`` → ``x.meta.json``) and printed to stdout.
The candle file is written only when ``status=ok``; a skipped fetch writes
the sidecar, leaves any existing candle file untouched, and exits 0 — an
empty series is a successful research result. ``--cross-check`` flags
same-bar close divergence above ``MAX_REFERENCE_DIVERGENCE_BPS`` against a
second candle file; flags are recorded, bars are never dropped or blended.
Gaps are never interpolated. Research inputs only: nothing here reaches
``RiskEngine`` or a ``PAPER_PROMOTE_*`` default.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import replace
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
from traderstack.research.candle_fetch import (
    CandleFetch,
    close_divergence_flags,
    header_line,
    write_candle_json,
    write_meta_sidecar,
)

# Research CLI / tests still use the underscored names from this module.
_INTERVAL_MINUTES = INTERVAL_MINUTES
_kraken_pair = kraken_pair

MAX_CANDLES_PER_CALL = 720
DEFAULT_MAX_CANDLES = 5_000

# --- multi-year candle fetchers (#133) ---
LEGACY_VENUES = ("ohlc", "kraken", "charts")
MULTI_YEAR_VENUES = ("coinbase", "binance_vision", "kraken_archive")
VENUE_CHOICES = LEGACY_VENUES + MULTI_YEAR_VENUES


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


async def download_spot_histories(
    symbols: tuple[str, ...],
    resolutions: tuple[str, ...],
    *,
    max_candles: int = 720,
    base_url: str = KRAKEN_REST_BASE_URL,
    client: httpx.AsyncClient | None = None,
) -> dict[str, tuple[Candle, ...]]:
    """Page every ``symbol@resolution`` pair up to Kraken's 720-bar public cap.

    Keys are ``SYMBOL@interval``. The public OHLC endpoint cannot retrieve
    bars older than the most recent 720 regardless of ``since``; daily is
    therefore the long window (~2y) and 1h is the recent window (~30d).
    """
    owned = client is None
    active = client or httpx.AsyncClient(base_url=base_url, timeout=30)
    try:
        out: dict[str, tuple[Candle, ...]] = {}
        for symbol in symbols:
            for resolution in resolutions:
                candles = await download_candles(
                    symbol,
                    resolution,
                    max_candles=max_candles,
                    base_url=base_url,
                    client=active,
                )
                out[f"{symbol.upper()}@{resolution}"] = candles
        return out
    finally:
        if owned:
            await active.aclose()


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
    parser.add_argument(
        "--max-candles",
        type=int,
        default=None,
        help=(
            f"cap on bars; legacy venues default to {DEFAULT_MAX_CANDLES}, multi-year venues "
            "(#133) are unbounded unless set (a multi-year hourly pull is ~50k+ bars)"
        ),
    )
    parser.add_argument(
        "--source",
        "--venue",
        dest="source",
        choices=VENUE_CHOICES,
        default="ohlc",
        help=(
            "ohlc (alias kraken) = public Spot OHLC (720-bar cap). charts = futures charts "
            "spot PI_* (~180d 1h). coinbase = Coinbase Exchange multi-year (USD; no 4h). "
            "binance_vision = data.binance.vision monthly spot zips (USDT; checksum-verified). "
            "kraken_archive = offline Kraken OHLCVT CSV drop (RESEARCH_KRAKEN_ARCHIVE_DIR)."
        ),
    )
    parser.add_argument("--out", type=Path, required=True, help="output JSON file path")
    # --- multi-year candle fetchers (#133) ---
    parser.add_argument(
        "--end",
        default=None,
        help="ISO8601 timestamp or unix seconds to stop at (multi-year venues; default: now)",
    )
    parser.add_argument(
        "--archive-dir",
        type=Path,
        default=None,
        help="kraken_archive only: directory of the unzipped OHLCVT CSVs "
        "(overrides RESEARCH_KRAKEN_ARCHIVE_DIR)",
    )
    parser.add_argument(
        "--cross-check",
        type=Path,
        default=None,
        help="multi-year venues only: a second candle JSON (e.g. the Kraken daily 720); "
        "same-bar closes diverging above the threshold are flagged in the sidecar, never dropped",
    )
    parser.add_argument(
        "--max-divergence-bps",
        type=float,
        default=None,
        help="research-only cross-check threshold in bps; default: Settings "
        "MAX_REFERENCE_DIVERGENCE_BPS (read, never written; not the pipeline gate)",
    )
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


# --- multi-year candle fetchers (#133) ---
def _resolve_max_divergence_bps(value: float | None) -> float:
    if value is not None:
        if value <= 0:
            raise ValueError("--max-divergence-bps must be positive")
        return float(value)
    from traderstack.config import Settings

    return float(Settings().max_reference_divergence_bps)


async def _fetch_multi_year(args: argparse.Namespace, since: int | None) -> CandleFetch:
    end = _parse_since(args.end)
    if args.source == "coinbase":
        from traderstack.research.candles_coinbase import fetch_coinbase_candles

        if since is None:
            raise ValueError("--since is required for --venue coinbase (e.g. 2016-01-01)")
        return await fetch_coinbase_candles(
            args.symbol, args.resolution, start=since, end=end, max_candles=args.max_candles
        )
    if args.source == "binance_vision":
        from traderstack.research.candles_binance_vision import fetch_binance_vision_candles

        if since is None:
            raise ValueError("--since is required for --venue binance_vision (e.g. 2017-08-01)")
        return await fetch_binance_vision_candles(
            args.symbol, args.resolution, start=since, end=end
        )
    if args.source == "kraken_archive":
        from traderstack.config import Settings
        from traderstack.research.candles_kraken_archive import load_kraken_archive_candles

        archive_dir = args.archive_dir
        if archive_dir is None:
            configured = Settings().research_kraken_archive_dir
            archive_dir = Path(configured) if configured else ""
        return load_kraken_archive_candles(
            archive_dir, args.symbol, args.resolution, start=since, end=end
        )
    raise ValueError(f"unknown venue {args.source!r}")


def _apply_cross_check(fetch: CandleFetch, args: argparse.Namespace) -> CandleFetch:
    if args.cross_check is None or fetch.status != "ok":
        return fetch
    from traderstack.research.cli import load_candles_from_json

    reference = load_candles_from_json(args.cross_check)
    max_bps = _resolve_max_divergence_bps(args.max_divergence_bps)
    flags = close_divergence_flags(fetch.candles, reference, max_bps=max_bps)
    shared = len(
        {int(c.opened_at.timestamp()) for c in fetch.candles}
        & {int(c.opened_at.timestamp()) for c in reference}
    )
    note = (
        f"cross-check vs {args.cross_check.name}: {shared} shared bars, "
        f"{len(flags)} flagged above {max_bps:g} bps (flagged only; nothing dropped or blended)"
    )
    return replace(
        fetch,
        divergence_flags=flags,
        divergence_max_bps=max_bps,
        divergence_reference=str(args.cross_check),
        notes=fetch.notes + (note,),
    )


async def _run_multi_year(args: argparse.Namespace, since: int | None) -> None:
    fetch = await _fetch_multi_year(args, since)
    fetch = _apply_cross_check(fetch, args)
    if fetch.status == "ok":
        write_candle_json(args.out, fetch.candles)
    sidecar = write_meta_sidecar(args.out, fetch)
    print(header_line(fetch))
    for note in fetch.notes:
        print(f"  note: {note}")
    if fetch.status == "ok":
        print(f"wrote {len(fetch.candles)} candles to {args.out} (header: {sidecar})")
    else:
        print(f"skipped: no candle file written (existing {args.out} untouched); header: {sidecar}")


async def _run_cli(args: argparse.Namespace) -> None:
    since = _parse_since(args.since)
    if args.source in MULTI_YEAR_VENUES:
        await _run_multi_year(args, since)
        return
    max_candles = DEFAULT_MAX_CANDLES if args.max_candles is None else args.max_candles
    if args.source == "charts":
        from traderstack.research.kraken_charts import download_kraken_charts

        candles = await download_kraken_charts(args.symbol, args.resolution, count=max_candles)
    else:
        candles = await download_candles(
            args.symbol, args.resolution, since=since, max_candles=max_candles
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
