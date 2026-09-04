from datetime import UTC, datetime, timedelta

import pytest

from traderstack.circuit_breaker import StrategyCircuitBreaker
from traderstack.config import Settings
from traderstack.features import AssetFeatureVector, MarketFeatures
from traderstack.killswitch import KillSwitch
from traderstack.models import PortfolioSnapshot, RiskDecision, Side, TradeProposal
from traderstack.risk import RiskEngine, derive_policy_version, risk_limits_hash


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


def test_allows_within_limits():
    result = RiskEngine(settings()).evaluate(proposal(), portfolio())
    assert result.decision == RiskDecision.ALLOW
    assert result.approved_notional_usd == 500


def test_reduces_to_position_limit():
    result = RiskEngine(settings()).evaluate(proposal(requested_notional_usd=2_000), portfolio())
    assert result.decision == RiskDecision.REDUCE
    assert result.approved_notional_usd == 1_000


def test_kill_switch_rejects():
    result = RiskEngine(settings(kill_switch=True)).evaluate(proposal(), portfolio())
    assert result.decision == RiskDecision.REJECT
    assert "kill_switch_enabled" in result.reasons


def test_daily_loss_rejects():
    result = RiskEngine(settings()).evaluate(proposal(), portfolio(daily_pnl_usd=-250))
    assert result.decision == RiskDecision.REJECT
    assert "daily_loss_limit_reached" in result.reasons


# --- risk plane (Epic 7) ---------------------------------------------------

NOW = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)


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


# --- volatility-based sizing ----------------------------------------------


def test_volatility_sizing_scales_notional_down_in_a_volatile_market():
    # target 2% vs observed 8% -> quarter size.
    result = RiskEngine(settings(target_volatility=0.02)).evaluate(
        proposal(requested_notional_usd=800), portfolio(), features(volatility_z=0.08)
    )
    assert result.decision == RiskDecision.REDUCE
    assert result.approved_notional_usd == pytest.approx(200)
    assert "volatility_scaled" in result.reasons
    assert "position_size_reduced" in result.reasons


def test_volatility_sizing_never_scales_above_the_requested_notional():
    # Observed volatility far below target would imply a 20x scale-up. The risk
    # engine does not invent risk nobody proposed.
    result = RiskEngine(settings(target_volatility=0.02)).evaluate(
        proposal(requested_notional_usd=500), portfolio(), features(volatility_z=0.001)
    )
    assert result.decision == RiskDecision.ALLOW
    assert result.approved_notional_usd == pytest.approx(500)
    assert "volatility_scaled" not in result.reasons


def test_volatility_sizing_is_still_capped_by_the_position_limit():
    # target/observed == 1 leaves the request intact; the 10% position limit
    # (1_000 on a 10_000 NAV) still binds.
    result = RiskEngine(settings(target_volatility=0.04)).evaluate(
        proposal(requested_notional_usd=5_000), portfolio(), features(volatility_z=0.04)
    )
    assert result.decision == RiskDecision.REDUCE
    assert result.approved_notional_usd == pytest.approx(1_000)


def test_volatility_sizing_can_be_disabled():
    result = RiskEngine(settings(volatility_sizing_enabled=False)).evaluate(
        proposal(requested_notional_usd=800), portfolio(), features(volatility_z=0.08)
    )
    assert result.decision == RiskDecision.ALLOW
    assert result.approved_notional_usd == pytest.approx(800)


def test_unknown_volatility_earns_no_scale_up():
    result = RiskEngine(settings()).evaluate(
        proposal(requested_notional_usd=500), portfolio(), features(volatility_z=0.0)
    )
    assert result.approved_notional_usd == pytest.approx(500)


def test_old_two_argument_signature_still_works():
    result = RiskEngine(settings()).evaluate(proposal(), portfolio())
    assert result.decision == RiskDecision.ALLOW
    assert result.approved_notional_usd == pytest.approx(500)


# --- liquidity / spread ----------------------------------------------------


def test_wide_spread_rejects():
    result = RiskEngine(settings(risk_max_spread_bps=30)).evaluate(
        proposal(), portfolio(), features(spread_bps=45)
    )
    assert result.decision == RiskDecision.REJECT
    assert "spread_too_wide" in result.reasons
    assert result.approved_notional_usd == 0


def test_spread_within_limit_allows():
    result = RiskEngine(settings(risk_max_spread_bps=30)).evaluate(
        proposal(), portfolio(), features(spread_bps=29.9)
    )
    assert result.decision == RiskDecision.ALLOW


