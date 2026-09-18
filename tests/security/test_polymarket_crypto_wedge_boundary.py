"""Hard boundary for the #142 wedge tape: it can only withhold and observe.

The collector is adjacent to the intelligence plane (Crucix) and to two public
venues. None of that may become an authorisation: the Crucix gate can only
clear bits from a mask, the tape rows carry no size/side/notional, and neither
the collector nor the Deribit client has a trading surface.
"""

from __future__ import annotations

import ast
import itertools
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from traderstack.config import Settings
from traderstack.market.crucix import parse_crucix_alerts
from traderstack.market.deribit import DeribitPublicClient
from traderstack.polymarket.clob import ClobPublicClient
from traderstack.polymarket.crypto_gate import (
    apply_crucix_gate,
    crucix_status_from_snapshot,
    stand_aside,
)
from traderstack.polymarket.crypto_models import (
    DEFAULT_PROMOTE_FLAG,
    CrucixStatus,
    CryptoAsset,
    CryptoWedgeRow,
    WedgeRowStatus,
)
from traderstack.polymarket.gamma import GammaClient

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src" / "traderstack"
NEW_SOURCES = (
    SRC / "market" / "deribit.py",
    SRC / "polymarket" / "crypto_service.py",
    SRC / "polymarket" / "crypto_cli.py",
    SRC / "polymarket" / "crypto_eval.py",
    SRC / "polymarket" / "crypto_eval_cli.py",
    SRC / "polymarket" / "crypto_gate.py",
    SRC / "polymarket" / "option_implied.py",
)
CRYPTO_LOOP = (
    SRC / "cli.py",
    SRC / "service.py",
    SRC / "runtime.py",
    SRC / "pipeline.py",
    SRC / "risk.py",
    SRC / "execution" / "submitter.py",
)
FORBIDDEN_IMPORTS = (
    "traderstack.risk",
    "traderstack.pipeline",
    "traderstack.execution",
    "traderstack.runtime",
    "traderstack.service",
)


# --- the gate can only withhold ---------------------------------------------
def test_gate_output_is_always_a_subset_of_its_input() -> None:
    statuses = tuple(CrucixStatus)
    for bits in itertools.product((True, False), repeat=len(statuses)):
        gated = apply_crucix_gate(bits, statuses)
        assert len(gated) == len(bits)
        for before, after in zip(bits, gated, strict=True):
            assert not (after and not before), "the gate turned a False into a True"


def test_only_a_known_clear_survives_the_gate() -> None:
    for status in CrucixStatus:
        gated = apply_crucix_gate((True,), (status,))
        assert gated == ((status is CrucixStatus.CLEAR),)
        assert stand_aside(status) is (status is not CrucixStatus.CLEAR)


def test_unknown_is_not_clear() -> None:
    assert crucix_status_from_snapshot(None, configured=False) is CrucixStatus.NOT_CONFIGURED
    assert crucix_status_from_snapshot(None, configured=True) is CrucixStatus.UNAVAILABLE
    assert stand_aside(CrucixStatus.NOT_CONFIGURED)
    assert stand_aside(CrucixStatus.UNAVAILABLE)


def test_high_tier_alert_beats_an_explicit_adverse_false() -> None:
    snapshot = parse_crucix_alerts(
        {"alerts": [{"asset": "BTC", "tier": "high", "adverse": False}]}, asset="BTC"
    )
    assert crucix_status_from_snapshot(snapshot, configured=True) is CrucixStatus.ADVERSE
    assert apply_crucix_gate((True,), (CrucixStatus.ADVERSE,)) == (False,)


def test_mask_length_mismatch_is_refused() -> None:
    with pytest.raises(ValueError):
        apply_crucix_gate((True, True), (CrucixStatus.CLEAR,))


