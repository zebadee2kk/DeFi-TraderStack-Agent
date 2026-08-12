import httpx
import pytest

from traderstack.execution.ledger import ExecutionLedger, ExecutionOrder, OrderLifecycleState
from traderstack.execution.reconcile import HummingbotExecutionReconciler
from traderstack.models import Side
from traderstack.portfolio import InMemoryPortfolioBook


@pytest.mark.asyncio
async def test_reconciler_applies_new_trades_once() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/trading/orders/search"):
            return httpx.Response(200, json=[{"order_id": "o1", "status": "filled"}])
        if request.url.path.endswith("/trading/trades"):
            return httpx.Response(
                200,
                json=[
                    {
                        "trade_id": "f1",
                        "order_id": "o1",
                        "trading_pair": "BTC-USD",
                        "trade_type": "BUY",
                        "amount": 0.05,
                        "price": 20_000,
                        "fee": 1.0,
                    }
                ],
            )
        return httpx.Response(404)

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
    book = InMemoryPortfolioBook(starting_nav_usd=10_000)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://test")
    reconciler = HummingbotExecutionReconciler(
        base_url="http://test",
        username="u",
        password="p",
        client=client,
    )

    assert (await reconciler.reconcile(ledger, book)).applied_fills == 1
    assert (await reconciler.reconcile(ledger, book)).applied_fills == 0
    await client.aclose()

    assert ledger.orders["o1"].state is OrderLifecycleState.FILLED
    assert book.snapshot().cash_usd == pytest.approx(9_000)
    assert book.snapshot().asset_exposure_usd["BTC"] == pytest.approx(1_000)


def test_number_coercion_rejects_non_finite_strings() -> None:
    with pytest.raises(ValueError, match="missing numeric field"):
        HummingbotExecutionReconciler._number({"price": "1e999"}, "price")
    with pytest.raises(ValueError, match="missing numeric field"):
        HummingbotExecutionReconciler._number({"price": float("inf")}, "price")
    assert HummingbotExecutionReconciler._number({"fee": "1e999"}, "fee", required=False) == 0.0
    assert HummingbotExecutionReconciler._number({"price": "101.5"}, "price") == 101.5


def _reconciler_with(payloads: dict[str, object]) -> tuple[HummingbotExecutionReconciler, httpx.AsyncClient]:
    def handler(request: httpx.Request) -> httpx.Response:
        for suffix, payload in payloads.items():
            if request.url.path.endswith(suffix):
                return httpx.Response(200, json=payload)
        return httpx.Response(404)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://test")
    return (
        HummingbotExecutionReconciler(
            base_url="http://test", username="u", password="p", client=client
        ),
        client,
    )


@pytest.mark.asyncio
async def test_orphan_fills_are_skipped_not_fatal() -> None:
    trades = [
        {
            "trade_id": "hist-1",
            "order_id": "unknown-order",
            "trading_pair": "BTC-USD",
            "trade_type": "BUY",
            "amount": 0.1,
            "price": 20_000,
        },
        {
            "trade_id": "f1",
            "order_id": "o1",
            "trading_pair": "BTC-USD",
            "trade_type": "BUY",
            "amount": 0.05,
            "price": 20_000,
        },
    ]
    reconciler, client = _reconciler_with({"/trading/orders/search": [], "/trading/trades": trades})
    ledger = ExecutionLedger()
    ledger.register_order(
        ExecutionOrder(
            order_id="o1", decision_id="d1", asset="BTC", side=Side.BUY, requested_quantity=0.05
        )
    )
    book = InMemoryPortfolioBook(starting_nav_usd=10_000)

    outcome = await reconciler.reconcile(ledger, book)
    await client.aclose()

    assert outcome.skipped_orphan_fills == 1
    assert outcome.applied_fills == 1
    assert book.snapshot().asset_exposure_usd["BTC"] == pytest.approx(1_000)


@pytest.mark.asyncio
async def test_failed_apply_does_not_consume_fill_id() -> None:
    trades = [
        {
            "trade_id": "s1",
            "order_id": "o-sell",
            "trading_pair": "BTC-USD",
            "trade_type": "SELL",
            "amount": 0.05,
            "price": 20_000,
        }
    ]
    reconciler, client = _reconciler_with({"/trading/orders/search": [], "/trading/trades": trades})
    ledger = ExecutionLedger()
    ledger.register_order(
        ExecutionOrder(
            order_id="o-sell", decision_id="d1", asset="BTC", side=Side.SELL, requested_quantity=0.05
        )
    )
    book = InMemoryPortfolioBook(starting_nav_usd=10_000)

    with pytest.raises(ValueError, match="cannot sell more"):
        await reconciler.reconcile(ledger, book)
    assert "s1" not in ledger.processed_fill_ids

    book.apply_fill("BTC", Side.BUY, quantity=0.05, price_usd=20_000)
    outcome = await reconciler.reconcile(ledger, book)
    await client.aclose()

    assert outcome.applied_fills == 1
    assert "s1" in ledger.processed_fill_ids
    assert book.positions["BTC"].quantity == pytest.approx(0)
