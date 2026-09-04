from datetime import UTC, datetime, timedelta

import pytest

from traderstack.circuit_breaker import (
    TRIP_CONSECUTIVE_LOSSES,
    TRIP_ROLLING_DRAWDOWN,
    PortfolioRealizedPnLFeeder,
    StrategyCircuitBreaker,
    rolling_drawdown,
)
from traderstack.config import Settings
from traderstack.execution.ledger import ExecutionFill, ExecutionLedger, ExecutionOrder
from traderstack.models import Side
from traderstack.portfolio import InMemoryPortfolioBook

NOW = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)


def breaker(**overrides: object) -> StrategyCircuitBreaker:
    values: dict[str, object] = {
        "max_consecutive_losses": 3,
        "drawdown_window": 10,
        "max_rolling_drawdown_pct": 0.05,
        "cooldown_seconds": 3_600.0,
    }
    values.update(overrides)
    return StrategyCircuitBreaker(**values)  # type: ignore[arg-type]


# --- trip -----------------------------------------------------------------


def test_trips_on_consecutive_losses() -> None:
    cb = breaker()
    for index in range(2):
        cb.record_closed_trade("momentum-v1", pnl_usd=-10, nav_usd=10_000, at=NOW)
        assert not cb.is_tripped("momentum-v1", NOW), f"tripped too early at loss {index}"

    cb.record_closed_trade("momentum-v1", pnl_usd=-10, nav_usd=10_000, at=NOW)
    assert cb.is_tripped("momentum-v1", NOW)
    assert cb.state_for("momentum-v1").trip_reason == TRIP_CONSECUTIVE_LOSSES


def test_trips_on_rolling_drawdown_without_consecutive_losses() -> None:
    cb = breaker(max_consecutive_losses=99)
    # Alternating wins/losses never hits the consecutive-loss rule but the
    # cumulative curve still falls 6% peak-to-trough.
    for pnl in (200, -400, 100, -300, 50, -250):
        cb.record_closed_trade("meanrev-v1", pnl_usd=pnl, nav_usd=10_000, at=NOW)

    assert cb.is_tripped("meanrev-v1", NOW)
    assert cb.state_for("meanrev-v1").trip_reason == TRIP_ROLLING_DRAWDOWN


def test_rolling_drawdown_only_counts_the_configured_window() -> None:
    cb = breaker(max_consecutive_losses=99, drawdown_window=3, max_rolling_drawdown_pct=0.99)
    for pnl in (-100, -100, -100, 500):
        cb.record_closed_trade("window-v1", pnl_usd=pnl, nav_usd=10_000, at=NOW)

    state = cb.state_for("window-v1")
    assert len(state.closed_trades) == 3
    assert [t.pnl_usd for t in state.closed_trades] == [-100, -100, 500]


def test_rolling_drawdown_is_peak_to_trough() -> None:
    cb = breaker()
    for pnl in (100, -50):
        cb.record_closed_trade("s", pnl_usd=pnl, nav_usd=1_000)
    assert rolling_drawdown(cb.state_for("s").closed_trades) == pytest.approx(0.05)


# --- hold -----------------------------------------------------------------


def test_holds_tripped_for_the_whole_cooldown() -> None:
    cb = breaker(cooldown_seconds=3_600)
    for _ in range(3):
        cb.record_closed_trade("momentum-v1", pnl_usd=-10, nav_usd=10_000, at=NOW)

    assert cb.is_tripped("momentum-v1", NOW)
    assert cb.is_tripped("momentum-v1", NOW + timedelta(minutes=59))
    # A subsequent winner does not un-trip it: only the cool-down does.
    cb.record_closed_trade("momentum-v1", pnl_usd=5_000, nav_usd=10_000, at=NOW)
    assert cb.is_tripped("momentum-v1", NOW + timedelta(minutes=59))


def test_only_the_failing_strategy_is_suspended() -> None:
    cb = breaker()
    for _ in range(3):
        cb.record_closed_trade("momentum-v1", pnl_usd=-10, nav_usd=10_000, at=NOW)
    cb.record_closed_trade("meanrev-v1", pnl_usd=10, nav_usd=10_000, at=NOW)

    assert cb.is_tripped("momentum-v1", NOW)
    assert not cb.is_tripped("meanrev-v1", NOW)
    assert not cb.is_tripped("never-traded-v1", NOW)


