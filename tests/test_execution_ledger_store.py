from pathlib import Path

import httpx
import pytest

from traderstack.execution.hummingbot import HummingbotPaperExecutor
from traderstack.execution.ledger import ExecutionLedger, ExecutionOrder, OrderLifecycleState
from traderstack.execution.ledger_store import JsonExecutionLedgerStore
from traderstack.execution.planner import ExecutionPlanner, client_order_id_for
from traderstack.execution.submitter import IdempotentSubmitter, SubmissionStatus
from traderstack.models import Side
from traderstack.pipeline import PaperOrderIntent


def intent(decision_id: str = "decision-1") -> PaperOrderIntent:
    return PaperOrderIntent(
        decision_id=decision_id,
        asset="BTC",
        side=Side.BUY,
        notional_usd=1_000,
        venue="kraken_paper_trade",
    )


def submitter(
    ledger: ExecutionLedger,
    client: httpx.AsyncClient,
    store: JsonExecutionLedgerStore | None = None,
) -> IdempotentSubmitter:
    return IdempotentSubmitter(
        executor=HummingbotPaperExecutor("http://hummingbot", "u", "p", client=client),
        ledger=ledger,
        planner=ExecutionPlanner(lot_step=0.001, min_notional_usd=10),
        ledger_store=store,
        max_retries=0,
    )


@pytest.mark.asyncio
async def test_store_round_trips_ledger_state(tmp_path: Path) -> None:
    ledger = ExecutionLedger()
    ledger.register_order(
        ExecutionOrder(
            order_id="ts-abc",
            decision_id="d1",
            asset="BTC",
            side=Side.BUY,
            requested_quantity=0.05,
            state=OrderLifecycleState.SUBMISSION_UNCERTAIN,
            client_order_id="ts-abc",
            venue_order_id=None,
            correlation_id="corr-1",
            submission_attempts=1,
            reason="submission timed out after 10s",
        )
    )
    ledger.processed_fill_ids.add("f1")

    store = JsonExecutionLedgerStore(tmp_path / "state" / "execution_ledger.json")
    assert await store.load() is None
    await store.save(ledger)

    restored = await store.load()
    assert restored is not None
    assert restored.state() == ledger.state()
    order = restored.orders["ts-abc"]
    assert order.state is OrderLifecycleState.SUBMISSION_UNCERTAIN
    assert order.submission_attempts == 1
    assert order.reason == "submission timed out after 10s"
    assert restored.processed_fill_ids == {"f1"}


@pytest.mark.asyncio
async def test_restart_with_pending_order_does_not_resubmit(tmp_path: Path) -> None:
    """The ledger is what stops a live order being submitted twice across restarts."""

    posts: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        posts.append(str(request.url))
        return httpx.Response(
            201,
            json={
                "order_id": "venue-1",
                "account_name": "paper_account",
                "connector_name": "kraken_paper_trade",
                "trading_pair": "BTC-USD",
                "trade_type": "BUY",
                "amount": 0.05,
                "order_type": "MARKET",
                "price": 20_000,
                "status": "submitted",
            },
        )

    store = JsonExecutionLedgerStore(tmp_path / "execution_ledger.json")
    transport = httpx.MockTransport(handler)

    async with httpx.AsyncClient(base_url="http://hummingbot", transport=transport) as client:
        first = await submitter(ExecutionLedger(), client, store).submit(
            intent(), execution_price_usd=20_000, reference_price_usd=20_000
        )
    assert first.status is SubmissionStatus.SUBMITTED
    assert len(posts) == 1

    # Process restart: a brand new ledger loaded from disk.
    reloaded = await store.load()
    assert reloaded is not None
    assert reloaded.orders[client_order_id_for("decision-1")].state is OrderLifecycleState.SUBMITTED

    async with httpx.AsyncClient(base_url="http://hummingbot", transport=transport) as client:
        second = await submitter(reloaded, client, store).submit(
            intent(), execution_price_usd=20_000, reference_price_usd=20_000
        )

    assert second.status is SubmissionStatus.DUPLICATE
    assert second.receipt is None
    assert len(posts) == 1, "the same decision must never reach the venue twice"


@pytest.mark.asyncio
async def test_restart_with_uncertain_order_does_not_resubmit_without_a_reconciler(
    tmp_path: Path,
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out", request=request)

    store = JsonExecutionLedgerStore(tmp_path / "execution_ledger.json")
    transport = httpx.MockTransport(handler)

    async with httpx.AsyncClient(base_url="http://hummingbot", transport=transport) as client:
        first = await submitter(ExecutionLedger(), client, store).submit(
            intent(), execution_price_usd=20_000, reference_price_usd=20_000
        )
    assert first.status is SubmissionStatus.UNCERTAIN

    reloaded = await store.load()
    assert reloaded is not None
    order = reloaded.orders[client_order_id_for("decision-1")]
    assert order.state is OrderLifecycleState.SUBMISSION_UNCERTAIN

    posts: list[str] = []

    async def counting_handler(request: httpx.Request) -> httpx.Response:
        posts.append(str(request.url))
        raise httpx.TimeoutException("timed out", request=request)

    async with httpx.AsyncClient(
        base_url="http://hummingbot", transport=httpx.MockTransport(counting_handler)
    ) as client:
        second = await submitter(reloaded, client, store).submit(
            intent(), execution_price_usd=20_000, reference_price_usd=20_000
        )

    assert second.status is SubmissionStatus.UNCERTAIN
    assert "no reconciler" in (second.reason or "")
    assert posts == [], "no retry is permitted before reconciliation"
