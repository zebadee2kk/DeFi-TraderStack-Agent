import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TypeVar, cast

from traderstack.features import AssetFeatureVector, MarketFeatures
from traderstack.intelligence import (
    AltFinsSignalSnapshot,
    NewsSnapshot,
    OnChainRegimeSnapshot,
    OnChainSnapshot,
    SocialSnapshot,
    merge_external_intelligence,
)

T = TypeVar("T")
OnChainFetcher = Callable[[str], Awaitable[OnChainSnapshot]]
SocialFetcher = Callable[[str], Awaitable[SocialSnapshot]]
NewsFetcher = Callable[[str], Awaitable[NewsSnapshot]]
# --- providers (Epic 3): altFINS technical-signal slot ------------------------
AltFinsFetcher = Callable[[str], Awaitable[AltFinsSignalSnapshot]]
# --- on-chain regime gate (#139) ---
OnChainRegimeFetcher = Callable[[str], Awaitable[OnChainRegimeSnapshot]]


@dataclass
class IntelligenceCache:
    max_age_seconds: float = 300.0
    _values: dict[str, object] = field(default_factory=dict)

    def get(self, key: str, expected_type: type[T]) -> T | None:
        value = self._values.get(key)
        if value is None or not isinstance(value, expected_type):
            return None
        observed_at = getattr(value, "observed_at", None)
        if not isinstance(observed_at, datetime):
            return None
        age = (datetime.now(UTC) - observed_at).total_seconds()
        return cast(T, value) if age <= self.max_age_seconds else None

    def put(self, key: str, value: object) -> None:
        self._values[key] = value


# Pipeline / runtime reject reason when an opted-in fail-closed news
# provider (Crucix) errors or times out. Distinct from adverse_news_event
# (we saw news) and no_external_intelligence (nothing returned).
PROVIDER_UNAVAILABLE_REASON = "intelligence_provider_unavailable"


@dataclass(frozen=True)
class ExternalIntelligence:
    """The external snapshots gathered for one asset in one cycle (any may be missing)."""

    asset: str
    onchain: OnChainSnapshot | None = None
    social: SocialSnapshot | None = None
    news: NewsSnapshot | None = None
    # --- providers (Epic 3): altFINS technical-signal slot ---------------------
    altfins: AltFinsSignalSnapshot | None = None
    # --- crucix fail-closed ---
    # True when an opted-in fail-closed news provider (Crucix) errored or
    # timed out. The pipeline rejects new risk; exits already ran upstream.
    provider_unavailable: bool = False
    # --- on-chain regime gate (#139) ---
    # Coin Metrics-derived valuation regime. None when the slot is not
    # registered or its fetch failed; the opt-in pipeline gate then rejects
    # new BUY entries (onchain_regime_unavailable). It is a policy input,
    # not asset intelligence: it does not count toward `is_empty`, so it
    # cannot by itself satisfy INTELLIGENCE_REQUIRED.
    onchain_regime: OnChainRegimeSnapshot | None = None

    @property
    def source_ids(self) -> list[str]:
        return [
            s.source_id
            for s in (self.onchain, self.social, self.news, self.altfins, self.onchain_regime)
            if s is not None
        ]

    @property
    def is_empty(self) -> bool:
        return (
            self.onchain is None
            and self.social is None
            and self.news is None
            and self.altfins is None
        )


