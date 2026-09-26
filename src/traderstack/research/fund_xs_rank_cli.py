"""`traderstack-fund-xs-rank`: HL asilletto funding-rank dual-era dual-print.

Never flips ``PAPER_PROMOTE_*``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from traderstack.config import Settings
from traderstack.research.edge_series import ASILLETTO81_CACHE_DIR
from traderstack.research.fund_xs_rank import (
    DEFAULT_FEE_BPS,
    DEFAULT_SLIPPAGE_BPS,
    load_asilletto_daily_funding,
    render_fund_xs_rank_markdown,
    run_fund_xs_rank,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "HL asilletto cross-sectional funding-rank dual-era dual-print. "
            "Pre-registered fund_xs_rank_* catalog. Never flips PAPER_PROMOTE_*."
        )
    )
    parser.add_argument(
        "--asilletto-dir",
        type=Path,
        default=ASILLETTO81_CACHE_DIR,
        help="Directory of YYYYMMDD.csv.lz4 asset_ctxs files",
    )
    parser.add_argument("--fee-bps", type=float, default=DEFAULT_FEE_BPS)
    parser.add_argument("--slippage-bps", type=float, default=DEFAULT_SLIPPAGE_BPS)
    parser.add_argument(
        "--output-md",
        type=Path,
        default=Path("docs/artifacts/strategy-search/fund-xs-rank-hl-dual-era-dual-print.md"),
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=Path("var/ops/fund_xs_rank_hl_dual_era_dual_print.json"),
    )
    parser.add_argument("--stdout-md", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _ = Settings()  # load defaults; never mutate PAPER_PROMOTE_*
    panel, notes = load_asilletto_daily_funding(args.asilletto_dir)
    report = run_fund_xs_rank(
        panel,
        fee_bps=args.fee_bps,
        slippage_bps=args.slippage_bps,
        history_notes=notes,
    )
    md = render_fund_xs_rank_markdown(report)
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
