from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest

from traderstack.backtest import BaselineBacktester
from traderstack.candles import Candle
from traderstack.config import Settings
from traderstack.market.models import MarketSource, MarketTick, ReferencePrice
from traderstack.market_features import CandleMarketFeatureBuilder
from traderstack.models import PortfolioSnapshot, RiskDecision, Side
from traderstack.pipeline import VerticalSlicePipeline
from traderstack.pretrade import PreTradeBacktestGate
from traderstack.risk import RiskEngine
from traderstack.runtime import PaperRuntime

START = datetime(2026, 1, 1, tzinfo=UTC)


def uptrend(count: int = 300, *, start: datetime = START) -> tuple[Candle, ...]:
    candles: list[Candle] = []
    previous = 100.0
    for index in range(count):
        close = 100.0 + index
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


def flat(count: int = 300) -> tuple[Candle, ...]:
    return tuple(
        Candle(
            symbol="BTC/USD",
            interval="1h",
            opened_at=START + timedelta(hours=index),
            open=100.0,
            high=100.0,
            low=100.0,
            close=100.0,
            volume=1_000,
        )
        for index in range(count)
    )


def end_time(candles: tuple[Candle, ...]) -> datetime:
    return candles[-1].opened_at + timedelta(minutes=30)


def lenient_gate(**overrides: object) -> PreTradeBacktestGate:
    base: dict[str, object] = {
        "min_candles": 250,
        "min_excess_return": -0.05,
        "max_drawdown": 0.5,
        "min_sharpe": -10.0,
        "min_trades": 1,
        "require_walkforward": True,
        "min_walkforward_excess_return": -0.05,
    }
    base.update(overrides)
    return PreTradeBacktestGate(**base)  # type: ignore[arg-type]


def test_gate_confirms_side_and_runs_backtest_and_walkforward() -> None:
    candles = uptrend()
    check = lenient_gate().evaluate(candles, Side.BUY, now=end_time(candles))
    assert check.passed, check.reasons
    assert check.confirmed_side is Side.BUY
    assert check.confidence > 0
    assert check.metrics is not None and check.metrics.trades >= 1
    assert check.walkforward is not None and len(check.walkforward.folds) >= 1
    assert check.candles_evaluated == 300


def test_gate_adopts_consensus_side_when_none_proposed() -> None:
    candles = uptrend()
    check = lenient_gate().evaluate(candles, now=end_time(candles))
    assert check.passed
    assert check.confirmed_side is Side.BUY


def test_gate_rejects_insufficient_history() -> None:
    check = lenient_gate().evaluate(uptrend(100), Side.BUY)
    assert not check.passed
    assert check.reasons == ["insufficient_candle_history"]
    assert check.metrics is None


def test_gate_rejects_stale_history() -> None:
    candles = uptrend()
    check = lenient_gate().evaluate(candles, Side.BUY, now=end_time(candles) + timedelta(days=2))
    assert not check.passed
    assert check.reasons == ["stale_candle_history"]


def test_gate_rejects_side_the_strategy_does_not_confirm() -> None:
    candles = uptrend()
    check = lenient_gate().evaluate(candles, Side.SELL, now=end_time(candles))
    assert not check.passed
    assert check.reasons == ["strategy_does_not_confirm_side"]
    assert check.confirmed_side is Side.BUY


def test_gate_rejects_when_no_consensus() -> None:
    candles = flat()
    check = lenient_gate().evaluate(candles, Side.BUY, now=end_time(candles))
    assert not check.passed
    assert check.reasons == ["no_strategy_consensus"]


def test_gate_rejects_on_backtest_thresholds() -> None:
    candles = uptrend()
    check = lenient_gate(min_excess_return=5.0, min_trades=50, min_sharpe=1_000.0).evaluate(
        candles, Side.BUY, now=end_time(candles)
    )
    assert not check.passed
    assert "backtest_excess_return_below_minimum" in check.reasons
    assert "backtest_trade_count_below_minimum" in check.reasons
    assert "backtest_sharpe_below_minimum" in check.reasons
    assert check.metrics is not None


def test_gate_requires_walkforward_when_configured() -> None:
    candles = uptrend(120)
    strict = lenient_gate(min_candles=100, require_walkforward=True)
    relaxed = lenient_gate(min_candles=100, require_walkforward=False)
    assert strict.evaluate(candles, Side.BUY, now=end_time(candles)).reasons == [
        "walkforward_insufficient_history"
    ]
    assert relaxed.evaluate(candles, Side.BUY, now=end_time(candles)).passed


def test_gate_uses_shared_backtester_costs() -> None:
    candles = uptrend()
    free = lenient_gate(backtester=BaselineBacktester(fee_bps=0.0, slippage_bps=0.0))
    costly = lenient_gate(backtester=BaselineBacktester(fee_bps=50.0, slippage_bps=50.0))
    free_check = free.evaluate(candles, Side.BUY, now=end_time(candles))
    costly_check = costly.evaluate(candles, Side.BUY, now=end_time(candles))
    assert free_check.metrics is not None and costly_check.metrics is not None
    assert free_check.metrics.ending_equity > costly_check.metrics.ending_equity
    assert free_check.metrics.benchmark_return == pytest.approx(
        costly_check.metrics.benchmark_return
    )


