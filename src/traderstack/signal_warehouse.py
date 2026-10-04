from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json

from sqlalchemy import JSON, Column, DateTime, Integer, MetaData, String, Table, insert, select
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from traderstack.runtime import RuntimeResult

metadata = MetaData()

feature_snapshots = Table(
    "feature_snapshots",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("observed_at", DateTime(timezone=True), nullable=False, index=True),
    Column("asset", String(32), nullable=False, index=True),
    Column("schema_version", String(32), nullable=False),
    Column("source_ids", JSON, nullable=False),
    Column("payload", JSON, nullable=False),
)

provider_observations = Table(
    "provider_observations",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("observed_at", DateTime(timezone=True), nullable=False, index=True),
    Column("asset", String(32), nullable=False, index=True),
    Column("source_id", String(128), nullable=False, index=True),
    Column("payload", JSON, nullable=False),
)

intelligence_observations = Table(
    "intelligence_observations",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("event_key", String(64), nullable=False, unique=True, index=True),
    Column("observed_at", DateTime(timezone=True), nullable=False, index=True),
    Column("asset", String(32), nullable=False, index=True),
    Column("source_id", String(128), nullable=False, index=True),
    Column("observation_type", String(32), nullable=False, index=True),
    Column("schema_version", String(32), nullable=False),
    Column("payload", JSON, nullable=False),
)

collector_health = Table(
    "collector_health",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("event_key", String(64), nullable=False, unique=True, index=True),
    Column("observed_at", DateTime(timezone=True), nullable=False, index=True),
    Column("provider", String(128), nullable=False, index=True),
    Column("state", String(32), nullable=False, index=True),
    Column("payload", JSON, nullable=False),
)

wallet_observations = Table(
    "wallet_observations",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("observed_at", DateTime(timezone=True), nullable=False, index=True),
    Column("wallet", String(42), nullable=False, index=True),
    Column("observation_type", String(64), nullable=False, index=True),
    Column("source_id", String(128), nullable=False, index=True),
    Column("payload", JSON, nullable=False),
)


def build_feature_rows(
    result: RuntimeResult,
) -> tuple[dict[str, object] | None, list[dict[str, object]]]:
    vector = result.pipeline.feature_vector
    if vector is None:
        return None, []

    payload = vector.model_dump(mode="json")
    feature_row: dict[str, object] = {
        "observed_at": vector.observed_at,
        "asset": vector.asset,
        "schema_version": vector.schema_version,
        "source_ids": list(vector.source_ids),
        "payload": payload,
    }
    provider_rows = [
        {
            "observed_at": vector.observed_at,
            "asset": vector.asset,
            "source_id": source_id,
            "payload": payload,
        }
        for source_id in vector.source_ids
    ]
    return feature_row, provider_rows


def build_intelligence_rows(result: RuntimeResult) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for observation in result.intelligence_observations:
        canonical = observation.model_dump(mode="json")
        encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
        rows.append(
            {
                "event_key": hashlib.sha256(encoded).hexdigest(),
                "observed_at": observation.observed_at,
                "asset": observation.asset.upper(),
                "source_id": observation.source_id,
                "observation_type": observation.observation_type,
                "schema_version": observation.schema_version,
                "payload": dict(observation.payload),
            }
        )
    return rows


