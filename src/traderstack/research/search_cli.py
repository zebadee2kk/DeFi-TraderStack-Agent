"""`traderstack-strategy-search`: offline candidate search + ranked report.

Loads Kraken Spot OHLC the same way as `traderstack-research` (JSON file or
`KrakenCandleProvider`), scores the pre-registered catalog under paper/pretrade
fees, and writes JSON + Markdown. It never enables paper promotion.
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
from traderstack.research.cli import load_candles_from_json
from traderstack.research.download_candles import download_candles
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


async def _load_from_kraken(symbol: str, resolution: str, count: int) -> tuple[Candle, ...]:
    """Spot OHLC from the paper candle provider, else the public REST downloader.

    Paper uses `KrakenCandleProvider` (futures-charts spot path). Research
    already pages `GET /0/public/OHLC` via `download_candles`. Live search
    tries the paper adapter first so the series matches the runtime when
    that endpoint is up, and falls back to the verified public Spot OHLC
    path (same venue, committed bars only) when it is not.
    """
    try:
        candles = await KrakenCandleProvider().fetch(symbol, resolution, count=count)
    except (httpx.HTTPError, OSError, TypeError, ValueError):
        candles = ()
    if candles:
        return candles
    return await download_candles(symbol, resolution, max_candles=count)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Score a small pre-registered catalog (MA cross, momentum, "
            "mean-reversion; optional liquidation / cross-venue series) with "
            "fee-aware walk-forward + holdout. Writes a ranked report. "
            "Does not enable paper promotion."
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
    parser.add_argument("--count", type=int, default=720)
    parser.add_argument("--starting-equity", type=float, default=None)
    parser.add_argument("--fee-bps", type=float, default=None, help="override conservative fee")
    parser.add_argument("--slippage-bps", type=float, default=None)
    parser.add_argument("--warmup", type=int, default=31)
    parser.add_argument("--train-size", type=int, default=180)
    parser.add_argument("--test-size", type=int, default=60)
    parser.add_argument("--step-size", type=int, default=60)
    parser.add_argument("--holdout-fraction", type=float, default=0.20)
    parser.add_argument("--min-trades", type=int, default=None)
    parser.add_argument("--min-wf-excess", type=float, default=None)
    parser.add_argument(
        "--no-holdout-confirmation",
        action="store_true",
        help="rank still ignores holdout; promotion would not require holdout > floor",
    )
    parser.add_argument(
        "--liquidation-z",
        type=Path,
        default=None,
        help="optional aligned [{opened_at, value}] series; omitted = family skipped",
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


def _load_histories(args: argparse.Namespace) -> dict[str, tuple[Candle, ...]]:
    histories: dict[str, tuple[Candle, ...]] = {}
    if args.candles:
        for path in args.candles:
            candles = load_candles_from_json(path)
            if not candles:
                raise ValueError(f"{path}: no candles")
            histories[candles[0].symbol] = candles
        return histories
    for symbol in args.symbol:
        candles = asyncio.run(_load_from_kraken(symbol, args.resolution, args.count))
        if not candles:
            raise ValueError(f"{symbol}: Kraken returned no candles")
        histories[candles[0].symbol] = candles
    return histories


def run(args: argparse.Namespace, settings: Settings | None = None) -> tuple[Path, Path]:
    settings = settings or Settings()
    histories = _load_histories(args)
    fee_bps = (
        args.fee_bps
        if args.fee_bps is not None
        else research_fee_bps(settings.pretrade_fee_bps, settings.paper_fee_bps)
    )
    slippage_bps = (
        args.slippage_bps if args.slippage_bps is not None else settings.pretrade_slippage_bps
    )
    report = run_search(
        histories,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
        starting_equity=args.starting_equity or settings.paper_starting_nav_usd,
        warmup=args.warmup,
        train_size=args.train_size,
        test_size=args.test_size,
        step_size=args.step_size,
        holdout_fraction=args.holdout_fraction,
        min_trades=(
            args.min_trades if args.min_trades is not None else settings.paper_search_min_trades
        ),
        min_wf_excess_return=(
            args.min_wf_excess
            if args.min_wf_excess is not None
            else settings.paper_search_min_wf_excess_return
        ),
        require_holdout_confirmation=not args.no_holdout_confirmation,
        liquidation=_parse_feature_series(args.liquidation_z) if args.liquidation_z else None,
        cross_venue=_parse_feature_series(args.cross_venue_z) if args.cross_venue_z else None,
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
