import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from traderstack.agents.meta import EvidencePacket, MetaAgentCall, MetaAgentDecision
from traderstack.agents.prompts import PromptRegistry
from traderstack.agents.review import (
    UNAVAILABLE_REASON,
    VETO_REASON,
    DailyBudget,
    EvidenceCache,
    MetaAgentMode,
    MetaAgentReviewer,
    build_evidence_packet,
    evidence_digest,
)
from traderstack.agents.specialists import SpecialistCommittee
from traderstack.backtest import BacktestMetrics
from traderstack.features import (
    AssetFeatureVector,
    MarketFeatures,
    NarrativeFeatures,
    NewsFeatures,
    OnChainFeatures,
)
from traderstack.models import RiskDecision, RiskResult, Side, TradeProposal
from traderstack.pipeline import PaperOrderIntent, PipelineResult
from traderstack.pretrade import PreTradeCheck
from traderstack.strategies import Regime

SYMBOL = "BTC/USD"


def pipeline_result(confidence: float = 0.6) -> PipelineResult:
    proposal = TradeProposal(
        strategy_id="vertical-slice-v1",
        asset="BTC",
        side=Side.BUY,
        confidence=confidence,
        requested_notional_usd=100.0,
        thesis="deterministic consensus",
        signal_ids=["pretrade-backtest-gate-v1"],
        source_freshness_seconds=0.5,
    )
    risk_result = RiskResult(
        decision_id=proposal.decision_id,
        decision=RiskDecision.REDUCE,
        approved_notional_usd=80.0,
        reasons=["position_size_reduced"],
        policy_version="mvp-v1",
    )
    return PipelineResult(
        accepted_market_data=True,
        feature_vector=AssetFeatureVector(
            asset="BTC",
            market=MarketFeatures(
                trend_4h=0.5,
                trend_1d=0.4,
                volatility_z=0.2,
                relative_volume=1.3,
                spread_bps=4.0,
            ),
            onchain=OnChainFeatures(exchange_netflow_z=-1.5, large_wallet_accumulation=0.4),
            narrative=NarrativeFeatures(sentiment=0.3, mention_velocity_z=1.1),
            news=NewsFeatures(event_score=0.2, adverse_event=False),
            source_ids=["kraken", "coingecko"],
        ),
        pretrade_check=PreTradeCheck(
            passed=True,
            confirmed_side=Side.BUY,
            confidence=confidence,
            regime=Regime.TRENDING_UP,
            rationale="momentum + trend",
            candles_evaluated=400,
            metrics=BacktestMetrics(
                starting_equity=10_000.0,
                ending_equity=12_000.0,
                total_return=0.2,
                benchmark_return=0.1,
                excess_return=0.1,
                max_drawdown=0.05,
                sharpe=1.2,
                trades=9,
            ),
        ),
        proposal=proposal,
        risk_result=risk_result,
        paper_order=PaperOrderIntent(
            decision_id=str(proposal.decision_id),
            asset="BTC",
            side=Side.BUY,
            notional_usd=80.0,
        ),
    )


def approving(delta: float = 0.1):
    async def client(_: EvidencePacket) -> MetaAgentDecision:
        return MetaAgentDecision(
            approve=True, confidence_delta=delta, rationale="corroborated", risk_flags=[]
        )

    return client


async def vetoing(_: EvidencePacket) -> MetaAgentDecision:
    return MetaAgentDecision(
        approve=False, confidence_delta=-0.1, rationale="thin evidence", risk_flags=["stale"]
    )


async def exploding(_: EvidencePacket) -> MetaAgentDecision:
    raise RuntimeError("provider down")


async def hanging(_: EvidencePacket) -> MetaAgentDecision:
    await asyncio.sleep(5)
    raise AssertionError("should have timed out")


def reviewer(mode: MetaAgentMode, client=None, **kwargs) -> MetaAgentReviewer:
    kwargs.setdefault("cache", EvidenceCache(ttl_seconds=0))
    kwargs.setdefault("budget", DailyBudget())
    return MetaAgentReviewer(client=client, mode=mode, model="test-model", **kwargs)


# --- evidence packet ------------------------------------------------------


