"""Invariants 5 and 7: a hostile or malformed venue response must fail closed.

Two confirmed defects are covered here:

* SEC-2026-09-01 -- a trades row carrying a non-finite number (`1e400` parses as
  `Infinity` in JSON, and `"inf"`/`"nan"` parse as floats) was applied to the
  portfolio, driving cash to -Infinity and NAV to NaN. Every later
  `PortfolioSnapshot` then failed validation, so the service died with a
  poisoned checkpoint already written to disk.
* SEC-2026-09-02 -- `_rows` turned an envelope it could not read into an empty
  row list, so `venue_knows_order` answered "the venue has never seen this
  order" and the submitter resubmitted an order the venue may already hold.
"""

from __future__ import annotations

import json

import httpx
import pytest

from traderstack.execution.ledger import ExecutionFill, ExecutionLedger, ExecutionOrder
from traderstack.execution.reconcile import HummingbotExecutionReconciler
from traderstack.models import Side
from traderstack.portfolio import InMemoryPortfolioBook

NON_FINITE_JSON = ("1e400", "-1e400", "NaN", "Infinity", '"inf"', '"nan"', '"-Infinity"')


def _reconciler(client: httpx.AsyncClient) -> HummingbotExecutionReconciler:
    return HummingbotExecutionReconciler("http://test", "u", "p", client=client)


def _ledger() -> ExecutionLedger:
    ledger = ExecutionLedger()
    ledger.register_order(
        ExecutionOrder(
            order_id="o1",
            decision_id="d1",
            asset="BTC",
            side=Side.BUY,
            requested_quantity=0.05,
        )
    )
    return ledger


def _trades_handler(raw_body: str):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/trading/orders/search"):
            return httpx.Response(200, json=[])
        if request.url.path.endswith("/trading/trades"):
            return httpx.Response(
                200, content=raw_body.encode(), headers={"content-type": "application/json"}
            )
        return httpx.Response(404)

    return handler


@pytest.mark.parametrize("literal", NON_FINITE_JSON)
@pytest.mark.parametrize("field", ["price", "amount", "fee"])
@pytest.mark.asyncio
async def test_a_non_finite_venue_number_never_reaches_the_portfolio(
    literal: str, field: str
) -> None:
    row: dict[str, object] = {
        "trade_id": "f1",
        "order_id": "o1",
        "trading_pair": "BTC-USD",
        "trade_type": "BUY",
        "amount": 0.05,
        "price": 20_000,
        "fee": 1.0,
    }
    body = json.dumps([row])
    body = body.replace(f'"{field}": {json.dumps(row[field])}', f'"{field}": {literal}')
    assert literal in body

    ledger = _ledger()
    book = InMemoryPortfolioBook(starting_nav_usd=10_000)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(_trades_handler(body)), base_url="http://test"
    ) as client:
        with pytest.raises(ValueError):
            await _reconciler(client).reconcile_state(ledger, book)

    # The book is untouched and still produces a valid snapshot.
    assert book.cash_usd == 10_000
    assert book.nav_usd == 10_000
    assert book.snapshot().nav_usd == 10_000
    assert ledger.processed_fill_ids == set()


def test_execution_fill_rejects_non_finite_quantities_and_prices() -> None:
    for kwargs in (
        {"quantity": float("inf")},
        {"quantity": float("nan")},
        {"price_usd": float("inf")},
        {"price_usd": float("nan")},
        {"fee_usd": float("inf")},
    ):
        with pytest.raises(ValueError):
            ExecutionFill(
                fill_id="f",
                order_id="o1",
                asset="BTC",
                side=Side.BUY,
                **{"quantity": 1.0, "price_usd": 1.0, **kwargs},  # type: ignore[arg-type]
            )


