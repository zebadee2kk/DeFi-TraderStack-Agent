"""Epic 10 drill: reconciliation drift.

Per docs/EXECUTION-ARCHITECTURE.md, NAV drift past the threshold blocks *new
risk only*. Market data, decisions, sizing and the audit trail all keep running;
only submission stops, and it resumes on the next clean pass.
"""

from __future__ import annotations

import pytest
from prometheus_client import REGISTRY

pytestmark = pytest.mark.asyncio


def _blocked_gauge() -> float | None:
    return REGISTRY.get_sample_value("traderstack_reconciliation_blocked")


async def test_nav_drift_blocks_submission_but_not_decisions(harness) -> None:
    drill = await harness(reconcilers=True)
    assert drill.portfolio_reconciler is not None
    drill.board.arm("portfolio_reconciler_nav_drift")

    assert await drill.service.reconcile_now() is False
    assert drill.service.health.reconciliation_blocked is True
    assert "NAV drift" in (drill.service.health.last_reconciliation_error or "")
    assert drill.service.submission_enabled is False
    assert _blocked_gauge() == 1

    result = await drill.cycle()

    assert result is not None
    # The decision plane is untouched: proposal, risk result and audit all ran.
    assert result.pipeline.accepted_market_data is True
    assert result.pipeline.proposal is not None
    assert result.pipeline.risk_result is not None
    assert result.pipeline.paper_order is not None
    # Only submission stopped.
    assert result.execution_receipt is None
    assert result.execution_status is None
    assert drill.venue_api.posts == 0
    assert drill.service.health.healthy

    drill.board.disarm("portfolio_reconciler_nav_drift")
    assert await drill.service.reconcile_now() is True
    assert drill.service.health.reconciliation_blocked is False
    assert drill.service.submission_enabled is True
    assert _blocked_gauge() == 0

    resumed = await drill.cycle()
    assert resumed is not None
    assert resumed.execution_status == "submitted"
    assert drill.venue_api.posts == 1


async def test_an_order_state_conflict_also_blocks_submission(harness) -> None:
    drill = await harness(reconcilers=True)
    drill.board.arm("execution_reconciler_drift")

    assert await drill.service.reconcile_now() is False
    assert drill.service.health.reconciliation_blocked is True
    assert "filled locally but open at the venue" in (
        drill.service.health.last_reconciliation_error or ""
    )

    await drill.cycle()
    assert drill.venue_api.posts == 0


async def test_an_unreachable_reconciler_is_unreconciled_state(harness) -> None:
    """An unanswered venue is not a clean venue."""

    drill = await harness(reconcilers=True)
    drill.board.arm("portfolio_reconciler_error")

    assert await drill.service.reconcile_now() is False
    assert drill.service.health.reconciliation_blocked is True
    assert drill.service.submission_enabled is False

    drill.board.disarm("portfolio_reconciler_error")
    assert await drill.service.reconcile_now() is True


async def test_the_block_clears_only_after_a_fully_clean_pass(harness) -> None:
    drill = await harness(reconcilers=True)
    drill.board.arm("portfolio_reconciler_nav_drift", times=1)
    drill.board.arm("execution_reconciler_drift", times=2)

    assert await drill.service.reconcile_now() is False
    # NAV is clean again but the order-state conflict is not: still blocked.
    assert await drill.service.reconcile_now() is False
    assert drill.service.health.reconciliation_blocked is True

    assert await drill.service.reconcile_now() is True
    assert drill.service.health.reconciliation_blocked is False
    assert drill.service.health.last_reconciliation_error is None
