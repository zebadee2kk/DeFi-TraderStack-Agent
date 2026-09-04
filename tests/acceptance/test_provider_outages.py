"""Epic 10 drill: forced provider outages.

Every external data source is taken away in turn and the run is checked against
the documented fail-closed behaviour: a missing *independent* price is a
rejection, missing candle history is a rejection, a missing intelligence
provider only degrades the cycle, and a provider that keeps failing is taken out
of circuit by the registry rather than retried forever.
"""

from __future__ import annotations

import pytest

from traderstack.agents.review import UNAVAILABLE_REASON, MetaAgentMode
from traderstack.market.registry import BreakerState

pytestmark = pytest.mark.asyncio


async def test_one_reference_down_still_trades_on_the_other(harness) -> None:
    drill = await harness()
    drill.board.arm("coingecko_reference_error")

    result = await drill.cycle()

    assert result is not None
    assert result.pipeline.accepted_market_data
    assert result.pipeline.rejection_reasons == []
    assert [reference.source.value for reference in result.references] == ["coinmarketcap"]
    assert result.pipeline.paper_order is not None
    assert result.execution_status == "submitted"
    assert drill.board.get("coingecko_reference_error").fired == 1


async def test_every_reference_down_rejects_with_no_independent_reference_price(harness) -> None:
    drill = await harness()
    drill.board.arm("coingecko_reference_error")
    drill.board.arm("coinmarketcap_reference_error")

    result = await drill.cycle()

    assert result is not None
    assert result.pipeline.accepted_market_data is False
    assert result.pipeline.rejection_reasons == ["no_independent_reference_price"]
    assert result.pipeline.paper_order is None
    assert result.pipeline.risk_result is None
    assert drill.venue_api.posts == 0


async def test_a_hanging_reference_provider_times_out_and_is_treated_as_down(harness) -> None:
    """A hang is not an answer: the registry timeout turns it into a failure."""

    drill = await harness()
    drill.board.arm("coingecko_reference_hang")
    drill.board.arm("coinmarketcap_reference_hang")

    result = await drill.cycle()

    assert result is not None
    assert result.pipeline.rejection_reasons == ["no_independent_reference_price"]
    assert drill.reference_registries[0].health().last_error is not None


async def test_candle_provider_down_rejects_with_missing_candle_history(harness) -> None:
    drill = await harness()
    drill.board.arm("candles_history_error")

    result = await drill.cycle()

    assert result is not None
    # Market data itself was fine; the pre-trade gate is what refuses.
    assert result.pipeline.accepted_market_data is True
    assert result.pipeline.rejection_reasons == ["missing_candle_history"]
    assert result.candles_loaded == 0
    assert result.candle_error is not None
    assert result.pipeline.paper_order is None
    assert drill.venue_api.posts == 0


async def test_an_empty_candle_history_is_also_missing_candle_history(harness) -> None:
    drill = await harness()
    drill.board.arm("candles_history_empty")

    result = await drill.cycle()

    assert result is not None
    assert result.pipeline.rejection_reasons == ["missing_candle_history"]
    assert result.candle_error is None, "an empty answer is not an error, but still fails closed"


async def test_intelligence_down_still_completes_the_cycle_and_records_the_error(harness) -> None:
    drill = await harness()
    drill.board.arm("intelligence_error")

    result = await drill.cycle()

    assert result is not None
    assert result.intelligence_error is not None
    assert "intelligence_error" in result.intelligence_error
    assert result.intelligence_sources == []
    # Intelligence is optional unless INTELLIGENCE_REQUIRED is set, so the cycle
    # completes on market data alone rather than erroring out.
    assert result.pipeline.accepted_market_data is True
    assert result.pipeline.paper_order is not None
    assert drill.service.health.healthy
    assert drill.service.health.consecutive_errors == 0


async def test_required_intelligence_down_blocks_new_risk(harness) -> None:
    drill = await harness(settings_overrides={"intelligence_required": True})
    drill.board.arm("intelligence_error")

    result = await drill.cycle()

    assert result is not None
    assert result.pipeline.rejection_reasons == ["no_external_intelligence"]
    assert result.pipeline.paper_order is None


async def test_provider_circuit_breaker_opens_after_the_failure_threshold(harness) -> None:
    drill = await harness(provider_failure_threshold=3)
    drill.board.arm("coingecko_reference_error")
    registry = drill.reference_registries[0]
    provider = drill.references[0]

    for _ in range(3):
        await drill.cycle()

    health = registry.health()
    assert health.state is BreakerState.OPEN
    assert health.consecutive_failures >= 3
    assert await registry.healthy() is False

    calls_when_open = provider.calls
    await drill.cycle()
    assert provider.calls == calls_when_open, "an open circuit must not reach the provider"
    assert registry.health().state is BreakerState.OPEN
    # The other reference is untouched, so the run keeps trading.
    assert drill.reference_registries[1].health().state is BreakerState.CLOSED
    assert drill.last.pipeline.paper_order is not None


async def test_meta_agent_unavailable_in_veto_mode_blocks_the_order(harness) -> None:
    drill = await harness(meta_mode=MetaAgentMode.VETO)
    drill.board.arm("meta_agent_error")

    result = await drill.cycle()

    assert result is not None
    assert result.meta_review is not None
    assert result.meta_review.usable is False
    assert result.meta_review.suppression_reason == UNAVAILABLE_REASON
    assert UNAVAILABLE_REASON in result.pipeline.rejection_reasons
    assert result.pipeline.paper_order is None
    assert drill.venue_api.posts == 0
    # The deterministic risk decision itself is untouched and still auditable.
    assert result.pipeline.risk_result is not None


async def test_meta_agent_unavailable_in_advisory_mode_changes_nothing(harness) -> None:
    drill = await harness(meta_mode=MetaAgentMode.ADVISORY)
    drill.board.arm("meta_agent_error")

    result = await drill.cycle()

    assert result is not None
    assert result.meta_review is not None
    assert result.meta_review.usable is False
    assert result.meta_review.suppressed_order is False
    assert result.pipeline.paper_order is not None
    assert result.execution_status == "submitted"
    assert drill.venue_api.posts == 1
