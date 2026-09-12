"""Paper-research edge features: pipeline merge, runtime snapshot, no risk impact."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest

from traderstack.config import Settings
from traderstack.features import ResearchEdgeFeatures
from traderstack.market.models import (
    BookTicker,
    LiquidationWindowSnapshot,
    MarketSource,
    MarketTick,
    ReferencePrice,
)
from traderstack.models import PortfolioSnapshot, RiskDecision
from traderstack.pipeline import VerticalSlicePipeline
from traderstack.risk import RiskEngine
from traderstack.runtime import PaperRuntime


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "database_url": "postgresql+asyncpg://x:x@localhost/x",
        "redis_url": "redis://localhost:6379/0",
        "kill_switch": False,
        "pretrade_backtest_enabled": False,
    }
    values.update(overrides)
    return Settings(**values)


def _portfolio() -> PortfolioSnapshot:
    return PortfolioSnapshot(nav_usd=10_000, cash_usd=10_000, daily_pnl_usd=0, peak_nav_usd=10_000)


def _tick() -> MarketTick:
    return MarketTick(source=MarketSource.KRAKEN, symbol="BTC/USD", bid=99.95, ask=100.05, last=100)


def _refs() -> list[ReferencePrice]:
    return [ReferencePrice(source=MarketSource.COINGECKO, asset="BTC", price=100)]


def _pipeline() -> VerticalSlicePipeline:
    return VerticalSlicePipeline(risk_engine=RiskEngine(_settings()))


def _edge() -> ResearchEdgeFeatures:
    return ResearchEdgeFeatures(
        liq_notional_long_z=4.5,
        liq_notional_short_z=-1.0,
        liq_count_long=1.0,
        liq_count_short=0.1,
        cross_venue_mid_divergence_bps=12.5,
        cross_venue_mid_source="binance",
    )


def test_pipeline_merges_edge_features_without_changing_notional() -> None:
    baseline = _pipeline().process(_tick(), _refs(), _portfolio())
    merged = _pipeline().process(
        _tick(),
        _refs(),
        _portfolio(),
        edge=_edge(),
        edge_source_ids=("binance_liq", "book_ticker:binance"),
    )
    assert merged.feature_vector is not None
    assert merged.feature_vector.edge.liq_notional_long_z == pytest.approx(4.5)
    assert merged.feature_vector.edge.cross_venue_mid_divergence_bps == pytest.approx(12.5)
    assert "binance_liq" in merged.feature_vector.source_ids
    assert "book_ticker:binance" in merged.feature_vector.source_ids
    assert baseline.paper_order is not None
    assert merged.paper_order is not None
    assert merged.paper_order.notional_usd == baseline.paper_order.notional_usd
    assert merged.risk_result is not None
    assert baseline.risk_result is not None
    assert merged.risk_result.approved_notional_usd == baseline.risk_result.approved_notional_usd


def test_risk_engine_ignores_extreme_edge_features() -> None:
    engine = RiskEngine(_settings())
    from traderstack.features import AssetFeatureVector, MarketFeatures
    from traderstack.models import Side, TradeProposal

    proposal = TradeProposal(
        strategy_id="vertical-slice-v1",
        asset="BTC",
        side=Side.BUY,
        confidence=0.5,
        requested_notional_usd=500,
        thesis="test",
        source_freshness_seconds=0.0,
    )
    market = MarketFeatures(
        trend_4h=0.0, trend_1d=0.0, volatility_z=0.01, relative_volume=1.0, spread_bps=5.0
    )
    plain = AssetFeatureVector(asset="BTC", market=market)
    hostile = AssetFeatureVector(asset="BTC", market=market, edge=_edge())
    without = engine.evaluate(proposal, _portfolio(), plain)
    with_edge = engine.evaluate(proposal, _portfolio(), hostile)
    assert without.decision is with_edge.decision is RiskDecision.ALLOW
    assert without.approved_notional_usd == with_edge.approved_notional_usd == 500


class FakeVenue:
    async def stream_ticks(self, symbols: tuple[str, ...]) -> AsyncIterator[MarketTick]:
        yield _tick()


class FakeReference:
    async def get_prices(self, assets: tuple[str, ...]) -> list[ReferencePrice]:
        return _refs()


class FakeLiquidations:
    def snapshot(self, asset: str) -> LiquidationWindowSnapshot:
        return LiquidationWindowSnapshot(
            asset=asset,
            observed_at=datetime.now(UTC),
            source_id="binance_liq",
            liq_notional_long_z=2.0,
            liq_count_long=0.5,
            long_notional=20_000,
        )


class FakeBookTicker:
    def latest(self, asset: str) -> BookTicker:
        return BookTicker(
            source=MarketSource.BINANCE,
            symbol=f"{asset}USDT",
            asset=asset,
            bid=100.10,
            ask=100.20,
        )


@pytest.mark.asyncio
async def test_runtime_attaches_local_edge_snapshots() -> None:
    runtime = PaperRuntime(
        venue=FakeVenue(),
        references=(FakeReference(),),
        pipeline=_pipeline(),
        liquidations=FakeLiquidations(),
        book_ticker=FakeBookTicker(),
    )
    result = await runtime.run_once("BTC/USD", _portfolio())
    assert result.edge_error is None
    vector = result.pipeline.feature_vector
    assert vector is not None
    assert vector.edge.liq_notional_long_z == pytest.approx(2.0)
    assert vector.edge.liq_count_long == pytest.approx(0.5)
    assert vector.edge.cross_venue_mid_source == "binance"
    assert vector.edge.cross_venue_mid_divergence_bps == pytest.approx(15.0)
    assert "binance_liq" in vector.source_ids
    assert "book_ticker:binance" in vector.source_ids
    assert result.pipeline.paper_order is not None
