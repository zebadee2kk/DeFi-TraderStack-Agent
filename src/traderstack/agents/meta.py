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
