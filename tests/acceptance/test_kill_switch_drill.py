"""Epic 10 drill: the kill switch, exercised against a running service.

The runbook's drill ("periodically verify the switch actually stops trading") as
an automated test: a sentinel file appears mid-run, the very next cycle is
rejected with ``kill_switch_enabled`` and places no order, the Prometheus gauge
flips, ``traderstack-resume`` clears it, and trading resumes. The SIGUSR1
channel is exercised too where the platform has it.
"""

from __future__ import annotations

import os
import signal

import pytest
from prometheus_client import REGISTRY

from traderstack import killswitch
from traderstack.killswitch import KILL_SWITCH_REASON, resume_main
from traderstack.models import RiskDecision

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def clear_signal_latch():
    killswitch._reset_signal_latch_for_tests()
    yield
    killswitch._reset_signal_latch_for_tests()


def _gauge(name: str, **labels: str) -> float | None:
    return REGISTRY.get_sample_value(name, labels or None)


async def test_a_sentinel_created_mid_run_halts_the_next_cycle_and_resume_releases_it(
    harness,
) -> None:
    drill = await harness()

    trading = await drill.cycle()
    assert trading is not None
    assert trading.pipeline.paper_order is not None
    assert drill.venue_api.posts == 1
    assert _gauge("traderstack_kill_switch_engaged") == 0

    # An operator touches the sentinel while the service is running.
    drill.kill_sentinel.arm()

    halted = await drill.cycle()
    assert halted is not None
    assert halted.pipeline.risk_result is not None
    assert halted.pipeline.risk_result.decision is RiskDecision.REJECT
    assert halted.pipeline.risk_result.reasons == [KILL_SWITCH_REASON]
    assert halted.pipeline.paper_order is None
    assert drill.venue_api.posts == 1, "no new risk while the halt is engaged"
    assert _gauge("traderstack_kill_switch_engaged") == 1
    assert _gauge("traderstack_kill_switch_source_engaged", source="file") == 1

    # traderstack-resume is the operator entry point, run here as the function.
    assert resume_main(["--file", str(drill.kill_sentinel.path)]) == 0
    assert not drill.kill_sentinel.path.exists()

    resumed = await drill.cycle()
    assert resumed is not None
    assert resumed.pipeline.rejection_reasons == []
    assert resumed.pipeline.paper_order is not None
    assert drill.venue_api.posts == 2
    assert _gauge("traderstack_kill_switch_engaged") == 0
    assert _gauge("traderstack_kill_switch_source_engaged", source="file") == 0


async def test_the_halt_is_re_probed_every_cycle_without_a_restart(harness) -> None:
    drill = await harness()
    drill.kill_sentinel.arm()

    await drill.cycles(3)

    assert drill.service.kill_switch is not None
    assert drill.service.kill_switch.last_refreshed_at is not None
    assert all(
        result.pipeline.risk_result is not None
        and result.pipeline.risk_result.reasons == [KILL_SWITCH_REASON]
        for result in drill.results
    )
    assert drill.venue_api.posts == 0


async def test_every_halted_cycle_is_still_recorded_in_the_risk_audit_trail(harness) -> None:
    """The halt suppresses risk, never evidence."""

    drill = await harness()
    drill.kill_sentinel.arm()

    await drill.cycles(2)

    verification = drill.risk_audit.verify()
    assert verification.valid is True
    assert verification.records == 2
    assert drill.risk_audit.path.read_text(encoding="utf-8").count(KILL_SWITCH_REASON) == 2


@pytest.mark.skipif(not hasattr(signal, "SIGUSR1"), reason="platform has no SIGUSR1")
async def test_sigusr1_halts_the_running_service(harness) -> None:
    drill = await harness()
    assert killswitch.install_signal_handler() is True

    first = await drill.cycle()
    assert first is not None and first.pipeline.paper_order is not None

    os.kill(os.getpid(), signal.SIGUSR1)

    halted = await drill.cycle()
    assert halted is not None
    assert halted.pipeline.risk_result is not None
    assert halted.pipeline.risk_result.reasons == [KILL_SWITCH_REASON]
    assert drill.service.kill_switch is not None
    assert "signal" in drill.service.kill_switch.engaged_sources
    assert drill.venue_api.posts == 1

    # There is deliberately no in-process way to clear a signalled halt: it
    # survives until the process restarts (killswitch module docstring).
    assert resume_main(["--file", str(drill.kill_sentinel.path)]) == 0
    still_halted = await drill.cycle()
    assert still_halted is not None
    assert still_halted.pipeline.risk_result is not None
    assert still_halted.pipeline.risk_result.reasons == [KILL_SWITCH_REASON]
