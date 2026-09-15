"""The on-chain regime gate (#139) can only withhold new longs.

It cannot raise approved notional, cannot flip a side, cannot clear a
reject through an approving meta-agent, and a provider outage fails closed
for this slot without freezing exits or halting the cycle. RiskEngine
(Zone C) sees exactly the same proposal, features and limits with the gate
on or off. Hostile provider payloads never yield a snapshot that passes.
"""

from __future__ import annotations

import math
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from traderstack.agents.meta import EvidencePacket, MetaAgentDecision
from traderstack.agents.review import MetaAgentMode, MetaAgentReviewer
from traderstack.config import Settings
from traderstack.intelligence import OnChainRegimeSnapshot
from traderstack.intelligence_orchestrator import ExternalIntelligence, IntelligenceOrchestrator
from traderstack.market.coinmetrics import (
    COINMETRICS_SOURCE_ID,
    ONCHAIN_REGIME_FEATURE_VERSION,
    derive_regime_series,
    parse_asset_metric_rows,
)
from traderstack.market.models import MarketSource, MarketTick, ReferencePrice
from traderstack.models import HeldPosition, PortfolioSnapshot, Side
from traderstack.pipeline import (
    ONCHAIN_REGIME_BLOCKED_REASON,
    ONCHAIN_REGIME_UNAVAILABLE_REASON,
    VerticalSlicePipeline,
)
from traderstack.risk import RiskEngine
from traderstack.runtime import PaperRuntime

NOW = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "database_url": "postgresql+asyncpg://x:x@localhost/x",
        "redis_url": "redis://localhost:6379/0",
        "kill_switch": False,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


def _engine() -> RiskEngine:
    return RiskEngine(_settings())


def _pipeline(**overrides: object) -> VerticalSlicePipeline:
    return VerticalSlicePipeline(risk_engine=_engine(), **overrides)  # type: ignore[arg-type]


def _tick() -> MarketTick:
    return MarketTick(
        source=MarketSource.KRAKEN, symbol="BTC/USD", bid=999.5, ask=1000.5, last=1000
    )


def _refs() -> list[ReferencePrice]:
    return [ReferencePrice(source=MarketSource.COINGECKO, asset="BTC", price=1000)]


def _portfolio() -> PortfolioSnapshot:
    return PortfolioSnapshot(nav_usd=10_000, cash_usd=10_000, daily_pnl_usd=0, peak_nav_usd=10_000)


def _snapshot(pct: float | None, *, nupl: float | None = 0.2) -> OnChainRegimeSnapshot:
    return OnChainRegimeSnapshot(
        asset="BTC",
        source_asset="btc",
        as_of=date(2026, 9, 13),
        mvrv_z=1.0 if pct is not None else None,
        mvrv_z_percentile=pct,
        nupl=nupl,
        points=1460,
        window_days=1460,
        feature_version=ONCHAIN_REGIME_FEATURE_VERSION,
        source_id=COINMETRICS_SOURCE_ID,
    )


def _bundle(snapshot: OnChainRegimeSnapshot | None) -> ExternalIntelligence:
    return ExternalIntelligence(asset="BTC", onchain_regime=snapshot)


# --- 1. hot regime blocks new longs; nothing is sized ------------------------------


def test_hot_regime_blocks_buy_and_leaves_notional_unset() -> None:
    result = _pipeline(onchain_regime_gate=True).process(
        _tick(), _refs(), _portfolio(), intelligence=_bundle(_snapshot(0.95))
    )
    assert result.rejection_reasons == [ONCHAIN_REGIME_BLOCKED_REASON]
    assert result.proposal is None
    assert result.risk_result is None
    assert result.paper_order is None
    assert result.feature_vector is not None
    assert result.feature_vector.onchain.mvrv_z_percentile == pytest.approx(0.95)


def test_threshold_is_exclusive_and_comes_from_the_pipeline_only() -> None:
    at_threshold = _pipeline(onchain_regime_gate=True, onchain_regime_max_percentile=0.90).process(
        _tick(), _refs(), _portfolio(), intelligence=_bundle(_snapshot(0.90))
    )
    assert at_threshold.rejection_reasons == []
    assert at_threshold.paper_order is not None
    tighter = _pipeline(onchain_regime_gate=True, onchain_regime_max_percentile=0.50).process(
        _tick(), _refs(), _portfolio(), intelligence=_bundle(_snapshot(0.60))
    )
    assert tighter.rejection_reasons == [ONCHAIN_REGIME_BLOCKED_REASON]


def test_gate_off_ignores_the_regime_entirely() -> None:
    result = _pipeline(onchain_regime_gate=False).process(
        _tick(), _refs(), _portfolio(), intelligence=_bundle(_snapshot(0.99))
    )
    assert result.rejection_reasons == []
    assert result.paper_order is not None


