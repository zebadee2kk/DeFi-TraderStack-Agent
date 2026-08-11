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

    with pytest.raises(ValueError, match="cannot sell more"):
        book.apply_fill("ETH", Side.SELL, quantity=2, price_usd=1_200)
