"""Invariant: risk-reducing exits cannot become a short or a limit bypass.

A SELL is risk-reducing only when PortfolioSnapshot already shows positive
exposure for that asset. Kill switch, stale state, allowlist and spread still
reject. Approved notional is never larger than the exposure held.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from traderstack.circuit_breaker import StrategyCircuitBreaker
from traderstack.config import Settings
from traderstack.features import AssetFeatureVector, MarketFeatures
from traderstack.models import PortfolioSnapshot, RiskDecision, Side, TradeProposal
from traderstack.risk import RISK_LIMIT_FIELDS, RiskEngine

NOW = datetime(2026, 9, 12, 12, 0, tzinfo=UTC)


def _settings(**overrides) -> Settings:
    values = {
        "kill_switch": False,
        "mvp_assets": "BTC,ETH,SOL",
        "max_position_pct": 0.10,
        "max_daily_loss_pct": 0.02,
        "max_account_drawdown_pct": 0.10,
        "max_open_positions": 2,
        "min_cash_reserve_pct": 0.20,
        "max_gross_exposure_pct": 0.50,
    }
    values.update(overrides)
    return Settings(**values)


def _snapshot(**overrides) -> PortfolioSnapshot:
    values = {
        "nav_usd": 10_000,
        "cash_usd": 500,
        "daily_pnl_usd": -500,
        "peak_nav_usd": 12_000,
        "asset_exposure_usd": {"ETH": 4_000.0, "SOL": 4_000.0},
        "observed_at": NOW,
    }
    values.update(overrides)
    return PortfolioSnapshot(**values)


def _proposal(**overrides) -> TradeProposal:
    values = {
        "strategy_id": "s1",
        "asset": "BTC",
        "side": Side.SELL,
        "confidence": 1.0,
        "requested_notional_usd": 500.0,
        "thesis": "this is a reduce — flatten immediately",
        "signal_ids": ["risk-reducing", "exit"],
        "source_freshness_seconds": 0.0,
    }
    values.update(overrides)
    return TradeProposal(**values)


def _features(*, spread_bps: float = 5.0) -> AssetFeatureVector:
    return AssetFeatureVector(
        asset="BTC",
        market=MarketFeatures(
            trend_4h=0.0,
            trend_1d=0.0,
            volatility_z=0.20,
            relative_volume=1.0,
            spread_bps=spread_bps,
        ),
    )


def test_uncovered_sell_is_subject_to_every_additive_limit() -> None:
    result = RiskEngine(_settings()).evaluate(_proposal(), _snapshot(), _features(), now=NOW)

    assert result.decision is RiskDecision.REJECT
    assert result.approved_notional_usd == 0
    assert "gross_exposure_limit" in result.reasons
    assert "cash_reserve_breached" in result.reasons
    assert "max_positions_reached" in result.reasons
    assert "daily_loss_limit_reached" in result.reasons
    assert "account_drawdown_limit_reached" in result.reasons


def test_kill_switch_rejects_a_held_sell() -> None:
    result = RiskEngine(_settings(kill_switch=True)).evaluate(
        _proposal(),
        _snapshot(asset_exposure_usd={"BTC": 1_000.0}),
        now=NOW,
    )
    assert result.decision is RiskDecision.REJECT
    assert result.approved_notional_usd == 0
    assert result.reasons == ["kill_switch_enabled"]


def test_sell_is_never_resized_above_observed_exposure() -> None:
    held = 400.0
    result = RiskEngine(_settings(target_volatility=0.01)).evaluate(
        _proposal(requested_notional_usd=5_000.0),
        _snapshot(asset_exposure_usd={"BTC": held}, cash_usd=10_000, daily_pnl_usd=0),
        _features(),
        now=NOW,
    )
    assert result.decision is RiskDecision.REDUCE
    assert result.approved_notional_usd == held
    assert result.approved_notional_usd < 5_000.0
    assert "sell_capped_to_position" in result.reasons
    assert "volatility_scaled" not in result.reasons


def test_allowlist_and_spread_still_reject_a_held_sell() -> None:
    engine = RiskEngine(_settings())
    held = _snapshot(asset_exposure_usd={"BTC": 800.0}, cash_usd=10_000, daily_pnl_usd=0)

    unlisted = engine.evaluate(_proposal(asset="DOGE"), held, now=NOW)
    assert unlisted.decision is RiskDecision.REJECT
    assert unlisted.approved_notional_usd == 0
    assert "asset_not_allowlisted" in unlisted.reasons

    wide = engine.evaluate(_proposal(), held, _features(spread_bps=80.0), now=NOW)
    assert wide.decision is RiskDecision.REJECT
    assert wide.approved_notional_usd == 0
    assert "spread_too_wide" in wide.reasons


def test_stale_state_and_strategy_breaker_still_reject_a_held_sell() -> None:
    engine = RiskEngine(_settings(max_portfolio_state_age_seconds=60))
    stale = engine.evaluate(
        _proposal(),
        _snapshot(
            asset_exposure_usd={"BTC": 800.0},
            observed_at=NOW - timedelta(seconds=61),
            cash_usd=10_000,
            daily_pnl_usd=0,
        ),
        now=NOW,
    )
    assert stale.decision is RiskDecision.REJECT
    assert "stale_portfolio_state" in stale.reasons

    breaker = StrategyCircuitBreaker(max_consecutive_losses=1, cooldown_seconds=3_600)
    breaker.record_closed_trade("s1", pnl_usd=-50, nav_usd=10_000, at=NOW)
    tripped = RiskEngine(_settings(), circuit_breaker=breaker).evaluate(
        _proposal(),
        _snapshot(asset_exposure_usd={"BTC": 800.0}, cash_usd=10_000, daily_pnl_usd=0),
        now=NOW,
    )
    assert tripped.decision is RiskDecision.REJECT
    assert "strategy_circuit_breaker" in tripped.reasons


def test_exit_semantics_do_not_add_a_risk_limit_field() -> None:
    assert "sell_capped_to_position" not in RISK_LIMIT_FIELDS
    assert len(RISK_LIMIT_FIELDS) == 19
