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


class IntelligenceCoverageBucket(TypedDict):
    rows: int
    first: datetime
    last: datetime
    observation_types: set[str]


class HealthCoverageBucket(TypedDict):
    rows: int
    first: datetime
    last: datetime
    latest_state: str


class SignalCoverageBucket(TypedDict):
    rows: int
    first_candidate_at: datetime
    last_candidate_at: datetime
    first_outcome_at: datetime
    last_outcome_at: datetime


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
        intelligence_rows = await warehouse.load_intelligence_observations(
            asset=args.asset,
            limit=args.limit,
        )
        health_rows = await warehouse.load_collector_health(limit=args.limit)
        signal_rows = await warehouse.load_signal_dataset(
            asset=args.asset,
            limit=args.limit,
        )
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

    intelligence_sources: dict[str, IntelligenceCoverageBucket] = {}
    for row in intelligence_rows:
        source_id = str(row["source_id"])
        observed_at = row["observed_at"]
        if not isinstance(observed_at, datetime):
            raise TypeError("intelligence observed_at must be a datetime")
        observation_type = str(row["observation_type"])
        bucket = intelligence_sources.setdefault(
            source_id,
            {
                "rows": 0,
                "first": observed_at,
                "last": observed_at,
                "observation_types": set(),
            },
        )
        bucket["rows"] += 1
        bucket["first"] = min(bucket["first"], observed_at)
        bucket["last"] = max(bucket["last"], observed_at)
        bucket["observation_types"].add(observation_type)

    provider_health: dict[str, HealthCoverageBucket] = {}
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
        bucket["rows"] += 1
        bucket["first"] = min(bucket["first"], observed_at)
        if observed_at >= bucket["last"]:
            bucket["last"] = observed_at
            bucket["latest_state"] = state

    serializable_intelligence = {
        source_id: {
            "rows": bucket["rows"],
            "first": bucket["first"].isoformat(),
            "last": bucket["last"].isoformat(),
            "observation_types": sorted(bucket["observation_types"]),
        }
        for source_id, bucket in intelligence_sources.items()
    }

    serializable_health = {
        provider: {
            "rows": bucket["rows"],
            "first": bucket["first"].isoformat(),
            "last": bucket["last"].isoformat(),
            "latest_state": bucket["latest_state"],
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

    signal_hypotheses: dict[str, SignalCoverageBucket] = {}
    for row in signal_rows:
        hypothesis_id = str(row["hypothesis_id"])
        candidate_at = row["candidate_at"]
        outcome_at = row["outcome_at"]
        if not isinstance(candidate_at, datetime) or not isinstance(outcome_at, datetime):
            raise TypeError("signal dataset timestamps must be datetimes")
        signal_bucket = signal_hypotheses.setdefault(
            hypothesis_id,
            {
                "rows": 0,
                "first_candidate_at": candidate_at,
                "last_candidate_at": candidate_at,
                "first_outcome_at": outcome_at,
                "last_outcome_at": outcome_at,
            },
        )
        signal_bucket["rows"] += 1
        signal_bucket["first_candidate_at"] = min(signal_bucket["first_candidate_at"], candidate_at)
        signal_bucket["last_candidate_at"] = max(signal_bucket["last_candidate_at"], candidate_at)
        signal_bucket["first_outcome_at"] = min(signal_bucket["first_outcome_at"], outcome_at)
        signal_bucket["last_outcome_at"] = max(signal_bucket["last_outcome_at"], outcome_at)

    serializable_signals = {
        hypothesis_id: {
            "rows": bucket["rows"],
            "first_candidate_at": bucket["first_candidate_at"].isoformat(),
            "last_candidate_at": bucket["last_candidate_at"].isoformat(),
            "first_outcome_at": bucket["first_outcome_at"].isoformat(),
            "last_outcome_at": bucket["last_outcome_at"].isoformat(),
        }
        for hypothesis_id, bucket in signal_hypotheses.items()
    }

    print(
        json.dumps(
            {
                "rows": len(rows),
                "assets": serializable_assets,
                "sources": dict(sorted(sources.items())),
                "intelligence_sources": dict(sorted(serializable_intelligence.items())),
                "collector_health": dict(sorted(serializable_health.items())),
                "signal_outcomes": dict(sorted(serializable_signals.items())),
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
