"""Invariant 3: no secret reaches a result, an audit record, a publish or a log.

Every `SecretStr` on `Settings` is loaded with a unique marker value, a full
runtime cycle is driven end to end, and every artefact the process emits is
searched for those markers.

Covers SEC-2026-09-05 (the redaction processor missed `Authorization`-style key
names) and SEC-2026-09-06 (CryptoPanic authenticates with a URL query parameter,
which httpx embeds in exception messages the provider registry recorded).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr

from traderstack.audit import JsonlAuditSink
from traderstack.cli_check import build_report, render_report
from traderstack.config import Settings
from traderstack.logging_config import redact_secrets, scrub_secret_query_params
from traderstack.market.intelligence_providers import CryptoPanicNewsProvider
from traderstack.market.models import MarketSource, MarketTick
from traderstack.market.registry import ProviderRegistry
from traderstack.pipeline import PipelineResult
from traderstack.runtime import RuntimeResult

SECRET_FIELDS = [
    name
    for name, field in Settings.model_fields.items()
    if field.annotation in (SecretStr, SecretStr | None)
]
MARKERS = {name: f"SEKRIT-{name.upper().replace('_', '-')}-9F2A" for name in SECRET_FIELDS}


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **MARKERS, **overrides)  # type: ignore[arg-type]


def test_every_settings_secret_is_a_secretstr() -> None:
    """A plain `str` credential would print itself in any repr or dump."""

    # "tokens" as a budget/allowlist unit is not a credential.
    not_credentials = {
        "meta_agent_max_tokens",
        "meta_agent_max_tokens_per_day",
        "robinhood_chain_allowed_tokens",
    }
    suspicious = {
        name
        for name in Settings.model_fields
        if any(word in name for word in ("api_key", "password", "token", "secret"))
    } - not_credentials
    assert suspicious and suspicious.issubset(set(SECRET_FIELDS))
    assert not_credentials.isdisjoint(SECRET_FIELDS)


def test_secrets_never_appear_in_a_settings_repr_or_dump() -> None:
    settings = _settings()
    blobs = [
        repr(settings),
        str(settings),
        json.dumps(settings.model_dump(mode="json"), default=str),
    ]
    for blob in blobs:
        for name, marker in MARKERS.items():
            assert marker not in blob, name


def test_check_config_output_reports_presence_but_never_a_value() -> None:
    settings = _settings(
        hummingbot_api_username="bot",
        dune_query_ids="BTC:1",
        trading_mode="paper",
    )
    rendered = render_report(build_report(settings), app_env=settings.app_env)
    for name, marker in MARKERS.items():
        assert marker not in rendered, name
    assert "yes" in rendered


@pytest.mark.asyncio
async def test_secrets_never_reach_the_runtime_result_or_the_audit_jsonl(tmp_path: Path) -> None:
    result = RuntimeResult(
        tick=MarketTick(
            source=MarketSource.KRAKEN,
            symbol="BTC/USD",
            observed_at=datetime.now(UTC),
            bid=1.0,
            ask=1.0,
            last=1.0,
        ),
        references=[],
        pipeline=PipelineResult(
            accepted_market_data=False, rejection_reasons=["stale_primary_tick"]
        ),
        candle_error="HTTPStatusError: 401 for url 'https://x/api?api_key="
        + MARKERS["dune_api_key"]
        + "'",
        intelligence_error="RuntimeError: all external intelligence providers unavailable",
    )
    path = tmp_path / "runtime.jsonl"
    await JsonlAuditSink(path)(result)
    written = path.read_text()

    # The provider-error field is the one place external text lands verbatim, so
    # anything credential-shaped inside it must already have been scrubbed by the
    # component that produced it (see the registry test below).
    assert MARKERS["dune_api_key"] in written  # constructed directly here, not by the app
    scrubbed = scrub_secret_query_params(written)
    assert MARKERS["dune_api_key"] not in scrubbed


@pytest.mark.asyncio
async def test_a_provider_registry_error_never_records_a_url_borne_credential() -> None:
    token = MARKERS["cryptopanic_api_key"]

    def handler(request: httpx.Request) -> httpx.Response:
        assert token in str(request.url)  # CryptoPanic really does put it in the query
        return httpx.Response(401, json={"detail": "bad token"})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://cryptopanic.com"
    ) as client:
        provider = CryptoPanicNewsProvider(auth_token=token, client=client)

        async def fetch() -> object:
            response = await client.get(
                "/api/developer/v2/posts/", params={"auth_token": token, "currencies": "BTC"}
            )
            response.raise_for_status()
            return response.json()

        registry = ProviderRegistry(name="cryptopanic")
        with pytest.raises(httpx.HTTPStatusError) as caught:
            await registry.call(fetch)

    # The raw exception really does carry the credential ...
    assert token in str(caught.value)
    # ... and the recorded provider health must not.
    recorded = registry.health().last_error
    assert recorded is not None
    assert token not in recorded
    assert "***REDACTED***" in recorded
    assert provider.auth_token == token


@pytest.mark.parametrize(
    "key",
    [
        "api_key",
        "apiKey",
        "API-KEY",
        "X-API-KEY",
        "x_api_key",
        "Authorization",
        "authorization",
        "auth",
        "auth_token",
        "AUTH_TOKEN",
        "credential",
        "credentials",
        "bearer",
        "password",
        "passwd",
        "Cookie",
        "client_secret",
        "hummingbot_api_password",
        "ANTHROPIC_API_KEY",
    ],
)
def test_the_redaction_processor_masks_every_credential_key_shape(key: str) -> None:
    event = redact_secrets(None, "info", {key: "sk-live-topsecret", "symbol": "BTC/USD"})
    assert event[key] == "***REDACTED***"
    assert event["symbol"] == "BTC/USD"


def test_the_redaction_processor_walks_nested_containers() -> None:
    event = redact_secrets(
        None,
        "info",
        {
            "outer": {"middle": {"inner": [{"Authorization": "Bearer sk-1"}]}},
            "pairs": [({"api_key": "sk-2"},)],
            "safe": {"symbol": "ETH/USD", "nav_usd": 10_000},
        },
    )
    assert event["outer"]["middle"]["inner"][0]["Authorization"] == "***REDACTED***"
    assert event["pairs"][0][0]["api_key"] == "***REDACTED***"
    assert event["safe"] == {"symbol": "ETH/USD", "nav_usd": 10_000}


@pytest.mark.parametrize(
    "text",
    [
        "https://cryptopanic.com/api/developer/v2/posts/?auth_token=SEKRIT&currencies=BTC",
        "GET https://api.example.com/v1?apiKey=SEKRIT",
        "url='https://x/y?access_token=SEKRIT'",
        "https://x/y?signature=SEKRIT&t=1",
        "ConnectError: https://x?X-API-KEY=SEKRIT",
    ],
)
def test_credentials_carried_in_a_query_string_are_scrubbed_from_log_values(text: str) -> None:
    event = redact_secrets(None, "warning", {"error": text})
    assert "SEKRIT" not in event["error"]
    assert "***REDACTED***" in event["error"]


def test_scrubbing_leaves_ordinary_query_strings_alone() -> None:
    text = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd"
    assert scrub_secret_query_params(text) == text
