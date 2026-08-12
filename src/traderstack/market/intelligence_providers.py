from dataclasses import dataclass

import httpx

from traderstack.intelligence import NewsSnapshot, OnChainSnapshot, SocialSnapshot


@dataclass
class DuneOnChainProvider:
    api_key: str
    query_ids: dict[str, int]
    netflow_field: str = "exchange_netflow_z"
    accumulation_field: str = "large_wallet_accumulation"
    base_url: str = "https://api.dune.com"
    client: httpx.AsyncClient | None = None

    async def fetch(self, asset: str) -> OnChainSnapshot:
        query_id = self.query_ids.get(asset.upper())
        if query_id is None:
            raise KeyError(f"no Dune query configured for {asset.upper()}")
        path = f"/api/v1/query/{query_id}/results"
        headers = {"X-Dune-Api-Key": self.api_key}
        if self.client is not None:
            response = await self.client.get(path, headers=headers)
        else:
            async with httpx.AsyncClient(base_url=self.base_url, timeout=20) as client:
                response = await client.get(path, headers=headers)
        response.raise_for_status()
        payload = response.json()
        result = payload.get("result") if isinstance(payload, dict) else None
        rows = result.get("rows") if isinstance(result, dict) else None
        if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
            raise TypeError("unexpected Dune query result")
        row = rows[0]
        netflow = row.get(self.netflow_field)
        accumulation = row.get(self.accumulation_field)
        return OnChainSnapshot(
            asset=asset.upper(),
            exchange_netflow_z=float(netflow) if isinstance(netflow, int | float) else None,
            large_wallet_accumulation=(
                float(accumulation) if isinstance(accumulation, int | float) else None
            ),
            source_id=f"dune:query:{query_id}",
        )


@dataclass
class LunarCrushSocialProvider:
    api_key: str
    base_url: str = "https://lunarcrush.com"
    client: httpx.AsyncClient | None = None

    async def fetch(self, asset: str) -> SocialSnapshot:
        path = "/api4/public/coins/list/v1"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        if self.client is not None:
            response = await self.client.get(path, headers=headers)
        else:
            async with httpx.AsyncClient(base_url=self.base_url, timeout=20) as client:
                response = await client.get(path, headers=headers)
        response.raise_for_status()
        payload = response.json()
        rows = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            raise TypeError("unexpected LunarCrush response")
        row = next(
            (
                item
                for item in rows
                if isinstance(item, dict) and str(item.get("symbol", "")).upper() == asset.upper()
            ),
            None,
        )
        if row is None:
            raise ValueError(f"LunarCrush response missing {asset.upper()}")
        sentiment_raw = row.get("sentiment")
        sentiment = None
        if isinstance(sentiment_raw, int | float):
            sentiment = max(-1.0, min(1.0, (float(sentiment_raw) - 50.0) / 50.0))
        social_volume = row.get("social_volume_24h")
        interactions = row.get("interactions_24h")
        mention_velocity = None
        if isinstance(social_volume, int | float) and isinstance(interactions, int | float):
            denominator = max(float(social_volume), 1.0)
            mention_velocity = float(interactions) / denominator
        return SocialSnapshot(
            asset=asset.upper(),
            sentiment=sentiment,
            mention_velocity_z=mention_velocity,
            source_id="lunarcrush:coins-list-v1",
        )


@dataclass
class CryptoPanicNewsProvider:
    auth_token: str
    api_plan: str = "developer"
    base_url: str = "https://cryptopanic.com"
    client: httpx.AsyncClient | None = None

    async def fetch(self, asset: str) -> NewsSnapshot:
        path = f"/api/{self.api_plan}/v2/posts/"
        params = {
            "auth_token": self.auth_token,
            "currencies": asset.upper(),
            "public": "true",
        }
        if self.client is not None:
            response = await self.client.get(path, params=params)
        else:
            async with httpx.AsyncClient(base_url=self.base_url, timeout=20) as client:
                response = await client.get(path, params=params)
        response.raise_for_status()
        payload = response.json()
        rows = payload.get("results") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            raise TypeError("unexpected CryptoPanic response")
        importance = 0.0
        adverse_votes = 0
        total_votes = 0
        for row in rows:
            if not isinstance(row, dict):
                continue
            panic_score = row.get("panic_score")
            if isinstance(panic_score, int | float):
                importance = max(importance, max(0.0, min(1.0, float(panic_score) / 100.0)))
            votes = row.get("votes")
            if isinstance(votes, dict):
                negative = votes.get("negative", 0)
                positive = votes.get("positive", 0)
                if isinstance(negative, int) and isinstance(positive, int):
                    adverse_votes += negative
                    total_votes += negative + positive
        adverse = total_votes > 0 and adverse_votes / total_votes >= 0.6
        return NewsSnapshot(
            asset=asset.upper(),
            event_score=importance,
            adverse_event=adverse,
            item_count=len(rows),
            source_id=f"cryptopanic:{self.api_plan}:v2",
        )
