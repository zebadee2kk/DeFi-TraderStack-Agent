from __future__ import annotations

from typing import Any

import pytest

from traderstack.polymarket.wallet_snapshot import collect_wallet_snapshot


class FakeClient:
    async def leaderboard(self, **_: Any) -> tuple[dict[str, Any], ...]:
        return (
            {"rank": 1, "proxyWallet": "0x" + "11" * 20, "pnl": 100},
            {"rank": 2, "proxyWallet": "0x" + "22" * 20, "pnl": 50},
        )

    async def user_stats(self, wallet: str) -> dict[str, Any]:
        return {"proxy_wallet": wallet, "all_time_pnl": 123}

    async def user_pnl(self, wallet: str) -> dict[str, Any]:
        return {"proxy_wallet": wallet, "points": [{"timestamp": 1, "realized_pnl": 1}]}

    async def value(self, wallet: str) -> dict[str, Any]:
        return {"proxy_wallet": wallet, "value": 10}

    async def positions(
        self, wallet: str, *, status: str, max_pages: int
    ) -> tuple[dict[str, Any], ...]:
        return ({"wallet": wallet, "status": status, "max_pages": max_pages},)

    async def trades(self, wallet: str, *, max_pages: int) -> tuple[dict[str, Any], ...]:
        return ({"wallet": wallet, "max_pages": max_pages},)


class FakeWarehouse:
    def __init__(self) -> None:
        self.rows: list[dict[str, object]] = []

    async def append_wallet_observations(self, rows: list[dict[str, object]]) -> None:
        self.rows.extend(rows)


@pytest.mark.asyncio
async def test_snapshot_preserves_historical_cohort_and_endpoint_evidence() -> None:
    warehouse = FakeWarehouse()
    summary = await collect_wallet_snapshot(
        client=FakeClient(),  # type: ignore[arg-type]
        warehouse=warehouse,  # type: ignore[arg-type]
        category="CRYPTO",
        time_period="MONTH",
        limit=10,
        max_pages=2,
    )

    assert summary.wallets_discovered == 2
    assert summary.endpoint_errors == 0
    assert summary.observations_written == 14
    assert len(warehouse.rows) == 14
    types = [str(row["observation_type"]) for row in warehouse.rows[:7]]
    assert types == [
        "leaderboard",
        "user_stats",
        "user_pnl",
        "portfolio_value",
        "positions_open",
        "positions_closed",
        "trades",
    ]
    leaderboard_payload = warehouse.rows[0]["payload"]
    assert isinstance(leaderboard_payload, dict)
    assert leaderboard_payload["category"] == "CRYPTO"
    assert leaderboard_payload["time_period"] == "MONTH"
