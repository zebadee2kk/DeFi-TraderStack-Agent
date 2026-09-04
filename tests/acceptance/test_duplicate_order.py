"""Epic 10 drill: duplicate orders.

One decision produces at most one venue order -- offered twice in the same
process, and offered again after a restart that reloads the ledger from disk.
The ledger, not the venue, is the authority: ``hummingbot-api`` does not persist
client order ids (see ``execution/hummingbot.py``), so the guard has to survive
without any venue cooperation at all.
"""

from __future__ import annotations

import pytest

from traderstack.execution.ledger import ExecutionLedger
from traderstack.execution.ledger_store import JsonExecutionLedgerStore
from traderstack.execution.planner import ExecutionPlanner, client_order_id_for
from traderstack.execution.submitter import IdempotentSubmitter, SubmissionStatus
from traderstack.pipeline import PaperOrderIntent

pytestmark = pytest.mark.asyncio


async def _first_order(drill) -> PaperOrderIntent:
    result = await drill.cycle()
    assert result is not None
    intent = result.pipeline.paper_order
    assert intent is not None
    assert result.execution_status == "submitted"
    assert drill.venue_api.posts == 1
    return intent


async def test_the_same_decision_offered_twice_submits_once(harness) -> None:
    drill = await harness()
    intent = await _first_order(drill)

    submitter = drill.service.runtime.submitter
    assert submitter is not None
    outcome = await submitter.submit(
        intent, execution_price_usd=intent.notional_usd, reference_price_usd=intent.notional_usd
    )

    assert outcome.status is SubmissionStatus.DUPLICATE
    assert outcome.receipt is None
    assert drill.venue_api.posts == 1
    assert len(drill.ledger.orders_for_decision(intent.decision_id)) == 1
    assert list(drill.ledger.orders) == [client_order_id_for(intent.decision_id)]


async def test_a_restart_that_reloads_the_ledger_still_refuses_the_duplicate(harness) -> None:
    drill = await harness()
    intent = await _first_order(drill)

    # Simulate the restart: nothing in memory survives, only the ledger file.
    store = JsonExecutionLedgerStore(drill.ledger_store.path)
    reloaded = await store.load()
    assert reloaded is not None
    assert reloaded is not drill.ledger
    assert reloaded.has_order_for_decision(intent.decision_id)

    async def no_sleep(seconds: float) -> None:
        return None

    restarted = IdempotentSubmitter(
        executor=drill.service.runtime.executor,
        ledger=reloaded,
        planner=ExecutionPlanner(lot_step=1e-8, min_notional_usd=10.0),
        ledger_store=store,
        backoff_seconds=0.0,
        sleep=no_sleep,
    )
    outcome = await restarted.submit(
        intent, execution_price_usd=intent.notional_usd, reference_price_usd=intent.notional_usd
    )

    assert outcome.status is SubmissionStatus.DUPLICATE
    assert drill.venue_api.posts == 1, "a restart must not resubmit a live decision"


async def test_an_empty_ledger_after_a_wiped_store_is_the_only_way_to_resubmit(harness) -> None:
    """Names the failure mode explicitly: idempotency lives in the ledger file.

    If the ledger is lost, the guard is lost with it. This is the reason the
    ledger is written *before* the venue call and persisted on every state
    change, and the reason ``--ledger-path`` must live on durable storage.
    """

    drill = await harness()
    intent = await _first_order(drill)

    async def no_sleep(seconds: float) -> None:
        return None

    amnesiac = IdempotentSubmitter(
        executor=drill.service.runtime.executor,
        ledger=ExecutionLedger(),
        planner=ExecutionPlanner(lot_step=1e-8, min_notional_usd=10.0),
        backoff_seconds=0.0,
        sleep=no_sleep,
    )
    outcome = await amnesiac.submit(
        intent, execution_price_usd=intent.notional_usd, reference_price_usd=intent.notional_usd
    )

    assert outcome.status is SubmissionStatus.SUBMITTED
    assert drill.venue_api.posts == 2


async def test_each_service_cycle_produces_exactly_one_ledger_order(harness) -> None:
    drill = await harness()
    await drill.cycles(5)

    decisions = [
        result.pipeline.paper_order.decision_id
        for result in drill.results
        if result.pipeline.paper_order is not None
    ]
    assert len(decisions) == 5
    assert len(set(decisions)) == 5
    assert len(drill.ledger.orders) == 5
    assert drill.venue_api.posts == 5
    for decision_id in decisions:
        assert len(drill.ledger.orders_for_decision(decision_id)) == 1
