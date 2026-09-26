"""`traderstack-fund-z-harvest`: paper-perp funding-z harvest dual-print.

Distinct from spot funding-div #162. Requires dual_basis. Never flips
``PAPER_PROMOTE_*``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime
from pathlib import Path

import httpx

from traderstack.config import Settings
from traderstack.research.basis import utc_day
from traderstack.research.edge_series import (
    HTX_BASE,
    HTX_DAILY_LIMIT_PAGES,
    HTX_DAILY_LOOKBACK_DAYS,
    HYPERLIQUID_BASE,
    HYPERLIQUID_DAILY_LIMIT_PAGES,
    HYPERLIQUID_DAILY_LOOKBACK_DAYS,
    HYPERLIQUID_SYMBOL_PAUSE_SECONDS,
    fetch_htx_funding,
    fetch_hyperliquid_funding,
)
from traderstack.research.fund_z_harvest import (
    DEFAULT_FEE_BPS,
    DEFAULT_SLIPPAGE_BPS,
    render_fund_z_harvest_markdown,
    run_fund_z_harvest,
)
from traderstack.research.funding_carry import REQUIRED_SYMBOLS, resample_funding_to_daily
from traderstack.research.funding_carry_cli import load_basis_dir

SYMBOLS = REQUIRED_SYMBOLS


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Paper-perp funding-z harvest dual-print on HL x HTX with required "
            "dual_basis. Pre-registered fund_z_harvest_* catalog. Never flips "
            "PAPER_PROMOTE_*."
        )
    )
    parser.add_argument("--live", action="store_true", help="fetch HL+HTX funding")
    parser.add_argument("--interval", default="1d", choices=("1d",))
    parser.add_argument("--basis-dir", type=Path, default=Path("var/research/basis"))
    parser.add_argument("--fee-bps", type=float, default=DEFAULT_FEE_BPS)
    parser.add_argument("--slippage-bps", type=float, default=DEFAULT_SLIPPAGE_BPS)
    parser.add_argument(
        "--output-md",
        type=Path,
        default=Path("docs/artifacts/strategy-search/fund-z-harvest-paper-perp-dual-print.md"),
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=Path("var/ops/fund_z_harvest_paper_perp_dual_print.json"),
    )
    parser.add_argument("--stdout-md", action="store_true")
    parser.add_argument("--timeout", type=float, default=60.0)
    return parser


async def _fetch_funding(
    timeout: float,
) -> tuple[
    dict[str, tuple[tuple[datetime, float], ...]],
    dict[str, tuple[tuple[datetime, float], ...]],
    list[dict[str, str]],
]:
    notes: list[dict[str, str]] = []
    hl: dict[str, tuple[tuple[datetime, float], ...]] = {}
    htx: dict[str, tuple[tuple[datetime, float], ...]] = {}
    async with httpx.AsyncClient(base_url=HYPERLIQUID_BASE, timeout=timeout) as client:
        for index, symbol in enumerate(SYMBOLS):
            if index:
                await asyncio.sleep(HYPERLIQUID_SYMBOL_PAUSE_SECONDS)
            result = await fetch_hyperliquid_funding(
                symbol,
                client=client,
                lookback_days=HYPERLIQUID_DAILY_LOOKBACK_DAYS,
                limit_pages=HYPERLIQUID_DAILY_LIMIT_PAGES,
            )
            notes.append(result.as_note())
            if result.status == "ok":
                daily = resample_funding_to_daily(result.points)
                hl[symbol.upper()] = daily
                notes.append(
                    {
                        "name": f"hl_funding_daily:{symbol}",
                        "status": "ok",
                        "reason": f"resampled {len(result.points)} -> {len(daily)} UTC daily sums",
                    }
                )
    async with httpx.AsyncClient(base_url=HTX_BASE, timeout=timeout) as client:
        for symbol in SYMBOLS:
            result = await fetch_htx_funding(
                symbol,
                client=client,
                lookback_days=HTX_DAILY_LOOKBACK_DAYS,
                limit_pages=HTX_DAILY_LIMIT_PAGES,
            )
            notes.append(result.as_note())
            if result.status == "ok":
                daily = resample_funding_to_daily(result.points)
                htx[symbol.upper()] = daily
                notes.append(
                    {
                        "name": f"htx_funding_daily:{symbol}",
                        "status": "ok",
                        "reason": f"resampled {len(result.points)} -> {len(daily)} UTC daily sums",
                    }
                )
    return hl, htx, notes


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _ = Settings()  # ensure defaults load; never mutate PAPER_PROMOTE_*
    notes: list[dict[str, str]] = []
    if not args.live:
        notes.append(
            {
                "name": "funding",
                "status": "skipped",
                "reason": "--live required to fetch HL+HTX funding (skip-not-invent)",
            }
        )
        hl: dict[str, tuple[tuple[datetime, float], ...]] = {}
        htx: dict[str, tuple[tuple[datetime, float], ...]] = {}
    else:
        hl, htx, fetch_notes = asyncio.run(_fetch_funding(args.timeout))
        notes.extend(fetch_notes)

    since = datetime.fromisoformat("2020-01-01T00:00:00+00:00")
    until = utc_day(datetime.now(tz=since.tzinfo))
    okx, okx_notes = load_basis_dir(args.basis_dir, "okx", SYMBOLS, since=since, until=until)
    vision, vision_notes = load_basis_dir(
        args.basis_dir, "binance_vision", SYMBOLS, since=since, until=until
    )
    notes.extend(okx_notes)
    notes.extend(vision_notes)

    report = run_fund_z_harvest(
        hl_funding=hl,
        htx_funding=htx,
        okx_basis=okx,
        vision_basis=vision,
        fee_bps=args.fee_bps,
        slippage_bps=args.slippage_bps,
        history_notes=notes,
    )
    md = render_fund_z_harvest_markdown(report)
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
