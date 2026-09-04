import json
from dataclasses import dataclass

import httpx

from traderstack.intelligence import NewsSnapshot


@dataclass
class PerplexityNewsProvider:
    api_key: str
    model: str = "sonar"
    base_url: str = "https://api.perplexity.ai"
    client: httpx.AsyncClient | None = None

    async def fetch(self, asset: str) -> NewsSnapshot:
        symbol = asset.upper()
        prompt = (
            f"Review the latest credible market-moving news for cryptocurrency {symbol}. "
            "Return one compact JSON object with keys event_score (0 to 1), "
            "adverse_event (boolean), and item_count (non-negative integer). "
            "event_score should reflect likely near-term market relevance, not sentiment alone."
        )
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": "You are a conservative crypto market-news classifier. Output JSON only.",
                },
                {"role": "user", "content": prompt},
            ],
            "max_tokens": 250,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if self.client is not None:
            response = await self.client.post("/v1/sonar", headers=headers, json=payload)
        else:
            async with httpx.AsyncClient(base_url=self.base_url.rstrip("/"), timeout=20) as client:
                response = await client.post("/v1/sonar", headers=headers, json=payload)
        response.raise_for_status()
        body = response.json()
        choices = body.get("choices") if isinstance(body, dict) else None
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise TypeError("unexpected Perplexity response")
        message = choices[0].get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str):
            raise TypeError("Perplexity response missing message content")
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ValueError("Perplexity news response was not JSON") from exc
        if not isinstance(parsed, dict):
            raise TypeError("Perplexity news response must be an object")
        event_score = parsed.get("event_score", 0.0)
        adverse_event = parsed.get("adverse_event", False)
        item_count = parsed.get("item_count", 0)
        if not isinstance(event_score, int | float):
            raise TypeError("Perplexity event_score must be numeric")
        if not isinstance(adverse_event, bool):
            raise TypeError("Perplexity adverse_event must be boolean")
        if not isinstance(item_count, int):
            raise TypeError("Perplexity item_count must be integer")
        return NewsSnapshot(
            asset=symbol,
            event_score=max(0.0, min(1.0, float(event_score))),
            adverse_event=adverse_event,
            item_count=max(0, item_count),
            source_id=f"perplexity:{self.model}",
        )
