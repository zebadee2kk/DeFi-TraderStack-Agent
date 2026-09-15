from datetime import date

from traderstack.polymarket.cities import CITY_CATALOG, match_city, resolve_allowlist
from traderstack.polymarket.models import TemperatureContract
from traderstack.polymarket.parse import parse_event_date, parse_temperature_market


def _allowlist():
    return resolve_allowlist("honolulu,san_diego,miami,phoenix,singapore,lisbon")


def test_resolve_allowlist_rejects_unknown_slug() -> None:
    try:
        resolve_allowlist("miami,anchorage")
    except ValueError as exc:
        assert "anchorage" in str(exc)
    else:
        raise AssertionError("expected unknown slug to fail closed")


def test_match_city_prefers_longer_name() -> None:
    city = match_city("Highest temperature in San Diego tomorrow", _allowlist())
    assert city is not None
    assert city.slug == "san_diego"


def test_parse_named_and_iso_dates() -> None:
    today = date(2026, 9, 12)
    assert parse_event_date("on September 12, 2026", today=today) == date(2026, 9, 12)
    assert parse_event_date("on 2026-09-12", today=today) == date(2026, 9, 12)
    assert parse_event_date("on Sep 12", today=today) == date(2026, 9, 12)


def test_parse_threshold_fahrenheit() -> None:
    parsed = parse_temperature_market(
        {
            "id": "m1",
            "question": "Will the highest temperature in Miami be 90°F or higher on September 12, 2026?",
            "clobTokenIds": '["yes","no"]',
            "active": True,
            "closed": False,
        },
        allowlist=_allowlist(),
        today=date(2026, 9, 11),
    )
    assert parsed is not None
    assert parsed.city_slug == "miami"
    assert parsed.contract is TemperatureContract.THRESHOLD_OR_HIGHER
    assert parsed.threshold_f == 90.0
    assert parsed.yes_token_id == "yes"


def test_parse_threshold_celsius_converts() -> None:
    parsed = parse_temperature_market(
        {
            "id": "m1",
            "question": "Will the highest temperature in Lisbon be 32°C or higher on September 12, 2026?",
            "clobTokenIds": ["yes", "no"],
            "active": True,
        },
        allowlist=_allowlist(),
        today=date(2026, 9, 11),
    )
    assert parsed is not None
    assert parsed.threshold_f == 89.6


def test_parse_bucket() -> None:
    parsed = parse_temperature_market(
        {
            "id": "m1",
            "question": "Highest temperature in Honolulu on September 12, 2026: 86-87°F",
            "clobTokenIds": ["yes", "no"],
        },
        allowlist=_allowlist(),
        today=date(2026, 9, 11),
    )
    assert parsed is not None
    assert parsed.contract is TemperatureContract.BUCKET
    assert parsed.bucket_low_f == 86.0
    assert parsed.bucket_high_f == 87.0


def test_parse_drops_city_outside_allowlist() -> None:
    parsed = parse_temperature_market(
        {
            "id": "m1",
            "question": "Will the highest temperature in New York City be 75°F or higher on September 12, 2026?",
            "clobTokenIds": ["yes", "no"],
        },
        allowlist=_allowlist(),
        today=date(2026, 9, 11),
    )
    assert parsed is None


def test_parse_drops_closed_or_tokenless_markets() -> None:
    allowlist = _allowlist()
    today = date(2026, 9, 11)
    assert (
        parse_temperature_market(
            {
                "question": "Will the highest temperature in Miami be 90°F or higher on September 12, 2026?",
                "clobTokenIds": ["yes", "no"],
                "closed": True,
            },
            allowlist=allowlist,
            today=today,
        )
        is None
    )
    assert (
        parse_temperature_market(
            {
                "question": "Will the highest temperature in Miami be 90°F or higher on September 12, 2026?",
                "clobTokenIds": "[]",
            },
            allowlist=allowlist,
            today=today,
        )
        is None
    )


def test_catalog_defaults_are_warm_climates() -> None:
    from traderstack.polymarket.cities import DEFAULT_CITY_SLUGS

    climates = {CITY_CATALOG[slug].climate for slug in DEFAULT_CITY_SLUGS}
    assert "tropical" in climates
    assert "mediterranean" in climates
    assert "humid_continental" not in climates
    assert "new_york" in CITY_CATALOG
    assert "new_york" not in DEFAULT_CITY_SLUGS


# --- polymarket weather PIT tape (#141) ---

import json as _json
from pathlib import Path as _Path

_TAPE_FIXTURES = _Path(__file__).parent / "fixtures" / "polymarket" / "tape"


def _live_events() -> list[dict]:
    return _json.loads((_TAPE_FIXTURES / "events.json").read_text(encoding="utf-8"))


def _catalog_allowlist():
    return tuple(CITY_CATALOG.values())


def test_or_below_bucket_parses_as_threshold_or_lower() -> None:
    payload = {
        "id": "m-low",
        "question": "Will the highest temperature in Miami be 77°F or below on September 17?",
        "clobTokenIds": '["yes-token", "no-token"]',
        "conditionId": "0xfeed",
    }
    market = parse_temperature_market(payload, allowlist=_allowlist(), today=date(2026, 9, 15))
    assert market is not None
    assert market.contract is TemperatureContract.THRESHOLD_OR_LOWER
    assert market.threshold_f == 77.0
    assert market.condition_id == "0xfeed"


def test_lowest_temperature_market_is_refused() -> None:
    payload = {
        "id": "m-lowest",
        "question": "Will the lowest temperature in Miami be 70°F or below on September 17?",
        "clobTokenIds": '["yes-token", "no-token"]',
    }
    assert (
        parse_temperature_market(payload, allowlist=_allowlist(), today=date(2026, 9, 15)) is None
    )


def test_market_not_accepting_orders_is_refused() -> None:
    payload = {
        "id": "m-closed",
        "question": "Will the highest temperature in Miami be 96°F or higher on September 17?",
        "clobTokenIds": '["yes-token", "no-token"]',
        "acceptingOrders": False,
    }
    assert (
        parse_temperature_market(payload, allowlist=_allowlist(), today=date(2026, 9, 15)) is None
    )


def test_live_miami_event_parses_all_eleven_buckets() -> None:
    event = next(e for e in _live_events() if e["title"].startswith("Highest temperature in Miami"))
    parsed = [
        parse_temperature_market(m, allowlist=_allowlist(), today=date(2026, 9, 15))
        for m in event["markets"]
    ]
    assert all(market is not None for market in parsed)
    contracts = [market.contract for market in parsed if market is not None]
    assert contracts.count(TemperatureContract.THRESHOLD_OR_LOWER) == 1
    assert contracts.count(TemperatureContract.THRESHOLD_OR_HIGHER) == 1
    assert contracts.count(TemperatureContract.BUCKET) == 9


def test_single_degree_celsius_buckets_stay_unparsed() -> None:
    event = next(
        e for e in _live_events() if e["title"].startswith("Highest temperature in Toronto")
    )
    middle = [m for m in event["markets"] if "or below" not in m["question"]]
    assert middle, "fixture should carry a single-degree °C bucket"
    for market in middle:
        assert (
            parse_temperature_market(
                market, allowlist=_catalog_allowlist(), today=date(2026, 9, 15)
            )
            is None
        )
