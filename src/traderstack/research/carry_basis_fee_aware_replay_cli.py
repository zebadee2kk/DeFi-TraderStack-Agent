"""`traderstack-carry-basis-fee-aware-replay`: HL funding + OKX/Vision fee-survival.

Paper/research only. Never flips PAPER_PROMOTE_*. Skip-not-invent.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from traderstack.config import Settings
from traderstack.research.carry_basis_fee_aware_replay import (
    load_asilletto_daily_sum_abs,
    load_basis_venue,
    render_carry_basis_replay_markdown,
    run_carry_basis_replay,
)
from traderstack.research.fund_z_fee_aware_replay import DEFAULT_NOTIONAL_PER_ASSET_USD


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
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--asilletto-dir",
        type=Path,
        default=Path("var/ops/basis_cache/asilletto81/asset_ctxs"),
    )
    p.add_argument(
        "--asilletto-compact",
        type=Path,
        default=Path("var/ops/basis_cache/asilletto81/daily_sum_abs_btc_eth.json"),
    )
    p.add_argument(
        "--basis-dir",
        type=Path,
        default=Path("var/research/basis"),
    )
    p.add_argument(
        "--notional-per-asset-usd",
        type=float,
        default=DEFAULT_NOTIONAL_PER_ASSET_USD,
    )
    p.add_argument(
        "--output-md",
        type=Path,
        default=Path(
            "docs/artifacts/strategy-search/carry-basis-fee-aware-multiday-replay.md"
        ),
    )
    p.add_argument(
        "--output-json",
        type=Path,
        default=Path(
            "docs/artifacts/strategy-search/carry-basis-fee-aware-multiday-replay.json"
        ),
    )
    p.add_argument("--stdout-md", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = Settings()
    if settings.trading_mode != "paper":
        raise SystemExit("TRADING_MODE must be paper; refusing replay CLI")
    if settings.paper_promote_fund_z_harvest_sign_hold:
        raise SystemExit("unexpected promote pin true; refusing")

    panel, notes = load_asilletto_daily_sum_abs(
        args.asilletto_dir,
        compact_path=args.asilletto_compact,
    )
    okx, okx_notes = load_basis_venue(args.basis_dir / "okx")
    vision, vis_notes = load_basis_venue(args.basis_dir / "binance_vision")
    notes.extend(okx_notes)
    notes.extend(vis_notes)
    report = run_carry_basis_replay(
        panel,
        okx,
        vision,
        notional_per_asset_usd=args.notional_per_asset_usd,
        history_notes=notes,
        recipe_commit=_recipe_commit(),
    )
    md = render_carry_basis_replay_markdown(report)
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
        print(
            json.dumps(
                {
                    "print_kind": report.print_kind,
                    "can_promote": report.can_promote,
                    "keep_flag_false": report.keep_flag_false,
                    "dual_basis_fee_survival_passers": report.dual_basis_fee_survival_passers,
                    "output_md": str(args.output_md),
                    "n_funding_days": len(panel),
                },
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
