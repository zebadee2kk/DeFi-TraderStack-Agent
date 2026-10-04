from __future__ import annotations

import argparse
import asyncio
import json

from traderstack.config import Settings
from traderstack.signal_warehouse import PostgresSignalWarehouse


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
    finally:
        await warehouse.close()

    if not rows:
        print(json.dumps({"rows": 0, "assets": {}, "sources": {}}, sort_keys=True))
        return 0

    assets: dict[str, dict[str, object]] = {}
    sources: dict[str, int] = {}
    for row in rows:
        asset = str(row["asset"])
        observed_at = row["observed_at"]
        bucket = assets.setdefault(asset, {"rows": 0, "first": observed_at, "last": observed_at})
        bucket["rows"] = int(bucket["rows"]) + 1
        bucket["first"] = min(bucket["first"], observed_at)
        bucket["last"] = max(bucket["last"], observed_at)

        for source_id in row.get("source_ids", []) or []:
            source = str(source_id)
            sources[source] = sources.get(source, 0) + 1

    for bucket in assets.values():
        for key in ("first", "last"):
            value = bucket[key]
            bucket[key] = value.isoformat() if hasattr(value, "isoformat") else str(value)

    print(
        json.dumps(
            {
                "rows": len(rows),
                "assets": assets,
                "sources": dict(sorted(sources.items())),
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
