"""Shared point-in-time basis helpers (#134). Research only.

Basis here means **daily mark−index over index** on one venue, labelled
by the UTC day open of the bar whose close formed it. It is applied to
the hedged-carry PnL of that same day only (close D−1 → close D), never
to the harvest decision, so nothing looks ahead.

Constructions the memo forbids are refused in code, not by convention:
funding premium (``premium``, ``premiumIndexKlines``), funding-implied
basis (``fundingRate``), last-trade candles (``klines``, ``candles``,
``candleSnapshot``), and trade or book tapes. Every value that leaves
these helpers is finite and bounded (``|basis| <= MAX_ABS_BASIS``); a
day that fails the bound, or that is missing on either side, is a skip
and is counted, never a zero.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from traderstack.research.edge_series import EdgeSeriesFetch

# Daily |mark−index|/index beyond 10% is a corrupt row, not a basis print.
MAX_ABS_BASIS = 0.10

# Path / label segments that name a forbidden construction. Matched on
# whole segments so ``history-index-candles`` (allowed) does not trip on
# ``candles`` (last-trade, refused).
FORBIDDEN_BASIS_SEGMENTS: frozenset[str] = frozenset(
    {
        "klines",
        "premiumindexklines",
        "premiumindex",
        "premium_index",
        "fundingrate",
        "funding_rate",
        "fundinghistory",
        "funding-rate-history",
        "swap_historical_funding_rate",
        "aggtrades",
        "trades",
        "trade",
        "bucketed",
        "quote",
        "candles",
        "history-candles",
        "candlesnapshot",
        "bookticker",
        "last-trade",
        "last_trade",
    }
)
# Substrings that are forbidden wherever they appear (a premium index is
# the funding-formula input on every venue that publishes one).
FORBIDDEN_BASIS_MARKERS: tuple[str, ...] = ("premium",)

_SEGMENT_SPLIT = re.compile(r"[/?&=\s:;,()]+")


def refuse_forbidden_basis_source(label: str) -> None:
    """Raise ``ValueError`` when *label* names a forbidden basis input."""
    lowered = label.lower()
    for marker in FORBIDDEN_BASIS_MARKERS:
        if marker in lowered:
            raise ValueError(
                f"refused basis source {label!r}: {marker!r} is a funding-formula "
                "premium, not point-in-time mark−index"
            )
    for segment in _SEGMENT_SPLIT.split(lowered):
        if segment in FORBIDDEN_BASIS_SEGMENTS:
            raise ValueError(
                f"refused basis source {label!r}: {segment!r} is last-trade, "
                "funding-implied, or a trade/book tape — not mark−index"
            )


def utc_day(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    ts = ts.astimezone(UTC)
    return datetime(ts.year, ts.month, ts.day, tzinfo=UTC)


def bounded_basis(mark: float, index: float) -> float | None:
    """``(mark−index)/index`` or ``None`` when either input is unusable."""
    try:
        mark_f = float(mark)
        index_f = float(index)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(mark_f) and math.isfinite(index_f)):
        return None
    if mark_f <= 0 or index_f <= 0:
        return None
    value = (mark_f - index_f) / index_f
    if not math.isfinite(value) or abs(value) > MAX_ABS_BASIS:
        return None
    return value


def basis_from_closes(
    mark_by_day: dict[datetime, float],
    index_by_day: dict[datetime, float],
) -> tuple[list[tuple[datetime, float]], int]:
    """Daily basis on days present on **both** sides.

    Returns ``(points, bounded_skips)``. A day missing on either side is
    simply absent (never zero); a day that fails the finite / positive /
    ``MAX_ABS_BASIS`` guard is absent and counted in ``bounded_skips``.
    """
    points: list[tuple[datetime, float]] = []
    bounded_skips = 0
    for day in sorted(mark_by_day):
        index = index_by_day.get(day)
        if index is None:
            continue
        value = bounded_basis(mark_by_day[day], index)
        if value is None:
            bounded_skips += 1
            continue
        points.append((utc_day(day), value))
    return points, bounded_skips


def align_basis_days(
    first: tuple[tuple[datetime, float], ...] | list[tuple[datetime, float]],
    second: tuple[tuple[datetime, float], ...] | list[tuple[datetime, float]],
) -> tuple[
    tuple[tuple[datetime, float], ...],
    tuple[tuple[datetime, float], ...],
    int,
    int,
]:
    """Intersect two daily series on UTC day open.

    Returns ``(aligned_first, aligned_second, dropped_first, dropped_second)``.
    Days present on only one side are dropped from that side and counted;
    they are never filled on the other side.
    """
    first_map = {utc_day(ts): value for ts, value in first}
    second_map = {utc_day(ts): value for ts, value in second}
    shared = sorted(set(first_map) & set(second_map))
    aligned_first = tuple((day, first_map[day]) for day in shared)
    aligned_second = tuple((day, second_map[day]) for day in shared)
    return (
        aligned_first,
        aligned_second,
        len(first_map) - len(shared),
        len(second_map) - len(shared),
    )


def count_gaps(points: tuple[tuple[datetime, float], ...] | list[tuple[datetime, float]]) -> int:
    """Calendar days between first and last (inclusive) that have no point."""
    if not points:
        return 0
    days = {utc_day(ts) for ts, _value in points}
    first = min(days)
    last = max(days)
    expected = (last - first).days + 1
    return max(expected - len(days), 0)


def write_feature_series_json(
    path: Path, points: tuple[tuple[datetime, float], ...] | list[tuple[datetime, float]]
) -> None:
    """Write the ``[{opened_at, value}]`` shape ``search_cli._parse_feature_series`` reads."""
    rows = [
        {"opened_at": utc_day(ts).isoformat(), "value": float(value)}
        for ts, value in sorted(points, key=lambda pair: pair[0])
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, indent=2) + "\n")


def read_feature_series_json(path: Path) -> tuple[tuple[datetime, float], ...]:
    """Bounded reader for the same shape; malformed or out-of-range rows are skipped."""
    payload = json.loads(path.read_text())
    if not isinstance(payload, list):
        raise TypeError(f"{path}: expected a JSON array of {{opened_at, value}}")
    rows: list[tuple[datetime, float]] = []
    for item in payload:
        if not isinstance(item, dict) or "opened_at" not in item or "value" not in item:
            raise TypeError(f"{path}: each row needs opened_at and value")
        try:
            when = datetime.fromisoformat(str(item["opened_at"]))
            value = float(item["value"])
        except (TypeError, ValueError):
            continue
        if not math.isfinite(value) or abs(value) > MAX_ABS_BASIS:
            continue
        rows.append((utc_day(when), value))
    rows.sort(key=lambda pair: pair[0])
    return tuple(rows)


@dataclass(frozen=True)
class BasisProbeRow:
    """One line of the probe table (venue × symbol)."""

    venue: str
    symbol: str
    source: str
    status: str
    first: str
    last: str
    days: int
    gaps: int
    bounded_skips: int
    truncated: bool
    reason: str

    def as_dict(self) -> dict[str, str]:
        return {key: str(value) for key, value in asdict(self).items()}


_BOUNDED_SKIPS = re.compile(r"bounded[_ ]skips=(\d+)")


def probe_row_from_fetch(venue: str, symbol: str, fetch: EdgeSeriesFetch) -> BasisProbeRow:
    match = _BOUNDED_SKIPS.search(fetch.reason)
    bounded_skips = int(match.group(1)) if match else 0
    return BasisProbeRow(
        venue=venue,
        symbol=symbol,
        source=fetch.source,
        status=fetch.status,
        first=fetch.first.date().isoformat() if fetch.first else "",
        last=fetch.last.date().isoformat() if fetch.last else "",
        days=len(fetch.points),
        gaps=count_gaps(fetch.points),
        bounded_skips=bounded_skips,
        truncated="truncated" in fetch.reason.lower(),
        reason=fetch.reason,
    )


def yesterday_utc(now: datetime | None = None) -> datetime:
    return utc_day(now or datetime.now(UTC)) - timedelta(days=1)
