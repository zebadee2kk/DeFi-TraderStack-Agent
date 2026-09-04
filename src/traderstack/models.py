from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class Side(StrEnum):
    BUY = "buy"
    SELL = "sell"


class RiskDecision(StrEnum):
    ALLOW = "allow"
    REDUCE = "reduce"
    REJECT = "reject"


class TradeProposal(BaseModel):
    decision_id: UUID = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    strategy_id: str
    asset: str
    side: Side
    confidence: float = Field(ge=0, le=1)
    requested_notional_usd: float = Field(gt=0)
    thesis: str
    signal_ids: list[str] = Field(default_factory=list)
    source_freshness_seconds: float = Field(ge=0)
    signal_version: str | None = None


class PortfolioSnapshot(BaseModel):
    nav_usd: float = Field(gt=0)
    cash_usd: float = Field(ge=0)
    daily_pnl_usd: float
    peak_nav_usd: float = Field(gt=0)
    asset_exposure_usd: dict[str, float] = Field(default_factory=dict)


class RiskResult(BaseModel):
    decision_id: UUID
    decision: RiskDecision
    approved_notional_usd: float = Field(ge=0)
    reasons: list[str] = Field(default_factory=list)
    policy_version: str
