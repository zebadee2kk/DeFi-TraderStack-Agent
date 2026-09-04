"""Perplexity news-research adapter (Epic 3).

Targets Perplexity's Agent API (``POST /v1/agent``), not the older Sonar Chat
Completions endpoint (``POST /v1/sonar``) this adapter previously called.
Verified against https://docs.perplexity.ai/api-reference/agent-post,
https://docs.perplexity.ai/docs/agent-api/migrate-from-sonar/how-to and
https://docs.perplexity.ai/docs/agent-api/building-agents/shape-output on
2026-09-04: Sonar Chat Completions is documented as deprecated in favour of
the Agent API and scheduled to stop working 27 Sep 2026
(https://docs.perplexity.ai/docs/agent-api/migrate-from-sonar/overview),
so the Agent API is the only one of the two worth building against now.

Field mapping from the old Sonar request: ``messages`` (system+user) becomes
``instructions`` (system) + ``input`` (a list of message items); ``max_tokens``
becomes ``max_output_tokens``; ``response_format.json_schema`` is unchanged in
shape and is used here to force a schema-constrained JSON reply instead of
hoping the model's prose happens to parse. The reply text lives at
``output[].content[].text`` for the item with ``type == "message"``.
"""

import json
from dataclasses import dataclass
from typing import Any

import httpx

from traderstack.intelligence import NewsSnapshot

AGENT_ENDPOINT = "/v1/agent"

_RESPONSE_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "event_score": {"type": "number", "minimum": 0, "maximum": 1},
        "adverse_event": {"type": "boolean"},
        "item_count": {"type": "integer", "minimum": 0},
    },
    "required": ["event_score", "adverse_event", "item_count"],
}


@dataclass
class PerplexityNewsProvider:
    api_key: str
    model: str = "perplexity/sonar"
    base_url: str = "https://api.perplexity.ai"
    client: httpx.AsyncClient | None = None

    async def fetch(self, asset: str) -> NewsSnapshot:
        symbol = asset.upper()
        instructions = (
            "You are a conservative crypto market-news classifier. Reply only "
            "with the requested JSON object - no prose, no markdown."
        )
        prompt = (
            f"Review the latest credible market-moving news for cryptocurrency {symbol}. "
            "Return event_score (0 to 1, reflecting likely near-term market relevance, "
            "not sentiment alone), adverse_event (boolean) and item_count "
            "(non-negative integer, how many distinct relevant items you found)."
        )
        payload: dict[str, Any] = {
            "model": self.model,
            "instructions": instructions,
            "input": [{"type": "message", "role": "user", "content": prompt}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "news_snapshot", "schema": _RESPONSE_JSON_SCHEMA},
            },
            "max_output_tokens": 250,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if self.client is not None:
            response = await self.client.post(AGENT_ENDPOINT, headers=headers, json=payload)
        else:
            async with httpx.AsyncClient(base_url=self.base_url.rstrip("/"), timeout=20) as client:
                response = await client.post(AGENT_ENDPOINT, headers=headers, json=payload)
        response.raise_for_status()
        body = response.json()
        content = _extract_output_text(body)
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


def _extract_output_text(body: object) -> str:
    output = body.get("output") if isinstance(body, dict) else None
    if not isinstance(output, list):
        raise TypeError("unexpected Perplexity Agent API response")
    for item in output:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        contents = item.get("content")
        if not isinstance(contents, list):
            continue
        texts = [
            piece["text"]
            for piece in contents
            if isinstance(piece, dict)
            and piece.get("type") == "output_text"
            and isinstance(piece.get("text"), str)
        ]
        if texts:
            return "".join(texts)
    raise TypeError("Perplexity Agent API response missing output text")
