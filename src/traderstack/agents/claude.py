import json
from dataclasses import dataclass

import httpx

from traderstack.agents.meta import EvidencePacket, MetaAgentDecision

META_AGENT_SCHEMA = {
    "type": "object",
    "properties": {
        "approve": {"type": "boolean"},
        "confidence_delta": {"type": "number"},
        "rationale": {"type": "string"},
        "risk_flags": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["approve", "confidence_delta", "rationale", "risk_flags"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """You are a constrained crypto trade review agent.
You review an already-generated deterministic candidate using only the supplied evidence packet.
You may approve or veto it and may adjust confidence only within the schema's bounded range.
You must not invent a different trade direction, request more capital, or imply that risk controls can be bypassed.
Prefer veto when evidence is stale, contradictory, materially adverse, or insufficiently corroborated.
Return only the structured response required by the output schema."""


@dataclass
class AnthropicMetaAgentClient:
    api_key: str
    model: str = "claude-haiku-4-5-20251001"
    base_url: str = "https://api.anthropic.com"
    max_tokens: int = 512
    timeout_seconds: float = 20.0
    client: httpx.AsyncClient | None = None

    async def __call__(self, packet: EvidencePacket) -> MetaAgentDecision:
        payload = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": SYSTEM_PROMPT,
            "messages": [
                {
                    "role": "user",
                    "content": json.dumps(packet.model_dump(mode="json"), separators=(",", ":")),
                }
            ],
            "output_config": {
                "format": {
                    "type": "json_schema",
                    "schema": META_AGENT_SCHEMA,
                }
            },
        }
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        if self.client is not None:
            response = await self.client.post("/v1/messages", headers=headers, json=payload)
        else:
            async with httpx.AsyncClient(
                base_url=self.base_url.rstrip("/"),
                timeout=self.timeout_seconds,
            ) as client:
                response = await client.post("/v1/messages", headers=headers, json=payload)
        response.raise_for_status()
        body = response.json()
        stop_reason = body.get("stop_reason") if isinstance(body, dict) else None
        if stop_reason in {"refusal", "max_tokens"}:
            raise RuntimeError(f"Claude meta-agent failed closed: stop_reason={stop_reason}")
        content = body.get("content") if isinstance(body, dict) else None
        if not isinstance(content, list):
            raise TypeError("unexpected Claude Messages response")
        text = next(
            (
                block.get("text")
                for block in content
                if isinstance(block, dict)
                and block.get("type") == "text"
                and isinstance(block.get("text"), str)
            ),
            None,
        )
        if text is None:
            raise TypeError("Claude response missing structured text block")
        return MetaAgentDecision.model_validate_json(text)