def test_a_win_resets_the_consecutive_loss_counter() -> None:
    cb = breaker()
    cb.record_closed_trade("s", pnl_usd=-10, nav_usd=10_000, at=NOW)
    cb.record_closed_trade("s", pnl_usd=-10, nav_usd=10_000, at=NOW)
    cb.record_closed_trade("s", pnl_usd=1, nav_usd=10_000, at=NOW)
    cb.record_closed_trade("s", pnl_usd=-10, nav_usd=10_000, at=NOW)

    assert cb.state_for("s").consecutive_losses == 1
    assert not cb.is_tripped("s", NOW)


# --- reset ----------------------------------------------------------------


def test_resets_after_cooldown_elapses() -> None:
    cb = breaker(cooldown_seconds=3_600)
    for _ in range(3):
        cb.record_closed_trade("momentum-v1", pnl_usd=-10, nav_usd=10_000, at=NOW)

    assert cb.is_tripped("momentum-v1", NOW)
    assert not cb.is_tripped("momentum-v1", NOW + timedelta(hours=1))

    state = cb.state_for("momentum-v1")
    assert state.tripped_at is None
    assert state.trip_reason is None
    assert state.consecutive_losses == 0
    assert state.closed_trades == []


def test_reset_then_retrips_on_fresh_losses() -> None:
    cb = breaker(cooldown_seconds=60)
    for _ in range(3):
        cb.record_closed_trade("s", pnl_usd=-10, nav_usd=10_000, at=NOW)
    later = NOW + timedelta(minutes=5)
    assert not cb.is_tripped("s", later)

    for _ in range(3):
        cb.record_closed_trade("s", pnl_usd=-10, nav_usd=10_000, at=later)
    assert cb.is_tripped("s", later)


# --- feeds ----------------------------------------------------------------


def test_records_realized_pnl_from_a_filled_ledger_close() -> None:
    ledger = ExecutionLedger()
    ledger.register_order(
        ExecutionOrder(
            order_id="o-1",
            decision_id="d-1",
            asset="ETH",
            side=Side.SELL,
            requested_quantity=2.0,
        )
    )
    ledger.record_fill(
        ExecutionFill(
            fill_id="f-1", order_id="o-1", asset="ETH", side=Side.SELL, quantity=2.0, price_usd=900
        )
    )

    cb = breaker()
    state = cb.record_ledger_close(
        ledger.orders["o-1"],
        strategy_id="momentum-v1",
        entry_price_usd=1_000,
        nav_usd=10_000,
        at=NOW,
    )
    assert state is not None
    assert state.closed_trades[-1].pnl_usd == pytest.approx(-200)
    assert state.consecutive_losses == 1


def test_ledger_buy_orders_are_not_closed_trades() -> None:
    ledger = ExecutionLedger()
    ledger.register_order(
        ExecutionOrder(
            order_id="o-2", decision_id="d-2", asset="BTC", side=Side.BUY, requested_quantity=1.0
        )
    )
    ledger.record_fill(
        ExecutionFill(
            fill_id="f-2", order_id="o-2", asset="BTC", side=Side.BUY, quantity=1.0, price_usd=100
        )
    )

    cb = breaker()
    assert (
        cb.record_ledger_close(
            ledger.orders["o-2"], strategy_id="s", entry_price_usd=90, nav_usd=10_000
        )
        is None
    )
    assert cb.states == {}


def test_portfolio_realized_pnl_feeder_records_only_deltas() -> None:
    book = InMemoryPortfolioBook(starting_nav_usd=10_000)
    cb = breaker()
    feeder = PortfolioRealizedPnLFeeder(breaker=cb)

    assert feeder.observe("momentum-v1", book) is False

    book.apply_fill("ETH", Side.BUY, quantity=2, price_usd=1_000)
    book.apply_fill("ETH", Side.SELL, quantity=1, price_usd=900)
    assert feeder.observe("momentum-v1", book) is True
    assert cb.state_for("momentum-v1").closed_trades[-1].pnl_usd == pytest.approx(-100)

    # No new realized PnL since the last observation -> nothing recorded.
    assert feeder.observe("momentum-v1", book) is False
    assert len(cb.state_for("momentum-v1").closed_trades) == 1


def test_from_settings_reads_version_controlled_limits() -> None:
    cb = StrategyCircuitBreaker.from_settings(
        Settings(
            strategy_max_consecutive_losses=7,
            strategy_drawdown_window=4,
            strategy_max_rolling_drawdown_pct=0.2,
            strategy_breaker_cooldown_seconds=90,
        )
    )
    assert cb.max_consecutive_losses == 7
    assert cb.drawdown_window == 4
    assert cb.max_rolling_drawdown_pct == pytest.approx(0.2)
    assert cb.cooldown_seconds == pytest.approx(90)
