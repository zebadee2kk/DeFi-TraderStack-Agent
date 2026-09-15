"""``traderstack-polymarket-crypto-collect``: paper-only wedge tape (#142).

A dedicated process, so the crypto paper loop is untouched whether this runs or
not. Always requires ``TRADING_MODE=paper``. Reads public Gamma / CLOB / Deribit
endpoints with GET only, never signs anything, and writes observations to a
JSONL tape. An empty cycle is a successful cycle.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from traderstack.config import Settings
from traderstack.killswitch import KillSwitch
from traderstack.logging_config import configure_logging
from traderstack.polymarket.crypto_models import CRYPTO_WEDGE_RULES, PRIMARY_MODEL_VERSION
from traderstack.polymarket.crypto_service import (
    CryptoWedgeCycleReport,
    CryptoWedgeFixtures,
    PolymarketCryptoWedgeCollector,
)
from traderstack.polymarket.crypto_tape import CryptoWedgeTape
from traderstack.polymarket.service import require_paper_trading_mode


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Paper-only Polymarket crypto-threshold vs Deribit option-implied "
            "wedge tape. Read-only: no CLOB orders, no Deribit private endpoints, "
            "no signing. Evidence only; the evaluator is a later slice."
        )
    )
    parser.add_argument(
        "--once",
        action="store_true",
        default=True,
        help="collect a single point-in-time cycle and exit (default)",
    )
    parser.add_argument(
        "--tape-path",
        default=None,
        help="JSONL wedge tape (default POLYMARKET_CRYPTO_TAPE_PATH)",
    )
    parser.add_argument(
        "--fixtures-dir",
        type=Path,
        default=None,
        help="offline Gamma/CLOB/Deribit/Crucix fixtures (no network)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit machine-readable JSON instead of the table",
    )
    parser.add_argument(
        "--print-rules",
        action="store_true",
        help="print the frozen pre-registered rules and exit",
    )
    return parser


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _require_object(path: Path) -> dict[str, Any]:
    payload = _load_json(path)
    if not isinstance(payload, dict):
        raise TypeError(f"{path}: expected a JSON object")
    return payload


def load_crypto_fixtures(directory: Path) -> CryptoWedgeFixtures:
    events_raw = _require_object(directory / "events.json")
    events: dict[str, list[dict[str, Any]]] = {}
    for slug, rows in events_raw.items():
        if not isinstance(rows, list):
            raise TypeError(f"events.json: {slug!r} is not a JSON array")
        events[str(slug)] = [row for row in rows if isinstance(row, dict)]
    now: datetime | None = None
    now_path = directory / "now.txt"
    if now_path.exists():
        parsed = datetime.fromisoformat(now_path.read_text(encoding="utf-8").strip())
        now = parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
    return CryptoWedgeFixtures(
        events=events,
        books=_require_object(directory / "books.json"),
        deribit_instruments=_require_object(directory / "deribit_instruments.json"),
        deribit_summary=_require_object(directory / "deribit_summary.json"),
        crucix=_require_object(directory / "crucix.json"),
        now=now,
    )


def _report_json(report: CryptoWedgeCycleReport) -> dict[str, Any]:
    return {
        "trading_mode": report.trading_mode,
        "kill_switch_engaged": report.kill_switch_engaged,
        "kill_switch_sources": list(report.kill_switch_sources),
        "observed_at": report.observed_at.isoformat(),
        "assets": list(report.assets),
        "slugs_requested": report.slugs_requested,
        "events_missing": report.events_missing,
        "markets_seen": report.markets_seen,
        "parsed": report.parsed,
        "unparsed": report.unparsed,
        "rows_written": report.rows_written,
        "rows_ok": report.rows_ok,
        "status_counts": dict(report.status_counts),
        "crucix_status": dict(report.crucix_status),
        "chain_errors": dict(report.chain_errors),
        "model_version": PRIMARY_MODEL_VERSION,
        "venue_submitted": False,
        "execution": "paper_tape_only",
        "rows": [row.model_dump(mode="json") for row in report.rows],
        "validation_note": (
            "Evidence only: no PnL, no promotion, no size and no side. "
            "See docs/EVALUATION-FRAMEWORK.md (#142 pre-registered rules)."
        ),
    }


async def _run(args: argparse.Namespace) -> CryptoWedgeCycleReport:
    settings = Settings()
    require_paper_trading_mode(settings)
    configure_logging(settings)
    tape_path = Path(args.tape_path or settings.polymarket_crypto_tape_path)
    kill_switch = KillSwitch.from_settings(settings)
    fixtures = load_crypto_fixtures(args.fixtures_dir) if args.fixtures_dir is not None else None
    collector = PolymarketCryptoWedgeCollector.from_settings(
        settings,
        tape=CryptoWedgeTape(tape_path),
        kill_switch=kill_switch,
        fixtures=fixtures,
    )
    return await collector.run_once()


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if args.print_rules:
        print(CRYPTO_WEDGE_RULES)
        return
    report = asyncio.run(_run(args))
    if args.json:
        print(json.dumps(_report_json(report), indent=2, default=str))
    else:
        print(report.render())


if __name__ == "__main__":
    main()
