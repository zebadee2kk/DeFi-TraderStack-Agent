from datetime import UTC, datetime

from traderstack.signal_warehouse_export import WarehouseExportSpec, _parse_dt


def test_export_query_hash_is_deterministic() -> None:
    spec_a = WarehouseExportSpec(
        asset="btc",
        start=datetime(2026, 10, 1, tzinfo=UTC),
        end=datetime(2026, 10, 2, tzinfo=UTC),
        limit=100,
    )
    spec_b = WarehouseExportSpec(
        asset="BTC",
        start=datetime(2026, 10, 1, tzinfo=UTC),
        end=datetime(2026, 10, 2, tzinfo=UTC),
        limit=100,
    )
    assert spec_a.canonical_json() == spec_b.canonical_json()
    assert spec_a.query_hash() == spec_b.query_hash()


def test_export_query_hash_changes_with_bounds() -> None:
    base = WarehouseExportSpec(
        asset="BTC",
        start=datetime(2026, 10, 1, tzinfo=UTC),
        end=datetime(2026, 10, 2, tzinfo=UTC),
        limit=100,
    )
    other = WarehouseExportSpec(
        asset="BTC",
        start=datetime(2026, 10, 1, tzinfo=UTC),
        end=datetime(2026, 10, 3, tzinfo=UTC),
        limit=100,
    )
    assert base.query_hash() != other.query_hash()


def test_parse_dt_normalizes_naive_and_zulu_to_utc() -> None:
    assert _parse_dt("2026-10-04T10:00:00Z") == datetime(2026, 10, 4, 10, tzinfo=UTC)
    assert _parse_dt("2026-10-04T10:00:00") == datetime(2026, 10, 4, 10, tzinfo=UTC)


def test_intelligence_export_has_distinct_reproducible_query_hash() -> None:
    feature = WarehouseExportSpec(
        asset="BTC",
        start=datetime(2026, 10, 1, tzinfo=UTC),
        end=datetime(2026, 10, 2, tzinfo=UTC),
        limit=100,
    )
    intelligence = WarehouseExportSpec(
        asset="BTC",
        start=datetime(2026, 10, 1, tzinfo=UTC),
        end=datetime(2026, 10, 2, tzinfo=UTC),
        limit=100,
        dataset="intelligence",
    )

    assert feature.query_hash() != intelligence.query_hash()
    assert '"dataset":"intelligence"' in intelligence.canonical_json()
    assert '"dataset"' not in feature.canonical_json()
