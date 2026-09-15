"""Pre-registered era print policy (#135).

The harness required **two venue prints** before a name could be called
a passer. Kraken and Coinbase BTC-USD over the same two years are very
nearly the same tape: two venues over one window are one observation
wearing two hats, not two independent observations.

This module adds the missing alternative, frozen **before** any score is
computed: a second **era** — a non-overlapping calendar window on the
*same* venue — counts as an independent print. Venue prints remain
valid and are unchanged; a report must now name **which kind of print**
it used, so a reader can tell "two venues, one window" from "one venue,
two eras".

Pre-registered eras (half-open, UTC, ``[start, end)``)::

    2016-2019   2016-01-01 .. 2020-01-01
    2020-2022   2020-01-01 .. 2022-01-01
    2022-2024   2022-01-01 .. 2024-01-01
    2024-2026   2024-01-01 .. 2026-01-01

They are disjoint and contiguous, so a bar belongs to at most one era
and no two eras can overlap by construction. Adding, moving or
re-cutting an era after a score has been seen is retuning: change this
tuple in version control, with a note, before the next run.

Nothing here relaxes a gate. An era that is not covered is reported as
not covered; a run with no second print keeps ``PrintKind.SINGLE`` and
cannot claim independence. Missing bars are a skip, never a zero.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from traderstack.candles import Candle

# Minimum committed bars inside an era before it counts as covered. One
# walk-forward train+test block at the #96 hyperparameters (180 + 60).
DEFAULT_MIN_ERA_BARS = 240
REQUIRED_INDEPENDENT_ERAS = 2


class PrintKind(StrEnum):
    """Which kind of independent print a report is resting on."""

    VENUE = "venue"
    ERA = "era"
    BOTH = "venue+era"
    SINGLE = "single"


class Era(BaseModel):
    """One pre-registered calendar window, half-open ``[start, end)``."""

    era_id: str
    start: datetime
    end: datetime

    def contains(self, moment: datetime) -> bool:
        return self.start <= moment < self.end


def _utc(year: int) -> datetime:
    return datetime(year, 1, 1, tzinfo=UTC)


PRE_REGISTERED_ERAS: tuple[Era, ...] = (
    Era(era_id="2016-2019", start=_utc(2016), end=_utc(2020)),
    Era(era_id="2020-2022", start=_utc(2020), end=_utc(2022)),
    Era(era_id="2022-2024", start=_utc(2022), end=_utc(2024)),
    Era(era_id="2024-2026", start=_utc(2024), end=_utc(2026)),
)

ERA_PRINT_RULE = (
    "Pre-registered print policy (frozen before any score). A second "
    "independent print is either (a) a second VENUE over the same "
    "window, or (b) a second pre-registered ERA — a non-overlapping "
    "calendar window on the same venue. Eras: "
    + ", ".join(era.era_id for era in PRE_REGISTERED_ERAS)
    + f". An era counts as covered only with >= {DEFAULT_MIN_ERA_BARS} "
    "committed bars in it. Two venues over one window are NOT two "
    "independent observations (Kraken and Coinbase BTC-USD are near "
    "identical tapes); the report names which kind of print it used. "
    f"Independence needs {REQUIRED_INDEPENDENT_ERAS} covered eras or a "
    "second venue. No threshold is lowered by this policy and no "
    "PAPER_PROMOTE_* default changes."
)


class EraSpan(BaseModel):
    """Observed coverage of one pre-registered era by one series."""

    era_id: str
    start: str
    end: str
    bars: int = 0
    first: str | None = None
    last: str | None = None
    covered: bool = False


class EraCoverage(BaseModel):
    """Era coverage of a venue's series, plus the print-kind verdict."""

    venue: str
    min_era_bars: int = DEFAULT_MIN_ERA_BARS
    total_bars: int = 0
    first: str | None = None
    last: str | None = None
    spans: list[EraSpan] = Field(default_factory=list)
    covered_era_ids: list[str] = Field(default_factory=list)
    covered_eras: int = 0
    has_independent_eras: bool = False
    span_years: float | None = None
    rule: str = ERA_PRINT_RULE


