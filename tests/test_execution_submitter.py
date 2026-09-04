import asyncio

import httpx
import pytest

from traderstack.execution.hummingbot import HummingbotPaperExecutor
from traderstack.execution.ledger import ExecutionLedger, OrderLifecycleState
from traderstack.execution.planner import ExecutionPlanner, client_order_id_for
from traderstack.execution.reconcile import HummingbotExecutionReconciler
from traderstack.execution.submitter import IdempotentSubmitter, SubmissionStatus
from traderstack.models import Side
from traderstack.pipeline import PaperOrderIntent

RECEIPT = {
    "order_id": "venue-1",
    "account_name": "paper_account",
    "connector_name": "kraken_paper_trade",
    "trading_pair": "BTC-USD",
    "trade_type": "BUY",
    "amount": 0.05,
    "order_type": "MARKET",
    "price": 20_000,
    "status": "submitted",
}


def intent(decision_id: str = "decision-1") -> PaperOrderIntent:
    return PaperOrderIntent(
        decision_id=decision_id,
        asset="BTC",
        side=Side.BUY,
        notional_usd=1_000,
        venue="kraken_paper_trade",
    )


class RecordingResolver:
    """Stands in for the venue-state reconciliation pass."""

    def __init__(self, *answers: bool | Exception) -> None:
        self.answers = list(answers)
        self.calls: list[str] = []

    async def venue_knows_order(
        self,
        ledger: ExecutionLedger,
        *,
        client_order_id: str,
        trading_pair: str,
        trade_type: str,
        quantity: float,
    ) -> bool:
        self.calls.append(client_order_id)
        answer = self.answers.pop(0) if self.answers else False
        if isinstance(answer, Exception):
            raise answer
        return answer


def build(
    ledger: ExecutionLedger,
    client: httpx.AsyncClient,
    *,
    resolver: object | None = None,
    max_retries: int = 2,
) -> tuple[IdempotentSubmitter, list[float]]:
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    submitter = IdempotentSubmitter(
        executor=HummingbotPaperExecutor("http://hummingbot", "u", "p", client=client),
        ledger=ledger,
        planner=ExecutionPlanner(lot_step=0.001, min_notional_usd=10),
        resolver=resolver,  # type: ignore[arg-type]
        max_retries=max_retries,
        backoff_seconds=0.5,
        backoff_multiplier=2.0,
        sleep=fake_sleep,
    )
    return submitter, slept


