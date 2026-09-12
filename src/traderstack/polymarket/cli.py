"""``traderstack-polymarket-weather-paper``: opt-in paper weather research.

A dedicated process so the crypto paper loop is untouched when this is off.
Always requires ``TRADING_MODE=paper``. Never submits CLOB orders.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from traderstack.config import Settings
from traderstack.killswitch import KillSwitch
from traderstack.logging_config import configure_logging
from traderstack.polymarket.ledger import PolymarketWeatherPaperLedger
from traderstack.polymarket.models import ForecastPoint
from traderstack.polymarket.service import (
    PolymarketWeatherPaperService,
    WeatherCycleReport,
    WeatherFixtures,
    require_paper_trading_mode,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Paper-only Polymarket weather research: compare NWP forecasts to "
            "CLOB mids and record would-trade intents. Never places live orders."
        )
    )
    parser.add_argument(
        "--once",
        action="store_true",
        default=True,
        help="run a single cycle and exit (default)",
    )
    parser.add_argument(
        "--ledger-path",
        default=None,
        help="JSONL paper ledger (default POLYMARKET_WEATHER_LEDGER_PATH)",
    )
    parser.add_argument(
        "--fixtures-dir",
        type=Path,
        default=None,
        help="offline Gamma/CLOB/NWP fixtures (no network)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit machine-readable JSON instead of the table",
    )
    return parser


def load_fixtures(directory: Path) -> WeatherFixtures:
    events = _load_json(directory / "events.json")
    if not isinstance(events, list):
        raise TypeError(f"{directory / 'events.json'}: expected a JSON array")
    mids_raw = _load_json(directory / "mids.json")
    if not isinstance(mids_raw, dict):
        raise TypeError(f"{directory / 'mids.json'}: expected a JSON object")
    mids = {str(key): float(value) for key, value in mids_raw.items()}
    forecasts_raw = _load_json(directory / "forecasts.json")
    if not isinstance(forecasts_raw, dict):
        raise TypeError(f"{directory / 'forecasts.json'}: expected a JSON object")
    forecasts: dict[tuple[str, str], ForecastPoint] = {}
    for key, row in forecasts_raw.items():
        if not isinstance(row, dict):
            raise TypeError(f"forecast {key!r} is not an object")
        point = ForecastPoint.model_validate(row)
        forecasts[(point.city_slug, point.event_date.isoformat())] = point
    return WeatherFixtures(
        events=tuple(row for row in events if isinstance(row, dict)),
        mids=mids,
        forecasts=forecasts,
    )


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _report_json(report: WeatherCycleReport) -> dict[str, Any]:
    return {
        "trading_mode": report.trading_mode,
        "kill_switch_engaged": report.kill_switch_engaged,
        "kill_switch_sources": list(report.kill_switch_sources),
        "cities": list(report.cities),
        "markets_seen": report.markets_seen,
        "parsed": report.parsed,
        "would_trade": report.would_trade,
        "withheld": report.withheld,
        "below_edge": report.below_edge,
        "skipped": report.skipped,
        "venue_submitted": False,
        "execution": "paper_intent_only",
        "intents": [intent.model_dump(mode="json") for intent in report.intents],
        "validation_note": (
            "Claimed weather-market win rates are unproven. See "
            "docs/EVALUATION-FRAMEWORK.md (Polymarket weather A/B)."
        ),
    }


async def _run(args: argparse.Namespace) -> WeatherCycleReport:
    settings = Settings()
    require_paper_trading_mode(settings)
    configure_logging(settings)
    ledger_path = Path(args.ledger_path or settings.polymarket_weather_ledger_path)
    kill_switch = KillSwitch.from_settings(settings)
    fixtures = load_fixtures(args.fixtures_dir) if args.fixtures_dir is not None else None
    service = PolymarketWeatherPaperService.from_settings(
        settings,
        ledger=PolymarketWeatherPaperLedger(ledger_path),
        kill_switch=kill_switch,
        fixtures=fixtures,
    )
    return await service.run_once()


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    report = asyncio.run(_run(args))
    if args.json:
        print(json.dumps(_report_json(report), indent=2, default=str))
    else:
        print(report.render())


if __name__ == "__main__":
    main()
