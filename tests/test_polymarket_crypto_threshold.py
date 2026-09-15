"""Gamma crypto-threshold parsing and slug discovery (#142)."""

import json
from datetime import UTC, date, datetime

import pytest

from traderstack.polymarket.crypto_models import CryptoAsset
from traderstack.polymarket.crypto_threshold import (
    event_slug,
    event_slugs,
    iter_event_markets,
    parse_crypto_threshold_market,
)

DESCRIPTION = (
    'This market will resolve to "Yes" if the Binance 1 minute candle for BTC/USDT '
    "12:00 in the ET timezone (noon) on the date specified in the title has a final "
    '"Close" price higher than the price specified in the title.'
)


def payload(**over: object) -> dict[str, object]:
    row: dict[str, object] = {
        "id": "4412001",
        "conditionId": "0xabc",
        "question": "Will the price of Bitcoin be above $80,000 on September 14?",
        "description": DESCRIPTION,
        "clobTokenIds": json.dumps(["yes-token", "no-token"]),
        "endDate": "2026-09-14T16:00:00Z",
        "active": True,
        "closed": False,
        "acceptingOrders": True,
        "enableOrderBook": True,
    }
    row.update(over)
    return row


def test_real_question_shape_parses() -> None:
    market = parse_crypto_threshold_market(payload(), slug="bitcoin-above-on-september-14-2026")
    assert market is not None
    assert market.asset is CryptoAsset.BTC
    assert market.strike_usd == 80000.0
    assert market.resolves_at == datetime(2026, 9, 14, 16, 0, tzinfo=UTC)
    assert market.yes_token_id == "yes-token"
    assert market.no_token_id == "no-token"
    assert market.event_slug == "bitcoin-above-on-september-14-2026"
    assert market.resolution_text_ok is True
    assert market.condition_id == "0xabc"


def test_ethereum_maps_to_eth() -> None:
    market = parse_crypto_threshold_market(
        payload(question="Will the price of Ethereum be above $3,000 on October 2?")
    )
    assert market is not None
    assert market.asset is CryptoAsset.ETH
    assert market.strike_usd == 3000.0


@pytest.mark.parametrize(
    "question",
    [
        "Will Bitcoin dip to $60,000 in September?",
        "Will Bitcoin reach $120,000 in September?",
        "Bitcoin Up or Down on September 14?",
        "Will Bitcoin reach $80,000 September 7-13?",
        "Will the price of Solana be above $200 on September 14?",
        "Will the price of Bitcoin be below $80,000 on September 14?",
    ],
)
def test_non_threshold_questions_are_skipped(question: str) -> None:
    assert parse_crypto_threshold_market(payload(question=question)) is None


@pytest.mark.parametrize(
    "override",
    [
        {"closed": True},
        {"active": False},
        {"acceptingOrders": False},
        {"enableOrderBook": False},
        {"clobTokenIds": json.dumps(["only-one"])},
        {"clobTokenIds": ""},
        {"endDate": None},
        {"endDate": "not-a-date"},
        {"description": ""},
        {"description": "Resolves on the Coinbase BTC-USD daily close."},
    ],
)
def test_unusable_markets_are_skipped_not_guessed(override: dict[str, object]) -> None:
    assert parse_crypto_threshold_market(payload(**override)) is None


def test_event_slugs_cover_the_lookahead_window_in_order() -> None:
    slugs = event_slugs((CryptoAsset.BTC, CryptoAsset.ETH), date(2026, 9, 13), 2)
    assert slugs == (
        "bitcoin-above-on-september-13-2026",
        "ethereum-above-on-september-13-2026",
        "bitcoin-above-on-september-14-2026",
        "ethereum-above-on-september-14-2026",
        "bitcoin-above-on-september-15-2026",
        "ethereum-above-on-september-15-2026",
    )


def test_event_slug_has_no_zero_padding() -> None:
    assert event_slug(CryptoAsset.BTC, date(2026, 1, 5)) == "bitcoin-above-on-january-5-2026"


def test_iter_event_markets_flattens_and_carries_the_slug() -> None:
    events = (
        {"slug": "bitcoin-above-on-september-14-2026", "markets": [payload()]},
        {"slug": "empty-event", "markets": []},
        {"question": "flat market", "clobTokenIds": "[]"},
        "not-an-event",
    )
    rows = iter_event_markets(events)  # type: ignore[arg-type]
    assert [slug for slug, _ in rows] == ["bitcoin-above-on-september-14-2026", None]
    assert rows[0][1]["id"] == "4412001"
