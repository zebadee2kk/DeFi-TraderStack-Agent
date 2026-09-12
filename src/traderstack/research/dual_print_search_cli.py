"""`traderstack-dual-print-search`: Kraken + Binance.US harder-gates bar.

Scores the frozen dual-print catalog on the Kraken primary 720-bar daily
window and the #102 Binance.US older-720. A name must combined-pass
**both** prints. Ranking is Kraken mean holdout excess among dual-print
passers. Never flips ``PAPER_PROMOTE_*``. An empty passer set is success.
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
from traderstack.research.daily_robustness_cli import _load_histories
from traderstack.research.dual_print_search import (
    RANKING_KEY,
    render_dual_print_markdown,
    run_dual_print_search,
)
from traderstack.research.miles_candidates import SearchCandidate
from traderstack.research.miles_search import research_fee_bps
from traderstack.research.second_print import SECOND_PRINT_BARS, primary_first_opened_at


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Dual-print daily search: expanded catalog must clear Kraken "
            "primary harder combined gates (#96+A+B+C) AND the #102 "
            "Binance.US older-720 combined gates. Ranking key (frozen): "
            f"{RANKING_KEY}. Does not flip PAPER_PROMOTE_* flags. "
            "An empty dual-print set is success."
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
            "fetch Kraken public OHLC daily (720-bar cap) and Binance "
            "Spot daily BTCUSDT/ETHUSDT (api.binance.com, then .us)"
        ),
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
        help="fetch/score Binance Spot daily (default on; --no-binance is success)",
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
        "--output-json",
        type=Path,
        default=Path("var/ops/dual_print_search.json"),
    )
    parser.add_argument(
        "--output-md",
        type=Path,
        default=Path("docs/artifacts/strategy-search/dual-print-search.md"),
    )
    parser.add_argument("--stdout-md", action="store_true")
    return parser


def _history_key(candles: tuple[Candle, ...]) -> str:
    return f"{candles[0].symbol}@{candles[0].interval}"


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
    end_before: datetime,
) -> tuple[dict[str, tuple[Candle, ...]], str | None, list[str]]:
    try:
        return asyncio.run(
            download_binance_spot_histories(
                DEFAULT_BINANCE_SYMBOLS,
                end_before=end_before,
                max_candles=SECOND_PRINT_BARS,
            )
        )
    except (OSError, TypeError, ValueError, httpx.HTTPError) as exc:
        return {}, None, [f"Binance Spot daily skipped: {exc}"]


def run(
    args: argparse.Namespace,
    settings: Settings | None = None,
    *,
    candidates: tuple[SearchCandidate, ...] | None = None,
) -> tuple[Path, Path]:
    settings = settings or Settings()
    if args.live:
        args.live_kraken = True
        args.yahoo = False
        if args.symbol is None:
            args.symbol = ["BTC/USD", "ETH/USD"]
    else:
        args.live_kraken = False
        args.yahoo = False
    kraken_histories, notes = _load_histories(args)
    primary_first, source = primary_first_opened_at(kraken_histories)
    notes.append(f"primary first bar {primary_first.isoformat()} (source={source})")

    binance_histories: dict[str, tuple[Candle, ...]] = {}
    binance_source: str | None = None
    if args.binance_candles:
        loaded, extra = _load_binance_files(args.binance_candles)
        binance_histories.update(loaded)
        notes.extend(extra)
        binance_source = "binance_json"
    elif args.binance and args.live:
        fetched, binance_source, extra = _load_live_binance(primary_first)
        binance_histories.update(fetched)
        notes.extend(extra)
    elif not args.binance:
        notes.append("Binance Spot daily skipped (--no-binance); empty print is success")
    else:
        notes.append(
            "Binance Spot daily not fetched (offline --candles without "
            "--binance-candles); empty print is success"
        )

    fee_bps = (
        args.fee_bps
        if args.fee_bps is not None
        else research_fee_bps(settings.pretrade_fee_bps, settings.paper_fee_bps)
    )
    slippage_bps = (
        args.slippage_bps if args.slippage_bps is not None else settings.pretrade_slippage_bps
    )
    report = run_dual_print_search(
        kraken_histories,
        binance_histories,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
        starting_equity=args.starting_equity or settings.paper_starting_nav_usd,
        train_size=args.train_size,
        test_size=args.test_size,
        step_size=args.step_size,
        holdout_fraction=args.holdout_fraction,
        min_trades=args.min_trades,
        candidates=candidates,
        binance_source=binance_source,
        data_notes=notes,
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(report.model_dump_json(indent=2) + "\n")
    markdown = render_dual_print_markdown(report)
    args.output_md.write_text(markdown)
    if args.stdout_md:
        print(markdown)
    else:
        status = "DUAL-PRINT PASSER" if report.any_dual_print_passer else "NO DUAL-PRINT PASSER"
        print(
            f"{status}: wrote {args.output_json} and {args.output_md} "
            f"(selected={report.selected_candidate_id or 'none'}; "
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
