from datetime import UTC, datetime

from pydantic import BaseModel, Field

from traderstack.features import (
    AssetFeatureVector,
    MarketFeatures,
    NarrativeFeatures,
    NewsFeatures,
    OnChainFeatures,
)


class OnChainSnapshot(BaseModel):
    asset: str
    observed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    exchange_netflow_z: float | None = None
    large_wallet_accumulation: float | None = Field(default=None, ge=-1, le=1)
    source_id: str


class SocialSnapshot(BaseModel):
    asset: str
    observed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    sentiment: float | None = Field(default=None, ge=-1, le=1)
    mention_velocity_z: float | None = None
    source_id: str


class NewsSnapshot(BaseModel):
    asset: str
    observed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    event_score: float = Field(default=0, ge=0, le=1)
    adverse_event: bool = False
    item_count: int = Field(default=0, ge=0)
    source_id: str


# --- providers (Epic 3): altFINS technical-signal slot -------------------------


class AltFinsSignalSnapshot(BaseModel):
    """A directional technical-signal score for one asset, bounded to [-1, 1]
    (see traderstack.market.altfins for how it's derived and why it's a
    documented assumption rather than a field altFINS returns directly).
    """

    asset: str
    observed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    score: float | None = Field(default=None, ge=-1, le=1)
    source_id: str


def merge_external_intelligence(
    asset: str,
    market: MarketFeatures,
    *,
    onchain: OnChainSnapshot | None = None,
    social: SocialSnapshot | None = None,
    news: NewsSnapshot | None = None,
    altfins: AltFinsSignalSnapshot | None = None,
) -> AssetFeatureVector:
    source_ids: list[str] = []
    if onchain is not None:
        source_ids.append(onchain.source_id)
    if social is not None:
        source_ids.append(social.source_id)
    if news is not None:
        source_ids.append(news.source_id)
    # --- providers (Epic 3): altFINS technical-signal slot ---------------------
    market_features = market
    if altfins is not None:
        source_ids.append(altfins.source_id)
        market_features = market.model_copy(
            update={
                "external_signal_score": altfins.score,
                "external_signal_source": altfins.source_id,
            }
        )
    return AssetFeatureVector(
        asset=asset.upper(),
        market=market_features,
        onchain=OnChainFeatures(
            exchange_netflow_z=onchain.exchange_netflow_z if onchain else None,
            large_wallet_accumulation=onchain.large_wallet_accumulation if onchain else None,
        ),
        narrative=NarrativeFeatures(
            mention_velocity_z=social.mention_velocity_z if social else None,
            sentiment=social.sentiment if social else None,
        ),
        news=NewsFeatures(
            event_score=news.event_score if news else 0,
            adverse_event=news.adverse_event if news else False,
        ),
        source_ids=source_ids,
    )
