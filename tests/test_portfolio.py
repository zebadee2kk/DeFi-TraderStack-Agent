from datetime import UTC, datetime, timedelta

import pytest

from traderstack.models import Side
from traderstack.portfolio import InMemoryPortfolioBook, PortfolioState


def test_buy_fill_updates_cash_exposure_and_nav() -> None:
    book = InMemoryPortfolioBook(starting_nav_usd=10_000)
    book.apply_fill("BTC", Side.BUY, quantity=0.1, price_usd=20_000)

    snapshot = book.snapshot()
    assert snapshot.cash_usd == pytest.approx(8_000)
    assert snapshot.asset_exposure_usd["BTC"] == pytest.approx(2_000)
    assert snapshot.nav_usd == pytest.approx(10_000)

    book.mark("BTC", 22_000)
    snapshot = book.snapshot()
    assert snapshot.nav_usd == pytest.approx(10_200)
    assert snapshot.daily_pnl_usd == pytest.approx(200)


def test_sell_realizes_pnl_and_rejects_oversell() -> None:
    book = InMemoryPortfolioBook(starting_nav_usd=10_000)
    book.apply_fill("ETH", Side.BUY, quantity=2, price_usd=1_000)
    book.apply_fill("ETH", Side.SELL, quantity=1, price_usd=1_200)

    assert book.realized_pnl_usd == pytest.approx(200)
    assert book.snapshot().cash_usd == pytest.approx(9_200)

    with pytest.raises(ValueError, match="cannot sell more"):
        book.apply_fill("ETH", Side.SELL, quantity=2, price_usd=1_200)


# --- risk plane (Epic 7): daily PnL anchor ---------------------------------


def test_daily_pnl_is_daily_not_lifetime() -> None:
    """Yesterday's gains must not fund today's max_daily_loss_pct budget."""

    day_one = datetime(2026, 9, 3, 23, 0, tzinfo=UTC)
    book = InMemoryPortfolioBook(starting_nav_usd=10_000)
    book.apply_fill("BTC", Side.BUY, quantity=0.5, price_usd=20_000)

    book.mark("BTC", 24_000)
    snapshot = book.snapshot(now=day_one)
    assert snapshot.nav_usd == pytest.approx(12_000)
    assert snapshot.daily_pnl_usd == pytest.approx(2_000)

    # New UTC day: the anchor rolls to the 12_000 NAV carried into it.
    day_two = datetime(2026, 9, 4, 0, 30, tzinfo=UTC)
    snapshot = book.snapshot(now=day_two)
    assert snapshot.daily_pnl_usd == pytest.approx(0)
    assert book.day_start_nav_usd == pytest.approx(12_000)
    assert book.day_start_date == day_two.date()

    # A loss on day two is measured against day two's open, not inception.
    book.mark("BTC", 22_000)
    snapshot = book.snapshot(now=day_two + timedelta(hours=6))
    assert snapshot.nav_usd == pytest.approx(11_000)
    assert snapshot.daily_pnl_usd == pytest.approx(-1_000)
    # Lifetime PnL is still positive: the old snapshot() would have said +1_000.
    assert snapshot.nav_usd - book.starting_nav_usd == pytest.approx(1_000)


def test_anchor_does_not_roll_within_the_same_utc_day() -> None:
    morning = datetime(2026, 9, 4, 1, 0, tzinfo=UTC)
    evening = datetime(2026, 9, 4, 23, 59, tzinfo=UTC)
    book = InMemoryPortfolioBook(starting_nav_usd=10_000)
    book.snapshot(now=morning)

    book.apply_fill("ETH", Side.BUY, quantity=1, price_usd=1_000)
    book.mark("ETH", 800)
    snapshot = book.snapshot(now=evening)

    assert book.day_start_nav_usd == pytest.approx(10_000)
    assert snapshot.daily_pnl_usd == pytest.approx(-200)