def test_evidence_packet_carries_pretrade_risk_and_specialist_context() -> None:
    packet = build_evidence_packet(SYMBOL, pipeline_result(), SpecialistCommittee())

    assert packet is not None
    assert packet.asset == "BTC"
    assert packet.requested_notional_usd == 100.0
    assert packet.pretrade is not None
    assert packet.pretrade.passed is True
    assert packet.pretrade.sharpe == pytest.approx(1.2)
    assert packet.pretrade.excess_return == pytest.approx(0.1)
    assert packet.risk is not None
    assert packet.risk.decision is RiskDecision.REDUCE
    assert packet.risk.reasons == ["position_size_reduced"]
    # External-intelligence feature fields travel with the packet.
    assert packet.feature_vector.onchain.exchange_netflow_z == pytest.approx(-1.5)
    assert packet.feature_vector.narrative.sentiment == pytest.approx(0.3)
    assert {s.strategy_id for s in packet.specialist_signals} == {
        "technical_specialist_v1",
        "onchain_specialist_v1",
        "narrative_specialist_v1",
    }


def test_no_evidence_packet_without_a_proposal() -> None:
    rejected = PipelineResult(accepted_market_data=False, rejection_reasons=["stale_primary_tick"])

    assert build_evidence_packet(SYMBOL, rejected, SpecialistCommittee()) is None


def test_evidence_digest_ignores_observation_time_only() -> None:
    first = build_evidence_packet(SYMBOL, pipeline_result(), SpecialistCommittee())
    assert first is not None

    later = first.model_copy(deep=True)
    later.feature_vector.observed_at = datetime.now(UTC) + timedelta(minutes=5)
    assert evidence_digest(first) == evidence_digest(later)

    changed = first.model_copy(deep=True)
    changed.feature_vector.market.trend_4h = 0.9
    assert evidence_digest(first) != evidence_digest(changed)


# --- modes ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_off_mode_never_calls_the_model() -> None:
    called = False

    async def client(_: EvidencePacket) -> MetaAgentDecision:
        nonlocal called
        called = True
        return MetaAgentDecision(approve=True, confidence_delta=0.0, rationale="x")

    result, review = await reviewer(MetaAgentMode.OFF, client).run(SYMBOL, pipeline_result())

    assert called is False
    assert review.called is False
    assert result.paper_order is not None


@pytest.mark.asyncio
async def test_advisory_mode_records_a_veto_without_blocking() -> None:
    result, review = await reviewer(MetaAgentMode.ADVISORY, vetoing).run(SYMBOL, pipeline_result())

    assert review.called is True
    assert review.approved is False
    assert review.rationale == "thin evidence"
    assert review.risk_flags == ["stale"]
    assert review.prompt_version and review.prompt_hash.startswith("sha256:")
    assert review.latency_seconds is not None
    # Advisory changes nothing about execution.
    assert review.suppressed_order is False
    assert result.paper_order is not None
    assert result.rejection_reasons == []
    assert result.proposal is not None
    assert result.proposal.confidence == pytest.approx(0.6)


@pytest.mark.asyncio
async def test_advisory_mode_never_blocks_even_when_the_model_fails() -> None:
    result, review = await reviewer(MetaAgentMode.ADVISORY, exploding).run(
        SYMBOL, pipeline_result()
    )

    assert review.error is not None
    assert result.paper_order is not None
    assert result.rejection_reasons == []


@pytest.mark.asyncio
async def test_veto_mode_suppresses_the_paper_order_on_veto() -> None:
    result, review = await reviewer(MetaAgentMode.VETO, vetoing).run(SYMBOL, pipeline_result())

    assert result.paper_order is None
    assert VETO_REASON in result.rejection_reasons
    assert review.suppressed_order is True
    assert review.suppression_reason == VETO_REASON
    # The deterministic record is left untouched.
    assert result.risk_result is not None
    assert result.risk_result.approved_notional_usd == 80.0


@pytest.mark.asyncio
async def test_veto_mode_fails_closed_on_an_exception() -> None:
    result, review = await reviewer(MetaAgentMode.VETO, exploding).run(SYMBOL, pipeline_result())

    assert result.paper_order is None
    assert UNAVAILABLE_REASON in result.rejection_reasons
    assert review.approved is None
    assert "RuntimeError" in (review.error or "")


