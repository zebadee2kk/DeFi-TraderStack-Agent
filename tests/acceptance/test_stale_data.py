"""Epic 10 drill: stale data.

Three independent freshness gates, each owned by a different layer, each of
which must refuse new risk on its own: the venue tick (pipeline), the candle
history (pre-trade gate) and the portfolio snapshot (risk engine).
"""

from __future__ import annotations

import pytest

from traderstack.models import RiskDecision

pytestmark = pytest.mark.asyncio


async def test_a_stale_tick_rejects_with_stale_primary_tick(harness) -> None:
    drill = await harness()
    drill.board.arm("venue_feed_stale")

    result = await drill.cycle()

    assert result is not None
    assert result.pipeline.accepted_market_data is False
    assert "stale_primary_tick" in result.pipeline.rejection_reasons
    assert result.pipeline.paper_order is None
    assert result.pipeline.risk_result is None
    assert drill.venue_api.posts == 0


async def test_a_stale_tick_recovers_on_the_next_fresh_cycle(harness) -> None:
    drill = await harness()
    drill.board.arm("venue_feed_stale", times=1)

    stale = await drill.cycle()
    fresh = await drill.cycle()

    assert stale is not None and fresh is not None
    assert "stale_primary_tick" in stale.pipeline.rejection_reasons
    assert fresh.pipeline.rejection_reasons == []
    assert fresh.pipeline.paper_order is not None


async def test_stale_candle_history_rejects_with_stale_candle_history(harness) -> None:
    drill = await harness()
    drill.board.arm("candles_history_stale")

    result = await drill.cycle()

    assert result is not None
    # The history arrived, it is simply too old to justify new risk.
    assert result.candles_loaded > 0
    assert result.candle_error is None
    assert result.pipeline.accepted_market_data is True
    assert result.pipeline.rejection_reasons == ["stale_candle_history"]
    assert result.pipeline.pretrade_check is not None
    assert result.pipeline.pretrade_check.passed is False
    assert result.pipeline.paper_order is None
    assert drill.venue_api.posts == 0


async def test_a_stale_portfolio_snapshot_rejects_with_stale_portfolio_state(harness) -> None:
    drill = await harness()
    drill.portfolio.stale.arm()

    result = await drill.cycle()

    assert result is not None
    assert result.pipeline.accepted_market_data is True
    assert result.pipeline.risk_result is not None
    assert result.pipeline.risk_result.decision is RiskDecision.REJECT
    assert "stale_portfolio_state" in result.pipeline.risk_result.reasons
    assert result.pipeline.paper_order is None
    assert drill.venue_api.posts == 0
    assert drill.portfolio.stale.fired > 0


async def test_stale_state_is_recorded_in_the_risk_audit_trail(harness) -> None:
    """A refusal is evidence too: it has to reach the immutable trail."""

    drill = await harness()
    drill.portfolio.stale.arm()
    await drill.cycle()
    drill.portfolio.stale.disarm()
    await drill.cycle()

    verification = drill.risk_audit.verify()
    assert verification.valid is True
    assert verification.records == 2

    records = drill.risk_audit.path.read_text(encoding="utf-8").splitlines()
    assert "stale_portfolio_state" in records[0]
    assert "stale_portfolio_state" not in records[1]
