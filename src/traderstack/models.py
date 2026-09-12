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


class HeldPosition(BaseModel):
    """One open position as the exit rules and snapshot consumers see it.

    Additive on ``PortfolioSnapshot`` so older constructors stay valid.
    """

    quantity: float = Field(ge=0)
    average_cost_usd: float = Field(ge=0)
    exposure_usd: float = Field(ge=0)
    # --- position management (#58) ---
    opened_at: datetime | None = None
    high_water_price_usd: float = Field(default=0.0, ge=0)
    entry_strategy_id: str | None = None


class PortfolioSnapshot(BaseModel):
    nav_usd: float = Field(gt=0)
    cash_usd: float = Field(ge=0)
    daily_pnl_usd: float
    peak_nav_usd: float = Field(gt=0)
    asset_exposure_usd: dict[str, float] = Field(default_factory=dict)
    # --- risk plane (Epic 7) ---
    # When this view of the book was taken. The risk engine authorises no new
    # risk against a snapshot older than MAX_PORTFOLIO_STATE_AGE_SECONDS.
    observed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    # --- position management (#58) ---
    # Entry price / open time / high-water for stop, TP and time-stop exits.
    # Empty on snapshots constructed before this field existed.
    held_positions: dict[str, HeldPosition] = Field(default_factory=dict)


class RiskResult(BaseModel):
    decision_id: UUID
    decision: RiskDecision
    approved_notional_usd: float = Field(ge=0)
    reasons: list[str] = Field(default_factory=list)
    policy_version: str
