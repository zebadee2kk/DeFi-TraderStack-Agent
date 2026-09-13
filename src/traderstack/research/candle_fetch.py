"""Shared contract for the multi-year research candle fetchers (#133).

Every fetcher in ``research/candles_*.py`` returns a :class:`CandleFetch`
that mirrors ``research.edge_series.EdgeSeriesFetch``: ``status`` is
``"ok"`` or ``"skipped"``, ``reason`` says why, and nothing is invented.
An empty series is a *successful* research outcome reported as
``skipped`` with a reason — never a zero-filled series.

Honesty rules shared by every venue:

* **Strict UTC alignment.** Every bar must open on a multiple of its
  interval in UTC; a misaligned bar is a ``ValueError`` at the adapter,
  which the fetcher reduces to ``status="skipped"``.
* **No interpolation.** Missing bars are reported as gaps (bounded to
  :data:`MAX_GAP_ENTRIES` entries plus a total) and never filled.
* **No uncommitted bar.** A bar whose close time is still in the future
  is dropped before the series is written.
* **Cross-venue divergence is flagged, never reconciled.** A daily close
  that differs by more than ``max_bps`` from the reference venue on the
  same bar is recorded in the sidecar; the candle file is left as fetched.

The candle JSON written here is the *bare list* every ``--candles``
consumer already loads through ``research.cli.load_candles_from_json``;
the fetch header (venue, first/last bar, bar count, gaps, fetch time,
divergence flags) lives in a sidecar ``<out>.meta.json`` so no consumer
has to change. Research inputs only: nothing here reaches ``RiskEngine``,
the pre-trade gate, or any ``PAPER_PROMOTE_*`` default.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from pathlib import Path
from typing import Any, Literal

import httpx

from traderstack.candles import Candle, interval_to_seconds

MAX_GAP_ENTRIES = 200
META_SIDECAR_SUFFIX = ".meta.json"


@dataclass(frozen=True)
class CandleGap:
    """``missing_bars`` consecutive bars are absent immediately after ``after``."""

    after: datetime
    missing_bars: int

    def as_dict(self) -> dict[str, Any]:
        return {"after": self.after.isoformat(), "missing_bars": self.missing_bars}


@dataclass(frozen=True)
class DivergenceFlag:
    """Same-bar close divergence between the fetched series and a reference file."""

    opened_at: datetime
    primary_close: float
    reference_close: float
    divergence_bps: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "opened_at": self.opened_at.isoformat(),
            "primary_close": self.primary_close,
            "reference_close": self.reference_close,
            "divergence_bps": round(self.divergence_bps, 4),
        }


@dataclass(frozen=True)
class CandleFetch:
    """One fetched (or skipped) research candle series plus its header."""

    name: str
    status: Literal["ok", "skipped"]
    reason: str
    source: str = ""
    candles: tuple[Candle, ...] = ()
    first: datetime | None = None
    last: datetime | None = None
    fetched_at: datetime | None = None
    gaps: tuple[CandleGap, ...] = ()
    gap_entries_total: int = 0
    missing_bars_total: int = 0
    notes: tuple[str, ...] = ()
    divergence_flags: tuple[DivergenceFlag, ...] = ()
    divergence_max_bps: float | None = None
    divergence_reference: str = ""

    def as_note(self) -> dict[str, str]:
        payload = {
            "name": self.name,
            "status": self.status,
            "reason": self.reason,
            "source": self.source,
            "points": str(len(self.candles)),
        }
        if self.first is not None:
            payload["first"] = self.first.isoformat()
        if self.last is not None:
            payload["last"] = self.last.isoformat()
        if self.fetched_at is not None:
            payload["fetched_at"] = self.fetched_at.isoformat()
        payload["gaps"] = str(self.gap_entries_total)
        payload["missing_bars"] = str(self.missing_bars_total)
        payload["divergence_flags"] = str(len(self.divergence_flags))
        return payload

    def as_meta(self) -> dict[str, Any]:
        """Sidecar header: everything the issue asks the report to carry."""
        payload: dict[str, Any] = {
            "name": self.name,
            "venue": self.source,
            "status": self.status,
            "reason": self.reason,
            "count": len(self.candles),
            "first": self.first.isoformat() if self.first is not None else None,
            "last": self.last.isoformat() if self.last is not None else None,
            "fetched_at": self.fetched_at.isoformat() if self.fetched_at is not None else None,
            "gap_entries_total": self.gap_entries_total,
            "missing_bars_total": self.missing_bars_total,
            "gaps": [gap.as_dict() for gap in self.gaps],
            "gaps_truncated": self.gap_entries_total > len(self.gaps),
            "notes": list(self.notes),
            "divergence_reference": self.divergence_reference,
            "divergence_max_bps": self.divergence_max_bps,
            "divergence_flags": [flag.as_dict() for flag in self.divergence_flags],
        }
        if self.candles:
            payload["symbol"] = self.candles[0].symbol
            payload["interval"] = self.candles[0].interval
        return payload


@dataclass
class _GapScan:
    entries: list[CandleGap] = field(default_factory=list)
    total_entries: int = 0
    missing_bars: int = 0


def assert_utc_aligned(candles: tuple[Candle, ...] | list[Candle], interval: str) -> None:
    """Raise ``ValueError`` unless every bar opens on a UTC multiple of ``interval``."""
    step = int(interval_to_seconds(interval))
    for index, candle in enumerate(candles):
        opened_at = candle.opened_at
        if opened_at.tzinfo is None or opened_at.utcoffset() != timedelta(0):
            raise ValueError(f"bar {index} ({opened_at.isoformat()}) is not timezone-aware UTC")
        timestamp = opened_at.timestamp()
        if timestamp != int(timestamp) or int(timestamp) % step != 0:
            raise ValueError(
                f"bar {index} ({opened_at.isoformat()}) is not aligned to {interval} in UTC"
            )


def floor_to_interval(unix_seconds: int, interval: str) -> int:
    """Floor a unix timestamp to the start of its ``interval`` bar (UTC)."""
    step = int(interval_to_seconds(interval))
    return (int(unix_seconds) // step) * step


def iso_utc(unix_seconds: int) -> str:
    """``2016-01-01T00:00:00Z`` style ISO8601 for venue query parameters."""
    return datetime.fromtimestamp(int(unix_seconds), tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def sort_and_dedupe(candles: tuple[Candle, ...] | list[Candle]) -> tuple[Candle, ...]:
    """Ascending by ``opened_at``; a later duplicate of the same bar wins."""
    merged: dict[int, Candle] = {}
    for candle in candles:
        merged[int(candle.opened_at.timestamp())] = candle
    return tuple(merged[key] for key in sorted(merged))


def _scan_gaps(candles: tuple[Candle, ...], interval: str) -> _GapScan:
    step = int(interval_to_seconds(interval))
    scan = _GapScan()
    for previous, current in pairwise(candles):
        delta = int(current.opened_at.timestamp()) - int(previous.opened_at.timestamp())
        if delta <= step:
            continue
        missing = delta // step - 1
        if missing <= 0:
            continue
        scan.total_entries += 1
        scan.missing_bars += missing
        if len(scan.entries) < MAX_GAP_ENTRIES:
            scan.entries.append(CandleGap(after=previous.opened_at, missing_bars=missing))
    return scan


def detect_gaps(candles: tuple[Candle, ...] | list[Candle], interval: str) -> tuple[CandleGap, ...]:
    """Bars after which one or more ``interval`` bars are missing (bounded)."""
    return tuple(_scan_gaps(sort_and_dedupe(candles), interval).entries)


def count_missing_bars(candles: tuple[Candle, ...] | list[Candle], interval: str) -> int:
    """Total number of missing bars across every gap (not bounded)."""
    return _scan_gaps(sort_and_dedupe(candles), interval).missing_bars


def drop_uncommitted_last(
    candles: tuple[Candle, ...] | list[Candle],
    interval: str,
    *,
    now: datetime | None = None,
) -> tuple[Candle, ...]:
    """Drop the final bar when its close time is still in the future."""
    ordered = tuple(candles)
    if not ordered:
        return ordered
    reference = now or datetime.now(UTC)
    close_at = ordered[-1].opened_at + timedelta(seconds=interval_to_seconds(interval))
    if close_at > reference:
        return ordered[:-1]
    return ordered


def close_divergence_flags(
    primary: tuple[Candle, ...] | list[Candle],
    reference: tuple[Candle, ...] | list[Candle],
    *,
    max_bps: float,
) -> tuple[DivergenceFlag, ...]:
    """Flag shared bars whose closes diverge by more than ``max_bps``.

    Same definition as ``market.validation.calculate_divergence``
    (``|a-b| / a * 1e4``, ``a`` = the fetched series). Bars present on only
    one side are ignored: this is a flag, never a filter or a blend.
    """
    if max_bps <= 0:
        raise ValueError("max_bps must be positive")
    by_time = {int(candle.opened_at.timestamp()): candle for candle in reference}
    flags: list[DivergenceFlag] = []
    for candle in sort_and_dedupe(primary):
        other = by_time.get(int(candle.opened_at.timestamp()))
        if other is None:
            continue
        divergence_bps = abs(candle.close - other.close) / candle.close * 10_000
        if divergence_bps > max_bps:
            flags.append(
                DivergenceFlag(
                    opened_at=candle.opened_at,
                    primary_close=candle.close,
                    reference_close=other.close,
                    divergence_bps=divergence_bps,
                )
            )
    return tuple(flags)


def skip_fetch(
    name: str,
    *,
    source: str,
    reason: str,
    notes: tuple[str, ...] = (),
    fetched_at: datetime | None = None,
) -> CandleFetch:
    return CandleFetch(
        name=name,
        status="skipped",
        reason=reason,
        source=source,
        notes=notes,
        fetched_at=fetched_at or datetime.now(UTC),
    )


def http_skip(
    name: str,
    *,
    source: str,
    exc: BaseException,
    notes: tuple[str, ...] = (),
) -> CandleFetch:
    """Reduce an HTTP failure to a skip (mirrors ``edge_series._geo_or_http_skip``)."""
    detail = str(exc)
    response_text = ""
    response = getattr(exc, "response", None)
    if response is not None:
        try:
            response_text = (response.text or "")[:200]
        except (httpx.HTTPError, TypeError, ValueError):
            response_text = ""
    lowered = f"{detail} {response_text}".lower()
    if "451" in detail or "451" in response_text:
        detail = "HTTP 451 (geo-blocked / unavailable in this environment)"
    elif "403" in detail or "403" in response_text:
        if "cloudfront" in lowered or "country" in lowered:
            detail = "HTTP 403 (CloudFront / country block — unavailable in this environment)"
        else:
            detail = "HTTP 403 (forbidden in this environment)"
    elif response_text:
        detail = f"{detail}: {response_text}"
    return skip_fetch(name, source=source, reason=detail, notes=notes)


def finish_fetch(
    name: str,
    *,
    source: str,
    candles: tuple[Candle, ...] | list[Candle],
    interval: str,
    ok_reason: str,
    notes: tuple[str, ...] = (),
    fetched_at: datetime | None = None,
) -> CandleFetch:
    """Sort, dedupe, alignment-check and gap-scan a series; empty -> skipped.

    Raises ``ValueError`` when a bar is misaligned; callers reduce that to a
    skip (an unverifiable series is not written).
    """
    ordered = sort_and_dedupe(candles)
    stamp = fetched_at or datetime.now(UTC)
    if not ordered:
        return CandleFetch(
            name=name,
            status="skipped",
            reason="empty series",
            source=source,
            notes=notes,
            fetched_at=stamp,
        )
    assert_utc_aligned(ordered, interval)
    scan = _scan_gaps(ordered, interval)
    return CandleFetch(
        name=name,
        status="ok",
        reason=ok_reason,
        source=source,
        candles=ordered,
        first=ordered[0].opened_at,
        last=ordered[-1].opened_at,
        fetched_at=stamp,
        gaps=tuple(scan.entries),
        gap_entries_total=scan.total_entries,
        missing_bars_total=scan.missing_bars,
        notes=notes,
    )


def meta_path(candle_path: Path) -> Path:
    """``x.json`` -> ``x.meta.json`` (``x.json.meta.json`` would hide the pairing)."""
    if candle_path.suffix == ".json":
        return candle_path.with_name(candle_path.stem + META_SIDECAR_SUFFIX)
    return candle_path.with_name(candle_path.name + META_SIDECAR_SUFFIX)


def write_candle_json(path: Path, candles: tuple[Candle, ...] | list[Candle]) -> None:
    """The bare-list format every ``--candles`` consumer loads."""
    payload = [json.loads(candle.model_dump_json()) for candle in candles]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))


def write_meta_sidecar(candle_path: Path, fetch: CandleFetch) -> Path:
    """Write the header sidecar next to the candle file and return its path."""
    target = meta_path(candle_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = fetch.as_meta()
    payload["candle_file"] = candle_path.name
    target.write_text(json.dumps(payload, indent=2))
    return target


def header_line(fetch: CandleFetch) -> str:
    """One stdout line: venue, first→last, count, gaps, fetched_at, divergence flags."""
    first = fetch.first.isoformat() if fetch.first is not None else "-"
    last = fetch.last.isoformat() if fetch.last is not None else "-"
    stamp = fetch.fetched_at.isoformat() if fetch.fetched_at is not None else "-"
    return (
        f"{fetch.name}: status={fetch.status} venue={fetch.source} "
        f"bars={len(fetch.candles)} first={first} last={last} "
        f"gaps={fetch.gap_entries_total} missing_bars={fetch.missing_bars_total} "
        f"fetched_at={stamp} divergence_flags={len(fetch.divergence_flags)} "
        f"reason={fetch.reason!r}"
    )
