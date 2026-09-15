"""``traderstack-verify-audit`` exit codes and output (#68)."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from traderstack.audit_anchor import AuditAnchorPublisher, JsonlAuditAnchorStore
from traderstack.audit_verify_cli import main
from traderstack.config import Settings
from traderstack.models import RiskDecision, RiskResult, Side, TradeProposal
from traderstack.risk_audit import JsonlRiskAuditTrail


def write_trail(path: Path, *, count: int, asset: str = "BTC") -> None:
    settings = Settings(kill_switch=False)
    trail = JsonlRiskAuditTrail(path)
    for _ in range(count):
        prop = TradeProposal(
            decision_id=uuid4(),
            asset=asset,
            side=Side.BUY,
            requested_notional_usd=1_000.0,
            confidence=0.6,
            strategy_id="momentum",
            thesis="t",
            source_freshness_seconds=1.0,
        )
        trail.record(
            prop,
            RiskResult(
                decision_id=prop.decision_id,
                decision=RiskDecision.ALLOW,
                approved_notional_usd=1_000.0,
                reasons=[],
                policy_version="mvp-v1",
            ),
            settings,
        )


def anchor_it(audit: Path, anchors: Path) -> None:
    import asyncio

    store = JsonlAuditAnchorStore(anchors)
    asyncio.run(AuditAnchorPublisher(sink=store, path=audit).publish_now())


def test_missing_trail_exits_2(tmp_path: Path, capsys) -> None:
    code = main(["--audit-path", str(tmp_path / "nope.jsonl")])
    assert code == 2
    assert "no risk audit trail found" in capsys.readouterr().out


def test_intact_and_anchored_trail_exits_0(tmp_path: Path, capsys) -> None:
    audit = tmp_path / "risk.jsonl"
    anchors = tmp_path / "anchors.jsonl"
    write_trail(audit, count=4)
    anchor_it(audit, anchors)

    code = main(["--audit-path", str(audit), "--anchor-path", str(anchors)])
    assert code == 0
    assert "result:  OK" in capsys.readouterr().out


def test_rewritten_trail_exits_1_and_names_the_divergence(tmp_path: Path, capsys) -> None:
    audit = tmp_path / "risk.jsonl"
    anchors = tmp_path / "anchors.jsonl"
    write_trail(audit, count=4)
    anchor_it(audit, anchors)
    audit.unlink()
    write_trail(audit, count=4, asset="ETH")

    code = main(["--audit-path", str(audit), "--anchor-path", str(anchors), "--json"])
    assert code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["valid"] is False
    # The chain itself is intact; only the anchor catches the rewrite.
    assert payload["chain"]["valid"] is True
    assert payload["diverged_at_sequence"] == 3


def test_unanchored_trail_fails_closed_unless_explicitly_allowed(tmp_path: Path, capsys) -> None:
    audit = tmp_path / "risk.jsonl"
    write_trail(audit, count=3)

    assert main(["--audit-path", str(audit), "--anchor-path", str(tmp_path / "none.jsonl")]) == 1
    capsys.readouterr()

    code = main(
        [
            "--audit-path",
            str(audit),
            "--anchor-path",
            str(tmp_path / "none.jsonl"),
            "--allow-unanchored",
        ]
    )
    assert code == 0
    assert "result:  OK" in capsys.readouterr().out
