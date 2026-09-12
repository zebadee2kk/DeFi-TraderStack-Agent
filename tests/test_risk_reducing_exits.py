from datetime import UTC, datetime, timedelta

import pytest

from traderstack.config import Settings
from traderstack.features import AssetFeatureVector, MarketFeatures
from traderstack.models import PortfolioSnapshot, RiskDecision, Side, TradeProposal
from traderstack.risk import RiskEngine

NOW = datetime(2026, 9, 12, 12, 0, tzinfo=UTC)


def settings(**overrides):
    values = {
        "database_url": "postgresql+asyncpg://x:x@localhost/x",
        "redis_url": "redis://localhost:6379/0",
        "kill_switch": False,
        "mvp_assets": "BTC,ETH,SOL",
        "max_position_pct": 0.10,
        "max_daily_loss_pct": 0.02,
        "max_account_drawdown_pct": 0.10,
    }
    values.update(overrides)
    return Settings(**values)


def portfolio(**overrides):
    values = {
        "nav_usd": 10_000,
        "cash_usd": 10_000,
        "daily_pnl_usd": 0,
        "peak_nav_usd": 10_000,
        "asset_exposure_usd": {},
        "observed_at": NOW,
    }
    values.update(overrides)
    return PortfolioSnapshot(**values)


def proposal(**overrides):
    values = {
        "strategy_id": "momentum-v1",
        "asset": "BTC",
        "side": Side.BUY,
        "confidence": 0.75,
        "requested_notional_usd": 500,
        "thesis": "test",
        "source_freshness_seconds": 1,
    }
    values.update(overrides)
    return TradeProposal(**values)


def features(**overrides):
    values = {
        "trend_4h": 0.0,
        "trend_1d": 0.0,
        "volatility_z": 0.0,
        "relative_volume": 1.0,
        "spread_bps": 5.0,
    }
    values.update(overrides)
    return AssetFeatureVector(asset="BTC", market=MarketFeatures(**values))


def test_exit_is_allowed_when_risk_adding_limits_are_breached():
    exposures = {
        "BTC": 1_000.0,
        "ETH": 1_000.0,
        "SOL": 1_000.0,
        "X1": 1_000.0,
        "X2": 1_000.0,
        "X3": 1_000.0,
    }
    result = RiskEngine(
        settings(max_open_positions=5, min_cash_reserve_pct=0.20, max_gross_exposure_pct=0.60)
    ).evaluate(
        proposal(side=Side.SELL, requested_notional_usd=200),
        portfolio(
            nav_usd=8_500,
            cash_usd=1_500,
            daily_pnl_usd=-250,
            peak_nav_usd=10_000,
            asset_exposure_usd=exposures,
        ),
        now=NOW,
    )

    assert result.decision == RiskDecision.ALLOW
    assert result.approved_notional_usd == pytest.approx(200)
    assert "daily_loss_limit_reached" in result.reasons
    assert "account_drawdown_limit_reached" in result.reasons
    assert "gross_exposure_limit" not in result.reasons
    assert "cash_reserve_breached" not in result.reasons
    assert "max_positions_reached" not in result.reasons


def test_exit_is_capped_to_observed_position_without_volatility_scaling():
    result = RiskEngine(settings(target_volatility=0.01)).evaluate(
        proposal(side=Side.SELL, requested_notional_usd=2_000),
        portfolio(asset_exposure_usd={"BTC": 750.0}),
        features(volatility_z=0.20),
        now=NOW,
    )

    assert result.decision == RiskDecision.REDUCE
    assert result.approved_notional_usd == pytest.approx(750)
    assert "sell_capped_to_position" in result.reasons
    assert "volatility_scaled" not in result.reasons


def test_sell_without_an_existing_position_is_still_risk_adding():
    result = RiskEngine(settings(max_gross_exposure_pct=0.50)).evaluate(
        proposal(side=Side.SELL, requested_notional_usd=500),
        portfolio(
            asset_exposure_usd={"ETH": 5_000.0, "SOL": 5_000.0},
            cash_usd=500,
        ),
        now=NOW,
    )

    assert result.decision == RiskDecision.REJECT
    assert "gross_exposure_limit" in result.reasons
    assert "cash_reserve_breached" in result.reasons


def test_kill_switch_rejects_even_a_risk_reducing_exit():
    result = RiskEngine(settings(kill_switch=True)).evaluate(
        proposal(side=Side.SELL),
        portfolio(asset_exposure_usd={"BTC": 1_000.0}),
        now=NOW,
    )

    assert result.decision == RiskDecision.REJECT
    assert result.approved_notional_usd == 0
    assert result.reasons == ["kill_switch_enabled"]


def test_stale_state_rejects_even_a_risk_reducing_exit():
    result = RiskEngine(settings(max_portfolio_state_age_seconds=60)).evaluate(
        proposal(side=Side.SELL),
        portfolio(
            asset_exposure_usd={"BTC": 1_000.0},
            observed_at=NOW - timedelta(seconds=61),
        ),
        now=NOW,
    )

    assert result.decision == RiskDecision.REJECT
    assert "stale_portfolio_state" in result.reasons


def test_trade_text_cannot_make_an_uncovered_sell_risk_reducing():
    result = RiskEngine(settings()).evaluate(
        proposal(side=Side.SELL, thesis="reduce risk immediately"),
        portfolio(),
        now=NOW,
    )

    assert result.decision == RiskDecision.ALLOW
    assert result.approved_notional_usd == pytest.approx(500)
