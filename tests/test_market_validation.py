from traderstack.market.models import MarketSource, ReferencePrice
from traderstack.market.validation import (
    calculate_divergence,
    is_reference_consistent,
    pairwise_divergences,
)


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


# --- providers (Epic 2): provider divergence event -----------------------------


def test_pairwise_divergences_includes_reference_vs_reference() -> None:
    primary = ReferencePrice(source=MarketSource.KRAKEN, asset="BTC", price=100.0)
    references = [
        ReferencePrice(source=MarketSource.COINGECKO, asset="BTC", price=100.1),
        ReferencePrice(source=MarketSource.COINMARKETCAP, asset="BTC", price=102.0),
    ]

    divergences = pairwise_divergences(primary, references, max_divergence_bps=50)

    # CoinGecko agrees with both Kraken and CoinMarketCap-adjacent bounds, but
    # CoinMarketCap disagrees with both Kraken *and* CoinGecko - two events,
    # not one, even though only CoinMarketCap is the outlier.
    pairs = {(d.primary_source, d.reference_source) for d in divergences}
    assert (MarketSource.KRAKEN, MarketSource.COINMARKETCAP) in pairs
    assert (MarketSource.COINGECKO, MarketSource.COINMARKETCAP) in pairs
    assert (MarketSource.KRAKEN, MarketSource.COINGECKO) not in pairs
    assert len(divergences) == 2


def test_pairwise_divergences_empty_when_all_agree() -> None:
    primary = ReferencePrice(source=MarketSource.KRAKEN, asset="BTC", price=100.0)
    references = [
        ReferencePrice(source=MarketSource.COINGECKO, asset="BTC", price=100.05),
        ReferencePrice(source=MarketSource.COINMARKETCAP, asset="BTC", price=99.98),
    ]

    assert pairwise_divergences(primary, references, max_divergence_bps=50) == []
