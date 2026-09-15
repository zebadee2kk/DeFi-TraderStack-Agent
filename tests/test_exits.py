from datetime import UTC, datetime, timedelta

import pytest

from traderstack.circuit_breaker import StrategyCircuitBreaker
from traderstack.config import Settings
from traderstack.execution.paper_fill import adverse_fill_price_usd
from traderstack.exits import (
    ExitReason,
    evaluate_position_exits,
    exit_sizing_price_usd,
    exit_strategy_id,
    is_exit_strategy_id,
)
from traderstack.intelligence import NewsSnapshot
from traderstack.intelligence_orchestrator import ExternalIntelligence
from traderstack.market.models import MarketSource, MarketTick, ReferencePrice
from traderstack.models import HeldPosition, PortfolioSnapshot, RiskDecision, Side, TradeProposal
from traderstack.pipeline import VerticalSlicePipeline
from traderstack.risk import RiskEngine
from traderstack.strategies import Regime

NOW = datetime(2026, 9, 12, 12, 0, tzinfo=UTC)


def settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "kill_switch": False,
        "exit_stop_loss_pct": 0.02,
        "exit_take_profit_pct": 0.04,
        "exit_trailing_stop_pct": 0.0,
        "exit_time_stop_bars": 24,
        "exit_on_thesis_invalidation": False,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


def held(
    *,
    quantity: float = 0.1,
    average_cost_usd: float = 20_000,
    mark: float | None = None,
    opened_at: datetime | None = NOW,
    high_water_price_usd: float = 20_000,
    entry_strategy_id: str | None = "momentum_v1",
) -> HeldPosition:
    price = mark if mark is not None else average_cost_usd
    return HeldPosition(
        quantity=quantity,
        average_cost_usd=average_cost_usd,
        exposure_usd=quantity * price,
        opened_at=opened_at,
        high_water_price_usd=high_water_price_usd,
        entry_strategy_id=entry_strategy_id,
    )


def evaluate(position: HeldPosition, mark: float, **overrides: object):
    return evaluate_position_exits(
        settings=settings(**overrides),
        asset="BTC",
        position=position,
        mark_price_usd=mark,
        now=NOW,
        bar_seconds=3_600.0,
    )


def test_stop_loss_fires_when_mark_is_below_average_cost() -> None:
    signal = evaluate(held(), mark=19_500)
    assert signal is not None
    assert signal.reason is ExitReason.STOP_LOSS
    assert signal.side is Side.SELL
    # --- protective-exit sizing (#130) --- sized at the worst-case execution
    # price (mark less PAPER_SLIPPAGE_BPS), not at the mark: the planner
    # divides by the adverse sell price and a mark-priced notional would ask
    # for more quantity than is held.
    assert signal.requested_notional_usd == pytest.approx(0.1 * 19_500 * (1 - 5 / 10_000))
    assert signal.requested_notional_usd < 0.1 * 19_500
    assert exit_strategy_id(signal.reason) == "exit-stop_loss"


def test_exit_notional_is_sized_at_the_worst_case_execution_price() -> None:
    # The planner's notional -> quantity conversion must land at or below the
    # held quantity once the paper fill applies adverse slippage.
    quantity, mark, slippage_bps = 0.1, 19_500.0, 25.0
    signal = evaluate(held(quantity=quantity), mark=mark, paper_slippage_bps=slippage_bps)
    assert signal is not None
    fill_price = adverse_fill_price_usd(Side.SELL, mark, slippage_bps)
    assert signal.requested_notional_usd / fill_price == pytest.approx(quantity)


def test_exit_sizing_never_prices_a_protective_exit_at_zero() -> None:
    # An absurd slippage configuration must not silently drop a stop-loss; the
    # reducing-only clamp at the planner boundary is the backstop instead.
    assert exit_sizing_price_usd(settings(paper_slippage_bps=20_000.0), 100.0) == 100.0
    assert exit_sizing_price_usd(settings(), 0.0) == 0.0
    signal = evaluate(held(), mark=19_500, paper_slippage_bps=20_000.0)
    assert signal is not None
    assert signal.requested_notional_usd == pytest.approx(0.1 * 19_500)


def test_take_profit_fires_when_mark_is_above_target() -> None:
    signal = evaluate(held(high_water_price_usd=21_000), mark=20_900)
    assert signal is not None
    assert signal.reason is ExitReason.TAKE_PROFIT


def test_time_stop_fires_after_configured_bars() -> None:
    opened = NOW - timedelta(hours=24)
    signal = evaluate(held(opened_at=opened), mark=20_100)
    assert signal is not None
    assert signal.reason is ExitReason.TIME_STOP


