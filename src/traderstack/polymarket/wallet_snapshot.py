from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Awaitable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from traderstack.config import Settings
from traderstack.market.registry import ProviderRegistry
from traderstack.polymarket.data_api import PolymarketDataClient, wallet_from_leaderboard_row
from traderstack.provider_health_journal import DEFAULT_PROVIDER_HEALTH_PATH, ProviderHealthJournal
from traderstack.signal_warehouse import PostgresSignalWarehouse


@dataclass(frozen=True)
class SnapshotSummary:
    leaderboard_rows: int
    wallets_discovered: int
    observations_written: int
    endpoint_errors: int


def _observation(
    *,
    wallet: str,
    observation_type: str,
    source_id: str,
    payload: Any,
    observed_at: datetime | None = None,
) -> dict[str, object]:
    return {
        "observed_at": observed_at or datetime.now(UTC),
        "wallet": wallet.lower(),
        "observation_type": observation_type,
        "source_id": source_id,
        "payload": payload,
    }


async def _capture(
    *,
    wallet: str,
    batch: list[dict[str, object]],
    observation_type: str,
    source_id: str,
    fetch: Awaitable[Any],
) -> bool:
    try:
        payload = await fetch
    except Exception as exc:  # noqa: BLE001 - preserve cohort membership on partial failure.
        batch.append(
            _observation(
                wallet=wallet,
                observation_type=f"{observation_type}_error",
                source_id=source_id,
                payload={"error_type": type(exc).__name__},
            )
        )
        return False

    batch.append(
        _observation(
            wallet=wallet,
            observation_type=observation_type,
            source_id=source_id,
            payload=payload,
        )
    )
    return True


async def collect_wallet_snapshot(
    *,
    client: PolymarketDataClient,
    warehouse: PostgresSignalWarehouse,
    category: str,
    time_period: str,
    limit: int,
    max_pages: int,
) -> SnapshotSummary:
    leaderboard = await client.leaderboard(
        category=category,
        time_period=time_period,
        order_by="PNL",
        limit=limit,
    )
    wallets: list[tuple[str, dict[str, Any]]] = []
    seen: set[str] = set()
    for row in leaderboard:
        wallet = wallet_from_leaderboard_row(row)
        if wallet is None or wallet in seen:
            continue
        seen.add(wallet)
        wallets.append((wallet, row))

    written = 0
    errors = 0
    for wallet, leaderboard_row in wallets:
        batch: list[dict[str, object]] = [
            _observation(
                wallet=wallet,
                observation_type="leaderboard",
                source_id="polymarket:data-api:/v1/leaderboard",
                payload={
                    "category": category.upper(),
                    "time_period": time_period.upper(),
                    "order_by": "PNL",
                    "row": leaderboard_row,
                },
            )
        ]

        calls: tuple[tuple[str, str, Awaitable[Any]], ...] = (
            (
                "user_stats",
                "polymarket:data-api:/v2/user-stats",
                client.user_stats(wallet),
            ),
            (
                "user_pnl",
                "polymarket:data-api:/v2/user-pnl",
                client.user_pnl(wallet),
            ),
            (
                "portfolio_value",
                "polymarket:data-api:/v2/value",
                client.value(wallet),
            ),
            (
                "positions_open",
                "polymarket:data-api:/v2/positions?status=OPEN",
                client.positions(wallet, status="OPEN", max_pages=max_pages),
            ),
            (
                "positions_closed",
                "polymarket:data-api:/v2/positions?status=CLOSED",
                client.positions(wallet, status="CLOSED", max_pages=max_pages),
            ),
            (
                "trades",
                "polymarket:data-api:/v2/trades",
                client.trades(wallet, max_pages=max_pages),
            ),
        )

        for observation_type, source_id, fetch in calls:
            if not await _capture(
                wallet=wallet,
                batch=batch,
                observation_type=observation_type,
                source_id=source_id,
                fetch=fetch,
            ):
                errors += 1

        await warehouse.append_wallet_observations(batch)
        written += len(batch)

    return SnapshotSummary(
        leaderboard_rows=len(leaderboard),
        wallets_discovered=len(wallets),
        observations_written=written,
        endpoint_errors=errors,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Collect a bounded, read-only Polymarket wallet research snapshot."
    )
    parser.add_argument("--category", default="OVERALL")
    parser.add_argument("--time-period", default="MONTH", choices=("DAY", "WEEK", "MONTH", "ALL"))
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--max-pages", type=int, default=2)
    return parser


async def _run(args: argparse.Namespace) -> int:
    if args.limit <= 0 or args.limit > 25:
        raise ValueError("limit must be between 1 and 25")
    if args.max_pages <= 0 or args.max_pages > 10:
        raise ValueError("max-pages must be between 1 and 10")

    settings = Settings()
    registry = ProviderRegistry(
        name="polymarket_data",
        timeout_seconds=min(settings.provider_timeout_seconds, 20.0),
        calls_per_minute=120,
        failure_threshold=3,
        health_recorder=ProviderHealthJournal(DEFAULT_PROVIDER_HEALTH_PATH).record,
    )
    client = PolymarketDataClient(registry=registry)
    warehouse = PostgresSignalWarehouse(settings.database_url)
    await warehouse.initialize()
    try:
        summary = await collect_wallet_snapshot(
            client=client,
            warehouse=warehouse,
            category=args.category,
            time_period=args.time_period,
            limit=args.limit,
            max_pages=args.max_pages,
        )
    finally:
        await warehouse.close()

    print(json.dumps(asdict(summary), sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(_run(build_parser().parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
