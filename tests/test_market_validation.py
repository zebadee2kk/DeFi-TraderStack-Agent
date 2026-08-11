from traderstack.market.models import MarketSource, ReferencePrice
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