@pytest.mark.asyncio
async def test_veto_mode_fails_closed_on_timeout() -> None:
    result, review = await reviewer(
        MetaAgentMode.VETO, hanging, timeout_seconds=0.01
    ).run(SYMBOL, pipeline_result())

    assert result.paper_order is None
    assert UNAVAILABLE_REASON in result.rejection_reasons
    assert "timeout" in (review.error or "")


@pytest.mark.asyncio
async def test_veto_mode_fails_closed_without_a_client() -> None:
    result, review = await reviewer(MetaAgentMode.VETO, None).run(SYMBOL, pipeline_result())

    assert result.paper_order is None
    assert UNAVAILABLE_REASON in result.rejection_reasons
    assert review.called is False


@pytest.mark.asyncio
async def test_veto_mode_fails_closed_on_an_invalid_model_reply() -> None:
    async def client(_: EvidencePacket) -> MetaAgentDecision:
        # A reply the schema cannot accept must not become an approval.
        return MetaAgentDecision.model_validate(
            {"approve": True, "confidence_delta": 0.9, "rationale": "trust me"}
        )

    result, review = await reviewer(MetaAgentMode.VETO, client).run(SYMBOL, pipeline_result())

    assert result.paper_order is None
    assert UNAVAILABLE_REASON in result.rejection_reasons
    assert "ValidationError" in (review.error or "")


@pytest.mark.asyncio
async def test_veto_mode_approval_applies_the_bounded_delta() -> None:
    result, review = await reviewer(MetaAgentMode.VETO, approving(0.1)).run(
        SYMBOL, pipeline_result(0.6)
    )

    assert result.paper_order is not None
    assert result.rejection_reasons == []
    assert result.proposal is not None
    assert result.proposal.confidence == pytest.approx(0.7)
    assert review.applied_confidence == pytest.approx(0.7)


@pytest.mark.asyncio
async def test_approval_clamps_confidence_into_the_unit_interval() -> None:
    high, _ = await reviewer(MetaAgentMode.VETO, approving(0.15)).run(
        SYMBOL, pipeline_result(0.95)
    )
    low, _ = await reviewer(MetaAgentMode.VETO, approving(-0.15)).run(
        SYMBOL, pipeline_result(0.05)
    )

    assert high.proposal is not None and high.proposal.confidence == pytest.approx(1.0)
    assert low.proposal is not None and low.proposal.confidence == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_approval_never_enlarges_the_approved_notional() -> None:
    before = pipeline_result(0.6)
    after, _ = await reviewer(MetaAgentMode.VETO, approving(0.15)).run(SYMBOL, before)

    assert after.paper_order is not None and before.paper_order is not None
    assert after.paper_order.notional_usd == before.paper_order.notional_usd
    assert after.proposal is not None and before.proposal is not None
    assert after.proposal.requested_notional_usd == before.proposal.requested_notional_usd
    assert after.proposal.side is before.proposal.side
    assert after.proposal.asset == before.proposal.asset


@pytest.mark.asyncio
async def test_rejected_cycles_are_not_reviewed() -> None:
    calls = 0

    async def client(_: EvidencePacket) -> MetaAgentDecision:
        nonlocal calls
        calls += 1
        return MetaAgentDecision(approve=True, confidence_delta=0.0, rationale="x")

    rejected = PipelineResult(accepted_market_data=False, rejection_reasons=["stale_primary_tick"])
    result, review = await reviewer(MetaAgentMode.VETO, client).run(SYMBOL, rejected)

    assert calls == 0
    assert review.called is False
    assert result.rejection_reasons == ["stale_primary_tick"]


# --- cost controls --------------------------------------------------------


@pytest.mark.asyncio
async def test_cache_prevents_a_second_call_for_identical_evidence() -> None:
    calls = 0

    async def client(_: EvidencePacket) -> MetaAgentDecision:
        nonlocal calls
        calls += 1
        return MetaAgentDecision(approve=True, confidence_delta=0.05, rationale="ok")

    agent = reviewer(MetaAgentMode.ADVISORY, client, cache=EvidenceCache(ttl_seconds=60))
    result = pipeline_result()

    first = await agent.review(SYMBOL, result)
    second = await agent.review(SYMBOL, result)

    assert calls == 1
    assert first.cached is False
    assert second.cached is True
    assert second.approved is True
    assert agent.budget.calls == 1


