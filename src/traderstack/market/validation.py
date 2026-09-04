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


# --- providers (Epic 2): provider divergence event -----------------------------


def pairwise_divergences(
    primary: ReferencePrice,
    references: list[ReferencePrice],
    max_divergence_bps: float,
) -> list[PriceDivergence]:
    """Every pair of independent-source prices (primary included) that disagrees
    by more than ``max_divergence_bps`` — not just each reference against the
    primary, but reference sources against each other too.
    """
    eligible = [primary, *(r for r in references if r.source != MarketSource.KRAKEN)]
    divergences: list[PriceDivergence] = []
    for i in range(len(eligible)):
        for j in range(i + 1, len(eligible)):
            a, b = eligible[i], eligible[j]
            if a.source == b.source:
                continue
            divergence = calculate_divergence(a, b)
            if divergence.divergence_bps > max_divergence_bps:
                divergences.append(divergence)
    return divergences
