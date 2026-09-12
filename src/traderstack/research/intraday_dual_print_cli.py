"""`traderstack-intraday-dual-print`: 4h/1h Kraken + Binance.US harder gates.

Scores the frozen non-EMA catalog on Kraken public Spot (default 4h,
720-bar cap) and the #102-style Binance.US older-720 of the same
interval. A name must combined-pass **both** prints. Ranking is Kraken
mean holdout excess among dual-print passers. Funding/OI instantiate
only when an aligned series is fetched. Never flips ``PAPER_PROMOTE_*``.
An empty passer set is success.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime
from pathlib import Path

import httpx

from traderstack.candles import Candle
from traderstack.config import Settings
from traderstack.research.binance_spot import (
    DEFAULT_BINANCE_SYMBOLS,
    download_binance_spot_histories,
)
from traderstack.research.cli import load_candles_from_json
from traderstack.research.daily_robustness import KRAKEN_PUBLIC_OHLC_MAX_BARS
from traderstack.research.download_candles import download_spot_histories
from traderstack.research.edge_series import fetch_edge_bundle
from traderstack.research.intraday_candidates import ALLOWED_INTERVALS, DEFAULT_INTERVAL
from traderstack.research.intraday_dual_print import (
    RANKING_KEY,
    render_intraday_dual_print_markdown,
    run_intraday_dual_print,
)
from traderstack.research.miles_candidates import SearchCandidate
from traderstack.research.miles_search import research_fee_bps
from traderstack.research.search_cli import _parse_feature_series
from traderstack.research.second_print import SECOND_PRINT_BARS, primary_first_opened_at

DEFAULT_SYMBOLS = ("BTC/USD", "ETH/USD")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Intraday (4h/1h) dual-print search: frozen non-EMA catalog "
            "must clear Kraken primary harder combined gates (#96+A+B+C) "
            "AND the #102-style Binance.US older-720 of the same interval. "
            f"Ranking key (frozen): {RANKING_KEY}. Does not flip "
            "PAPER_PROMOTE_* flags. An empty dual-print set is success."
        )
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--candles",
        type=Path,
        action="append",
        help="Kraken JSON candle array (repeat per asset). Symbol+interval from file.",
    )
    source.add_argument(
        "--live",
        action="store_true",
        help=(
            "fetch Kraken public Spot OHLC (720-bar cap) and Binance "
            "Spot BTCUSDT/ETHUSDT (api.binance.com, then .us) at --interval"
        ),
    )
    parser.add_argument(
        "--interval",
        choices=ALLOWED_INTERVALS,
        default=DEFAULT_INTERVAL,
        help="promotion interval (default 4h; 1h is the alternate)",
    )
    parser.add_argument(
        "--binance-candles",
        type=Path,
        action="append",
        default=None,
        help="offline Binance JSON candle array (repeat; BTCUSDT/ETHUSDT)",
    )
    parser.add_argument(
        "--binance",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="fetch/score Binance Spot (default on; --no-binance is success)",
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
    parser.add_argument("--train-size", type=int, default=180)
    parser.add_argument("--test-size", type=int, default=60)
    parser.add_argument("--step-size", type=int, default=60)
    parser.add_argument("--holdout-fraction", type=float, default=0.20)
    parser.add_argument("--min-trades", type=int, default=3)
    parser.add_argument(
        "--fetch-edge-series",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="download public funding/OI (default on for --live). Skip-not-invent.",
    )
    parser.add_argument(
        "--funding-z",
        type=Path,
        default=None,
        help="optional aligned [{opened_at, value}] series; omitted = family skipped",
    )
    parser.add_argument("--oi-z", type=Path, default=None)
    parser.add_argument(
        "--output-json",
        type=Path,
        default=Path("var/ops/intraday_dual_print.json"),
    )
    parser.add_argument(
        "--output-md",
        type=Path,
        default=Path("docs/artifacts/strategy-search/intraday-dual-print.md"),
    )
    parser.add_argument("--stdout-md", action="store_true")
    return parser


def _history_key(candles: tuple[Candle, ...]) -> str:
    return f"{candles[0].symbol}@{candles[0].interval}"


def _load_kraken_files(
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


def _load_binance_files(paths: list[Path]) -> tuple[dict[str, tuple[Candle, ...]], list[str]]:
    histories: dict[str, tuple[Candle, ...]] = {}
    notes: list[str] = []
    for path in paths:
        candles = load_candles_from_json(path)
        if not candles:
            raise ValueError(f"{path}: no candles")
        histories[_history_key(candles)] = candles
        notes.append(
            f"loaded {len(candles)} {candles[0].interval} bars for "
            f"{candles[0].symbol} from {path} (binance_json; non-Kraken)"
        )
    return histories, notes


def _load_live_binance(
    end_before: datetime, *, interval: str
) -> tuple[dict[str, tuple[Candle, ...]], str | None, list[str]]:
    try:
        return asyncio.run(
            download_binance_spot_histories(
                DEFAULT_BINANCE_SYMBOLS,
                end_before=end_before,
                max_candles=SECOND_PRINT_BARS,
                interval=interval,
            )
        )
    except (OSError, TypeError, ValueError, httpx.HTTPError) as exc:
        return {}, None, [f"Binance Spot {interval} skipped: {exc}"]


def run(
    args: argparse.Namespace,
    settings: Settings | None = None,
    *,
    candidates: tuple[SearchCandidate, ...] | None = None,
) -> tuple[Path, Path]:
    settings = settings or Settings()
    interval: str = args.interval
    notes: list[str] = []
    if args.live:
        symbols = tuple(args.symbol) if args.symbol else DEFAULT_SYMBOLS
        kraken_histories, extra = _load_live_kraken(
            symbols, interval=interval, max_candles=args.max_candles
        )
        notes.extend(extra)
    else:
        kraken_histories, extra = _load_kraken_files(args.candles, interval=interval)
        notes.extend(extra)
    if not kraken_histories:
        raise ValueError(f"no Kraken {interval} histories loaded")
    primary_first, source = primary_first_opened_at(kraken_histories, interval=interval)
    notes.append(f"primary first bar {primary_first.isoformat()} (source={source})")

    binance_histories: dict[str, tuple[Candle, ...]] = {}
    binance_source: str | None = None
    if args.binance_candles:
        loaded, extra = _load_binance_files(args.binance_candles)
        binance_histories.update(loaded)
        notes.extend(extra)
        binance_source = "binance_json"
    elif args.binance and args.live:
        fetched, binance_source, extra = _load_live_binance(primary_first, interval=interval)
        binance_histories.update(fetched)
        notes.extend(extra)
    elif not args.binance:
        notes.append(f"Binance Spot {interval} skipped (--no-binance); empty print is success")
    else:
        notes.append(
            f"Binance Spot {interval} not fetched (offline --candles without "
            "--binance-candles); empty print is success"
        )

    funding = _parse_feature_series(args.funding_z) if args.funding_z else None
    open_interest = _parse_feature_series(args.oi_z) if args.oi_z else None
    funding_by_symbol = {"BTC/USD": funding, "ETH/USD": funding} if funding else None
    oi_by_symbol = {"BTC/USD": open_interest, "ETH/USD": open_interest} if open_interest else None

    fetch_edge = args.fetch_edge_series if args.fetch_edge_series is not None else bool(args.live)
    symbols = tuple(args.symbol) if args.symbol else DEFAULT_SYMBOLS
    if fetch_edge:
        bundle = asyncio.run(fetch_edge_bundle(symbols))
        for note in bundle.notes:
            notes.append(note.as_note()["name"] + ": " + note.status + " — " + note.reason)
        if bundle.funding:
            funding_by_symbol = bundle.funding
        if bundle.open_interest:
            oi_by_symbol = bundle.open_interest

    fee_bps = (
        args.fee_bps
        if args.fee_bps is not None
        else research_fee_bps(settings.pretrade_fee_bps, settings.paper_fee_bps)
    )
    slippage_bps = (
        args.slippage_bps if args.slippage_bps is not None else settings.pretrade_slippage_bps
    )
    report = run_intraday_dual_print(
        kraken_histories,
        binance_histories,
        interval=interval,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
        starting_equity=args.starting_equity or settings.paper_starting_nav_usd,
        train_size=args.train_size,
        test_size=args.test_size,
        step_size=args.step_size,
        holdout_fraction=args.holdout_fraction,
        min_trades=args.min_trades,
        candidates=candidates,
        funding_by_symbol=funding_by_symbol,
        open_interest_by_symbol=oi_by_symbol,
        binance_source=binance_source,
        data_notes=notes,
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(report.model_dump_json(indent=2) + "\n")
    markdown = render_intraday_dual_print_markdown(report)
    args.output_md.write_text(markdown)
    if args.stdout_md:
        print(markdown)
    else:
        status = "DUAL-PRINT PASSER" if report.any_dual_print_passer else "NO DUAL-PRINT PASSER"
        print(
            f"{status}: wrote {args.output_json} and {args.output_md} "
            f"(interval={report.interval}; "
            f"selected={report.selected_candidate_id or 'none'}; "
            f"dual_print_passers={len(report.dual_print_passer_ids)}; "
            f"kraken_combined={len(report.kraken_combined_passer_ids)}; "
            f"binance_combined={len(report.binance_combined_passer_ids)}; "
            f"ranking_key={report.ranking_key}; "
            f"keep_flag_false={report.keep_flag_false}). "
            "PAPER_PROMOTE_* flags are unchanged."
        )
    return args.output_json, args.output_md


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    run(args)


if __name__ == "__main__":
    main()
