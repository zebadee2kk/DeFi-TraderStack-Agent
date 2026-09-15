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


# --- polymarket weather PIT tape (#141) ---

from datetime import date, timedelta

from traderstack.polymarket.cities import CITY_CATALOG
from traderstack.polymarket.models import TemperatureContract
from traderstack.polymarket.stations import (
    GhcnDailyClient,
    IemAsosClient,
    resolve_official_high,
)
from traderstack.polymarket.tape import (
    PolymarketWeatherTape,
    ResolvedTapeRow,
    TapeObservation,
    local_close_at,
    to_resolved_weather_rows,
)

_TAPE_MODULES = ("collect_cli.py", "resolve_cli.py", "tape.py", "stations.py")


def _tape_observation(**overrides: object) -> TapeObservation:
    city = CITY_CATALOG["miami"]
    event_date = date(2026, 9, 14)
    close_at = local_close_at(city, event_date)
    observed_at = close_at - timedelta(hours=4)
    payload: dict[str, object] = {
        "event_id": "evt",
        "market_id": "mkt",
        "city_slug": "miami",
        "station_icao": "KMIA",
        "event_date": event_date,
        "contract": TemperatureContract.BUCKET,
        "bucket_low_f": 88.0,
        "bucket_high_f": 89.0,
        "yes_token_id": "yes",
        "no_token_id": "no",
        "observed_at": observed_at,
        "clob_mid": 0.4,
        "best_bid": 0.38,
        "best_ask": 0.42,
        "half_spread": 0.02,
        "forecast_high_f": 88.5,
        "forecast_issued_at": observed_at,
        "close_at": close_at,
        "lead_hours": 4.0,
    }
    payload.update(overrides)
    return TapeObservation(**payload)  # type: ignore[arg-type]


def test_tape_modules_define_no_post_methods() -> None:
    for name in _TAPE_MODULES:
        tree = ast.parse((POLYMARKET_SRC / name).read_text(encoding="utf-8"))
        posts = [
            node.name
            for node in ast.walk(tree)
            if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef)
            and node.name in {"post", "order", "submit", "sign", "place_order"}
        ]
        assert posts == [], f"{name} defines {posts}"


@pytest.mark.asyncio
async def test_injected_transport_never_sees_a_non_get_on_the_tape_clients() -> None:
    methods: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        if request.url.path == "/events/keyset":
            return httpx.Response(200, json={"events": [], "next_cursor": None})
        if request.url.path == "/book":
            return httpx.Response(
                200,
                json={
                    "bids": [{"price": "0.30", "size": "1"}],
                    "asks": [{"price": "0.32", "size": "1"}],
                },
            )
        if request.url.path == "/cgi-bin/request/daily.py":
            return httpx.Response(200, text="station,day,max_temp_f\nMIA,2026-09-14,88.0\n")
        if request.url.path == "/access/services/data/v1":
            return httpx.Response(
                200, json=[{"DATE": "2026-09-14", "STATION": "USW00012839", "TMAX": "88"}]
            )
        raise AssertionError(f"unexpected path {request.url.path}")

    async with httpx.AsyncClient(
        base_url="https://example.invalid", transport=httpx.MockTransport(handler)
    ) as client:
        await GammaClient(client=client).list_weather_events_keyset(tag_slug="weather", limit=5)
        await ClobPublicClient(client=client).book_top("tok")
        await resolve_official_high(
            CITY_CATALOG["miami"],
            date(2026, 9, 14),
            iem=IemAsosClient(client=client),
            ghcn=GhcnDailyClient(client=client),
        )

    assert set(methods) == {"GET"}


def test_resolver_refuses_settlement_and_post_close_observations() -> None:
    # A Gamma settlement price is not a station high: without one, the row is
    # dropped rather than scored off `outcomePrices`.
    observation = _tape_observation()
    unmatched = ResolvedTapeRow(
        **observation.model_dump(),
        official_high_f=0.0,
        station_id="",
        resolution_source="missing",
        resolved_at=observation.close_at,
    )
    rows, drops = to_resolved_weather_rows([unmatched], print_id="p")
    assert rows == ()
    assert drops == {"station_unmatched": 1}

    # An observation taken after the local close is look-ahead, both at the
    # writer and at the converter.
    late = ResolvedTapeRow(
        **observation.model_dump(),
        official_high_f=88.0,
        station_id="KMIA",
        resolution_source="iem_asos",
        resolved_at=observation.close_at,
    ).model_copy(update={"observed_at": observation.close_at + timedelta(minutes=1)})
    rows, drops = to_resolved_weather_rows([late], print_id="p")
    assert rows == ()
    assert drops == {"lookahead_observation": 1}


def test_tape_writer_refuses_non_paper_and_post_close_rows(tmp_path) -> None:
    tape = PolymarketWeatherTape(tmp_path / "tape.jsonl")
    observation = _tape_observation()
    with pytest.raises(RuntimeError):
        tape.append_sync(observation.model_copy(update={"observed_at": observation.close_at}))
    assert not (tmp_path / "tape.jsonl").exists()


def test_tape_paths_are_isolated_from_the_crypto_audit_trail() -> None:
    settings = Settings()
    research = {
        settings.polymarket_weather_tape_path,
        settings.polymarket_weather_resolved_path,
    }
    crypto = {settings.risk_audit_path, settings.audit_anchor_path}
    assert research.isdisjoint(crypto)
    collector = (POLYMARKET_SRC / "collect_cli.py").read_text(encoding="utf-8")
    resolver = (POLYMARKET_SRC / "resolve_cli.py").read_text(encoding="utf-8")
    for text in (collector, resolver):
        assert "risk_audit" not in text
        assert "execution_ledger" not in text
        assert "kill_switch" not in text.replace("kill switch", "")


def test_tape_settings_add_no_credential_or_promote_fields() -> None:
    for name in Settings.model_fields:
        if not name.startswith("polymarket_weather"):
            continue
        assert not any(part in name for part in ("key", "secret", "password", "token", "signer"))
    assert "paper_promote_polymarket_weather" not in Settings.model_fields


def test_new_tape_console_scripts_are_paper_only() -> None:
    pyproject = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    assert "traderstack-polymarket-weather-collect" in pyproject
    assert "traderstack-polymarket-weather-resolve" in pyproject
    for name in ("collect_cli.py", "resolve_cli.py"):
        text = (POLYMARKET_SRC / name).read_text(encoding="utf-8")
        assert "require_paper_trading_mode" in text


def test_collector_never_writes_the_paper_intent_ledger() -> None:
    collector = (POLYMARKET_SRC / "collect_cli.py").read_text(encoding="utf-8")
    assert "PolymarketWeatherPaperLedger" not in collector
    assert "PaperIntent" not in collector
