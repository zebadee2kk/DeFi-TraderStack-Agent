"""`traderstack-weekly-trend`: weekly low-turnover trend dual-print.

Scores the frozen ``wk_trend_*`` catalog on Friday-UTC weekly bars
resampled from existing Kraken x Coinbase daily archives. Never flips
``PAPER_PROMOTE_*``. Empty dual-print set is success. Paper only.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from traderstack.candles import Candle
from traderstack.research.cli import load_candles_from_json
from traderstack.research.weekly_trend import (
    DEFAULT_KRAKEN_TIER,
    DEFAULT_SLIPPAGE_BPS,
    KRAKEN_PRO_TIERS,
    render_weekly_trend_markdown,
    run_weekly_trend_search,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Weekly / low-turnover trend dual-print (Hypothesis C): "
            "Friday-UTC weekly resample of existing Kraken x Coinbase "
            "daily archives; frozen wk_trend_* catalog; weekly-scaled "
            "#96+A+B+C; pilot 80+5 bps. Does not flip PAPER_PROMOTE_*. "
            "Empty dual-print set is success. No live."
        )
    )
    parser.add_argument(
        "--candles-dir",
        nargs=2,
        action="append",
        metavar=("VENUE", "DIR"),
        required=True,
        help="venue label and candle directory (expect kraken + coinbase)",
    )
    parser.add_argument(
        "--era-dir",
        type=Path,
        default=None,
        help="optional non-overlapping coinbase era dir fallback",
    )
    parser.add_argument(
        "--kraken-tier",
        type=int,
        choices=sorted(KRAKEN_PRO_TIERS),
        default=DEFAULT_KRAKEN_TIER,
        help="Kraken Pro tier; taker bps (default tier 1 = 80)",
    )
    parser.add_argument("--fee-bps", type=float, default=None)
    parser.add_argument("--slippage-bps", type=float, default=DEFAULT_SLIPPAGE_BPS)
    parser.add_argument("--starting-equity", type=float, default=10_000.0)
    parser.add_argument(
        "--recipe-commit",
        type=str,
        default=None,
        help="git SHA of pre-registered recipe commit (auto-detect if omitted)",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=Path("var/ops/weekly_lowturn_trend_dual_print.json"),
    )
    parser.add_argument(
        "--output-md",
        type=Path,
        default=Path("docs/artifacts/strategy-search/weekly-lowturn-trend-dual-print.md"),
    )
    parser.add_argument("--stdout-md", action="store_true")
    return parser


def load_candles_dir(directory: Path) -> tuple[dict[str, tuple[Candle, ...]], list[str]]:
    """Load every ``*_1d.json`` candle array (skip report sidecars)."""
    histories: dict[str, tuple[Candle, ...]] = {}
    notes: list[str] = []
    if not directory.is_dir():
        notes.append(f"{directory}: not a directory; skipped")
        return histories, notes
    for path in sorted(directory.glob("*.json")):
        if path.name.endswith(".report.json") or ".report." in path.name:
            continue
        if not path.name.endswith("_1d.json") and "_1d." not in path.name:
            # still try; skip-not-invent on parse failure
            pass
        try:
            candles = load_candles_from_json(path)
        except (OSError, TypeError, ValueError) as exc:
            notes.append(f"{path.name}: load failed ({exc}); skipped")
            continue
        if not candles:
            notes.append(f"{path.name}: empty; skipped")
            continue
        # keep BTC/ETH/SOL gate+report symbols only for score speed
        sym = candles[0].symbol.upper().replace("-", "/")
        if sym not in {
            "BTC/USD",
            "ETH/USD",
            "SOL/USD",
            "BTCUSDT",
            "ETHUSDT",
            "SOLUSDT",
            "BTC-USD",
            "ETH-USD",
            "SOL-USD",
            "XBT/USD",
        }:
            continue
        key = f"{candles[0].symbol}@{candles[0].interval}"
        histories[key] = candles
        notes.append(
            f"loaded {len(candles)} {candles[0].interval} bars for {candles[0].symbol} from {path}"
        )
    return histories, notes


def _detect_recipe_commit() -> str | None:
    try:
        out = subprocess.check_output(
            [
                "git",
                "log",
                "-1",
                "--format=%h",
                "--",
                "docs/recipes/strategy-search/weekly-lowturn-trend-dual-print-recipe.md",
            ],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        return out or None
    except (OSError, subprocess.CalledProcessError):
        return None


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    fee_bps = (
        float(args.fee_bps)
        if args.fee_bps is not None
        else float(KRAKEN_PRO_TIERS[args.kraken_tier])
    )
    notes: list[str] = []
    by_venue: dict[str, dict[str, tuple[Candle, ...]]] = {}
    for venue, directory in args.candles_dir:
        loaded, extra = load_candles_dir(Path(directory))
        notes.extend(f"{venue}: {n}" for n in extra)
        by_venue[venue.lower()] = loaded

    kraken = by_venue.get("kraken") or {}
    if not kraken:
        raise SystemExit("require --candles-dir kraken <dir> with BTC/ETH daily JSON")
    coinbase = by_venue.get("coinbase") or None
    era = None
    if args.era_dir is not None:
        era, era_notes = load_candles_dir(args.era_dir)
        notes.extend(f"era: {n}" for n in era_notes)

    recipe_commit = args.recipe_commit or _detect_recipe_commit()
    report = run_weekly_trend_search(
        kraken,
        coinbase,
        fee_bps=fee_bps,
        slippage_bps=float(args.slippage_bps),
        starting_equity=float(args.starting_equity),
        kraken_tier=int(args.kraken_tier),
        recipe_commit=recipe_commit,
        history_notes=notes,
        era_daily=era,
    )
    md = render_weekly_trend_markdown(report)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.write_text(md, encoding="utf-8")
    args.output_json.write_text(
        json.dumps(report.model_dump_json_safe(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if args.stdout_md:
        print(md)
    else:
        print(
            f"wrote {args.output_md} and {args.output_json}; "
            f"dual_print_passers={report.dual_print_passers}; "
            f"print_kind={report.print_kind}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
