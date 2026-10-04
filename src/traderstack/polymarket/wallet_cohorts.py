from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from traderstack.config import Settings
from traderstack.signal_warehouse import PostgresSignalWarehouse


@dataclass(frozen=True)
class CohortMember:
    snapshot_id: str
    snapshot_at: datetime
    wallet: str
    category: str
    time_period: str
    rank: int | None
    pnl: float | None


@dataclass(frozen=True)
class WalletPersistence:
    wallet: str
    appearances: int
    first_seen: datetime
    last_seen: datetime
    mean_rank: float | None
    best_rank: int | None
    latest_rank: int | None
    latest_pnl: float | None


def _as_float(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _as_int(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _parse_dt(value: object, fallback: datetime) -> datetime:
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            return parsed.astimezone(UTC)
        except ValueError:
            pass
    return fallback.astimezone(UTC)


def leaderboard_member(row: dict[str, object]) -> CohortMember | None:
    if row.get("observation_type") != "leaderboard":
        return None
    observed_at = row.get("observed_at")
    if not isinstance(observed_at, datetime):
        return None
    wallet = row.get("wallet")
    payload = row.get("payload")
    if not isinstance(wallet, str) or not isinstance(payload, dict):
        return None
    leaderboard_row = payload.get("row")
    if not isinstance(leaderboard_row, dict):
        return None

    snapshot_at = _parse_dt(payload.get("snapshot_at"), observed_at)
    snapshot_id_raw = payload.get("snapshot_id")
    snapshot_id = (
        str(snapshot_id_raw)
        if isinstance(snapshot_id_raw, str) and snapshot_id_raw
        else "legacy:" + snapshot_at.replace(second=0, microsecond=0).isoformat()
    )
    return CohortMember(
        snapshot_id=snapshot_id,
        snapshot_at=snapshot_at,
        wallet=wallet.lower(),
        category=str(payload.get("category", "UNKNOWN")).upper(),
        time_period=str(payload.get("time_period", "UNKNOWN")).upper(),
        rank=_as_int(leaderboard_row.get("rank")),
        pnl=_as_float(leaderboard_row.get("pnl")),
    )


def build_persistence(rows: list[dict[str, object]]) -> list[WalletPersistence]:
    members = [member for row in rows if (member := leaderboard_member(row)) is not None]
    by_wallet: dict[str, list[CohortMember]] = {}
    for member in members:
        by_wallet.setdefault(member.wallet, []).append(member)

    output: list[WalletPersistence] = []
    for wallet, items in by_wallet.items():
        ordered = sorted(items, key=lambda item: item.snapshot_at)
        ranks = [item.rank for item in ordered if item.rank is not None]
        output.append(
            WalletPersistence(
                wallet=wallet,
                appearances=len(ordered),
                first_seen=ordered[0].snapshot_at,
                last_seen=ordered[-1].snapshot_at,
                mean_rank=(sum(ranks) / len(ranks)) if ranks else None,
                best_rank=min(ranks) if ranks else None,
                latest_rank=ordered[-1].rank,
                latest_pnl=ordered[-1].pnl,
            )
        )
    return sorted(
        output,
        key=lambda item: (
            -item.appearances,
            item.mean_rank if item.mean_rank is not None else float("inf"),
            item.wallet,
        ),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Rank point-in-time Polymarket leaderboard persistence from stored snapshots."
    )
    parser.add_argument("--category")
    parser.add_argument("--time-period")
    parser.add_argument("--limit", type=int, default=100000)
    parser.add_argument("--top", type=int, default=50)
    return parser


async def _run(args: argparse.Namespace) -> int:
    if args.limit <= 0 or args.limit > 1_000_000:
        raise ValueError("limit must be between 1 and 1000000")
    if args.top <= 0 or args.top > 1000:
        raise ValueError("top must be between 1 and 1000")

    warehouse = PostgresSignalWarehouse(Settings().database_url)
    try:
        rows = await warehouse.load_wallet_observations(
            observation_type="leaderboard",
            limit=args.limit,
        )
    finally:
        await warehouse.close()

    if args.category or args.time_period:
        filtered: list[dict[str, object]] = []
        for row in rows:
            member = leaderboard_member(row)
            if member is None:
                continue
            if args.category and member.category != args.category.upper():
                continue
            if args.time_period and member.time_period != args.time_period.upper():
                continue
            filtered.append(row)
        rows = filtered

    ranked = build_persistence(rows)[: args.top]
    print(
        json.dumps(
            [
                {
                    **asdict(item),
                    "first_seen": item.first_seen.isoformat(),
                    "last_seen": item.last_seen.isoformat(),
                }
                for item in ranked
            ],
            sort_keys=True,
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(_run(build_parser().parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
