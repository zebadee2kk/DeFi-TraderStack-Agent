from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from pydantic import BaseModel, Field

from traderstack.features import AssetFeatureVector
from traderstack.models import Side, TradeProposal
from traderstack.strategies import StrategySignal


class MetaAgentDecision(BaseModel):
    approve: bool
    confidence_delta: float = Field(ge=-0.15, le=0.15)
    rationale: str
    risk_flags: list[str] = Field(default_factory=list)


class EvidencePacket(BaseModel):
    asset: str
    feature_vector: AssetFeatureVector
    strategy_signal: StrategySignal
    requested_notional_usd: float = Field(gt=0)
    source_freshness_seconds: float = Field(default=0.0, ge=0)


MetaAgentClient = Callable[[EvidencePacket], Awaitable[MetaAgentDecision]]


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
        base_confidence = packet.strategy_signal.confidence
        confidence = max(0.0, min(1.0, base_confidence + decision.confidence_delta))
        side = packet.strategy_signal.side
        if side not in (Side.BUY, Side.SELL):
            return None
        # The nudge scales sizing proportionally but can never increase the
        # capital requested by the deterministic candidate.
        notional = packet.requested_notional_usd
        if base_confidence > 0:
            notional = min(notional, notional * (confidence / base_confidence))
        if notional <= 0:
            return None
        return TradeProposal(
            strategy_id=self.strategy_id,
            asset=packet.asset.upper(),
            side=side,
            confidence=confidence,
            requested_notional_usd=notional,
            thesis=decision.rationale,
            signal_ids=[packet.strategy_signal.strategy_id],
            source_freshness_seconds=packet.source_freshness_seconds,
        )
