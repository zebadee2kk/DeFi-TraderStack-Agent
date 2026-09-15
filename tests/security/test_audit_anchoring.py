"""Anchored audit verification (#68).

The property under test is the one the hash chain alone cannot give you: a
whole-file rewrite. An attacker with write access to `var/audit/` can
regenerate the chain from genesis with different content, and the result
verifies perfectly against itself. These tests pin that such a file passes
`verify_chain` and *fails* once anchors are consulted.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from traderstack.audit_anchor import (
    AuditAnchor,
    AuditAnchorPublisher,
    FanoutAuditAnchorSink,
    JsonlAuditAnchorStore,
    RedisAuditAnchorStore,
    assert_trail_matches_anchors,
    head_anchor,
    verify_with_anchors,
)
from traderstack.config import Settings
from traderstack.models import RiskDecision, RiskResult, Side, TradeProposal
from traderstack.risk_audit import JsonlRiskAuditTrail, verify_chain


def proposal(asset: str = "BTC") -> TradeProposal:
    return TradeProposal(
        decision_id=uuid4(),
        asset=asset,
        side=Side.BUY,
        requested_notional_usd=1_000.0,
        confidence=0.6,
        strategy_id="momentum",
        thesis="t",
        source_freshness_seconds=1.0,
    )


def result(prop: TradeProposal, *, policy_version: str) -> RiskResult:
    return RiskResult(
        decision_id=prop.decision_id,
        decision=RiskDecision.ALLOW,
        approved_notional_usd=1_000.0,
        reasons=[],
        policy_version=policy_version,
    )


def write_trail(path: Path, *, count: int, asset: str = "BTC") -> JsonlRiskAuditTrail:
    """A real hash-chained trail of ``count`` records."""

    settings = Settings(kill_switch=False)
    trail = JsonlRiskAuditTrail(path)
    for _ in range(count):
        prop = proposal(asset)
        trail.record(prop, result(prop, policy_version="mvp-v1"), settings)
    return trail


# --- the acceptance criterion ------------------------------------------------


def test_a_regenerated_trail_passes_verify_chain_but_fails_anchored_verification(
    tmp_path: Path,
) -> None:
    """The whole point of #68, end to end."""

    audit = tmp_path / "risk.jsonl"
    write_trail(audit, count=6)
    anchor = head_anchor(audit)
    assert anchor is not None

    # The attacker rewrites the file from genesis with different content.
    audit.unlink()
    write_trail(audit, count=6, asset="ETH")

    # Self-consistency is intact: the hash chain alone is fooled.
    assert verify_chain(audit).valid is True

    # The published head is not: it commits to a record that no longer exists.
    verification = verify_with_anchors(audit, [anchor])
    assert verification.valid is False
    assert verification.chain.valid is True
    assert verification.diverged_at_sequence == anchor.sequence
    assert "rewritten" in (verification.error or "")


def test_a_truncated_trail_is_caught_by_an_anchor_beyond_its_head(tmp_path: Path) -> None:
    """Restored-from-backup or truncated: the head is behind what was anchored."""

    audit = tmp_path / "risk.jsonl"
    write_trail(audit, count=8)
    anchor = head_anchor(audit)
    assert anchor is not None

    lines = audit.read_text(encoding="utf-8").splitlines()[:4]
    audit.write_text("\n".join(lines) + "\n", encoding="utf-8")

    assert verify_chain(audit).valid is True
    verification = verify_with_anchors(audit, [anchor])
    assert verification.valid is False
    assert verification.diverged_at_sequence == anchor.sequence
    assert "truncated" in (verification.error or "")


def test_an_untouched_trail_verifies_against_its_anchors(tmp_path: Path) -> None:
    audit = tmp_path / "risk.jsonl"
    write_trail(audit, count=5)
    early = head_anchor(audit)
    write_trail(audit, count=3)
    late = head_anchor(audit)
    assert early is not None and late is not None

    verification = verify_with_anchors(audit, [early, late])
    assert verification.valid is True
    assert verification.anchors_checked == 2


def test_no_anchors_is_not_a_pass(tmp_path: Path) -> None:
    """An intact chain proves internal consistency only — fail closed."""

    audit = tmp_path / "risk.jsonl"
    write_trail(audit, count=3)

    verification = verify_with_anchors(audit, [])
    assert verification.valid is False
    assert verification.chain.valid is True
    assert "no anchors available" in (verification.error or "")


def test_an_edited_line_still_fails_before_anchors_are_consulted(tmp_path: Path) -> None:
    audit = tmp_path / "risk.jsonl"
    write_trail(audit, count=4)
    anchor = head_anchor(audit)
    assert anchor is not None
    audit.write_text(
        audit.read_text(encoding="utf-8").replace(
            '"approved_notional_usd":1000.0', '"approved_notional_usd":9999.0', 1
        ),
        encoding="utf-8",
    )

    verification = verify_with_anchors(audit, [anchor])
    assert verification.valid is False
    assert verification.chain.valid is False


