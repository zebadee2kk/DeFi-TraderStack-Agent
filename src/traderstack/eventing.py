import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from redis.asyncio import Redis
from sqlalchemy import JSON, Column, DateTime, Integer, MetaData, String, Table, insert
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
    Column("payload", JSON, nullable=False),
)


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
            payload=payload,
        )
        async with self._engine().begin() as connection:
            await connection.execute(statement)

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
        outcomes = await asyncio.gather(
            *(sink(result) for sink in self.sinks), return_exceptions=True
        )
        failures = [outcome for outcome in outcomes if isinstance(outcome, BaseException)]
        if failures:
            raise RuntimeError(f"{len(failures)} runtime event sink(s) failed") from failures[0]
