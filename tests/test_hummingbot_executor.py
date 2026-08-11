from uuid import uuid4

import httpx
import pytest

from traderstack.execution.hummingbot import ExecutionSafetyError, HummingbotPaperExecutor
from traderstack.models import Side
from traderstack.pipeline import PaperOrderIntent


def intent() -> PaperOrderIntent:
    return PaperOrderIntent(
        decision_id=str(uuid4()),
        asset="BTC",
        side=Side.BUY,
        notional_usd=100,
        venue="kraken_paper_trade",
    )


def test_build_request_converts_notional_to_base_amount() -> None:
    executor = HummingbotPaperExecutor("http://localhost:8000", "user", "pass")
    order = executor.build_request(intent(), execution_price_usd=50_000)
    assert order.connector_name == "kraken_paper_trade"
    assert order.trading_pair == "BTC-USD"
    assert order.trade_type == "BUY"
    assert order.amount == pytest.approx(0.002)
    assert order.order_type == "MARKET"


def test_executor_rejects_live_mode() -> None:
    executor = HummingbotPaperExecutor("http://localhost:8000", "user", "pass")
    with pytest.raises(ExecutionSafetyError, match="outside paper mode"):
        executor.build_request(intent(), execution_price_usd=50_000, trading_mode="live")


def test_executor_rejects_non_paper_connector() -> None:
    executor = HummingbotPaperExecutor(
        "http://localhost:8000", "user", "pass", connector_name="kraken"
    )
    bad_intent = intent().model_copy(update={"venue": "kraken"})
    with pytest.raises(ExecutionSafetyError, match="_paper_trade"):
        executor.build_request(bad_intent, execution_price_usd=50_000)


@pytest.mark.asyncio
async def test_submit_maps_201_receipt() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/trading/orders"
        payload = __import__("json").loads(request.content)
        assert payload["connector_name"] == "kraken_paper_trade"
        assert payload["trading_pair"] == "BTC-USD"
        assert payload["order_type"] == "MARKET"
        assert payload["position_action"] == "OPEN"
        return httpx.Response(
            201,
            json={
                "order_id": "paper-order-1",
                "account_name": "paper_account",
                "connector_name": "kraken_paper_trade",
                "trading_pair": "BTC-USD",
                "trade_type": "BUY",
                "amount": 0.002,
                "order_type": "MARKET",
                "price": None,
                "status": "submitted",
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(base_url="http://hummingbot", transport=transport) as client:
        executor = HummingbotPaperExecutor(
            "http://hummingbot", "user", "pass", client=client
        )
        receipt = await executor.submit(intent(), execution_price_usd=50_000)
    assert receipt.order_id == "paper-order-1"
    assert receipt.status == "submitted"


@pytest.mark.asyncio
async def test_submit_fails_closed_on_http_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"detail": "failure"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(base_url="http://hummingbot", transport=transport) as client:
        executor = HummingbotPaperExecutor(
            "http://hummingbot", "user", "pass", client=client
        )
        with pytest.raises(ExecutionSafetyError, match="HTTP 500"):
            await executor.submit(intent(), execution_price_usd=50_000)
