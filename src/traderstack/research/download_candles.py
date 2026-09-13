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

Multi-year archives (#133)
--------------------------

``--venue`` selects a longer-history source than the Kraken 720-bar REST cap:

* ``kraken`` (default) — the public OHLC walk described above. Unchanged.
* ``coinbase`` — Coinbase Exchange public candles, paginated 300 at a time
  back to 2015/2016 (``research/candles_coinbase.py``).
* ``binance_vision`` — checksum-verified monthly spot kline zips from
  ``data.binance.vision``, spot from 2017-08
  (``research/candles_binance_vision.py``).
* ``kraken_archive`` — a local, manually downloaded Kraken OHLCVT drop
  (``research/candles_kraken_archive.py``). No network.

Every non-Kraken-REST venue also writes a **report header** next to the candle
JSON (``--report``, default ``<out>.report.json``) recording venue, first/last
bar, bar count, gaps and the fetch time. ``--cross-check`` compares the fetched
daily closes against another candle JSON (e.g. a Kraken archive export) and
flags every bar diverging by more than ``MAX_REFERENCE_DIVERGENCE_BPS`` — the
existing version-controlled ``Settings`` limit, read, never written. A flagged
bar is reported, never silently used.
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

# --- multi-year candle archives (#133) ---
from traderstack.research.candle_archives import (
    CandleSeriesFetch,
    DivergenceReport,
    cross_venue_divergence,
)
from traderstack.research.candles_binance_vision import fetch_binance_vision_monthly
from traderstack.research.candles_coinbase import (
    COINBASE_DEFAULT_REQUESTS_PER_SECOND,
    fetch_coinbase_candles,
)
from traderstack.research.candles_kraken_archive import load_kraken_archive

# Research CLI / tests still use the underscored names from this module.
_INTERVAL_MINUTES = INTERVAL_MINUTES
_kraken_pair = kraken_pair

MAX_CANDLES_PER_CALL = 720

# --- multi-year candle archives (#133) ---
ARCHIVE_VENUES: tuple[str, ...] = ("coinbase", "binance_vision", "kraken_archive")
VENUE_CHOICES: tuple[str, ...] = ("kraken", *ARCHIVE_VENUES)


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
    parser.add_argument("--max-candles", type=int, default=5_000)
    parser.add_argument(
        "--source",
        choices=("ohlc", "charts"),
        default="ohlc",
        help="ohlc = public Spot OHLC (720-bar cap). charts = futures charts spot PI_* (~180d 1h).",
    )
    parser.add_argument("--out", type=Path, required=True, help="output JSON file path")
    # --- multi-year candle archives (#133) ---
    parser.add_argument(
        "--venue",
        choices=VENUE_CHOICES,
        default="kraken",
        help=(
            "kraken = public OHLC REST (720-bar cap, the default). "
            "coinbase = Coinbase Exchange public candles (300/request, back to 2015/2016). "
            "binance_vision = checksum-verified monthly spot zips (from 2017-08). "
            "kraken_archive = local OHLCVT drop (manual download, no network)."
        ),
    )
    parser.add_argument(
        "--start",
        default=None,
        help="ISO8601 UTC start of the archive window (required for coinbase/binance_vision)",
    )
    parser.add_argument(
        "--end",
        default=None,
        help="ISO8601 UTC end of the archive window; default: now",
    )
    parser.add_argument(
        "--archive-path",
        type=Path,
        default=None,
        help=(
            "kraken_archive only: the unpacked OHLCVT CSV or the directory holding it. "
            "Default: RESEARCH_KRAKEN_ARCHIVE_PATH from Settings."
        ),
    )
    parser.add_argument(
        "--requests-per-second",
        type=float,
        default=COINBASE_DEFAULT_REQUESTS_PER_SECOND,
        help=(
            "coinbase only: explicit request pace. The documented public limit is "
            "10 req/s/IP (bursts to 15); an HTTP 429 is a skip, never a retry."
        ),
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="archive venues: report-header JSON path; default <out>.report.json",
    )
    parser.add_argument(
        "--cross-check",
        type=Path,
        default=None,
        help=(
            "candle JSON from another venue to sanity-check daily closes against; "
            "bars diverging by more than --max-divergence-bps are flagged in the report"
        ),
    )
    parser.add_argument(
        "--max-divergence-bps",
        type=float,
        default=None,
        help="default: MAX_REFERENCE_DIVERGENCE_BPS from Settings (never written back)",
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


# --- multi-year candle archives (#133) ---
def _parse_moment(value: str | None) -> datetime | None:
    """ISO8601 (or unix seconds) → an aware UTC datetime."""
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=UTC)
    except ValueError:
        pass
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def write_candle_json(path: Path, candles: tuple[Candle, ...]) -> None:
    """Write the candle JSON format `traderstack-research --candles` reads."""
    payload = [json.loads(candle.model_dump_json()) for candle in candles]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))


