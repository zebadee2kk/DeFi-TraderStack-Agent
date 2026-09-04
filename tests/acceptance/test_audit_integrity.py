"""Epic 10 drill: audit integrity.

The MVP exit criteria require "a complete auditable decision trail". After a run
that must mean three things at once: the hash chain verifies, every submitted
order is traceable back to both a risk-audit record and a runtime event, and any
edit to the trail is detected rather than silently accepted.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from traderstack.risk_audit import RiskAuditRecord, verify_chain

pytestmark = pytest.mark.asyncio

CYCLES = 6


def _runtime_events(path: Path) -> list[dict]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def _risk_records(path: Path) -> list[RiskAuditRecord]:
    return [
        RiskAuditRecord.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


async def test_the_chain_verifies_and_every_order_is_fully_traceable(harness) -> None:
    drill = await harness()
    await drill.cycles(CYCLES)

    risk_path = drill.risk_audit.path
    runtime_path = Path(drill.audit_sink.delegate.path)

    verification = verify_chain(risk_path)
    assert verification.valid is True
    assert verification.records == CYCLES
    assert verification.error is None

    risk_by_decision = {
        str(record.result.decision_id): record for record in _risk_records(risk_path)
    }
    events_by_decision = {
        event["pipeline"]["proposal"]["decision_id"]: event
        for event in _runtime_events(runtime_path)
        if event["pipeline"].get("proposal")
    }

    assert drill.ledger.orders, "the drill must actually have submitted something"
    for order in drill.ledger.orders.values():
        record = risk_by_decision.get(order.decision_id)
        assert record is not None, f"order {order.order_id} has no risk audit record"
        assert record.result.approved_notional_usd > 0
        assert record.policy_version == record.result.policy_version
        assert record.risk_limits["kill_switch"] is False

        event = events_by_decision.get(order.decision_id)
        assert event is not None, f"order {order.order_id} has no runtime event"
        assert event["execution_status"] == "submitted"
        assert event["execution_receipt"]["order_id"] is not None


async def test_the_chain_survives_a_restart_of_the_audit_trail(harness) -> None:
    drill = await harness()
    await drill.cycles(2)

    # A new trail object over the same file resumes the chain rather than
    # restarting the sequence at zero.
    from traderstack.risk_audit import JsonlRiskAuditTrail

    restarted = JsonlRiskAuditTrail(drill.risk_audit.path)
    drill.service.risk_audit = restarted
    await drill.cycles(2)

    verification = verify_chain(drill.risk_audit.path)
    assert verification.valid is True
    assert verification.records == 4
    assert [record.sequence for record in _risk_records(drill.risk_audit.path)] == [0, 1, 2, 3]


async def test_an_edited_record_fails_verification(harness) -> None:
    drill = await harness()
    await drill.cycles(3)
    path = drill.risk_audit.path
    lines = path.read_text(encoding="utf-8").splitlines()

    tampered = json.loads(lines[1])
    tampered["result"]["approved_notional_usd"] = 1_000_000.0
    lines[1] = json.dumps(tampered, separators=(",", ":"), sort_keys=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    verification = verify_chain(path)
    assert verification.valid is False
    assert verification.first_invalid_sequence == 1
    assert "record hash" in (verification.error or "")


async def test_a_removed_record_fails_verification(harness) -> None:
    drill = await harness()
    await drill.cycles(3)
    path = drill.risk_audit.path
    lines = path.read_text(encoding="utf-8").splitlines()

    del lines[1]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    verification = verify_chain(path)
    assert verification.valid is False
    assert "removed or reordered" in (verification.error or "")