# --- sinks -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_jsonl_store_round_trips_anchors(tmp_path: Path) -> None:
    store = JsonlAuditAnchorStore(tmp_path / "anchors.jsonl")
    assert await store.anchors() == []
    anchor = AuditAnchor(
        sequence=3, head_hash="a" * 64, policy_version="mvp-v1", anchored_at=datetime.now(UTC)
    )
    await store.publish(anchor)
    assert [a.head_hash for a in await store.anchors()] == ["a" * 64]


@pytest.mark.asyncio
async def test_redis_store_publishes_and_reads_the_head() -> None:
    class FakeRedis:
        def __init__(self) -> None:
            self.values: dict[str, str] = {}

        async def set(self, name: str, value: str) -> object:
            self.values[name] = value
            return True

        async def get(self, name: str) -> bytes | None:
            raw = self.values.get(name)
            return raw.encode("utf-8") if raw is not None else None

    client = FakeRedis()
    store = RedisAuditAnchorStore(client)
    assert await store.anchors() == []
    anchor = AuditAnchor(
        sequence=9, head_hash="b" * 64, policy_version="mvp-v1", anchored_at=datetime.now(UTC)
    )
    await store.publish(anchor)
    assert [a.sequence for a in await store.anchors()] == [9]


@pytest.mark.asyncio
async def test_a_failing_sink_never_blocks_the_cycle(tmp_path: Path) -> None:
    """Anchoring is evidence: a down sink is counted, not raised."""

    class Broken:
        async def publish(self, anchor: AuditAnchor) -> None:
            raise ConnectionError("redis is down")

        async def anchors(self) -> list[AuditAnchor]:
            raise ConnectionError("redis is down")

    good = JsonlAuditAnchorStore(tmp_path / "anchors.jsonl")
    fanout = FanoutAuditAnchorSink({"broken": Broken(), "local": good})
    anchor = AuditAnchor(
        sequence=1, head_hash="c" * 64, policy_version="mvp-v1", anchored_at=datetime.now(UTC)
    )

    await fanout.publish(anchor)  # must not raise

    # The reachable sink still recorded it, and one bad sink does not hide it.
    assert [a.sequence for a in await fanout.anchors()] == [1]


@pytest.mark.asyncio
async def test_publisher_anchors_every_n_records_and_on_demand(tmp_path: Path) -> None:
    audit = tmp_path / "risk.jsonl"
    write_trail(audit, count=3)
    store = JsonlAuditAnchorStore(tmp_path / "anchors.jsonl")
    publisher = AuditAnchorPublisher(sink=store, path=audit, anchor_every=5)

    assert await publisher.maybe_publish(sequence=2) is None
    assert await publisher.maybe_publish(sequence=4) is not None
    # Just anchored at 4; 5 is not yet another full interval.
    assert await publisher.maybe_publish(sequence=5) is None
    # Shutdown publishes unconditionally.
    assert await publisher.publish_now() is not None


@pytest.mark.asyncio
async def test_publisher_on_an_empty_trail_is_a_no_op(tmp_path: Path) -> None:
    store = JsonlAuditAnchorStore(tmp_path / "anchors.jsonl")
    publisher = AuditAnchorPublisher(sink=store, path=tmp_path / "missing.jsonl")
    assert await publisher.publish_now() is None
    assert await store.anchors() == []


# --- startup gate ------------------------------------------------------------


@pytest.mark.asyncio
async def test_startup_refuses_a_rewritten_trail(tmp_path: Path) -> None:
    audit = tmp_path / "risk.jsonl"
    write_trail(audit, count=4)
    store = JsonlAuditAnchorStore(tmp_path / "anchors.jsonl")
    publisher = AuditAnchorPublisher(sink=store, path=audit, anchor_every=1)
    await publisher.publish_now()

    audit.unlink()
    write_trail(audit, count=4, asset="ETH")

    verification = await assert_trail_matches_anchors(audit, store)
    assert verification.valid is False
    assert "rewritten" in (verification.error or "")


@pytest.mark.asyncio
async def test_startup_allows_a_first_run_with_no_trail(tmp_path: Path) -> None:
    store = JsonlAuditAnchorStore(tmp_path / "anchors.jsonl")
    verification = await assert_trail_matches_anchors(tmp_path / "missing.jsonl", store)
    assert verification.valid is True


@pytest.mark.asyncio
async def test_startup_refuses_a_deleted_trail_that_was_already_anchored(tmp_path: Path) -> None:
    """A missing file is benign only when nothing was ever anchored."""

    audit = tmp_path / "risk.jsonl"
    write_trail(audit, count=2)
    store = JsonlAuditAnchorStore(tmp_path / "anchors.jsonl")
    await AuditAnchorPublisher(sink=store, path=audit).publish_now()
    audit.unlink()

    verification = await assert_trail_matches_anchors(audit, store)
    assert verification.valid is False
    assert "deleted after it was anchored" in (verification.error or "")


@pytest.mark.asyncio
async def test_startup_accepts_an_intact_trail_not_yet_anchored(tmp_path: Path) -> None:
    """Anchoring newly enabled on an existing trail is not a failure."""

    audit = tmp_path / "risk.jsonl"
    write_trail(audit, count=3)
    store = JsonlAuditAnchorStore(tmp_path / "anchors.jsonl")

    verification = await assert_trail_matches_anchors(audit, store)
    assert verification.valid is True
    assert verification.anchors_checked == 0