@pytest.mark.parametrize(
    "payload",
    [
        {"data": {"o1": {"order_id": "o1"}}},
        {"orders": "not-a-list"},
        {"trades": None},
        {"unexpected": "envelope"},
        {},
        {"detail": "internal error"},
    ],
)
@pytest.mark.asyncio
async def test_an_unreadable_orders_envelope_is_unknown_state_not_an_empty_venue(
    payload: dict[str, object],
) -> None:
    """`venue_knows_order` returning False licenses a resubmission, so an
    envelope we cannot read must raise instead of reading as "no orders"."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://test"
    ) as client:
        with pytest.raises(TypeError):
            await _reconciler(client).venue_knows_order(
                ExecutionLedger(),
                client_order_id="ts-unknown",
                trading_pair="BTC-USD",
                trade_type="BUY",
                quantity=0.05,
            )


@pytest.mark.asyncio
async def test_a_genuinely_empty_venue_still_answers_no() -> None:
    """The fix must not turn a real "no open orders" answer into an error."""

    for payload in ([], {"data": []}, {"orders": []}, {"trades": []}):

        def handler(request: httpx.Request, body: object = payload) -> httpx.Response:
            return httpx.Response(200, json=body)

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url="http://test"
        ) as client:
            assert not await _reconciler(client).venue_knows_order(
                ExecutionLedger(),
                client_order_id="ts-unknown",
                trading_pair="BTC-USD",
                trade_type="BUY",
                quantity=0.05,
            )


@pytest.mark.asyncio
async def test_a_replayed_fill_id_is_applied_exactly_once() -> None:
    row = {
        "trade_id": "f1",
        "order_id": "o1",
        "trading_pair": "BTC-USD",
        "trade_type": "BUY",
        "amount": 0.02,
        "price": 20_000,
        "fee": 0.0,
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/trading/orders/search"):
            return httpx.Response(200, json=[])
        if request.url.path.endswith("/trading/trades"):
            # The same fill id repeated inside one page, then again next pass.
            return httpx.Response(200, json=[row, dict(row), dict(row)])
        return httpx.Response(404)

    ledger = _ledger()
    book = InMemoryPortfolioBook(starting_nav_usd=10_000)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://test"
    ) as client:
        reconciler = _reconciler(client)
        assert (await reconciler.reconcile_state(ledger, book)).applied_fills == 1
        assert (await reconciler.reconcile_state(ledger, book)).applied_fills == 0

    assert book.cash_usd == pytest.approx(10_000 - 0.02 * 20_000)
    assert ledger.orders["o1"].filled_quantity == pytest.approx(0.02)


@pytest.mark.asyncio
async def test_a_spoofed_order_id_cannot_overfill_or_flip_a_known_order() -> None:
    ledger = _ledger()
    book = InMemoryPortfolioBook(starting_nav_usd=10_000)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/trading/orders/search"):
            return httpx.Response(200, json=[])
        if request.url.path.endswith("/trading/trades"):
            return httpx.Response(
                200,
                json=[
                    {
                        "trade_id": "spoof",
                        "order_id": "o1",
                        "trading_pair": "BTC-USD",
                        "trade_type": "BUY",
                        "amount": 1_000.0,  # far beyond the 0.05 we asked for
                        "price": 20_000,
                    }
                ],
            )
        return httpx.Response(404)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://test"
    ) as client:
        with pytest.raises(ValueError, match="overfills"):
            await _reconciler(client).reconcile_state(ledger, book)
    assert book.cash_usd == 10_000

    # A fill claiming the wrong side or asset for a known order is refused too.
    for bad in (
        {"side": Side.SELL, "asset": "BTC"},
        {"side": Side.BUY, "asset": "ETH"},
    ):
        with pytest.raises(ValueError, match="does not match order"):
            ledger.record_fill(
                ExecutionFill(
                    fill_id=f"x-{bad['asset']}-{bad['side']}",
                    order_id="o1",
                    quantity=0.01,
                    price_usd=20_000,
                    **bad,  # type: ignore[arg-type]
                )
            )


@pytest.mark.asyncio
async def test_an_orphan_fill_referencing_an_unknown_order_is_refused() -> None:
    ledger = ExecutionLedger()
    with pytest.raises(KeyError, match="orphan fill"):
        ledger.record_fill(
            ExecutionFill(
                fill_id="f1",
                order_id="never-planned",
                asset="BTC",
                side=Side.BUY,
                quantity=0.01,
                price_usd=20_000,
            )
        )
    assert ledger.processed_fill_ids == set()