@dataclass
class IntelligenceOrchestrator:
    onchain: OnChainFetcher | None = None
    social: SocialFetcher | None = None
    news: tuple[NewsFetcher, ...] = ()
    cache: IntelligenceCache = field(default_factory=IntelligenceCache)
    require_any_external: bool = False
    # --- providers (Epic 3): altFINS technical-signal slot ---------------------
    altfins: AltFinsFetcher | None = None
    # --- crucix fail-closed ---
    # News fetchers that must succeed for new risk. Empty unless Crucix is
    # opted in. Optional `news` fetchers still isolate failures.
    fail_closed_news: tuple[NewsFetcher, ...] = ()
    # --- on-chain regime gate (#139) ---
    # Registered only when ONCHAIN_REGIME_GATE_ENABLED=true. A raise is
    # isolated to None like every other slot; the pipeline gate is what
    # makes that None fail closed for new longs.
    onchain_regime: OnChainRegimeFetcher | None = None

    async def gather(self, asset: str) -> ExternalIntelligence:
        symbol = asset.upper()
        news_task = asyncio.create_task(self._fetch_news(symbol))
        onchain, social, altfins, onchain_regime = await asyncio.gather(
            self._fetch_one("onchain", symbol, self.onchain, OnChainSnapshot),
            self._fetch_one("social", symbol, self.social, SocialSnapshot),
            self._fetch_one("altfins", symbol, self.altfins, AltFinsSignalSnapshot),
            # --- on-chain regime gate (#139) ---
            self._fetch_one("onchain_regime", symbol, self.onchain_regime, OnChainRegimeSnapshot),
        )
        news, provider_unavailable = await news_task
        bundle = ExternalIntelligence(
            asset=symbol,
            onchain=onchain,
            social=social,
            news=news,
            altfins=altfins,
            provider_unavailable=provider_unavailable,
            onchain_regime=onchain_regime,
        )
        if self.require_any_external and bundle.is_empty and not provider_unavailable:
            raise RuntimeError("all external intelligence providers unavailable")
        return bundle

    async def build(self, asset: str, market: MarketFeatures) -> AssetFeatureVector:
        bundle = await self.gather(asset)
        return merge_external_intelligence(
            bundle.asset,
            market,
            onchain=bundle.onchain,
            social=bundle.social,
            news=bundle.news,
            altfins=bundle.altfins,
            onchain_regime=bundle.onchain_regime,
        )

    async def _fetch_one(
        self,
        kind: str,
        asset: str,
        fetcher: Callable[[str], Awaitable[T]] | None,
        expected_type: type[T],
    ) -> T | None:
        key = f"{kind}:{asset}"
        cached = self.cache.get(key, expected_type)
        if cached is not None:
            return cached
        if fetcher is None:
            return None
        try:
            value = await fetcher(asset)
        except Exception:  # noqa: BLE001 - provider failure is isolated at orchestration boundary.
            return None
        if not isinstance(value, expected_type):
            return None
        self.cache.put(key, value)
        return value

    async def _fetch_news(self, asset: str) -> tuple[NewsSnapshot | None, bool]:
        cached = self.cache.get(f"news:{asset}", NewsSnapshot)
        if cached is not None:
            return cached, False
        if not self.news and not self.fail_closed_news:
            return None, False
        optional_results, fail_closed_results = await asyncio.gather(
            asyncio.gather(*(fetcher(asset) for fetcher in self.news), return_exceptions=True),
            asyncio.gather(
                *(fetcher(asset) for fetcher in self.fail_closed_news),
                return_exceptions=True,
            ),
        )
        snapshots = [result for result in optional_results if isinstance(result, NewsSnapshot)]
        provider_unavailable = False
        for result in fail_closed_results:
            if isinstance(result, NewsSnapshot):
                snapshots.append(result)
            else:
                provider_unavailable = True
        if not snapshots:
            return None, provider_unavailable
        combined = NewsSnapshot(
            asset=asset,
            observed_at=max(snapshot.observed_at for snapshot in snapshots),
            event_score=max(snapshot.event_score for snapshot in snapshots),
            adverse_event=any(snapshot.adverse_event for snapshot in snapshots),
            item_count=sum(snapshot.item_count for snapshot in snapshots),
            source_id="+".join(snapshot.source_id for snapshot in snapshots),
        )
        # A fail-closed outage must not be cached as "no news" / partial news.
        if not provider_unavailable:
            self.cache.put(f"news:{asset}", combined)
        return combined, provider_unavailable
