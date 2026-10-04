from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

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


def build_feature_rows(result: RuntimeResult) -> tuple[dict[str, object] | None, list[dict[str, object]]]:
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
        if feature_row is None:
            return
        async with self._engine().begin() as connection:
            await connection.execute(insert(feature_snapshots).values(feature_row))
            if provider_rows:
                await connection.execute(insert(provider_observations).values(provider_rows))

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

    async def close(self) -> None:
        if self.engine is not None:
            await self.engine.dispose()
