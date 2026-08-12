import pytest

from traderstack.models import Side
from traderstack.portfolio import InMemoryPortfolioBook


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

    # Oversized sell fills are clamped to the remaining position (the venue
    # fill can slightly exceed the mark-sized intent); only selling with no
    # position at all is a hard error.
    book.apply_fill("ETH", Side.SELL, quantity=2, price_usd=1_200)
    assert book.positions["ETH"].quantity == 0
    assert book.realized_pnl_usd == pytest.approx(400)

    with pytest.raises(ValueError, match="cannot sell more"):
        book.apply_fill("ETH", Side.SELL, quantity=1, price_usd=1_200)


def test_daily_pnl_resets_on_new_utc_day() -> None:
    book = InMemoryPortfolioBook(starting_nav_usd=10_000)
    book.apply_fill("BTC", Side.BUY, quantity=0.1, price_usd=20_000)
    book.mark("BTC", 22_000)
    assert book.snapshot().daily_pnl_usd == pytest.approx(200)

    book.daily_anchor_date = "2000-01-01"
    snapshot = book.snapshot()
    assert snapshot.daily_pnl_usd == pytest.approx(0)
    assert book.daily_anchor_nav_usd == pytest.approx(10_200)

    book.mark("BTC", 23_000)
    assert book.snapshot().daily_pnl_usd == pytest.approx(100)


def test_daily_anchor_survives_state_round_trip() -> None:
    book = InMemoryPortfolioBook(starting_nav_usd=10_000)
    book.apply_fill("BTC", Side.BUY, quantity=0.1, price_usd=20_000)
    book.mark("BTC", 21_000)
    book.snapshot()

    restored = InMemoryPortfolioBook.from_state(book.state())
    assert restored.daily_anchor_date == book.daily_anchor_date
    assert restored.daily_anchor_nav_usd == pytest.approx(book.daily_anchor_nav_usd)
    assert restored.snapshot().daily_pnl_usd == pytest.approx(book.snapshot().daily_pnl_usd)