@pytest.mark.asyncio
async def test_cache_misses_when_the_evidence_changes() -> None:
    calls = 0

    async def client(_: EvidencePacket) -> MetaAgentDecision:
        nonlocal calls
        calls += 1
        return MetaAgentDecision(approve=True, confidence_delta=0.0, rationale="ok")

    agent = reviewer(MetaAgentMode.ADVISORY, client, cache=EvidenceCache(ttl_seconds=60))

    await agent.review(SYMBOL, pipeline_result(0.6))
    await agent.review(SYMBOL, pipeline_result(0.4))

    assert calls == 2


@pytest.mark.asyncio
async def test_failed_reviews_are_not_cached() -> None:
    calls = 0

    async def client(_: EvidencePacket) -> MetaAgentDecision:
        nonlocal calls
        calls += 1
        raise RuntimeError("provider down")

    agent = reviewer(MetaAgentMode.ADVISORY, client, cache=EvidenceCache(ttl_seconds=60))
    result = pipeline_result()

    await agent.review(SYMBOL, result)
    await agent.review(SYMBOL, result)

    assert calls == 2


@pytest.mark.asyncio
async def test_veto_mode_fails_closed_when_the_daily_call_budget_is_exhausted() -> None:
    agent = reviewer(
        MetaAgentMode.VETO, approving(0.1), budget=DailyBudget(max_calls=1)
    )

    first, _ = await agent.run(SYMBOL, pipeline_result(0.6))
    second, review = await agent.run(SYMBOL, pipeline_result(0.4))

    assert first.paper_order is not None
    assert second.paper_order is None
    assert UNAVAILABLE_REASON in second.rejection_reasons
    assert review.error == "daily_call_budget_exhausted"
    assert review.called is False


@pytest.mark.asyncio
async def test_veto_mode_fails_closed_when_the_daily_token_budget_is_exhausted() -> None:
    class TokenHungryClient:
        async def review(self, _: EvidencePacket) -> MetaAgentCall:
            return MetaAgentCall(
                decision=MetaAgentDecision(
                    approve=True, confidence_delta=0.0, rationale="ok"
                ),
                model="test-model",
                input_tokens=900,
                output_tokens=200,
            )

    agent = reviewer(
        MetaAgentMode.VETO, TokenHungryClient(), budget=DailyBudget(max_tokens=1_000)
    )

    first, first_review = await agent.run(SYMBOL, pipeline_result(0.6))
    second, second_review = await agent.run(SYMBOL, pipeline_result(0.4))

    assert first.paper_order is not None
    assert first_review.input_tokens == 900
    assert first_review.output_tokens == 200
    assert second.paper_order is None
    assert second_review.error == "daily_token_budget_exhausted"


@pytest.mark.asyncio
async def test_usage_reporting_client_populates_cost_and_model() -> None:
    class UsageClient:
        async def review(self, _: EvidencePacket) -> MetaAgentCall:
            return MetaAgentCall(
                decision=MetaAgentDecision(
                    approve=True, confidence_delta=0.0, rationale="ok"
                ),
                model="claude-test",
                input_tokens=1_000_000,
                output_tokens=1_000_000,
            )

    agent = reviewer(
        MetaAgentMode.ADVISORY,
        UsageClient(),
        input_cost_per_mtok=1.0,
        output_cost_per_mtok=5.0,
    )
    review = await agent.review(SYMBOL, pipeline_result())

    assert review.model == "claude-test"
    assert review.estimated_cost_usd == pytest.approx(6.0)


def test_daily_budget_resets_on_a_new_utc_day() -> None:
    budget = DailyBudget(max_calls=1)
    today = datetime(2026, 9, 4, 23, 30, tzinfo=UTC)
    budget.record(10, now=today)

    assert budget.exhausted(now=today) == "daily_call_budget_exhausted"
    assert budget.exhausted(now=today + timedelta(hours=1)) is None


# --- prompt versioning ----------------------------------------------------


@pytest.mark.asyncio
async def test_every_review_records_the_prompt_version_and_hash() -> None:
    prompt = PromptRegistry().register("meta_agent_review", "test-v9", "review carefully")
    agent = reviewer(MetaAgentMode.ADVISORY, approving(0.0), prompt=prompt)

    review = await agent.review(SYMBOL, pipeline_result())

    assert review.prompt_version == "test-v9"
    assert review.prompt_hash == prompt.content_hash
