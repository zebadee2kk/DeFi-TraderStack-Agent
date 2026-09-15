"""Reduce untrusted Gamma payloads to typed BTC/ETH threshold markets (#142).

Only the exact daily "above $K on <Month D>?" shape is accepted. Weekly range
markets, "dip to", "reach", and "Up or Down" questions are not threshold-at-time
contracts and are dropped rather than guessed at.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any

from traderstack.polymarket.crypto_models import CryptoAsset, ParsedCryptoThresholdMarket
from traderstack.polymarket.parse import _json_list, _parse_datetime

_QUESTION = re.compile(
    r"^Will the price of (?P<asset>Bitcoin|Ethereum) be above "
    r"\$(?P<strike>[\d,]+(?:\.\d+)?) on (?P<when>[A-Za-z]+ \d{1,2})\?$",
    re.IGNORECASE,
)

_ASSETS = {"bitcoin": CryptoAsset.BTC, "ethereum": CryptoAsset.ETH}
_SLUG_PREFIX = {CryptoAsset.BTC: "bitcoin", CryptoAsset.ETH: "ethereum"}

_MONTH_NAMES = (
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
)

# The resolution text this tape is about: the Binance 1-minute candle. A market
# whose description does not say so is skipped, not assumed to settle the same
# way (a different settlement source is a different contract).
_RESOLUTION_NEEDLES = ("binance", "1 minute candle")


def _resolution_text_ok(payload: dict[str, Any]) -> bool:
    description = payload.get("description")
    if not isinstance(description, str) or not description.strip():
        return False
    lowered = " ".join(description.split()).lower()
    return all(needle in lowered for needle in _RESOLUTION_NEEDLES)


def _title_date_matches(when: str, resolves_at: datetime) -> bool:
    """Does the "<Month D>" in the question agree with ``endDate``?

    An unreadable month name is treated as a mismatch: the title is untrusted
    text, and a market whose two statements of its own settlement date disagree
    is not one this tape can honestly record.
    """

    month_name, _, day_text = when.strip().partition(" ")
    try:
        month = _MONTH_NAMES.index(month_name.lower()) + 1
        day = int(day_text)
    except ValueError:
        return False
    return (month, day) == (resolves_at.month, resolves_at.day)


def parse_crypto_threshold_market(
    payload: dict[str, Any],
    *,
    slug: str | None = None,
) -> ParsedCryptoThresholdMarket | None:
    """Return a typed market, or None when the payload cannot be researched."""

    if not isinstance(payload, dict):
        return None
    if payload.get("closed") is True or payload.get("active") is False:
        return None
    if payload.get("acceptingOrders") is False or payload.get("enableOrderBook") is False:
        return None

    raw_question = payload.get("question") or payload.get("title") or ""
    if not isinstance(raw_question, str) or not raw_question.strip():
        return None
    question = " ".join(raw_question.split())
    match = _QUESTION.match(question)
    if match is None:
        return None

    asset = _ASSETS.get(match.group("asset").lower())
    if asset is None:
        return None
    try:
        strike = float(match.group("strike").replace(",", ""))
    except ValueError:
        return None
    if strike <= 0:
        return None

    resolves_at = _parse_datetime(payload.get("endDate") or payload.get("end_date_iso"))
    if resolves_at is None:
        return None

    if not _title_date_matches(match.group("when"), resolves_at):
        # The title says one date and endDate says another: two different
        # claims about when this settles. Skip rather than pick one.
        return None

    token_ids = _json_list(payload.get("clobTokenIds") or payload.get("clob_token_ids"))
    if len(token_ids) < 2 or not token_ids[0].strip() or not token_ids[1].strip():
        return None

    if not _resolution_text_ok(payload):
        # No description, or a description that does not name the Binance
        # 1-minute candle: skip rather than assume how it settles.
        return None

    condition_id = payload.get("conditionId") or payload.get("condition_id")
    market_id = str(payload.get("id") or condition_id or token_ids[0])

    return ParsedCryptoThresholdMarket(
        market_id=market_id,
        condition_id=str(condition_id) if isinstance(condition_id, str) else None,
        question=question,
        asset=asset,
        strike_usd=strike,
        resolves_at=resolves_at,
        yes_token_id=token_ids[0],
        no_token_id=token_ids[1],
        event_slug=slug,
        resolution_text_ok=True,
    )


def event_slug(asset: CryptoAsset, day: date) -> str:
    """``bitcoin-above-on-september-14-2026`` (lowercase month, no zero pad)."""

    return f"{_SLUG_PREFIX[asset]}-above-on-{_MONTH_NAMES[day.month - 1]}-{day.day}-{day.year}"


def event_slugs(
    assets: tuple[CryptoAsset, ...],
    start_date: date,
    lookahead_days: int,
) -> tuple[str, ...]:
    """Slugs for ``start_date`` plus ``lookahead_days`` further days, per asset."""

    slugs: list[str] = []
    for offset in range(max(0, lookahead_days) + 1):
        day = start_date + timedelta(days=offset)
        for asset in assets:
            slugs.append(event_slug(asset, day))
    return tuple(slugs)


def iter_event_markets(
    events: tuple[dict[str, Any], ...],
) -> list[tuple[str | None, dict[str, Any]]]:
    """Flatten Gamma events into ``(event_slug, market payload)`` pairs."""

    rows: list[tuple[str | None, dict[str, Any]]] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        slug = event.get("slug")
        slug_text = slug if isinstance(slug, str) else None
        nested = event.get("markets")
        if isinstance(nested, list) and nested:
            rows.extend((slug_text, row) for row in nested if isinstance(row, dict))
        elif "clobTokenIds" in event or "question" in event:
            rows.append((slug_text, event))
    return rows
