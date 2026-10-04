import math
from datetime import UTC, date, datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

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


# --- on-chain regime gate (#139) ---------------------------------------------


class OnChainRegimeSnapshot(BaseModel):
    """Bounded, versioned on-chain valuation regime for one asset.

    Derived by ``traderstack.market.coinmetrics`` from the Coin Metrics
    community series (``source_asset`` is the series actually used — BTC
    for every requested asset in the first slice; ``asset`` is what was
    requested). ``as_of`` is the newest committed row used. ``None`` fields
    mean "not enough history" and the pipeline gate treats them as
    unavailable (fail closed for new longs). Nothing here can size, side,
    or authorise; the gate only adds a rejection reason.
    """

    asset: str
    source_asset: str
    observed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    as_of: date
    mvrv_z: float | None = Field(default=None, ge=-10, le=10)
    mvrv_z_percentile: float | None = Field(default=None, ge=0, le=1)
    nupl: float | None = Field(default=None, ge=-5, le=1)
    points: int = Field(default=0, ge=0)
    window_days: int = Field(gt=0)
    feature_version: str
    source_id: str


ObservationType = Literal["onchain", "social", "news", "altfins", "onchain_regime"]
ObservationScalar = str | int | float | bool | None

_ALLOWED_OBSERVATION_PAYLOAD_FIELDS: dict[ObservationType, frozenset[str]] = {
    "onchain": frozenset({"exchange_netflow_z", "large_wallet_accumulation"}),
    "social": frozenset({"sentiment", "mention_velocity_z"}),
    "news": frozenset({"event_score", "adverse_event", "item_count"}),
    "altfins": frozenset({"score"}),
    "onchain_regime": frozenset(
        {
            "source_asset",
            "as_of",
            "mvrv_z",
            "mvrv_z_percentile",
            "nupl",
            "points",
            "window_days",
            "feature_version",
        }
    ),
}


class IntelligenceObservation(BaseModel):
    """Bounded provider-native evidence preserved before canonical feature merge."""

    asset: str = Field(min_length=1, max_length=32)
    observed_at: datetime
    source_id: str = Field(min_length=1, max_length=128)
    observation_type: ObservationType
    schema_version: str = Field(default="1.0", min_length=1, max_length=32)
    payload: dict[str, ObservationScalar]

    @model_validator(mode="after")
    def _validate_payload_boundary(self) -> "IntelligenceObservation":
        allowed = _ALLOWED_OBSERVATION_PAYLOAD_FIELDS[self.observation_type]
        unexpected = set(self.payload) - allowed
        if unexpected:
            raise ValueError(
                "unsupported intelligence observation payload fields: "
                + ", ".join(sorted(unexpected))
            )
        for key, value in self.payload.items():
            if isinstance(value, str) and (len(value) > 64 or "\n" in value or "\r" in value):
                raise ValueError(f"unsafe string value for intelligence field {key}")
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError(f"non-finite value for intelligence field {key}")
        return self


def normalize_intelligence_snapshot(
    snapshot: OnChainSnapshot
    | SocialSnapshot
    | NewsSnapshot
    | AltFinsSignalSnapshot
    | OnChainRegimeSnapshot,
) -> IntelligenceObservation:
    """Convert a typed provider snapshot to an allowlisted research payload.

    This deliberately does not accept arbitrary provider JSON or free-form text.
    Provider adapters must first map external data into one of the bounded snapshot
    models above.
    """

    if isinstance(snapshot, OnChainSnapshot):
        observation_type: ObservationType = "onchain"
        payload: dict[str, ObservationScalar] = {
            "exchange_netflow_z": snapshot.exchange_netflow_z,
            "large_wallet_accumulation": snapshot.large_wallet_accumulation,
        }
    elif isinstance(snapshot, SocialSnapshot):
        observation_type = "social"
        payload = {
            "sentiment": snapshot.sentiment,
            "mention_velocity_z": snapshot.mention_velocity_z,
        }
    elif isinstance(snapshot, NewsSnapshot):
        observation_type = "news"
        payload = {
            "event_score": snapshot.event_score,
            "adverse_event": snapshot.adverse_event,
            "item_count": snapshot.item_count,
        }
    elif isinstance(snapshot, AltFinsSignalSnapshot):
        observation_type = "altfins"
        payload = {"score": snapshot.score}
    else:
        observation_type = "onchain_regime"
        payload = {
            "source_asset": snapshot.source_asset,
            "as_of": snapshot.as_of.isoformat(),
            "mvrv_z": snapshot.mvrv_z,
            "mvrv_z_percentile": snapshot.mvrv_z_percentile,
            "nupl": snapshot.nupl,
            "points": snapshot.points,
            "window_days": snapshot.window_days,
            "feature_version": snapshot.feature_version,
        }

    return IntelligenceObservation(
        asset=snapshot.asset.upper(),
        observed_at=snapshot.observed_at,
        source_id=snapshot.source_id,
        observation_type=observation_type,
        payload=payload,
    )


def merge_external_intelligence(
    asset: str,
    market: MarketFeatures,
    *,
    onchain: OnChainSnapshot | None = None,
    social: SocialSnapshot | None = None,
    news: NewsSnapshot | None = None,
    altfins: AltFinsSignalSnapshot | None = None,
    # --- on-chain regime gate (#139) ---
    onchain_regime: OnChainRegimeSnapshot | None = None,
) -> AssetFeatureVector:
    source_ids: list[str] = []
    if onchain is not None:
        source_ids.append(onchain.source_id)
    if social is not None:
        source_ids.append(social.source_id)
    if news is not None:
        source_ids.append(news.source_id)
    # --- on-chain regime gate (#139) ---
    if onchain_regime is not None:
        source_ids.append(onchain_regime.source_id)
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
            # --- on-chain regime gate (#139) ---
            mvrv_z=onchain_regime.mvrv_z if onchain_regime else None,
            mvrv_z_percentile=onchain_regime.mvrv_z_percentile if onchain_regime else None,
            nupl=onchain_regime.nupl if onchain_regime else None,
            regime_as_of=onchain_regime.as_of if onchain_regime else None,
            regime_version=onchain_regime.feature_version if onchain_regime else None,
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
