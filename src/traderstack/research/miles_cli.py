"""`traderstack-miles-search`: Miles-inspired EMA/ADX × GARCH catalog search.

Loads Kraken Spot OHLC (JSON files or the public REST downloader), scores the
pre-registered EMA 9/21 and 12/26 catalog with optional ADX gates and GARCH
vol-targeted sizing, and writes JSON + Markdown. It never enables
``PAPER_GARCH_SIZE`` or ``PAPER_PROMOTE_EMA_9_21``. When that promote
flag is on at paper runtime, candles are forced to daily (``1d`` / 1440);
this CLI does not change that.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from traderstack.candles import Candle
from traderstack.config import Settings
from traderstack.fee_tiers import add_fee_tier_argument, resolve_research_costs
from traderstack.research.cli import load_candles_from_json
from traderstack.research.download_candles import download_spot_histories
from traderstack.research.miles_search import (
    render_miles_markdown,
    run_miles_search,
)

DEFAULT_SYMBOLS = ("BTC/USD", "ETH/USD", "SOL/USD")
DEFAULT_RESOLUTIONS = ("1d", "1h")
KRAKEN_OHLC_CAP_NOTE = (
    "Kraken public Spot OHLC (`GET /0/public/OHLC`) returns at most 720 of the "
    "most recent committed bars per pair/interval. `since` pages forward only; "
    "older history is not available from this endpoint. Daily ≈ 2 years; 1h ≈ 30 days."
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Score the Miles-inspired EMA 9/21 and 12/26 catalog (optional ADX "
            "gate, optional GARCH vol-targeted size) with fee-aware walk-forward "
            "+ holdout. Writes a ranked report. Does not enable "
            "PAPER_GARCH_SIZE or PAPER_PROMOTE_EMA_9_21."
        )
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--candles",
        type=Path,
        action="append",
        help="JSON candle array (repeat per asset/interval). Symbol+interval from file.",
    )
    source.add_argument(
        "--live-kraken",
        action="store_true",
        help="fetch BTC/ETH/SOL daily and 1h from Kraken public OHLC (720-bar cap)",
    )
    parser.add_argument(
        "--symbol",
        action="append",
        default=None,
        help="override live symbols (repeat; default BTC/USD ETH/USD SOL/USD)",
    )
    parser.add_argument(
        "--resolution",
        action="append",
        default=None,
        help="override live resolutions (repeat; default 1d and 1h)",
    )
    parser.add_argument("--max-candles", type=int, default=720)
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
    parser.add_argument("--garch-min-train", type=int, default=120)
    parser.add_argument("--garch-refit-every", type=int, default=21)
    parser.add_argument("--garch-target-vol", type=float, default=0.50)
    parser.add_argument(
        "--output-json",
        type=Path,
        default=Path("var/ops/miles_inspired_search.json"),
    )
    parser.add_argument(
        "--output-md",
        type=Path,
        default=Path("docs/artifacts/strategy-search/miles-inspired-report.md"),
    )
    parser.add_argument("--stdout-md", action="store_true")
    return parser


def _history_key(candles: tuple[Candle, ...]) -> str:
    return f"{candles[0].symbol}@{candles[0].interval}"


def _load_histories(args: argparse.Namespace) -> tuple[dict[str, tuple[Candle, ...]], list[str]]:
    notes = [KRAKEN_OHLC_CAP_NOTE]
    histories: dict[str, tuple[Candle, ...]] = {}
    if args.candles:
        for path in args.candles:
            candles = load_candles_from_json(path)
            if not candles:
                raise ValueError(f"{path}: no candles")
            histories[_history_key(candles)] = candles
            notes.append(
                f"loaded {len(candles)} {candles[0].interval} bars for {candles[0].symbol} from {path}"
            )
        return histories, notes
    symbols = tuple(args.symbol) if args.symbol else DEFAULT_SYMBOLS
    resolutions = tuple(args.resolution) if args.resolution else DEFAULT_RESOLUTIONS
    fetched = asyncio.run(
        download_spot_histories(symbols, resolutions, max_candles=args.max_candles)
    )
    for key, candles in fetched.items():
        histories[key] = candles
        if candles:
            first = candles[0].opened_at.isoformat()
            last = candles[-1].opened_at.isoformat()
            notes.append(f"{key}: {len(candles)} committed bars {first} → {last}")
        else:
            notes.append(f"{key}: Kraken returned no committed bars")
    if not any(histories.values()):
        raise ValueError("Kraken returned no candles")
    return {key: candles for key, candles in histories.items() if candles}, notes


def run(args: argparse.Namespace, settings: Settings | None = None) -> tuple[Path, Path]:
    settings = settings or Settings()
    histories, notes = _load_histories(args)
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
    report = run_miles_search(
        histories,
        fee_bps=fee_bps,
        fee_tier=costs.stamp,
        slippage_bps=slippage_bps,
        starting_equity=args.starting_equity or settings.paper_starting_nav_usd,
        train_size=args.train_size,
        test_size=args.test_size,
        step_size=args.step_size,
        holdout_fraction=args.holdout_fraction,
        min_trades=args.min_trades,
        garch_min_train=args.garch_min_train,
        garch_refit_every=args.garch_refit_every,
        garch_target_vol_ann=args.garch_target_vol,
        data_notes=notes,
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(report.model_dump_json(indent=2) + "\n")
    markdown = render_miles_markdown(report)
    args.output_md.write_text(markdown)
    if args.stdout_md:
        print(markdown)
    else:
        status = "PROMOTED" if report.any_promoted else "NO EDGE"
        print(
            f"{status}: wrote {args.output_json} and {args.output_md} "
            f"(selected={report.selected_candidate_id or 'none'}; "
            f"promoted={', '.join(report.promoted_candidate_ids) or 'none'}). "
            "PAPER_GARCH_SIZE and PAPER_PROMOTE_EMA_9_21 are unchanged."
        )
    return args.output_json, args.output_md


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    run(args)


if __name__ == "__main__":
    main()
