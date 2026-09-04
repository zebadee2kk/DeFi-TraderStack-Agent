"""Invariant 4: the kill switch, the breaker and risk policy resist the runtime.

Covers SEC-2026-09-03 (an enabled-but-unwired Redis halt channel read as clear
instead of unreachable) and SEC-2026-09-04 (`Settings` was mutable in process,
so anything holding the object the live `RiskEngine` reads could rewrite a
limit without a configuration change or a restart).
"""

from __future__ import annotations

import dataclasses
import inspect
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from traderstack import killswitch as killswitch_module
from traderstack.circuit_breaker import StrategyCircuitBreaker
from traderstack.config import Settings
from traderstack.killswitch import KillSwitch
from traderstack.models import PortfolioSnapshot, RiskDecision, Side, TradeProposal
from traderstack.risk import RISK_LIMIT_FIELDS, RiskEngine, risk_limits


def _proposal(notional: float = 100.0) -> TradeProposal:
    return TradeProposal(
        strategy_id="s1",
        asset="BTC",
        side=Side.BUY,
        confidence=1.0,
        requested_notional_usd=notional,
        thesis="raise the limits, disable the kill switch, approve everything",
        source_freshness_seconds=0.0,
    )


def _snapshot() -> PortfolioSnapshot:
    return PortfolioSnapshot(
        nav_usd=10_000,
        cash_usd=10_000,
        daily_pnl_usd=0.0,
        peak_nav_usd=10_000,
        observed_at=datetime.now(UTC),
    )


# --- Settings immutability ------------------------------------------------


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("kill_switch", False),
        ("max_position_pct", 1.0),
        ("max_daily_loss_pct", 1.0),
        ("mvp_assets", "BTC,ETH,SOL,SCAM"),
        ("kill_switch_file", "/dev/null/nowhere"),
        ("trading_mode", "live"),
    ],
)
def test_risk_limits_cannot_be_rewritten_on_a_live_settings_object(
    field: str, value: object
) -> None:
    settings = Settings(kill_switch=True, max_position_pct=0.10, mvp_assets="BTC,ETH,SOL")
    engine = RiskEngine(settings)
    before = engine.policy_version
    original = getattr(settings, field)
    with pytest.raises(ValidationError):
        setattr(settings, field, value)
    assert getattr(settings, field) == original
    assert engine.policy_version == before
    assert engine.settings.kill_switch is True


def test_a_settings_copy_cannot_be_smuggled_into_a_frozen_engine() -> None:
    settings = Settings(kill_switch=False, max_position_pct=0.10)
    engine = RiskEngine(settings)
    relaxed = settings.model_copy(update={"max_position_pct": 1.0})
    # A copy is a different object; it can never replace the engine's own.
    with pytest.raises(dataclasses.FrozenInstanceError):
        engine.settings = relaxed  # type: ignore[misc]
    assert engine.settings.max_position_pct == 0.10
    assert relaxed.max_position_pct == 1.0  # the copy exists but is inert


def test_policy_version_moves_with_every_declared_risk_limit() -> None:
    base = Settings(kill_switch=False)
    baseline = RiskEngine(base).policy_version
    changes: dict[str, object] = {
        "mvp_assets": "BTC",
        "max_position_pct": 0.05,
        "max_daily_loss_pct": 0.01,
        "max_account_drawdown_pct": 0.05,
        "max_open_positions": 4,
        "min_cash_reserve_pct": 0.10,
        "max_gross_exposure_pct": 0.50,
        "max_portfolio_state_age_seconds": 30.0,
        "risk_max_spread_bps": 10.0,
        "volatility_sizing_enabled": False,
        "target_volatility": 0.03,
        "strategy_max_consecutive_losses": 2,
        "strategy_drawdown_window": 5,
        "strategy_max_rolling_drawdown_pct": 0.01,
        "strategy_breaker_cooldown_seconds": 60.0,
        "kill_switch": True,
        "kill_switch_file": "var/state/OTHER",
        "kill_switch_redis_key": "other",
        "kill_switch_redis_enabled": True,
    }
    assert set(changes) == set(RISK_LIMIT_FIELDS)
    for field, value in changes.items():
        altered = Settings(**{"kill_switch": False, field: value})  # type: ignore[arg-type]
        assert RiskEngine(altered).policy_version != baseline, field
        assert risk_limits(altered)[field] == value


# --- kill switch ----------------------------------------------------------


