"""Reduce untrusted Gamma market payloads to typed temperature contracts."""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime
from typing import Any

from traderstack.polymarket.cities import match_city
from traderstack.polymarket.models import City, ParsedTemperatureMarket, TemperatureContract

_MONTHS = {
    "january": 1,
    "jan": 1,
    "february": 2,
    "feb": 2,
    "march": 3,
    "mar": 3,
    "april": 4,
    "apr": 4,
    "may": 5,
    "june": 6,
    "jun": 6,
    "july": 7,
    "jul": 7,
    "august": 8,
    "aug": 8,
    "september": 9,
    "sept": 9,
    "sep": 9,
    "october": 10,
    "oct": 10,
    "november": 11,
    "nov": 11,
    "december": 12,
    "dec": 12,
}

_ISO_DATE = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")
_NAMED_DATE = re.compile(
    r"\b(" + "|".join(_MONTHS) + r")\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s*(20\d{2}))?\b",
    re.IGNORECASE,
)
_THRESHOLD = re.compile(
    r"(?:at\s+least\s+|be\s+)?"
    r"(?P<value>\d+(?:\.\d+)?)\s*°?\s*(?P<unit>f|c|fahrenheit|celsius)"
    r"\s*(?:or\s+(?:higher|above|more|greater)|and\s+(?:higher|above)|or\s+warmer)",
    re.IGNORECASE,
)
# --- polymarket weather PIT tape (#141) ---
# "Lowest temperature in <city>" is a different contract family (daily low).
# Guarded out rather than mis-parsed as a high-temperature bucket.
_LOWEST = re.compile(r"\blowest\s+temperature\b", re.IGNORECASE)
# Polymarket's bottom bucket: "77°F or below" / "or lower" / "or less".
_THRESHOLD_LOWER = re.compile(
    r"(?:at\s+most\s+|be\s+)?"
    r"(?P<value>\d+(?:\.\d+)?)\s*°?\s*(?P<unit>f|c|fahrenheit|celsius)"
    r"\s*(?:or\s+(?:below|lower|less|colder)|and\s+below)",
    re.IGNORECASE,
)
_BUCKET = re.compile(
    r"(?P<low>\d+(?:\.\d+)?)\s*(?:-|–|to)\s*(?P<high>\d+(?:\.\d+)?)\s*°?\s*"
    r"(?P<unit>f|c|fahrenheit|celsius)\b",
    re.IGNORECASE,
)


def _as_fahrenheit(value: float, unit: str) -> float:
    if unit.lower() in {"c", "celsius"}:
        return value * 9.0 / 5.0 + 32.0
    return value


def _json_list(raw: object) -> list[str]:
    if isinstance(raw, list):
        return [str(item) for item in raw]
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return []
        if isinstance(parsed, list):
            return [str(item) for item in parsed]
    return []


def _parse_datetime(raw: object) -> datetime | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip()
    try:
        value = datetime.fromisoformat(text)
    except ValueError:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value


def parse_event_date(text: str, *, today: date) -> date | None:
    iso = _ISO_DATE.search(text)
    if iso:
        return date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
    named = _NAMED_DATE.search(text)
    if named:
        month = _MONTHS[named.group(1).lower()]
        day = int(named.group(2))
        year = int(named.group(3)) if named.group(3) else today.year
        try:
            return date(year, month, day)
        except ValueError:
            return None
    return None


def parse_temperature_market(
    payload: dict[str, Any],
    *,
    allowlist: tuple[City, ...],
    today: date,
) -> ParsedTemperatureMarket | None:
    """Return a typed market or None when the payload cannot be researched.

    Untrusted Gamma fields are reduced to bounded scalars/ids. Markets that
    name a city outside the allowlist, or that we cannot parse, are dropped
    rather than guessed.
    """

    if not isinstance(payload, dict):
        return None
    if payload.get("closed") is True or payload.get("active") is False:
        return None
    # --- polymarket weather PIT tape (#141) ---
    # A market that no longer accepts orders has no decision-time mid.
    if payload.get("acceptingOrders") is False:
        return None

    question = payload.get("question") or payload.get("title") or ""
    if not isinstance(question, str) or not question.strip():
        return None
    question = " ".join(question.split())
    # --- polymarket weather PIT tape (#141) ---
    if _LOWEST.search(question):
        return None

    city = match_city(question, allowlist)
    if city is None:
        return None

    event_date = parse_event_date(question, today=today)
    if event_date is None:
        return None

    token_ids = _json_list(payload.get("clobTokenIds") or payload.get("clob_token_ids"))
    if len(token_ids) < 2 or not token_ids[0] or not token_ids[1]:
        return None

    market_id = str(payload.get("id") or payload.get("conditionId") or token_ids[0])
    end_at = _parse_datetime(payload.get("endDate") or payload.get("end_date_iso"))
    # --- polymarket weather PIT tape (#141) ---
    raw_condition = payload.get("conditionId") or payload.get("condition_id") or ""
    condition_id = str(raw_condition) if isinstance(raw_condition, str) else ""

    bucket = _BUCKET.search(question)
    threshold = _THRESHOLD.search(question)
    threshold_lower = _THRESHOLD_LOWER.search(question)
    if bucket:
        unit = bucket.group("unit")
        low = _as_fahrenheit(float(bucket.group("low")), unit)
        high = _as_fahrenheit(float(bucket.group("high")), unit)
        if high <= low:
            return None
        return ParsedTemperatureMarket(
            market_id=market_id,
            question=question,
            city_slug=city.slug,
            city_name=city.name,
            event_date=event_date,
            contract=TemperatureContract.BUCKET,
            bucket_low_f=low,
            bucket_high_f=high,
            yes_token_id=token_ids[0],
            no_token_id=token_ids[1],
            end_at=end_at,
            condition_id=condition_id,
        )
    # --- polymarket weather PIT tape (#141) ---
    if threshold_lower:
        unit = threshold_lower.group("unit")
        value = _as_fahrenheit(float(threshold_lower.group("value")), unit)
        return ParsedTemperatureMarket(
            market_id=market_id,
            question=question,
            city_slug=city.slug,
            city_name=city.name,
            event_date=event_date,
            contract=TemperatureContract.THRESHOLD_OR_LOWER,
            threshold_f=value,
            yes_token_id=token_ids[0],
            no_token_id=token_ids[1],
            end_at=end_at,
            condition_id=condition_id,
        )
    if threshold:
        unit = threshold.group("unit")
        value = _as_fahrenheit(float(threshold.group("value")), unit)
        return ParsedTemperatureMarket(
            market_id=market_id,
            question=question,
            city_slug=city.slug,
            city_name=city.name,
            event_date=event_date,
            contract=TemperatureContract.THRESHOLD_OR_HIGHER,
            threshold_f=value,
            yes_token_id=token_ids[0],
            no_token_id=token_ids[1],
            end_at=end_at,
            condition_id=condition_id,
        )
    return None
