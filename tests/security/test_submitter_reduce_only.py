"""The reducing-only clamp on the venue-submission path (#130).

`PaperFillSimulator` has enforced "a reducing order never plans more than is
held" since #130. `IdempotentSubmitter` — the ``--submit`` / Hummingbot path —
did not, because it holds no portfolio reference. These tests pin the invariant
on that second path, and pin the two properties that make the clamp safe: it can
only ever shrink an order, and it is unreachable for an entry.
"""

from __future__ import annotations

import httpx
import pytest

from traderstack.execution.hummingbot import HummingbotPaperExecutor
from traderstack.execution.ledger import (
    ExecutionLedger,
    ExecutionOrder,
    OrderLifecycleState,
)
from traderstack.execution.planner import ExecutionPlanner, client_order_id_for
from traderstack.execution.submitter import IdempotentSubmitter, SubmissionStatus
from traderstack.models import Side
from traderstack.pipeline import PaperOrderIntent

PRICE = 20_000.0

RECEIPT = {
    "order_id": "venue-1",
    "account_name": "paper_account",
    "connector_name": "kraken_paper_trade",
    "trading_pair": "BTC-USD",
    "trade_type": "SELL",
    "amount": 0.04,
    "order_type": "MARKET",
    "price": PRICE,
    "status": "submitted",
}


def exit_intent(
    *, decision_id: str = "decision-1", notional_usd: float = 1_000.0
) -> PaperOrderIntent:
    """A protective exit: reducing-only SELL, as `pipeline._build_exit_result` emits."""

    return PaperOrderIntent(
        decision_id=decision_id,
        asset="BTC",
        side=Side.SELL,
        notional_usd=notional_usd,
        venue="kraken_paper_trade",
        reduce_only=True,
    )


def entry_intent(*, notional_usd: float = 1_000.0) -> PaperOrderIntent:
    return PaperOrderIntent(
        decision_id="decision-entry",
        asset="BTC",
        side=Side.SELL,
        notional_usd=notional_usd,
        venue="kraken_paper_trade",
        reduce_only=False,
    )


def build(ledger: ExecutionLedger) -> tuple[IdempotentSubmitter, list[dict]]:
    """Submitter wired to a transport that records every venue request body."""

    sent: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        sent.append(json.loads(request.content))
        return httpx.Response(201, json=RECEIPT)

    client = httpx.AsyncClient(base_url="http://hummingbot", transport=httpx.MockTransport(handler))
    submitter = IdempotentSubmitter(
        executor=HummingbotPaperExecutor("http://hummingbot", "u", "p", client=client),
        ledger=ledger,
        planner=ExecutionPlanner(lot_step=0.0001, min_notional_usd=10),
    )
    return submitter, sent


@pytest.mark.asyncio
async def test_reducing_order_is_clamped_to_the_held_quantity() -> None:
    """$1000 at $20000 asks for 0.05 BTC; only 0.04 is held, so 0.04 is sent."""

    ledger = ExecutionLedger()
    submitter, sent = build(ledger)

    outcome = await submitter.submit(
        exit_intent(),
        execution_price_usd=PRICE,
        reference_price_usd=PRICE,
        max_quantity=0.04,
    )

    assert outcome.status is SubmissionStatus.SUBMITTED
    assert outcome.plan is not None
    assert outcome.plan.quantity == pytest.approx(0.04)
    # The venue is sent plan.quantity, so the clamp has to reach the wire, not
    # just the ledger row.
    assert sent[0]["amount"] == pytest.approx(0.04)
    assert ledger.orders_for_decision("decision-1")[0].requested_quantity == pytest.approx(0.04)


@pytest.mark.asyncio
async def test_clamp_never_raises_a_smaller_reducing_order() -> None:
    """A reducing order well inside the position is submitted untouched."""

    ledger = ExecutionLedger()
    submitter, sent = build(ledger)

    outcome = await submitter.submit(
        exit_intent(notional_usd=200.0),
        execution_price_usd=PRICE,
        reference_price_usd=PRICE,
        max_quantity=5.0,
    )

    assert outcome.status is SubmissionStatus.SUBMITTED
    assert outcome.plan is not None
    assert outcome.plan.quantity == pytest.approx(0.01)
    assert sent[0]["amount"] == pytest.approx(0.01)


