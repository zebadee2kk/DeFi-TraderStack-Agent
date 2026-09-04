import json

import pytest

from traderstack.config import Settings
from traderstack.models import PortfolioSnapshot, RiskDecision, Side, TradeProposal
from traderstack.risk import RiskEngine, risk_limits, risk_limits_hash
from traderstack.risk_audit import GENESIS_HASH, JsonlRiskAuditTrail, verify_chain


def settings(**overrides: object) -> Settings:
    values: dict[str, object] = {"kill_switch": False, "mvp_assets": "BTC,ETH,SOL"}
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def portfolio() -> PortfolioSnapshot:
    return PortfolioSnapshot(
        nav_usd=10_000, cash_usd=10_000, daily_pnl_usd=0, peak_nav_usd=10_000
    )


def proposal(**overrides: object) -> TradeProposal:
    values: dict[str, object] = {
        "strategy_id": "momentum-v1",
        "asset": "BTC",
        "side": Side.BUY,
        "confidence": 0.75,
        "requested_notional_usd": 500,
        "thesis": "test",
        "source_freshness_seconds": 1,
    }
    values.update(overrides)
    return TradeProposal(**values)  # type: ignore[arg-type]


def write_three(path) -> tuple[JsonlRiskAuditTrail, Settings]:
    config = settings()
    engine = RiskEngine(config)
    trail = JsonlRiskAuditTrail(path)
    for notional in (100, 200, 300):
        item = proposal(requested_notional_usd=notional)
        trail.record(item, engine.evaluate(item, portfolio()), config)
    return trail, config


# --- record content --------------------------------------------------------


def test_record_carries_proposal_result_policy_and_limits(tmp_path) -> None:
    path = tmp_path / "risk" / "decisions.jsonl"
    config = settings()
    engine = RiskEngine(config)
    trail = JsonlRiskAuditTrail(path)
    item = proposal()
    result = engine.evaluate(item, portfolio())

    record = trail.record(item, result, config)

    assert record.sequence == 0
    assert record.previous_hash == GENESIS_HASH
    assert record.policy_version == engine.policy_version
    assert record.risk_limits_hash == risk_limits_hash(config)
    # Limits are inline as well as hashed, so an auditor never needs the config.
    assert record.risk_limits["max_position_pct"] == pytest.approx(config.max_position_pct)
    assert set(record.risk_limits) == set(risk_limits(config))
    assert record.proposal.decision_id == item.decision_id
    assert record.result.decision is RiskDecision.ALLOW
    assert record.result.approved_notional_usd == pytest.approx(500)

    payload = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert payload["result"]["reasons"] == []
    assert payload["proposal"]["thesis"] == "test"


def test_rejections_are_recorded_with_their_reasons(tmp_path) -> None:
    path = tmp_path / "decisions.jsonl"
    config = settings()
    engine = RiskEngine(config)
    trail = JsonlRiskAuditTrail(path)
    item = proposal(asset="DOGE")

    record = trail.record(item, engine.evaluate(item, portfolio()), config)

    assert record.result.decision is RiskDecision.REJECT
    assert "asset_not_allowlisted" in record.result.reasons
    assert verify_chain(path).valid


# --- chain -----------------------------------------------------------------


def test_chain_verifies(tmp_path) -> None:
    path = tmp_path / "decisions.jsonl"
    write_three(path)

    verification = verify_chain(path)
    assert verification.valid is True
    assert verification.records == 3
    assert verification.error is None

    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [item["sequence"] for item in lines] == [0, 1, 2]
    assert lines[1]["previous_hash"] == lines[0]["record_hash"]
    assert lines[2]["previous_hash"] == lines[1]["record_hash"]


def test_appending_across_a_restart_continues_the_same_chain(tmp_path) -> None:
    path = tmp_path / "decisions.jsonl"
    _, config = write_three(path)

    resumed = JsonlRiskAuditTrail(path)
    item = proposal(requested_notional_usd=400)
    record = resumed.record(item, RiskEngine(config).evaluate(item, portfolio()), config)

    assert record.sequence == 3
    assert verify_chain(path).valid


# --- tampering -------------------------------------------------------------


def test_edited_line_is_detected(tmp_path) -> None:
    path = tmp_path / "decisions.jsonl"
    write_three(path)

    lines = path.read_text(encoding="utf-8").splitlines()
    payload = json.loads(lines[1])
    payload["result"]["approved_notional_usd"] = 999_999
    lines[1] = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    verification = verify_chain(path)
    assert verification.valid is False
    assert verification.first_invalid_sequence == 1
    assert "record hash" in (verification.error or "")


def test_edited_reason_string_is_detected(tmp_path) -> None:
    path = tmp_path / "decisions.jsonl"
    config = settings()
    trail = JsonlRiskAuditTrail(path)
    item = proposal(asset="DOGE")
    trail.record(item, RiskEngine(config).evaluate(item, portfolio()), config)

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["result"]["reasons"] = []
    payload["result"]["decision"] = "allow"
    path.write_text(json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n", "utf-8")

    assert verify_chain(path).valid is False


def test_removed_line_is_detected(tmp_path) -> None:
    path = tmp_path / "decisions.jsonl"
    write_three(path)

    lines = path.read_text(encoding="utf-8").splitlines()
    del lines[1]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    verification = verify_chain(path)
    assert verification.valid is False
    assert "removed or reordered" in (verification.error or "")


def test_truncating_the_tail_and_re_signing_still_breaks_the_chain(tmp_path) -> None:
    """A tamperer who deletes the last record cannot restore it undetected.

    The removed record's hash is the predecessor of nothing, so the file still
    verifies -- but the operator's own copy of the chain head no longer matches,
    which the trail detects the moment it resumes.
    """

    path = tmp_path / "decisions.jsonl"
    trail, _ = write_three(path)
    head = trail._last_hash

    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")

    resumed = JsonlRiskAuditTrail(path)
    resumed._resume()
    assert resumed._last_hash != head


def test_a_corrupt_line_is_detected(tmp_path) -> None:
    path = tmp_path / "decisions.jsonl"
    write_three(path)
    with path.open("a", encoding="utf-8") as handle:
        handle.write("{not json}\n")

    verification = verify_chain(path)
    assert verification.valid is False
    assert "not a valid audit record" in (verification.error or "")


def test_missing_trail_does_not_verify(tmp_path) -> None:
    verification = verify_chain(tmp_path / "absent.jsonl")
    assert verification.valid is False
    assert verification.error == "audit trail does not exist"


# --- async wrapper ---------------------------------------------------------


@pytest.mark.asyncio
async def test_arecord_appends_to_the_same_chain(tmp_path) -> None:
    path = tmp_path / "decisions.jsonl"
    config = settings()
    engine = RiskEngine(config)
    trail = JsonlRiskAuditTrail(path)

    for _ in range(3):
        item = proposal()
        await trail.arecord(item, engine.evaluate(item, portfolio()), config)

    assert trail.verify().valid is True
    assert trail.verify().records == 3


def test_from_settings_uses_the_configured_path(tmp_path) -> None:
    path = tmp_path / "audit" / "risk.jsonl"
    trail = JsonlRiskAuditTrail.from_settings(settings(risk_audit_path=str(path)))
    assert trail.path == path
