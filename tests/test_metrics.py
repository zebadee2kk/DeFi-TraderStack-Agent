import asyncio

import pytest
from prometheus_client import REGISTRY

from traderstack import metrics
from traderstack.market.models import MarketSource, ReferencePrice
from traderstack.models import RiskDecision, RiskResult, Side, TradeProposal
from traderstack.pipeline import PaperOrderIntent, PipelineResult


def _counter_value(name: str, **labels: str) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


def test_record_pipeline_result_counts_outcome_and_rejection_reasons() -> None:
    before = _counter_value(
        "traderstack_pipeline_outcomes_total", symbol="BTC/USD", outcome="rejected"
    )
    before_reason = _counter_value(
        "traderstack_pipeline_rejections_total", symbol="BTC/USD", reason="stale_primary_tick"
    )

    result = PipelineResult(accepted_market_data=False, rejection_reasons=["stale_primary_tick"])
    metrics.record_pipeline_result("BTC/USD", result)

    assert (
        _counter_value("traderstack_pipeline_outcomes_total", symbol="BTC/USD", outcome="rejected")
        == before + 1
    )
    assert (
        _counter_value(
            "traderstack_pipeline_rejections_total", symbol="BTC/USD", reason="stale_primary_tick"
        )
        == before_reason + 1
    )


def test_record_pipeline_result_counts_proposal_and_risk_decision() -> None:
    proposal = TradeProposal(
        strategy_id="s",
        asset="BTC",
        side=Side.BUY,
        confidence=0.5,
        requested_notional_usd=100,
        thesis="t",
        source_freshness_seconds=0,
    )
    risk_result = RiskResult(
        decision_id=proposal.decision_id,
        decision=RiskDecision.ALLOW,
        approved_notional_usd=100,
        policy_version="v1",
    )
    order = PaperOrderIntent(
        decision_id=str(proposal.decision_id), asset="BTC", side=Side.BUY, notional_usd=100
    )
    result = PipelineResult(
        accepted_market_data=True, proposal=proposal, risk_result=risk_result, paper_order=order
    )

    before_proposals = _counter_value("traderstack_proposals_total", symbol="ETH/USD")
    before_allow = _counter_value(
        "traderstack_risk_decisions_total", symbol="ETH/USD", decision="allow"
    )

    metrics.record_pipeline_result("ETH/USD", result)

    assert _counter_value("traderstack_proposals_total", symbol="ETH/USD") == before_proposals + 1
    assert (
        _counter_value("traderstack_risk_decisions_total", symbol="ETH/USD", decision="allow")
        == before_allow + 1
    )


def test_record_paper_order_submitted() -> None:
    before = _counter_value(
        "traderstack_paper_orders_submitted_total", symbol="SOL/USD", side="buy"
    )
    metrics.record_paper_order_submitted("SOL/USD", "buy")
    assert (
        _counter_value("traderstack_paper_orders_submitted_total", symbol="SOL/USD", side="buy")
        == before + 1
    )


def test_record_candles_loaded_sets_gauge() -> None:
    metrics.record_candles_loaded("BTC/USD", 250)
    assert (
        REGISTRY.get_sample_value("traderstack_candle_history_size", {"symbol": "BTC/USD"}) == 250
    )


def test_record_provider_fetch_records_latency_and_failure() -> None:
    before_failures = _counter_value(
        "traderstack_provider_fetch_failures_total", provider="test", kind="ping"
    )
    before_count = _counter_value(
        "traderstack_provider_fetch_latency_seconds_count", provider="test", kind="ping"
    )

    metrics.record_provider_fetch("test", "ping", 0.01, failed=False)
    metrics.record_provider_fetch("test", "ping", 0.02, failed=True)

    assert (
        _counter_value("traderstack_provider_fetch_failures_total", provider="test", kind="ping")
        == before_failures + 1
    )
    assert (
        _counter_value(
            "traderstack_provider_fetch_latency_seconds_count", provider="test", kind="ping"
        )
        == before_count + 2
    )


def test_record_portfolio_snapshot_sets_nav_cash_and_drawdown() -> None:
    metrics.record_portfolio_snapshot(nav_usd=9_000, cash_usd=1_000, peak_nav_usd=10_000)
    assert REGISTRY.get_sample_value("traderstack_portfolio_nav_usd") == 9_000
    assert REGISTRY.get_sample_value("traderstack_portfolio_cash_usd") == 1_000
    assert REGISTRY.get_sample_value("traderstack_portfolio_drawdown_pct") == pytest.approx(0.1)


def test_record_event_sink_failure() -> None:
    before = _counter_value("traderstack_event_sink_failures_total", sink="redis")
    metrics.record_event_sink_failure("redis")
    assert _counter_value("traderstack_event_sink_failures_total", sink="redis") == before + 1


@pytest.mark.asyncio
async def test_timed_provider_call_records_success() -> None:
    before_count = _counter_value(
        "traderstack_provider_fetch_latency_seconds_count",
        provider="coingecko",
        kind="reference_price",
    )

    async def ok() -> list[ReferencePrice]:
        return [ReferencePrice(source=MarketSource.COINGECKO, asset="BTC", price=100)]

    result = await metrics.timed_provider_call("coingecko", "reference_price", ok())

    assert result[0].asset == "BTC"
    assert (
        _counter_value(
            "traderstack_provider_fetch_latency_seconds_count",
            provider="coingecko",
            kind="reference_price",
        )
        == before_count + 1
    )


@pytest.mark.asyncio
async def test_timed_provider_call_records_and_reraises_failure() -> None:
    before_failures = _counter_value(
        "traderstack_provider_fetch_failures_total", provider="broken", kind="reference_price"
    )

    async def boom() -> None:
        raise RuntimeError("provider unavailable")

    with pytest.raises(RuntimeError, match="provider unavailable"):
        await metrics.timed_provider_call("broken", "reference_price", boom())

    assert (
        _counter_value(
            "traderstack_provider_fetch_failures_total", provider="broken", kind="reference_price"
        )
        == before_failures + 1
    )


def test_timed_provider_call_is_a_coroutine_function() -> None:
    assert asyncio.iscoroutinefunction(metrics.timed_provider_call)
