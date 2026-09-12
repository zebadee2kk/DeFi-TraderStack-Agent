from datetime import UTC, datetime

from pydantic import BaseModel, Field


class MarketFeatures(BaseModel):
    trend_4h: float = Field(ge=-1, le=1)
    trend_1d: float = Field(ge=-1, le=1)
    volatility_z: float
    relative_volume: float = Field(ge=0)
    spread_bps: float = Field(ge=0)
    # --- miles-inspired GARCH sizing (paper research) ---
    # One-step-ahead annualized vol forecast (fraction, e.g. 0.55). None when
    # the builder did not run GARCH. RiskEngine may only *reduce* size from
    # this number; it is never an authorisation.
    garch_forecast_vol: float | None = Field(default=None, ge=0)
    # --- providers (Epic 3): altFINS technical-signal slot ---------------------
    # Optional pre-computed external technical-signal score in [-1, 1] (bearish
    # to bullish) and which provider it came from. None when no such provider
    # ran this cycle; existing consumers are unaffected.
    external_signal_score: float | None = Field(default=None, ge=-1, le=1)
    external_signal_source: str | None = None


class OnChainFeatures(BaseModel):
    exchange_netflow_z: float | None = None
    large_wallet_accumulation: float | None = Field(default=None, ge=-1, le=1)


class NarrativeFeatures(BaseModel):
    mention_velocity_z: float | None = None
    sentiment: float | None = Field(default=None, ge=-1, le=1)


class NewsFeatures(BaseModel):
    event_score: float = Field(default=0, ge=0, le=1)
    adverse_event: bool = False


# --- paper-research edge data plane -------------------------------------------
#
# Research/risk context only. RiskEngine reads market.spread_bps,
# market.volatility_z, and (when PAPER_GARCH_SIZE is on) market.garch_forecast_vol;
# it does not read this slice to size, side, or authorize a trade. The
# meta-agent may see these numbers as withhold-only context. Bounded counts
# are in [0, 1]; z-scores are clipped to [-5, 5].


class ResearchEdgeFeatures(BaseModel):
    liq_notional_long_z: float | None = Field(default=None, ge=-5, le=5)
    liq_notional_short_z: float | None = Field(default=None, ge=-5, le=5)
    liq_count_long: float | None = Field(default=None, ge=0, le=1)
    liq_count_short: float | None = Field(default=None, ge=0, le=1)
    cross_venue_mid_divergence_bps: float | None = Field(default=None, ge=0)
    cross_venue_mid_source: str | None = None


class AssetFeatureVector(BaseModel):
    asset: str
    observed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    market: MarketFeatures
    onchain: OnChainFeatures = Field(default_factory=OnChainFeatures)
    narrative: NarrativeFeatures = Field(default_factory=NarrativeFeatures)
    news: NewsFeatures = Field(default_factory=NewsFeatures)
    # --- paper-research edge data plane ---
    edge: ResearchEdgeFeatures = Field(default_factory=ResearchEdgeFeatures)
    source_ids: list[str] = Field(default_factory=list)
    schema_version: str = "1.1"
