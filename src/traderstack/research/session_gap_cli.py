"""`traderstack-sess-gap`: overnight vs session gap SPOT dual-print.

Scores the frozen ``sess_gap_*`` catalog on Kraken x Coinbase daily spot
BTC/ETH using OHLC-derived overnight gap and session return FeatureZ
series. Never flips ``PAPER_PROMOTE_*``. No intraday archive required.
Empty dual-print is success.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from traderstack.candles import Candle
from traderstack.config import Settings
from traderstack.research.cli import load_candles_from_json
from traderstack.research.funding_carry import (
    DEFAULT_STEP_SIZE,
    DEFAULT_TEST_SIZE,
    DEFAULT_TRAIN_SIZE,
    DEFAULT_WARMUP,
)
from traderstack.research.session_gap import (
    REQUIRED_SYMBOLS,
    SESS_GAP_RULES,
    render_sess_gap_markdown,
    run_sess_gap,
)
from traderstack.research.xs_topk import PILOT_TIER_TAKER_BPS

SYMBOLS = REQUIRED_SYMBOLS


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Overnight vs session open-close gap SPOT dual-print on Kraken x "
            "Coinbase at pilot fees. Pre-registered sess_gap_* catalog. "
            "Never flips PAPER_PROMOTE_*."
        )
    )
    parser.add_argument("--interval", default="1d", choices=("1d",))
    parser.add_argument("--fee-bps", type=float, default=PILOT_TIER_TAKER_BPS)
    parser.add_argument("--slippage-bps", type=float, default=5.0)
    parser.add_argument("--starting-equity", type=float, default=10_000.0)
    parser.add_argument("--train-size", type=int, default=DEFAULT_TRAIN_SIZE)
    parser.add_argument("--test-size", type=int, default=DEFAULT_TEST_SIZE)
    parser.add_argument("--step-size", type=int, default=DEFAULT_STEP_SIZE)
    parser.add_argument("--warmup", type=int, default=DEFAULT_WARMUP)
    parser.add_argument("--holdout-fraction", type=float, default=0.20)
    parser.add_argument("--min-trades", type=int, default=3)
    parser.add_argument(
        "--candles-dir",
        nargs=2,
        action="append",
        metavar=("VENUE", "DIR"),
        default=None,
        help="venue label and candle directory (repeatable; expect kraken + coinbase)",
    )
    parser.add_argument(
        "--output-md",
        type=Path,
        default=Path("docs/artifacts/strategy-search/sess-gap-overnight-session-dual-print.md"),
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=Path("var/ops/sess_gap_overnight_session_dual_print.json"),
    )
    parser.add_argument("--stdout-md", action="store_true")
    return parser


def _load_symbol_candles(
    directory: Path, symbols: tuple[str, ...]
) -> dict[str, tuple[Candle, ...]]:
    wanted = {symbol.upper() for symbol in symbols}
    histories: dict[str, tuple[Candle, ...]] = {}
    for path in sorted(directory.glob("*.json")):
        if path.name.endswith(".report.json"):
            continue
        try:
            candles = load_candles_from_json(path)
        except (TypeError, ValueError, OSError):
            continue
        if not candles or candles[0].interval != "1d":
            continue
        symbol = candles[0].symbol.upper()
        if symbol not in wanted:
            continue
        histories[symbol] = candles
    return histories


def run(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _ = Settings()  # ensure defaults load; never mutate PAPER_PROMOTE_*

    candle_dirs = args.candles_dir or [
        ["kraken", "var/research/candles/kraken"],
        ["coinbase", "var/research/candles/coinbase"],
    ]
    history_notes: list[dict[str, str]] = []
    primary_venue, primary_dir = candle_dirs[0][0], Path(candle_dirs[0][1])
    histories = _load_symbol_candles(primary_dir, SYMBOLS)
    for symbol in SYMBOLS:
        series = histories.get(symbol.upper())
        if series:
            history_notes.append(
                {
                    "name": f"{primary_venue}:{symbol}",
                    "status": "ok",
                    "reason": (
                        f"{len(series)} daily bars "
                        f"{series[0].opened_at.isoformat()} -> {series[-1].opened_at.isoformat()}"
                    ),
                }
            )
        else:
            history_notes.append(
                {
                    "name": f"{primary_venue}:{symbol}",
                    "status": "skipped",
                    "reason": f"missing 1d candles under {primary_dir}",
                }
            )

    second_histories: dict[str, tuple[Candle, ...]] | None = None
    second_venue: str | None = None
    if len(candle_dirs) >= 2:
        second_venue, second_dir = candle_dirs[1][0], Path(candle_dirs[1][1])
        second_histories = _load_symbol_candles(second_dir, SYMBOLS)
        for symbol in SYMBOLS:
            series = second_histories.get(symbol.upper())
            if series:
                history_notes.append(
                    {
                        "name": f"{second_venue}:{symbol}",
                        "status": "ok",
                        "reason": (
                            f"{len(series)} daily bars "
                            f"{series[0].opened_at.isoformat()} -> "
                            f"{series[-1].opened_at.isoformat()}"
                        ),
                    }
                )
            else:
                history_notes.append(
                    {
                        "name": f"{second_venue}:{symbol}",
                        "status": "skipped",
                        "reason": f"missing 1d candles under {second_dir}",
                    }
                )
        if len(second_histories) < len(SYMBOLS):
            second_histories = None
            second_venue = None

    report = run_sess_gap(
        histories,
        fee_bps=args.fee_bps,
        slippage_bps=args.slippage_bps,
        starting_equity=args.starting_equity,
        warmup=args.warmup,
        train_size=args.train_size,
        test_size=args.test_size,
        step_size=args.step_size,
        holdout_fraction=args.holdout_fraction,
        min_trades=args.min_trades,
        interval=args.interval,
        second_histories=second_histories,
        primary_candle_venue=primary_venue,
        second_candle_venue=second_venue,
        history_notes=history_notes,
    )

    md = render_sess_gap_markdown(report)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.write_text(md, encoding="utf-8")
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(report.model_dump(mode="json"), indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    if args.stdout_md:
        print(md)
    print(
        f"wrote {args.output_md} dual_print_passers={report.dual_print_passers} "
        f"print_kind={report.print_kind} keep_flag_false={report.keep_flag_false}"
    )
    print(SESS_GAP_RULES.split(".")[0] + ".")
    return 0


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
