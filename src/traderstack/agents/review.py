"""Constrained meta-agent review stage for the live loop (Epic 6).

The pipeline produces a proposal, sizes it and passes it through the risk engine.
This module inserts one bounded review step between that result and execution.

Guarantees this module is responsible for:

* The reviewer can only *withhold* risk. It never chooses a side, an asset, a
  venue or a size, and it never edits `risk_result` / `approved_notional_usd`.
  Sizing is already fixed by the deterministic risk engine before the model is
  asked anything, so even an approval with a positive confidence delta cannot
  increase notional.
* Fail closed. A timeout, an exception, a refusal, an invalid payload or an
  exhausted budget all produce `meta_agent_unavailable` in veto mode; there is no
  path on which a failed review silently approves.
* Bounded cost. Identical evidence inside the cache window is not re-asked, and
  daily call/token budgets are enforced before the request is made.
* Auditability. Every cycle records the prompt version and content hash, the
  model id, the latency, the token usage and an estimated cost.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from traderstack.agents import metrics
from traderstack.agents.meta import (
    EvidencePacket,
    MetaAgentCall,
    MetaAgentClient,
    PreTradeSummary,
    RiskSummary,
    UsageReportingMetaAgentClient,
)
from traderstack.agents.prompts import RegisteredPrompt, meta_agent_prompt
from traderstack.agents.specialists import SpecialistCommittee
from traderstack.pipeline import PipelineResult
from traderstack.strategies import Regime, StrategySignal

VETO_REASON = "meta_agent_veto"
UNAVAILABLE_REASON = "meta_agent_unavailable"


class MetaAgentMode(StrEnum):
    OFF = "off"
    ADVISORY = "advisory"
    VETO = "veto"


class MetaAgentReview(BaseModel):
    """Audit record of one review cycle."""

    mode: MetaAgentMode
    called: bool = False
    cached: bool = False
    approved: bool | None = None
    confidence_delta: float | None = None
    rationale: str | None = None
    risk_flags: list[str] = Field(default_factory=list)
    prompt_version: str
    prompt_hash: str
    model: str | None = None
    latency_seconds: float | None = None
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    estimated_cost_usd: float = Field(default=0.0, ge=0)
    error: str | None = None
    evidence_digest: str | None = None
    suppressed_order: bool = False
    suppression_reason: str | None = None
    applied_confidence: float | None = None
    specialist_signals: list[StrategySignal] = Field(default_factory=list)

    @property
    def usable(self) -> bool:
        """True only when a decision actually came back and validated."""
        return self.error is None and self.approved is not None


@dataclass
class DailyBudget:
    """UTC-day call and token budgets. Zero means unlimited."""

    max_calls: int = 0
    max_tokens: int = 0
    day: date | None = None
    calls: int = 0
    tokens: int = 0

    def _roll(self, now: datetime) -> None:
        today = now.astimezone(UTC).date()
        if self.day != today:
            self.day = today
            self.calls = 0
            self.tokens = 0

    def exhausted(self, now: datetime | None = None) -> str | None:
        self._roll(now or datetime.now(UTC))
        if self.max_calls and self.calls >= self.max_calls:
            return "daily_call_budget_exhausted"
        if self.max_tokens and self.tokens >= self.max_tokens:
            return "daily_token_budget_exhausted"
        return None

    def record(self, tokens: int, now: datetime | None = None) -> None:
        self._roll(now or datetime.now(UTC))
        self.calls += 1
        self.tokens += max(0, tokens)
        metrics.meta_agent_daily_calls.set(self.calls)
        metrics.meta_agent_daily_tokens.set(self.tokens)


@dataclass
class EvidenceCache:
    """Short-lived cache keyed by the evidence digest.

    Only successful reviews are cached: caching a failure would extend a provider
    outage past its actual duration, and in veto mode that means suppressing
    trades for longer than necessary.
    """

    ttl_seconds: float = 60.0
    _entries: dict[str, tuple[float, MetaAgentReview]] = field(default_factory=dict)

    def get(self, digest: str) -> MetaAgentReview | None:
        if self.ttl_seconds <= 0:
            return None
        entry = self._entries.get(digest)
        if entry is None:
            return None
        stored_at, review = entry
        if time.monotonic() - stored_at > self.ttl_seconds:
            del self._entries[digest]
            return None
        return review

    def put(self, digest: str, review: MetaAgentReview) -> None:
        if self.ttl_seconds <= 0 or not review.usable:
            return
        self._entries[digest] = (time.monotonic(), review)


def evidence_digest(packet: EvidencePacket) -> str:
    """Stable hash of the decision-relevant content of an evidence packet.

    Wall-clock observation times are excluded so that two cycles carrying the same
    numbers hash the same; freshness is enforced upstream by the market-data and
    pre-trade gates, not here.
    """
    payload = packet.model_dump(mode="json", exclude={"feature_vector": {"observed_at"}})
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def summarize_pretrade(result: PipelineResult) -> PreTradeSummary | None:
    check = result.pretrade_check
    if check is None:
        return None
    metrics_ = check.metrics
    walkforward = check.walkforward
    return PreTradeSummary(
        passed=check.passed,
        reasons=list(check.reasons),
        confirmed_side=check.confirmed_side,
        confidence=check.confidence,
        regime=check.regime,
        candles_evaluated=check.candles_evaluated,
        excess_return=metrics_.excess_return if metrics_ is not None else None,
        max_drawdown=metrics_.max_drawdown if metrics_ is not None else None,
        sharpe=metrics_.sharpe if metrics_ is not None else None,
        trades=metrics_.trades if metrics_ is not None else None,
        walkforward_mean_excess_return=(
            walkforward.mean_excess_return if walkforward is not None else None
        ),
        walkforward_worst_drawdown=(
            walkforward.worst_drawdown if walkforward is not None else None
        ),
    )


def build_evidence_packet(
    symbol: str,
    result: PipelineResult,
    committee: SpecialistCommittee | None = None,
) -> EvidencePacket | None:
    """Assemble the packet for one cycle, or None when there is nothing to review."""
    proposal = result.proposal
    vector = result.feature_vector
    if proposal is None or vector is None:
        return None

    regime = result.pretrade_check.regime if result.pretrade_check is not None else None
    regime = regime or Regime.RANGE
    specialists = committee.evaluate(vector, regime, symbol) if committee is not None else ()

    direction = 1.0 if proposal.side.value == "buy" else -1.0
    baseline = StrategySignal(
        strategy_id=proposal.signal_ids[0] if proposal.signal_ids else proposal.strategy_id,
        symbol=symbol,
        side=proposal.side,
        score=max(-1.0, min(1.0, proposal.confidence * direction)),
        confidence=proposal.confidence,
        regime=regime,
        rationale=proposal.thesis,
    )

    risk = None
    if result.risk_result is not None:
        risk = RiskSummary(
            decision=result.risk_result.decision,
            approved_notional_usd=result.risk_result.approved_notional_usd,
            reasons=list(result.risk_result.reasons),
            policy_version=result.risk_result.policy_version,
        )

    return EvidencePacket(
        asset=proposal.asset.upper(),
        feature_vector=vector,
        strategy_signal=baseline,
        requested_notional_usd=proposal.requested_notional_usd,
        specialist_signals=list(specialists),
        pretrade=summarize_pretrade(result),
        risk=risk,
    )


@dataclass
class MetaAgentReviewer:
    """Runs the bounded review and applies its (limited) effect to the cycle."""

    # Any awaitable `(EvidencePacket) -> MetaAgentDecision`. A client that also
    # implements `UsageReportingMetaAgentClient.review` additionally reports the
    # model id and token usage, which is what fills in the cost telemetry.
    client: MetaAgentClient | None = None
    mode: MetaAgentMode = MetaAgentMode.ADVISORY
    model: str = "unknown"
    timeout_seconds: float = 20.0
    prompt: RegisteredPrompt = field(default_factory=meta_agent_prompt)
    committee: SpecialistCommittee | None = field(default_factory=SpecialistCommittee)
    cache: EvidenceCache = field(default_factory=EvidenceCache)
    budget: DailyBudget = field(default_factory=DailyBudget)
    # Operator-supplied model pricing; API list prices change independently of
    # this repository, so they are configuration, not constants.
    input_cost_per_mtok: float = 0.0
    output_cost_per_mtok: float = 0.0

    def _record(
        self,
        *,
        called: bool = False,
        approved: bool | None = None,
        confidence_delta: float | None = None,
        rationale: str | None = None,
        risk_flags: list[str] | None = None,
        model: str | None = None,
        latency_seconds: float | None = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        estimated_cost_usd: float = 0.0,
        error: str | None = None,
        digest: str | None = None,
        specialist_signals: list[StrategySignal] | None = None,
    ) -> MetaAgentReview:
        return MetaAgentReview(
            mode=self.mode,
            called=called,
            approved=approved,
            confidence_delta=confidence_delta,
            rationale=rationale,
            risk_flags=risk_flags or [],
            prompt_version=self.prompt.version,
            prompt_hash=self.prompt.content_hash,
            model=model or self.model,
            latency_seconds=latency_seconds,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost_usd=estimated_cost_usd,
            error=error,
            evidence_digest=digest,
            specialist_signals=specialist_signals or [],
        )

    async def run(self, symbol: str, result: PipelineResult) -> tuple[PipelineResult, MetaAgentReview]:
        """Review the cycle and return the (possibly restricted) pipeline result."""
        review = await self.review(symbol, result)
        return self.apply(result, review)

    async def review(self, symbol: str, result: PipelineResult) -> MetaAgentReview:
        if self.mode is MetaAgentMode.OFF or self.client is None:
            return self._record()

        packet = build_evidence_packet(symbol, result, self.committee)
        if packet is None:
            # Nothing reached the reviewer: the deterministic layer already
            # rejected this cycle, so there is no new risk to withhold.
            return self._record()

        digest = evidence_digest(packet)
        cached = self.cache.get(digest)
        if cached is not None:
            metrics.meta_agent_reviews_total.labels(mode=self.mode.value, outcome="cached").inc()
            return cached.model_copy(
                update={"cached": True, "specialist_signals": list(packet.specialist_signals)}
            )

        exhausted = self.budget.exhausted()
        if exhausted is not None:
            metrics.meta_agent_reviews_total.labels(
                mode=self.mode.value, outcome="budget_exhausted"
            ).inc()
            return self._record(
                digest=digest,
                error=exhausted,
                specialist_signals=list(packet.specialist_signals),
            )

        started = time.monotonic()
        try:
            call = await asyncio.wait_for(self._call(packet), timeout=self.timeout_seconds)
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            # A failed call still consumed provider quota, so it counts against
            # the daily call budget even though it produced no usable decision.
            self.budget.record(0)
            metrics.meta_agent_reviews_total.labels(mode=self.mode.value, outcome="timeout").inc()
            return self._record(
                called=True,
                digest=digest,
                latency_seconds=time.monotonic() - started,
                error=f"timeout after {self.timeout_seconds}s",
                specialist_signals=list(packet.specialist_signals),
            )
        except Exception as exc:  # noqa: BLE001 - every failure mode is a fail-closed review.
            self.budget.record(0)
            metrics.meta_agent_reviews_total.labels(mode=self.mode.value, outcome="error").inc()
            return self._record(
                called=True,
                digest=digest,
                latency_seconds=time.monotonic() - started,
                error=f"{type(exc).__name__}: {exc}",
                specialist_signals=list(packet.specialist_signals),
            )

        latency = time.monotonic() - started
        cost = self._cost(call)
        self.budget.record(call.total_tokens)
        metrics.meta_agent_tokens_total.labels(kind="input").inc(call.input_tokens)
        metrics.meta_agent_tokens_total.labels(kind="output").inc(call.output_tokens)
        metrics.meta_agent_cost_usd_total.inc(cost)
        metrics.meta_agent_reviews_total.labels(
            mode=self.mode.value,
            outcome="approve" if call.decision.approve else "veto",
        ).inc()

        review = self._record(
            called=True,
            approved=call.decision.approve,
            confidence_delta=call.decision.confidence_delta,
            rationale=call.decision.rationale,
            risk_flags=list(call.decision.risk_flags),
            model=call.model or self.model,
            latency_seconds=latency,
            input_tokens=call.input_tokens,
            output_tokens=call.output_tokens,
            estimated_cost_usd=cost,
            digest=digest,
            specialist_signals=list(packet.specialist_signals),
        )
        self.cache.put(digest, review)
        return review

    def apply(
        self, result: PipelineResult, review: MetaAgentReview
    ) -> tuple[PipelineResult, MetaAgentReview]:
        """Apply the review's bounded effect. Advisory mode changes nothing."""
        if self.mode is not MetaAgentMode.VETO or result.proposal is None:
            return result, review

        if not review.usable:
            return self._suppress(result, review, UNAVAILABLE_REASON)
        if review.approved is False:
            return self._suppress(result, review, VETO_REASON)

        delta = review.confidence_delta or 0.0
        adjusted = max(0.0, min(1.0, result.proposal.confidence + delta))
        proposal = result.proposal.model_copy(update={"confidence": adjusted})
        updated = review.model_copy(update={"applied_confidence": adjusted})
        # Only confidence changes: side, asset, notional, risk result and the
        # already-approved paper order are untouched.
        return result.model_copy(update={"proposal": proposal}), updated

    def _suppress(
        self, result: PipelineResult, review: MetaAgentReview, reason: str
    ) -> tuple[PipelineResult, MetaAgentReview]:
        metrics.meta_agent_suppressed_orders_total.labels(reason=reason).inc()
        restricted = result.model_copy(
            update={
                "paper_order": None,
                "rejection_reasons": [*result.rejection_reasons, reason],
            }
        )
        updated = review.model_copy(
            update={"suppressed_order": True, "suppression_reason": reason}
        )
        return restricted, updated

    async def _call(self, packet: EvidencePacket) -> MetaAgentCall:
        client = self.client
        if client is None:  # pragma: no cover - guarded by review()
            raise RuntimeError("meta-agent client is not configured")
        if isinstance(client, UsageReportingMetaAgentClient):
            return await client.review(packet)
        decision = await client(packet)
        return MetaAgentCall(decision=decision, model=self.model)

    def _cost(self, call: MetaAgentCall) -> float:
        return (
            call.input_tokens * self.input_cost_per_mtok
            + call.output_tokens * self.output_cost_per_mtok
        ) / 1_000_000