def era_for(moment: datetime, eras: Sequence[Era] = PRE_REGISTERED_ERAS) -> Era | None:
    """The pre-registered era containing ``moment``, if any."""
    for era in eras:
        if era.contains(moment):
            return era
    return None


def era_coverage(
    candles: Iterable[Candle] | None,
    *,
    venue: str,
    min_era_bars: int = DEFAULT_MIN_ERA_BARS,
    eras: Sequence[Era] = PRE_REGISTERED_ERAS,
) -> EraCoverage:
    """Bucket a series into the pre-registered eras.

    A missing or empty series yields zero covered eras — a skip, not a
    pass: ``has_independent_eras`` stays ``False`` and no era is invented.
    """
    ordered = sorted(candles or (), key=lambda candle: candle.opened_at)
    buckets: dict[str, list[datetime]] = {era.era_id: [] for era in eras}
    for candle in ordered:
        matched = era_for(candle.opened_at, eras)
        if matched is not None:
            buckets[matched.era_id].append(candle.opened_at)
    spans: list[EraSpan] = []
    covered_ids: list[str] = []
    for era in eras:
        stamps = buckets[era.era_id]
        covered = len(stamps) >= min_era_bars
        if covered:
            covered_ids.append(era.era_id)
        spans.append(
            EraSpan(
                era_id=era.era_id,
                start=era.start.isoformat(),
                end=era.end.isoformat(),
                bars=len(stamps),
                first=stamps[0].isoformat() if stamps else None,
                last=stamps[-1].isoformat() if stamps else None,
                covered=covered,
            )
        )
    span_years: float | None = None
    if len(ordered) >= 2:
        delta = ordered[-1].opened_at - ordered[0].opened_at
        span_years = delta.total_seconds() / (365.25 * 24 * 3600)
    return EraCoverage(
        venue=venue,
        min_era_bars=min_era_bars,
        total_bars=len(ordered),
        first=ordered[0].opened_at.isoformat() if ordered else None,
        last=ordered[-1].opened_at.isoformat() if ordered else None,
        spans=spans,
        covered_era_ids=covered_ids,
        covered_eras=len(covered_ids),
        has_independent_eras=len(covered_ids) >= REQUIRED_INDEPENDENT_ERAS,
        span_years=span_years,
    )


def classify_print_kind(
    *,
    venue_print_available: bool,
    coverage: EraCoverage | None,
) -> PrintKind:
    """Name the independence this run actually has.

    ``SINGLE`` whenever neither a second venue nor two covered eras is
    present. It never upgrades on missing evidence.
    """
    era_ok = coverage is not None and coverage.has_independent_eras
    if venue_print_available and era_ok:
        return PrintKind.BOTH
    if venue_print_available:
        return PrintKind.VENUE
    if era_ok:
        return PrintKind.ERA
    return PrintKind.SINGLE


def describe_print_kind(kind: PrintKind, coverage: EraCoverage | None) -> str:
    """One operator-readable sentence for the report header."""
    if kind is PrintKind.SINGLE:
        return (
            "single print: no second venue and fewer than "
            f"{REQUIRED_INDEPENDENT_ERAS} covered pre-registered eras. "
            "This run cannot claim an independent confirmation."
        )
    covered = ", ".join(coverage.covered_era_ids) if coverage else ""
    if kind is PrintKind.VENUE:
        return (
            "venue print: a second venue confirmed the same calendar "
            "window. Two venues over one window are near-identical tapes; "
            "treat this as weaker than an era print."
        )
    if kind is PrintKind.ERA:
        return f"era print: non-overlapping pre-registered eras covered ({covered})."
    return (
        "venue+era print: a second venue AND non-overlapping "
        f"pre-registered eras ({covered}). Strongest available evidence."
    )


__all__ = [
    "DEFAULT_MIN_ERA_BARS",
    "ERA_PRINT_RULE",
    "PRE_REGISTERED_ERAS",
    "REQUIRED_INDEPENDENT_ERAS",
    "Era",
    "EraCoverage",
    "EraSpan",
    "PrintKind",
    "classify_print_kind",
    "describe_print_kind",
    "era_coverage",
    "era_for",
]
