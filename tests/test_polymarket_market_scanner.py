from datetime import UTC, datetime, timedelta

from traderstack.polymarket.clob import BookMetrics
from traderstack.polymarket.market_scanner import (
    SCORING_CONTRACT_VERSION,
    MarketScanInput,
    rank_markets,
    scan_input_from_gamma,
    score_market,
)


NOW = datetime(2026, 10, 5, 12, tzinfo=UTC)


def _market(**overrides: object) -> MarketScanInput:
    values: dict[str, object] = {
        "market_id": "market-1",
        "condition_id": "condition-1",
        "token_id": "token-1",
        "category": "crypto",
        "observed_at": NOW,
        "close_at": NOW + timedelta(days=3),
        "best_bid": 0.49,
        "best_ask": 0.51,
        "bid_depth_usd": 2500.0,
        "ask_depth_usd": 2500.0,
        "liquidity_usd": 50_000.0,
        "wallet_coverage": 0.8,
        "external_context_coverage": 0.6,
        "evidence_fresh": True,
        "collector_healthy": True,
    }
    values.update(overrides)
    return MarketScanInput(**values)  # type: ignore[arg-type]


def test_score_market_is_deterministic_and_attributed() -> None:
    first = score_market(_market())
    second = score_market(_market())

    assert first == second
    assert first.eligible
    assert first.quality_score is not None
    assert first.scoring_contract_version == SCORING_CONTRACT_VERSION
    assert set(first.components) == {
        "liquidity",
        "spread",
        "depth",
        "time_to_resolution",
        "wallet_coverage",
        "external_context_coverage",
    }


def test_missing_or_stale_evidence_never_becomes_zero_score() -> None:
    result = score_market(
        _market(
            wallet_coverage=None,
            evidence_fresh=False,
        )
    )

    assert not result.eligible
    assert result.quality_score is None
    assert result.components == {}
    assert "missing_wallet_coverage" in result.reasons
    assert "stale_evidence" in result.reasons


def test_one_sided_crossed_and_expired_books_fail_closed() -> None:
    one_sided = score_market(_market(best_ask=None))
    crossed = score_market(_market(best_bid=0.6, best_ask=0.5))
    expired = score_market(_market(close_at=NOW))

    assert "one_sided_book" in one_sided.reasons
    assert "crossed_book" in crossed.reasons
    assert "closed_or_expired" in expired.reasons
    assert not one_sided.eligible
    assert not crossed.eligible
    assert not expired.eligible


def test_weaker_execution_quality_ranks_lower() -> None:
    strong = _market(market_id="strong", token_id="strong-token")
    weak = _market(
        market_id="weak",
        token_id="weak-token",
        best_bid=0.45,
        best_ask=0.55,
        bid_depth_usd=250.0,
        ask_depth_usd=300.0,
        liquidity_usd=5_000.0,
    )

    ranked = rank_markets([weak, strong])

    assert ranked[0].market_id == "strong"
    assert ranked[1].market_id == "weak"
    assert ranked[0].quality_score is not None
    assert ranked[1].quality_score is not None
    assert ranked[0].quality_score > ranked[1].quality_score


def test_ineligible_markets_sort_after_eligible_markets() -> None:
    eligible = _market(market_id="eligible")
    ineligible = _market(market_id="stale", evidence_fresh=False)

    ranked = rank_markets([ineligible, eligible])

    assert ranked[0].market_id == "eligible"
    assert ranked[1].market_id == "stale"
    assert ranked[1].quality_score is None


def test_scan_input_from_gamma_requires_real_identifiers_and_liquidity() -> None:
    book = BookMetrics(
        best_bid=0.49,
        best_ask=0.51,
        mid=0.50,
        bid_depth_usd=900.0,
        ask_depth_usd=850.0,
    )
    payload = {
        "id": "market-9",
        "conditionId": "condition-9",
        "clobTokenIds": '["yes-9", "no-9"]',
        "endDate": "2026-10-08T12:00:00+00:00",
        "active": True,
        "closed": False,
        "acceptingOrders": True,
        "enableOrderBook": True,
        "liquidityNum": 12000,
    }

    item = scan_input_from_gamma(
        payload,
        observed_at=NOW,
        category="politics",
        book=book,
        wallet_coverage=0.7,
        external_context_coverage=0.9,
        evidence_fresh=True,
        collector_healthy=True,
    )

    assert item is not None
    assert item.market_id == "market-9"
    assert item.condition_id == "condition-9"
    assert item.token_id == "yes-9"
    assert item.liquidity_usd == 12000.0
    assert item.bid_depth_usd == 900.0
    assert item.external_context_coverage == 0.9


def test_scan_input_from_gamma_skips_closed_or_unidentified_markets() -> None:
    book = BookMetrics(
        best_bid=0.49,
        best_ask=0.51,
        mid=0.50,
        bid_depth_usd=900.0,
        ask_depth_usd=850.0,
    )
    base = {
        "id": "market-9",
        "conditionId": "condition-9",
        "clobTokenIds": '["yes-9", "no-9"]',
        "endDate": "2026-10-08T12:00:00+00:00",
        "active": True,
        "closed": False,
        "acceptingOrders": True,
        "enableOrderBook": True,
        "liquidityNum": 12000,
    }

    assert (
        scan_input_from_gamma(
            {**base, "closed": True},
            observed_at=NOW,
            category="politics",
            book=book,
            wallet_coverage=0.7,
            external_context_coverage=0.9,
            evidence_fresh=True,
            collector_healthy=True,
        )
        is None
    )
    assert (
        scan_input_from_gamma(
            {**base, "conditionId": ""},
            observed_at=NOW,
            category="politics",
            book=book,
            wallet_coverage=0.7,
            external_context_coverage=0.9,
            evidence_fresh=True,
            collector_healthy=True,
        )
        is None
    )