def test_roll_day_reports_whether_it_rolled() -> None:
    book = InMemoryPortfolioBook(starting_nav_usd=10_000)
    day_one = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)
    # The first observation only stamps the date onto the existing anchor.
    assert book.roll_day(day_one) is False
    assert book.roll_day(day_one + timedelta(hours=1)) is False
    assert book.roll_day(day_one + timedelta(days=1)) is True
    assert book.day_start_date == (day_one + timedelta(days=1)).date()


def test_snapshot_stamps_observed_at() -> None:
    moment = datetime(2026, 9, 4, 8, 15, tzinfo=UTC)
    book = InMemoryPortfolioBook(starting_nav_usd=10_000)
    assert book.snapshot(now=moment).observed_at == moment


def test_anchor_survives_a_checkpoint_round_trip() -> None:
    day_one = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)
    book = InMemoryPortfolioBook(starting_nav_usd=10_000)
    book.apply_fill("BTC", Side.BUY, quantity=0.1, price_usd=20_000)
    book.mark("BTC", 30_000)
    book.snapshot(now=day_one)

    restored = InMemoryPortfolioBook.from_state(
        PortfolioState.model_validate_json(book.state().model_dump_json())
    )
    assert restored.day_start_date == day_one.date()
    assert restored.day_start_nav_usd == pytest.approx(book.day_start_nav_usd)
    assert restored.snapshot(now=day_one).daily_pnl_usd == pytest.approx(1_000)


# --- paper fees (#66) -------------------------------------------------------


def test_round_trip_at_constant_price_with_fees_lowers_nav() -> None:
    """A flat round trip must still reduce NAV, daily PnL and raise drawdown."""

    book = InMemoryPortfolioBook(starting_nav_usd=10_000)
    book.apply_fill("ETH", Side.BUY, quantity=1, price_usd=1_000, fee_usd=5)
    book.apply_fill("ETH", Side.SELL, quantity=1, price_usd=1_000, fee_usd=5)

    snapshot = book.snapshot()
    assert snapshot.nav_usd == pytest.approx(9_990)
    assert snapshot.daily_pnl_usd == pytest.approx(-10)
    assert snapshot.peak_nav_usd == pytest.approx(10_000)
    assert book.realized_pnl_usd == pytest.approx(-10)
    assert book.positions["ETH"].fees_paid_usd == pytest.approx(10)
    drawdown = 1 - snapshot.nav_usd / snapshot.peak_nav_usd
    assert drawdown == pytest.approx(0.001)


def test_buy_fee_is_debited_from_cash_and_nav() -> None:
    book = InMemoryPortfolioBook(starting_nav_usd=10_000)
    book.apply_fill("BTC", Side.BUY, quantity=0.1, price_usd=20_000, fee_usd=10)

    snapshot = book.snapshot()
    assert snapshot.cash_usd == pytest.approx(7_990)
    assert snapshot.asset_exposure_usd["BTC"] == pytest.approx(2_000)
    assert snapshot.nav_usd == pytest.approx(9_990)
    assert snapshot.daily_pnl_usd == pytest.approx(-10)


def test_fees_paid_survive_a_checkpoint_round_trip() -> None:
    book = InMemoryPortfolioBook(starting_nav_usd=10_000)
    book.apply_fill("BTC", Side.BUY, quantity=0.1, price_usd=20_000, fee_usd=3)

    restored = InMemoryPortfolioBook.from_state(
        PortfolioState.model_validate_json(book.state().model_dump_json())
    )
    assert restored.positions["BTC"].fees_paid_usd == pytest.approx(3)
    assert restored.nav_usd == pytest.approx(book.nav_usd)


def test_apply_fill_rejects_a_negative_or_non_finite_fee() -> None:
    book = InMemoryPortfolioBook(starting_nav_usd=10_000)
    with pytest.raises(ValueError, match="fee"):
        book.apply_fill("BTC", Side.BUY, quantity=0.1, price_usd=20_000, fee_usd=-1)
    with pytest.raises(ValueError, match="fee"):
        book.apply_fill("BTC", Side.BUY, quantity=0.1, price_usd=20_000, fee_usd=float("inf"))