# --- pipeline integration -------------------------------------------------


def portfolio() -> PortfolioSnapshot:
    return PortfolioSnapshot(nav_usd=10_000, cash_usd=10_000, daily_pnl_usd=0, peak_nav_usd=10_000)


def tick() -> MarketTick:
    return MarketTick(
        source=MarketSource.KRAKEN, symbol="BTC/USD", bid=999.5, ask=1000.5, last=1000
    )


def references() -> list[ReferencePrice]:
    return [ReferencePrice(source=MarketSource.COINGECKO, asset="BTC", price=1000)]


def gated_pipeline(**overrides: object) -> VerticalSlicePipeline:
    return VerticalSlicePipeline(
        risk_engine=RiskEngine(Settings(kill_switch=False)),
        pretrade_gate=lenient_gate(**overrides),
        feature_builder=CandleMarketFeatureBuilder(),
    )


def recent_uptrend(count: int = 300) -> tuple[Candle, ...]:
    return uptrend(count, start=datetime.now(UTC) - timedelta(hours=count))


def test_pipeline_fails_closed_without_candles_when_gate_configured() -> None:
    result = gated_pipeline().process(tick(), references(), portfolio())
    assert result.accepted_market_data is True
    assert result.rejection_reasons == ["missing_candle_history"]
    assert result.proposal is None
    assert result.paper_order is None


def test_pipeline_emits_strategy_confirmed_proposal() -> None:
    result = gated_pipeline().process(tick(), references(), portfolio(), candles=recent_uptrend())
    assert result.pretrade_check is not None and result.pretrade_check.passed
    assert result.proposal is not None
    assert result.proposal.side is Side.BUY
    assert result.proposal.signal_ids == ["pretrade-backtest-gate-v1"]
    assert result.risk_result is not None
    assert result.risk_result.decision is RiskDecision.ALLOW
    assert result.paper_order is not None
    assert result.feature_vector is not None
    assert result.feature_vector.market.trend_1d > 0
    assert "candles:1h" in result.feature_vector.source_ids


def test_pipeline_records_failed_pretrade_check_and_blocks_proposal() -> None:
    result = gated_pipeline(min_trades=50).process(
        tick(), references(), portfolio(), candles=recent_uptrend()
    )
    assert result.pretrade_check is not None
    assert not result.pretrade_check.passed
    assert "backtest_trade_count_below_minimum" in result.rejection_reasons
    assert result.proposal is None
    assert result.paper_order is None


def test_pipeline_without_gate_ignores_candles_gracefully() -> None:
    ungated = VerticalSlicePipeline(risk_engine=RiskEngine(Settings(kill_switch=False)))
    result = ungated.process(tick(), references(), portfolio(), candles=recent_uptrend())
    assert result.paper_order is not None
    assert result.pretrade_check is None


# --- runtime integration --------------------------------------------------


class FakeVenue:
    async def stream_ticks(self, symbols: tuple[str, ...]) -> AsyncIterator[MarketTick]:
        yield MarketTick(
            source=MarketSource.KRAKEN, symbol=symbols[0], bid=99.95, ask=100.05, last=100
        )


class GoodReference:
    async def get_prices(self, assets: tuple[str, ...]) -> list[ReferencePrice]:
        return [ReferencePrice(source=MarketSource.COINGECKO, asset=assets[0], price=100)]


class BrokenCandles:
    async def fetch(self, symbol: str, resolution: str = "1h", *, count: int = 400):
        raise RuntimeError("candle API down")


class GoodCandles:
    async def fetch(self, symbol: str, resolution: str = "1h", *, count: int = 400):
        return recent_uptrend(count)


@pytest.mark.asyncio
async def test_runtime_fails_closed_when_candle_history_unavailable() -> None:
    runtime = PaperRuntime(
        venue=FakeVenue(),
        references=(GoodReference(),),
        pipeline=gated_pipeline(),
        candles=BrokenCandles(),
    )
    result = await runtime.run_once("BTC/USD", portfolio())
    assert result.candle_error is not None and "candle API down" in result.candle_error
    assert result.candles_loaded == 0
    assert result.pipeline.rejection_reasons == ["missing_candle_history"]
    assert result.pipeline.paper_order is None


@pytest.mark.asyncio
async def test_runtime_passes_candles_through_to_gate() -> None:
    runtime = PaperRuntime(
        venue=FakeVenue(),
        references=(GoodReference(),),
        pipeline=gated_pipeline(),
        candles=GoodCandles(),
        candle_count=300,
    )
    result = await runtime.run_once("BTC/USD", portfolio())
    assert result.candles_loaded == 300
    assert result.pipeline.pretrade_check is not None and result.pipeline.pretrade_check.passed
    assert result.pipeline.paper_order is not None