def test_time_stop_does_not_invent_opened_at_on_legacy_positions() -> None:
    signal = evaluate(
        held(opened_at=None),
        mark=20_100,
        exit_stop_loss_pct=0.0,
        exit_take_profit_pct=0.0,
    )
    assert signal is None


def test_trailing_stop_fires_off_the_high_water_not_the_entry() -> None:
    signal = evaluate(
        held(high_water_price_usd=22_000),
        mark=21_600,
        exit_stop_loss_pct=0.0,
        exit_take_profit_pct=0.10,
        exit_trailing_stop_pct=0.015,
        exit_time_stop_bars=0,
    )
    assert signal is not None
    assert signal.reason is ExitReason.TRAILING_STOP


def test_stop_loss_beats_trailing_stop_when_both_are_true() -> None:
    signal = evaluate(
        held(high_water_price_usd=22_000),
        mark=19_000,
        exit_trailing_stop_pct=0.015,
    )
    assert signal is not None
    assert signal.reason is ExitReason.STOP_LOSS


def test_no_exit_inside_the_band() -> None:
    signal = evaluate(held(), mark=20_200)
    assert signal is None


def test_thesis_invalidation_on_opposite_ensemble_side() -> None:
    signal = evaluate_position_exits(
        settings=settings(
            exit_stop_loss_pct=0.0,
            exit_take_profit_pct=0.0,
            exit_time_stop_bars=0,
            exit_on_thesis_invalidation=True,
        ),
        asset="BTC",
        position=held(),
        mark_price_usd=20_200,
        now=NOW,
        bar_seconds=3_600.0,
        confirmed_side=Side.SELL,
    )
    assert signal is not None
    assert signal.reason is ExitReason.THESIS_INVALIDATED


def test_thesis_invalidation_on_trending_down_momentum_entry() -> None:
    signal = evaluate_position_exits(
        settings=settings(
            exit_stop_loss_pct=0.0,
            exit_take_profit_pct=0.0,
            exit_time_stop_bars=0,
            exit_on_thesis_invalidation=True,
        ),
        asset="BTC",
        position=held(entry_strategy_id="momentum_v1"),
        mark_price_usd=20_200,
        now=NOW,
        bar_seconds=3_600.0,
        confirmed_side=None,
        regime=Regime.TRENDING_DOWN,
    )
    assert signal is not None
    assert signal.reason is ExitReason.THESIS_INVALIDATED


def test_thesis_text_cannot_trigger_an_exit() -> None:
    # evaluate_position_exits takes no thesis argument; a hostile string
    # cannot be smuggled in. Confirmed by the absence of a fire here.
    signal = evaluate(
        held(),
        mark=20_200,
        exit_stop_loss_pct=0.0,
        exit_take_profit_pct=0.0,
        exit_time_stop_bars=0,
        exit_on_thesis_invalidation=True,
    )
    assert signal is None


def test_live_mode_never_evaluates_exits() -> None:
    signal = evaluate(held(), mark=10_000, trading_mode="live")
    assert signal is None
    assert settings(trading_mode="live").position_exits_active is False
    assert settings(trading_mode="shadow").position_exits_active is True


def test_zeroed_rules_disable_exits() -> None:
    signal = evaluate(
        held(),
        mark=10_000,
        exit_stop_loss_pct=0.0,
        exit_take_profit_pct=0.0,
        exit_time_stop_bars=0,
        exit_trailing_stop_pct=0.0,
        exit_on_thesis_invalidation=False,
    )
    assert signal is None


def test_empty_position_does_not_emit_a_short() -> None:
    empty = HeldPosition(
        quantity=0.0,
        average_cost_usd=0.0,
        exposure_usd=0.0,
        opened_at=NOW,
    )
    signal = evaluate(empty, mark=19_000)
    assert signal is None


def test_exit_strategy_id_helpers() -> None:
    assert is_exit_strategy_id("exit-stop_loss")
    assert is_exit_strategy_id("exit-time_stop")
    assert not is_exit_strategy_id("vertical-slice-v1")
    assert not is_exit_strategy_id("momentum_v1")


def _pipeline_snapshot(held_pos: HeldPosition, *, mark: float) -> PortfolioSnapshot:
    return PortfolioSnapshot(
        nav_usd=10_000,
        cash_usd=8_000,
        daily_pnl_usd=0.0,
        peak_nav_usd=10_000,
        asset_exposure_usd={"BTC": held_pos.exposure_usd},
        observed_at=NOW,
        held_positions={"BTC": held_pos},
    )


