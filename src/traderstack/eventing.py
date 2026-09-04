import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from redis.asyncio import Redis
from sqlalchemy import JSON, Column, DateTime, Integer, MetaData, String, Table, insert, select
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from traderstack.runtime import RuntimeResult

ResultSink = Callable[[RuntimeResult], Awaitable[None]]
metadata = MetaData()
runtime_events = Table(
    "runtime_events",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("observed_at", DateTime(timezone=True), nullable=False, index=True),
    Column("symbol", String(32), nullable=False, index=True),
    Column("accepted_market_data", Integer, nullable=False),
    # --- observability (Epic 9): decision-to-fill trace view, as a query ---
    # Nullable: most-rejected cycles never produce a proposal/decision.
    Column("decision_id", String(64), nullable=True, index=True),
    # --- end observability (Epic 9) ---
    Column("payload", JSON, nullable=False),
)


def _decision_id_of(result: RuntimeResult) -> str | None:
    """The decision id a runtime event belongs to, if any (proposal or paper order)."""

    if result.pipeline.proposal is not None:
        return str(result.pipeline.proposal.decision_id)
    if result.pipeline.paper_order is not None:
        return str(result.pipeline.paper_order.decision_id)
    return None


@dataclass
class PostgresRuntimeEventStore:
    database_url: str
    engine: AsyncEngine | None = None

    def _engine(self) -> AsyncEngine:
        if self.engine is None:
            self.engine = create_async_engine(self.database_url, pool_pre_ping=True)
        return self.engine

    async def initialize(self) -> None:
        engine = self._engine()
        async with engine.begin() as connection:
            await connection.run_sync(metadata.create_all)

    async def __call__(self, result: RuntimeResult) -> None:
        payload = result.model_dump(mode="json")
        statement = insert(runtime_events).values(
            observed_at=datetime.now(UTC),
            symbol=result.tick.symbol,
            accepted_market_data=int(result.pipeline.accepted_market_data),
            decision_id=_decision_id_of(result),  # observability (Epic 9)
            payload=payload,
        )
        async with self._engine().begin() as connection:
            await connection.execute(statement)

    # --- observability (Epic 9): decision-to-fill trace view, as queries ---

    async def recent(self, symbol: str, limit: int = 20) -> list[RuntimeResult]:
        """The most recent persisted runtime events for one symbol, newest first."""

        if limit <= 0:
            raise ValueError("limit must be positive")
        statement = (
            select(runtime_events)
            .where(runtime_events.c.symbol == symbol)
            .order_by(runtime_events.c.observed_at.desc(), runtime_events.c.id.desc())
            .limit(limit)
        )
        async with self._engine().connect() as connection:
            rows = (await connection.execute(statement)).mappings().all()
        return [RuntimeResult.model_validate(row["payload"]) for row in rows]

    async def decision_trace(self, decision_id: str) -> list[RuntimeResult]:
        """Every persisted runtime event for one decision, in chronological order.

        This is the "decision-to-fill trace view" backlog item expressed as a
        query: every cycle whose proposal or paper order carried this
        decision_id, oldest first, so a caller can follow the full
        signal -> proposal -> risk decision -> paper order path for one trade.
        """

        statement = (
            select(runtime_events)
            .where(runtime_events.c.decision_id == decision_id)
            .order_by(runtime_events.c.observed_at.asc(), runtime_events.c.id.asc())
        )
        async with self._engine().connect() as connection:
            rows = (await connection.execute(statement)).mappings().all()
        return [RuntimeResult.model_validate(row["payload"]) for row in rows]

    # --- end observability (Epic 9) ---

    async def close(self) -> None:
        if self.engine is not None:
            await self.engine.dispose()


@dataclass
class RedisRuntimePublisher:
    redis_url: str
    channel: str = "traderstack.runtime"
    client: Redis | None = None

    def _client(self) -> Redis:
        if self.client is None:
            self.client = Redis.from_url(self.redis_url, decode_responses=True)
        return self.client

    async def __call__(self, result: RuntimeResult) -> None:
        payload = json.dumps(result.model_dump(mode="json"), separators=(",", ":"))
        await self._client().publish(self.channel, payload)

    async def close(self) -> None:
        if self.client is not None:
            await self.client.aclose()


@dataclass(frozen=True)
class FanoutResultSink:
    sinks: tuple[ResultSink, ...]

    async def __call__(self, result: RuntimeResult) -> None:
        outcomes = await asyncio.gather(*(sink(result) for sink in self.sinks), return_exceptions=True)
        failures = [outcome for outcome in outcomes if isinstance(outcome, BaseException)]
        if failures:
            raise RuntimeError(f"{len(failures)} runtime event sink(s) failed") from failures[0]
