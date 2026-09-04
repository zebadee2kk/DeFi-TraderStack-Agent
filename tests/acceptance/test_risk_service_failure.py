"""Epic 10 drill: risk-service failure.

docs/RISK-PRINCIPLES.md ("Failure behaviour") and docs/SECURITY-THREAT-MODEL.md
("Failure Policy") both say an unavailable risk service means no new risk. The
drill breaks the risk engine and checks the whole chain: no order, the cycle is
recorded as an error, the health counter moves, and the service eventually stops
itself rather than looping on a broken control.
"""

from __future__ import annotations

import asyncio

import pytest

pytestmark = pytest.mark.asyncio


async def test_a_raising_risk_engine_produces_no_order_and_an_error_cycle(harness) -> None:
    drill = await harness()
    drill.risk_failure.arm()

    result = await drill.cycle()

    assert result is None, "a failed risk decision never reaches the event sinks"
    assert drill.venue_api.posts == 0
    assert drill.ledger.orders == {}
    assert drill.service.health.consecutive_errors == 1
    assert drill.service.health.last_error is not None
    assert "risk_engine_error" in drill.service.health.last_error
    assert drill.risk_failure.fired == 1


async def test_the_service_stops_after_max_consecutive_errors(harness) -> None:
    """ "Unavailable risk service = no new risk" has to terminate, not spin."""

    drill = await harness()
    drill.service.health.max_consecutive_errors = 3
    drill.risk_failure.arm()

    await asyncio.wait_for(drill.service.run(), timeout=5)

    assert drill.service.health.healthy is False
    assert drill.service.health.consecutive_errors == 3
    assert drill.risk_failure.fired == 3
    assert drill.venue_api.posts == 0


async def test_the_run_recovers_when_the_risk_engine_comes_back(harness) -> None:
    drill = await harness()
    drill.risk_failure.arm(times=2)

    await drill.cycles(2)
    assert drill.service.health.consecutive_errors == 2
    assert drill.results == []

    result = await drill.cycle()

    assert result is not None
    assert result.pipeline.risk_result is not None
    assert drill.service.health.consecutive_errors == 0
    assert drill.service.health.healthy


async def test_a_broken_risk_engine_writes_nothing_to_the_risk_audit_trail(harness) -> None:
    """No decision was made, so there is no decision to record."""

    drill = await harness()
    drill.risk_failure.arm()

    await drill.cycle()

    assert not drill.risk_audit.path.exists()