def test_pipeline_emits_stop_loss_before_discretionary_and_ignores_adverse_news() -> None:
    engine = RiskEngine(settings(kill_switch=False))
    pipe = VerticalSlicePipeline(risk_engine=engine, block_on_adverse_news=True)
    tick = MarketTick(
        source=MarketSource.KRAKEN,
        symbol="BTC/USD",
        observed_at=NOW,
        bid=19_490,
        ask=19_510,
        last=19_500,
    )
    refs = [ReferencePrice(source=MarketSource.COINGECKO, asset="BTC", price=19_500)]
    news = ExternalIntelligence(
        asset="BTC",
        news=NewsSnapshot(
            asset="BTC",
            event_score=0.9,
            adverse_event=True,
            item_count=3,
            source_id="test",
        ),
    )
    result = pipe.process(
        tick,
        refs,
        _pipeline_snapshot(held(mark=19_500), mark=19_500),
        intelligence=news,
        now=NOW,
    )
    assert result.accepted_market_data is True
    assert result.exit_reason == "exit_stop_loss"
    assert result.proposal is not None
    assert result.proposal.side is Side.SELL
    assert result.proposal.strategy_id == "exit-stop_loss"
    assert result.paper_order is not None
    # --- protective-exit sizing (#130) --- the execution boundary may clamp an
    # exit down to the held quantity; entry orders are never marked this way.
    assert result.paper_order.reduce_only is True
    assert "adverse_news_event" not in result.rejection_reasons


def test_pipeline_emits_stop_loss_before_provider_unavailable() -> None:
    engine = RiskEngine(settings(kill_switch=False))
    pipe = VerticalSlicePipeline(risk_engine=engine, block_on_adverse_news=True)
    tick = MarketTick(
        source=MarketSource.KRAKEN,
        symbol="BTC/USD",
        observed_at=NOW,
        bid=19_490,
        ask=19_510,
        last=19_500,
    )
    refs = [ReferencePrice(source=MarketSource.COINGECKO, asset="BTC", price=19_500)]
    intel = ExternalIntelligence(asset="BTC", provider_unavailable=True)
    result = pipe.process(
        tick,
        refs,
        _pipeline_snapshot(held(mark=19_500), mark=19_500),
        intelligence=intel,
        now=NOW,
    )
    assert result.exit_reason == "exit_stop_loss"
    assert result.paper_order is not None
    assert "intelligence_provider_unavailable" not in result.rejection_reasons


def test_tripped_entry_breaker_does_not_block_an_exit_proposal() -> None:
    breaker = StrategyCircuitBreaker.from_settings(settings())
    breaker.record_closed_trade("momentum_v1", pnl_usd=-50.0, nav_usd=10_000, at=NOW)
    breaker.record_closed_trade("momentum_v1", pnl_usd=-50.0, nav_usd=10_000, at=NOW)
    breaker.record_closed_trade("momentum_v1", pnl_usd=-50.0, nav_usd=10_000, at=NOW)
    assert breaker.is_tripped("momentum_v1", NOW)

    snapshot = PortfolioSnapshot(
        nav_usd=10_000,
        cash_usd=8_000,
        daily_pnl_usd=0.0,
        peak_nav_usd=10_000,
        asset_exposure_usd={"BTC": 2_000},
        observed_at=NOW,
    )
    engine = RiskEngine(settings(kill_switch=False), circuit_breaker=breaker)
    result = engine.evaluate(
        TradeProposal(
            strategy_id="exit-stop_loss",
            asset="BTC",
            side=Side.SELL,
            confidence=1.0,
            requested_notional_usd=2_000,
            thesis="stop",
            source_freshness_seconds=0.0,
        ),
        snapshot,
        now=NOW,
    )
    assert result.decision is RiskDecision.ALLOW
    assert "strategy_circuit_breaker" not in result.reasons


def test_pipeline_does_not_exit_when_live() -> None:
    engine = RiskEngine(settings(trading_mode="live", kill_switch=False))
    pipe = VerticalSlicePipeline(risk_engine=engine)
    tick = MarketTick(
        source=MarketSource.KRAKEN,
        symbol="BTC/USD",
        observed_at=NOW,
        bid=19_490,
        ask=19_510,
        last=19_500,
    )
    refs = [ReferencePrice(source=MarketSource.COINGECKO, asset="BTC", price=19_500)]
    result = pipe.process(
        tick,
        refs,
        _pipeline_snapshot(held(mark=19_500), mark=19_500),
        now=NOW,
    )
    assert result.exit_reason is None
    assert result.proposal is None or result.proposal.strategy_id != "exit-stop_loss"
