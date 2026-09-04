from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from traderstack.features import AssetFeatureVector
from traderstack.models import RiskDecision, Side, TradeProposal
from traderstack.strategies import Regime, StrategySignal


class MetaAgentDecision(BaseModel):
    # --- meta-agent (Epic 6) ---
    # Unexpected keys are a schema violation, not something to quietly drop: an
    # unrecognised field means the model returned something we do not understand,
    # which must fail closed rather than be partially honoured.
    model_config = ConfigDict(extra="forbid")
    # --- end meta-agent (Epic 6) ---

    approve: bool
    confidence_delta: float = Field(ge=-0.15, le=0.15)
    # Model-authored free text. It cannot change a decision, but it *is*
    # persisted verbatim into TradeProposal.thesis, the hash-chained risk audit,
    # the runtime JSONL/Postgres/Redis event stream and log lines, so it is
    # bounded here at the trust boundary rather than at each sink.
    rationale: str = Field(max_length=2_000)
    risk_flags: list[str] = Field(default_factory=list, max_length=16)


# --- meta-agent (Epic 6) ---
class PreTradeSummary(BaseModel):
    """Bounded, numeric-only summary of the deterministic pre-trade gate."""

    passed: bool
    reasons: list[str] = Field(default_factory=list)
    confirmed_side: Side | None = None
    confidence: float = Field(default=0.0, ge=0, le=1)
    regime: Regime | None = None
    candles_evaluated: int = Field(default=0, ge=0)
    excess_return: float | None = None
    max_drawdown: float | None = None
    sharpe: float | None = None
    trades: int | None = None
    walkforward_mean_excess_return: float | None = None
    walkforward_worst_drawdown: float | None = None


class RiskSummary(BaseModel):
    """What the deterministic risk engine already decided.

    Present so the reviewer can see the constraint, never so it can argue with
    it: the risk result is final regardless of what the model returns.
    """

    decision: RiskDecision
    approved_notional_usd: float = Field(ge=0)
    reasons: list[str] = Field(default_factory=list)
    policy_version: str


# --- end meta-agent (Epic 6) ---


class EvidencePacket(BaseModel):
    asset: str
    feature_vector: AssetFeatureVector
    strategy_signal: StrategySignal
    requested_notional_usd: float = Field(gt=0)
    # --- meta-agent (Epic 6) ---
    # Everything below is structured, bounded data derived from deterministic
    # components. No free-form retrieved text ever enters the packet.
    specialist_signals: list[StrategySignal] = Field(default_factory=list)
    pretrade: PreTradeSummary | None = None
    risk: RiskSummary | None = None
    schema_version: str = "1.1"
    # --- end meta-agent (Epic 6) ---


MetaAgentClient = Callable[[EvidencePacket], Awaitable[MetaAgentDecision]]


# --- meta-agent (Epic 6) ---
class MetaAgentCall(BaseModel):
    """A completed model call: the decision plus what it cost."""

    decision: MetaAgentDecision
    model: str | None = None
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@runtime_checkable
class UsageReportingMetaAgentClient(Protocol):
    """A meta-agent client that also reports model identity and token usage."""

    async def review(self, packet: EvidencePacket) -> MetaAgentCall: ...


# --- end meta-agent (Epic 6) ---


@dataclass(frozen=True)
class ConstrainedMetaAgent:
    client: MetaAgentClient
    strategy_id: str = "claude_meta_v1"

    async def propose(self, packet: EvidencePacket) -> TradeProposal | None:
        if packet.strategy_signal.side is None:
            return None
        decision = await self.client(packet)
        if not decision.approve:
            return None
        confidence = max(
            0.0,
            min(1.0, packet.strategy_signal.confidence + decision.confidence_delta),
        )
        side = packet.strategy_signal.side
        if side not in (Side.BUY, Side.SELL):
            return None
        return TradeProposal(
            strategy_id=self.strategy_id,
            asset=packet.asset.upper(),
            side=side,
            confidence=confidence,
            requested_notional_usd=packet.requested_notional_usd,
            thesis=decision.rationale,
            signal_ids=[packet.strategy_signal.strategy_id],
            source_freshness_seconds=0.0,
        )
