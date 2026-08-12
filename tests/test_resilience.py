from pathlib import Path

import httpx
import pytest

from traderstack.checkpoint import JsonPortfolioCheckpointStore
from traderstack.health import RuntimeHealth
from traderstack.models import Side
from traderstack.portfolio import InMemoryPortfolioBook
from traderstack.reconciliation import HummingbotPortfolioReconciler


@pytest.mark.asyncio
async def test_portfolio_checkpoint_round_trip(tmp_path: Path) -> None:
    book = InMemoryPortfolioBook(starting_nav_usd=10_000)
    book.apply_fill("BTC", Side.BUY, quantity=0.05, price_usd=20_000)
    store = JsonPortfolioCheckpointStore(tmp_path / "portfolio.json")

    await store.save(book)
    restored = await store.load()

    assert restored is not None
    assert restored.state() == book.state()


def test_runtime_health_becomes_unhealthy_at_threshold() -> None:
    health = RuntimeHealth(max_consecutive_errors=2)
    health.record_error("BTC/USD", RuntimeError("one"))
    assert health.healthy
    health.record_error("BTC/USD", RuntimeError("two"))
    assert not health.healthy
    health.record_success("BTC/USD")
    assert health.healthy


@pytest.mark.asyncio
async def test_hummingbot_reconciliation_detects_nav_drift() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/portfolio/state"
        return httpx.Response(
            200,
            json={
                "paper_account": {
                    "kraken_paper_trade": {
                        "USD": {"units": 8_000, "price": 1, "value": 8_000},
                        "BTC": {"units": 0.1, "price": 20_000, "value": 2_000},
                    }
                }
            },
        )

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://hummingbot",
    )
    reconciler = HummingbotPortfolioReconciler(
        base_url="http://hummingbot",
        username="user",
        password="pass",
        client=client,
        max_nav_difference_bps=25,
    )
    book = InMemoryPortfolioBook(starting_nav_usd=10_000)
    result = await reconciler.reconcile(book)
    assert result.matched

    book.apply_fill("BTC", Side.BUY, quantity=0.05, price_usd=20_000)
    book.mark("BTC", 18_000)
    result = await reconciler.reconcile(book)
    assert not result.matched
    assert result.nav_difference_bps > 25

    await client.aclose()


def test_health_trips_on_persistent_single_symbol_failure() -> None:
    health = RuntimeHealth(max_consecutive_errors=5)
    for cycle in range(5):
        health.record_success("BTC/USD")
        health.record_error("SOL/USD", RuntimeError(f"boom {cycle}"))
    assert health.symbol_consecutive_errors["SOL/USD"] == 5
    assert health.healthy is False


def test_health_symbol_counter_resets_on_success() -> None:
    health = RuntimeHealth(max_consecutive_errors=5)
    for _ in range(4):
        health.record_error("SOL/USD", RuntimeError("boom"))
    health.record_success("SOL/USD")
    for _ in range(4):
        health.record_error("SOL/USD", RuntimeError("boom"))
    assert health.healthy is True