# --- 2. outage fails closed for the slot; exits and the cycle continue -----------


def test_missing_regime_fails_closed_for_new_longs_only() -> None:
    for bundle in (_bundle(None), _bundle(_snapshot(None)), None):
        result = _pipeline(onchain_regime_gate=True).process(
            _tick(), _refs(), _portfolio(), intelligence=bundle
        )
        assert result.accepted_market_data is True
        assert result.rejection_reasons == [ONCHAIN_REGIME_UNAVAILABLE_REASON]
        assert result.proposal is None and result.paper_order is None


def test_outage_does_not_freeze_a_stop_loss_exit() -> None:
    held = HeldPosition(
        quantity=0.1,
        average_cost_usd=1_200,
        exposure_usd=100,
        opened_at=NOW,
        high_water_price_usd=1_200,
        entry_strategy_id="vertical-slice-v1",
    )
    portfolio = PortfolioSnapshot(
        nav_usd=10_000,
        cash_usd=9_900,
        daily_pnl_usd=0,
        peak_nav_usd=10_000,
        asset_exposure_usd={"BTC": 100},
        held_positions={"BTC": held},
    )
    result = _pipeline(onchain_regime_gate=True).process(
        _tick(), _refs(), portfolio, intelligence=_bundle(None)
    )
    assert result.exit_reason == "exit_stop_loss"
    assert result.proposal is not None and result.proposal.side is Side.SELL
    assert result.paper_order is not None and result.paper_order.side is Side.SELL
    assert ONCHAIN_REGIME_UNAVAILABLE_REASON not in result.rejection_reasons


# --- 3. a passing regime cannot raise notional or flip side ------------------------


def test_passing_regime_yields_identical_notional_and_side_to_gate_off() -> None:
    gate_on = _pipeline(onchain_regime_gate=True).process(
        _tick(), _refs(), _portfolio(), intelligence=_bundle(_snapshot(0.10))
    )
    gate_off = _pipeline(onchain_regime_gate=False).process(
        _tick(), _refs(), _portfolio(), intelligence=_bundle(_snapshot(0.10))
    )
    assert gate_on.paper_order is not None and gate_off.paper_order is not None
    assert gate_on.paper_order.side is Side.BUY and gate_off.paper_order.side is Side.BUY
    assert gate_on.paper_order.notional_usd == pytest.approx(gate_off.paper_order.notional_usd)
    assert gate_on.risk_result is not None and gate_off.risk_result is not None
    assert gate_on.risk_result.approved_notional_usd == pytest.approx(
        gate_off.risk_result.approved_notional_usd
    )
    assert gate_on.proposal is not None and gate_off.proposal is not None
    assert gate_on.proposal.requested_notional_usd == pytest.approx(
        gate_off.proposal.requested_notional_usd
    )


# --- 4. an approving meta-agent cannot clear the block ---------------------------


class _Venue:
    async def stream_ticks(self, symbols: tuple[str, ...]) -> AsyncIterator[MarketTick]:
        yield MarketTick(
            source=MarketSource.KRAKEN, symbol=symbols[0], bid=99.95, ask=100.05, last=100
        )


class _Reference:
    async def get_prices(self, assets: tuple[str, ...]) -> list[ReferencePrice]:
        return [ReferencePrice(source=MarketSource.COINGECKO, asset=assets[0], price=100)]


@pytest.mark.asyncio
async def test_meta_agent_approval_cannot_authorise_after_regime_outage() -> None:
    async def broken(_asset: str) -> OnChainRegimeSnapshot:
        raise TimeoutError("community-api down")

    async def approve(_: EvidencePacket) -> MetaAgentDecision:
        return MetaAgentDecision(
            approve=True, confidence_delta=0.15, rationale="authorise anyway", risk_flags=[]
        )

    runtime = PaperRuntime(
        venue=_Venue(),
        references=(_Reference(),),
        pipeline=_pipeline(onchain_regime_gate=True),
        intelligence=IntelligenceOrchestrator(onchain_regime=broken),
        meta_reviewer=MetaAgentReviewer(client=approve, mode=MetaAgentMode.VETO),
    )
    result = await runtime.run_once("BTC/USD", _portfolio())
    assert result.pipeline.rejection_reasons == [ONCHAIN_REGIME_UNAVAILABLE_REASON]
    assert result.pipeline.paper_order is None
    assert result.pipeline.proposal is None
    assert result.execution_receipt is None
    if result.meta_review is not None:
        assert result.meta_review.called is False


