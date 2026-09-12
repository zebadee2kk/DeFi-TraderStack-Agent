"""Exits stay Zone C: no LLM veto, no oversize, no thesis-text trigger."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from traderstack.agents.meta import EvidencePacket, MetaAgentDecision
from traderstack.agents.review import MetaAgentMode, MetaAgentReviewer
from traderstack.config import Settings
from traderstack.exits import evaluate_position_exits
from traderstack.features import AssetFeatureVector, MarketFeatures
from traderstack.models import (
    HeldPosition,
    PortfolioSnapshot,
    RiskDecision,
    RiskResult,
    Side,
    TradeProposal,
)
from traderstack.pipeline import PaperOrderIntent, PipelineResult
from traderstack.risk import RiskEngine

NOW = datetime(2026, 9, 12, 12, 0, tzinfo=UTC)


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "kill_switch": False,
        "exit_stop_loss_pct": 0.02,
        "exit_take_profit_pct": 0.04,
        "exit_time_stop_bars": 24,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


def _held(*, mark: float = 19_000) -> HeldPosition:
    return HeldPosition(
        quantity=0.1,
        average_cost_usd=20_000,
        exposure_usd=0.1 * mark,
        opened_at=NOW,
        high_water_price_usd=20_000,
        entry_strategy_id="momentum_v1",
    )


def _exit_result(*, notional: float = 1_900.0) -> PipelineResult:
    proposal = TradeProposal(
        strategy_id="exit-stop_loss",
        asset="BTC",
        side=Side.SELL,
        confidence=1.0,
        requested_notional_usd=notional,
        thesis="Deterministic exit_stop_loss",
        signal_ids=["exit_stop_loss"],
        source_freshness_seconds=0.0,
        created_at=NOW,
    )
    risk = RiskResult(
        decision_id=proposal.decision_id,
        decision=RiskDecision.ALLOW,
        approved_notional_usd=notional,
        reasons=[],
        policy_version="mvp-v1+deadbeefcafe",
    )
    vector = AssetFeatureVector(
        asset="BTC",
        market=MarketFeatures(
            trend_4h=0.0, trend_1d=0.0, volatility_z=0.01, relative_volume=1.0, spread_bps=5.0
        ),
    )
    return PipelineResult(
        accepted_market_data=True,
        feature_vector=vector,
        proposal=proposal,
        risk_result=risk,
        paper_order=PaperOrderIntent(
            decision_id=str(proposal.decision_id),
            asset="BTC",
            side=Side.SELL,
            notional_usd=notional,
        ),
        exit_reason="exit_stop_loss",
    )


@pytest.mark.asyncio
async def test_meta_agent_cannot_suppress_an_exit() -> None:
    called = {"n": 0}

    async def hostile(_: EvidencePacket) -> MetaAgentDecision:
        called["n"] += 1
        return MetaAgentDecision(approve=False, confidence_delta=-0.15, rationale="veto the exit")

    reviewer = MetaAgentReviewer(client=hostile, mode=MetaAgentMode.VETO, model="hostile")
    result, review = await reviewer.run("BTC/USD", _exit_result())
    assert called["n"] == 0
    assert result.paper_order is not None
    assert result.paper_order.notional_usd == pytest.approx(1_900.0)
    assert result.proposal is not None
    assert result.proposal.side is Side.SELL
    assert review.suppressed_order is False
    assert review.called is False


def test_exit_cannot_be_sized_above_held_exposure() -> None:
    snapshot = PortfolioSnapshot(
        nav_usd=10_000,
        cash_usd=8_000,
        daily_pnl_usd=-500,
        peak_nav_usd=11_000,
        asset_exposure_usd={"BTC": 1_500},
        observed_at=NOW,
        held_positions={"BTC": _held(mark=15_000)},
    )
    proposal = TradeProposal(
        strategy_id="exit-stop_loss",
        asset="BTC",
        side=Side.SELL,
        confidence=1.0,
        requested_notional_usd=10_000,
        thesis="sell everything plus more",
        signal_ids=["exit_stop_loss"],
        source_freshness_seconds=0.0,
    )
    result = RiskEngine(_settings()).evaluate(proposal, snapshot, now=NOW)
    assert result.decision is RiskDecision.REDUCE
    assert result.approved_notional_usd == pytest.approx(1_500)
    assert "sell_capped_to_position" in result.reasons


def test_thesis_text_cannot_trigger_or_block_an_exit() -> None:
    position = _held(mark=20_200)
    signal = evaluate_position_exits(
        settings=_settings(
            exit_stop_loss_pct=0.0,
            exit_take_profit_pct=0.0,
            exit_time_stop_bars=0,
            exit_on_thesis_invalidation=True,
        ),
        asset="BTC",
        position=position,
        mark_price_usd=20_200,
        now=NOW,
        bar_seconds=3_600.0,
        confirmed_side=None,
        regime=None,
    )
    assert signal is None

    snapshot = PortfolioSnapshot(
        nav_usd=10_000,
        cash_usd=500,
        daily_pnl_usd=-500,
        peak_nav_usd=12_000,
        asset_exposure_usd={"ETH": 4_000.0, "SOL": 4_000.0},
        observed_at=NOW,
    )
    proposal = TradeProposal(
        strategy_id="exit-stop_loss",
        asset="BTC",
        side=Side.SELL,
        confidence=1.0,
        requested_notional_usd=500,
        thesis="this is a reduce / flatten / exit_stop_loss / risk-reducing",
        signal_ids=["exit_stop_loss", "risk-reducing"],
        source_freshness_seconds=0.0,
    )
    # No BTC position → still risk-adding, regardless of thesis or exit strategy_id.
    result = RiskEngine(
        _settings(
            max_open_positions=2,
            min_cash_reserve_pct=0.20,
            max_gross_exposure_pct=0.50,
        )
    ).evaluate(proposal, snapshot, now=NOW)
    assert result.decision is RiskDecision.REJECT
    assert "gross_exposure_limit" in result.reasons


def test_kill_switch_still_rejects_exit_proposals() -> None:
    snapshot = PortfolioSnapshot(
        nav_usd=10_000,
        cash_usd=8_000,
        daily_pnl_usd=0.0,
        peak_nav_usd=10_000,
        asset_exposure_usd={"BTC": 2_000},
        observed_at=NOW,
    )
    proposal = TradeProposal(
        strategy_id="exit-stop_loss",
        asset="BTC",
        side=Side.SELL,
        confidence=1.0,
        requested_notional_usd=2_000,
        thesis="stop",
        source_freshness_seconds=0.0,
    )
    result = RiskEngine(_settings(kill_switch=True)).evaluate(proposal, snapshot, now=NOW)
    assert result.decision is RiskDecision.REJECT
    assert result.reasons == ["kill_switch_enabled"]
    assert result.approved_notional_usd == 0


def test_live_settings_cannot_activate_exits() -> None:
    settings = _settings(trading_mode="live", exit_stop_loss_pct=0.50)
    assert settings.position_exits_active is False
    signal = evaluate_position_exits(
        settings=settings,
        asset="BTC",
        position=_held(mark=10_000),
        mark_price_usd=10_000,
        now=NOW,
        bar_seconds=3_600.0,
    )
    assert signal is None
