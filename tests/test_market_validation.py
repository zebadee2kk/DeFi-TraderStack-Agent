import pytest
from pydantic import ValidationError

from traderstack.market.adapters import parse_kraken_ticker
from traderstack.market.models import MarketSource, MarketTick, ReferencePrice
from traderstack.market.validation import calculate_divergence, is_reference_consistent


def test_calculate_divergence() -> None:
    primary = ReferencePrice(source=MarketSource.KRAKEN, asset="BTC", price=100.0)
    reference = ReferencePrice(source=MarketSource.COINGECKO, asset="BTC", price=101.0)

    result = calculate_divergence(primary, reference)

    assert result.divergence_bps == 100.0


def test_reference_consistency_requires_reference_source() -> None:
    primary = ReferencePrice(source=MarketSource.KRAKEN, asset="BTC", price=100.0)

    assert is_reference_consistent(primary, [], max_divergence_bps=50) is False


def test_reference_consistency_rejects_large_divergence() -> None:
    primary = ReferencePrice(source=MarketSource.KRAKEN, asset="ETH", price=100.0)
    references = [
        ReferencePrice(source=MarketSource.COINGECKO, asset="ETH", price=100.2),
        ReferencePrice(source=MarketSource.COINMARKETCAP, asset="ETH", price=102.0),
    ]

    assert is_reference_consistent(primary, references, max_divergence_bps=50) is False


def test_market_tick_rejects_non_finite_and_crossed_quotes() -> None:
    base = {"source": MarketSource.KRAKEN, "symbol": "BTC/USD", "bid": 99.0, "ask": 101.0, "last": 100.0}
    with pytest.raises(ValidationError):
        MarketTick(**{**base, "last": float("inf")})
    with pytest.raises(ValidationError):
        MarketTick(**{**base, "bid": float("nan")})
    with pytest.raises(ValidationError):
        MarketTick(**{**base, "last": 1e13})
    with pytest.raises(ValidationError, match="crossed tick"):
        MarketTick(**{**base, "bid": 101.0, "ask": 99.0})


def test_reference_price_rejects_non_finite() -> None:
    with pytest.raises(ValidationError):
        ReferencePrice(source=MarketSource.COINGECKO, asset="BTC", price=float("inf"))


def test_parse_kraken_ticker_drops_corrupt_quotes() -> None:
    def message(**quote):
        row = {"symbol": "BTC/USD", "bid": 99.0, "ask": 101.0, "last": 100.0, **quote}
        return {"channel": "ticker", "data": [row]}

    assert parse_kraken_ticker(message(last=float("inf"))) is None
    assert parse_kraken_ticker(message(bid=float("nan"))) is None
    assert parse_kraken_ticker(message(bid=101.0, ask=99.0)) is None
    assert parse_kraken_ticker(message(last=-5.0)) is None
    assert parse_kraken_ticker(message()) is not None