@pytest.mark.asyncio
async def test_meta_agent_approval_cannot_clear_a_hot_regime_block() -> None:
    async def hot(_asset: str) -> OnChainRegimeSnapshot:
        return _snapshot(0.97)

    async def approve(_: EvidencePacket) -> MetaAgentDecision:
        return MetaAgentDecision(
            approve=True, confidence_delta=0.15, rationale="looks fine", risk_flags=[]
        )

    runtime = PaperRuntime(
        venue=_Venue(),
        references=(_Reference(),),
        pipeline=_pipeline(onchain_regime_gate=True),
        intelligence=IntelligenceOrchestrator(onchain_regime=hot),
        meta_reviewer=MetaAgentReviewer(client=approve, mode=MetaAgentMode.VETO),
    )
    result = await runtime.run_once("BTC/USD", _portfolio())
    assert result.pipeline.rejection_reasons == [ONCHAIN_REGIME_BLOCKED_REASON]
    assert result.pipeline.paper_order is None
    assert result.intelligence_sources == [COINMETRICS_SOURCE_ID]
    if result.meta_review is not None:
        assert result.meta_review.called is False


# --- 5. hostile payloads never yield a passing snapshot ---------------------------


@pytest.mark.parametrize("pct", ["5", 5.0, -0.2, math.nan, math.inf])
def test_out_of_range_percentile_never_becomes_a_snapshot(pct: object) -> None:
    with pytest.raises(ValidationError):
        OnChainRegimeSnapshot(
            asset="BTC",
            source_asset="btc",
            as_of=date(2026, 9, 13),
            mvrv_z=0.0,
            mvrv_z_percentile=pct,  # type: ignore[arg-type]
            nupl=0.1,
            points=1,
            window_days=1460,
            feature_version="x",
            source_id="x",
        )


def test_hostile_provider_rows_reduce_to_nothing_usable() -> None:
    payload = {
        "data": [
            {
                "asset": "btc",
                "time": "2026-09-01T00:00:00.000000000Z",
                "CapMVRVCur": "-3",  # negative MVRV
                "CapMrktCurUSD": "1e12",
                "mvrv_z_percentile": "0.0",  # extra field: ignored
                "approve": True,
            },
            {
                "asset": "btc",
                "time": "2026-09-02T00:00:00.000000000Z",
                "CapMVRVCur": "NaN",
                "CapMrktCurUSD": "1e12",
            },
            {
                "asset": "btc",
                "time": "2026-09-03T00:00:00.000000000Z",
                "CapMVRVCur": "1.1",
                "CapMrktCurUSD": "inf",
            },
        ]
    }
    rows = parse_asset_metric_rows(payload, asset="btc")
    assert rows == ()
    assert derive_regime_series(rows) == ()
    # Even a hostile "percentile" delivered on an otherwise valid row is not read.
    good = parse_asset_metric_rows(
        {
            "data": [
                {
                    "asset": "btc",
                    "time": "2026-09-04T00:00:00Z",
                    "CapMVRVCur": "1.1",
                    "CapMrktCurUSD": "1e12",
                    "mvrv_z_percentile": "0.0",
                }
            ]
        },
        asset="btc",
    )
    series = derive_regime_series(good)
    assert len(series) == 1 and series[0].mvrv_z_percentile is None
    # Which the gate treats as unavailable → reject, never allow.
    result = _pipeline(onchain_regime_gate=True).process(
        _tick(), _refs(), _portfolio(), intelligence=_bundle(_snapshot(None))
    )
    assert result.rejection_reasons == [ONCHAIN_REGIME_UNAVAILABLE_REASON]


# --- 6. Zone C is untouched ----------------------------------------------------------


def test_risk_engine_output_and_policy_version_are_identical_with_gate_on_and_off() -> None:
    on = _pipeline(onchain_regime_gate=True)
    off = _pipeline(onchain_regime_gate=False)
    assert on.risk_engine.policy_version == off.risk_engine.policy_version
    assert on.risk_engine.risk_limits == off.risk_engine.risk_limits
    result_on = on.process(_tick(), _refs(), _portfolio(), intelligence=_bundle(_snapshot(0.10)))
    result_off = off.process(_tick(), _refs(), _portfolio(), intelligence=_bundle(_snapshot(0.10)))
    assert result_on.risk_result is not None and result_off.risk_result is not None
    assert result_on.risk_result.decision is result_off.risk_result.decision
    assert result_on.risk_result.reasons == result_off.risk_result.reasons
    assert result_on.risk_result.policy_version == result_off.risk_result.policy_version
    # The threshold is not on the feature vector, so nothing a provider
    # returns can move it.
    assert result_on.feature_vector is not None
    assert not hasattr(result_on.feature_vector.onchain, "onchain_regime_max_percentile")
