from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from traderstack.config import Settings
from traderstack.signal_warehouse import PostgresSignalWarehouse


@dataclass(frozen=True)
class WarehouseExportSpec:
    asset: str | None
    start: datetime | None
    end: datetime | None
    limit: int
    dataset: Literal["features", "intelligence", "signals"] = "features"
    hypothesis_id: str | None = None

    def canonical_json(self) -> str:
        query: dict[str, object] = {
            "asset": self.asset.upper() if self.asset else None,
            "start": self.start.astimezone(UTC).isoformat() if self.start else None,
            "end": self.end.astimezone(UTC).isoformat() if self.end else None,
            "limit": self.limit,
        }
        # Preserve the original feature-export query hash contract.
        if self.dataset != "features":
            query["dataset"] = self.dataset
        if self.dataset == "signals":
            query["hypothesis_id"] = self.hypothesis_id
        return json.dumps(query, sort_keys=True, separators=(",", ":"))

    def query_hash(self) -> str:
        return "sha256:" + hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


def _parse_dt(value: str | None) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export point-in-time signal-warehouse rows.")
    parser.add_argument("--asset")
    parser.add_argument("--start", help="ISO-8601 inclusive lower bound")
    parser.add_argument("--end", help="ISO-8601 inclusive upper bound")
    parser.add_argument("--limit", type=int, default=10000)
    parser.add_argument(
        "--dataset",
        choices=("features", "intelligence", "signals"),
        default="features",
        help=(
            "export canonical features, provider-native intelligence, or "
            "matured signal candidate/outcome rows"
        ),
    )
    parser.add_argument("--hypothesis-id", help="optional signal hypothesis filter")
    parser.add_argument("--output", type=Path, required=True)
    return parser


async def _run(args: argparse.Namespace) -> int:
    if args.limit <= 0 or args.limit > 100000:
        raise ValueError("limit must be between 1 and 100000")

    spec = WarehouseExportSpec(
        asset=args.asset,
        start=_parse_dt(args.start),
        end=_parse_dt(args.end),
        limit=args.limit,
        dataset=args.dataset,
        hypothesis_id=args.hypothesis_id,
    )
    if spec.start is not None and spec.end is not None and spec.start > spec.end:
        raise ValueError("start must be <= end")

    settings = Settings()
    warehouse = PostgresSignalWarehouse(settings.database_url)
    try:
        if spec.dataset == "features":
            rows = await warehouse.load_features(
                asset=spec.asset,
                start=spec.start,
                end=spec.end,
                limit=spec.limit,
            )
        elif spec.dataset == "intelligence":
            rows = await warehouse.load_intelligence_observations(
                asset=spec.asset,
                start=spec.start,
                end=spec.end,
                limit=spec.limit,
            )
        else:
            rows = await warehouse.load_signal_dataset(
                asset=spec.asset,
                hypothesis_id=spec.hypothesis_id,
                candidate_start=spec.start,
                candidate_end=spec.end,
                limit=spec.limit,
            )
    finally:
        await warehouse.close()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        header = {
            "record_type": "warehouse_export_manifest",
            "query_hash": spec.query_hash(),
            "query": json.loads(spec.canonical_json()),
            "row_count": len(rows),
        }
        handle.write(json.dumps(header, sort_keys=True, separators=(",", ":")) + "\n")
        for row in rows:
            serializable = dict(row)
            for field in ("observed_at", "candidate_at", "outcome_at"):
                value = serializable.get(field)
                if isinstance(value, datetime):
                    serializable[field] = value.astimezone(UTC).isoformat()
            handle.write(json.dumps(serializable, sort_keys=True, separators=(",", ":")) + "\n")

    print(
        json.dumps(
            {
                "output": str(args.output),
                "query_hash": spec.query_hash(),
                "row_count": len(rows),
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
