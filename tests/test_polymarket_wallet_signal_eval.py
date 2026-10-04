# ruff: noqa: I001
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from traderstack.polymarket.data_api import DataPricePoint
from traderstack.polymarket import wallet_signal_eval


WALLET = "0x" + "11" * 20


def leaderboard_row(
    *,
    snapshot_id: str,
    snapshot_at: datetime,
    rank: int,
) -> dict[str, object]:
    return {
        "observed_at": snapshot_at,
        "wallet": WALLET,
        "observation_type": "leaderboard",
        "source_id": "polymarket:data-api:/v2/leaderboard",
        "payload": {
            "snapshot_id": snapshot_id,
            "snapshot_at": snapshot_at.isoformat(),
            "category": "CRYPTO",
            "time_period": "MONTH",
            "row": {"rank": rank, "pnl": 100.0},
        },
    }


def trade_row(*, observed_at: datetime, trades: list[dict[str, object]]) -> dict[str, object]:
    return {
        "observed_at": observed_at,
        "wallet": WALLET,
        "observation_type": "trades",
        "source_id": "polymarket:data-api:/v2/trades",
        "payload": trades,
    }


def trade(*, timestamp: int, side: str = "BUY", size: float = 100.0) -> dict[str, object]:
    return {
        "proxy_wallet": WALLET,
        "side": side,
        "asset": "123456",
        "condition_id": "0x" + "ab" * 32,
        "size": size,
        "price": 0.4,
        "timestamp": timestamp,
        "outcome": "Yes",
        "title": "Will BTC exceed X?",
        "transaction_hash": "0x" + f"{timestamp:x}".rjust(64, "0"),
    }


def test_parse_trade_observations_dedupes_repeated_snapshot_payloads() -> None:
    happened = datetime(2026, 10, 4, 10, tzinfo=UTC)
    raw = trade(timestamp=int(happened.timestamp()))
    rows = [
        trade_row(observed_at=happened + timedelta(minutes=1), trades=[raw]),
        trade_row(observed_at=happened + timedelta(hours=1), trades=[raw]),
    ]
    parsed = wallet_signal_eval.parse_trade_observations(rows)
    assert len(parsed) == 1
    assert parsed[0].side == "BUY"
    assert parsed[0].token_id == "123456"


def test_candidates_use_only_latest_point_in_time_eligible_cohort() -> None:
    first = datetime(2026, 10, 1, 9, tzinfo=UTC)
    second = datetime(2026, 10, 2, 9, tzinfo=UTC)
    traded = second + timedelta(hours=1)
    leaderboard = [
        leaderboard_row(snapshot_id="s1", snapshot_at=first, rank=8),
        leaderboard_row(snapshot_id="s2", snapshot_at=second, rank=6),
    ]
    trades = [
        trade_row(
            observed_at=traded + timedelta(minutes=1),
            trades=[trade(timestamp=int(traded.timestamp()))],
        )
    ]

    candidates = wallet_signal_eval.build_signal_candidates(
        leaderboard_rows=leaderboard,
        trade_rows=trades,
        category="CRYPTO",
        time_period="MONTH",
        cohort_ttl_hours=168,
    )
    ids = {candidate.hypothesis for candidate in candidates}
    assert ids == {"persistent_top10_follow", "persistent_top10_fade"}
    assert all(candidate.cohort_snapshot_id == "s2" for candidate in candidates)
    assert all(candidate.appearances_to_date == 2 for candidate in candidates)


def test_top3_follow_can_qualify_on_first_point_in_time_snapshot() -> None:
    snapshot = datetime(2026, 10, 2, 9, tzinfo=UTC)
    traded = snapshot + timedelta(minutes=10)
    candidates = wallet_signal_eval.build_signal_candidates(
        leaderboard_rows=[leaderboard_row(snapshot_id="s1", snapshot_at=snapshot, rank=2)],
        trade_rows=[
            trade_row(
                observed_at=traded + timedelta(minutes=1),
                trades=[trade(timestamp=int(traded.timestamp()))],
            )
        ],
        category="CRYPTO",
        time_period="MONTH",
        cohort_ttl_hours=168,
    )
    assert [candidate.hypothesis for candidate in candidates] == ["top3_follow"]


def test_sell_trades_are_not_silently_treated_as_executable_copies() -> None:
    snapshot = datetime(2026, 10, 2, 9, tzinfo=UTC)
    traded = snapshot + timedelta(minutes=10)
    candidates = wallet_signal_eval.build_signal_candidates(
        leaderboard_rows=[leaderboard_row(snapshot_id="s1", snapshot_at=snapshot, rank=1)],
        trade_rows=[
            trade_row(
                observed_at=traded + timedelta(minutes=1),
                trades=[trade(timestamp=int(traded.timestamp()), side="SELL")],
            )
        ],
        category="CRYPTO",
        time_period="MONTH",
        cohort_ttl_hours=168,
    )
    assert candidates == []


