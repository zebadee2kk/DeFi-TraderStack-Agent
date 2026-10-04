from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime
from typing import TypedDict

from traderstack.config import Settings
from traderstack.signal_warehouse import PostgresSignalWarehouse


class CoverageBucket(TypedDict):
    rows: int
    first: datetime
    last: datetime


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Report signal-warehouse feature coverage.")
    parser.add_argument("--asset")
    parser.add_argument("--limit", type=int, default=100000)
    return parser


async def _run(args: argparse.Namespace) -> int:
    if args.limit <= 0 or args.limit > 100000:
        raise ValueError("limit must be between 1 and 100000")

    settings = Settings()
    warehouse = PostgresSignalWarehouse(settings.database_url)
    try:
        rows = await warehouse.load_features(asset=args.asset, limit=args.limit)
        health_rows = await warehouse.load_collector_health(limit=args.limit)
    finally:
        await warehouse.close()

    assets: dict[str, CoverageBucket] = {}
    sources: dict[str, int] = {}
    for row in rows:
        asset = str(row["asset"])
        observed_at = row["observed_at"]
        if not isinstance(observed_at, datetime):
            raise TypeError("warehouse observed_at must be a datetime")

        bucket = assets.setdefault(
            asset,
            {"rows": 0, "first": observed_at, "last": observed_at},
        )
        bucket["rows"] += 1
        bucket["first"] = min(bucket["first"], observed_at)
        bucket["last"] = max(bucket["last"], observed_at)

        raw_source_ids = row.get("source_ids")
        if raw_source_ids is None:
            continue
        if not isinstance(raw_source_ids, list):
            raise TypeError("warehouse source_ids must be a list")
        for source_id in raw_source_ids:
            source = str(source_id)
            sources[source] = sources.get(source, 0) + 1

    provider_health: dict[str, dict[str, object]] = {}
    for row in health_rows:
        provider = str(row["provider"])
        observed_at = row["observed_at"]
        if not isinstance(observed_at, datetime):
            raise TypeError("collector health observed_at must be a datetime")
        state = str(row["state"])
        bucket = provider_health.setdefault(
            provider,
            {
                "rows": 0,
                "first": observed_at,
                "last": observed_at,
                "latest_state": state,
            },
        )
        bucket["rows"] = int(bucket["rows"]) + 1
        if observed_at < bucket["first"]:
            bucket["first"] = observed_at
        if observed_at >= bucket["last"]:
            bucket["last"] = observed_at
            bucket["latest_state"] = state

    serializable_health = {
        provider: {
            "rows": int(bucket["rows"]),
            "first": bucket["first"].isoformat(),
            "last": bucket["last"].isoformat(),
            "latest_state": str(bucket["latest_state"]),
        }
        for provider, bucket in provider_health.items()
    }

    serializable_assets = {
        asset: {
            "rows": bucket["rows"],
            "first": bucket["first"].isoformat(),
            "last": bucket["last"].isoformat(),
        }
        for asset, bucket in assets.items()
    }

    print(
        json.dumps(
            {
                "rows": len(rows),
                "assets": serializable_assets,
                "sources": dict(sorted(sources.items())),
                "collector_health": dict(sorted(serializable_health.items())),
            },
            sort_keys=True,
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
