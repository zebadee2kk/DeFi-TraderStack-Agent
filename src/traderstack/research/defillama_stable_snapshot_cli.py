"""``traderstack-defillama-stable-snapshot``: PIT snapshot collector.

Fetches public DefiLlama ``/stablecoincharts/all`` and writes an immutable
``as_of=YYYY-MM-DD`` snapshot under ``var/research/defillama/stablecoincharts/``
plus an append-only tip row. Does **not** score dual-prints and never flips
``PAPER_PROMOTE_*``. A single collect day is not a 720-day PIT archive.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx

from traderstack.config import Settings
from traderstack.market.defillama_stable_snapshots import (
    DEFAULT_ARCHIVE_DIR,
    MIN_SNAPSHOT_DAYS,
    coverage,
    render_status_markdown,
    write_snapshot_from_raw,
)
from traderstack.market.defillama_stablecoins import (
    DEFILLAMA_STABLECOINS_BASE,
    STABLECOIN_CHARTS_ALL_PATH,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Collect an operator-dated DefiLlama stablecoin chart snapshot "
            "(as_of = fetch UTC day). Appends tips.jsonl. Does not score "
            "dual-prints. Never flips PAPER_PROMOTE_*."
        )
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="GET https://stablecoins.llama.fi/stablecoincharts/all",
    )
    parser.add_argument(
        "--chart-json",
        type=Path,
        default=None,
        help="offline chart JSON array (still dated as_of=fetch/now UTC day)",
    )
    parser.add_argument(
        "--archive-dir",
        type=Path,
        default=DEFAULT_ARCHIVE_DIR,
        help="root under var/research/ for as_of=* snapshots + tips.jsonl",
    )
    parser.add_argument(
        "--status-md",
        type=Path,
        default=None,
        help="optional STATUS.md path (default: <archive-dir>/STATUS.md)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="operator recovery: allow replace of same as_of (default refuse)",
    )
    parser.add_argument(
        "--fetched-at",
        default=None,
        help="ISO timestamp override for offline tests (UTC)",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="print coverage only; do not fetch or write",
    )
    return parser


async def _fetch_raw() -> list[dict]:
    async with httpx.AsyncClient(
        base_url=DEFILLAMA_STABLECOINS_BASE,
        timeout=90.0,
        headers={"User-Agent": "traderstack-research/0.1"},
    ) as client:
        response = await client.get(STABLECOIN_CHARTS_ALL_PATH)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            raise TypeError("stablecoincharts/all did not return a list")
        return payload


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = Settings()
    mode = getattr(settings.trading_mode, "value", settings.trading_mode)
    if str(mode).lower() != "paper":
        print(f"refuse: TRADING_MODE={mode}; collector is paper-only")
        return 2

    archive_dir: Path = args.archive_dir
    status_md = args.status_md or (archive_dir / "STATUS.md")

    if args.check_only:
        cov = coverage(archive_dir)
        status_md.parent.mkdir(parents=True, exist_ok=True)
        status_md.write_text(render_status_markdown(cov), encoding="utf-8")
        print(
            f"coverage tip_days={cov.tip_days} "
            f"enough_for_dual_print={cov.enough_for_dual_print} "
            f"(min={MIN_SNAPSHOT_DAYS}); wrote {status_md}"
        )
        return 0

    raw: list[dict]
    fetched_at = datetime.now(UTC)
    if args.fetched_at:
        fetched_at = datetime.fromisoformat(args.fetched_at)
        if fetched_at.tzinfo is None:
            fetched_at = fetched_at.replace(tzinfo=UTC)
    if args.chart_json is not None:
        payload = json.loads(args.chart_json.read_text(encoding="utf-8"))
        if isinstance(payload, dict) and "rows" in payload:
            raw = payload["rows"]
        elif isinstance(payload, list):
            raw = payload
        else:
            raise TypeError(f"{args.chart_json}: expected list or {{rows: ...}}")
    elif args.live:
        raw = asyncio.run(_fetch_raw())
        fetched_at = datetime.now(UTC)
    else:
        print("refuse: pass --live or --chart-json (or --check-only)")
        return 2

    try:
        meta, dest, cov = write_snapshot_from_raw(
            archive_dir,
            raw,
            fetched_at=fetched_at,
            force=bool(args.force),
        )
    except FileExistsError as exc:
        print(f"refuse overwrite: {exc}")
        cov = coverage(archive_dir)
        status_md.parent.mkdir(parents=True, exist_ok=True)
        status_md.write_text(render_status_markdown(cov), encoding="utf-8")
        return 1

    status_md.parent.mkdir(parents=True, exist_ok=True)
    status_md.write_text(render_status_markdown(cov), encoding="utf-8")
    print(
        f"wrote snapshot {dest}; as_of={meta.as_of.isoformat()}; "
        f"tip_day={meta.tip_day}; points={meta.point_count}; "
        f"archive tip_days={cov.tip_days}; "
        f"enough_for_dual_print={cov.enough_for_dual_print}; "
        f"status={status_md}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