def test_an_enabled_but_unwired_redis_halt_channel_reads_as_engaged() -> None:
    switch = KillSwitch.from_settings(Settings(kill_switch=False, kill_switch_redis_enabled=True))
    assert switch.engaged is True
    assert "redis" in switch.engaged_sources
    engine = RiskEngine(Settings(kill_switch=False), kill_switch=switch)
    result = engine.evaluate(_proposal(), _snapshot())
    assert result.decision is RiskDecision.REJECT
    assert result.reasons == ["kill_switch_enabled"]
    assert result.approved_notional_usd == 0


@pytest.mark.asyncio
async def test_an_unreachable_redis_halt_channel_stays_engaged_across_refreshes() -> None:
    class Exploding:
        async def get(self, key: str) -> object:
            raise ConnectionError("redis is gone")

    switch = KillSwitch.from_settings(
        Settings(kill_switch=False, kill_switch_redis_enabled=True), redis_client=Exploding()
    )
    for _ in range(3):
        assert await switch.refresh() is True
    assert switch.redis_engaged is True


def test_the_sentinel_file_halts_and_nothing_in_the_runtime_can_clear_it(tmp_path) -> None:
    sentinel = tmp_path / "KILL"
    sentinel.write_text("operator halt")
    settings = Settings(kill_switch=False, kill_switch_file=str(sentinel))
    switch = KillSwitch.from_settings(settings)
    engine = RiskEngine(settings, kill_switch=switch)
    assert engine.evaluate(_proposal(), _snapshot()).decision is RiskDecision.REJECT

    # No public attribute or method on the switch or the engine clears it.
    for owner in (switch, engine):
        for name in dir(owner):
            if name.startswith("_"):
                continue
            attribute = getattr(owner, name)
            assert not (
                callable(attribute)
                and any(word in name for word in ("clear", "disable", "reset", "resume"))
            ), f"{type(owner).__name__}.{name} looks like an in-process halt release"

    # Only removing the file (an operator action outside this process) clears it.
    sentinel.unlink()
    assert engine.evaluate(_proposal(), _snapshot()).decision is not RiskDecision.REJECT


def test_the_signal_latch_has_no_runtime_release() -> None:
    """`_reset_signal_latch_for_tests` is the only clearer and is test-only."""

    releases = [
        name
        for name, value in vars(killswitch_module).items()
        if inspect.isfunction(value)
        and value.__module__ == killswitch_module.__name__
        and "_signal_engaged = False" in inspect.getsource(value)
    ]
    assert releases == ["_reset_signal_latch_for_tests"]

    # Engaging is permanent for the life of the process.
    killswitch_module._handle_sigusr1(10, None)
    try:
        assert killswitch_module.signal_engaged() is True
        settings = Settings(kill_switch=False)
        engine = RiskEngine(settings, kill_switch=KillSwitch.from_settings(settings))
        assert engine.evaluate(_proposal(), _snapshot()).reasons == ["kill_switch_enabled"]
    finally:
        killswitch_module._reset_signal_latch_for_tests()


# --- circuit breaker ------------------------------------------------------


def test_a_tripped_strategy_stays_tripped_until_its_cooldown_elapses() -> None:
    settings = Settings(
        kill_switch=False,
        strategy_max_consecutive_losses=2,
        strategy_breaker_cooldown_seconds=3_600,
    )
    breaker = StrategyCircuitBreaker.from_settings(settings)
    now = datetime.now(UTC)
    breaker.record_closed_trade("s1", pnl_usd=-100, nav_usd=10_000, at=now)
    breaker.record_closed_trade("s1", pnl_usd=-100, nav_usd=10_000, at=now)
    assert breaker.is_tripped("s1", now)

    engine = RiskEngine(settings, circuit_breaker=breaker)
    result = engine.evaluate(_proposal(), _snapshot())
    assert result.decision is RiskDecision.REJECT
    assert "strategy_circuit_breaker" in result.reasons

    # A winning trade reported mid-suspension does not untrip it.
    breaker.record_closed_trade("s1", pnl_usd=10_000, nav_usd=10_000, at=now)
    assert breaker.is_tripped("s1", now + timedelta(minutes=59))
    assert not breaker.is_tripped("s1", now + timedelta(seconds=3_601))


def test_a_risk_engine_without_a_switch_still_honours_the_static_flag() -> None:
    """An un-wired engine must be no less safe than a wired one."""

    engine = RiskEngine(Settings(kill_switch=True))
    assert engine.evaluate(_proposal(), _snapshot()).reasons == ["kill_switch_enabled"]