# --- max simultaneous positions -------------------------------------------


def test_max_open_positions_rejects_a_new_asset():
    exposures = {"ETH": 100.0, "SOL": 100.0}
    result = RiskEngine(settings(max_open_positions=2)).evaluate(
        proposal(asset="BTC"), portfolio(asset_exposure_usd=exposures)
    )
    assert result.decision == RiskDecision.REJECT
    assert "max_positions_reached" in result.reasons


def test_max_open_positions_still_allows_adding_to_an_existing_position():
    exposures = {"ETH": 100.0, "BTC": 100.0}
    result = RiskEngine(settings(max_open_positions=2)).evaluate(
        proposal(asset="BTC"), portfolio(asset_exposure_usd=exposures)
    )
    assert result.decision == RiskDecision.ALLOW
    assert "max_positions_reached" not in result.reasons


def test_zero_exposure_entries_do_not_count_as_open_positions():
    exposures = {"ETH": 0.0, "SOL": 0.0}
    result = RiskEngine(settings(max_open_positions=1)).evaluate(
        proposal(asset="BTC"), portfolio(asset_exposure_usd=exposures)
    )
    assert result.decision == RiskDecision.ALLOW


# --- minimum cash reserve --------------------------------------------------


def test_cash_reserve_breach_rejects():
    result = RiskEngine(settings(min_cash_reserve_pct=0.20)).evaluate(
        proposal(), portfolio(cash_usd=1_500)
    )
    assert result.decision == RiskDecision.REJECT
    assert "cash_reserve_breached" in result.reasons


def test_cash_reserve_caps_the_approved_notional():
    # A 10% floor on a 10_000 NAV leaves 200 of the 1_200 cash spendable.
    result = RiskEngine(settings(min_cash_reserve_pct=0.10)).evaluate(
        proposal(requested_notional_usd=900), portfolio(cash_usd=1_200)
    )
    assert result.decision == RiskDecision.REDUCE
    assert result.approved_notional_usd == pytest.approx(200)


# --- max gross exposure ----------------------------------------------------


def test_gross_exposure_limit_rejects():
    exposures = {"ETH": 3_000.0, "SOL": 3_000.0}
    result = RiskEngine(settings(max_gross_exposure_pct=0.60)).evaluate(
        proposal(), portfolio(asset_exposure_usd=exposures)
    )
    assert result.decision == RiskDecision.REJECT
    assert "gross_exposure_limit" in result.reasons


def test_gross_exposure_room_caps_the_approved_notional():
    exposures = {"ETH": 2_800.0, "SOL": 2_800.0}
    result = RiskEngine(settings(max_gross_exposure_pct=0.60)).evaluate(
        proposal(requested_notional_usd=900), portfolio(asset_exposure_usd=exposures)
    )
    assert result.decision == RiskDecision.REDUCE
    assert result.approved_notional_usd == pytest.approx(400)


# --- stale-state shutdown --------------------------------------------------


def test_stale_portfolio_state_rejects():
    stale = portfolio(observed_at=NOW - timedelta(seconds=300))
    result = RiskEngine(settings(max_portfolio_state_age_seconds=60)).evaluate(
        proposal(), stale, now=NOW
    )
    assert result.decision == RiskDecision.REJECT
    assert "stale_portfolio_state" in result.reasons


def test_fresh_portfolio_state_allows():
    fresh = portfolio(observed_at=NOW - timedelta(seconds=5))
    result = RiskEngine(settings(max_portfolio_state_age_seconds=60)).evaluate(
        proposal(), fresh, now=NOW
    )
    assert result.decision == RiskDecision.ALLOW


# --- strategy circuit breaker ----------------------------------------------


def tripped_breaker(strategy_id="momentum-v1"):
    breaker = StrategyCircuitBreaker(max_consecutive_losses=2, cooldown_seconds=3_600)
    for _ in range(2):
        breaker.record_closed_trade(strategy_id, pnl_usd=-50, nav_usd=10_000, at=NOW)
    return breaker


def test_tripped_strategy_is_rejected():
    engine = RiskEngine(settings(), circuit_breaker=tripped_breaker())
    result = engine.evaluate(
        proposal(strategy_id="momentum-v1"), portfolio(observed_at=NOW), now=NOW
    )
    assert result.decision == RiskDecision.REJECT
    assert result.reasons == ["strategy_circuit_breaker"]


