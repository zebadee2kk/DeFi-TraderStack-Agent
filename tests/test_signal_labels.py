from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import create_async_engine

from traderstack.research.signal_labels import (
    SignalCandidateRecord,
    SignalOutcomeRecord,
    build_candidate_row,
    build_outcome_row,
)
from traderstack.signal_warehouse import PostgresSignalWarehouse, metadata


def _candidate() -> SignalCandidateRecord:
    return SignalCandidateRecord(
        candidate_at=datetime(2026, 10, 5, 9, tzinfo=UTC),
        asset="btc",
        hypothesis_id="wallet_top3_follow",
        hypothesis_version="1.0",
        horizon_seconds=3600,
        direction=1,
        confidence=0.7,
        feature_query_hash="a" * 64,
    )


def _outcome(candidate: SignalCandidateRecord) -> SignalOutcomeRecord:
    return SignalOutcomeRecord(
        candidate_event_key=candidate.event_key(),
        candidate_at=candidate.candidate_at,
        outcome_at=candidate.candidate_at + timedelta(hours=1),
        horizon_seconds=candidate.horizon_seconds,
        gross_return=0.03,
        net_return=0.02,
        gross_pnl_usd=0.30,
        net_pnl_usd=0.20,
        fee_bps=25.0,
        slippage_bps=5.0,
    )


def test_signal_candidate_event_key_is_deterministic_and_normalized() -> None:
    first = _candidate()
    second = _candidate()

    assert first.asset == "BTC"
    assert first.event_key() == second.event_key()
    assert len(first.event_key()) == 64


def test_signal_outcome_cannot_be_created_before_registered_horizon() -> None:
    candidate = _candidate()

    with pytest.raises(ValidationError, match="registered candidate horizon"):
        SignalOutcomeRecord(
            candidate_event_key=candidate.event_key(),
            candidate_at=candidate.candidate_at,
            outcome_at=candidate.candidate_at + timedelta(minutes=59),
            horizon_seconds=candidate.horizon_seconds,
            gross_return=0.01,
            net_return=0.0,
            fee_bps=25.0,
            slippage_bps=5.0,
        )


@pytest.mark.asyncio
async def test_signal_candidate_and_outcome_storage_is_idempotent_and_queryable() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    warehouse = PostgresSignalWarehouse("sqlite+aiosqlite:///:memory:", engine=engine)
    async with engine.begin() as connection:
        await connection.run_sync(metadata.create_all)

    candidate = _candidate()
    outcome = _outcome(candidate)
    candidate_row = build_candidate_row(candidate)
    outcome_row = build_outcome_row(outcome)

    assert await warehouse.append_signal_candidates([candidate_row]) == 1
    assert await warehouse.append_signal_candidates([candidate_row]) == 0
    assert await warehouse.append_signal_outcomes([outcome_row]) == 1
    assert await warehouse.append_signal_outcomes([outcome_row]) == 0

    dataset = await warehouse.load_signal_dataset(asset="BTC")
    assert len(dataset) == 1
    assert dataset[0]["event_key"] == candidate.event_key()
    assert dataset[0]["hypothesis_id"] == "wallet_top3_follow"
    assert dataset[0]["net_return"] == pytest.approx(0.02)
    assert dataset[0]["outcome_at"] >= dataset[0]["candidate_at"]

    await warehouse.close()


@pytest.mark.asyncio
async def test_warehouse_rejects_unknown_or_early_outcome_rows() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    warehouse = PostgresSignalWarehouse("sqlite+aiosqlite:///:memory:", engine=engine)
    async with engine.begin() as connection:
        await connection.run_sync(metadata.create_all)

    candidate = _candidate()
    outcome = _outcome(candidate)

    unknown = build_outcome_row(outcome)
    unknown["candidate_event_key"] = "f" * 64
    with pytest.raises(ValueError, match="unknown candidate"):
        await warehouse.append_signal_outcomes([unknown])

    await warehouse.append_signal_candidates([build_candidate_row(candidate)])
    early = build_outcome_row(outcome)
    early["outcome_at"] = candidate.candidate_at + timedelta(minutes=30)
    with pytest.raises(ValueError, match="precedes registered candidate horizon"):
        await warehouse.append_signal_outcomes([early])

    await warehouse.close()
