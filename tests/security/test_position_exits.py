"""Exits stay Zone C: no LLM veto, no oversize, no thesis-text trigger."""

from __future__ import annotations

import inspect  # --- protective exit sizing (#130) ---
from datetime import UTC, datetime

import pytest

from traderstack.agents.meta import EvidencePacket, MetaAgentDecision
from traderstack.agents.review import MetaAgentMode, MetaAgentReviewer
from traderstack.config import Settings
from traderstack.execution.ledger import ExecutionLedger  # --- #130 ---
from traderstack.execution.paper_fill import (  # --- #130 ---
    PaperFillRejectReason,
    PaperFillSimulator,
    PaperFillStatus,
)
from traderstack.execution.planner import ExecutionPlanner  # --- #130 ---
from traderstack.exits import evaluate_position_exits
from traderstack.features import AssetFeatureVector, MarketFeatures
from traderstack.market.models import MarketSource, MarketTick, ReferencePrice  # --- #130 ---
from traderstack.models import (
    HeldPosition,
    PortfolioSnapshot,
    RiskDecision,
    RiskResult,
    Side,
    TradeProposal,
)
from traderstack.pipeline import PaperOrderIntent, PipelineResult, VerticalSlicePipeline
from traderstack.portfolio import InMemoryPortfolioBook  # --- #130 ---
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


# --- protective exit sizing (#130) ---


def _capped_exit_intent(
    *, notional: float = 100.0, max_quantity: float | None = 1.0
) -> PaperOrderIntent:
    return PaperOrderIntent(
        decision_id="exit-130",
        asset="BTC",
        side=Side.SELL,
        notional_usd=notional,
        max_quantity=max_quantity,
    )


def test_max_quantity_cannot_scale_a_plan_above_notional_over_price() -> None:
    planner = ExecutionPlanner(lot_step=1e-8, min_notional_usd=10)
    baseline = planner.plan(
        _capped_exit_intent(max_quantity=None),
        execution_price_usd=99.95,
        reference_price_usd=100.0,
    )
    hostile = planner.plan(
        _capped_exit_intent(max_quantity=100.0 * baseline.quantity),
        execution_price_usd=99.95,
        reference_price_usd=100.0,
    )
    assert hostile.quantity == pytest.approx(baseline.quantity)
    assert hostile.notional_usd <= hostile.requested_notional_usd + 1e-9
    assert hostile.quantity_capped_to_position is False


def test_hostile_max_quantity_above_the_book_cannot_create_a_short() -> None:
    book = InMemoryPortfolioBook(starting_nav_usd=10_000)
    book.apply_fill("BTC", Side.BUY, 0.25, 100.0)
    book.mark("BTC", 100.0)
    cash_before = book.cash_usd
    ledger = ExecutionLedger()

    outcome = PaperFillSimulator(paper_slippage_bps=5.0).apply(
        _capped_exit_intent(notional=100.0, max_quantity=1.0),
        mid_usd=100.0,
        ledger=ledger,
        portfolio=book,
    )

    assert outcome.status is PaperFillStatus.REJECTED
    assert outcome.reason_code is PaperFillRejectReason.EXIT_SIZING_INVALID
    assert book.positions["BTC"].quantity == pytest.approx(0.25)
    assert book.cash_usd == pytest.approx(cash_before)
    assert ledger.processed_fill_ids == set()


@pytest.mark.asyncio
async def test_meta_agent_leaves_max_quantity_intact_and_is_not_called_for_exits() -> None:
    called = {"n": 0}

    async def hostile(_: EvidencePacket) -> MetaAgentDecision:
        called["n"] += 1
        return MetaAgentDecision(approve=True, confidence_delta=0.15, rationale="sell more")

    base = _exit_result(notional=100.0)
    assert base.paper_order is not None
    exit_result = base.model_copy(
        update={"paper_order": base.paper_order.model_copy(update={"max_quantity": 1.0})}
    )
    reviewer = MetaAgentReviewer(client=hostile, mode=MetaAgentMode.VETO, model="hostile")
    result, review = await reviewer.run("BTC/USD", exit_result)

    assert called["n"] == 0
    assert review.called is False
    assert result.paper_order is not None
    assert result.paper_order.max_quantity == pytest.approx(1.0)
    assert result.paper_order.notional_usd == pytest.approx(100.0)
    assert result.paper_order.side is Side.SELL


def test_risk_engine_approved_notional_is_independent_of_max_quantity() -> None:
    """RiskEngine.evaluate never sees a PaperOrderIntent, so max_quantity cannot move it."""

    signature = inspect.signature(RiskEngine.evaluate)
    assert "intent" not in signature.parameters
    assert "max_quantity" not in signature.parameters
    for name, parameter in signature.parameters.items():
        if name == "self":
            continue
        assert "PaperOrderIntent" not in str(parameter.annotation)

    snapshot = PortfolioSnapshot(
        nav_usd=10_000,
        cash_usd=8_000,
        daily_pnl_usd=-100,
        peak_nav_usd=10_000,
        asset_exposure_usd={"BTC": 1_900},
        observed_at=NOW,
        held_positions={"BTC": _held(mark=19_000)},
    )
    proposal = TradeProposal(
        strategy_id="exit-stop_loss",
        asset="BTC",
        side=Side.SELL,
        confidence=1.0,
        requested_notional_usd=1_900,
        thesis="stop",
        signal_ids=["exit_stop_loss"],
        source_freshness_seconds=0.0,
        created_at=NOW,
    )
    engine = RiskEngine(_settings())
    first = engine.evaluate(proposal, snapshot, now=NOW)
    second = engine.evaluate(proposal, snapshot, now=NOW)
    assert first.approved_notional_usd == pytest.approx(second.approved_notional_usd)
    assert first.approved_notional_usd <= proposal.requested_notional_usd

    # The pipeline sets max_quantity from the snapshot only; the intent's
    # notional is exactly the engine's approved notional, never more.
    pipe = VerticalSlicePipeline(risk_engine=engine)
    tick = MarketTick(
        source=MarketSource.KRAKEN,
        symbol="BTC/USD",
        observed_at=NOW,
        bid=18_990,
        ask=19_010,
        last=19_000,
    )
    refs = [ReferencePrice(source=MarketSource.COINGECKO, asset="BTC", price=19_000)]
    result = pipe.process(tick, refs, snapshot, now=NOW)
    assert result.paper_order is not None
    assert result.risk_result is not None
    assert result.paper_order.notional_usd == pytest.approx(
        result.risk_result.approved_notional_usd
    )
    assert result.paper_order.max_quantity == pytest.approx(0.1)
    assert result.paper_order.max_quantity * tick.last >= result.paper_order.notional_usd - 1e-9