def read_candle_json(path: Path) -> tuple[Candle, ...]:
    payload = json.loads(path.read_text())
    if not isinstance(payload, list):
        raise TypeError(f"{path}: expected a JSON array of candle objects")
    return tuple(Candle.model_validate(row) for row in payload)


def build_archive_report(
    fetch: CandleSeriesFetch, *, divergence: DivergenceReport | None = None
) -> dict[str, object]:
    """The report header for one archive pull, plus any cross-venue flags."""
    report: dict[str, object] = {"series": fetch.as_note()}
    if divergence is not None:
        report["cross_venue_divergence"] = divergence.as_note()
    return report


async def fetch_archive_series(args: argparse.Namespace) -> CandleSeriesFetch:
    """Dispatch one archive venue. Each returns a status=ok|skipped series."""
    start = _parse_moment(args.start)
    end = _parse_moment(args.end)
    if args.venue == "coinbase":
        if start is None:
            raise ValueError("--start is required for --venue coinbase")
        return await fetch_coinbase_candles(
            args.symbol,
            args.resolution,
            start=start,
            end=end,
            requests_per_second=args.requests_per_second,
        )
    if args.venue == "binance_vision":
        if start is None:
            raise ValueError("--start is required for --venue binance_vision")
        return await fetch_binance_vision_monthly(
            args.symbol, args.resolution, start=start, end=end
        )
    archive_path = args.archive_path
    if archive_path is None:
        from traderstack.config import Settings

        configured = Settings().research_kraken_archive_path.strip()
        if not configured:
            raise ValueError(
                "--venue kraken_archive needs --archive-path or RESEARCH_KRAKEN_ARCHIVE_PATH "
                "(the drop is a manual download; see docs/DATA-SOURCES.md)"
            )
        archive_path = Path(configured)
    return load_kraken_archive(archive_path, args.symbol, args.resolution, start=start, end=end)


def _resolve_max_divergence_bps(explicit: float | None) -> float:
    if explicit is not None:
        return explicit
    from traderstack.config import Settings

    # Read-only use of the existing version-controlled limit. Never written.
    return Settings().max_reference_divergence_bps


async def _run_archive_cli(args: argparse.Namespace) -> None:
    fetch = await fetch_archive_series(args)
    divergence: DivergenceReport | None = None
    if args.cross_check is not None and fetch.candles:
        reference = read_candle_json(args.cross_check)
        divergence = cross_venue_divergence(
            fetch.candles,
            reference,
            left_venue=fetch.venue,
            right_venue=f"cross_check:{args.cross_check.name}",
            max_bps=_resolve_max_divergence_bps(args.max_divergence_bps),
        )
    report_path = args.report or args.out.with_suffix(args.out.suffix + ".report.json")
    report = build_archive_report(fetch, divergence=divergence)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2))

    if fetch.status == "skipped":
        print(f"skipped {fetch.name}: {fetch.reason} (report: {report_path})")
        return
    write_candle_json(args.out, fetch.candles)
    first = fetch.first.isoformat() if fetch.first else ""
    last = fetch.last.isoformat() if fetch.last else ""
    print(
        f"wrote {fetch.bars} candles to {args.out} "
        f"[{fetch.venue} {first}..{last}, gaps={len(fetch.gaps)} "
        f"({fetch.missing_bars} bars), report: {report_path}]"
    )
    if divergence is not None and divergence.flagged:
        print(
            f"WARNING: {len(divergence.flagged)} bar(s) diverge from "
            f"{divergence.right_venue} by more than {divergence.max_bps:g} bps "
            f"(worst {divergence.worst_bps:.1f} bps) — see the report before using this series"
        )


async def _run_cli(args: argparse.Namespace) -> None:
    if getattr(args, "venue", "kraken") in ARCHIVE_VENUES:
        await _run_archive_cli(args)
        return
    since = _parse_since(args.since)
    if args.source == "charts":
        from traderstack.research.kraken_charts import download_kraken_charts

        candles = await download_kraken_charts(args.symbol, args.resolution, count=args.max_candles)
    else:
        candles = await download_candles(
            args.symbol, args.resolution, since=since, max_candles=args.max_candles
        )
    write_candle_json(args.out, candles)
    print(f"wrote {len(candles)} candles to {args.out}")


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    asyncio.run(_run_cli(args))


if __name__ == "__main__":
    main()
