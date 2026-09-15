"""`traderstack-strategy-search`: offline candidate search + ranked report.

Loads Kraken history (charts-spot PI_* for 90–180d when available, else the
720-bar public Spot OHLC), optionally fetches free public funding/OI series,
scores the expanded pre-registered catalog under paper/pretrade fees, and
writes JSON + Markdown. It never enables paper promotion.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime
from pathlib import Path

import httpx

from traderstack.candles import Candle
from traderstack.config import Settings
from traderstack.market.kraken_candles import KrakenCandleProvider
from traderstack.research.candidates import expanded_price_candidates
from traderstack.research.cli import load_candles_from_json
from traderstack.research.download_candles import download_candles
from traderstack.research.edge_series import fetch_edge_bundle
from traderstack.research.kraken_charts import (
    describe_ohlc_cap,
    download_kraken_charts,
)
from traderstack.research.search import (
    render_search_markdown,
    research_fee_bps,
    run_search,
)


def _parse_feature_series(path: Path) -> tuple[tuple[datetime, float], ...]:
    payload = json.loads(path.read_text())
    if not isinstance(payload, list):
        raise TypeError(f"{path}: expected a JSON array of {{opened_at, value}}")
    rows: list[tuple[datetime, float]] = []
    for item in payload:
        if not isinstance(item, dict) or "opened_at" not in item or "value" not in item:
            raise TypeError(f"{path}: each row needs opened_at and value")
        rows.append((datetime.fromisoformat(str(item["opened_at"])), float(item["value"])))
    rows.sort(key=lambda pair: pair[0])
    return tuple(rows)


def _history_key(candles: tuple[Candle, ...]) -> str:
    return f"{candles[0].symbol}:{candles[0].interval}"


def _note_for(candles: tuple[Candle, ...], source: str, extra: str = "") -> dict[str, str]:
    first = candles[0].opened_at.isoformat() if candles else ""
    last = candles[-1].opened_at.isoformat() if candles else ""
    span_days = ""
    if candles:
        span_days = f"{(candles[-1].opened_at - candles[0].opened_at).total_seconds() / 86400:.1f}"
    note = extra
    if candles and all(c.volume == 0 for c in candles[: min(20, len(candles))]):
        note = (note + " " if note else "") + "volume is zero on this path"
    return {
        "symbol": candles[0].symbol if candles else "?",
        "interval": candles[0].interval if candles else "",
        "source": source,
        "candles": str(len(candles)),
        "first": first,
        "last": last,
        "span_days": span_days,
        "note": note,
    }


async def _load_one(
    symbol: str, resolution: str, count: int, source: str
) -> tuple[tuple[Candle, ...], dict[str, str]]:
    """Charts-spot first for long windows; public OHLC is the 720-bar cap."""
    if source in {"auto", "charts"}:
        try:
            candles = await download_kraken_charts(symbol, resolution, count=count)
        except (httpx.HTTPError, OSError, TypeError, ValueError):
            candles = ()
        if candles:
            extra = (
                "Kraken futures charts spot PI_* (research-only). "
                "Closes can differ a few bps from /0/public/OHLC."
            )
            return candles, _note_for(candles, "kraken_charts_spot", extra)
        if source == "charts":
            raise ValueError(f"{symbol}: Kraken charts-spot returned no candles")

    try:
        candles = await KrakenCandleProvider().fetch(symbol, resolution, count=count)
    except (httpx.HTTPError, OSError, TypeError, ValueError):
        candles = ()
    if candles:
        extra = ""
        if count > len(candles):
            extra = describe_ohlc_cap(interval=resolution, requested=count, received=len(candles))
        return candles, _note_for(candles, "kraken_candle_provider", extra)

    candles = await download_candles(symbol, resolution, max_candles=count)
    extra = ""
    if count > len(candles):
        extra = describe_ohlc_cap(interval=resolution, requested=count, received=len(candles))
    return candles, _note_for(candles, "kraken_public_ohlc", extra)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Score the expanded pre-registered catalog (MA / momentum / "
            "mean-reversion + vol-regime filters; optional funding / OI / "
            "liquidation series) with fee-aware walk-forward + holdout. "
            "Writes a ranked report. Does not enable paper promotion."
        )
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--candles",
        type=Path,
        action="append",
        help="JSON candle array (repeat per asset). Symbol is read from the file.",
    )
    source.add_argument(
        "--symbol",
        action="append",
        help="fetch live from Kraken (repeat; e.g. BTC/USD ETH/USD SOL/USD)",
    )
    parser.add_argument("--resolution", default="1h")
    parser.add_argument(
        "--also-resolution",
        action="append",
        default=[],
        help="extra interval to fetch (e.g. 4h). Repeatable. Live --symbol only.",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=4320,
        help="committed bars to request (charts-spot honours ~180d 1h; public OHLC caps at 720)",
    )
    parser.add_argument(
        "--source",
        choices=("auto", "charts", "ohlc"),
        default="auto",
        help="auto tries charts-spot PI_* then public OHLC",
    )
    parser.add_argument("--starting-equity", type=float, default=None)
    parser.add_argument("--fee-bps", type=float, default=None, help="override conservative fee")
    parser.add_argument("--slippage-bps", type=float, default=None)
    parser.add_argument("--warmup", type=int, default=31)
    parser.add_argument("--train-size", type=int, default=None)
    parser.add_argument("--test-size", type=int, default=None)
    parser.add_argument("--step-size", type=int, default=None)
    parser.add_argument("--holdout-fraction", type=float, default=0.20)
    parser.add_argument("--min-trades", type=int, default=None)
    parser.add_argument("--min-wf-excess", type=float, default=None)
    parser.add_argument("--min-wf-total", type=float, default=None)
    parser.add_argument(
        "--no-wf-total-confirmation",
        action="store_true",
        help="do not require WF mean total return > floor (not the default)",
    )
    parser.add_argument(
        "--no-holdout-confirmation",
        action="store_true",
        help="rank still ignores holdout; promotion would not require holdout > floor",
    )
    parser.add_argument(
        "--expanded-catalog",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="include vol-regime-filtered price voters (default on)",
    )
    parser.add_argument(
        "--fetch-edge-series",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="download public funding/OI (and probe liquidations). Default on for --symbol",
    )
    parser.add_argument(
        "--liquidation-z",
        type=Path,
        default=None,
        help="optional aligned [{opened_at, value}] series; omitted = family skipped",
    )
    parser.add_argument(
        "--funding-z",
        type=Path,
        default=None,
        help="optional aligned [{opened_at, value}] funding series",
    )
    parser.add_argument(
        "--oi-z",
        type=Path,
        default=None,
        help="optional aligned [{opened_at, value}] open-interest series",
    )
    parser.add_argument(
        "--cross-venue-z",
        type=Path,
        default=None,
        help="optional aligned [{opened_at, value}] series; omitted = family skipped",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=Path("var/ops/strategy_search_report.json"),
    )
    parser.add_argument(
        "--output-md",
        type=Path,
        default=Path("var/ops/strategy_search_report.md"),
    )
    parser.add_argument(
        "--stdout-md",
        action="store_true",
        help="also print the markdown report",
    )
    return parser


def _default_windows(count: int) -> tuple[int, int, int]:
    """Longer folds on ~180d 1h; keep the PR #89 180/60/60 on short windows."""
    if count >= 2000:
        return 360, 168, 168
    return 180, 60, 60


