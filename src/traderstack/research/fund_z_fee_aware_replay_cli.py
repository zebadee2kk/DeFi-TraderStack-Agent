"""`traderstack-fund-z-fee-aware-replay`: multi-day fee-survival historical REPLAY.

Paper/research only. Never flips PAPER_PROMOTE_*. Skip-not-invent.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from traderstack.config import Settings
from traderstack.research.fund_z_fee_aware_replay import (
    DEFAULT_NOTIONAL_PER_ASSET_USD,
    load_asilletto_daily_sum_abs,
    render_fee_aware_replay_markdown,
    run_fee_aware_replay,
)


def _recipe_commit() -> str | None:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
        )
        return out.strip() or None
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Historical fee-aware multi-day REPLAY of fund_z_harvest_sign_hold "
            "on HL asilletto hourly→daily_sum_abs tapes. Dual era when HTX "
            "hourly absent. Never flips PAPER_PROMOTE_*."
        )
    )
    parser.add_argument(
        "--asilletto-dir",
        type=Path,
        default=Path("var/ops/basis_cache/asilletto81/asset_ctxs"),
        help="HL asilletto81 asset_ctxs directory (*.csv.lz4)",
    )
    parser.add_argument(
        "--compact-path",
        type=Path,
        default=None,
        help="Optional compact daily_sum_abs JSON path (default beside asset_ctxs)",
    )
    parser.add_argument(
        "--notional-per-asset-usd",
        type=float,
        default=DEFAULT_NOTIONAL_PER_ASSET_USD,
    )
    parser.add_argument(
        "--output-md",
        type=Path,
        default=Path("docs/artifacts/strategy-search/fund-z-harvest-fee-aware-multiday-replay.md"),
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=Path(
            "docs/artifacts/strategy-search/fund-z-harvest-fee-aware-multiday-replay.json"
        ),
    )
    parser.add_argument("--stdout-md", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = Settings()
    # Guardrails: never mutate promote defaults; refuse non-paper trading_mode.
    if settings.trading_mode != "paper":
        raise SystemExit("TRADING_MODE must be paper; refusing replay CLI")
    if settings.paper_promote_fund_z_harvest_sign_hold:
        raise SystemExit(
            "PAPER_PROMOTE_FUND_Z_HARVEST_SIGN_HOLD is unexpectedly true in "
            "Settings; refusing (Field default must stay false)"
        )

    panel, notes = load_asilletto_daily_sum_abs(
        args.asilletto_dir,
        compact_path=args.compact_path,
    )
    report = run_fee_aware_replay(
        panel,
        notional_per_asset_usd=args.notional_per_asset_usd,
        history_notes=notes,
        recipe_commit=_recipe_commit(),
    )
    md = render_fee_aware_replay_markdown(report)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.write_text(md + "\n", encoding="utf-8")
    args.output_json.write_text(
        json.dumps(report.model_dump_json_safe(), indent=2) + "\n",
        encoding="utf-8",
    )
    if args.stdout_md:
        print(md)
    else:
        summary = {
            "print_kind": report.print_kind,
            "can_promote": report.can_promote,
            "keep_flag_false": report.keep_flag_false,
            "dual_era_fee_survival_passers": report.dual_era_fee_survival_passers,
            "output_md": str(args.output_md),
            "output_json": str(args.output_json),
            "n_panel_days": len(panel),
        }
        print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