@pytest.mark.asyncio
async def test_successful_submission_sends_the_client_order_id() -> None:
    payloads: list[dict[str, object]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        import json

        payloads.append(json.loads(request.content))
        return httpx.Response(201, json=RECEIPT)

    ledger = ExecutionLedger()
    async with httpx.AsyncClient(
        base_url="http://hummingbot", transport=httpx.MockTransport(handler)
    ) as client:
        submitter, _ = build(ledger, client)
        outcome = await submitter.submit(
            intent(), execution_price_usd=20_000, reference_price_usd=20_000
        )

    expected_id = client_order_id_for("decision-1")
    assert outcome.status is SubmissionStatus.SUBMITTED
    assert payloads[0]["client_order_id"] == expected_id
    assert payloads[0]["amount"] == pytest.approx(0.05)

    order = ledger.orders[expected_id]
    assert order.state is OrderLifecycleState.SUBMITTED
    assert order.venue_order_id == "venue-1"
    assert order.correlation_id is not None
    assert order.submission_attempts == 1


@pytest.mark.asyncio
async def test_duplicate_decision_is_never_resubmitted() -> None:
    posts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal posts
        posts += 1
        return httpx.Response(201, json=RECEIPT)

    ledger = ExecutionLedger()
    async with httpx.AsyncClient(
        base_url="http://hummingbot", transport=httpx.MockTransport(handler)
    ) as client:
        submitter, _ = build(ledger, client)
        first = await submitter.submit(
            intent(), execution_price_usd=20_000, reference_price_usd=20_000
        )
        second = await submitter.submit(
            intent(), execution_price_usd=20_010, reference_price_usd=20_000
        )

    assert first.status is SubmissionStatus.SUBMITTED
    assert second.status is SubmissionStatus.DUPLICATE
    assert "already has a ledger order" in (second.reason or "")
    assert posts == 1


@pytest.mark.asyncio
async def test_timeout_marks_uncertain_and_reconciles_before_retrying() -> None:
    attempts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.TimeoutException("timed out", request=request)
        return httpx.Response(201, json=RECEIPT)

    ledger = ExecutionLedger()
    resolver = RecordingResolver(False)
    async with httpx.AsyncClient(
        base_url="http://hummingbot", transport=httpx.MockTransport(handler)
    ) as client:
        submitter, slept = build(ledger, client, resolver=resolver)
        outcome = await submitter.submit(
            intent(), execution_price_usd=20_000, reference_price_usd=20_000
        )

    assert outcome.status is SubmissionStatus.SUBMITTED
    assert attempts == 2
    # Reconciliation ran between the timeout and the retry, and backed off.
    assert resolver.calls == [client_order_id_for("decision-1")]
    assert slept == [0.5]
    assert ledger.orders[client_order_id_for("decision-1")].submission_attempts == 2


@pytest.mark.asyncio
async def test_timeout_never_retries_when_the_venue_knows_the_order() -> None:
    attempts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.TimeoutException("timed out", request=request)

    ledger = ExecutionLedger()
    resolver = RecordingResolver(True)
    async with httpx.AsyncClient(
        base_url="http://hummingbot", transport=httpx.MockTransport(handler)
    ) as client:
        submitter, slept = build(ledger, client, resolver=resolver)
        outcome = await submitter.submit(
            intent(), execution_price_usd=20_000, reference_price_usd=20_000
        )

    assert outcome.status is SubmissionStatus.ADOPTED
    assert attempts == 1
    assert slept == []
    assert ledger.orders[client_order_id_for("decision-1")].state is OrderLifecycleState.SUBMITTED


@pytest.mark.asyncio
async def test_failed_reconciliation_leaves_the_order_uncertain_and_unretried() -> None:
    attempts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.TimeoutException("timed out", request=request)

    ledger = ExecutionLedger()
    resolver = RecordingResolver(RuntimeError("hummingbot unreachable"))
    async with httpx.AsyncClient(
        base_url="http://hummingbot", transport=httpx.MockTransport(handler)
    ) as client:
        submitter, _ = build(ledger, client, resolver=resolver)
        outcome = await submitter.submit(
            intent(), execution_price_usd=20_000, reference_price_usd=20_000
        )

    assert outcome.status is SubmissionStatus.UNCERTAIN
    assert "reconciliation failed" in (outcome.reason or "")
    assert attempts == 1
    order = ledger.orders[client_order_id_for("decision-1")]
    assert order.state is OrderLifecycleState.SUBMISSION_UNCERTAIN


@pytest.mark.asyncio
async def test_server_error_is_uncertain_and_backs_off_before_bounded_retries() -> None:
    attempts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(503, json={"detail": "unavailable"})

    ledger = ExecutionLedger()
    resolver = RecordingResolver(False, False, False)
    async with httpx.AsyncClient(
        base_url="http://hummingbot", transport=httpx.MockTransport(handler)
    ) as client:
        submitter, slept = build(ledger, client, resolver=resolver, max_retries=2)
        outcome = await submitter.submit(
            intent(), execution_price_usd=20_000, reference_price_usd=20_000
        )

    assert attempts == 3, "one initial attempt plus max_retries"
    assert slept == [0.5, 1.0], "exponential backoff between attempts"
    assert outcome.status is SubmissionStatus.REJECTED
    assert "venue does not know client order id" in (outcome.reason or "")
    order = ledger.orders[client_order_id_for("decision-1")]
    assert order.state is OrderLifecycleState.REJECTED
    assert order.reason is not None


@pytest.mark.asyncio
async def test_client_error_is_a_permanent_rejection_with_no_retry() -> None:
    attempts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(422, json={"detail": "bad pair"})

    ledger = ExecutionLedger()
    resolver = RecordingResolver()
    async with httpx.AsyncClient(
        base_url="http://hummingbot", transport=httpx.MockTransport(handler)
    ) as client:
        submitter, _ = build(ledger, client, resolver=resolver)
        outcome = await submitter.submit(
            intent(), execution_price_usd=20_000, reference_price_usd=20_000
        )

    assert outcome.status is SubmissionStatus.REJECTED
    assert "HTTP 422" in (outcome.reason or "")
    assert attempts == 1
    assert resolver.calls == []
    assert ledger.orders[client_order_id_for("decision-1")].state is OrderLifecycleState.REJECTED


@pytest.mark.asyncio
async def test_slow_venue_is_cut_off_by_the_submission_timeout() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(5)
        return httpx.Response(201, json=RECEIPT)

    ledger = ExecutionLedger()
    async with httpx.AsyncClient(
        base_url="http://hummingbot", transport=httpx.MockTransport(handler)
    ) as client:
        submitter, _ = build(ledger, client, resolver=RecordingResolver(RuntimeError("down")))
        submitter.timeout_seconds = 0.01
        outcome = await submitter.submit(
            intent(), execution_price_usd=20_000, reference_price_usd=20_000
        )

    assert outcome.status is SubmissionStatus.UNCERTAIN
    assert "timed out" in (outcome.reason or "")
    assert ledger.orders[client_order_id_for("decision-1")].state is (
        OrderLifecycleState.SUBMISSION_UNCERTAIN
    )


@pytest.mark.asyncio
async def test_planner_rejection_never_reaches_the_venue() -> None:
    posts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal posts
        posts += 1
        return httpx.Response(201, json=RECEIPT)

    ledger = ExecutionLedger()
    async with httpx.AsyncClient(
        base_url="http://hummingbot", transport=httpx.MockTransport(handler)
    ) as client:
        submitter, _ = build(ledger, client)
        outcome = await submitter.submit(
            intent(), execution_price_usd=21_000, reference_price_usd=20_000
        )

    assert outcome.status is SubmissionStatus.PLAN_REJECTED
    assert "deviates" in (outcome.reason or "")
    assert posts == 0
    assert ledger.orders == {}


@pytest.mark.asyncio
async def test_non_paper_mode_is_refused_before_anything_is_written() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("live submission must never reach the venue")

    ledger = ExecutionLedger()
    async with httpx.AsyncClient(
        base_url="http://hummingbot", transport=httpx.MockTransport(handler)
    ) as client:
        submitter, _ = build(ledger, client)
        submitter.trading_mode = "live"
        outcome = await submitter.submit(
            intent(), execution_price_usd=20_000, reference_price_usd=20_000
        )

    assert outcome.status is SubmissionStatus.REJECTED
    assert "outside paper mode" in (outcome.reason or "")
    assert ledger.orders == {}


@pytest.mark.asyncio
async def test_reconciler_resolves_uncertainty_by_client_order_id() -> None:
    client_order_id = client_order_id_for("decision-1")

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {
                    "order_id": "venue-9",
                    "client_order_id": client_order_id,
                    "trading_pair": "BTC-USD",
                    "trade_type": "BUY",
                    "amount": 0.05,
                    "status": "open",
                }
            ],
        )

    async with httpx.AsyncClient(
        base_url="http://test", transport=httpx.MockTransport(handler)
    ) as client:
        reconciler = HummingbotExecutionReconciler("http://test", "u", "p", client=client)
        assert await reconciler.venue_knows_order(
            ExecutionLedger(),
            client_order_id=client_order_id,
            trading_pair="BTC-USD",
            trade_type="BUY",
            quantity=0.05,
        )


