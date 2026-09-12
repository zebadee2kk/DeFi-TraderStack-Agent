"""`traderstack-funding-carry`: fee-aware funding-z / carry catalog.

Scores the frozen funding-z threshold + spot-overlay + hedged-carry
catalog on Kraken public Spot (default 4h) aligned to public
funding-rate history. Probes Binance, Bybit, OKX, Hyperliquid, HTX,
and BitMEX independently (skip-not-invent; do not blend). BitMEX is
a sunset venue (official closure 23 September 2026 04:00 UTC) and is
excluded from venue pick. ``--interval 1d`` resamples funding to UTC
daily sums (empty days omitted) so the #96+A+B+C bar can be evaluated
or recorded UNAVAILABLE. Dual-print only if two independent
non-sunset funding venues cover BTC and ETH. Basis is skipped unless
a PIT mark−index / perp-mid−spot-mid series is supplied on **both**
dual-print venues for the scored window; live probes record
UNAVAILABLE rather than inventing one. Otherwise SINGLE-PRINT and
cannot promote. Never flips ``PAPER_PROMOTE_*``. Empty search is
success. No live.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

import httpx

from traderstack.candles import Candle
from traderstack.config import Settings
from traderstack.research.cli import load_candles_from_json
from traderstack.research.daily_robustness import KRAKEN_PUBLIC_OHLC_MAX_BARS
from traderstack.research.download_candles import download_spot_histories
from traderstack.research.edge_series import (
    utc_day,
    truncate_points_to_end,
    freeze_window_start,
    BASIS_AWARE_WINDOW_END_UTC,
    BASIS_AWARE_MIN_ALIGNED_DAYS,
    BINANCE_FAPI_BASE,
    BITMEX_BASE,
    BITMEX_DAILY_LIMIT_PAGES,
    BITMEX_DAILY_LOOKBACK_DAYS,
    BITMEX_DEFAULT_LOOKBACK_DAYS,
    BYBIT_BASE,
    HTX_BASE,
    HTX_DAILY_LIMIT_PAGES,
    HTX_DAILY_LOOKBACK_DAYS,
    HTX_DEFAULT_LOOKBACK_DAYS,
    HYPERLIQUID_BASE,
    HYPERLIQUID_DAILY_LIMIT_PAGES,
    HYPERLIQUID_DAILY_LOOKBACK_DAYS,
    HYPERLIQUID_DEFAULT_LOOKBACK_DAYS,
    HYPERLIQUID_SYMBOL_PAUSE_SECONDS,
    OKX_BASE,
    SUNSET_FUNDING_VENUES,
    fetch_binance_funding,
    fetch_bitmex_basis,
    fetch_bitmex_funding,
    fetch_bybit_funding,
    fetch_htx_basis,
    fetch_htx_funding,
    fetch_hyperliquid_basis,
    fetch_hyperliquid_funding,
    fetch_okx_funding,
)
from traderstack.research.funding_carry import (
    ALLOWED_INTERVALS,
    DEFAULT_INTERVAL,
    DEFAULT_STEP_SIZE,
    DEFAULT_TEST_SIZE,
    DEFAULT_TRAIN_SIZE,
    DEFAULT_WARMUP,
    REQUIRED_SYMBOLS,
    funding_usable,
    render_funding_carry_markdown,
    run_funding_carry,
    venue_mean_points,
)
from traderstack.research.miles_search import research_fee_bps
from traderstack.research.search_cli import _parse_feature_series

DEFAULT_SYMBOLS = REQUIRED_SYMBOLS


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Score a pre-registered funding-z / carry catalog on Kraken "
            "public Spot (default 4h) aligned to public funding-rate "
            "history (OKX + Hyperliquid + HTX when reachable; BitMEX "
            "is a sunset venue and is not selected; "
            "Binance/Bybit probed and skipped if geo-blocked). --interval 1d resamples "
            "funding to UTC daily sums (empty days omitted) so #96+A+B+C "
            "can be evaluated or recorded UNAVAILABLE honestly. Dual-print "
            "only if two independent funding venues cover BTC and ETH. "
            "Basis is skipped unless a PIT mark−index / perp-mid−spot-mid "
            "series is supplied on both dual-print venues; --live probes "
            "Hyperliquid, HTX, and BitMEX (sunset notes) and records "
            "UNAVAILABLE rather than inventing one. Otherwise "
            "SINGLE-PRINT and cannot promote. Does not flip "
            "PAPER_PROMOTE_*. Empty search is success."
        )
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--candles",
        type=Path,
        action="append",
        help="JSON candle array (repeat per asset). Symbol+interval from file.",
    )
    source.add_argument(
        "--live",
        action="store_true",
        help=(
            "fetch BTC/ETH from Kraken public OHLC "
            f"(hard cap {KRAKEN_PUBLIC_OHLC_MAX_BARS} bars) and probe "
            "Binance + Bybit + OKX + Hyperliquid + HTX + BitMEX "
            "(sunset, not selected) funding-rate history independently "
            "(skip-not-invent)"
        ),
    )
    parser.add_argument(
        "--interval",
        choices=ALLOWED_INTERVALS,
        default=DEFAULT_INTERVAL,
        help=(
            "Kraken interval (default 4h so a ~90d tape can walk-forward; "
            "1d resamples funding to UTC daily sums for the hard-gate bar)"
        ),
    )
    parser.add_argument(
        "--symbol",
        action="append",
        default=None,
        help="override live Kraken symbols (repeat; default BTC/USD ETH/USD)",
    )
    parser.add_argument("--max-candles", type=int, default=KRAKEN_PUBLIC_OHLC_MAX_BARS)
    parser.add_argument("--starting-equity", type=float, default=None)
    parser.add_argument("--fee-bps", type=float, default=None)
    parser.add_argument("--slippage-bps", type=float, default=None)
    parser.add_argument("--train-size", type=int, default=DEFAULT_TRAIN_SIZE)
    parser.add_argument("--test-size", type=int, default=DEFAULT_TEST_SIZE)
    parser.add_argument("--step-size", type=int, default=DEFAULT_STEP_SIZE)
    parser.add_argument("--warmup", type=int, default=DEFAULT_WARMUP)
    parser.add_argument("--holdout-fraction", type=float, default=0.20)
    parser.add_argument("--min-trades", type=int, default=3)
    parser.add_argument(
        "--fetch-funding",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="download public funding (default on for --live). Skip-not-invent.",
    )
    parser.add_argument(
        "--funding-z",
        type=Path,
        default=None,
        help="optional aligned [{opened_at, value}] series; omitted = family skipped",
    )
    parser.add_argument(
        "--second-funding-z",
        type=Path,
        default=None,
        help="optional second independent funding series (offline dual-print)",
    )
    parser.add_argument(
        "--basis",
        type=Path,
        default=None,
        help=(
            "optional PIT perp−spot basis [{opened_at, value}] series. "
            "Omitted = skip-not-invent; do not pass last-trade or funding "
            "premium as a substitute"
        ),
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=Path("var/ops/funding_carry.json"),
    )
    parser.add_argument(
        "--output-md",
        type=Path,
        default=Path("docs/artifacts/strategy-search/funding-carry.md"),
    )
    parser.add_argument("--stdout-md", action="store_true")
    return parser


def _history_key(candles: tuple[Candle, ...]) -> str:
    return f"{candles[0].symbol}@{candles[0].interval}"


def _as_history_notes(notes: list[str]) -> list[dict[str, str]]:
    return [{"note": item, "source": "funding_carry"} for item in notes]


def _load_candle_files(
    paths: list[Path], *, interval: str
) -> tuple[dict[str, tuple[Candle, ...]], list[str]]:
    histories: dict[str, tuple[Candle, ...]] = {}
    notes: list[str] = []
    for path in paths:
        candles = load_candles_from_json(path)
        if not candles:
            raise ValueError(f"{path}: no candles")
        if candles[0].interval != interval:
            raise ValueError(
                f"{path}: interval {candles[0].interval!r} does not match --interval {interval!r}"
            )
        histories[_history_key(candles)] = candles
        notes.append(
            f"loaded {len(candles)} {candles[0].interval} bars for "
            f"{candles[0].symbol} from {path} (json)"
        )
    return histories, notes


def _load_live_kraken(
    symbols: tuple[str, ...], *, interval: str, max_candles: int
) -> tuple[dict[str, tuple[Candle, ...]], list[str]]:
    fetched = asyncio.run(download_spot_histories(symbols, (interval,), max_candles=max_candles))
    histories: dict[str, tuple[Candle, ...]] = {}
    notes: list[str] = []
    for key, candles in fetched.items():
        if not candles:
            notes.append(f"{key}: Kraken returned no committed bars")
            continue
        histories[key] = candles
        first = candles[0].opened_at.isoformat()
        last = candles[-1].opened_at.isoformat()
        cap = ""
        if len(candles) >= KRAKEN_PUBLIC_OHLC_MAX_BARS or max_candles > len(candles):
            cap = f" (public OHLC cap; requested {max_candles}, received {len(candles)} committed)"
        notes.append(f"{key}: {len(candles)} committed Kraken bars {first} → {last}{cap}")
    return histories, notes


async def fetch_funding_venues(
    symbols: tuple[str, ...],
    *,
    timeout: float = 20.0,
    hyperliquid_lookback_days: int = HYPERLIQUID_DEFAULT_LOOKBACK_DAYS,
    hyperliquid_limit_pages: int = 16,
    bitmex_lookback_days: int = BITMEX_DEFAULT_LOOKBACK_DAYS,
    bitmex_limit_pages: int = 8,
    htx_lookback_days: int = HTX_DEFAULT_LOOKBACK_DAYS,
    htx_limit_pages: int = 8,
) -> tuple[dict[str, dict[str, tuple]], list[dict[str, str]]]:
    """Fetch each venue independently. Do not blend the tapes."""
    venue_maps: dict[str, dict[str, tuple]] = {
        "binance": {},
        "bybit": {},
        "okx": {},
        "hyperliquid": {},
        "htx": {},
        "bitmex": {},
    }
    notes: list[dict[str, str]] = []
    async with httpx.AsyncClient(base_url=BINANCE_FAPI_BASE, timeout=timeout) as client:
        for symbol in symbols:
            result = await fetch_binance_funding(symbol, client=client)
            notes.append(result.as_note())
            if result.status == "ok":
                venue_maps["binance"][symbol.upper()] = result.points
    async with httpx.AsyncClient(base_url=BYBIT_BASE, timeout=timeout) as client:
        for symbol in symbols:
            result = await fetch_bybit_funding(symbol, client=client)
            notes.append(result.as_note())
            if result.status == "ok":
                venue_maps["bybit"][symbol.upper()] = result.points
    async with httpx.AsyncClient(base_url=OKX_BASE, timeout=timeout) as client:
        for symbol in symbols:
            result = await fetch_okx_funding(symbol, client=client)
            notes.append(result.as_note())
            if result.status == "ok":
                venue_maps["okx"][symbol.upper()] = result.points
    async with httpx.AsyncClient(base_url=HYPERLIQUID_BASE, timeout=max(timeout, 30.0)) as client:
        for index, symbol in enumerate(symbols):
            if index:
                await asyncio.sleep(HYPERLIQUID_SYMBOL_PAUSE_SECONDS)
            result = await fetch_hyperliquid_funding(
                symbol,
                client=client,
                lookback_days=hyperliquid_lookback_days,
                limit_pages=hyperliquid_limit_pages,
            )
            notes.append(result.as_note())
            if result.status == "ok":
                venue_maps["hyperliquid"][symbol.upper()] = result.points
    async with httpx.AsyncClient(base_url=HTX_BASE, timeout=max(timeout, 30.0)) as client:
        for symbol in symbols:
            result = await fetch_htx_funding(
                symbol,
                client=client,
                lookback_days=htx_lookback_days,
                limit_pages=htx_limit_pages,
            )
            notes.append(result.as_note())
            if result.status == "ok":
                venue_maps["htx"][symbol.upper()] = result.points
    async with httpx.AsyncClient(base_url=BITMEX_BASE, timeout=max(timeout, 30.0)) as client:
        for symbol in symbols:
            result = await fetch_bitmex_funding(
                symbol,
                client=client,
                lookback_days=bitmex_lookback_days,
                limit_pages=bitmex_limit_pages,
            )
            notes.append(result.as_note())
            if result.status == "ok":
                venue_maps["bitmex"][symbol.upper()] = result.points
    return venue_maps, notes


async def fetch_basis_venues(
    symbols: tuple[str, ...],
    *,
    timeout: float = 20.0,
    window_end: datetime | None = None,
    window_start: datetime | None = None,
) -> tuple[dict[str, dict[str, tuple]], list[dict[str, str]]]:
    """Fetch HL (asilletto81) + HTX PIT basis; BitMEX notes only (sunset)."""
    from datetime import datetime as _dt

    end = window_end or BASIS_AWARE_WINDOW_END_UTC
    start = window_start or freeze_window_start(end)
    notes: list[dict[str, str]] = []
    venue_maps: dict[str, dict[str, tuple]] = {
        "hyperliquid": {},
        "htx": {},
        "bitmex": {},
    }
    async with httpx.AsyncClient(base_url=HYPERLIQUID_BASE, timeout=max(timeout, 120.0)) as client:
        for index, symbol in enumerate(symbols):
            if index:
                await asyncio.sleep(HYPERLIQUID_SYMBOL_PAUSE_SECONDS)
            result = await fetch_hyperliquid_basis(
                symbol, client=client, start=start, end=end, prefer_archive=True
            )
            notes.append(result.as_note())
            if result.status == "ok":
                venue_maps["hyperliquid"][symbol.upper()] = result.points
    async with httpx.AsyncClient(base_url=HTX_BASE, timeout=max(timeout, 60.0)) as client:
        for symbol in symbols:
            result = await fetch_htx_basis(symbol, client=client)
            # clamp to freeze
            if result.status == "ok":
                clamped = truncate_points_to_end(result.points, end)
                clamped = tuple((ts, v) for ts, v in clamped if utc_day(ts) >= utc_day(start))
                notes.append(
                    {
                        **result.as_note(),
                        "points": str(len(clamped)),
                        "reason": result.reason + f" Clamped to freeze [{start.date()}→{end.date()}].",
                    }
                )
                if len(clamped) >= BASIS_AWARE_MIN_ALIGNED_DAYS:
                    venue_maps["htx"][symbol.upper()] = clamped
                else:
                    notes.append(
                        {
                            "name": f"htx_basis:{symbol}",
                            "status": "skipped",
                            "reason": (
                                f"HTX basis {len(clamped)} days inside freeze "
                                f"(need >={BASIS_AWARE_MIN_ALIGNED_DAYS})"
                            ),
                            "source": result.source,
                            "points": str(len(clamped)),
                        }
                    )
            else:
                notes.append(result.as_note())
    async with httpx.AsyncClient(base_url=BITMEX_BASE, timeout=max(timeout, 30.0)) as client:
        for symbol in symbols:
            result = await fetch_bitmex_basis(symbol, client=client)
            notes.append(result.as_note())
    return venue_maps, notes


def _merge_basis_by_symbol(
    mapping: dict[str, tuple],
) -> tuple[tuple[datetime, float], ...] | None:
    """Prefer BTC series when present; else first symbol. Skip-not-invent."""
    if not mapping:
        return None
    for key in ("BTC/USD", "BTCUSDT", "BTC"):
        for k, series in mapping.items():
            if key in k.upper() or k.upper().startswith("BTC"):
                return series
    # fall back to any
    return next(iter(mapping.values()))


def truncate_histories_to_end(
    histories: dict[str, tuple],
    end: datetime,
) -> dict[str, tuple]:
    end_d = utc_day(end)
    out: dict[str, tuple] = {}
    for key, candles in histories.items():
        kept = tuple(c for c in candles if utc_day(c.opened_at) <= end_d)
        if kept:
            out[key] = kept
    return out


def truncate_funding_map_to_window(
    mapping: dict[str, tuple] | None,
    *,
    start: datetime,
    end: datetime,
) -> dict[str, tuple] | None:
    if not mapping:
        return mapping
    start_d = utc_day(start)
    end_d = utc_day(end)
    out: dict[str, tuple] = {}
    for key, series in mapping.items():
        kept = tuple((ts, v) for ts, v in series if start_d <= utc_day(ts) <= end_d)
        if kept:
            out[key] = kept
    return out or None


def _pick_venues(
    venue_maps: dict[str, dict[str, tuple]],
) -> tuple[dict[str, tuple] | None, str | None, dict[str, tuple] | None, str | None]:
    """Prefer the two usable non-sunset venues with the most mean points."""
    usable = [
        (name, mapping)
        for name, mapping in venue_maps.items()
        if name not in SUNSET_FUNDING_VENUES and funding_usable(funding_by_symbol=mapping)
    ]
    usable.sort(key=lambda item: (-venue_mean_points(item[1]), item[0]))
    if len(usable) >= 2:
        return usable[0][1], usable[0][0], usable[1][1], usable[1][0]
    if len(usable) == 1:
        return usable[0][1], usable[0][0], None, None
    return None, None, None, None


def run(args: argparse.Namespace, settings: Settings | None = None) -> tuple[Path, Path]:
    settings = settings or Settings()
    symbols = tuple(args.symbol) if args.symbol else DEFAULT_SYMBOLS
    if args.live:
        histories, notes = _load_live_kraken(
            symbols, interval=args.interval, max_candles=args.max_candles
        )
    else:
        histories, notes = _load_candle_files(args.candles, interval=args.interval)
    history_notes = _as_history_notes(notes)

    if args.interval == "1d" and args.output_md == Path(
        "docs/artifacts/strategy-search/funding-carry.md"
    ):
        args.output_md = Path("docs/artifacts/strategy-search/funding-carry-daily.md")
    if args.interval == "1d" and args.output_json == Path("var/ops/funding_carry.json"):
        args.output_json = Path("var/ops/funding_carry_daily.json")

    funding = _parse_feature_series(args.funding_z) if args.funding_z else None
    second_funding = _parse_feature_series(args.second_funding_z) if args.second_funding_z else None
    basis = _parse_feature_series(args.basis) if args.basis else None
    basis_second = None
    funding_by_symbol = None
    second_funding_by_symbol = None
    primary_venue: str | None = "file" if funding is not None else None
    second_venue: str | None = "file" if second_funding is not None else None
    edge_notes: list[dict[str, str]] = []

    fetch_funding = args.fetch_funding if args.fetch_funding is not None else bool(args.live)
    if fetch_funding:
        hl_lookback = (
            HYPERLIQUID_DAILY_LOOKBACK_DAYS
            if args.interval == "1d"
            else HYPERLIQUID_DEFAULT_LOOKBACK_DAYS
        )
        hl_pages = HYPERLIQUID_DAILY_LIMIT_PAGES if args.interval == "1d" else 16
        bitmex_lookback = (
            BITMEX_DAILY_LOOKBACK_DAYS if args.interval == "1d" else BITMEX_DEFAULT_LOOKBACK_DAYS
        )
        bitmex_pages = BITMEX_DAILY_LIMIT_PAGES if args.interval == "1d" else 4
        htx_lookback = (
            HTX_DAILY_LOOKBACK_DAYS if args.interval == "1d" else HTX_DEFAULT_LOOKBACK_DAYS
        )
        htx_pages = HTX_DAILY_LIMIT_PAGES if args.interval == "1d" else 8
        venue_maps, edge_notes = asyncio.run(
            fetch_funding_venues(
                symbols,
                hyperliquid_lookback_days=hl_lookback,
                hyperliquid_limit_pages=hl_pages,
                bitmex_lookback_days=bitmex_lookback,
                bitmex_limit_pages=bitmex_pages,
                htx_lookback_days=htx_lookback,
                htx_limit_pages=htx_pages,
            )
        )
        primary_map, primary_venue, second_map, second_venue = _pick_venues(venue_maps)
        funding_by_symbol = primary_map
        second_funding_by_symbol = second_map
        basis_primary = None
        basis_second = None
        if basis is None:
            # Coverage-driven freeze BEFORE scoring (asilletto81 ends 2026-06-01).
            freeze_end = BASIS_AWARE_WINDOW_END_UTC
            freeze_start = freeze_window_start(freeze_end)
            histories = truncate_histories_to_end(histories, freeze_end)
            history_notes.append(
                {
                    "note": (
                        f"Basis-aware freeze: truncate candles/funding/basis to "
                        f"{freeze_start.date()}→{freeze_end.date()} "
                        f"(>={BASIS_AWARE_MIN_ALIGNED_DAYS}d) before scoring. "
                        "asilletto81 ends 2026-06-01; do not invent the post-archive tail."
                    ),
                    "source": "basis_window_freeze",
                }
            )
            if funding_by_symbol is not None:
                funding_by_symbol = truncate_funding_map_to_window(
                    funding_by_symbol, start=freeze_start, end=freeze_end
                )
            if second_funding_by_symbol is not None:
                second_funding_by_symbol = truncate_funding_map_to_window(
                    second_funding_by_symbol, start=freeze_start, end=freeze_end
                )
            basis_maps, basis_notes = asyncio.run(
                fetch_basis_venues(symbols, window_end=freeze_end, window_start=freeze_start)
            )
            edge_notes.extend(basis_notes)
            hl_map = basis_maps.get("hyperliquid") or {}
            htx_map = basis_maps.get("htx") or {}
            # Align basis venue to funding venue pick when possible.
            if primary_venue == "hyperliquid" and hl_map:
                basis_primary = _merge_basis_by_symbol(hl_map)
            elif primary_venue == "htx" and htx_map:
                basis_primary = _merge_basis_by_symbol(htx_map)
            if second_venue == "htx" and htx_map:
                basis_second = _merge_basis_by_symbol(htx_map)
            elif second_venue == "hyperliquid" and hl_map:
                basis_second = _merge_basis_by_symbol(hl_map)
            # If venues flipped, still attach whichever we have.
            if basis_primary is None and hl_map:
                basis_primary = _merge_basis_by_symbol(hl_map)
            if basis_second is None and htx_map:
                basis_second = _merge_basis_by_symbol(htx_map)
            basis = basis_primary
        if funding_by_symbol is None and funding is None:
            history_notes.append(
                {
                    "note": (
                        "No usable Binance / Bybit / OKX / Hyperliquid / HTX "
                        "funding series (BitMEX is a sunset venue and is not "
                        "selected) — families skipped, not invented. Labeled "
                        "single-print; cannot promote."
                    ),
                    "source": "funding_carry",
                }
            )
        elif second_funding_by_symbol is None and second_funding is None:
            history_notes.append(
                {
                    "note": (
                        f"Only one funding venue usable ({primary_venue}). "
                        "Same-venue split is not dual-print. Cannot promote."
                    ),
                    "source": "funding_carry",
                }
            )

    fee_bps = (
        args.fee_bps
        if args.fee_bps is not None
        else research_fee_bps(settings.pretrade_fee_bps, settings.paper_fee_bps)
    )
    slippage_bps = (
        args.slippage_bps if args.slippage_bps is not None else settings.pretrade_slippage_bps
    )
    report = run_funding_carry(
        histories,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
        starting_equity=args.starting_equity or settings.paper_starting_nav_usd,
        warmup=args.warmup,
        train_size=args.train_size,
        test_size=args.test_size,
        step_size=args.step_size,
        holdout_fraction=args.holdout_fraction,
        min_trades=args.min_trades,
        interval=args.interval,
        funding=funding,
        funding_by_symbol=funding_by_symbol,
        primary_venue=primary_venue,
        second_funding=second_funding,
        second_funding_by_symbol=second_funding_by_symbol,
        second_venue=second_venue,
        history_notes=history_notes,
        edge_notes=edge_notes,
        basis=basis,
        second_basis=basis_second,
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(report.model_dump_json(indent=2) + "\n")
    markdown = render_funding_carry_markdown(report)
    args.output_md.write_text(markdown)
    if args.stdout_md:
        print(markdown)
    else:
        print(
            f"{report.print_kind.upper()}: wrote {args.output_json} and "
            f"{args.output_md} (selected={report.selected_candidate_id or 'none'}; "
            f"primary={report.primary_venue or 'none'}; "
            f"hard_gates={report.hard_gates_available}; "
            f"can_promote={report.can_promote}; "
            f"keep_flag_false={report.keep_flag_false}). "
            "PAPER_PROMOTE_* flags are unchanged."
        )
    return args.output_json, args.output_md


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    run(args)


if __name__ == "__main__":
    main()
