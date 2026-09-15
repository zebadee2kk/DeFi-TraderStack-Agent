"""`traderstack-second-print`: fee-aware second print for ema_9_21_adx15.

Kraken public OHLC cannot unlock a second 720-bar era. This command
scores the holdout-blind prefix (same venue; not independent) and a
pre-registered older Binance Spot daily 720 (BTCUSDT+ETHUSDT) that
ends before the primary Kraken first bar. Labeled non-Kraken /
report-only. Never flips ``PAPER_PROMOTE_*``. An honest FAIL is success.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime
from pathlib import Path

import httpx

from traderstack.candles import Candle
from traderstack.config import Settings
from traderstack.fee_tiers import add_fee_tier_argument, resolve_research_costs
from traderstack.research.binance_spot import (
    DEFAULT_BINANCE_SYMBOLS,
    download_binance_spot_histories,
)
from traderstack.research.cli import load_candles_from_json
from traderstack.research.daily_robustness import KRAKEN_PUBLIC_OHLC_MAX_BARS
from traderstack.research.daily_robustness_cli import _load_histories
from traderstack.research.miles_candidates import SearchCandidate
from traderstack.research.second_print import (
    DEFAULT_CANDIDATE_ID,
    SECOND_PRINT_BARS,
    SECOND_PRINT_CANDIDATE_IDS,
    primary_first_opened_at,
    render_second_print_markdown,
    run_second_print,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Second independent print for "
            f"{DEFAULT_CANDIDATE_ID} (and the other #99/#100 "
            "combined-passers). Kraken holdout-blind prefix + Binance "
            "Spot daily BTCUSDT/ETHUSDT older 720 ending before the "
            "primary Kraken first bar. Report-only; cannot enter the "
            "promotion average. Does not flip PAPER_PROMOTE_* flags. "
            "An honest FAIL is success."
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
    # --- fee realism (#138) ---
    add_fee_tier_argument(parser)
    parser.add_argument("--slippage-bps", type=float, default=None)
    parser.add_argument("--train-size", type=int, default=180)
    parser.add_argument("--test-size", type=int, default=60)
    parser.add_argument("--step-size", type=int, default=60)
    parser.add_argument("--holdout-fraction", type=float, default=0.20)
    parser.add_argument("--min-trades", type=int, default=3)
    parser.add_argument(
        "--candidate",
        default=DEFAULT_CANDIDATE_ID,
        help=f"focus id (default {DEFAULT_CANDIDATE_ID})",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=Path("var/ops/ema_9_21_adx15_second_print.json"),
    )
    parser.add_argument(
        "--output-md",
        type=Path,
        default=Path("docs/artifacts/strategy-search/ema-9-21-adx15-second-print.md"),
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
    del candidates
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

    # --- fee realism (#138) ---
    # Precedence: --fee-bps (stamped "explicit") > --fee-tier > PAPER_FEE_TIER;
    # the tier fee is max(PRETRADE_FEE_BPS, tier taker). Taker leg only.
    costs = resolve_research_costs(
        fee_bps=args.fee_bps,
        fee_tier=args.fee_tier,
        settings=settings,
        slippage_bps=args.slippage_bps,
    )
    fee_bps = costs.fee_bps
    slippage_bps = costs.slippage_bps
    report = run_second_print(
        kraken_histories,
        binance_histories,
        fee_bps=fee_bps,
        fee_tier=costs.stamp,
        slippage_bps=slippage_bps,
        starting_equity=args.starting_equity or settings.paper_starting_nav_usd,
        train_size=args.train_size,
        test_size=args.test_size,
        step_size=args.step_size,
        holdout_fraction=args.holdout_fraction,
        min_trades=args.min_trades,
        candidate_id=args.candidate,
        candidate_ids=SECOND_PRINT_CANDIDATE_IDS,
        binance_source=binance_source,
        data_notes=notes,
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(report.model_dump_json(indent=2) + "\n")
    markdown = render_second_print_markdown(report)
    args.output_md.write_text(markdown)
    if args.stdout_md:
        print(markdown)
    else:
        verdict = "PASS" if report.binance_combined_pass else "FAIL"
        print(
            f"SECOND PRINT {verdict} (report-only): wrote {args.output_json} "
            f"and {args.output_md} (candidate={report.candidate_id}; "
            f"binance_combined={report.binance_combined_pass}; "
            f"binance_fail_closed={report.binance_print_fail_closed}; "
            f"can_enter_promotion_average={report.can_enter_promotion_average}; "
            f"keep_flag_false={report.keep_flag_false}). "
            "PAPER_PROMOTE_* flags are unchanged."
        )
    return args.output_json, args.output_md


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    run(args)


if __name__ == "__main__":
    main()