@pytest.mark.asyncio
async def test_clamp_is_unavailable_to_an_entry_order() -> None:
    """An entry ignores the cap entirely: the clamp cannot resize a non-exit."""

    ledger = ExecutionLedger()
    submitter, sent = build(ledger)

    outcome = await submitter.submit(
        entry_intent(),
        execution_price_usd=PRICE,
        reference_price_usd=PRICE,
        max_quantity=0.04,
    )

    assert outcome.status is SubmissionStatus.SUBMITTED
    assert outcome.plan is not None
    # Unclamped: the full 0.05 the notional asked for.
    assert outcome.plan.quantity == pytest.approx(0.05)
    assert sent[0]["amount"] == pytest.approx(0.05)


@pytest.mark.asyncio
async def test_no_remaining_position_is_a_labelled_refusal() -> None:
    """A reducing order against a flat book is refused, and labelled as such."""

    ledger = ExecutionLedger()
    submitter, sent = build(ledger)

    outcome = await submitter.submit(
        exit_intent(),
        execution_price_usd=PRICE,
        reference_price_usd=PRICE,
        max_quantity=0.0,
    )

    assert outcome.status is SubmissionStatus.INVALID_EXIT_SIZE
    assert outcome.status is not SubmissionStatus.PLAN_REJECTED
    assert sent == []
    assert ledger.orders_for_decision("decision-1") == []


@pytest.mark.asyncio
async def test_absent_cap_leaves_the_order_unclamped() -> None:
    """No position view means no clamp — deliberately, not fail-closed.

    Refusing a protective exit because its position view is unavailable would
    reproduce #130's actual harm: a stop-loss that does not reduce risk.
    """

    ledger = ExecutionLedger()
    submitter, sent = build(ledger)

    outcome = await submitter.submit(
        exit_intent(),
        execution_price_usd=PRICE,
        reference_price_usd=PRICE,
    )

    assert outcome.status is SubmissionStatus.SUBMITTED
    assert outcome.plan is not None
    assert outcome.plan.quantity == pytest.approx(0.05)
    assert sent[0]["amount"] == pytest.approx(0.05)


@pytest.mark.asyncio
async def test_replan_after_an_uncertain_submission_never_grows_the_order() -> None:
    """A resumed order re-planned at a lower price keeps the smaller quantity.

    `notional / execution_price` grows as the price falls, so a replan is
    exactly where a reducing order could silently get bigger.
    """

    ledger = ExecutionLedger()
    submitter, sent = build(ledger)
    client_order_id = client_order_id_for("decision-1")
    ledger.register_order(
        ExecutionOrder(
            order_id=client_order_id,
            decision_id="decision-1",
            asset="BTC",
            side=Side.SELL,
            requested_quantity=0.04,
            state=OrderLifecycleState.SUBMISSION_UNCERTAIN,
            client_order_id=client_order_id,
            correlation_id="c",
        )
    )

    class Resolver:
        async def venue_knows_order(self, ledger: ExecutionLedger, **kwargs: object) -> bool:
            return False

    submitter.resolver = Resolver()  # type: ignore[assignment]

    # Price halved: $1000 now converts to 0.1 BTC, far above the planned 0.04.
    outcome = await submitter.submit(
        exit_intent(),
        execution_price_usd=PRICE / 2,
        reference_price_usd=PRICE / 2,
        max_quantity=5.0,
    )

    assert outcome.status is SubmissionStatus.SUBMITTED
    assert outcome.plan is not None
    assert outcome.plan.quantity == pytest.approx(0.04)
    assert sent[0]["amount"] == pytest.approx(0.04)
    assert ledger.orders_for_decision("decision-1")[0].requested_quantity == pytest.approx(0.04)


@pytest.mark.asyncio
async def test_clamping_does_not_change_the_client_order_id() -> None:
    """Idempotency: the key is derived from the decision, not the quantity."""

    unclamped_ledger = ExecutionLedger()
    unclamped, _ = build(unclamped_ledger)
    first = await unclamped.submit(
        exit_intent(),
        execution_price_usd=PRICE,
        reference_price_usd=PRICE,
    )

    clamped_ledger = ExecutionLedger()
    clamped, _ = build(clamped_ledger)
    second = await clamped.submit(
        exit_intent(),
        execution_price_usd=PRICE,
        reference_price_usd=PRICE,
        max_quantity=0.04,
    )

    assert first.plan is not None and second.plan is not None
    assert first.plan.quantity != second.plan.quantity
    assert first.plan.client_order_id == second.plan.client_order_id
    assert second.plan.client_order_id == client_order_id_for("decision-1")
