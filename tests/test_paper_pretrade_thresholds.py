"""Paper Spot pretrade floors vs the live/shadow promotion bar.

A candle-only MA voter on ~400-bar 1h history is structurally behind
PRETRADE_MIN_EXCESS_RETURN=0 / PRETRADE_MIN_SHARPE=0 / PRETRADE_MIN_TRADES=3
(fee drag vs costless buy-and-hold; one-trade uptrends). Paper applies
documented floors that still require positive total return. Live/shadow
keep the strict mins even when PAPER_PRETRADE_* are set.
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

START = datetime(2026, 1, 1, tzinfo=UTC)


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "database_url": "postgresql+asyncpg://x:x@localhost/x",
        "redis_url": "redis://localhost:6379/0",
        "kill_switch": False,
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def mild_uptrend(count: int = 400, *, start: datetime = START) -> tuple[Candle, ...]:
    candles: list[Candle] = []
    previous = 100.0
    for index in range(count):
        close = 100.0 + index * 0.08
        candles.append(
            Candle(
                symbol="BTC/USD",
                interval="1h",
                opened_at=start + timedelta(hours=index),
                open=previous,
                high=max(previous, close) * 1.001,
                low=min(previous, close) * 0.999,
                close=close,
                volume=1_000 + index,
            )
        )
        previous = close
    return tuple(candles)


def losing_choppy(count: int = 400, *, start: datetime = START) -> tuple[Candle, ...]:
    """Oscillating book that still has a late MA tilt but loses money after fees."""
    candles: list[Candle] = []
    previous = 100.0
    for index in range(count):
        # 8-bar square wave, net drift down so a flip-happy MA pays fees and loses.
        wave = 2.0 if (index // 8) % 2 == 0 else -2.0
        close = max(1.0, previous + wave - 0.05)
        candles.append(
            Candle(
                symbol="BTC/USD",
                interval="1h",
                opened_at=start + timedelta(hours=index),
                open=previous,
                high=max(previous, close) * 1.002,
                low=min(previous, close) * 0.998,
                close=close,
                volume=1_000 + index,
            )
        )
        previous = close
    return tuple(candles)


def end_time(candles: tuple[Candle, ...]) -> datetime:
    return candles[-1].opened_at + timedelta(minutes=30)


def test_paper_defaults_differ_from_live_promotion_bar() -> None:
    paper = _settings()
    live = _settings(trading_mode="live")
    assert paper.effective_pretrade_min_excess_return == paper.paper_pretrade_min_excess_return
    assert paper.effective_pretrade_min_sharpe == paper.paper_pretrade_min_sharpe
    assert paper.effective_pretrade_min_trades == paper.paper_pretrade_min_trades
    assert paper.effective_pretrade_min_total_return == 0.0
    assert live.effective_pretrade_min_excess_return == live.pretrade_min_excess_return
    assert live.effective_pretrade_min_sharpe == live.pretrade_min_sharpe
    assert live.effective_pretrade_min_trades == live.pretrade_min_trades
    assert live.effective_pretrade_min_total_return is None
    assert live.pretrade_min_excess_return == 0.0
    assert live.pretrade_min_sharpe == 0.0
    assert live.pretrade_min_trades == 3


def test_live_ignores_paper_pretrade_env_overrides() -> None:
    live = _settings(
        trading_mode="live",
        paper_pretrade_min_excess_return=-10.0,
        paper_pretrade_min_sharpe=-100.0,
        paper_pretrade_min_trades=0,
        paper_pretrade_min_total_return=-1.0,
    )
    gate = build_pretrade_gate(live)
    assert gate.min_excess_return == 0.0
    assert gate.min_sharpe == 0.0
    assert gate.min_trades == 3
    assert gate.min_total_return is None
    assert gate.min_walkforward_excess_return == 0.0


def test_shadow_keeps_strict_pretrade_mins() -> None:
    gate = build_pretrade_gate(_settings(trading_mode="shadow", paper_research_mode=True))
    assert gate.min_excess_return == 0.0
    assert gate.min_sharpe == 0.0
    assert gate.min_total_return is None
    assert gate.backtester.ensemble.paper_research_strategy is None


def test_strict_live_mins_are_unreachable_on_mild_kraken_uptrend() -> None:
    candles = mild_uptrend()
    live = PreTradeBacktestGate(
        backtester=BaselineBacktester(
            ensemble=paper_research_ensemble(_settings()),
            fee_bps=10.0,
            slippage_bps=5.0,
        ),
        min_candles=250,
        min_excess_return=0.0,
        min_sharpe=0.0,
        min_trades=3,
        require_walkforward=True,
        min_walkforward_excess_return=0.0,
    ).evaluate(candles, now=end_time(candles))
    assert live.confirmed_side is Side.BUY
    assert not live.passed
    assert "backtest_excess_return_below_minimum" in live.reasons or (
        "backtest_trade_count_below_minimum" in live.reasons
    )


def test_paper_gate_reaches_consensus_and_clears_floors_on_mild_uptrend() -> None:
    settings = _settings()
    candles = mild_uptrend()
    check = build_pretrade_gate(settings).evaluate(candles, now=end_time(candles))
    assert check.passed, check.reasons
    assert check.confirmed_side is Side.BUY
    assert check.metrics is not None
    assert check.metrics.total_return >= 0.0
    assert check.metrics.trades >= 1
    # Fee-shock Sharpe on a one-trade hold is largely negative; the paper
    # floor is documented to sit below that artifact.
    assert check.metrics.sharpe < 0.0
    assert check.metrics.sharpe >= settings.paper_pretrade_min_sharpe


def test_paper_sharpe_floor_is_below_one_trade_fee_shock() -> None:
    settings = _settings()
    assert settings.paper_pretrade_min_sharpe <= -5.0


def test_paper_gate_still_rejects_a_losing_lookback() -> None:
    candles = losing_choppy()
    check = build_pretrade_gate(_settings()).evaluate(candles, now=end_time(candles))
    assert not check.passed
    assert check.metrics is not None
    # Positive-evidence floor: either no consensus, or the book lost money /
    # breached drawdown. Must not silently pass a losing MA voter.
    assert check.confirmed_side is None or (
        "backtest_total_return_below_minimum" in check.reasons
        or "backtest_drawdown_above_maximum" in check.reasons
        or "walkforward_drawdown_above_maximum" in check.reasons
        or "walkforward_excess_return_below_minimum" in check.reasons
        or "no_strategy_consensus" in check.reasons
    )


def test_pipeline_reaches_risk_on_default_paper_gate() -> None:
    settings = _settings()
    candles = tuple(
        Candle(
            symbol="BTC/USD",
            interval="1h",
            opened_at=datetime.now(UTC) - timedelta(hours=400 - index),
            open=100.0 + (index - 1) * 0.08 if index else 100.0,
            high=(100.0 + index * 0.08) * 1.001,
            low=(100.0 + index * 0.08) * 0.999,
            close=100.0 + index * 0.08,
            volume=1_000 + index,
        )
        for index in range(400)
    )
    pipeline = VerticalSlicePipeline(
        risk_engine=RiskEngine(settings),
        pretrade_gate=build_pretrade_gate(settings),
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
    assert result.pretrade_check is not None
    assert result.pretrade_check.passed, result.pretrade_check.reasons
    assert result.proposal is not None
    assert result.risk_result is not None
    assert result.risk_result.decision in {RiskDecision.ALLOW, RiskDecision.REDUCE}
    assert result.paper_order is not None
    assert result.proposal.requested_notional_usd == 100.0
    assert result.risk_result.approved_notional_usd <= result.proposal.requested_notional_usd
