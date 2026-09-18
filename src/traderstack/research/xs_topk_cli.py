"""`traderstack-xs-topk`: long-only top-k cross-sectional momentum on the
point-in-time Kraken USD spot universe (#140).

Sources (mutually exclusive, required):

- ``--live``: Kraken public ``AssetPairs`` listing, then one public OHLC
  daily pull per universe pair (720-bar cap, ``--sleep-seconds`` between
  pairs). A pair that errors, is rate-limited, or has too little history
  is skipped with a data note — never zero-filled. If the listing itself
  is unreachable and no ``--universe-file`` is given, the report says
  "universe unavailable; nothing scored" and exits 0 (empty is success).
- ``--candles-dir VENUE DIR`` (repeatable): every ``*.json`` candle array
  in ``DIR`` (the ``traderstack-download-candles`` format, or the #133
  Coinbase / Binance Vision fetcher output) is one venue print labelled
  ``VENUE``. Each print is scored independently; dual-print needs two
  independent covered cells.

Never flips ``PAPER_PROMOTE_*``. An empty passer set is success. No live.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx

from traderstack.candles import Candle
from traderstack.config import Settings
from traderstack.market.kraken_candles import KRAKEN_REST_BASE_URL
from traderstack.research.cli import load_candles_from_json
from traderstack.research.daily_robustness import KRAKEN_PUBLIC_OHLC_MAX_BARS
from traderstack.research.download_candles import download_candles
from traderstack.research.miles_search import research_fee_bps
from traderstack.research.universe import (
    UniversePair,
    canonical_from_symbol,
    canonical_symbol,
    fetch_kraken_usd_pairs,
)
from traderstack.research.xs_topk import (
    CATALOGS,
    resolve_catalog,
    MIN_HISTORY_MARGIN,
    PILOT_TIER_TAKER_BPS,
    RANKING_KEY,
    TOPK_LOOKBACKS,
    PrintResult,
    build_xs_topk_report,
    render_xs_topk_markdown,
    score_print,
)

LIVE_VENUE = "kraken"
LIVE_SOURCE = "kraken_public_ohlc_1d"
LISTING_SOURCE = "kraken_asset_pairs"
UNIVERSE_LISTING_FILENAME = "xs_topk_universe.json"
MIN_BARS_TO_LOAD = min(TOPK_LOOKBACKS) + MIN_HISTORY_MARGIN


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Long-only top-k cross-sectional momentum on the point-in-time "
            "Kraken USD spot universe (N in {21, 63, 126} with a 7-day skip; "
            "k in {3, 5}; equal or inverse-vol weights; weekly Monday-UTC "
            "rebalance). Portfolio bar with era prints; turnover and fee drag "
            "at research 10+5 bps and the pilot tier; ew_bh_universe control "
            f"cannot promote. Ranking key (frozen): {RANKING_KEY}. Does not "
            "flip PAPER_PROMOTE_* flags. An empty dual-print set is success. "
            "Not a #117 top-1 reprint. No live."
        )
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--live",
        action="store_true",
        help="fetch the Kraken AssetPairs listing and one daily OHLC pull per pair",
    )
    source.add_argument(
        "--candles-dir",
        nargs=2,
        action="append",
        metavar=("VENUE", "DIR"),
        default=None,
        help="score every *.json candle array in DIR as one venue print (repeatable)",
    )
    parser.add_argument(
        "--universe-file",
        type=Path,
        default=None,
        help="JSON list of canonical BASE/USD symbols freezing the candidate listing",
    )
    parser.add_argument("--base-url", default=KRAKEN_REST_BASE_URL)
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=None,
        help=(
            "--live only: reuse <canonical>_1d.json candle arrays found here instead of "
            "re-fetching them, and write newly fetched pairs into it (a 600-pair pull "
            "is resumable across rate limits)"
        ),
    )
    parser.add_argument("--sleep-seconds", type=float, default=1.0)
    parser.add_argument("--max-pairs", type=int, default=0, help="0 = every listed pair")
    parser.add_argument("--max-candles", type=int, default=KRAKEN_PUBLIC_OHLC_MAX_BARS)
    parser.add_argument("--starting-equity", type=float, default=None)
    parser.add_argument("--fee-bps", type=float, default=None)
    parser.add_argument("--slippage-bps", type=float, default=None)
    parser.add_argument("--pilot-fee-bps", type=float, default=PILOT_TIER_TAKER_BPS)
    parser.add_argument("--holdout-fraction", type=float, default=0.20)
    parser.add_argument(
        "--catalog",
        choices=sorted(CATALOGS),
        default="default",
        help="Frozen catalog: default (K=13) or lowturn (longer N; new ids).",
    )
    parser.add_argument("--output-json", type=Path, default=Path("var/ops/xs_topk.json"))
    parser.add_argument(
        "--output-md",
        type=Path,
        default=Path("docs/artifacts/strategy-search/xs-topk.md"),
    )
    parser.add_argument("--stdout-md", action="store_true")
    return parser


def load_universe_file(path: Path) -> tuple[str, ...]:
    payload = json.loads(path.read_text())
    if not isinstance(payload, list) or not all(isinstance(item, str) for item in payload):
        raise TypeError(f"{path}: expected a JSON array of BASE/USD symbols")
    return tuple(sorted({canonical_from_symbol(item) for item in payload}))


def _relabel(candles: tuple[Candle, ...], canonical: str) -> tuple[Candle, ...]:
    return tuple(candle.model_copy(update={"symbol": canonical}) for candle in candles)


def cache_path(cache_dir: Path, canonical: str) -> Path:
    return cache_dir / (canonical.replace("/", "_") + "_1d.json")


def _read_cache(cache_dir: Path | None, canonical: str) -> tuple[Candle, ...] | None:
    if cache_dir is None:
        return None
    path = cache_path(cache_dir, canonical)
    if not path.exists():
        return None
    try:
        candles = load_candles_from_json(path)
    except (TypeError, ValueError, OSError):
        return None
    if not candles or candles[0].interval != "1d":
        return None
    return candles


def _write_cache(cache_dir: Path | None, canonical: str, candles: tuple[Candle, ...]) -> None:
    if cache_dir is None:
        return
    cache_dir.mkdir(parents=True, exist_ok=True)
    payload = [candle.model_dump(mode="json") for candle in candles]
    cache_path(cache_dir, canonical).write_text(json.dumps(payload))


async def pull_live(
    args: argparse.Namespace,
    client: httpx.AsyncClient,
) -> tuple[dict[str, tuple[Candle, ...]], dict[str, object], list[str], list[str], int]:
    """Listing + per-pair daily pull. Returns (histories, listing_meta,
    notes, skip_reasons, names_skipped). Never raises on a per-pair error."""
    notes: list[str] = []
    skip_reasons: list[str] = []
    listing: dict[str, object] = {
        "source": LISTING_SOURCE,
        "fetched_at": None,
        "pairs": [],
    }
    universe = load_universe_file(args.universe_file) if args.universe_file else None
    try:
        pairs = await fetch_kraken_usd_pairs(client)
        listing["fetched_at"] = datetime.now(UTC).isoformat()
        notes.append(f"{LISTING_SOURCE}: ok; {len(pairs)} online USD pairs after exclusions")
    except (httpx.HTTPError, OSError, TypeError, ValueError, RuntimeError) as exc:
        notes.append(f"{LISTING_SOURCE}: skipped ({exc})")
        if universe is None:
            notes.append("universe unavailable; nothing scored; empty is success")
            return {}, listing, notes, skip_reasons, 0
        listing["source"] = f"universe_file:{args.universe_file}"
        pairs = tuple(
            UniversePair(
                pair_key=item.replace("/", ""),
                altname=item.replace("/", ""),
                wsname=item,
                base=item.partition("/")[0],
                canonical=canonical_symbol(item.partition("/")[0]),
            )
            for item in universe
        )
    if universe is not None:
        wanted = set(universe)
        pairs = tuple(pair for pair in pairs if pair.canonical in wanted)
        notes.append(f"universe restricted by {args.universe_file}: {len(pairs)} pairs")
    if args.max_pairs and args.max_pairs > 0:
        pairs = pairs[: args.max_pairs]
        notes.append(f"--max-pairs {args.max_pairs}: {len(pairs)} pairs pulled")
    listing["pairs"] = [{"wsname": pair.wsname, "canonical": pair.canonical} for pair in pairs]
    histories: dict[str, tuple[Candle, ...]] = {}
    skipped = 0
    cached = 0
    fetched = 0
    cache_dir: Path | None = args.cache_dir
    for index, pair in enumerate(pairs):
        candles = _read_cache(cache_dir, pair.canonical)
        if candles is not None:
            cached += 1
        else:
            try:
                candles = await download_candles(
                    pair.wsname, "1d", max_candles=args.max_candles, client=client
                )
            except (httpx.HTTPError, OSError, TypeError, ValueError, RuntimeError) as exc:
                skipped += 1
                skip_reasons.append(f"{pair.canonical}: fetch skipped ({exc})")
                candles = None
                if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 429:
                    await asyncio.sleep(max(args.sleep_seconds, 1.0) * 10)
            else:
                fetched += 1
                _write_cache(cache_dir, pair.canonical, _relabel(candles, pair.canonical))
            if index + 1 < len(pairs) and args.sleep_seconds > 0:
                await asyncio.sleep(args.sleep_seconds)
        if candles is None:
            continue
        if len(candles) < MIN_BARS_TO_LOAD:
            skipped += 1
            skip_reasons.append(
                f"{pair.canonical}: {len(candles)} daily bars < {MIN_BARS_TO_LOAD} (short history)"
            )
        elif all(candle.volume <= 0 for candle in candles):
            skipped += 1
            skip_reasons.append(f"{pair.canonical}: zero volume on every bar")
        else:
            histories[f"{pair.canonical}@1d"] = _relabel(candles, pair.canonical)
    notes.append(
        f"{LIVE_SOURCE}: {len(histories)} names loaded, {skipped} skipped; "
        f"{fetched} pairs fetched now (sleep {args.sleep_seconds:g}s between pairs; "
        f"720-bar public cap)"
        + (f", {cached} pairs reused from --cache-dir {cache_dir}" if cache_dir else "")
    )
    return histories, listing, notes, skip_reasons, skipped


def load_candles_dir(
    directory: Path, *, universe: tuple[str, ...] | None
) -> tuple[dict[str, tuple[Candle, ...]], list[str], int]:
    histories: dict[str, tuple[Candle, ...]] = {}
    skip_reasons: list[str] = []
    skipped = 0
    wanted = set(universe) if universe is not None else None
    for path in sorted(directory.glob("*.json")):
        # Archive downloads (#147) write <out>.report.json sidecars next to the
        # candle arrays; those are headers, not candle series — skip them.
        if path.name.endswith(".report.json"):
            continue
        try:
            candles = load_candles_from_json(path)
        except (TypeError, ValueError, OSError) as exc:
            skipped += 1
            skip_reasons.append(f"{path.name}: unreadable ({exc})")
            continue
        if not candles:
            skipped += 1
            skip_reasons.append(f"{path.name}: empty")
            continue
        if candles[0].interval != "1d":
            skipped += 1
            skip_reasons.append(f"{path.name}: interval {candles[0].interval} != 1d")
            continue
        try:
            canonical = canonical_from_symbol(candles[0].symbol)
        except ValueError as exc:
            skipped += 1
            skip_reasons.append(f"{path.name}: {exc}")
            continue
        if wanted is not None and canonical not in wanted:
            continue
        if len(candles) < MIN_BARS_TO_LOAD:
            skipped += 1
            skip_reasons.append(
                f"{canonical}: {len(candles)} daily bars < {MIN_BARS_TO_LOAD} (short history)"
            )
            continue
        histories[f"{canonical}@1d"] = _relabel(candles, canonical)
    return histories, skip_reasons, skipped


def run(
    args: argparse.Namespace,
    settings: Settings | None = None,
    *,
    client: httpx.AsyncClient | None = None,
) -> tuple[Path, Path]:
    settings = settings or Settings()
    fee_bps = (
        args.fee_bps
        if args.fee_bps is not None
        else research_fee_bps(settings.pretrade_fee_bps, settings.paper_fee_bps)
    )
    slippage_bps = (
        args.slippage_bps if args.slippage_bps is not None else settings.pretrade_slippage_bps
    )
    starting_equity = args.starting_equity or settings.paper_starting_nav_usd
    notes: list[str] = []
    prints: list[PrintResult] = []
    listing_fetched_at: str | None = None
    listing_source: str | None = None
    listing_size = 0
    universe = load_universe_file(args.universe_file) if args.universe_file else None

    if args.live:

        async def _pull() -> tuple[
            dict[str, tuple[Candle, ...]], dict[str, object], list[str], list[str], int
        ]:
            if client is not None:
                return await pull_live(args, client)
            async with httpx.AsyncClient(base_url=args.base_url, timeout=30) as owned:
                return await pull_live(args, owned)

        histories, listing, extra, skip_reasons, skipped = asyncio.run(_pull())
        notes.extend(extra)
        fetched = listing.get("fetched_at")
        listing_fetched_at = fetched if isinstance(fetched, str) else None
        source = listing.get("source")
        listing_source = source if isinstance(source, str) else None
        pairs = listing.get("pairs")
        listing_size = len(pairs) if isinstance(pairs, list) else 0
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        (args.output_json.parent / UNIVERSE_LISTING_FILENAME).write_text(
            json.dumps(listing, indent=2) + "\n"
        )
        prints.append(
            score_print(
                LIVE_VENUE,
                histories,
                source=LIVE_SOURCE,
                fee_bps=fee_bps,
                slippage_bps=slippage_bps,
                pilot_fee_bps=args.pilot_fee_bps,
                starting_equity=starting_equity,
                holdout_fraction=args.holdout_fraction,
                skip_reasons=skip_reasons,
                names_skipped=skipped,
                catalog=resolve_catalog(args.catalog),
            )
        )
    else:
        listing_source = (
            f"universe_file:{args.universe_file}" if args.universe_file else "candles_dir_listing"
        )
        listing_size = len(universe) if universe is not None else 0
        for venue, directory in args.candles_dir:
            histories, skip_reasons, skipped = load_candles_dir(Path(directory), universe=universe)
            notes.append(
                f"{venue}: loaded {len(histories)} daily names from {directory}, skipped {skipped}"
            )
            if universe is None:
                listing_size = max(listing_size, len(histories) + skipped)
            prints.append(
                score_print(
                    venue,
                    histories,
                    source=f"candles_dir:{directory}",
                    fee_bps=fee_bps,
                    slippage_bps=slippage_bps,
                    pilot_fee_bps=args.pilot_fee_bps,
                    starting_equity=starting_equity,
                    holdout_fraction=args.holdout_fraction,
                    skip_reasons=skip_reasons,
                    names_skipped=skipped,
                    catalog=resolve_catalog(args.catalog),
                )
            )

    report = build_xs_topk_report(
        prints,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
        pilot_fee_bps=args.pilot_fee_bps,
        starting_equity=starting_equity,
        holdout_fraction=args.holdout_fraction,
        universe_listing_fetched_at=listing_fetched_at,
        universe_listing_source=listing_source,
        universe_listing_size=listing_size,
        data_notes=notes,
        catalog_name=args.catalog,
        catalog=resolve_catalog(args.catalog),
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(report.model_dump_json(indent=2) + "\n")
    markdown = render_xs_topk_markdown(report)
    args.output_md.write_text(markdown)
    if args.stdout_md:
        print(markdown)
    else:
        status = "DUAL-PRINT PASSER" if report.any_dual_print_passer else "NO DUAL-PRINT PASSER"
        print(
            f"{status}: wrote {args.output_json} and {args.output_md} "
            f"(selected={report.selected_candidate_id or 'none'}; "
            f"dual_print_passers={len(report.dual_print_passer_ids)}; "
            f"single_print_passers={len(report.single_print_passer_ids)}; "
            f"prints={[item.meta.venue + ':' + item.meta.status for item in report.prints]}; "
            f"ranking_key={report.ranking_key}; "
            f"paper_path_ready={report.paper_path_ready}; "
            f"keep_flag_false={report.keep_flag_false}). "
            "PAPER_PROMOTE_* flags are unchanged."
        )
    return args.output_json, args.output_md


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    run(args)


if __name__ == "__main__":
    main()
