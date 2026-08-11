from traderstack.config import Settings
from traderstack.models import PortfolioSnapshot, RiskDecision, Side, TradeProposal
from traderstack.risk import RiskEngine


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
