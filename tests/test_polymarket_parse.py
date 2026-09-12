from datetime import date

from traderstack.polymarket.cities import CITY_CATALOG, match_city, resolve_allowlist
from traderstack.polymarket.models import TemperatureContract
from traderstack.polymarket.parse import parse_event_date, parse_temperature_market


def _allowlist():
    return resolve_allowlist("honolulu,san_diego,miami,phoenix,singapore,lisbon")


def test_resolve_allowlist_rejects_unknown_slug() -> None:
    try:
        resolve_allowlist("miami,chicago")
    except ValueError as exc:
        assert "chicago" in str(exc)
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