@dataclass
class PostgresSignalWarehouse:
    database_url: str
    engine: AsyncEngine | None = None

    def _engine(self) -> AsyncEngine:
        if self.engine is None:
            self.engine = create_async_engine(self.database_url, pool_pre_ping=True)
        return self.engine

    async def initialize(self) -> None:
        async with self._engine().begin() as connection:
            await connection.run_sync(metadata.create_all)

    async def __call__(self, result: RuntimeResult) -> None:
        feature_row, provider_rows = build_feature_rows(result)
        intelligence_rows = build_intelligence_rows(result)
        if feature_row is not None:
            async with self._engine().begin() as connection:
                await connection.execute(insert(feature_snapshots).values(feature_row))
                if provider_rows:
                    await connection.execute(insert(provider_observations).values(provider_rows))
        if intelligence_rows:
            await self.append_intelligence_observations(intelligence_rows)

    async def load_features(
        self,
        *,
        asset: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 1000,
    ) -> list[dict[str, object]]:
        if limit <= 0:
            raise ValueError("limit must be positive")
        statement = select(feature_snapshots)
        if asset is not None:
            statement = statement.where(feature_snapshots.c.asset == asset.upper())
        if start is not None:
            statement = statement.where(feature_snapshots.c.observed_at >= start)
        if end is not None:
            statement = statement.where(feature_snapshots.c.observed_at <= end)
        statement = statement.order_by(feature_snapshots.c.observed_at.asc()).limit(limit)
        async with self._engine().connect() as connection:
            rows = (await connection.execute(statement)).mappings().all()
        return [dict(row) for row in rows]

    async def load_provider_observations(
        self,
        *,
        asset: str | None = None,
        source_id: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 10000,
    ) -> list[dict[str, object]]:
        if limit <= 0:
            raise ValueError("limit must be positive")
        statement = select(provider_observations)
        if asset is not None:
            statement = statement.where(provider_observations.c.asset == asset.upper())
        if source_id is not None:
            statement = statement.where(provider_observations.c.source_id == source_id)
        if start is not None:
            statement = statement.where(provider_observations.c.observed_at >= start)
        if end is not None:
            statement = statement.where(provider_observations.c.observed_at <= end)
        statement = statement.order_by(provider_observations.c.observed_at.asc()).limit(limit)
        async with self._engine().connect() as connection:
            rows = (await connection.execute(statement)).mappings().all()
        return [dict(row) for row in rows]

    async def append_intelligence_observations(
        self, rows: list[dict[str, object]]
    ) -> int:
        if not rows:
            return 0
        keys = [str(row["event_key"]) for row in rows]
        async with self._engine().begin() as connection:
            existing = set(
                (
                    await connection.execute(
                        select(intelligence_observations.c.event_key).where(
                            intelligence_observations.c.event_key.in_(keys)
                        )
                    )
                ).scalars()
            )
            fresh = [row for row in rows if str(row["event_key"]) not in existing]
            if fresh:
                await connection.execute(insert(intelligence_observations).values(fresh))
        return len(fresh)

    async def load_intelligence_observations(
        self,
        *,
        asset: str | None = None,
        source_id: str | None = None,
        observation_type: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 10000,
    ) -> list[dict[str, object]]:
        if limit <= 0:
            raise ValueError("limit must be positive")
        statement = select(intelligence_observations)
        if asset is not None:
            statement = statement.where(intelligence_observations.c.asset == asset.upper())
        if source_id is not None:
            statement = statement.where(intelligence_observations.c.source_id == source_id)
        if observation_type is not None:
            statement = statement.where(
                intelligence_observations.c.observation_type == observation_type
            )
        if start is not None:
            statement = statement.where(intelligence_observations.c.observed_at >= start)
        if end is not None:
            statement = statement.where(intelligence_observations.c.observed_at <= end)
        statement = statement.order_by(intelligence_observations.c.observed_at.asc()).limit(limit)
        async with self._engine().connect() as connection:
            rows = (await connection.execute(statement)).mappings().all()
        return [dict(row) for row in rows]

    async def append_collector_health(self, rows: list[dict[str, object]]) -> int:
        if not rows:
            return 0
        keys = [str(row["event_key"]) for row in rows]
        async with self._engine().begin() as connection:
            existing = set(
                (
                    await connection.execute(
                        select(collector_health.c.event_key).where(
                            collector_health.c.event_key.in_(keys)
                        )
                    )
                ).scalars()
            )
            fresh = [row for row in rows if str(row["event_key"]) not in existing]
            if fresh:
                await connection.execute(insert(collector_health).values(fresh))
        return len(fresh)

    async def load_collector_health(
        self,
        *,
        provider: str | None = None,
        limit: int = 100000,
    ) -> list[dict[str, object]]:
        if limit <= 0:
            raise ValueError("limit must be positive")
        statement = select(collector_health)
        if provider is not None:
            statement = statement.where(collector_health.c.provider == provider)
        statement = statement.order_by(collector_health.c.observed_at.asc()).limit(limit)
        async with self._engine().connect() as connection:
            rows = (await connection.execute(statement)).mappings().all()
        return [dict(row) for row in rows]

    async def append_wallet_observations(self, rows: list[dict[str, object]]) -> None:
        if not rows:
            return
        async with self._engine().begin() as connection:
            await connection.execute(insert(wallet_observations).values(rows))

    async def load_wallet_observations(
        self,
        *,
        wallet: str | None = None,
        observation_type: str | None = None,
        limit: int = 1000,
    ) -> list[dict[str, object]]:
        if limit <= 0:
            raise ValueError("limit must be positive")
        statement = select(wallet_observations)
        if wallet is not None:
            statement = statement.where(wallet_observations.c.wallet == wallet.lower())
        if observation_type is not None:
            statement = statement.where(wallet_observations.c.observation_type == observation_type)
        statement = statement.order_by(wallet_observations.c.observed_at.asc()).limit(limit)
        async with self._engine().connect() as connection:
            rows = (await connection.execute(statement)).mappings().all()
        return [dict(row) for row in rows]

    async def close(self) -> None:
        if self.engine is not None:
            await self.engine.dispose()
