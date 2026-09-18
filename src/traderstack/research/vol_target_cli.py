"""`traderstack-vol-target`: vol-target overlay on ma_cross_10_30 dual-print.

Scores the frozen ``ma_cross_10_30`` + ``ma_cross_10_30_vt*`` catalog on
Kraken x Coinbase daily spot BTC/ETH. Never flips ``PAPER_PROMOTE_*``.
Empty dual-print is success.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from traderstack.candles import Candle
from traderstack.research.cli import load_candles_from_json
from traderstack.research.vol_target import (
    REQUIRED_SYMBOLS,
    VOL_TARGET_RULES,
    render_vol_target_markdown,
    run_vol_target,
)
from traderstack.research.xs_topk import PILOT_TIER_TAKER_BPS

SYMBOLS = REQUIRED_SYMBOLS


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Vol-target size overlay on frozen ma_cross_10_30; Kraken x Coinbase "
            "dual-print at pilot fees. Never flips PAPER_PROMOTE_*."
        )
    )
    parser.add_argument("--interval", default="1d", choices=("1d",))
    parser.add_argument("--fee-bps", type=float, default=PILOT_TIER_TAKER_BPS)
    parser.add_argument("--slippage-bps", type=float, default=5.0)
    parser.add_argument("--starting-equity", type=float, default=10_000.0)
    parser.add_argument("--train-size", type=int, default=180)
    parser.add_argument("--test-size", type=int, default=60)
    parser.add_argument("--step-size", type=int, default=60)
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
        default=Path("docs/artifacts/strategy-search/vol-target-ma-cross-dual-print.md"),
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=Path("var/ops/vol_target_ma_cross_dual_print.json"),
    )
    parser.add_argument("--stdout-md", action="store_true")
    return parser


def _load_symbol_candles(
    directory: Path, symbols: tuple[str, ...]
) -> dict[str, tuple[Candle, ...]]:
    out: dict[str, tuple[Candle, ...]] = {}
    for symbol in symbols:
        stem = symbol.replace("/", "_")
        path = directory / f"{stem}_1d.json"
        if not path.exists():
            continue
        loaded = load_candles_from_json(path)
        if loaded:
            out[symbol.upper()] = loaded
    return out


def _tip_sha() -> str | None:
    try:
        return (
            subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"],
                stderr=subprocess.DEVNULL,
                text=True,
            ).strip()
            or None
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def run(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    candle_dirs = args.candles_dir or [
        ("kraken", "var/research/candles/kraken"),
        ("coinbase", "var/research/candles/coinbase"),
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
                        f"{series[0].opened_at.isoformat()} -> "
                        f"{series[-1].opened_at.isoformat()}"
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

    report = run_vol_target(
        histories,
        fee_bps=args.fee_bps,
        slippage_bps=args.slippage_bps,
        starting_equity=args.starting_equity,
        train_size=args.train_size,
        test_size=args.test_size,
        step_size=args.step_size,
        holdout_fraction=args.holdout_fraction,
        min_trades=args.min_trades,
        second_histories=second_histories,
        primary_candle_venue=primary_venue,
        second_candle_venue=second_venue,
        history_notes=history_notes,
        tip_sha=_tip_sha(),
    )
    md = render_vol_target_markdown(report)
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
    print(VOL_TARGET_RULES.split(".")[0] + ".")
    return 0


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
