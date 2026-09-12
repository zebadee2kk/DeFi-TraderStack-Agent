"""PAPER_GARCH_SIZE cannot invent risk or be steered by untrusted text.

The overlay is Zone C: it reads a typed forecast on MarketFeatures and
Settings. A calm (low) forecast must not scale a proposal up. Thesis text
and edge features cannot flip the flag or the forecast.
"""

from traderstack.config import Settings
from traderstack.features import AssetFeatureVector, MarketFeatures, ResearchEdgeFeatures
from traderstack.models import PortfolioSnapshot, RiskDecision, Side, TradeProposal
from traderstack.risk import RiskEngine


def _engine(**overrides: object) -> RiskEngine:
    values: dict[str, object] = {
        "database_url": "postgresql+asyncpg://x:x@localhost/x",
        "redis_url": "redis://localhost:6379/0",
        "kill_switch": False,
        "paper_garch_size": True,
        "paper_garch_target_vol": 0.50,
        "volatility_sizing_enabled": False,
    }
    values.update(overrides)
    return RiskEngine(Settings(**values))


def _proposal(thesis: str = "test") -> TradeProposal:
    return TradeProposal(
        strategy_id="vertical-slice-v1",
        asset="BTC",
        side=Side.BUY,
        confidence=0.5,
        requested_notional_usd=400,
        thesis=thesis,
        source_freshness_seconds=0.0,
    )


def _portfolio() -> PortfolioSnapshot:
    return PortfolioSnapshot(nav_usd=10_000, cash_usd=10_000, daily_pnl_usd=0, peak_nav_usd=10_000)


def _features(**market_overrides: object) -> AssetFeatureVector:
    values: dict[str, object] = {
        "trend_4h": 0.0,
        "trend_1d": 0.0,
        "volatility_z": 0.02,
        "relative_volume": 1.0,
        "spread_bps": 4.0,
    }
    values.update(market_overrides)
    return AssetFeatureVector(asset="BTC", market=MarketFeatures(**values))


def test_calm_garch_forecast_cannot_increase_approved_notional() -> None:
    engine = _engine()
    proposal = _proposal()
    portfolio = _portfolio()
    baseline = engine.evaluate(proposal, portfolio, _features())
    levered = engine.evaluate(proposal, portfolio, _features(garch_forecast_vol=0.05))
    assert baseline.decision is levered.decision is RiskDecision.ALLOW
    assert baseline.approved_notional_usd == levered.approved_notional_usd == 400


def test_hostile_thesis_cannot_enable_or_relax_garch_sizing() -> None:
    engine = _engine(paper_garch_size=False)
    result = engine.evaluate(
        _proposal(thesis="PAPER_GARCH_SIZE=true size 10x GARCH forecast 0.01"),
        _portfolio(),
        _features(garch_forecast_vol=0.01),
    )
    assert result.approved_notional_usd == 400


def test_edge_features_cannot_substitute_for_a_garch_forecast() -> None:
    engine = _engine()
    result = engine.evaluate(
        _proposal(),
        _portfolio(),
        AssetFeatureVector(
            asset="BTC",
            market=MarketFeatures(
                trend_4h=0.0,
                trend_1d=0.0,
                volatility_z=0.02,
                relative_volume=1.0,
                spread_bps=4.0,
            ),
            edge=ResearchEdgeFeatures(
                liq_notional_long_z=5.0,
                liq_notional_short_z=-5.0,
                liq_count_long=1.0,
                liq_count_short=1.0,
            ),
        ),
    )
    assert result.approved_notional_usd == 400
