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
