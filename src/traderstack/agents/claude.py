import json
from dataclasses import dataclass, field

import httpx

from traderstack.agents.meta import EvidencePacket, MetaAgentCall, MetaAgentDecision
from traderstack.agents.prompts import RegisteredPrompt, meta_agent_prompt

# JSON Schema for the Messages API `output_config.format` block. Structured
# outputs reject numeric constraints (minimum/maximum), so the bound on
# confidence_delta is enforced client-side by MetaAgentDecision instead — an
# out-of-range value fails validation and therefore fails closed.
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

# Retained for backwards compatibility; the registry is the source of truth.
SYSTEM_PROMPT = meta_agent_prompt().text

# Default model id. `claude-haiku-4-5` is the current alias for Claude Haiku 4.5,
# which supports structured outputs; overridable via META_AGENT_MODEL.
DEFAULT_META_AGENT_MODEL = "claude-haiku-4-5"


@dataclass
class AnthropicMetaAgentClient:
    api_key: str
    model: str = DEFAULT_META_AGENT_MODEL
    base_url: str = "https://api.anthropic.com"
    max_tokens: int = 512
    timeout_seconds: float = 20.0
    client: httpx.AsyncClient | None = None
    prompt: RegisteredPrompt = field(default_factory=meta_agent_prompt)

    async def __call__(self, packet: EvidencePacket) -> MetaAgentDecision:
        return (await self.review(packet)).decision

    async def review(self, packet: EvidencePacket) -> MetaAgentCall:
        """Call the Messages API and return the validated decision plus usage."""
        payload = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": self.prompt.text,
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
        if not isinstance(body, dict):
            raise TypeError("unexpected Claude Messages response")
        stop_reason = body.get("stop_reason")
        if stop_reason in {"refusal", "max_tokens"}:
            raise RuntimeError(f"Claude meta-agent failed closed: stop_reason={stop_reason}")
        content = body.get("content")
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
        decision = MetaAgentDecision.model_validate_json(text)
        usage = body.get("usage")
        usage = usage if isinstance(usage, dict) else {}
        return MetaAgentCall(
            decision=decision,
            model=body.get("model") if isinstance(body.get("model"), str) else self.model,
            input_tokens=_int(usage.get("input_tokens")),
            output_tokens=_int(usage.get("output_tokens")),
        )


def _int(value: object) -> int:
    return value if isinstance(value, int) and value >= 0 else 0
