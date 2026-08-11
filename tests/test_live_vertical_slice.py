from datetime import UTC, datetime, timedelta

from traderstack.config import Settings
from traderstack.market.adapters import parse_kraken_ticker
from traderstack.market.models import MarketSource, MarketTick, ReferencePrice
from traderstack.models import PortfolioSnapshot, RiskDecision
from traderstack.pipeline import VerticalSlicePipeline
from traderstack.risk import RiskEngine


def portfolio() -> PortfolioSnapshot:
    return PortfolioSnapshot(
        nav_usd=10_000,
        cash_usd=10_000,
        daily_pnl_usd=0,
        peak_nav_usd=10_000,
    )


def pipeline() -> VerticalSlicePipeline:
    return VerticalSlicePipeline(risk_engine=RiskEngine(Settings(kill_switch=False)))


def test_parse_kraken_ticker() -> None:
    tick = parse_kraken_ticker(
        {
            "channel": "ticker",
            "type": "snapshot",
            "data": [{"symbol": "BTC/USD", "bid": 999.0, "ask": 1001.0, "last": 1000.0}],
        }
    )
    assert tick is not None
    assert tick.symbol == "BTC/USD"
    assert tick.mid == 1000.0
    assert tick.source is MarketSource.KRAKEN


def test_pipeline_emits_paper_intent_after_validation() -> None:
    tick = MarketTick(source=MarketSource.KRAKEN, symbol="BTC/USD", bid=999.5, ask=1000.5, last=1000)
    references = [
        ReferencePrice(source=MarketSource.COINGECKO, asset="BTC", price=1001),
        ReferencePrice(source=MarketSource.COINMARKETCAP, asset="BTC", price=999),
    ]
    result = pipeline().process(tick, references, portfolio())
    assert result.accepted_market_data is True
    assert result.risk_result is not None
    assert result.risk_result.decision is RiskDecision.ALLOW
    assert result.paper_order is not None
    assert result.paper_order.venue == "kraken_paper_trade"


def test_pipeline_rejects_stale_tick() -> None:
    tick = MarketTick(
        source=MarketSource.KRAKEN,
        symbol="BTC/USD",
        observed_at=datetime.now(UTC) - timedelta(seconds=60),
        bid=999.5,
        ask=1000.5,
        last=1000,
    )
    refs = [ReferencePrice(source=MarketSource.COINGECKO, asset="BTC", price=1000)]
    result = pipeline().process(tick, refs, portfolio())
    assert result.accepted_market_data is False
    assert "stale_primary_tick" in result.rejection_reasons
    assert result.paper_order is None


def test_pipeline_rejects_divergent_reference() -> None:
    tick = MarketTick(source=MarketSource.KRAKEN, symbol="ETH/USD", bid=999.5, ask=1000.5, last=1000)
    refs = [ReferencePrice(source=MarketSource.COINGECKO, asset="ETH", price=1200)]
    result = pipeline().process(tick, refs, portfolio())
    assert result.accepted_market_data is False
    assert "reference_price_divergence" in result.rejection_reasons


def test_kill_switch_prevents_paper_intent() -> None:
    guarded = VerticalSlicePipeline(risk_engine=RiskEngine(Settings(kill_switch=True)))
    tick = MarketTick(source=MarketSource.KRAKEN, symbol="SOL/USD", bid=99.95, ask=100.05, last=100)
    refs = [ReferencePrice(source=MarketSource.COINGECKO, asset="SOL", price=100)]
    result = guarded.process(tick, refs, portfolio())
    assert result.risk_result is not None
    assert result.risk_result.decision is RiskDecision.REJECT
    assert result.paper_order is None
