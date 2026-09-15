"""`traderstack-honesty-pack`: focused reprint for one combined-passer.

Reuses the harder-gates loader and scoring. Writes a paper-only honesty
report for one catalog id (default ``ema_9_21_adx15``). Never flips
``PAPER_PROMOTE_*`` flags. Empty or negative Yahoo is success.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from traderstack.config import Settings
from traderstack.fee_tiers import add_fee_tier_argument, resolve_research_costs
from traderstack.research.daily_robustness import KRAKEN_PUBLIC_OHLC_MAX_BARS
from traderstack.research.daily_robustness_cli import _load_histories
from traderstack.research.honesty_pack import (
    DEFAULT_CANDIDATE_ID,
    PAPER_DD_CEILING,
    honesty_md_name,
    render_honesty_pack_markdown,
    run_honesty_pack,
)
from traderstack.research.miles_candidates import SearchCandidate


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Honesty pack for one harder-gates candidate (default "
            f"{DEFAULT_CANDIDATE_ID}): reprint Kraken combined A/B/C, "
            "Yahoo period1/period2 A/B for this id only (cannot promote), "
            "WF maxDD vs paper DD ceiling "
            f"{PAPER_DD_CEILING:.0%}, and the gate-B multi-window table. "
            "Does not flip PAPER_PROMOTE_* flags. Empty/negative Yahoo is "
            "success."
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
    parser.add_argument(
        "--candidate",
        default=DEFAULT_CANDIDATE_ID,
        help=f"catalog id to pack (default {DEFAULT_CANDIDATE_ID})",
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
        "--catalog",
        choices=("expanded", "balanced", "legacy"),
        default="expanded",
        help="harder-gates catalog used for the combined reprint (default expanded)",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=Path("var/ops/ema_9_21_adx15_honesty.json"),
    )
    parser.add_argument(
        "--output-md",
        type=Path,
        default=Path("docs/artifacts/strategy-search") / honesty_md_name(DEFAULT_CANDIDATE_ID),
    )
    parser.add_argument("--stdout-md", action="store_true")
    return parser


def run(
    args: argparse.Namespace,
    settings: Settings | None = None,
    *,
    candidates: tuple[SearchCandidate, ...] | None = None,
) -> tuple[Path, Path]:
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
    report = run_honesty_pack(
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
        candidate_id=args.candidate,
        candidates=candidates,
        catalog_name=args.catalog,
        data_notes=notes,
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(report.model_dump_json(indent=2) + "\n")
    markdown = render_honesty_pack_markdown(report)
    args.output_md.write_text(markdown)
    if args.stdout_md:
        print(markdown)
    else:
        status = "STILL TOP-1" if report.still_combined_top1 else "NOT TOP-1"
        print(
            f"{status}: wrote {args.output_json} and {args.output_md} "
            f"(candidate={report.candidate_id}; "
            f"combined={report.still_combined_pass}; "
            f"top1={report.still_combined_top1}; "
            f"yahoo_rows={len(report.yahoo_rows)}; "
            f"sol_blows_past={report.sol_blows_past_ceiling}; "
            f"keep_flag_false={report.keep_flag_false}). "
            "PAPER_PROMOTE_* flags are unchanged."
        )
    return args.output_json, args.output_md


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    run(args)


if __name__ == "__main__":
    main()
