from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    select,
)
from sqlalchemy.dialects.postgresql import Insert as PostgresInsert
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from traderstack.candles import Candle

metadata = MetaData()
candles_table = Table(
    "candles",
    metadata,
    Column("symbol", String(32), nullable=False),
    Column("interval", String(16), nullable=False),
    Column("opened_at", DateTime(timezone=True), nullable=False),
    Column("open", Float, nullable=False),
    Column("high", Float, nullable=False),
    Column("low", Float, nullable=False),
    Column("close", Float, nullable=False),
    Column("volume", Float, nullable=False),
    UniqueConstraint("symbol", "interval", "opened_at", name="uq_candle_identity"),
)


def build_upsert_statement(candles: tuple[Candle, ...]) -> PostgresInsert | None:
    """Build the batch ``INSERT ... ON CONFLICT DO NOTHING`` statement for ``candles``.

    Pure and DB-free by design so the statement shape (columns, values, the
    conflict target) can be unit-tested without a running PostgreSQL. Returns
    None for an empty batch.
    """

    if not candles:
        return None
    rows = [
        {
            "symbol": candle.symbol.upper(),
            "interval": candle.interval,
            "opened_at": candle.opened_at,
            "open": candle.open,
            "high": candle.high,
            "low": candle.low,
            "close": candle.close,
            "volume": candle.volume,
        }
        for candle in candles
    ]
    statement = pg_insert(candles_table).values(rows)
    return statement.on_conflict_do_nothing(
        index_elements=[
            candles_table.c.symbol,
            candles_table.c.interval,
            candles_table.c.opened_at,
        ]
    )


@dataclass
class PostgresCandleStore:
    database_url: str
    engine: AsyncEngine | None = None

    def _engine(self) -> AsyncEngine:
        if self.engine is None:
            self.engine = create_async_engine(self.database_url, pool_pre_ping=True)
        return self.engine

    async def initialize(self) -> None:
        async with self._engine().begin() as connection:
            await connection.run_sync(metadata.create_all)

    async def append_many(self, candles: tuple[Candle, ...]) -> None:
        """Batch-insert candles, silently skipping any that already exist.

        Uses a single PostgreSQL ``INSERT ... ON CONFLICT (symbol, interval,
        opened_at) DO NOTHING`` statement instead of a per-row
        select-then-insert, so appending a full history batch costs one round
        trip regardless of how many candles are already deduplicated.
        """

        statement = build_upsert_statement(candles)
        if statement is None:
            return
        async with self._engine().begin() as connection:
            await connection.execute(statement)

    async def load(
        self,
        symbol: str,
        interval: str,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int | None = None,
    ) -> tuple[Candle, ...]:
        statement = select(candles_table).where(
            candles_table.c.symbol == symbol.upper(),
            candles_table.c.interval == interval,
        )
        if start is not None:
            statement = statement.where(candles_table.c.opened_at >= start)
        if end is not None:
            statement = statement.where(candles_table.c.opened_at <= end)
        statement = statement.order_by(candles_table.c.opened_at.asc())
        if limit is not None:
            if limit <= 0:
                raise ValueError("limit must be positive")
            statement = statement.limit(limit)
        async with self._engine().connect() as connection:
            rows = (await connection.execute(statement)).mappings().all()
        return tuple(
            Candle(
                symbol=row["symbol"],
                interval=row["interval"],
                opened_at=row["opened_at"],
                open=row["open"],
                high=row["high"],
                low=row["low"],
                close=row["close"],
                volume=row["volume"],
            )
            for row in rows
        )

    async def close(self) -> None:
        if self.engine is not None:
            await self.engine.dispose()
