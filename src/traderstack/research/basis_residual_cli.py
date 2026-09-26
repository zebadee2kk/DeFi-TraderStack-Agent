"""`traderstack-basis-residual`: OKX x Binance Vision basis residual dual-print.

Scores frozen ``basis_resid_*`` catalog. Never flips ``PAPER_PROMOTE_*``.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from traderstack.research.basis import utc_day
from traderstack.research.basis_residual import (
    DEFAULT_FEE_BPS,
    DEFAULT_SLIPPAGE_BPS,
    render_basis_residual_markdown,
    run_basis_residual,
)
from traderstack.research.funding_carry import REQUIRED_SYMBOLS
from traderstack.research.funding_carry_cli import load_basis_dir


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "OKX x Binance Vision basis residual dual-print. Pre-registered "
            "basis_resid_* catalog. Never flips PAPER_PROMOTE_*."
        )
    )
    parser.add_argument(
        "--basis-dir",
        type=Path,
        default=Path("var/research/basis"),
        help="directory of <venue>/<SYMBOL>_basis_1d.json",
    )
    parser.add_argument("--fee-bps", type=float, default=DEFAULT_FEE_BPS)
    parser.add_argument("--slippage-bps", type=float, default=DEFAULT_SLIPPAGE_BPS)
    parser.add_argument(
        "--output-md",
        type=Path,
        default=Path("docs/artifacts/strategy-search/basis-residual-dual-print.md"),
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=Path("var/ops/basis_residual_dual_print.json"),
    )
    parser.add_argument("--stdout-md", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    since = datetime.fromisoformat("2020-01-01T00:00:00+00:00")
    until = datetime.now(tz=since.tzinfo)
    until = utc_day(until)
    notes: list[dict[str, str]] = []
    okx, okx_notes = load_basis_dir(
        args.basis_dir, "okx", REQUIRED_SYMBOLS, since=since, until=until
    )
    vision, vision_notes = load_basis_dir(
        args.basis_dir, "binance_vision", REQUIRED_SYMBOLS, since=since, until=until
    )
    notes.extend(okx_notes)
    notes.extend(vision_notes)
    report = run_basis_residual(
        okx_basis=okx,
        vision_basis=vision,
        fee_bps=args.fee_bps,
        slippage_bps=args.slippage_bps,
        history_notes=notes,
    )
    md = render_basis_residual_markdown(report)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.write_text(md, encoding="utf-8")
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(report.model_dump_json_safe(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if args.stdout_md:
        print(md)
    else:
        print(
            f"wrote {args.output_md}; dual_print_passers={report.dual_print_passers}; "
            f"can_promote={report.can_promote}; keep_flag_false={report.keep_flag_false}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