def test_other_strategies_are_unaffected_by_a_tripped_breaker():
    engine = RiskEngine(settings(), circuit_breaker=tripped_breaker())
    result = engine.evaluate(
        proposal(strategy_id="meanrev-v1"), portfolio(observed_at=NOW), now=NOW
    )
    assert result.decision == RiskDecision.ALLOW


def test_tripped_strategy_resumes_after_cooldown():
    engine = RiskEngine(settings(), circuit_breaker=tripped_breaker())
    later = NOW + timedelta(hours=2)
    result = engine.evaluate(
        proposal(strategy_id="momentum-v1"), portfolio(observed_at=later), now=later
    )
    assert result.decision == RiskDecision.ALLOW


# --- live kill switch ------------------------------------------------------


def test_live_kill_switch_overrides_a_permissive_setting(tmp_path):
    sentinel = tmp_path / "KILL"
    switch = KillSwitch(settings_flag=False, sentinel_path=sentinel)
    engine = RiskEngine(settings(kill_switch=False), kill_switch=switch)

    assert engine.evaluate(proposal(), portfolio()).decision == RiskDecision.ALLOW

    sentinel.write_text("halt", encoding="utf-8")
    result = engine.evaluate(proposal(), portfolio())
    assert result.decision == RiskDecision.REJECT
    assert result.reasons == ["kill_switch_enabled"]
    assert result.approved_notional_usd == 0


def test_kill_switch_outranks_every_other_reason(tmp_path):
    sentinel = tmp_path / "KILL"
    sentinel.write_text("halt", encoding="utf-8")
    engine = RiskEngine(
        settings(kill_switch=False), kill_switch=KillSwitch(sentinel_path=sentinel)
    )
    result = engine.evaluate(proposal(asset="DOGE"), portfolio(daily_pnl_usd=-9_000))
    assert result.reasons == ["kill_switch_enabled"]


# --- policy versioning -----------------------------------------------------


def test_policy_version_combines_the_label_and_a_limit_digest():
    config = settings()
    version = RiskEngine(config).policy_version
    label, _, digest = version.partition("+")
    assert label == config.risk_policy_label
    assert risk_limits_hash(config).startswith(digest)


def test_changing_a_limit_changes_the_policy_version():
    baseline = RiskEngine(settings(max_position_pct=0.10)).policy_version
    loosened = RiskEngine(settings(max_position_pct=0.20)).policy_version
    assert baseline != loosened


@pytest.mark.parametrize(
    "change",
    [
        {"max_daily_loss_pct": 0.05},
        {"max_account_drawdown_pct": 0.25},
        {"max_open_positions": 9},
        {"min_cash_reserve_pct": 0.5},
        {"max_gross_exposure_pct": 0.9},
        {"max_portfolio_state_age_seconds": 600},
        {"risk_max_spread_bps": 200},
        {"target_volatility": 0.5},
        {"volatility_sizing_enabled": False},
        {"strategy_max_consecutive_losses": 20},
        {"strategy_breaker_cooldown_seconds": 1},
        {"mvp_assets": "BTC,ETH,SOL,DOGE"},
        {"kill_switch": True},
    ],
)
def test_every_risk_limit_is_covered_by_the_policy_version(change):
    assert RiskEngine(settings()).policy_version != RiskEngine(settings(**change)).policy_version


def test_a_non_risk_setting_does_not_change_the_policy_version():
    baseline = RiskEngine(settings()).policy_version
    assert RiskEngine(settings(log_level="DEBUG")).policy_version == baseline


def test_manual_label_can_be_bumped_without_a_limit_change():
    config = settings()
    assert derive_policy_version(config, "mvp-v2") != derive_policy_version(config, "mvp-v1")


def test_policy_version_is_stamped_on_every_result():
    engine = RiskEngine(settings())
    allowed = engine.evaluate(proposal(), portfolio())
    rejected = engine.evaluate(proposal(asset="DOGE"), portfolio())
    assert allowed.policy_version == engine.policy_version
    assert rejected.policy_version == engine.policy_version


# --- control hierarchy -----------------------------------------------------


def test_portfolio_layer_rejection_survives_a_valid_trade_layer():
    # A perfectly sized, allowlisted, liquid proposal is still refused while the
    # account drawdown limit is breached.
    result = RiskEngine(settings()).evaluate(
        proposal(requested_notional_usd=100),
        portfolio(nav_usd=8_000, peak_nav_usd=10_000),
        features(),
    )
    assert result.decision == RiskDecision.REJECT
    assert "account_drawdown_limit_reached" in result.reasons
