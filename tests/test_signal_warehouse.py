from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from traderstack.features import AssetFeatureVector, MarketFeatures
from traderstack.intelligence import IntelligenceObservation
from traderstack.market.models import MarketSource, MarketTick
from traderstack.pipeline import PipelineResult
from traderstack.runtime import RuntimeResult
from traderstack.signal_warehouse import (
    PostgresSignalWarehouse,
    build_feature_rows,
    build_intelligence_rows,
    collector_health,
    intelligence_observations,
    metadata,
    wallet_observations,
)


def _result(*, with_features: bool = True) -> RuntimeResult:
    vector = (
        AssetFeatureVector(
            asset="BTC",
            observed_at=datetime(2026, 10, 4, 10, tzinfo=UTC),
            market=MarketFeatures(
                trend_4h=0.1,
                trend_1d=0.2,
                volatility_z=0.3,
                relative_volume=1.2,
                spread_bps=4.0,
            ),
            source_ids=["dune:q1", "crucix:data"],
        )
        if with_features
        else None
    )
    return RuntimeResult(
        tick=MarketTick(
            source=MarketSource.KRAKEN,
            symbol="BTC/USD",
            observed_at=datetime(2026, 10, 4, 10, tzinfo=UTC),
            bid=99,
            ask=101,
            last=100,
        ),
        references=[],
        pipeline=PipelineResult(
            accepted_market_data=with_features,
            feature_vector=vector,
        ),
        intelligence_observations=[
            IntelligenceObservation(
                asset="BTC",
                observed_at=datetime(2026, 10, 4, 9, 59, tzinfo=UTC),
                source_id="crucix:alerts",
                observation_type="news",
                payload={
                    "event_score": 0.8,
                    "adverse_event": True,
                    "item_count": 2,
                },
            )
        ],
    )


def test_build_feature_rows_preserves_point_in_time_payload() -> None:
    row, providers = build_feature_rows(_result())
    assert row is not None
    assert row["asset"] == "BTC"
    assert row["schema_version"] == "1.1"
    assert row["source_ids"] == ["dune:q1", "crucix:data"]
    assert row["payload"]["observed_at"] == "2026-10-04T10:00:00Z"
    assert [item["source_id"] for item in providers] == ["dune:q1", "crucix:data"]


def test_build_feature_rows_skips_rejected_cycle_without_features() -> None:
    row, providers = build_feature_rows(_result(with_features=False))
    assert row is None
    assert providers == []


def test_wallet_observation_table_has_point_in_time_provenance_columns() -> None:
    assert set(wallet_observations.c.keys()) == {
        "id",
        "observed_at",
        "wallet",
        "observation_type",
        "source_id",
        "payload",
    }


def test_collector_health_table_has_idempotency_and_provenance_columns() -> None:
    assert set(collector_health.c.keys()) == {
        "id",
        "event_key",
        "observed_at",
        "provider",
        "state",
        "payload",
    }


def test_build_intelligence_rows_is_deterministic_and_provider_native() -> None:
    first = build_intelligence_rows(_result())
    second = build_intelligence_rows(_result())

    assert first == second
    assert len(first) == 1
    assert first[0]["asset"] == "BTC"
    assert first[0]["source_id"] == "crucix:alerts"
    assert first[0]["observation_type"] == "news"
    assert first[0]["schema_version"] == "1.0"
    assert first[0]["payload"] == {
        "event_score": 0.8,
        "adverse_event": True,
        "item_count": 2,
    }
    assert len(str(first[0]["event_key"])) == 64


def test_intelligence_observation_table_has_idempotency_and_provenance_columns() -> None:
    assert set(intelligence_observations.c.keys()) == {
        "id",
        "event_key",
        "observed_at",
        "asset",
        "source_id",
        "observation_type",
        "schema_version",
        "payload",
    }


@pytest.mark.asyncio
async def test_complete_wallet_history_reads_beyond_old_100k_boundary() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    warehouse = PostgresSignalWarehouse("sqlite+aiosqlite:///:memory:", engine=engine)
    async with engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
        start = datetime(2026, 1, 1, tzinfo=UTC)
        rows = [
            {
                "observed_at": start + timedelta(seconds=index // 100),
                "wallet": "0x" + f"{index % 1000:040x}",
                "observation_type": "trades",
                "source_id": "polymarket:data-api-v2",
                "payload": {"sequence": index},
            }
            for index in range(100_005)
        ]
        await connection.execute(wallet_observations.insert(), rows)

    result = await warehouse.load_wallet_observations_complete(
        observation_type="trades",
        page_size=4096,
        max_rows=150_000,
    )

    assert result.complete
    assert result.available_count == 100_005
    assert len(result.rows) == 100_005
    assert result.pages > 1
    assert result.rows[99_999]["payload"]["sequence"] == 99_999
    assert result.rows[100_004]["payload"]["sequence"] == 100_004
    assert [row["id"] for row in result.rows] == list(range(1, 100_006))
    assert result.first_evaluated_at == result.first_available_at
    assert result.last_evaluated_at == result.last_available_at
    await warehouse.close()


@pytest.mark.asyncio
async def test_complete_wallet_history_surfaces_incomplete_safety_ceiling() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    warehouse = PostgresSignalWarehouse("sqlite+aiosqlite:///:memory:", engine=engine)
    async with engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
        start = datetime(2026, 1, 1, tzinfo=UTC)
        await connection.execute(
            wallet_observations.insert(),
            [
                {
                    "observed_at": start + timedelta(seconds=index),
                    "wallet": "0x" + f"{index:040x}",
                    "observation_type": "leaderboard",
                    "source_id": "polymarket:data-api-v2",
                    "payload": {"sequence": index},
                }
                for index in range(11)
            ],
        )

    result = await warehouse.load_wallet_observations_complete(
        observation_type="leaderboard",
        page_size=3,
        max_rows=10,
    )

    assert not result.complete
    assert result.available_count == 11
    assert len(result.rows) == 10
    assert result.last_evaluated_at is not None
    assert result.last_available_at is not None
    assert result.last_evaluated_at < result.last_available_at
    await warehouse.close()