# --- position management (#58) ---------------------------------------------


def test_opening_fill_stamps_opened_at_and_high_water() -> None:
    moment = datetime(2026, 9, 12, 10, 0, tzinfo=UTC)
    book = InMemoryPortfolioBook(starting_nav_usd=10_000)
    book.apply_fill(
        "BTC", Side.BUY, quantity=0.1, price_usd=20_000, now=moment, strategy_id="momentum_v1"
    )

    position = book.positions["BTC"]
    assert position.opened_at == moment
    assert position.high_water_price_usd == pytest.approx(20_000)
    assert position.entry_strategy_id == "momentum_v1"
    held = book.snapshot(now=moment).held_positions["BTC"]
    assert held.opened_at == moment
    assert held.average_cost_usd == pytest.approx(20_000)
    assert held.entry_strategy_id == "momentum_v1"


def test_mark_raises_high_water_and_sell_clears_exit_fields() -> None:
    moment = datetime(2026, 9, 12, 10, 0, tzinfo=UTC)
    book = InMemoryPortfolioBook(starting_nav_usd=10_000)
    book.apply_fill("ETH", Side.BUY, quantity=1, price_usd=1_000, now=moment)
    book.mark("ETH", 1_200)
    assert book.positions["ETH"].high_water_price_usd == pytest.approx(1_200)

    book.apply_fill("ETH", Side.SELL, quantity=1, price_usd=1_100)
    assert book.positions["ETH"].opened_at is None
    assert book.positions["ETH"].high_water_price_usd == pytest.approx(0.0)
    assert book.positions["ETH"].entry_strategy_id is None
    assert "ETH" not in book.snapshot().held_positions


def test_exit_fields_survive_a_checkpoint_round_trip() -> None:
    moment = datetime(2026, 9, 12, 10, 0, tzinfo=UTC)
    book = InMemoryPortfolioBook(starting_nav_usd=10_000)
    book.apply_fill(
        "BTC", Side.BUY, quantity=0.1, price_usd=20_000, now=moment, strategy_id="trend_v1"
    )
    book.mark("BTC", 21_000)

    restored = InMemoryPortfolioBook.from_state(
        PortfolioState.model_validate_json(book.state().model_dump_json())
    )
    position = restored.positions["BTC"]
    assert position.opened_at == moment
    assert position.high_water_price_usd == pytest.approx(21_000)
    assert position.entry_strategy_id == "trend_v1"


def test_legacy_position_checkpoint_loads_without_exit_fields() -> None:
    legacy = PortfolioState.model_validate(
        {
            "starting_nav_usd": 10_000,
            "cash_usd": 8_000,
            "peak_nav_usd": 10_000,
            "positions": {"BTC": {"quantity": 0.1, "average_cost_usd": 20_000}},
            "marks_usd": {"BTC": 20_000},
        }
    )
    book = InMemoryPortfolioBook.from_state(legacy)
    assert book.positions["BTC"].opened_at is None
    assert book.positions["BTC"].high_water_price_usd == pytest.approx(0.0)


def test_a_pre_epic7_checkpoint_anchors_on_load() -> None:
    """Checkpoints written before the anchor existed must not report a bogus day."""

    legacy = PortfolioState.model_validate(
        {
            "starting_nav_usd": 10_000,
            "cash_usd": 4_000,
            "peak_nav_usd": 12_000,
            "positions": {"BTC": {"quantity": 0.4, "average_cost_usd": 20_000}},
            "marks_usd": {"BTC": 20_000},
        }
    )
    assert legacy.day_start_nav_usd is None
    assert legacy.day_start_date is None

    book = InMemoryPortfolioBook.from_state(legacy)
    assert book.day_start_nav_usd == pytest.approx(12_000)
    assert book.snapshot().daily_pnl_usd == pytest.approx(0)
