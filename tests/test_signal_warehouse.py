from datetime import UTC, datetime

from traderstack.features import AssetFeatureVector, MarketFeatures
from traderstack.market.models import MarketSource, MarketTick
from traderstack.pipeline import PipelineResult
from traderstack.runtime import RuntimeResult
from traderstack.signal_warehouse import build_feature_rows, wallet_observations


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
