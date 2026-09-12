"""`traderstack-harder-gates`: magnitude / multi-window / fee-stress bar.

Loads the longest Kraken public Spot daily OHLC the API will return (720
committed bars, ~2y), optionally a Yahoo Finance daily A/B (non-Kraken),
scores the pre-registered balanced-holdout catalog under gates A/B/C,
and writes JSON + Markdown. It never enables ``PAPER_PROMOTE_EMA_9_21``
or ``PAPER_PROMOTE_SEARCHED_STRATEGIES``.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from traderstack.config import Settings
from traderstack.research.daily_robustness import KRAKEN_PUBLIC_OHLC_MAX_BARS
from traderstack.research.daily_robustness_cli import _load_histories
from traderstack.research.harder_gates import (
    FEE_STRESS_MULTIPLIER,
    MAGNITUDE_RATIO_MIN,
    MULTIWINDOW_BARS,
    MULTIWINDOW_COUNT,
    MULTIWINDOW_MIN_PASSES,
    render_harder_gates_markdown,
    run_harder_gates,
)
from traderstack.research.miles_search import research_fee_bps


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Stress-test the #96 Kraken daily catalog under pre-registered "
            "harder honesty gates: A magnitude balance "
            f"(min/max holdout ratio >= {MAGNITUDE_RATIO_MIN:.2f}), B "
            f"{MULTIWINDOW_COUNT}x{MULTIWINDOW_BARS}-bar multi-window "
            f"(>= {MULTIWINDOW_MIN_PASSES} of {MULTIWINDOW_COUNT} with "
            "BTC and ETH WF total > 0), C "
            f"{FEE_STRESS_MULTIPLIER:g}x fees still clearing #96 "
            "balanced signs. Writes a ranked report. Does not enable "
            "PAPER_PROMOTE_* flags. An honest FAIL is success."
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
        "--output-json",
        type=Path,
        default=Path("var/ops/harder_gates_search.json"),
    )
    parser.add_argument(
        "--output-md",
        type=Path,
        default=Path("docs/artifacts/strategy-search/magnitude-multiwindow-report.md"),
    )
    parser.add_argument("--stdout-md", action="store_true")
    return parser


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
    report = run_harder_gates(
        histories,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
        starting_equity=args.starting_equity or settings.paper_starting_nav_usd,
        train_size=args.train_size,
        test_size=args.test_size,
        step_size=args.step_size,
        holdout_fraction=args.holdout_fraction,
        min_trades=args.min_trades,
        catalog_name=args.catalog,
        data_notes=notes,
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(report.model_dump_json(indent=2) + "\n")
    markdown = render_harder_gates_markdown(report)
    args.output_md.write_text(markdown)
    if args.stdout_md:
        print(markdown)
    else:
        status = "PROMOTED" if report.any_promoted else "NO EDGE"
        print(
            f"{status}: wrote {args.output_json} and {args.output_md} "
            f"(selected={report.selected_candidate_id or 'none'}; "
            f"promoted={', '.join(report.promoted_candidate_ids) or 'none'}; "
            f"ema_9_21 A={report.ema_9_21_gate_a} "
            f"B={report.ema_9_21_gate_b} C={report.ema_9_21_gate_c} "
            f"combined={report.ema_9_21_combined}). "
            "PAPER_PROMOTE_* flags are unchanged."
        )
    return args.output_json, args.output_md


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    run(args)


if __name__ == "__main__":
    main()