@pytest.mark.asyncio
async def test_score_candidates_applies_copy_delay_capacity_and_costs() -> None:
    first = datetime(2026, 10, 1, 9, tzinfo=UTC)
    second = datetime(2026, 10, 2, 9, tzinfo=UTC)
    traded = second + timedelta(hours=1)
    candidates = wallet_signal_eval.build_signal_candidates(
        leaderboard_rows=[
            leaderboard_row(snapshot_id="s1", snapshot_at=first, rank=8),
            leaderboard_row(snapshot_id="s2", snapshot_at=second, rank=6),
        ],
        trade_rows=[
            trade_row(
                observed_at=traded + timedelta(minutes=1),
                trades=[trade(timestamp=int(traded.timestamp()), size=1000)],
            )
        ],
        category="CRYPTO",
        time_period="MONTH",
        cohort_ttl_hours=168,
    )
    follow = [c for c in candidates if c.hypothesis == "persistent_top10_follow"]

    async def price_lookup(_: str, timestamp: int) -> DataPricePoint | None:
        entry_target = int(traded.timestamp()) + 300
        if timestamp == entry_target:
            return DataPricePoint(timestamp=timestamp, price=0.40, resolution_seconds=60)
        return DataPricePoint(timestamp=timestamp, price=0.50, resolution_seconds=60)

    scored, skipped = await wallet_signal_eval.score_candidates(
        follow,
        price_lookup=price_lookup,
        copy_delay_seconds=300,
        hold_seconds=3600,
        cost_bps_per_side=50,
        target_notional_usd=10,
        copy_fraction_of_leader=0.10,
        max_resolution_seconds=300,
        max_staleness_seconds=300,
        max_signals=10,
    )
    assert skipped["price_unavailable_or_too_coarse"] == 0
    assert len(scored) == 1
    assert scored[0].copied_notional_usd == 10
    assert scored[0].gross_pnl_usd == pytest.approx(2.5)
    assert scored[0].cost_usd > 0
    assert scored[0].net_pnl_usd < scored[0].gross_pnl_usd


@pytest.mark.asyncio
async def test_score_candidates_rejects_price_resolution_too_coarse_for_delay() -> None:
    snapshot = datetime(2026, 10, 2, 9, tzinfo=UTC)
    traded = snapshot + timedelta(minutes=10)
    candidates = wallet_signal_eval.build_signal_candidates(
        leaderboard_rows=[leaderboard_row(snapshot_id="s1", snapshot_at=snapshot, rank=1)],
        trade_rows=[
            trade_row(
                observed_at=traded + timedelta(minutes=1),
                trades=[trade(timestamp=int(traded.timestamp()), size=1000)],
            )
        ],
        category="CRYPTO",
        time_period="MONTH",
        cohort_ttl_hours=168,
    )

    async def coarse(_: str, timestamp: int) -> DataPricePoint | None:
        return DataPricePoint(timestamp=timestamp, price=0.4, resolution_seconds=43_200)

    scored, skipped = await wallet_signal_eval.score_candidates(
        candidates,
        price_lookup=coarse,
        copy_delay_seconds=300,
        hold_seconds=3600,
        cost_bps_per_side=50,
        target_notional_usd=10,
        copy_fraction_of_leader=0.10,
        max_resolution_seconds=1800,
        max_staleness_seconds=1800,
        max_signals=10,
    )
    assert scored == []
    assert skipped["price_unavailable_or_too_coarse"] == len(candidates)


def test_hypothesis_catalog_is_frozen_to_three_initial_wallet_rules() -> None:
    assert wallet_signal_eval.HYPOTHESES == (
        "persistent_top10_follow",
        "top3_follow",
        "persistent_top10_fade",
    )


def test_summarize_keeps_chronological_holdout_separate() -> None:
    base = datetime(2026, 10, 1, tzinfo=UTC)
    rows = [
        wallet_signal_eval.ScoredSignal(
            hypothesis="top3_follow",
            wallet=WALLET,
            token_id="t",
            condition_id=None,
            trade_at=base + timedelta(days=i),
            cohort_snapshot_at=base,
            copy_delay_seconds=300,
            hold_seconds=3600,
            cost_bps_per_side=50,
            copied_notional_usd=10,
            entry_timestamp=1,
            entry_price=0.4,
            exit_timestamp=2,
            exit_price=0.5,
            gross_pnl_usd=1,
            cost_usd=0.1,
            net_pnl_usd=0.9 if i < 3 else -0.5,
            direction=1,
            title=None,
            outcome=None,
        )
        for i in range(4)
    ]
    summaries = wallet_signal_eval.summarize(rows, holdout_fraction=0.25)
    discovery = next(item for item in summaries if item.split == "discovery")
    holdout = next(item for item in summaries if item.split == "holdout")
    assert discovery.signals == 3
    assert holdout.signals == 1
    assert holdout.net_pnl_usd == pytest.approx(-0.5)


@pytest.mark.asyncio
async def test_paced_price_lookup_caches_and_spaces_unique_requests() -> None:
    upstream_calls: list[tuple[str, int]] = []
    sleeps: list[float] = []
    times = iter((0.0, 0.0, 0.1, 0.1))

    async def upstream(token_id: str, timestamp: int) -> DataPricePoint | None:
        upstream_calls.append((token_id, timestamp))
        return DataPricePoint(timestamp=timestamp, price=0.5, resolution_seconds=60)

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    paced = wallet_signal_eval.PacedPriceLookup(
        lookup=upstream,
        calls_per_minute=60,
        sleep=fake_sleep,
        monotonic=lambda: next(times),
    )

    first = await paced("token-a", 100)
    cached = await paced("token-a", 100)
    second = await paced("token-b", 200)

    assert first == cached
    assert second is not None
    assert upstream_calls == [("token-a", 100), ("token-b", 200)]
    assert sleeps == [pytest.approx(0.9)]
    assert paced.cached_points == 2


def test_paced_price_lookup_refuses_budget_above_provider_ceiling() -> None:
    async def upstream(_: str, __: int) -> DataPricePoint | None:
        return None

    with pytest.raises(ValueError, match="between 1 and 120"):
        wallet_signal_eval.PacedPriceLookup(lookup=upstream, calls_per_minute=121)