@pytest.mark.asyncio
async def test_reconciler_treats_an_unattributed_matching_order_as_ours() -> None:
    """hummingbot-api drops client order ids, so a matching orphan blocks retry."""

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {
                    "order_id": "venue-9",
                    "trading_pair": "BTC-USD",
                    "trade_type": "BUY",
                    "amount": 0.05,
                    "status": "open",
                }
            ],
        )

    async with httpx.AsyncClient(
        base_url="http://test", transport=httpx.MockTransport(handler)
    ) as client:
        reconciler = HummingbotExecutionReconciler("http://test", "u", "p", client=client)
        assert await reconciler.venue_knows_order(
            ExecutionLedger(),
            client_order_id="ts-unknown",
            trading_pair="BTC-USD",
            trade_type="BUY",
            quantity=0.05,
        )


@pytest.mark.asyncio
async def test_reconciler_reports_an_absent_order() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {
                    "order_id": "venue-9",
                    "trading_pair": "ETH-USD",
                    "trade_type": "SELL",
                    "amount": 2.0,
                    "status": "open",
                }
            ],
        )

    async with httpx.AsyncClient(
        base_url="http://test", transport=httpx.MockTransport(handler)
    ) as client:
        reconciler = HummingbotExecutionReconciler("http://test", "u", "p", client=client)
        assert not await reconciler.venue_knows_order(
            ExecutionLedger(),
            client_order_id="ts-unknown",
            trading_pair="BTC-USD",
            trade_type="BUY",
            quantity=0.05,
        )


@pytest.mark.asyncio
async def test_reconciler_propagates_transport_failure_rather_than_saying_no() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"detail": "boom"})

    async with httpx.AsyncClient(
        base_url="http://test", transport=httpx.MockTransport(handler)
    ) as client:
        reconciler = HummingbotExecutionReconciler("http://test", "u", "p", client=client)
        with pytest.raises(httpx.HTTPStatusError):
            await reconciler.venue_knows_order(
                ExecutionLedger(),
                client_order_id="ts-unknown",
                trading_pair="BTC-USD",
                trade_type="BUY",
                quantity=0.05,
            )
