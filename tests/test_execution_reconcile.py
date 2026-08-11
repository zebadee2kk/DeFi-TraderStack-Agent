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

    assert await reconciler.reconcile(ledger, book) == 1
    assert await reconciler.reconcile(ledger, book) == 0
    await client.aclose()

    assert ledger.orders["o1"].state is OrderLifecycleState.FILLED
    assert book.snapshot().cash_usd == pytest.approx(9_000)
    assert book.snapshot().asset_exposure_usd["BTC"] == pytest.approx(1_000)
