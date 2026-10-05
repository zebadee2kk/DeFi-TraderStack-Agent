from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import cast

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    and_,
    func,
    insert,
    or_,
    select,
)
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.sql.elements import ColumnElement

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

signal_candidates = Table(
    "signal_candidates",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("event_key", String(64), nullable=False, unique=True, index=True),
    Column("candidate_at", DateTime(timezone=True), nullable=False, index=True),
    Column("asset", String(32), nullable=False, index=True),
    Column("hypothesis_id", String(128), nullable=False, index=True),
    Column("hypothesis_version", String(64), nullable=False),
    Column("horizon_seconds", Integer, nullable=False),
    Column("direction", Integer, nullable=False),
    Column("confidence", Float, nullable=True),
    Column("feature_query_hash", String(128), nullable=False, index=True),
    Column("schema_version", String(32), nullable=False),
)

signal_outcomes = Table(
    "signal_outcomes",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("event_key", String(64), nullable=False, unique=True, index=True),
    Column(
        "candidate_event_key",
        String(64),
        ForeignKey("signal_candidates.event_key"),
        nullable=False,
        index=True,
    ),
    Column("candidate_at", DateTime(timezone=True), nullable=False, index=True),
    Column("outcome_at", DateTime(timezone=True), nullable=False, index=True),
    Column("horizon_seconds", Integer, nullable=False),
    Column("gross_return", Float, nullable=False),
    Column("net_return", Float, nullable=False),
    Column("gross_pnl_usd", Float, nullable=True),
    Column("net_pnl_usd", Float, nullable=True),
    Column("fee_bps", Float, nullable=False),
    Column("slippage_bps", Float, nullable=False),
    Column("schema_version", String(32), nullable=False),
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


@dataclass(frozen=True)
class WalletObservationQueryResult:
    rows: list[dict[str, object]]
    complete: bool
    available_count: int
    pages: int
    first_available_at: datetime | None
    last_available_at: datetime | None
    first_evaluated_at: datetime | None
    last_evaluated_at: datetime | None

    def coverage(self) -> dict[str, object]:
        return {
            "complete": self.complete,
            "available_count": self.available_count,
            "evaluated_count": len(self.rows),
            "pages": self.pages,
            "first_available_at": self.first_available_at,
            "last_available_at": self.last_available_at,
            "first_evaluated_at": self.first_evaluated_at,
            "last_evaluated_at": self.last_evaluated_at,
        }


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

    async def append_intelligence_observations(self, rows: list[dict[str, object]]) -> int:
        if not rows:
            return 0
        by_key = {str(row["event_key"]): row for row in rows}
        keys = list(by_key)
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
            fresh = [row for key, row in by_key.items() if key not in existing]
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
        statement = statement.order_by(
            intelligence_observations.c.observed_at.asc(),
            intelligence_observations.c.source_id.asc(),
            intelligence_observations.c.observation_type.asc(),
            intelligence_observations.c.event_key.asc(),
        ).limit(limit)
        async with self._engine().connect() as connection:
            rows = (await connection.execute(statement)).mappings().all()
        return [dict(row) for row in rows]

    async def append_signal_candidates(self, rows: list[dict[str, object]]) -> int:
        if not rows:
            return 0
        by_key = {str(row["event_key"]): row for row in rows}
        keys = list(by_key)
        async with self._engine().begin() as connection:
            existing = set(
                (
                    await connection.execute(
                        select(signal_candidates.c.event_key).where(
                            signal_candidates.c.event_key.in_(keys)
                        )
                    )
                ).scalars()
            )
            fresh = [row for key, row in by_key.items() if key not in existing]
            if fresh:
                await connection.execute(insert(signal_candidates).values(fresh))
        return len(fresh)

    async def append_signal_outcomes(self, rows: list[dict[str, object]]) -> int:
        if not rows:
            return 0
        candidate_keys = {str(row["candidate_event_key"]) for row in rows}
        by_key = {str(row["event_key"]): row for row in rows}
        keys = list(by_key)
        async with self._engine().begin() as connection:
            known_candidates = set(
                (
                    await connection.execute(
                        select(signal_candidates.c.event_key).where(
                            signal_candidates.c.event_key.in_(candidate_keys)
                        )
                    )
                ).scalars()
            )
            missing = candidate_keys - known_candidates
            if missing:
                raise ValueError(
                    "signal outcome references unknown candidate event key(s): "
                    + ", ".join(sorted(missing))
                )
            existing = set(
                (
                    await connection.execute(
                        select(signal_outcomes.c.event_key).where(
                            signal_outcomes.c.event_key.in_(keys)
                        )
                    )
                ).scalars()
            )
            fresh = [row for key, row in by_key.items() if key not in existing]
            if fresh:
                await connection.execute(insert(signal_outcomes).values(fresh))
        return len(fresh)

    async def load_signal_dataset(
        self,
        *,
        asset: str | None = None,
        hypothesis_id: str | None = None,
        candidate_start: datetime | None = None,
        candidate_end: datetime | None = None,
        limit: int = 10000,
    ) -> list[dict[str, object]]:
        if limit <= 0:
            raise ValueError("limit must be positive")
        statement = (
            select(
                signal_candidates,
                signal_outcomes.c.outcome_at,
                signal_outcomes.c.gross_return,
                signal_outcomes.c.net_return,
                signal_outcomes.c.gross_pnl_usd,
                signal_outcomes.c.net_pnl_usd,
                signal_outcomes.c.fee_bps,
                signal_outcomes.c.slippage_bps,
                signal_outcomes.c.schema_version.label("outcome_schema_version"),
            )
            .join(
                signal_outcomes,
                signal_outcomes.c.candidate_event_key == signal_candidates.c.event_key,
            )
            .where(signal_outcomes.c.outcome_at >= signal_candidates.c.candidate_at)
        )
        if asset is not None:
            statement = statement.where(signal_candidates.c.asset == asset.upper())
        if hypothesis_id is not None:
            statement = statement.where(signal_candidates.c.hypothesis_id == hypothesis_id)
        if candidate_start is not None:
            statement = statement.where(signal_candidates.c.candidate_at >= candidate_start)
        if candidate_end is not None:
            statement = statement.where(signal_candidates.c.candidate_at <= candidate_end)
        statement = statement.order_by(
            signal_candidates.c.candidate_at.asc(),
            signal_candidates.c.id.asc(),
        ).limit(limit)
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

    def _wallet_observation_filters(
        self,
        *,
        wallet: str | None,
        observation_type: str | None,
    ) -> list[ColumnElement[bool]]:
        filters: list[ColumnElement[bool]] = []
        if wallet is not None:
            filters.append(wallet_observations.c.wallet == wallet.lower())
        if observation_type is not None:
            filters.append(wallet_observations.c.observation_type == observation_type)
        return filters

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
        filters = self._wallet_observation_filters(
            wallet=wallet,
            observation_type=observation_type,
        )
        if filters:
            statement = statement.where(*filters)
        statement = statement.order_by(
            wallet_observations.c.observed_at.asc(),
            wallet_observations.c.id.asc(),
        ).limit(limit)
        async with self._engine().connect() as connection:
            rows = (await connection.execute(statement)).mappings().all()
        return [dict(row) for row in rows]

    async def load_wallet_observations_complete(
        self,
        *,
        wallet: str | None = None,
        observation_type: str | None = None,
        page_size: int = 5000,
        max_rows: int = 1_000_000,
    ) -> WalletObservationQueryResult:
        if page_size <= 0:
            raise ValueError("page_size must be positive")
        if max_rows <= 0:
            raise ValueError("max_rows must be positive")

        filters = self._wallet_observation_filters(
            wallet=wallet,
            observation_type=observation_type,
        )
        stats = select(
            func.count(wallet_observations.c.id),
            func.min(wallet_observations.c.observed_at),
            func.max(wallet_observations.c.observed_at),
        )
        if filters:
            stats = stats.where(*filters)

        rows: list[dict[str, object]] = []
        pages = 0
        cursor_time: datetime | None = None
        cursor_id: int | None = None

        async with self._engine().connect() as connection:
            available_count_raw, first_available_raw, last_available_raw = (
                await connection.execute(stats)
            ).one()
            available_count = int(available_count_raw)
            first_available_at = cast(datetime | None, first_available_raw)
            last_available_at = cast(datetime | None, last_available_raw)

            while len(rows) < min(available_count, max_rows):
                statement = select(wallet_observations)
                if filters:
                    statement = statement.where(*filters)
                if cursor_time is not None and cursor_id is not None:
                    statement = statement.where(
                        or_(
                            wallet_observations.c.observed_at > cursor_time,
                            and_(
                                wallet_observations.c.observed_at == cursor_time,
                                wallet_observations.c.id > cursor_id,
                            ),
                        )
                    )
                remaining = max_rows - len(rows)
                statement = statement.order_by(
                    wallet_observations.c.observed_at.asc(),
                    wallet_observations.c.id.asc(),
                ).limit(min(page_size, remaining))
                page = (await connection.execute(statement)).mappings().all()
                if not page:
                    break
                pages += 1
                rows.extend(dict(row) for row in page)
                last = page[-1]
                cursor_time = last["observed_at"]
                cursor_id = int(last["id"])

        complete = len(rows) == available_count
        return WalletObservationQueryResult(
            rows=rows,
            complete=complete,
            available_count=available_count,
            pages=pages,
            first_available_at=first_available_at,
            last_available_at=last_available_at,
            first_evaluated_at=(cast(datetime, rows[0]["observed_at"]) if rows else None),
            last_evaluated_at=(cast(datetime, rows[-1]["observed_at"]) if rows else None),
        )

    async def close(self) -> None:
        if self.engine is not None:
            await self.engine.dispose()
