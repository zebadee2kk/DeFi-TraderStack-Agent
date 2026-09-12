"""Hard boundary: the weather module cannot place live Polymarket orders."""

from __future__ import annotations

import ast
from pathlib import Path

import httpx
import pytest

from traderstack.config import Settings
from traderstack.polymarket.clob import ClobPublicClient
from traderstack.polymarket.gamma import GammaClient

REPO = Path(__file__).resolve().parents[2]
POLYMARKET_SRC = REPO / "src" / "traderstack" / "polymarket"
CRYPTO_LOOP = (
    REPO / "src" / "traderstack" / "cli.py",
    REPO / "src" / "traderstack" / "service.py",
    REPO / "src" / "traderstack" / "runtime.py",
    REPO / "src" / "traderstack" / "pipeline.py",
    REPO / "src" / "traderstack" / "risk.py",
    REPO / "src" / "traderstack" / "execution" / "submitter.py",
)

_FORBIDDEN_SOURCE = (
    "private_key",
    "api_secret",
    "l2_header",
    "py_clob_client",
    "ClobClient",
    "/order",
    "create_order",
    "post_order",
)


def test_settings_has_no_polymarket_promote_pin() -> None:
    assert "paper_promote_polymarket_weather" not in Settings.model_fields
    assert not any("polymarket" in name and "promote" in name for name in Settings.model_fields)


def test_settings_has_no_polymarket_credential_fields() -> None:
    forbidden = {
        name
        for name in Settings.model_fields
        if "polymarket" in name
        and any(part in name for part in ("key", "secret", "password", "token", "signer"))
    }
    assert not forbidden


def test_polymarket_package_has_no_signing_or_order_surface() -> None:
    hits: list[str] = []
    for path in POLYMARKET_SRC.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for needle in _FORBIDDEN_SOURCE:
            if needle.lower() not in text.lower():
                continue
            comment_ok = "never" in text.lower() or "not implemented" in text.lower()
            if comment_ok and needle in {"/order", "create_order", "post_order", "private_key"}:
                continue
            hits.append(f"{path.name}:{needle}")
    # Explicitly require the refuse-order helper to exist so this test is not
    # a false green if the client is deleted.
    clob = (POLYMARKET_SRC / "clob.py").read_text(encoding="utf-8")
    assert "assert_public_clob_path" in clob
    assert "There is intentionally no" in clob
    assert not [hit for hit in hits if "py_clob_client" in hit or "ClobClient" in hit]


def test_polymarket_clients_define_no_post_methods() -> None:
    for path in (POLYMARKET_SRC / "clob.py", POLYMARKET_SRC / "gamma.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        posts = [
            node.name
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name in {"post", "order", "submit"}
        ]
        assert posts == []


def test_crypto_paper_loop_does_not_import_polymarket() -> None:
    for path in CRYPTO_LOOP:
        text = path.read_text(encoding="utf-8")
        assert "polymarket" not in text.lower(), f"{path.name} must not reference polymarket"


@pytest.mark.asyncio
async def test_injected_transport_never_sees_a_non_get() -> None:
    methods: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        if request.url.path == "/events":
            return httpx.Response(200, json=[])
        if request.url.path == "/midpoint":
            return httpx.Response(200, json={"mid": "0.4"})
        raise AssertionError(f"unexpected path {request.url.path}")

    async with httpx.AsyncClient(
        base_url="https://example.invalid", transport=httpx.MockTransport(handler)
    ) as client:
        await GammaClient(client=client).list_weather_events(tag_slug="weather", limit=5)
        await ClobPublicClient(client=client).midpoint("tok")

    assert methods == ["GET", "GET"]
    assert "POST" not in methods
