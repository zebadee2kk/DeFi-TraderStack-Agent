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


def _client(handler: object) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.MockTransport(handler),  # type: ignore[arg-type]
        base_url="http://test",
    )


def _state_handler(orders: list[dict[str, object]], trades: list[dict[str, object]]) -> object:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/trading/orders/search"):
            return httpx.Response(200, json=orders)
        if request.url.path.endswith("/trading/trades"):
            return httpx.Response(200, json=trades)
        return httpx.Response(404)

    return handler


@pytest.mark.asyncio
async def test_reconciler_flags_a_venue_that_disagrees_with_a_terminal_order() -> None:
    ledger = ExecutionLedger()
    ledger.register_order(
        ExecutionOrder(
            order_id="o1",
            decision_id="d1",
            asset="BTC",
            side=Side.BUY,
            requested_quantity=0.05,
            state=OrderLifecycleState.FILLED,
        )
    )
    book = InMemoryPortfolioBook(starting_nav_usd=10_000)
    client = _client(_state_handler([{"order_id": "o1", "status": "open"}], []))
    reconciler = HummingbotExecutionReconciler("http://test", "u", "p", client=client)

    result = await reconciler.reconcile_state(ledger, book)
    await client.aclose()

    assert not result.matched
    assert "filled locally but open at the venue" in result.conflicts[0]
    assert ledger.orders["o1"].state is OrderLifecycleState.FILLED


@pytest.mark.asyncio
async def test_reconciler_tolerates_a_venue_snapshot_that_lags_a_partial_fill() -> None:
    """A partially filled order is still 'open' at the venue; that is not drift."""

    ledger = ExecutionLedger()
    ledger.register_order(
        ExecutionOrder(
            order_id="o1",
            decision_id="d1",
            asset="BTC",
            side=Side.BUY,
            requested_quantity=0.10,
        )
    )
    book = InMemoryPortfolioBook(starting_nav_usd=10_000)
    trades = [
        {
            "trade_id": "f1",
            "order_id": "o1",
            "trading_pair": "BTC-USD",
            "trade_type": "BUY",
            "amount": 0.04,
            "price": 20_000,
        }
    ]
    client = _client(_state_handler([{"order_id": "o1", "status": "open"}], trades))
    reconciler = HummingbotExecutionReconciler("http://test", "u", "p", client=client)

    result = await reconciler.reconcile_state(ledger, book)
    await client.aclose()

    assert result.matched
    assert result.applied_fills == 1
    assert result.venue_orders == 1
    assert ledger.orders["o1"].state is OrderLifecycleState.PARTIALLY_FILLED


@pytest.mark.asyncio
async def test_reconciler_maps_expired_and_acknowledged_statuses() -> None:
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

    client = _client(_state_handler([{"order_id": "o1", "status": "acknowledged"}], []))
    reconciler = HummingbotExecutionReconciler("http://test", "u", "p", client=client)
    assert (await reconciler.reconcile_state(ledger, book)).matched
    assert ledger.orders["o1"].state is OrderLifecycleState.ACKNOWLEDGED
    await client.aclose()

    client = _client(_state_handler([{"order_id": "o1", "status": "expired"}], []))
    reconciler = HummingbotExecutionReconciler("http://test", "u", "p", client=client)
    assert (await reconciler.reconcile_state(ledger, book)).matched
    assert ledger.orders["o1"].state is OrderLifecycleState.EXPIRED
    await client.aclose()