# --- the row is an observation, not an instruction ---------------------------
def test_wedge_row_has_no_instruction_shaped_field() -> None:
    forbidden = {"side", "size", "quantity", "notional", "limit", "paper_order", "leverage"}
    assert not forbidden & set(CryptoWedgeRow.model_fields)
    row = CryptoWedgeRow(
        status=WedgeRowStatus.OK,
        market_id="1",
        asset=CryptoAsset.BTC,
        strike_usd=1.0,
        resolves_at=datetime(2026, 9, 14, 16, tzinfo=UTC),
        observed_at=datetime(2026, 9, 14, 6, tzinfo=UTC),
        crucix_status=CrucixStatus.CLEAR,
    )
    assert row.venue_submitted is False
    assert row.execution == "paper_tape_only"
    assert row.trading_mode == "paper"


# --- isolation ---------------------------------------------------------------
def test_new_modules_never_import_the_risk_or_execution_plane() -> None:
    for path in NEW_SOURCES:
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text)
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
        for module in imported:
            assert not any(
                module == forbidden or module.startswith(f"{forbidden}.")
                for forbidden in FORBIDDEN_IMPORTS
            ), f"{path.name} imports {module}"


def test_crypto_paper_loop_references_neither_polymarket_nor_deribit() -> None:
    for path in CRYPTO_LOOP:
        text = path.read_text(encoding="utf-8").lower()
        assert "polymarket" not in text, f"{path.name} must not reference polymarket"
        assert "deribit" not in text, f"{path.name} must not reference deribit"


def test_new_modules_define_no_trading_surface() -> None:
    for path in NEW_SOURCES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        }
        assert not names & {"post", "order", "submit", "buy", "sell", "cancel", "sign"}


def test_deribit_client_keeps_its_refusal_helper() -> None:
    text = (SRC / "market" / "deribit.py").read_text(encoding="utf-8")
    assert "assert_public_deribit_path" in text
    assert "There is intentionally no method" in text


# --- settings surface ---------------------------------------------------------
def test_no_promote_pin_and_no_credential_like_new_field() -> None:
    assert DEFAULT_PROMOTE_FLAG.lower() not in Settings.model_fields
    assert not any("polymarket" in name and "promote" in name for name in Settings.model_fields)
    new_fields = [
        name
        for name in Settings.model_fields
        if name.startswith(("polymarket_crypto_", "deribit_"))
    ]
    assert new_fields
    assert not [
        name
        for name in new_fields
        if any(part in name for part in ("key", "secret", "password", "token", "signer"))
    ]


def test_new_settings_fields_are_not_risk_policy() -> None:
    from traderstack.policy_fields import NON_POLICY_FIELDS
    from traderstack.risk import CONTROL_PLANE_FIELDS, RISK_LIMIT_FIELDS

    for name in Settings.model_fields:
        if name.startswith(("polymarket_crypto_", "deribit_")):
            assert name in NON_POLICY_FIELDS
            assert name not in RISK_LIMIT_FIELDS
            assert name not in CONTROL_PLANE_FIELDS


# --- every venue call in one cycle is a GET -----------------------------------
async def test_all_three_venues_only_ever_see_get() -> None:
    methods: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        if request.url.path.endswith("get_instruments"):
            return httpx.Response(200, json={"result": []})
        if request.url.path.endswith("get_book_summary_by_currency"):
            return httpx.Response(200, json={"result": []})
        if request.url.path == "/events":
            return httpx.Response(200, json=[])
        if request.url.path == "/book":
            return httpx.Response(200, json={"bids": [], "asks": [], "timestamp": "0"})
        raise AssertionError(f"unexpected path {request.url.path}")

    async with httpx.AsyncClient(
        base_url="https://example.invalid", transport=httpx.MockTransport(handler)
    ) as client:
        await GammaClient(client=client).list_events_by_slug(slug="bitcoin-above-on-x")
        await ClobPublicClient(client=client).book("tok")
        deribit = DeribitPublicClient(client=client)
        await deribit.instruments("BTC")
        await deribit.book_summary("BTC")

    assert methods == ["GET"] * 4
    assert "POST" not in methods
