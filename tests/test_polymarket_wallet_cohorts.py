from datetime import UTC, datetime

from traderstack.polymarket.wallet_cohorts import build_persistence, leaderboard_member


def row(
    *,
    wallet: str,
    snapshot_id: str | None,
    observed_at: datetime,
    rank: int,
    pnl: float,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "category": "CRYPTO",
        "time_period": "MONTH",
        "row": {"rank": rank, "pnl": pnl},
    }
    if snapshot_id is not None:
        payload["snapshot_id"] = snapshot_id
        payload["snapshot_at"] = observed_at.isoformat()
    return {
        "observed_at": observed_at,
        "wallet": wallet,
        "observation_type": "leaderboard",
        "source_id": "polymarket:data-api:/v1/leaderboard",
        "payload": payload,
    }


def test_leaderboard_member_uses_explicit_snapshot_identity() -> None:
    observed = datetime(2026, 10, 4, 10, tzinfo=UTC)
    member = leaderboard_member(
        row(
            wallet="0x" + "11" * 20,
            snapshot_id="snap-1",
            observed_at=observed,
            rank=2,
            pnl=123.0,
        )
    )
    assert member is not None
    assert member.snapshot_id == "snap-1"
    assert member.rank == 2
    assert member.pnl == 123.0


def test_legacy_rows_receive_minute_bucket_snapshot_id() -> None:
    observed = datetime(2026, 10, 4, 10, 5, 27, tzinfo=UTC)
    member = leaderboard_member(
        row(
            wallet="0x" + "22" * 20,
            snapshot_id=None,
            observed_at=observed,
            rank=1,
            pnl=200.0,
        )
    )
    assert member is not None
    assert member.snapshot_id == "legacy:2026-10-04T10:05:00+00:00"


def test_persistence_ranking_prefers_repeated_point_in_time_membership() -> None:
    first = datetime(2026, 10, 1, tzinfo=UTC)
    second = datetime(2026, 10, 2, tzinfo=UTC)
    a = "0x" + "aa" * 20
    b = "0x" + "bb" * 20
    ranked = build_persistence(
        [
            row(wallet=a, snapshot_id="s1", observed_at=first, rank=5, pnl=10),
            row(wallet=b, snapshot_id="s1", observed_at=first, rank=1, pnl=50),
            row(wallet=a, snapshot_id="s2", observed_at=second, rank=3, pnl=20),
        ]
    )
    assert ranked[0].wallet == a
    assert ranked[0].appearances == 2
    assert ranked[0].mean_rank == 4
    assert ranked[0].latest_rank == 3
