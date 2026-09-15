"""The Deribit public client is GET-only and reduces untrusted rows (#142)."""

from datetime import UTC, datetime

import httpx
import pytest

from traderstack.market.deribit import (
    DeribitPublicClient,
    assert_public_deribit_path,
    reduce_book_summary,
    reduce_instruments,
)

_EXPIRY_MS = 1789372800000  # 2026-09-14T08:00:00Z
_CREATED_MS = 1789365570000  # 2026-09-14T05:59:30Z


def _instrument_row(**over: object) -> dict[str, object]:
    row: dict[str, object] = {
        "instrument_name": "BTC-14SEP26-74000-C",
        "kind": "option",
        "option_type": "call",
        "strike": 74000.0,
        "expiration_timestamp": _EXPIRY_MS,
    }
    row.update(over)
    return row


def _summary_row(**over: object) -> dict[str, object]:
    row: dict[str, object] = {
        "instrument_name": "BTC-14SEP26-74000-C",
        "mark_iv": 42.0,
        "mark_price": 0.031,
        "bid_price": 0.030,
        "ask_price": 0.032,
        "underlying_price": 76000.0,
        "underlying_index": "BTC-14SEP26",
        "creation_timestamp": _CREATED_MS,
    }
    row.update(over)
    return row


def test_instruments_reduce_to_bounded_typed_rows() -> None:
    rows = reduce_instruments({"result": [_instrument_row()]}, currency="btc")
    assert len(rows) == 1
    assert rows[0].currency == "BTC"
    assert rows[0].strike == 74000.0
    assert rows[0].option_type == "call"
    assert rows[0].expiry_at == datetime(2026, 9, 14, 8, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    "override",
    [
        {"strike": None},
        {"strike": -1},
        {"option_type": "future"},
        {"expiration_timestamp": 12},  # implausible epoch
        {"expiration_timestamp": "not-a-number"},
        {"instrument_name": ""},
    ],
)
def test_malformed_instrument_rows_are_dropped_not_guessed(override: dict[str, object]) -> None:
    assert reduce_instruments({"result": [_instrument_row(**override)]}, currency="BTC") == ()


def test_book_summary_reduces_and_keeps_null_sides() -> None:
    rows = reduce_book_summary({"result": [_summary_row(bid_price=None)]})
    assert len(rows) == 1
    assert rows[0].best_bid is None
    assert rows[0].best_ask == 0.032
    assert rows[0].mark_iv == 42.0
    assert rows[0].observed_at == datetime(2026, 9, 14, 5, 59, 30, tzinfo=UTC)


@pytest.mark.parametrize(
    "override",
    [
        {"mark_iv": -1.0},
        {"mark_iv": "x"},
        {"mark_price": None},
        {"underlying_price": 0},
        {"creation_timestamp": 5},
    ],
)
def test_malformed_summary_rows_are_dropped(override: dict[str, object]) -> None:
    assert reduce_book_summary({"result": [_summary_row(**override)]}) == ()


def test_non_list_result_raises() -> None:
    with pytest.raises(TypeError):
        reduce_book_summary({"result": {"instrument_name": "BTC-14SEP26-74000-C"}})
    with pytest.raises(TypeError):
        reduce_instruments({"result": "nope"}, currency="BTC")


@pytest.mark.parametrize(
    "path",
    [
        "/private/buy",
        "/private/sell",
        "/private/get_account_summary",
        "/public/auth",
        "/private/cancel_all",
        "/private/withdraw",
    ],
)
def test_private_and_trading_paths_are_refused(path: str) -> None:
    with pytest.raises(RuntimeError):
        assert_public_deribit_path(path)


def test_unknown_public_path_is_refused() -> None:
    with pytest.raises(RuntimeError):
        assert_public_deribit_path("/public/get_order_book")


def test_allowlisted_paths_pass() -> None:
    assert_public_deribit_path("/public/get_instruments")
    assert_public_deribit_path("/public/get_book_summary_by_currency")


async def test_client_issues_get_with_expected_params() -> None:
    seen: list[tuple[str, str, dict[str, str]]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path, dict(request.url.params)))
        if request.url.path.endswith("get_instruments"):
            return httpx.Response(200, json={"result": [_instrument_row()]})
        return httpx.Response(200, json={"result": [_summary_row()]})

    async with httpx.AsyncClient(
        base_url="https://example.invalid/api/v2", transport=httpx.MockTransport(handler)
    ) as client:
        deribit = DeribitPublicClient(client=client)
        instruments = await deribit.instruments("btc")
        quotes = await deribit.book_summary("BTC")

    assert len(instruments) == 1
    assert len(quotes) == 1
    assert [method for method, _, _ in seen] == ["GET", "GET"]
    assert seen[0][2] == {"currency": "BTC", "kind": "option", "expired": "false"}
    assert seen[1][2] == {"currency": "BTC", "kind": "option"}
    assert all(path.startswith("/api/v2/public/") for _, path, _ in seen)


async def test_blank_currency_is_rejected() -> None:
    with pytest.raises(ValueError):
        await DeribitPublicClient().instruments("  ")
    with pytest.raises(ValueError):
        await DeribitPublicClient().book_summary("")
