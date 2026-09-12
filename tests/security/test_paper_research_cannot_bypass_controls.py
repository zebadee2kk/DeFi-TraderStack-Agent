"""Paper research mode must not relax Zone C controls.

The paper-only ensemble may form consensus from healthier candle inputs. It
must not disable the kill switch, raise approved notional, apply to
live/shadow, or let an LLM-shaped setting rewrite risk policy.
"""

from datetime import UTC, datetime, timedelta

from traderstack.backtest import BaselineBacktester
from traderstack.candles import Candle
from traderstack.cli import build_pretrade_gate, paper_research_ensemble
from traderstack.config import Settings
from traderstack.market.models import MarketSource, MarketTick, ReferencePrice
from traderstack.market_features import CandleMarketFeatureBuilder
from traderstack.models import PortfolioSnapshot, RiskDecision, Side
from traderstack.pipeline import VerticalSlicePipeline
from traderstack.pretrade import PreTradeBacktestGate
from traderstack.risk import RiskEngine
from traderstack.strategies import PaperResearchStrategy


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "database_url": "postgresql+asyncpg://x:x@localhost/x",
        "redis_url": "redis://localhost:6379/0",
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def mild_uptrend(count: int = 300) -> tuple[Candle, ...]:
    candles: list[Candle] = []
    previous = 100.0
    now = datetime.now(UTC)
    for index in range(count):
        close = 100.0 + index * 0.08
        candles.append(
            Candle(
                symbol="BTC/USD",
                interval="1h",
                opened_at=now - timedelta(hours=count - index),
                open=previous,
                high=max(previous, close) * 1.001,
                low=min(previous, close) * 0.999,
                close=close,
                volume=1_000 + index,
            )
        )
        previous = close
    return tuple(candles)


def _lenient_paper_gate(settings: Settings) -> PreTradeBacktestGate:
    return PreTradeBacktestGate(
        backtester=BaselineBacktester(
            starting_equity=settings.paper_starting_nav_usd,
            ensemble=paper_research_ensemble(settings),
        ),
        min_candles=250,
        min_excess_return=-0.05,
        max_drawdown=0.5,
        min_sharpe=-10.0,
        min_trades=1,
        require_walkforward=False,
        min_walkforward_excess_return=-0.05,
    )


def test_live_and_shadow_cannot_activate_paper_research_looseness() -> None:
    for mode in ("live", "shadow"):
        settings = _settings(trading_mode=mode, paper_research_mode=True)
        assert settings.paper_research_active is False
        ensemble = paper_research_ensemble(settings)
        assert ensemble.min_agreeing == 2
        assert ensemble.paper_research_strategy is None


def test_kill_switch_still_withholds_after_paper_research_consensus() -> None:
    settings = _settings(trading_mode="paper", paper_research_mode=True, kill_switch=True)
    candles = mild_uptrend()
    pipeline = VerticalSlicePipeline(
        risk_engine=RiskEngine(settings),
        pretrade_gate=_lenient_paper_gate(settings),
        feature_builder=CandleMarketFeatureBuilder(),
        max_tick_age_seconds=30.0,
    )
    last = candles[-1].close
    result = pipeline.process(
        MarketTick(
            source=MarketSource.KRAKEN,
            symbol="BTC/USD",
            bid=last * 0.9995,
            ask=last * 1.0005,
            last=last,
        ),
        [ReferencePrice(source=MarketSource.COINGECKO, asset="BTC", price=last)],
        PortfolioSnapshot(nav_usd=10_000, cash_usd=10_000, daily_pnl_usd=0, peak_nav_usd=10_000),
        candles=candles,
    )
    assert result.pretrade_check is not None and result.pretrade_check.passed
    assert result.proposal is not None
    assert result.risk_result is not None
    assert result.risk_result.decision is RiskDecision.REJECT
    assert "kill_switch_enabled" in result.risk_result.reasons
    assert result.paper_order is None


