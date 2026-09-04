from traderstack.market.models import MarketSource, PriceDivergence, ReferencePrice


def calculate_divergence(primary: ReferencePrice, reference: ReferencePrice) -> PriceDivergence:
    if primary.asset != reference.asset:
        raise ValueError("cannot compare different assets")
    if primary.currency != reference.currency:
        raise ValueError("cannot compare different currencies")

    divergence_bps = abs(primary.price - reference.price) / primary.price * 10_000
    return PriceDivergence(
        primary_source=primary.source,
        reference_source=reference.source,
        asset=primary.asset,
        primary_price=primary.price,
        reference_price=reference.price,
        divergence_bps=divergence_bps,
    )


def is_reference_consistent(
    primary: ReferencePrice,
    references: list[ReferencePrice],
    max_divergence_bps: float,
) -> bool:
    eligible = [r for r in references if r.source != MarketSource.KRAKEN]
    if not eligible:
        return False
    return all(
        calculate_divergence(primary, ref).divergence_bps <= max_divergence_bps for ref in eligible
    )
