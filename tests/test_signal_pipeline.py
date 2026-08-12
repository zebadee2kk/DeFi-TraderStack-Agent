from datetime import UTC, datetime, timedelta

from traderstack.agents.meta import ConstrainedMetaAgent, EvidencePacket, MetaAgentDecision
from traderstack.candles import Candle
from traderstack.config import Settings
from traderstack.intelligence import NewsSnapshot
from traderstack.intelligence_orchestrator import IntelligenceOrchestrator
from traderstack.market.models import MarketSource, MarketTick, ReferencePrice
from traderstack.models import PortfolioSnapshot, RiskDecision, Side
from traderstack.risk import RiskEngine
from traderstack.signal_pipeline import SignalPipeline
from traderstack.strategies import Regime


def make_candles(prices: list[float], symbol: str = "BTC/USD") -> tuple[Candle, ...]:
    start = datetime.now(UTC) - timedelta(hours=len(prices) + 1)
    candles = []
    for index, price in enumerate(prices):
        previous = prices[index - 1] if index else price
        high = max(previous, price) * 1.001
        low = min(previous, price) * 0.999
        candles.append(
            Candle(
                symbol=symbol,
                interval="1h",
                opened_at=start + timedelta(hours=index),
                open=previous,
                high=high,
                low=low,
                close=price,
                volume=100 + index,
            )
        )
    return tuple(candles)


def rising_prices(count: int = 60, start: float = 100.0, step: float = 0.005) -> list[float]:
    return [start * (1 + step) ** index for index in range(count)]


def falling_prices(count: int = 60, start: float = 100.0, step: float = 0.005) -> list[float]:
    return [start * (1 - step) ** index for index in range(count)]


def tick(symbol: str = "BTC/USD", last: float = 1000.0) -> MarketTick:
    return MarketTick(
        source=MarketSource.KRAKEN,
        symbol=symbol,
        bid=last * 0.9995,
        ask=last * 1.0005,
        last=last,
    )


def references(asset: str = "BTC", price: float = 1000.0) -> list[ReferencePrice]:
    return [
        ReferencePrice(source=MarketSource.COINGECKO, asset=asset, price=price * 1.0005),
        ReferencePrice(source=MarketSource.COINMARKETCAP, asset=asset, price=price * 0.9995),
    ]


def portfolio(**overrides) -> PortfolioSnapshot:
    values = {
        "nav_usd": 10_000,
        "cash_usd": 10_000,
        "daily_pnl_usd": 0,
        "peak_nav_usd": 10_000,
        "asset_exposure_usd": {},
    }
    values.update(overrides)
    return PortfolioSnapshot(**values)


def pipeline(**overrides) -> SignalPipeline:
    values = {"risk_engine": RiskEngine(Settings(kill_switch=False))}
    values.update(overrides)
    return SignalPipeline(**values)


async def test_consensus_buy_produces_confidence_scaled_order() -> None:
    result = await pipeline().process(
        tick(), make_candles(rising_prices()), references(), portfolio()
    )
    assert result.accepted_market_data is True
    assert result.regime is Regime.TRENDING_UP
    assert result.proposal is not None
    assert result.proposal.side is Side.BUY
    assert result.proposal.strategy_id == "signal_ensemble_v1"
    assert result.risk_result is not None
    assert result.risk_result.decision is RiskDecision.ALLOW
    assert result.paper_order is not None
    expected = 10_000 * 0.02 * result.proposal.confidence
    assert abs(result.paper_order.notional_usd - expected) < 1e-6


async def test_flat_market_produces_no_consensus() -> None:
    result = await pipeline().process(
        tick(), make_candles([100.0] * 60), references(), portfolio()
    )
    assert result.accepted_market_data is True
    assert result.proposal is None
    assert "no_consensus_signal" in result.no_trade_reasons


async def test_insufficient_candles_rejects_market_data() -> None:
    result = await pipeline().process(tick(), (), references(), portfolio())
    assert result.accepted_market_data is False
    assert "insufficient_candle_history" in result.rejection_reasons


async def test_stale_tick_rejected_before_signals() -> None:
    stale = MarketTick(
        source=MarketSource.KRAKEN,
        symbol="BTC/USD",
        observed_at=datetime.now(UTC) - timedelta(seconds=60),
        bid=999.5,
        ask=1000.5,
        last=1000,
    )
    result = await pipeline().process(
        stale, make_candles(rising_prices()), references(), portfolio()
    )
    assert result.accepted_market_data is False
    assert "stale_primary_tick" in result.rejection_reasons


async def test_adverse_news_vetoes_buy() -> None:
    async def adverse_news(asset: str) -> NewsSnapshot:
        return NewsSnapshot(
            asset=asset,
            event_score=0.9,
            adverse_event=True,
            item_count=3,
            source_id="test-news",
        )

    orchestrator = IntelligenceOrchestrator(news=(adverse_news,))
    result = await pipeline(intelligence=orchestrator).process(
        tick(), make_candles(rising_prices()), references(), portfolio()
    )
    assert result.proposal is None
    assert "adverse_news_event" in result.no_trade_reasons
    assert result.feature_vector is not None
    assert result.feature_vector.news.adverse_event is True


async def test_sell_without_position_is_rejected_by_risk() -> None:
    result = await pipeline().process(
        tick(), make_candles(falling_prices()), references(), portfolio()
    )
    assert result.proposal is not None
    assert result.proposal.side is Side.SELL
    assert result.risk_result is not None
    assert result.risk_result.decision is RiskDecision.REJECT
    assert "no_position_to_reduce" in result.risk_result.reasons
    assert result.paper_order is None


async def test_meta_agent_approval_flows_through() -> None:
    async def approving_client(_: EvidencePacket) -> MetaAgentDecision:
        return MetaAgentDecision(approve=True, confidence_delta=-0.1, rationale="corroborated")

    meta = ConstrainedMetaAgent(client=approving_client)
    result = await pipeline(meta_agent=meta).process(
        tick(), make_candles(rising_prices()), references(), portfolio()
    )
    assert result.proposal is not None
    assert result.proposal.strategy_id == "claude_meta_v1"
    assert result.paper_order is not None


async def test_meta_agent_veto_blocks_proposal() -> None:
    async def vetoing_client(_: EvidencePacket) -> MetaAgentDecision:
        return MetaAgentDecision(approve=False, confidence_delta=0, rationale="stale evidence")

    meta = ConstrainedMetaAgent(client=vetoing_client)
    result = await pipeline(meta_agent=meta).process(
        tick(), make_candles(rising_prices()), references(), portfolio()
    )
    assert result.proposal is None
    assert "meta_agent_veto" in result.no_trade_reasons
    assert result.paper_order is None


async def test_meta_agent_failure_fails_closed() -> None:
    async def broken_client(_: EvidencePacket) -> MetaAgentDecision:
        raise RuntimeError("api down")

    meta = ConstrainedMetaAgent(client=broken_client)
    result = await pipeline(meta_agent=meta).process(
        tick(), make_candles(rising_prices()), references(), portfolio()
    )
    assert result.proposal is None
    assert "meta_agent_unavailable" in result.no_trade_reasons
    assert result.paper_order is None


async def test_intelligence_failure_falls_back_to_market_only() -> None:
    async def broken_news(asset: str) -> NewsSnapshot:
        raise RuntimeError("provider down")

    orchestrator = IntelligenceOrchestrator(news=(broken_news,), require_any_external=True)
    result = await pipeline(intelligence=orchestrator).process(
        tick(), make_candles(rising_prices()), references(), portfolio()
    )
    assert result.accepted_market_data is True
    assert result.proposal is not None
    assert result.paper_order is not None
