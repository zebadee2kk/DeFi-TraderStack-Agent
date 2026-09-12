"""Paper research mode: ensemble wiring from Settings, paper-only.

The pre-trade candle ensemble is structurally unable to reach two agreeing
votes on typical Kraken 1h OHLC (regime-exclusive voters + a 2% momentum
bar). Paper research mode adds a candle-only baseline and may drop
min_agreeing to 1 when optional intel is unset. Live/shadow never apply it.
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
from traderstack.strategies import PaperResearchStrategy, StrategyEnsemble

START = datetime(2026, 1, 1, tzinfo=UTC)


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "database_url": "postgresql+asyncpg://x:x@localhost/x",
        "redis_url": "redis://localhost:6379/0",
        "kill_switch": False,
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def mild_uptrend(count: int = 300) -> tuple[Candle, ...]:
    candles: list[Candle] = []
    previous = 100.0
    for index in range(count):
        close = 100.0 + index * 0.08
        candles.append(
            Candle(
                symbol="BTC/USD",
                interval="1h",
                opened_at=START + timedelta(hours=index),
                open=previous,
                high=max(previous, close) * 1.001,
                low=min(previous, close) * 0.999,
                close=close,
                volume=1_000 + index,
            )
        )
        previous = close
    return tuple(candles)


def test_default_paper_settings_activate_research_mode() -> None:
    settings = _settings()
    assert settings.trading_mode == "paper"
    assert settings.paper_research_mode is True
    assert settings.paper_research_active is True
    assert settings.optional_intelligence_configured is False


def test_paper_research_ensemble_adds_baseline_and_single_voter_when_intel_off() -> None:
    ensemble = paper_research_ensemble(_settings())
    assert ensemble.paper_research_strategy is not None
    assert ensemble.min_agreeing == 1


def test_paper_research_keeps_two_voters_when_intel_is_configured() -> None:
    ensemble = paper_research_ensemble(_settings(lunarcrush_api_key="present"))
    assert ensemble.paper_research_strategy is not None
    assert ensemble.min_agreeing == 2


def test_paper_research_ensemble_ignored_for_shadow_and_live() -> None:
    for mode in ("shadow", "live"):
        ensemble = paper_research_ensemble(
            _settings(trading_mode=mode, paper_research_mode=True)
        )
        assert ensemble.paper_research_strategy is None
        assert ensemble.min_agreeing == 2


def test_paper_research_off_keeps_strict_ensemble() -> None:
    ensemble = paper_research_ensemble(_settings(paper_research_mode=False))
    assert ensemble.paper_research_strategy is None
    assert ensemble.min_agreeing == 2


def test_build_pretrade_gate_uses_paper_research_ensemble() -> None:
    gate = build_pretrade_gate(_settings())
    assert isinstance(gate.backtester.ensemble.paper_research_strategy, PaperResearchStrategy)
    assert gate.backtester.ensemble.min_agreeing == 1


def test_empty_intel_and_absent_edge_fields_do_not_block_paper_consensus() -> None:
    """Kraken-like candles + empty intel / missing Crucix / no edge fields."""
    candles = mild_uptrend()
    default = StrategyEnsemble()
    _regime, default_signals = default.evaluate(candles)
    assert default.consensus(default_signals) is None

    research = paper_research_ensemble(_settings())
    _regime, signals = research.evaluate(candles)
    consensus = research.consensus(signals)
    assert consensus is not None
    assert consensus.side is Side.BUY
    assert any(signal.strategy_id == "paper_research_baseline_v1" for signal in signals)


def test_pipeline_reaches_risk_on_paper_research_consensus() -> None:
    settings = _settings()
    candles = tuple(
        Candle(
            symbol="BTC/USD",
            interval="1h",
            opened_at=datetime.now(UTC) - timedelta(hours=300 - index),
            open=100.0 + (index - 1) * 0.08 if index else 100.0,
            high=(100.0 + index * 0.08) * 1.001,
            low=(100.0 + index * 0.08) * 0.999,
            close=100.0 + index * 0.08,
            volume=1_000 + index,
        )
        for index in range(300)
    )
    pipeline = VerticalSlicePipeline(
        risk_engine=RiskEngine(settings),
        pretrade_gate=PreTradeBacktestGate(
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
        ),
        feature_builder=CandleMarketFeatureBuilder(),
        max_tick_age_seconds=30.0,
    )
    tick = MarketTick(
        source=MarketSource.KRAKEN, symbol="BTC/USD", bid=123.5, ask=124.5, last=124.0
    )
    references = [ReferencePrice(source=MarketSource.COINGECKO, asset="BTC", price=124.0)]
    portfolio = PortfolioSnapshot(
        nav_usd=10_000, cash_usd=10_000, daily_pnl_usd=0, peak_nav_usd=10_000
    )
    result = pipeline.process(tick, references, portfolio, candles=candles)
    assert result.accepted_market_data is True
    assert result.pretrade_check is not None
    assert result.pretrade_check.passed, result.pretrade_check.reasons
    assert result.proposal is not None
    assert result.risk_result is not None
    assert result.risk_result.decision in {RiskDecision.ALLOW, RiskDecision.REDUCE}
    assert result.paper_order is not None
    assert result.feature_vector is not None
    assert result.feature_vector.onchain.exchange_netflow_z is None
    assert result.feature_vector.narrative.sentiment is None
    assert result.feature_vector.market.external_signal_score is None


def test_paper_research_does_not_change_demonstration_notional() -> None:
    settings = _settings()
    research = build_pretrade_gate(settings)
    strict = build_pretrade_gate(_settings(paper_research_mode=False))
    assert research.backtester.starting_equity == strict.backtester.starting_equity
    assert isinstance(research.backtester, BaselineBacktester)
    pipeline_research = VerticalSlicePipeline(risk_engine=RiskEngine(settings))
    pipeline_strict = VerticalSlicePipeline(
        risk_engine=RiskEngine(_settings(paper_research_mode=False))
    )
    assert pipeline_research.demonstration_notional_pct == pipeline_strict.demonstration_notional_pct
