from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from traderstack.polymarket.wallet_signal_eval import SignalCandidate, WalletTrade
from traderstack.polymarket.world_signal_fusion import fuse_signal_context


def _candidate(
    *, signal_at: datetime, title: str = "Will Bitcoin be above $100k?"
) -> SignalCandidate:
    trade = WalletTrade(
        wallet="0x" + "1" * 40,
        trade_at=signal_at,
        observed_at=signal_at,
        side="BUY",
        token_id="token-btc",
        condition_id="condition-1",
        size=100.0,
        leader_price=0.5,
        outcome="Yes",
        title=title,
        transaction_hash="0xabc",
    )
    return SignalCandidate(
        hypothesis="top3_follow",
        cohort_snapshot_id="snapshot-1",
        cohort_snapshot_at=signal_at - timedelta(hours=1),
        wallet=trade.wallet,
        rank=1,
        appearances_to_date=1,
        trade=trade,
        direction=1,
    )


def test_fusion_uses_latest_point_in_time_matching_asset_and_global_context() -> None:
    signal_at = datetime(2026, 10, 4, 12, tzinfo=UTC)
    rows = [
        {
            "observed_at": signal_at - timedelta(hours=2),
            "asset": "BTC",
            "source_id": "crucix",
            "payload": {"adverse_event": False, "version": 1},
        },
        {
            "observed_at": signal_at - timedelta(minutes=5),
            "asset": "BTC",
            "source_id": "crucix",
            "payload": {"adverse_event": True, "version": 2},
        },
        {
            "observed_at": signal_at - timedelta(minutes=3),
            "asset": "GLOBAL",
            "source_id": "cryptopanic",
            "payload": {"news_score": -0.2},
        },
        {
            "observed_at": signal_at - timedelta(minutes=1),
            "asset": "ETH",
            "source_id": "dune",
            "payload": {"exchange_netflow_z": 2.0},
        },
    ]

    fused = fuse_signal_context([_candidate(signal_at=signal_at)], rows, max_age_hours=24)

    assert len(fused) == 1
    context = fused[0].provider_context
    assert [(item.source_id, item.asset) for item in context] == [
        ("crucix", "BTC"),
        ("cryptopanic", "GLOBAL"),
    ]
    crucix = next(item for item in context if item.source_id == "crucix")
    assert crucix.payload["version"] == 2
    assert crucix.age_seconds == 300


def test_fusion_rejects_future_and_stale_observations() -> None:
    signal_at = datetime(2026, 10, 4, 12, tzinfo=UTC)
    rows = [
        {
            "observed_at": signal_at + timedelta(seconds=1),
            "asset": "BTC",
            "source_id": "future",
            "payload": {"value": 1},
        },
        {
            "observed_at": signal_at - timedelta(hours=25),
            "asset": "BTC",
            "source_id": "stale",
            "payload": {"value": 2},
        },
    ]

    fused = fuse_signal_context([_candidate(signal_at=signal_at)], rows, max_age_hours=24)

    assert fused[0].provider_context == ()


def test_fusion_requires_positive_age_window() -> None:
    with pytest.raises(ValueError, match="max_age_hours must be positive"):
        fuse_signal_context([], [], max_age_hours=0)


def test_fusion_does_not_guess_unrelated_asset_from_generic_market_text() -> None:
    signal_at = datetime(2026, 10, 4, 12, tzinfo=UTC)
    rows = [
        {
            "observed_at": signal_at - timedelta(minutes=2),
            "asset": "BTC",
            "source_id": "market",
            "payload": {"value": 1},
        },
        {
            "observed_at": signal_at - timedelta(minutes=2),
            "asset": "GLOBAL",
            "source_id": "world",
            "payload": {"value": 2},
        },
    ]

    fused = fuse_signal_context(
        [_candidate(signal_at=signal_at, title="Will the Fed cut rates?")],
        rows,
        max_age_hours=24,
    )

    assert [(item.source_id, item.asset) for item in fused[0].provider_context] == [
        ("world", "GLOBAL")
    ]


def test_native_fusion_preserves_two_news_providers_and_explicit_types() -> None:
    signal_at = datetime(2026, 10, 4, 12, tzinfo=UTC)
    native_rows = [
        {
            "observed_at": signal_at - timedelta(minutes=5),
            "asset": "BTC",
            "source_id": "cryptopanic",
            "observation_type": "news",
            "payload": {"event_score": 0.7, "adverse_event": True, "item_count": 4},
        },
        {
            "observed_at": signal_at - timedelta(minutes=5),
            "asset": "BTC",
            "source_id": "perplexity",
            "observation_type": "news",
            "payload": {"event_score": 0.2, "adverse_event": False, "item_count": 2},
        },
    ]

    fused = fuse_signal_context(
        [_candidate(signal_at=signal_at)],
        native_rows=native_rows,
        max_age_hours=24,
    )

    context = fused[0].provider_context
    assert [(item.source_id, item.observation_type) for item in context] == [
        ("cryptopanic", "news"),
        ("perplexity", "news"),
    ]
    assert context[0].payload["news"]["event_score"] == 0.7  # type: ignore[index]
    assert context[1].payload["news"]["event_score"] == 0.2  # type: ignore[index]


def test_native_fusion_rejects_future_and_unrelated_asset_rows() -> None:
    signal_at = datetime(2026, 10, 4, 12, tzinfo=UTC)
    native_rows = [
        {
            "observed_at": signal_at + timedelta(seconds=1),
            "asset": "BTC",
            "source_id": "future-news",
            "observation_type": "news",
            "payload": {"event_score": 1.0, "adverse_event": True, "item_count": 1},
        },
        {
            "observed_at": signal_at - timedelta(minutes=1),
            "asset": "ETH",
            "source_id": "eth-news",
            "observation_type": "news",
            "payload": {"event_score": 1.0, "adverse_event": True, "item_count": 1},
        },
    ]

    fused = fuse_signal_context(
        [_candidate(signal_at=signal_at)],
        native_rows=native_rows,
        max_age_hours=24,
    )

    assert fused[0].provider_context == ()


def test_canonical_feature_context_contributes_only_edge_namespace() -> None:
    signal_at = datetime(2026, 10, 4, 12, tzinfo=UTC)
    canonical_rows = [
        {
            "observed_at": signal_at - timedelta(minutes=2),
            "asset": "BTC",
            "payload": {
                "news": {"event_score": 1.0, "adverse_event": True},
                "onchain": {"exchange_netflow_z": 9.0},
                "edge": {"liq_notional_long_z": 1.7, "liq_notional_short_z": None},
            },
        }
    ]

    fused = fuse_signal_context(
        [_candidate(signal_at=signal_at)],
        canonical_rows=canonical_rows,
        max_age_hours=24,
    )

    context = fused[0].provider_context
    assert len(context) == 1
    assert context[0].source_id == "canonical:feature"
    assert context[0].observation_type == "canonical_feature"
    assert context[0].payload == {
        "edge": {"liq_notional_long_z": 1.7, "liq_notional_short_z": None}
    }
