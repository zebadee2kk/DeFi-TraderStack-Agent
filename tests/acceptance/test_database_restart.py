"""Epic 10 drill: forced database restart.

The durable event sink (Postgres / Redis fan-out behind ``on_result``) is made
to fail for a run of cycles and then recover. What must hold throughout:

* the failure is counted, not swallowed (``traderstack_event_sink_failures_total``);
* no decision is submitted twice because a sink failed after submission;
* the portfolio checkpoint -- the thing a restart actually reads -- is never
  frozen by a sink outage;
* persistence resumes on its own once the sink comes back.
"""

from __future__ import annotations

import pytest
from prometheus_client import REGISTRY

from traderstack.checkpoint import JsonPortfolioCheckpointStore

pytestmark = pytest.mark.asyncio


def _sink_failures(sink: str) -> float:
    return REGISTRY.get_sample_value("traderstack_event_sink_failures_total", {"sink": sink}) or 0.0


async def test_a_sink_outage_is_counted_and_recovers(harness) -> None:
    drill = await harness()
    before = _sink_failures("on_result")

    await drill.cycles(2)
    assert drill.audit_sink.delivered == 2

    drill.board.arm("audit_sink_error", times=3)
    await drill.cycles(3)

    assert drill.board.get("audit_sink_error").fired == 3
    assert _sink_failures("on_result") == pytest.approx(before + 3)
    assert drill.audit_sink.delivered == 2, "nothing was persisted while the sink was down"
    assert drill.service.health.consecutive_errors == 3
    assert drill.service.health.healthy, "3 sink failures stay under max_consecutive_errors"

    await drill.cycles(2)

    assert drill.audit_sink.delivered == 4, "persistence resumes without operator action"
    assert drill.service.health.consecutive_errors == 0


async def test_a_sink_outage_never_resubmits_a_decision(harness) -> None:
    drill = await harness()
    drill.board.arm("audit_sink_error", times=3)

    await drill.cycles(6)

    decisions = [order.decision_id for order in drill.ledger.orders.values()]
    assert len(decisions) == len(set(decisions)), "one ledger order per decision"
    assert drill.venue_api.posts == len(drill.ledger.orders)
    # Submission happens before the sink fan-out, so the orders placed during the
    # outage are real and must not be replayed when the sink returns.
    assert drill.venue_api.posts == 6


async def test_the_portfolio_checkpoint_survives_a_sink_outage(harness) -> None:
    """A remote sink outage must not freeze the local recovery checkpoint.

    Regression guard: the checkpoint is written *before* the event fan-out, so a
    Postgres/Redis outage cannot leave a restart resuming from a stale book
    while the execution ledger has moved on.
    """

    drill = await harness()
    await drill.cycles(2)

    store = JsonPortfolioCheckpointStore(drill.checkpoint_store.path)
    saved = await store.load()
    assert saved is not None
    assert saved.marks_usd["BTC"] == pytest.approx(drill.portfolio.marks_usd["BTC"])

    drill.board.arm("audit_sink_error", times=3)
    await drill.cycles(3)

    resumed = await store.load()
    assert resumed is not None
    assert resumed.marks_usd["BTC"] == pytest.approx(drill.portfolio.marks_usd["BTC"])
    assert resumed.cash_usd == pytest.approx(drill.portfolio.cash_usd)


async def test_a_permanent_sink_outage_stops_the_service(harness) -> None:
    """Losing the durable trail entirely is not something to trade through."""

    drill = await harness()
    drill.service.health.max_consecutive_errors = 3
    drill.board.arm("audit_sink_error")

    for _ in range(3):
        await drill.cycle()

    assert drill.service.health.healthy is False
    assert drill.audit_sink.delivered == 0
