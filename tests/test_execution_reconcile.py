import httpx
import pytest

from traderstack.execution.ledger import (
    ExecutionFill,
    ExecutionLedger,
    ExecutionOrder,
    FeeSource,
    OrderLifecycleState,
)
from traderstack.execution.paper_fill import paper_fill_id
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
    assert ledger.orders["o1"].fees_paid_usd == pytest.approx(1.0)
    assert ledger.orders["o1"].fee_source is FeeSource.VENUE
    # Venue fee of $1 is debited from cash; NAV falls by the fee.
    assert book.snapshot().cash_usd == pytest.approx(8_999)
    assert book.snapshot().asset_exposure_usd["BTC"] == pytest.approx(1_000)
    assert book.snapshot().nav_usd == pytest.approx(9_999)


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


@pytest.mark.asyncio
async def test_missing_venue_fee_is_modelled_and_labelled() -> None:
    """Paper connectors often omit fee; PAPER_FEE_BPS still hits the book."""

    trades = [
        {
            "trade_id": "f1",
            "order_id": "o1",
            "trading_pair": "BTC-USD",
            "trade_type": "BUY",
            "amount": 0.05,
            "price": 20_000,
        }
    ]
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
    client = _client(_state_handler([{"order_id": "o1", "status": "filled"}], trades))
    reconciler = HummingbotExecutionReconciler(
        "http://test", "u", "p", client=client, paper_fee_bps=10.0
    )

    result = await reconciler.reconcile_state(ledger, book)
    await client.aclose()

    modelled = 0.05 * 20_000 * 10.0 / 10_000
    assert result.applied_fills == 1
    fill_order = ledger.orders["o1"]
    assert fill_order.fees_paid_usd == pytest.approx(modelled)
    assert fill_order.fee_source is FeeSource.MODELLED
    assert book.snapshot().nav_usd == pytest.approx(10_000 - modelled)
    assert book.snapshot().cash_usd == pytest.approx(9_000 - modelled)


@pytest.mark.asyncio
async def test_local_paper_fill_is_not_double_applied_by_venue_lag() -> None:
    """A paper-simulated FILLED order must not conflict with an still-open venue row."""

    ledger = ExecutionLedger()
    ledger.register_order(
        ExecutionOrder(
            order_id="ts-abc",
            decision_id="d1",
            asset="BTC",
            side=Side.BUY,
            requested_quantity=0.05,
            state=OrderLifecycleState.PLANNED,
            client_order_id="ts-abc",
            venue_order_id="venue-1",
        )
    )
    book = InMemoryPortfolioBook(starting_nav_usd=10_000)
    assert ledger.record_fill(
        ExecutionFill(
            fill_id=paper_fill_id("ts-abc"),
            order_id="ts-abc",
            asset="BTC",
            side=Side.BUY,
            quantity=0.05,
            price_usd=20_000,
            fee_usd=1.0,
            fee_source=FeeSource.MODELLED,
        )
    )
    book.apply_fill("BTC", Side.BUY, 0.05, 20_000, fee_usd=1.0)
    nav_after = book.nav_usd

    trades = [
        {
            "trade_id": "venue-f1",
            "order_id": "venue-1",
            "trading_pair": "BTC-USD",
            "trade_type": "BUY",
            "amount": 0.05,
            "price": 20_000,
            "fee": 1.0,
        }
    ]
    client = _client(_state_handler([{"order_id": "venue-1", "status": "open"}], trades))
    reconciler = HummingbotExecutionReconciler("http://test", "u", "p", client=client)

    result = await reconciler.reconcile_state(ledger, book)
    await client.aclose()

    assert result.applied_fills == 0
    assert result.matched
    assert book.nav_usd == pytest.approx(nav_after)
    assert ledger.orders["ts-abc"].state is OrderLifecycleState.FILLED
