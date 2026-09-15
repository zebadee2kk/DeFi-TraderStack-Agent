"""`traderstack-daily-robustness`: daily catalog + balanced-holdout bar.

Loads the longest Kraken public Spot daily OHLC the API will return (720
committed bars, ~2y), optionally a Yahoo Finance daily A/B (non-Kraken),
scores the pre-registered balanced-holdout catalog, and writes JSON +
Markdown. Promotion requires BTC **and** ETH walk-forward total > 0
**and** BTC **and** ETH holdout excess > 0. It never enables
``PAPER_PROMOTE_EMA_9_21`` or ``PAPER_PROMOTE_SEARCHED_STRATEGIES``.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

import httpx

from traderstack.candles import Candle
from traderstack.config import Settings
from traderstack.research.cli import load_candles_from_json
from traderstack.research.daily_robustness import (
    KRAKEN_DAILY_CAP_NOTE,
    KRAKEN_PUBLIC_OHLC_MAX_BARS,
    render_daily_robustness_markdown,
    run_daily_robustness,
)
from traderstack.research.download_candles import download_spot_histories
from traderstack.research.miles_search import research_fee_bps
from traderstack.research.yahoo_daily import YAHOO_SOURCE, download_yahoo_histories

DEFAULT_SYMBOLS = ("BTC/USD", "ETH/USD", "SOL/USD")
DEFAULT_YAHOO_TICKERS = ("BTC-USD", "ETH-USD")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Score the pre-registered balanced-holdout daily catalog (EMA "
            "9/21, 12/26, 20/50, 50/200, ADX gates, dual-mom grid, "
            "buy-the-dip, MA risk-off, optional GARCH size) with fee-aware "
            "walk-forward + holdout. Promote only if Kraken BTC and ETH both "
            "have WF total > 0 AND both have holdout excess > 0. Writes a "
            "ranked report. Does not enable PAPER_PROMOTE_* flags."
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
        "--live-kraken",
        action="store_true",
        help=(
            "fetch BTC/ETH/SOL daily from Kraken public OHLC "
            f"(hard cap {KRAKEN_PUBLIC_OHLC_MAX_BARS} bars)"
        ),
    )
    parser.add_argument(
        "--symbol",
        action="append",
        default=None,
        help="override live Kraken symbols (repeat; default BTC/USD ETH/USD SOL/USD)",
    )
    parser.add_argument(
        "--yahoo",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="also fetch Yahoo Finance BTC-USD/ETH-USD daily (non-Kraken A/B)",
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
        "--catalog",
        choices=("balanced", "legacy"),
        default="balanced",
        help="balanced = expanded pre-registered grid; legacy = frozen #95 K=8",
    )
    parser.add_argument(
        "--balanced-holdout",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="require BTC and ETH holdout excess > 0 (default on)",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=Path("var/ops/balanced_holdout_search.json"),
    )
    parser.add_argument(
        "--output-md",
        type=Path,
        default=Path("docs/artifacts/strategy-search/balanced-holdout-report.md"),
    )
    parser.add_argument("--stdout-md", action="store_true")
    return parser


def _history_key(candles: tuple[Candle, ...]) -> str:
    return f"{candles[0].symbol}@{candles[0].interval}"


def _load_histories(args: argparse.Namespace) -> tuple[dict[str, tuple[Candle, ...]], list[str]]:
    notes = [KRAKEN_DAILY_CAP_NOTE]
    histories: dict[str, tuple[Candle, ...]] = {}
    if args.candles:
        for path in args.candles:
            candles = load_candles_from_json(path)
            if not candles:
                raise ValueError(f"{path}: no candles")
            histories[_history_key(candles)] = candles
            source = YAHOO_SOURCE if "-" in candles[0].symbol else "json"
            notes.append(
                f"loaded {len(candles)} {candles[0].interval} bars for "
                f"{candles[0].symbol} from {path} ({source})"
            )
        return histories, notes

    symbols = tuple(args.symbol) if args.symbol else DEFAULT_SYMBOLS
    fetched = asyncio.run(download_spot_histories(symbols, ("1d",), max_candles=args.max_candles))
    for key, candles in fetched.items():
        if not candles:
            notes.append(f"{key}: Kraken returned no committed bars")
            continue
        histories[key] = candles
        first = candles[0].opened_at.isoformat()
        last = candles[-1].opened_at.isoformat()
        cap = ""
        if len(candles) >= KRAKEN_PUBLIC_OHLC_MAX_BARS or (args.max_candles > len(candles)):
            cap = (
                f" (public OHLC cap; requested {args.max_candles}, "
                f"received {len(candles)} committed)"
            )
        notes.append(f"{key}: {len(candles)} committed Kraken bars {first} → {last}{cap}")
    if args.yahoo:
        try:
            yahoo = asyncio.run(download_yahoo_histories(DEFAULT_YAHOO_TICKERS))
        except (OSError, TypeError, ValueError, httpx.HTTPError) as exc:
            notes.append(f"Yahoo Finance daily skipped: {exc}")
        else:
            if not yahoo:
                notes.append("Yahoo Finance daily skipped: no committed bars")
            for key, candles in yahoo.items():
                histories[key] = candles
                first = candles[0].opened_at.isoformat()
                last = candles[-1].opened_at.isoformat()
                notes.append(
                    f"{key}: {len(candles)} Yahoo Finance (yfinance-compatible, "
                    f"non-Kraken) daily bars {first} → {last}"
                )
    if not histories:
        raise ValueError("no candle histories loaded")
    return histories, notes


def run(args: argparse.Namespace, settings: Settings | None = None) -> tuple[Path, Path]:
    settings = settings or Settings()
    histories, notes = _load_histories(args)
    fee_bps = (
        args.fee_bps
        if args.fee_bps is not None
        else research_fee_bps(settings.pretrade_fee_bps, settings.paper_fee_bps)
    )
    slippage_bps = (
        args.slippage_bps if args.slippage_bps is not None else settings.pretrade_slippage_bps
    )
    report = run_daily_robustness(
        histories,
        # --- era prints / DSR / PBO (#135) ---
        # This CLI is the report consumer, so it opts in. harder_gates and
        # honesty_pack leave it off and carry their own block.
        include_selection_evidence=True,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
        starting_equity=args.starting_equity or settings.paper_starting_nav_usd,
        train_size=args.train_size,
        test_size=args.test_size,
        step_size=args.step_size,
        holdout_fraction=args.holdout_fraction,
        min_trades=args.min_trades,
        catalog_name=args.catalog,
        require_balanced_holdout=args.balanced_holdout,
        data_notes=notes,
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(report.model_dump_json(indent=2) + "\n")
    markdown = render_daily_robustness_markdown(report)
    args.output_md.write_text(markdown)
    if args.stdout_md:
        print(markdown)
    else:
        status = "PROMOTED" if report.any_promoted else "NO EDGE"
        print(
            f"{status}: wrote {args.output_json} and {args.output_md} "
            f"(selected={report.selected_candidate_id or 'none'}; "
            f"promoted={', '.join(report.promoted_candidate_ids) or 'none'}; "
            f"flag={report.recommended_promote_flag or 'none'}). "
            "PAPER_PROMOTE_* flags are unchanged."
        )
    return args.output_json, args.output_md


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    run(args)


if __name__ == "__main__":
    main()
