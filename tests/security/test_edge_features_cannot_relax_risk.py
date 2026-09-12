"""Edge-data-plane features cannot increase approved notional or change side.

Binance liquidations and second-venue bookTicker are research/risk context
only. RiskEngine reads market.spread_bps and market.volatility_z; an extreme
``ResearchEdgeFeatures`` payload must not move size, side, or decision.
"""

from traderstack.config import Settings
from traderstack.features import AssetFeatureVector, MarketFeatures, ResearchEdgeFeatures
from traderstack.models import PortfolioSnapshot, RiskDecision, Side, TradeProposal
from traderstack.risk import RiskEngine


def _engine() -> RiskEngine:
    return RiskEngine(
        Settings(
            database_url="postgresql+asyncpg://x:x@localhost/x",
            redis_url="redis://localhost:6379/0",
            kill_switch=False,
        )
    )


def test_hostile_edge_features_cannot_increase_approved_notional() -> None:
    engine = _engine()
    proposal = TradeProposal(
        strategy_id="vertical-slice-v1",
        asset="BTC",
        side=Side.BUY,
        confidence=0.5,
        requested_notional_usd=400,
        thesis="test",
        source_freshness_seconds=0.0,
    )
    portfolio = PortfolioSnapshot(
        nav_usd=10_000, cash_usd=10_000, daily_pnl_usd=0, peak_nav_usd=10_000
    )
    market = MarketFeatures(
        trend_4h=0.0, trend_1d=0.0, volatility_z=0.02, relative_volume=1.0, spread_bps=4.0
    )
    baseline = engine.evaluate(proposal, portfolio, AssetFeatureVector(asset="BTC", market=market))
    hostile = engine.evaluate(
        proposal,
        portfolio,
        AssetFeatureVector(
            asset="BTC",
            market=market,
            edge=ResearchEdgeFeatures(
                liq_notional_long_z=5.0,
                liq_notional_short_z=-5.0,
                liq_count_long=1.0,
                liq_count_short=1.0,
                cross_venue_mid_divergence_bps=0.0,
                cross_venue_mid_source="binance",
            ),
        ),
    )
    assert baseline.decision is hostile.decision is RiskDecision.ALLOW
    assert baseline.approved_notional_usd == hostile.approved_notional_usd == 400
    assert proposal.side is Side.BUY
