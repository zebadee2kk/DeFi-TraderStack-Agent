from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from traderstack.config import Settings
from traderstack.provider_health_journal import (
    DEFAULT_PROVIDER_HEALTH_PATH,
    ProviderHealthEvent,
    load_provider_health_events,
)
from traderstack.signal_warehouse import PostgresSignalWarehouse


def health_event_key(event: ProviderHealthEvent) -> str:
    canonical = json.dumps(
        {
            "observed_at": event.observed_at.isoformat(),
            "provider": event.provider,
            "state": event.state,
            "consecutive_failures": event.consecutive_failures,
            "last_latency_seconds": event.last_latency_seconds,
            "last_success_at": (
                event.last_success_at.isoformat() if event.last_success_at is not None else None
            ),
            "last_error": event.last_error,
            "calls_last_minute": event.calls_last_minute,
            "calls_today": event.calls_today,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def health_event_row(event: ProviderHealthEvent) -> dict[str, object]:
    payload = asdict(event)
    payload["observed_at"] = event.observed_at.isoformat()
    payload["last_success_at"] = (
        event.last_success_at.isoformat() if event.last_success_at is not None else None
    )
    return {
        "event_key": health_event_key(event),
        "observed_at": event.observed_at,
        "provider": event.provider,
        "state": event.state,
        "payload": payload,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Import append-only provider-health journal rows into the signal warehouse."
    )
    parser.add_argument(
        "--journal",
        type=Path,
        default=DEFAULT_PROVIDER_HEALTH_PATH,
        help="provider health JSONL journal",
    )
    return parser


async def _run(args: argparse.Namespace) -> int:
    events = load_provider_health_events(args.journal)
    rows = [health_event_row(event) for event in events]
    warehouse = PostgresSignalWarehouse(Settings().database_url)
    await warehouse.initialize()
    try:
        inserted = await warehouse.append_collector_health(rows)
    finally:
        await warehouse.close()

    print(
        json.dumps(
            {
                "journal": str(args.journal),
                "events_read": len(events),
                "rows_inserted": inserted,
            },
            sort_keys=True,
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(_run(build_parser().parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
