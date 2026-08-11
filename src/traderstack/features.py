from datetime import UTC, datetime

from pydantic import BaseModel, Field


class MarketFeatures(BaseModel):
    trend_4h: float = Field(ge=-1, le=1)
    trend_1d: float = Field(ge=-1, le=1)
    volatility_z: float
    relative_volume: float = Field(ge=0)
    spread_bps: float = Field(ge=0)


class OnChainFeatures(BaseModel):
    exchange_netflow_z: float | None = None
    large_wallet_accumulation: float | None = Field(default=None, ge=-1, le=1)


class NarrativeFeatures(BaseModel):
    mention_velocity_z: float | None = None
    sentiment: float | None = Field(default=None, ge=-1, le=1)


class NewsFeatures(BaseModel):
    event_score: float = Field(default=0, ge=0, le=1)
    adverse_event: bool = False


class AssetFeatureVector(BaseModel):
    asset: str
    observed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    market: MarketFeatures
    onchain: OnChainFeatures = Field(default_factory=OnChainFeatures)
    narrative: NarrativeFeatures = Field(default_factory=NarrativeFeatures)
    news: NewsFeatures = Field(default_factory=NewsFeatures)
    source_ids: list[str] = Field(default_factory=list)
    schema_version: str = "1.0"
