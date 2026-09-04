"""Immutable risk-decision audit trail (Epic 7).

Every ``RiskEngine.evaluate`` outcome is appended to a JSONL file as a
hash-chained record. Each record carries:

* the full ``TradeProposal`` that was judged,
* the full ``RiskResult`` (decision, approved notional, every reason string),
* the policy version in force,
* the risk limits in force, inline *and* as a SHA-256 digest,
* the meta-agent's review of this same cycle, when one ran (Epic 6) -- so a
  veto or an unavailable-review suppression that nulled the paper order after
  the risk engine approved it is visible on the *same* record, not only
  inferable by cross-referencing a separate log,
* the execution outcome (``execution_status``/``execution_reason``) the cycle
  actually reached, when a submission was attempted,
* ``previous_hash`` -- the ``record_hash`` of the preceding record,
* ``record_hash`` -- SHA-256 over the canonical JSON of everything above.

Because each hash commits to its predecessor, editing or deleting any line
invalidates every record after it. ``verify_chain`` reports the first sequence
number where the chain breaks. The file is append-only by construction: this
module never opens it for anything but ``"a"``, and offers no update or delete.

This is evidence, not control flow: recording a decision never changes it. A
record showing ``result.decision == ALLOW`` together with
``meta_review.suppressed_order == True`` is not a contradiction: it is the
whole point of recording both -- the deterministic risk engine approved the
notional, and the bounded meta-agent review withheld it before execution. An
auditor reading only ``result`` would otherwise believe the order was sent.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from traderstack.agents.review import MetaAgentReview
from traderstack.config import Settings
from traderstack.models import RiskResult, TradeProposal
from traderstack.risk import risk_limits, risk_limits_hash

GENESIS_HASH = "0" * 64


class RiskAuditRecord(BaseModel):
    sequence: int = Field(ge=0)
    recorded_at: datetime
    policy_version: str
    risk_limits: dict[str, Any]
    risk_limits_hash: str
    proposal: TradeProposal
    result: RiskResult
    # --- meta-agent (Epic 6): the review that ran against this same proposal,
    # when the reviewer was in play. None when the meta-agent was off or never
    # reached (e.g. the deterministic layer already rejected the cycle).
    meta_review: MetaAgentReview | None = None
    # The execution outcome this cycle actually reached, when a submission was
    # attempted (None when submission was disabled or never eligible).
    execution_status: str | None = None
    execution_reason: str | None = None
    previous_hash: str
    record_hash: str

    def body(self) -> dict[str, Any]:
        """The signed portion of the record: everything except ``record_hash``."""

        payload = self.model_dump(mode="json")
        payload.pop("record_hash", None)
        return payload

    def expected_hash(self) -> str:
        return hash_body(self.body())


def hash_body(body: dict[str, Any]) -> str:
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ChainVerification(BaseModel):
    valid: bool
    records: int = Field(default=0, ge=0)
    error: str | None = None
    # Sequence number of the first record that failed verification, when known.
    first_invalid_sequence: int | None = None

    def __bool__(self) -> bool:  # pragma: no cover - convenience only
        return self.valid


@dataclass
class JsonlRiskAuditTrail:
    """Append-only, hash-chained JSONL sink for risk decisions."""

    path: Path
    _sequence: int = field(default=-1, init=False)
    _last_hash: str = field(default=GENESIS_HASH, init=False)
    _resumed: bool = field(default=False, init=False)

    @classmethod
    def from_settings(cls, settings: Settings) -> JsonlRiskAuditTrail:
        return cls(Path(settings.risk_audit_path))

    def _resume(self) -> None:
        """Pick up the chain head from an existing file so restarts keep the chain."""

        if self._resumed:
            return
        self._resumed = True
        if not self.path.exists():
            return
        last_line = ""
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    last_line = line
        if not last_line:
            return
        record = RiskAuditRecord.model_validate_json(last_line)
        self._sequence = record.sequence
        self._last_hash = record.record_hash

    def record(
        self,
        proposal: TradeProposal,
        result: RiskResult,
        settings: Settings,
        *,
        at: datetime | None = None,
        meta_review: MetaAgentReview | None = None,
        execution_status: str | None = None,
        execution_reason: str | None = None,
    ) -> RiskAuditRecord:
        self._resume()
        body = {
            "sequence": self._sequence + 1,
            "recorded_at": (at or datetime.now(UTC)).isoformat(),
            "policy_version": result.policy_version,
            "risk_limits": json.loads(json.dumps(risk_limits(settings), default=str)),
            "risk_limits_hash": risk_limits_hash(settings),
            "proposal": proposal.model_dump(mode="json"),
            "result": result.model_dump(mode="json"),
            "meta_review": meta_review.model_dump(mode="json") if meta_review is not None else None,
            "execution_status": execution_status,
            "execution_reason": execution_reason,
            "previous_hash": self._last_hash,
        }
        # Hash the model's own canonical JSON so a record written here and the
        # same record parsed back off disk hash identically.
        draft = RiskAuditRecord.model_validate({**body, "record_hash": ""})
        digest = draft.expected_hash()
        record = draft.model_copy(update={"record_hash": digest})
        self._append(record)
        self._sequence = record.sequence
        self._last_hash = digest
        return record

    async def arecord(
        self,
        proposal: TradeProposal,
        result: RiskResult,
        settings: Settings,
        *,
        at: datetime | None = None,
        meta_review: MetaAgentReview | None = None,
        execution_status: str | None = None,
        execution_reason: str | None = None,
    ) -> RiskAuditRecord:
        return await asyncio.to_thread(
            self.record,
            proposal,
            result,
            settings,
            at=at,
            meta_review=meta_review,
            execution_status=execution_status,
            execution_reason=execution_reason,
        )

    def _append(self, record: RiskAuditRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record.model_dump(mode="json"), separators=(",", ":"), sort_keys=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
            handle.flush()

    def verify(self) -> ChainVerification:
        return verify_chain(self.path)


def verify_chain(path: Path) -> ChainVerification:
    """Verify an on-disk risk audit trail, detecting edited or removed lines."""

    path = Path(path)
    if not path.exists():
        return ChainVerification(valid=False, error="audit trail does not exist")

    previous_hash = GENESIS_HASH
    expected_sequence = 0
    count = 0
    with path.open("r", encoding="utf-8") as handle:
        for number, raw in enumerate(handle, start=1):
            if not raw.strip():
                continue
            try:
                record = RiskAuditRecord.model_validate_json(raw)
            except Exception as exc:  # noqa: BLE001 - malformed line is tampering.
                return ChainVerification(
                    valid=False,
                    records=count,
                    error=f"line {number} is not a valid audit record: {exc}",
                    first_invalid_sequence=expected_sequence,
                )
            if record.sequence != expected_sequence:
                return ChainVerification(
                    valid=False,
                    records=count,
                    error=(
                        f"line {number} has sequence {record.sequence}, "
                        f"expected {expected_sequence} (a record was removed or reordered)"
                    ),
                    first_invalid_sequence=record.sequence,
                )
            if record.previous_hash != previous_hash:
                return ChainVerification(
                    valid=False,
                    records=count,
                    error=f"line {number} does not chain to its predecessor",
                    first_invalid_sequence=record.sequence,
                )
            if record.expected_hash() != record.record_hash:
                return ChainVerification(
                    valid=False,
                    records=count,
                    error=f"line {number} content does not match its record hash (edited)",
                    first_invalid_sequence=record.sequence,
                )
            previous_hash = record.record_hash
            expected_sequence += 1
            count += 1

    return ChainVerification(valid=True, records=count)