def _load_histories(
    args: argparse.Namespace,
) -> tuple[dict[str, tuple[Candle, ...]], list[dict[str, str]]]:
    histories: dict[str, tuple[Candle, ...]] = {}
    notes: list[dict[str, str]] = []
    if args.candles:
        for path in args.candles:
            candles = load_candles_from_json(path)
            if not candles:
                raise ValueError(f"{path}: no candles")
            histories[_history_key(candles)] = candles
            notes.append(_note_for(candles, f"json:{path}"))
        return histories, notes

    resolutions = [args.resolution, *list(args.also_resolution)]
    seen: set[str] = set()
    for resolution in resolutions:
        if resolution in seen:
            continue
        seen.add(resolution)
        for symbol in args.symbol:
            candles, note = asyncio.run(_load_one(symbol, resolution, args.count, args.source))
            if not candles:
                raise ValueError(f"{symbol} {resolution}: Kraken returned no candles")
            histories[_history_key(candles)] = candles
            notes.append(note)
    return histories, notes


def run(args: argparse.Namespace, settings: Settings | None = None) -> tuple[Path, Path]:
    settings = settings or Settings()
    histories, history_notes = _load_histories(args)
    fee_bps = (
        args.fee_bps
        if args.fee_bps is not None
        else research_fee_bps(settings.pretrade_fee_bps, settings.paper_fee_bps)
    )
    slippage_bps = (
        args.slippage_bps if args.slippage_bps is not None else settings.pretrade_slippage_bps
    )
    train_default, test_default, step_default = _default_windows(args.count)
    fetch_edge = args.fetch_edge_series if args.fetch_edge_series is not None else bool(args.symbol)

    funding = _parse_feature_series(args.funding_z) if args.funding_z else None
    open_interest = _parse_feature_series(args.oi_z) if args.oi_z else None
    liquidation = _parse_feature_series(args.liquidation_z) if args.liquidation_z else None
    funding_by_symbol = None
    oi_by_symbol = None
    liq_by_symbol = None
    edge_notes: list[dict[str, str]] = []
    if fetch_edge and args.symbol:
        bundle = asyncio.run(fetch_edge_bundle(tuple(args.symbol)))
        edge_notes = [note.as_note() for note in bundle.notes]
        if bundle.funding:
            funding_by_symbol = bundle.funding
        if bundle.open_interest:
            oi_by_symbol = bundle.open_interest
        if bundle.liquidation:
            liq_by_symbol = bundle.liquidation

    report = run_search(
        histories,
        # --- era prints / DSR / PBO (#135) ---
        # This CLI is the report consumer, so it opts in; the loop callers
        # (funding_carry, liq_regime_search) leave it off.
        include_selection_evidence=True,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
        starting_equity=args.starting_equity or settings.paper_starting_nav_usd,
        warmup=args.warmup,
        train_size=args.train_size if args.train_size is not None else train_default,
        test_size=args.test_size if args.test_size is not None else test_default,
        step_size=args.step_size if args.step_size is not None else step_default,
        holdout_fraction=args.holdout_fraction,
        min_trades=(
            args.min_trades if args.min_trades is not None else settings.paper_search_min_trades
        ),
        min_wf_excess_return=(
            args.min_wf_excess
            if args.min_wf_excess is not None
            else settings.paper_search_min_wf_excess_return
        ),
        min_wf_total_return=(
            args.min_wf_total
            if args.min_wf_total is not None
            else settings.paper_search_min_wf_total_return
        ),
        require_wf_total_return=not args.no_wf_total_confirmation,
        require_holdout_confirmation=not args.no_holdout_confirmation,
        candidates=expanded_price_candidates() if args.expanded_catalog else None,
        liquidation=liquidation,
        liquidation_by_symbol=liq_by_symbol,
        funding=funding,
        funding_by_symbol=funding_by_symbol,
        open_interest=open_interest,
        open_interest_by_symbol=oi_by_symbol,
        cross_venue=_parse_feature_series(args.cross_venue_z) if args.cross_venue_z else None,
        history_notes=history_notes,
        edge_notes=edge_notes,
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(report.model_dump_json(indent=2) + "\n")
    markdown = render_search_markdown(report)
    args.output_md.write_text(markdown)
    if args.stdout_md:
        print(markdown)
    else:
        status = "PROMOTED" if report.any_promoted else "NO EDGE"
        print(
            f"{status}: wrote {args.output_json} and {args.output_md} "
            f"(selected={report.selected_candidate_id or 'none'}; "
            f"promoted={', '.join(report.promoted_candidate_ids) or 'none'}). "
            "PAPER_PROMOTE_SEARCHED_STRATEGIES is unchanged."
        )
    return args.output_json, args.output_md


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    run(args)


if __name__ == "__main__":
    main()
