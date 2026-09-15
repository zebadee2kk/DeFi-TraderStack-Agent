"""External anchoring for the risk-audit hash chain (#68).

`JsonlRiskAuditTrail` is SHA-256 hash-chained, and `verify_chain` detects any
edited, removed or reordered line. That protects against tampering *within* the
file. It does not protect against a whole-file rewrite: anyone with write access
to `var/audit/` can regenerate the chain from genesis with different content,
and the result verifies perfectly, because the only root of trust is the file
itself.

For a system whose central claim is "a complete auditable decision trail", and
whose threat model assumes the host may be compromised, the chain head has to
live somewhere the trading process cannot rewrite. This module publishes
`{sequence, head_hash, policy_version, anchored_at}` to one or more sinks
outside the audit file, and cross-checks the file against them.

What an anchor does and does not buy you:

* A rewritten file is detected as soon as *any* surviving anchor names a
  sequence whose `record_hash` no longer matches. The attacker would have to
  forge every anchor in every channel as well as the file.
* A truncated or restored-from-backup file is detected because its head is
  behind an anchor that was already published.
* An anchor sink on the same host, writing to a file the same process can
  reach, is a weaker root of trust than a remote one. `JsonlAuditAnchorStore`
  exists for local operation and tests; Redis and Postgres sinks with
  insert-only grants, or an operator-held remote receiver, are the real
  boundary. `docs/SECURITY-THREAT-MODEL.md` records which is in play.

Publishing is evidence, never control flow: a sink that is down must never stop
the trading cycle, so `FanoutAuditAnchorSink` swallows and counts failures the
same way the runtime event sinks do. Verification is the opposite posture — an
unreadable or divergent anchor fails closed.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, Field

from traderstack._fs import append_jsonl
from traderstack.metrics import record_audit_anchor_failure
from traderstack.risk_audit import ChainVerification, RiskAuditRecord, verify_chain

# Redis key the head anchor is published under. Namespaced so an operator can
# grant the app SET on exactly this key and nothing else.
DEFAULT_REDIS_ANCHOR_KEY = "traderstack:audit:head"


class AuditAnchor(BaseModel):
    """A published commitment to the audit chain head at one point in time."""

    sequence: int = Field(ge=0)
    head_hash: str
    policy_version: str
    anchored_at: datetime

    def to_json(self) -> str:
        return json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


class AnchorVerification(BaseModel):
    """Result of checking an audit file against its published anchors."""

    valid: bool
    chain: ChainVerification
    anchors_checked: int = Field(default=0, ge=0)
    error: str | None = None
    #: Sequence number where the file and an anchor disagree, when known.
    diverged_at_sequence: int | None = None

    def __bool__(self) -> bool:  # pragma: no cover - convenience only
        return self.valid


class AuditAnchorSink(Protocol):
    """Somewhere a chain head can be published and read back.

    Structural on purpose, like `killswitch.RedisKeyProbe`: a real
    `redis.asyncio.Redis` or a SQLAlchemy engine satisfies the concrete sinks
    below without this module importing either.
    """

    async def publish(self, anchor: AuditAnchor) -> None: ...

    async def anchors(self) -> list[AuditAnchor]: ...


def head_anchor(path: Path, *, at: datetime | None = None) -> AuditAnchor | None:
    """The current chain head of ``path`` as a publishable anchor.

    Returns ``None`` for a missing or empty trail — there is nothing to commit
    to yet, which is not an error on a first run.
    """

    path = Path(path)
    if not path.exists():
        return None
    last_line = ""
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                last_line = line
    if not last_line:
        return None
    record = RiskAuditRecord.model_validate_json(last_line)
    return AuditAnchor(
        sequence=record.sequence,
        head_hash=record.record_hash,
        policy_version=record.policy_version,
        anchored_at=at or datetime.now(UTC),
    )


def _hashes_by_sequence(path: Path) -> dict[int, str]:
    hashes: dict[int, str] = {}
    with Path(path).open("r", encoding="utf-8") as handle:
        for raw in handle:
            if not raw.strip():
                continue
            record = RiskAuditRecord.model_validate_json(raw)
            hashes[record.sequence] = record.record_hash
    return hashes


def verify_with_anchors(path: Path, anchors: list[AuditAnchor]) -> AnchorVerification:
    """Verify the chain *and* cross-check every anchor against it.

    This is what a regenerate-from-genesis rewrite cannot survive. The rewritten
    file has a self-consistent chain, so `verify_chain` alone passes it; but the
    record at an anchored sequence hashes to something the anchor does not name,
    and that mismatch is reported with the sequence number of divergence.

    Fails closed: no anchors at all is *not* success, because an attacker who
    can rewrite the file can also delete a local anchor store. A caller that
    genuinely has no anchors yet should say so explicitly rather than read a
    pass out of this.
    """

    path = Path(path)
    chain = verify_chain(path)
    if not chain.valid:
        return AnchorVerification(
            valid=False,
            chain=chain,
            anchors_checked=0,
            error=chain.error,
            diverged_at_sequence=chain.first_invalid_sequence,
        )

    if not anchors:
        return AnchorVerification(
            valid=False,
            chain=chain,
            anchors_checked=0,
            error=(
                "no anchors available: an intact chain proves only internal "
                "consistency, not that the file was never rewritten from genesis"
            ),
        )

    hashes = _hashes_by_sequence(path)
    for anchor in sorted(anchors, key=lambda item: item.sequence):
        found = hashes.get(anchor.sequence)
        if found is None:
            return AnchorVerification(
                valid=False,
                chain=chain,
                anchors_checked=len(anchors),
                error=(
                    f"anchor at sequence {anchor.sequence} has no record in the "
                    f"trail (the file is truncated or was restored from an "
                    f"earlier backup; it holds {chain.records} record(s))"
                ),
                diverged_at_sequence=anchor.sequence,
            )
        if found != anchor.head_hash:
            return AnchorVerification(
                valid=False,
                chain=chain,
                anchors_checked=len(anchors),
                error=(
                    f"record {anchor.sequence} hashes to {found[:12]} but the "
                    f"published anchor commits to {anchor.head_hash[:12]}: the "
                    f"trail was rewritten"
                ),
                diverged_at_sequence=anchor.sequence,
            )

    return AnchorVerification(valid=True, chain=chain, anchors_checked=len(anchors))


@dataclass
class JsonlAuditAnchorStore:
    """Append-only anchor log on local disk.

    The weakest of the sinks — a process that can rewrite the audit file can
    usually rewrite this too — but it makes the whole path testable, and it is
    a real control when the file is shipped off-host or written to a mount the
    trading process cannot reach.
    """

    path: Path

    async def publish(self, anchor: AuditAnchor) -> None:
        # Off the event loop: the trading cycle awaits this, and a slow disk
        # must not stall it (same reason JsonlRiskAuditTrail.arecord threads).
        await asyncio.to_thread(append_jsonl, Path(self.path), anchor.to_json())

    async def anchors(self) -> list[AuditAnchor]:
        return await asyncio.to_thread(self._read)

    def _read(self) -> list[AuditAnchor]:
        path = Path(self.path)
        if not path.exists():
            return []
        found: list[AuditAnchor] = []
        with path.open("r", encoding="utf-8") as handle:
            for raw in handle:
                if raw.strip():
                    found.append(AuditAnchor.model_validate_json(raw))
        return found


class RedisAnchorClient(Protocol):
    """The two Redis calls this sink needs, structurally.

    Non-async signatures returning ``Awaitable`` so a real
    ``redis.asyncio.Redis`` satisfies this, matching
    ``killswitch.RedisKeyProbe``: redis-py's methods are sync functions that
    return awaitables, not coroutine functions.
    """

    def set(self, name: str, value: str, /) -> Awaitable[object]: ...

    def get(self, name: str, /) -> Awaitable[object]: ...


@dataclass
class RedisAuditAnchorStore:
    """Publishes the head anchor to a single Redis key.

    Holds the latest head only, which is enough to catch a rewrite or a
    rollback: the newest anchor is the one an attacker most needs to match.
    """

    client: RedisAnchorClient
    key: str = DEFAULT_REDIS_ANCHOR_KEY

    async def publish(self, anchor: AuditAnchor) -> None:
        await self.client.set(self.key, anchor.to_json())

    async def anchors(self) -> list[AuditAnchor]:
        raw = await self.client.get(self.key)
        if raw is None:
            return []
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        if not isinstance(raw, str):
            # A client that returned something unexpected is unreadable state,
            # not an empty anchor set: say so rather than silently passing.
            raise TypeError(f"redis anchor key {self.key} holds {type(raw).__name__}, not a string")
        return [AuditAnchor.model_validate_json(raw)]


@dataclass
class FanoutAuditAnchorSink:
    """Publishes to every configured sink; one failure never blocks the cycle.

    Same posture as the runtime event sinks: anchoring is evidence, and a Redis
    outage must not stop trading. Every failure is counted so an operator can
    alert on "we have not anchored in N minutes" rather than discovering it at
    audit time.
    """

    sinks: dict[str, AuditAnchorSink] = field(default_factory=dict)

    async def publish(self, anchor: AuditAnchor) -> None:
        for name, sink in self.sinks.items():
            try:
                await sink.publish(anchor)
            except Exception:  # noqa: BLE001 - a down sink must not stop trading.
                record_audit_anchor_failure(name)

    async def anchors(self) -> list[AuditAnchor]:
        """Every anchor every sink can still produce.

        Read failures are counted and skipped rather than raised: one reachable
        sink is enough to catch a rewrite, and demanding all of them would let
        an attacker suppress verification by taking one offline.
        """

        found: list[AuditAnchor] = []
        for name, sink in self.sinks.items():
            try:
                found.extend(await sink.anchors())
            except Exception:  # noqa: BLE001 - counted; other sinks still count.
                record_audit_anchor_failure(name)
        return found


@dataclass
class AuditAnchorPublisher:
    """Decides when to publish: every ``anchor_every`` records, and on shutdown."""

    sink: AuditAnchorSink
    path: Path
    anchor_every: int = 25
    _last_anchored_sequence: int = field(default=-1, init=False)

    def __post_init__(self) -> None:
        if self.anchor_every <= 0:
            raise ValueError("anchor_every must be positive")

    async def maybe_publish(self, sequence: int) -> AuditAnchor | None:
        """Publish if ``anchor_every`` records have passed since the last anchor."""

        if sequence - self._last_anchored_sequence < self.anchor_every:
            return None
        return await self.publish_now()

    async def publish_now(self) -> AuditAnchor | None:
        """Publish the current head unconditionally (shutdown, or on demand)."""

        anchor = head_anchor(Path(self.path))
        if anchor is None:
            return None
        await self.sink.publish(anchor)
        self._last_anchored_sequence = anchor.sequence
        return anchor


async def assert_trail_matches_anchors(path: Path, sink: AuditAnchorSink) -> AnchorVerification:
    """Startup gate: refuse to append to a trail that disagrees with its anchors.

    Fail-closed by design, matching the kill switch and reconciliation: an
    audit file that has been restored from backup, truncated, or regenerated
    must be caught *before* new records are appended onto a forked chain, not
    at the next audit.

    A trail that does not exist yet is the one benign case — a first run has
    nothing to contradict — and returns valid with no anchors checked.
    """

    path = Path(path)
    anchors = await sink.anchors()
    if not path.exists():
        if anchors:
            return AnchorVerification(
                valid=False,
                chain=ChainVerification(valid=False, error="audit trail does not exist"),
                anchors_checked=len(anchors),
                error=(
                    "audit trail is missing but anchors exist: the file was "
                    "deleted after it was anchored"
                ),
                diverged_at_sequence=min(anchor.sequence for anchor in anchors),
            )
        return AnchorVerification(valid=True, chain=ChainVerification(valid=True, records=0))
    if not anchors:
        # Nothing published yet (first run with anchoring newly enabled). An
        # intact chain is all that can be asked for here.
        chain = verify_chain(path)
        return AnchorVerification(
            valid=chain.valid,
            chain=chain,
            anchors_checked=0,
            error=chain.error,
            diverged_at_sequence=chain.first_invalid_sequence,
        )
    return verify_with_anchors(path, anchors)