def test_paper_research_cannot_increase_approved_notional() -> None:
    settings = _settings(trading_mode="paper", paper_research_mode=True, kill_switch=False)
    candles = mild_uptrend()
    last = candles[-1].close
    research = VerticalSlicePipeline(
        risk_engine=RiskEngine(settings),
        pretrade_gate=_lenient_paper_gate(settings),
        feature_builder=CandleMarketFeatureBuilder(),
        max_tick_age_seconds=30.0,
    ).process(
        MarketTick(
            source=MarketSource.KRAKEN,
            symbol="BTC/USD",
            bid=last * 0.9995,
            ask=last * 1.0005,
            last=last,
        ),
        [ReferencePrice(source=MarketSource.COINGECKO, asset="BTC", price=last)],
        PortfolioSnapshot(nav_usd=10_000, cash_usd=10_000, daily_pnl_usd=0, peak_nav_usd=10_000),
        candles=candles,
    )
    assert research.proposal is not None
    assert research.risk_result is not None
    # Pipeline demonstration size is 1% of NAV; paper research must not lift it.
    assert research.proposal.requested_notional_usd == 100.0
    assert research.risk_result.approved_notional_usd <= research.proposal.requested_notional_usd
    assert research.proposal.side is Side.BUY


def test_paper_thresholds_cannot_apply_on_live_or_shadow() -> None:
    for mode in ("live", "shadow"):
        settings = _settings(
            trading_mode=mode,
            paper_research_mode=True,
            paper_pretrade_min_excess_return=-10.0,
            paper_pretrade_min_sharpe=-100.0,
            paper_pretrade_min_trades=0,
            paper_reference_last_good_seconds=9_999,
        )
        assert settings.effective_reference_last_good_seconds == 0.0
        gate = build_pretrade_gate(settings)
        assert gate.min_excess_return == settings.pretrade_min_excess_return
        assert gate.min_sharpe == settings.pretrade_min_sharpe
        assert gate.min_trades == settings.pretrade_min_trades
        assert gate.min_total_return is None


def test_paper_last_good_does_not_change_risk_limits() -> None:
    settings = _settings(
        trading_mode="paper",
        paper_reference_last_good_seconds=300,
        max_position_pct=0.10,
        kill_switch=True,
    )
    engine = RiskEngine(settings)
    assert engine.settings.max_position_pct == 0.10
    assert engine.settings.kill_switch is True
    assert settings.effective_reference_last_good_seconds == 300


def test_build_pretrade_gate_does_not_rewrite_risk_policy_fields() -> None:
    settings = _settings(
        trading_mode="paper",
        paper_research_mode=True,
        max_position_pct=0.10,
        paper_starting_nav_usd=10_000,
    )
    gate = build_pretrade_gate(settings)
    engine = RiskEngine(settings)
    assert settings.max_position_pct == 0.10
    assert engine.settings.max_position_pct == 0.10
    assert gate.backtester.starting_equity == 10_000
    assert isinstance(gate.backtester.ensemble.paper_research_strategy, PaperResearchStrategy)


def test_promote_ema_cannot_silently_score_hourly_bars() -> None:
    settings = _settings(
        trading_mode="paper",
        paper_promote_ema_9_21=True,
        pretrade_candle_interval="1h",
        kill_switch=True,
        max_position_pct=0.10,
    )
    assert settings.effective_pretrade_candle_interval == "1d"
    gate = build_pretrade_gate(settings)
    assert gate.required_candle_interval == "1d"
    hourly = mild_uptrend()
    check = gate.evaluate(hourly, now=datetime.now(UTC))
    assert not check.passed
    assert check.reasons == ["candle_interval_mismatch"]
    assert check.metrics is None
    engine = RiskEngine(settings)
    assert engine.settings.kill_switch is True
    assert engine.settings.max_position_pct == 0.10


def test_promote_ema_is_ignored_on_live_and_does_not_force_daily() -> None:
    settings = _settings(
        trading_mode="live",
        paper_promote_ema_9_21=True,
        pretrade_candle_interval="1h",
    )
    assert settings.paper_promote_ema_9_21_active is False
    assert settings.effective_pretrade_candle_interval == "1h"
    gate = build_pretrade_gate(settings)
    assert gate.required_candle_interval is None
