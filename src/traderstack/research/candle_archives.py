"""Shared vocabulary for the multi-year candle archives (#133).

Every strategy catalog since #104 is scored on Kraken's 720-bar public REST
cap (about two years daily) plus one older Binance.US 720. That is one regime
and too little history to confirm anything the #96+A+B+C gates ask for. The
three fetch/load modules that sit on top of this one
(``candles_coinbase``, ``candles_binance_vision``, ``candles_kraken_archive``)
reach further back, and they all report through the types defined here.

Conventions, deliberately the same as the funding / edge adapters
(``research/edge_series.py``, ``research/funding_carry.py``):

* ``status`` is ``"ok"`` or ``"skipped"`` — never an invented series. An
  unreachable host, a rate-limited response, a missing month, a checksum
  mismatch or an unparsable file is a **skip with a recorded reason**.
* Missing bars are **gaps**, never zeros. Nothing here interpolates,
  forward-fills or synthesises a bar; a hole in a venue's tape stays a hole
  and is counted in :class:`CandleGap` for the report header.
* Timestamps are strictly UTC and strictly aligned to the interval grid
  (``epoch_seconds % interval_seconds == 0``). A misaligned row is a parse
  failure, not something to round.
* Everything a venue returns is untrusted input (``docs/SECURITY-THREAT-MODEL.md``):
  rows are reduced to bounded, typed :class:`~traderstack.candles.Candle`
  values — which validate ``high``/``low`` containment and positivity — before
  any caller sees them.

Cross-venue sanity lives here too: :func:`cross_venue_divergence` compares two
aligned daily series and flags every bar whose closes disagree by more than the
caller-supplied ``max_bps``. The threshold comes from the existing
version-controlled ``Settings.max_reference_divergence_bps``; this module never
defines a risk limit of its own and never reads one from fetched content.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from typing import Literal

from traderstack.candles import Candle, interval_to_seconds

ArchiveStatus = Literal["ok", "skipped"]

# Report-header key order, so a report diff between two runs is readable.
REPORT_FIELDS: tuple[str, ...] = (
    "name",
    "venue",
    "symbol",
    "interval",
    "status",
    "reason",
    "bars",
    "first",
    "last",
    "gaps",
    "missing_bars",
    "fetched_at",
)


class ArchiveParseError(ValueError):
    """A venue payload could not be reduced to bounded, typed candles."""


@dataclass(frozen=True)
class CandleGap:
    """A hole in a venue's tape: bars the venue did not publish.

    ``missing_bars`` is how many interval steps sit strictly between
    ``after`` and ``before``. Never filled in — recorded so the report can
    show the caller exactly what history is absent.
    """

    after: datetime
    before: datetime
    missing_bars: int

    def as_note(self) -> dict[str, str]:
        return {
            "after": self.after.isoformat(),
            "before": self.before.isoformat(),
            "missing_bars": str(self.missing_bars),
        }


@dataclass(frozen=True)
class CandleSeriesFetch:
    """One venue/symbol/interval fetch or load, plus its report header."""

    name: str
    venue: str
    symbol: str
    interval: str
    status: ArchiveStatus
    reason: str
    candles: tuple[Candle, ...] = ()
    gaps: tuple[CandleGap, ...] = ()
    fetched_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    notes: tuple[str, ...] = ()

    @property
    def bars(self) -> int:
        return len(self.candles)

    @property
    def first(self) -> datetime | None:
        return self.candles[0].opened_at if self.candles else None

    @property
    def last(self) -> datetime | None:
        return self.candles[-1].opened_at if self.candles else None

    @property
    def missing_bars(self) -> int:
        return sum(gap.missing_bars for gap in self.gaps)

    def as_note(self) -> dict[str, object]:
        """The report header: venue, first/last bar, bar count, gaps, fetch time."""
        first = self.first
        last = self.last
        payload: dict[str, object] = {
            "name": self.name,
            "venue": self.venue,
            "symbol": self.symbol,
            "interval": self.interval,
            "status": self.status,
            "reason": self.reason,
            "bars": self.bars,
            "first": first.isoformat() if first is not None else "",
            "last": last.isoformat() if last is not None else "",
            "gaps": [gap.as_note() for gap in self.gaps],
            "missing_bars": self.missing_bars,
            "fetched_at": self.fetched_at.isoformat(),
        }
        if self.notes:
            payload["notes"] = list(self.notes)
        return payload


def skipped_series(
    *,
    name: str,
    venue: str,
    symbol: str,
    interval: str,
    reason: str,
    notes: tuple[str, ...] = (),
    fetched_at: datetime | None = None,
) -> CandleSeriesFetch:
    """A skip carries no candles at all — never a partial, never a zero-fill."""
    return CandleSeriesFetch(
        name=name,
        venue=venue,
        symbol=symbol,
        interval=interval,
        status="skipped",
        reason=reason,
        notes=notes,
        fetched_at=fetched_at or datetime.now(UTC),
    )


def interval_step(interval: str) -> timedelta:
    return timedelta(seconds=interval_to_seconds(interval))


def is_aligned(moment: datetime, interval: str) -> bool:
    """True when ``moment`` sits exactly on the UTC interval grid."""
    if moment.tzinfo is None:
        return False
    step = int(interval_to_seconds(interval))
    return int(moment.astimezone(UTC).timestamp()) % step == 0


def require_aligned(moment: datetime, interval: str) -> datetime:
    if not is_aligned(moment, interval):
        raise ArchiveParseError(
            f"bar timestamp {moment!r} is not aligned to the UTC {interval} grid"
        )
    return moment.astimezone(UTC)


def detect_gaps(candles: tuple[Candle, ...], interval: str) -> tuple[CandleGap, ...]:
    """Every hole in a sorted, deduplicated series. Nothing is filled."""
    if len(candles) < 2:
        return ()
    step = interval_step(interval)
    gaps: list[CandleGap] = []
    for previous, current in pairwise(candles):
        delta = current.opened_at - previous.opened_at
        if delta <= step:
            continue
        missing = int(delta / step) - 1
        if missing > 0:
            gaps.append(
                CandleGap(after=previous.opened_at, before=current.opened_at, missing_bars=missing)
            )
    return tuple(gaps)


def dedupe_and_sort(candles: list[Candle]) -> tuple[Candle, ...]:
    """Sort ascending by open time; a later duplicate for the same bar wins."""
    by_time: dict[datetime, Candle] = {}
    for candle in candles:
        by_time[candle.opened_at.astimezone(UTC)] = candle
    return tuple(by_time[key] for key in sorted(by_time))


def finish_series(
    *,
    name: str,
    venue: str,
    symbol: str,
    interval: str,
    candles: list[Candle],
    ok_reason: str,
    empty_reason: str = "empty series",
    notes: tuple[str, ...] = (),
    fetched_at: datetime | None = None,
) -> CandleSeriesFetch:
    """Reduce collected candles to a reported series (empty ⇒ skipped)."""
    ordered = dedupe_and_sort(candles)
    when = fetched_at or datetime.now(UTC)
    if not ordered:
        return skipped_series(
            name=name,
            venue=venue,
            symbol=symbol,
            interval=interval,
            reason=empty_reason,
            notes=notes,
            fetched_at=when,
        )
    return CandleSeriesFetch(
        name=name,
        venue=venue,
        symbol=symbol,
        interval=interval,
        status="ok",
        reason=ok_reason,
        candles=ordered,
        gaps=detect_gaps(ordered, interval),
        fetched_at=when,
        notes=notes,
    )


def drop_uncommitted(
    candles: tuple[Candle, ...], *, interval: str, now: datetime | None = None
) -> tuple[Candle, ...]:
    """Drop trailing bars whose close time has not passed yet.

    A backtest must never persist a candle whose close can still change. This
    trims rather than pads: an unfinished bar is removed, not projected.
    """
    if not candles:
        return candles
    moment = (now or datetime.now(UTC)).astimezone(UTC)
    step = interval_step(interval)
    kept = list(candles)
    while kept and kept[-1].opened_at + step > moment:
        kept.pop()
    return tuple(kept)


def aggregate(
    candles: tuple[Candle, ...],
    *,
    source_interval: str,
    target_interval: str,
) -> tuple[Candle, ...]:
    """Roll complete, contiguous source bars up into target bars.

    Used only where a venue does not publish a granularity natively (Coinbase
    has no 4h bucket). A target bar is emitted **only** when every constituent
    source bar is present; a partial bucket is dropped, never completed with an
    invented bar.
    """
    factor_float = interval_to_seconds(target_interval) / interval_to_seconds(source_interval)
    factor = int(factor_float)
    if factor < 2 or factor != factor_float:
        raise ValueError(
            f"{target_interval} is not a whole multiple of {source_interval}; cannot aggregate"
        )
    target_step = int(interval_to_seconds(target_interval))
    buckets: dict[int, list[Candle]] = {}
    for candle in candles:
        opened = int(candle.opened_at.astimezone(UTC).timestamp())
        buckets.setdefault(opened - (opened % target_step), []).append(candle)
    rolled: list[Candle] = []
    for bucket_start in sorted(buckets):
        members = sorted(buckets[bucket_start], key=lambda item: item.opened_at)
        if len(members) != factor:
            # Incomplete bucket: skip-not-invent.
            continue
        rolled.append(
            Candle(
                symbol=members[0].symbol,
                interval=target_interval,
                opened_at=datetime.fromtimestamp(bucket_start, tz=UTC),
                open=members[0].open,
                high=max(member.high for member in members),
                low=min(member.low for member in members),
                close=members[-1].close,
                volume=sum(member.volume for member in members),
            )
        )
    return tuple(rolled)


# --- cross-venue sanity ------------------------------------------------------


@dataclass(frozen=True)
class DivergentBar:
    opened_at: datetime
    left_close: float
    right_close: float
    divergence_bps: float

    def as_note(self) -> dict[str, str]:
        return {
            "opened_at": self.opened_at.isoformat(),
            "left_close": f"{self.left_close:.8g}",
            "right_close": f"{self.right_close:.8g}",
            "divergence_bps": f"{self.divergence_bps:.2f}",
        }


@dataclass(frozen=True)
class DivergenceReport:
    """Cross-venue close comparison on the bars both venues published."""

    left_venue: str
    right_venue: str
    max_bps: float
    compared_bars: int
    flagged: tuple[DivergentBar, ...]
    worst_bps: float
    overlap_first: datetime | None = None
    overlap_last: datetime | None = None

    @property
    def status(self) -> Literal["ok", "flagged", "skipped"]:
        if self.compared_bars == 0:
            return "skipped"
        return "flagged" if self.flagged else "ok"

    def as_note(self) -> dict[str, object]:
        return {
            "left_venue": self.left_venue,
            "right_venue": self.right_venue,
            "max_reference_divergence_bps": self.max_bps,
            "status": self.status,
            "compared_bars": self.compared_bars,
            "flagged_bars": len(self.flagged),
            "worst_bps": round(self.worst_bps, 2),
            "overlap_first": (
                self.overlap_first.isoformat() if self.overlap_first is not None else ""
            ),
            "overlap_last": (
                self.overlap_last.isoformat() if self.overlap_last is not None else ""
            ),
            "flagged": [bar.as_note() for bar in self.flagged],
        }


def close_divergence_bps(left: float, right: float) -> float:
    """Symmetric divergence in basis points against the mean of the two closes."""
    midpoint = (left + right) / 2.0
    if midpoint <= 0:
        raise ValueError("closes must be positive to measure divergence")
    return abs(left - right) / midpoint * 10_000.0


def cross_venue_divergence(
    left: tuple[Candle, ...],
    right: tuple[Candle, ...],
    *,
    left_venue: str,
    right_venue: str,
    max_bps: float,
) -> DivergenceReport:
    """Flag every shared bar whose closes disagree by more than ``max_bps``.

    ``max_bps`` is supplied by the caller from the version-controlled
    ``Settings.max_reference_divergence_bps``; nothing here reads a limit out
    of fetched content. Bars only one venue published are not compared (a
    missing bar is a skip, not a disagreement) and never averaged together.
    """
    if max_bps <= 0:
        raise ValueError("max_bps must be positive")
    right_by_time = {candle.opened_at.astimezone(UTC): candle for candle in right}
    flagged: list[DivergentBar] = []
    compared = 0
    worst = 0.0
    overlap: list[datetime] = []
    for candle in left:
        opened = candle.opened_at.astimezone(UTC)
        other = right_by_time.get(opened)
        if other is None:
            continue
        compared += 1
        overlap.append(opened)
        bps = close_divergence_bps(candle.close, other.close)
        worst = max(worst, bps)
        if bps > max_bps:
            flagged.append(
                DivergentBar(
                    opened_at=opened,
                    left_close=candle.close,
                    right_close=other.close,
                    divergence_bps=bps,
                )
            )
    return DivergenceReport(
        left_venue=left_venue,
        right_venue=right_venue,
        max_bps=max_bps,
        compared_bars=compared,
        flagged=tuple(flagged),
        worst_bps=worst,
        overlap_first=min(overlap) if overlap else None,
        overlap_last=max(overlap) if overlap else None,
    )
