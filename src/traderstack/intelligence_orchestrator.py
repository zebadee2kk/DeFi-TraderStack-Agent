import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from traderstack.features import AssetFeatureVector, MarketFeatures
from traderstack.intelligence import (
    NewsSnapshot,
    OnChainSnapshot,
    SocialSnapshot,
    merge_external_intelligence,
)

OnChainFetcher = Callable[[str], Awaitable[OnChainSnapshot]]
SocialFetcher = Callable[[str], Awaitable[SocialSnapshot]]
NewsFetcher = Callable[[str], Awaitable[NewsSnapshot]]


@dataclass
class IntelligenceCache:
    max_age_seconds: float = 300.0
    _values: dict[str, object] = field(default_factory=dict)

    def get(self, key: str, expected_type: type[object]) -> object | None:
        value = self._values.get(key)
        if value is None or not isinstance(value, expected_type):
            return None
        observed_at = getattr(value, "observed_at", None)
        if not isinstance(observed_at, datetime):
            return None
        age = (datetime.now(UTC) - observed_at).total_seconds()
        return value if age <= self.max_age_seconds else None

    def put(self, key: str, value: object) -> None:
        self._values[key] = value


@dataclass
class IntelligenceOrchestrator:
    onchain: OnChainFetcher | None = None
    social: SocialFetcher | None = None
    news: tuple[NewsFetcher, ...] = ()
    cache: IntelligenceCache = field(default_factory=IntelligenceCache)
    require_any_external: bool = False

    async def build(self, asset: str, market: MarketFeatures) -> AssetFeatureVector:
        symbol = asset.upper()
        onchain = await self._fetch_one("onchain", symbol, self.onchain, OnChainSnapshot)
        social = await self._fetch_one("social", symbol, self.social, SocialSnapshot)
        news = await self._fetch_news(symbol)
        if self.require_any_external and onchain is None and social is None and news is None:
            raise RuntimeError("all external intelligence providers unavailable")
        return merge_external_intelligence(
            symbol,
            market,
            onchain=onchain,
            social=social,
            news=news,
        )

    async def _fetch_one(
        self,
        kind: str,
        asset: str,
        fetcher: Callable[[str], Awaitable[object]] | None,
        expected_type: type[object],
    ) -> object | None:
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

    async def _fetch_news(self, asset: str) -> NewsSnapshot | None:
        cached = self.cache.get(f"news:{asset}", NewsSnapshot)
        if isinstance(cached, NewsSnapshot):
            return cached
        if not self.news:
            return None
        results = await asyncio.gather(*(fetcher(asset) for fetcher in self.news), return_exceptions=True)
        snapshots = [result for result in results if isinstance(result, NewsSnapshot)]
        if not snapshots:
            return None
        combined = NewsSnapshot(
            asset=asset,
            observed_at=max(snapshot.observed_at for snapshot in snapshots),
            event_score=max(snapshot.event_score for snapshot in snapshots),
            adverse_event=any(snapshot.adverse_event for snapshot in snapshots),
            item_count=sum(snapshot.item_count for snapshot in snapshots),
            source_id="+".join(snapshot.source_id for snapshot in snapshots),
        )
        self.cache.put(f"news:{asset}", combined)
        return combined
