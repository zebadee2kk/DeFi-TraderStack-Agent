"""Zero-trade diagnosis: the per-run opportunity funnel (#131).

A 24-hour paper run can end with zero fills for very different reasons -- no
valid ticks, a reference provider down, stale candles, a strategy ensemble
that never agrees, a pre-trade backtest that never clears its bar, a risk
rejection, a meta-agent veto, a planner refusal, or fills simply not being
enabled. Without the breakdown it is easy to loosen the wrong control, or to
mistake a *safety* rejection for a *strategy* failure.

This module reduces every ``RuntimeResult`` a cycle produced to one
``FunnelObservation`` -- the furthest stage the cycle reached and, when it did
not fill, the single nearest gate that stopped it and the bounded reason
strings that gate emitted -- and accumulates them into an
``OpportunityFunnelReport`` with per-symbol and per-strategy counts, bounded
reason maps, first/last timestamps, provider freshness, candle age and whether
fills were even enabled.

Stages, in pipeline order (``docs/EXECUTION-ARCHITECTURE.md``, "Cycle order of
operations"):

    cycles -> valid_market_data -> signal_candidate -> pretrade_eligible
           -> risk_allowed -> meta_agent_retained -> planner_accepted
           -> filled (-> exit_filled)

The three headline categories an operator needs to tell apart:

* ``no_opportunity``      -- nothing tradeable was ever formed (bad/missing
  data, no strategy consensus, symbol outside the promote universe);
* ``opportunity_rejected`` -- a candidate existed and a control withheld it
  (intelligence gate, pre-trade backtest, risk engine, meta-agent, planner);
* ``fill_unavailable``    -- risk approved an order and nothing could book it
  (fills disabled, kill switch, reconciliation block, diagnostic mode, venue
  uncertainty, still pending at the venue).

This is evidence, not control flow. Observing a cycle never changes it, and
nothing here is read by the pipeline, the risk engine or the meta-agent.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, PrivateAttr

from traderstack._fs import write_atomic
from traderstack.agents.review import UNAVAILABLE_REASON, VETO_REASON
from traderstack.execution.ledger import ExecutionLedger, OrderLifecycleState
from traderstack.execution.paper_fill import PaperFillStatus
from traderstack.execution.submitter import SubmissionStatus
from traderstack.models import RiskDecision
from traderstack.runtime import RuntimeResult

#: Stamped on ``RuntimeResult.execution_status`` when diagnostic mode withheld a
#: paper fill / venue submission that every other control had already allowed.
DIAGNOSTIC_WITHHELD_STATUS = "diagnostic_withheld"

#: Cap on distinct keys per reason map so a run can never grow the report
#: unboundedly (free-text venue reasons are never used as keys, but a bug that
#: produced one per cycle still must not).
MAX_REASON_KEYS = 64
OVERFLOW_KEY = "(other)"
#: Longest reason text kept as an example per gate.
MAX_REASON_TEXT = 200
#: Pending venue decisions tracked for a later ledger join.
MAX_PENDING_DECISIONS = 4_096


class FunnelStage(StrEnum):
    """The furthest point a cycle reached, in pipeline order."""

    CYCLE = "cycle"
    VALID_MARKET_DATA = "valid_market_data"
    SIGNAL_CANDIDATE = "signal_candidate"
    PRETRADE_ELIGIBLE = "pretrade_eligible"
    RISK_ALLOWED = "risk_allowed"
    META_AGENT_RETAINED = "meta_agent_retained"
    PLANNER_ACCEPTED = "planner_accepted"
    FILLED = "filled"


STAGE_ORDER: tuple[FunnelStage, ...] = (
    FunnelStage.CYCLE,
    FunnelStage.VALID_MARKET_DATA,
    FunnelStage.SIGNAL_CANDIDATE,
    FunnelStage.PRETRADE_ELIGIBLE,
    FunnelStage.RISK_ALLOWED,
    FunnelStage.META_AGENT_RETAINED,
    FunnelStage.PLANNER_ACCEPTED,
    FunnelStage.FILLED,
)


class BlockingGate(StrEnum):
    """The nearest control that stopped a cycle short of a fill."""

    MARKET_DATA = "market_data"
    CANDLE_HISTORY = "candle_history"
    UNIVERSE = "universe"
    INTELLIGENCE = "intelligence"
    SIGNAL = "signal"
    PRETRADE = "pretrade"
    RISK = "risk"
    META_AGENT = "meta_agent"
    PLANNER = "planner"
    FILL = "fill"


class FunnelCategory(StrEnum):
    NO_OPPORTUNITY = "no_opportunity"
    OPPORTUNITY_REJECTED = "opportunity_rejected"
    FILL_UNAVAILABLE = "fill_unavailable"
    FILLED = "filled"


#: Which headline category each gate belongs to. Intelligence gating is a
#: policy control firing (a safety rejection), not "no signal": the strategy
#: was never consulted because the cycle was withheld first.
GATE_CATEGORY: dict[BlockingGate, FunnelCategory] = {
    BlockingGate.MARKET_DATA: FunnelCategory.NO_OPPORTUNITY,
    BlockingGate.CANDLE_HISTORY: FunnelCategory.NO_OPPORTUNITY,
    BlockingGate.UNIVERSE: FunnelCategory.NO_OPPORTUNITY,
    BlockingGate.SIGNAL: FunnelCategory.NO_OPPORTUNITY,
    BlockingGate.INTELLIGENCE: FunnelCategory.OPPORTUNITY_REJECTED,
    BlockingGate.PRETRADE: FunnelCategory.OPPORTUNITY_REJECTED,
    BlockingGate.RISK: FunnelCategory.OPPORTUNITY_REJECTED,
    BlockingGate.META_AGENT: FunnelCategory.OPPORTUNITY_REJECTED,
    BlockingGate.PLANNER: FunnelCategory.OPPORTUNITY_REJECTED,
    BlockingGate.FILL: FunnelCategory.FILL_UNAVAILABLE,
}

#: Every literal reason string each pre-proposal gate can emit (pipeline.py,
#: pretrade.py). Unknown reasons fall through to the gate whose check produced
#: them rather than being dropped.
CANDLE_HISTORY_REASONS = frozenset(
    {
        "missing_candle_history",
        "insufficient_candle_history",
        "stale_candle_history",
        "candle_interval_mismatch",
    }
)
UNIVERSE_REASONS = frozenset({"promote_universe_excluded"})
INTELLIGENCE_REASONS = frozenset(
    {
        "no_external_intelligence",
        "adverse_news_event",
        "intelligence_provider_unavailable",
    }
)
SIGNAL_REASONS = frozenset({"no_strategy_consensus", "strategy_does_not_confirm_side"})
META_AGENT_REASONS = frozenset({VETO_REASON, UNAVAILABLE_REASON})
# --- on-chain regime gate (#139) ---
# Fires AFTER the ensemble produced a side (BUY), so it is a policy withhold
# at SIGNAL_CANDIDATE, not a missing-intelligence stop at VALID_MARKET_DATA.
ONCHAIN_REGIME_REASONS = frozenset({"onchain_regime_blocked", "onchain_regime_unavailable"})

PLANNER_STATUSES = frozenset(
    {SubmissionStatus.PLAN_REJECTED.value, PaperFillStatus.PLAN_REJECTED.value}
)
FILLED_STATUSES = frozenset({PaperFillStatus.FILLED.value})
#: Accepted by the planner and handed onward, but not a fill yet: the venue
#: (or a later reconciliation pass) owns what happens next. Shadow recording
#: is the same shape -- the plan was accepted, and by design nothing fills.
PENDING_STATUSES = frozenset(
    {
        SubmissionStatus.SUBMITTED.value,
        SubmissionStatus.ADOPTED.value,
        "shadow_recorded",
    }
)
#: Reason keys used in the fill gate when no execution status was stamped.
NOT_ATTEMPTED_REASON = "execution_not_attempted"
PENDING_REASON = "venue_fill_pending"


class FunnelObservation(BaseModel):
    """One cycle reduced to where it stopped and why."""

    observed_at: datetime
    symbol: str
    strategy_id: str | None = None
    decision_id: str | None = None
    stage: FunnelStage
    gate: BlockingGate | None = None
    category: FunnelCategory
    reasons: list[str] = Field(default_factory=list)
    reason_text: str | None = None
    is_exit: bool = False
    tick_age_seconds: float | None = None
    candle_age_seconds: float | None = None
    candles_loaded: int = 0

    def explain(self) -> str:
        """One line an operator can read: the nearest blocking gate and why."""

        head = f"{self.symbol}: reached {self.stage.value}"
        if self.stage is FunnelStage.FILLED:
            return f"{head}; filled ({'exit' if self.is_exit else 'entry'})"
        gate = self.gate.value if self.gate is not None else "unknown"
        reasons = ", ".join(self.reasons) if self.reasons else "(no reason recorded)"
        text = f" -- {self.reason_text}" if self.reason_text else ""
        return f"{head}; blocked at {gate} [{self.category.value}]: {reasons}{text}"


class FunnelCounts(BaseModel):
    """Stage counts plus a bounded map of where the stopped cycles stopped."""

    stages: dict[str, int] = Field(default_factory=dict)
    blocked_by_gate: dict[str, int] = Field(default_factory=dict)
    categories: dict[str, int] = Field(default_factory=dict)
    exits_filled: int = 0

    def add(self, observation: FunnelObservation) -> None:
        reached = STAGE_ORDER.index(observation.stage)
        for stage in STAGE_ORDER[: reached + 1]:
            self.stages[stage.value] = self.stages.get(stage.value, 0) + 1
        if observation.gate is not None:
            key = observation.gate.value
            self.blocked_by_gate[key] = self.blocked_by_gate.get(key, 0) + 1
        key = observation.category.value
        self.categories[key] = self.categories.get(key, 0) + 1
        if observation.stage is FunnelStage.FILLED and observation.is_exit:
            self.exits_filled += 1

    def stage_count(self, stage: FunnelStage) -> int:
        return self.stages.get(stage.value, 0)


class FreshnessStats(BaseModel):
    """Bounded summary of one freshness series (seconds)."""

    samples: int = 0
    last: float | None = None
    max: float | None = None
    mean: float | None = None
    _total: float = PrivateAttr(default=0.0)

    def add(self, value: float | None) -> None:
        if value is None:
            return
        self.samples += 1
        self.last = value
        self.max = value if self.max is None else max(self.max, value)
        self._total += value
        self.mean = self._total / self.samples


class FunnelDiagnosis(BaseModel):
    """What a zero-fill run should tell the operator first."""

    fills: int = 0
    cycles: int = 0
    dominant_gate: str | None = None
    dominant_gate_count: int = 0
    dominant_reason: str | None = None
    dominant_reason_count: int = 0
    category: str | None = None
    verdict: str = ""


class OpportunityFunnelReport(BaseModel):
    """Machine-readable funnel, persisted verbatim into ``report.json``."""

    schema_version: str = "1"
    started_at: datetime | None = None
    first_observed_at: datetime | None = None
    last_observed_at: datetime | None = None
    paper_fills_enabled: bool | None = None
    submission_enabled: bool | None = None
    diagnostic_mode: bool = False
    totals: FunnelCounts = Field(default_factory=FunnelCounts)
    by_symbol: dict[str, FunnelCounts] = Field(default_factory=dict)
    #: Keyed by ``TradeProposal.strategy_id``; only cycles that formed a
    #: proposal carry one, so these counts start at ``pretrade_eligible``.
    by_strategy: dict[str, FunnelCounts] = Field(default_factory=dict)
    reasons_by_gate: dict[str, dict[str, int]] = Field(default_factory=dict)
    reason_examples: dict[str, str] = Field(default_factory=dict)
    execution_statuses: dict[str, int] = Field(default_factory=dict)
    tick_age_seconds: FreshnessStats = Field(default_factory=FreshnessStats)
    candle_age_seconds: FreshnessStats = Field(default_factory=FreshnessStats)
    candles_loaded_last: int | None = None
    candles_loaded_min: int | None = None
    pending_venue_decisions: int = 0
    diagnosis: FunnelDiagnosis = Field(default_factory=FunnelDiagnosis)

    def render(self) -> str:
        lines = ["Opportunity funnel", "-" * 60]
        flags = (
            f"  paper_fills_enabled={_flag(self.paper_fills_enabled)}  "
            f"submission_enabled={_flag(self.submission_enabled)}  "
            f"diagnostic_mode={'yes' if self.diagnostic_mode else 'no'}"
        )
        lines.append(flags)
        lines.append(f"  first={self.first_observed_at}  last={self.last_observed_at}")
        for stage in STAGE_ORDER:
            lines.append(f"  {stage.value:<34}{self.totals.stage_count(stage):>6}")
        lines.append(f"  {'exits_filled':<34}{self.totals.exits_filled:>6}")
        lines.append("\nBlocked by gate (nearest control that stopped the cycle)")
        lines.append("-" * 60)
        if self.totals.blocked_by_gate:
            for gate, count in sorted(
                self.totals.blocked_by_gate.items(), key=lambda item: (-item[1], item[0])
            ):
                category = GATE_CATEGORY[BlockingGate(gate)].value
                lines.append(f"  {gate:<22}{category:<24}{count:>6}")
                for reason, reason_count in sorted(
                    self.reasons_by_gate.get(gate, {}).items(),
                    key=lambda item: (-item[1], item[0]),
                ):
                    lines.append(f"    {reason:<40}{reason_count:>6}")
        else:
            lines.append("  (none)")
        lines.append("\nOutcome categories")
        lines.append("-" * 60)
        for category in FunnelCategory:
            lines.append(
                f"  {category.value:<34}{self.totals.categories.get(category.value, 0):>6}"
            )
        lines.append("\nFreshness")
        lines.append("-" * 60)
        lines.append(f"  tick age (s)      {_stats(self.tick_age_seconds)}")
        lines.append(f"  candle age (s)    {_stats(self.candle_age_seconds)}")
        lines.append(
            f"  candles loaded    last={self.candles_loaded_last}  min={self.candles_loaded_min}"
        )
        if self.by_symbol:
            lines.append("\nPer symbol (valid / signal / eligible / risk / meta / plan / fill)")
            lines.append("-" * 60)
            for symbol, counts in sorted(self.by_symbol.items()):
                lines.append(f"  {symbol:<12}{_stage_row(counts)}")
        if self.by_strategy:
            lines.append("\nPer strategy (eligible / risk / meta / plan / fill)")
            lines.append("-" * 60)
            for strategy, counts in sorted(self.by_strategy.items()):
                row = " / ".join(
                    str(counts.stage_count(stage))
                    for stage in STAGE_ORDER[STAGE_ORDER.index(FunnelStage.PRETRADE_ELIGIBLE) :]
                )
                lines.append(f"  {strategy:<30}{row}")
        lines.append("\nDiagnosis")
        lines.append("-" * 60)
        lines.append(f"  {self.diagnosis.verdict}")
        return "\n".join(lines)


def _flag(value: bool | None) -> str:
    if value is None:
        return "unknown"
    return "yes" if value else "no"


def _stats(stats: FreshnessStats) -> str:
    if stats.samples == 0:
        return "n/a"
    return f"last={stats.last:.1f}  max={stats.max:.1f}  mean={stats.mean:.1f}  n={stats.samples}"


def _stage_row(counts: FunnelCounts) -> str:
    return " / ".join(str(counts.stage_count(stage)) for stage in STAGE_ORDER[1:])


# --- classification -----------------------------------------------------------


def _first_matching(reasons: Iterable[str], known: frozenset[str]) -> list[str]:
    return [reason for reason in reasons if reason in known]


def classify(
    result: RuntimeResult,
    *,
    now: datetime | None = None,
    filled: bool | None = None,
) -> FunnelObservation:
    """Reduce one cycle to the furthest stage reached and the nearest gate.

    ``filled`` lets a caller with ledger access assert that a venue-submitted
    decision has since filled; ``None`` means "trust the execution status".
    """

    pipeline = result.pipeline
    tick = result.tick
    symbol = tick.symbol
    observed_at = tick.observed_at
    tick_age = None
    if now is not None:
        tick_age = max(0.0, (now - observed_at).total_seconds())
    candle_age = None
    if result.candle_last_opened_at is not None:
        candle_age = max(0.0, (observed_at - result.candle_last_opened_at).total_seconds())
    base: dict[str, Any] = {
        "observed_at": observed_at,
        "symbol": symbol,
        "tick_age_seconds": tick_age,
        "candle_age_seconds": candle_age,
        "candles_loaded": result.candles_loaded,
    }

    def stopped(
        stage: FunnelStage,
        gate: BlockingGate,
        reasons: list[str],
        *,
        text: str | None = None,
        strategy_id: str | None = None,
        decision_id: str | None = None,
        is_exit: bool = False,
    ) -> FunnelObservation:
        return FunnelObservation(
            **base,
            stage=stage,
            gate=gate,
            category=GATE_CATEGORY[gate],
            reasons=reasons,
            reason_text=_bounded_text(text),
            strategy_id=strategy_id,
            decision_id=decision_id,
            is_exit=is_exit,
        )

    rejection_reasons = list(pipeline.rejection_reasons)

    # 1. Market-data validation: the cycle never produced a feature vector.
    if not pipeline.accepted_market_data:
        reasons = rejection_reasons or ["market_data_rejected"]
        return stopped(FunnelStage.CYCLE, BlockingGate.MARKET_DATA, reasons)

    proposal = pipeline.proposal
    check = pipeline.pretrade_check

    # 2. Gates that fire before the strategy ensemble is consulted.
    if proposal is None:
        candle = _first_matching(rejection_reasons, CANDLE_HISTORY_REASONS)
        if check is not None:
            candle = candle or _first_matching(check.reasons, CANDLE_HISTORY_REASONS)
        if candle:
            return stopped(FunnelStage.VALID_MARKET_DATA, BlockingGate.CANDLE_HISTORY, candle)
        universe = _first_matching(rejection_reasons, UNIVERSE_REASONS)
        if universe:
            return stopped(FunnelStage.VALID_MARKET_DATA, BlockingGate.UNIVERSE, universe)
        intelligence = _first_matching(rejection_reasons, INTELLIGENCE_REASONS)
        if intelligence:
            return stopped(FunnelStage.VALID_MARKET_DATA, BlockingGate.INTELLIGENCE, intelligence)
        # 3. The ensemble ran (pre-trade gate) and produced no side ...
        check_reasons = list(check.reasons) if check is not None else []
        signal = _first_matching(check_reasons, SIGNAL_REASONS) or _first_matching(
            rejection_reasons, SIGNAL_REASONS
        )
        if signal or (check is not None and check.confirmed_side is None):
            return stopped(
                FunnelStage.VALID_MARKET_DATA,
                BlockingGate.SIGNAL,
                signal or check_reasons or rejection_reasons or ["no_confirmed_side"],
            )
        # --- on-chain regime gate (#139) --- a side existed; policy withheld it.
        regime = _first_matching(rejection_reasons, ONCHAIN_REGIME_REASONS)
        if regime:
            return stopped(FunnelStage.SIGNAL_CANDIDATE, BlockingGate.INTELLIGENCE, regime)
        # 4. ... or produced a side the backtest / walk-forward bar rejected.
        reasons = check_reasons or rejection_reasons or ["pretrade_rejected"]
        return stopped(FunnelStage.SIGNAL_CANDIDATE, BlockingGate.PRETRADE, reasons)

    strategy_id = proposal.strategy_id
    decision_id = str(proposal.decision_id)
    is_exit = pipeline.exit_reason is not None

    # 5. Risk engine (Zone C). A proposal exists, so the signal and pre-trade
    #    stages were both reached.
    risk = pipeline.risk_result
    if risk is None:
        return stopped(
            FunnelStage.PRETRADE_ELIGIBLE,
            BlockingGate.RISK,
            ["risk_result_missing"],
            strategy_id=strategy_id,
            decision_id=decision_id,
            is_exit=is_exit,
        )
    if risk.decision is RiskDecision.REJECT or risk.approved_notional_usd <= 0:
        reasons = list(risk.reasons) or [risk.decision.value]
        return stopped(
            FunnelStage.PRETRADE_ELIGIBLE,
            BlockingGate.RISK,
            reasons,
            strategy_id=strategy_id,
            decision_id=decision_id,
            is_exit=is_exit,
        )

    # 6. Meta-agent: it can only null the paper order it was handed.
    review = result.meta_review
    suppressed = review is not None and review.suppressed_order
    meta_reasons = _first_matching(rejection_reasons, META_AGENT_REASONS)
    if suppressed or meta_reasons or pipeline.paper_order is None:
        reasons = meta_reasons
        if not reasons and review is not None and review.suppression_reason:
            reasons = [review.suppression_reason]
        if not reasons:
            reasons = rejection_reasons or ["paper_order_withheld"]
        return stopped(
            FunnelStage.RISK_ALLOWED,
            BlockingGate.META_AGENT,
            reasons,
            text=review.rationale if review is not None else None,
            strategy_id=strategy_id,
            decision_id=decision_id,
            is_exit=is_exit,
        )

    # 7. Planner / execution boundary.
    status = result.execution_status
    reason_text = result.execution_reason
    if filled or (filled is None and status in FILLED_STATUSES):
        return FunnelObservation(
            **base,
            stage=FunnelStage.FILLED,
            category=FunnelCategory.FILLED,
            reasons=[status] if status else [],
            strategy_id=strategy_id,
            decision_id=decision_id,
            is_exit=is_exit,
        )
    if status in PLANNER_STATUSES:
        return stopped(
            FunnelStage.META_AGENT_RETAINED,
            BlockingGate.PLANNER,
            [status],
            text=reason_text,
            strategy_id=strategy_id,
            decision_id=decision_id,
            is_exit=is_exit,
        )
    if status in PENDING_STATUSES:
        return stopped(
            FunnelStage.PLANNER_ACCEPTED,
            BlockingGate.FILL,
            [PENDING_REASON, status],
            text=reason_text,
            strategy_id=strategy_id,
            decision_id=decision_id,
            is_exit=is_exit,
        )
    if status is None:
        return stopped(
            FunnelStage.META_AGENT_RETAINED,
            BlockingGate.FILL,
            [NOT_ATTEMPTED_REASON],
            text="no paper fill simulator and no venue submission on this cycle",
            strategy_id=strategy_id,
            decision_id=decision_id,
            is_exit=is_exit,
        )
    # Withheld, rejected, uncertain, duplicate, diagnostic: risk approved an
    # order and nothing booked it.
    return stopped(
        FunnelStage.META_AGENT_RETAINED,
        BlockingGate.FILL,
        [status],
        text=reason_text,
        strategy_id=strategy_id,
        decision_id=decision_id,
        is_exit=is_exit,
    )


def _bounded_text(text: str | None) -> str | None:
    if text is None:
        return None
    text = " ".join(text.split())
    if len(text) > MAX_REASON_TEXT:
        return text[: MAX_REASON_TEXT - 1] + "…"
    return text or None


# --- accumulation ---------------------------------------------------------------


class OpportunityFunnel:
    """Accumulates observations into an ``OpportunityFunnelReport``.

    Plain in-memory state; ``snapshot()`` is cheap enough to call every cycle
    and ``report()`` finalises the diagnosis text.
    """

    def __init__(
        self,
        *,
        paper_fills_enabled: bool | None = None,
        submission_enabled: bool | None = None,
        diagnostic_mode: bool = False,
        started_at: datetime | None = None,
    ) -> None:
        self._report = OpportunityFunnelReport(
            started_at=started_at or datetime.now(UTC),
            paper_fills_enabled=paper_fills_enabled,
            submission_enabled=submission_enabled,
            diagnostic_mode=diagnostic_mode,
        )
        self._reason_counters: dict[str, Counter[str]] = {}
        self._status_counter: Counter[str] = Counter()
        # decision_id -> observation, for venue-pending decisions a later
        # ledger pass can promote to filled.
        self._pending: dict[str, FunnelObservation] = {}
        #: Audit lines ``funnel_from_audit`` could not parse (torn tail).
        self.skipped_lines = 0

    @property
    def flags(self) -> tuple[bool | None, bool | None, bool]:
        report = self._report
        return (report.paper_fills_enabled, report.submission_enabled, report.diagnostic_mode)

    def set_flags(
        self,
        *,
        paper_fills_enabled: bool | None = None,
        submission_enabled: bool | None = None,
        diagnostic_mode: bool | None = None,
    ) -> None:
        if paper_fills_enabled is not None:
            self._report.paper_fills_enabled = paper_fills_enabled
        if submission_enabled is not None:
            self._report.submission_enabled = submission_enabled
        if diagnostic_mode is not None:
            self._report.diagnostic_mode = diagnostic_mode

    def observe(
        self,
        result: RuntimeResult,
        *,
        now: datetime | None = None,
        ledger: ExecutionLedger | None = None,
    ) -> FunnelObservation:
        filled: bool | None = None
        proposal = result.pipeline.proposal
        if ledger is not None and proposal is not None and result.pipeline.paper_order is not None:
            orders = ledger.orders_for_decision(str(proposal.decision_id))
            if any(order.state is OrderLifecycleState.FILLED for order in orders):
                filled = True
        observation = classify(result, now=now, filled=filled)
        self.add(observation)
        if result.execution_status is not None:
            self._status_counter[result.execution_status] += 1
            self._report.execution_statuses = dict(self._status_counter)
        return observation

    def add(self, observation: FunnelObservation) -> None:
        report = self._report
        report.totals.add(observation)
        report.by_symbol.setdefault(observation.symbol, FunnelCounts()).add(observation)
        if observation.strategy_id is not None:
            report.by_strategy.setdefault(observation.strategy_id, FunnelCounts()).add(observation)
        if observation.gate is not None:
            counter = self._reason_counters.setdefault(observation.gate.value, Counter())
            for reason in observation.reasons or ["(unspecified)"]:
                key = reason if reason in counter or len(counter) < MAX_REASON_KEYS else None
                counter[key if key is not None else OVERFLOW_KEY] += 1
            report.reasons_by_gate[observation.gate.value] = dict(counter)
            if observation.reason_text and observation.gate.value not in report.reason_examples:
                report.reason_examples[observation.gate.value] = observation.reason_text
        if report.first_observed_at is None or observation.observed_at < report.first_observed_at:
            report.first_observed_at = observation.observed_at
        if report.last_observed_at is None or observation.observed_at >= report.last_observed_at:
            report.last_observed_at = observation.observed_at
        report.tick_age_seconds.add(observation.tick_age_seconds)
        report.candle_age_seconds.add(observation.candle_age_seconds)
        report.candles_loaded_last = observation.candles_loaded
        report.candles_loaded_min = (
            observation.candles_loaded
            if report.candles_loaded_min is None
            else min(report.candles_loaded_min, observation.candles_loaded)
        )
        if (
            observation.decision_id is not None
            and observation.gate is BlockingGate.FILL
            and PENDING_REASON in observation.reasons
            and len(self._pending) < MAX_PENDING_DECISIONS
        ):
            self._pending[observation.decision_id] = observation
        report.pending_venue_decisions = len(self._pending)

    def apply_ledger(self, ledger: ExecutionLedger) -> int:
        """Promote venue-pending decisions the ledger has since seen fill.

        Counts are corrected in place (the pending observation is un-counted
        from the fill gate and re-counted as filled). Returns how many moved.
        """

        moved = 0
        for decision_id, pending in list(self._pending.items()):
            orders = ledger.orders_for_decision(decision_id)
            if not any(order.state is OrderLifecycleState.FILLED for order in orders):
                continue
            self._retract(pending)
            filled = pending.model_copy(
                update={
                    "stage": FunnelStage.FILLED,
                    "gate": None,
                    "category": FunnelCategory.FILLED,
                    "reasons": ["ledger_filled"],
                    "reason_text": None,
                }
            )
            del self._pending[decision_id]
            self.add(filled)
            moved += 1
        self._report.pending_venue_decisions = len(self._pending)
        return moved

    def _retract(self, observation: FunnelObservation) -> None:
        report = self._report
        for counts in (
            report.totals,
            report.by_symbol.get(observation.symbol),
            report.by_strategy.get(observation.strategy_id or ""),
        ):
            if counts is None:
                continue
            reached = STAGE_ORDER.index(observation.stage)
            for stage in STAGE_ORDER[: reached + 1]:
                _decrement(counts.stages, stage.value)
            if observation.gate is not None:
                _decrement(counts.blocked_by_gate, observation.gate.value)
            _decrement(counts.categories, observation.category.value)
        if observation.gate is not None:
            counter = self._reason_counters.get(observation.gate.value)
            if counter is not None:
                for reason in observation.reasons:
                    _decrement(counter, reason)
                if counter:
                    report.reasons_by_gate[observation.gate.value] = dict(counter)
                else:
                    report.reasons_by_gate.pop(observation.gate.value, None)

    def snapshot(self) -> OpportunityFunnelReport:
        report = self._report.model_copy(deep=True)
        report.diagnosis = diagnose(report)
        return report

    def report(self) -> OpportunityFunnelReport:
        return self.snapshot()

    def write(self, path: Path) -> None:
        """Persist a snapshot atomically (safe to call every cycle)."""

        payload = json.dumps(self.snapshot().model_dump(mode="json"), indent=2, default=str)
        write_atomic(Path(path), payload)


def _decrement(counts: dict[str, int] | Counter[str], key: str) -> None:
    """Un-count one observation; a key that reaches zero is dropped, not kept at 0."""

    remaining = counts.get(key, 0) - 1
    if remaining > 0:
        counts[key] = remaining
    else:
        counts.pop(key, None)


def diagnose(report: OpportunityFunnelReport) -> FunnelDiagnosis:
    """Name the dominant blocking stage and its top reason, with a verdict."""

    totals = report.totals
    cycles = totals.stage_count(FunnelStage.CYCLE)
    fills = totals.stage_count(FunnelStage.FILLED)
    diagnosis = FunnelDiagnosis(fills=fills, cycles=cycles)
    if cycles == 0:
        diagnosis.verdict = "no cycles observed"
        return diagnosis
    if not totals.blocked_by_gate:
        diagnosis.category = FunnelCategory.FILLED.value
        diagnosis.verdict = f"{fills} fill(s) in {cycles} cycle(s); no cycle was blocked"
        return diagnosis
    gate, gate_count = max(totals.blocked_by_gate.items(), key=lambda item: (item[1], item[0]))
    diagnosis.dominant_gate = gate
    diagnosis.dominant_gate_count = gate_count
    reasons = report.reasons_by_gate.get(gate, {})
    if reasons:
        reason, reason_count = max(reasons.items(), key=lambda item: (item[1], item[0]))
        diagnosis.dominant_reason = reason
        diagnosis.dominant_reason_count = reason_count
    category = GATE_CATEGORY[BlockingGate(gate)]
    diagnosis.category = category.value
    reason_part = (
        f" ({diagnosis.dominant_reason} x{diagnosis.dominant_reason_count})"
        if diagnosis.dominant_reason
        else ""
    )
    hint = {
        FunnelCategory.NO_OPPORTUNITY: (
            "no tradeable opportunity was formed; this is not a safety rejection"
        ),
        FunnelCategory.OPPORTUNITY_REJECTED: (
            "a candidate existed and a control withheld it; read the gate's reasons "
            "before touching any threshold"
        ),
        FunnelCategory.FILL_UNAVAILABLE: (
            "risk approved an order and nothing could book it; check fills/submission "
            "flags, the kill switch, reconciliation, and diagnostic mode"
        ),
        FunnelCategory.FILLED: "",
    }[category]
    if report.diagnostic_mode and category is FunnelCategory.FILL_UNAVAILABLE:
        hint = "diagnostic mode withheld every approved order by design"
    diagnosis.verdict = (
        f"{fills} fill(s) in {cycles} cycle(s): dominant blocking gate is {gate} "
        f"x{gate_count}{reason_part} -> {category.value}: {hint}"
    )
    return diagnosis


# --- offline reconstruction ---------------------------------------------------


def funnel_from_audit(
    audit_path: Path,
    *,
    ledger: ExecutionLedger | None = None,
    diagnostic_mode: bool = False,
) -> OpportunityFunnel:
    """Rebuild the funnel from a run's ``runtime.jsonl`` (and optional ledger).

    Tick freshness relative to wall clock is not recorded in the audit trail,
    so ``tick_age_seconds`` stays empty here; ``stale_primary_tick`` counts
    still show under the market_data gate.
    """

    funnel = OpportunityFunnel(diagnostic_mode=diagnostic_mode)
    statuses: Counter[str] = Counter()
    skipped = 0
    for line in Path(audit_path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            result = RuntimeResult.model_validate_json(line)
        except Exception:  # noqa: BLE001 - a torn tail must not lose the run.
            skipped += 1
            continue
        funnel.observe(result, ledger=ledger)
        status = result.execution_status
        if status is not None:
            statuses[status] += 1
    if statuses:
        fills_seen = any(status in FILLED_STATUSES for status in statuses)
        withheld = any(status == PaperFillStatus.WITHHELD.value for status in statuses)
        funnel.set_flags(paper_fills_enabled=fills_seen or withheld or None)
        funnel.set_flags(
            submission_enabled=(any(status in PENDING_STATUSES for status in statuses) or None)
        )
    if ledger is not None:
        funnel.apply_ledger(ledger)
    funnel.skipped_lines = skipped
    return funnel
