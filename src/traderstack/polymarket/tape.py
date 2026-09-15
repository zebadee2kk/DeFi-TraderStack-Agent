"""Append-only point-in-time tape of Polymarket weather observations (#141).

The #44 evaluator has never scored a row because nothing in this repository
records a *decision-time* CLOB mid next to the forecast that was available at
that moment. Settlement prices are not a substitute: reading them back as a
mid is look-ahead. This module is the storage and the guard for the tape the
collector writes while markets are open.

Everything here is research evidence, never an order:

* every row carries ``venue_submitted=False`` / ``trading_mode="paper"`` and
  the writer refuses anything else;
* ``close_at`` is the end of the event's local calendar day, not Gamma's
  nominal ``endDate`` (12:00Z while the market keeps accepting orders all
  day), so a "point-in-time" claim means what it says;
* both ``observed_at`` and ``forecast_issued_at`` must be strictly before
  ``close_at`` or the row is dropped — and ``eval._row_reason`` checks the
  forecast side again downstream;
* a missing official high is a drop, never a zero.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

from traderstack.polymarket.eval import ResolvedWeatherRow
from traderstack.polymarket.models import City, TemperatureContract

TAPE_SCHEMA_VERSION = 1


class TapeObservation(BaseModel):
    """One decision-time observation of one open weather market."""

    schema_version: int = TAPE_SCHEMA_VERSION
    tape_kind: Literal["live"] = "live"
    venue: Literal["polymarket"] = "polymarket"
    trading_mode: Literal["paper"] = "paper"
    venue_submitted: Literal[False] = False

    event_id: str
    market_id: str
    condition_id: str = ""
    city_slug: str
    station_icao: str = ""
    event_date: date
    contract: TemperatureContract
    threshold_f: float | None = None
    bucket_low_f: float | None = None
    bucket_high_f: float | None = None
    yes_token_id: str
    no_token_id: str

    observed_at: datetime
    clob_mid: float = Field(ge=0, le=1)
    best_bid: float = Field(ge=0, le=1)
    best_ask: float = Field(ge=0, le=1)
    half_spread: float = Field(ge=0, lt=1)

    forecast_high_f: float
    forecast_model: str = "best_match"
    forecast_source: Literal["open_meteo", "noaa", "fixture"] = "open_meteo"
    forecast_issued_at: datetime

    close_at: datetime
    lead_hours: float
    question: str = ""


class ResolvedTapeRow(TapeObservation):
    """A tape observation paired with an official station high."""

    official_high_f: float
    station_id: str
    resolution_source: str
    crosscheck_high_f: float | None = None
    crosscheck_source: str = "missing"
    resolution_mismatch: float | None = None
    resolved_at: datetime


class SourceStatus(BaseModel):
    """One data source actually reached, or explicitly skipped."""

    name: str
    status: Literal["ok", "skipped"]
    detail: str = ""

    def as_note(self) -> str:
        return f"{self.name}: {self.status}" + (f" ({self.detail})" if self.detail else "")


class TapeStatus(BaseModel):
    """Counts-only status of the tape. Deliberately carries no PnL."""

    generated_at: datetime
    tape_path: str
    resolved_path: str
    observations: int = 0
    markets: int = 0
    decision_rows: int = 0
    resolved_rows: int = 0
    eligible_rows: int = 0
    window_start: date | None = None
    window_end: date | None = None
    per_city: dict[str, int] = Field(default_factory=dict)
    per_stage: dict[str, int] = Field(default_factory=dict)
    drop_reasons: dict[str, int] = Field(default_factory=dict)
    prints: dict[str, int] = Field(default_factory=dict)
    sources: list[SourceStatus] = Field(default_factory=list)
    fee_haircut: float
    min_lead_hours: float
    settle_lag_hours: float
    station_tolerance_f: float
    print_kind: str = "single_print"
    notes: list[str] = Field(default_factory=list)


def local_close_at(city: City, event_date: date) -> datetime:
    """End of ``event_date`` in the city's local calendar, as UTC.

    Gamma's ``endDate`` for these events is 12:00Z on the event date while
    the market keeps ``acceptingOrders`` for the rest of the local day.
    Using it as the close would admit observations taken after the day's
    high was already known in some timezones and would discard honest
    afternoon observations in others. The resolution source is the local
    calendar day, so the close is local midnight at the end of it.
    """

    tz = ZoneInfo(city.timezone)
    start_of_next_day = datetime.combine(event_date + timedelta(days=1), datetime.min.time())
    return start_of_next_day.replace(tzinfo=tz).astimezone(UTC)


def lead_hours(observed_at: datetime, close_at: datetime) -> float:
    return (close_at - observed_at).total_seconds() / 3600.0


class PolymarketWeatherTape:
    """Append-only JSONL tape of observations. Refuses non-paper rows."""

    def __init__(self, path: Path) -> None:
        self.path = path

    async def append(self, observation: TapeObservation) -> None:
        await asyncio.to_thread(self.append_sync, observation)

    def append_sync(self, observation: TapeObservation) -> None:
        if observation.venue_submitted:
            raise RuntimeError("weather tape refuses venue_submitted=true")
        if observation.trading_mode != "paper":
            raise RuntimeError("weather tape refuses non-paper trading_mode")
        if observation.observed_at >= observation.close_at:
            raise RuntimeError("weather tape refuses an observation at or after close_at")
        if observation.forecast_issued_at >= observation.close_at:
            raise RuntimeError("weather tape refuses a forecast issued at or after close_at")
        payload = observation.model_dump(mode="json")
        payload["venue_submitted"] = False
        line = json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()

    def read(self) -> tuple[TapeObservation, ...]:
        return tuple(TapeObservation.model_validate(row) for row in _read_jsonl(self.path))


class PolymarketWeatherResolvedTape:
    """Append-only JSONL tape of resolved rows, idempotent on market id."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def read(self) -> tuple[ResolvedTapeRow, ...]:
        return tuple(ResolvedTapeRow.model_validate(row) for row in _read_jsonl(self.path))

    def resolved_market_ids(self) -> set[str]:
        return {row.market_id for row in self.read()}

    def append_sync(self, row: ResolvedTapeRow) -> None:
        if row.venue_submitted or row.trading_mode != "paper":
            raise RuntimeError("resolved weather tape refuses non-paper rows")
        payload = row.model_dump(mode="json")
        payload["venue_submitted"] = False
        line = json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()

    async def append(self, row: ResolvedTapeRow) -> None:
        await asyncio.to_thread(self.append_sync, row)


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    rows: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        payload = json.loads(text)
        if not isinstance(payload, dict):
            raise TypeError(f"{path}: each tape line must be a JSON object")
        rows.append(payload)
    return rows


def select_decision_rows(
    rows: Iterable[TapeObservation], *, min_lead_hours: float = 0.0
) -> tuple[TapeObservation, ...]:
    """One decision row per market: the latest observation with enough lead.

    "Latest with at least ``min_lead_hours`` to go" is the pre-registered
    decision point. It is fixed here rather than chosen per market so the
    selection cannot be tuned against the outcome.
    """

    chosen: dict[str, TapeObservation] = {}
    for row in rows:
        if row.lead_hours < min_lead_hours:
            continue
        current = chosen.get(row.market_id)
        if current is None or row.observed_at > current.observed_at:
            chosen[row.market_id] = row
    return tuple(sorted(chosen.values(), key=lambda row: (row.event_date, row.market_id)))


def to_resolved_weather_rows(
    resolved: Iterable[ResolvedTapeRow], *, print_id: str
) -> tuple[tuple[ResolvedWeatherRow, ...], dict[str, int]]:
    """Convert resolved tape rows into evaluator rows, dropping look-ahead.

    Returns the rows plus the count of each drop reason. Nothing is
    zero-filled: a row that cannot pass the guard is simply absent.
    """

    out: list[ResolvedWeatherRow] = []
    drops: dict[str, int] = {}
    for row in resolved:
        if row.observed_at >= row.close_at:
            drops["lookahead_observation"] = drops.get("lookahead_observation", 0) + 1
            continue
        if row.forecast_issued_at >= row.close_at:
            drops["lookahead_forecast"] = drops.get("lookahead_forecast", 0) + 1
            continue
        if not row.station_id.strip():
            drops["station_unmatched"] = drops.get("station_unmatched", 0) + 1
            continue
        out.append(
            ResolvedWeatherRow(
                market_id=row.market_id,
                city_slug=row.city_slug,
                event_date=row.event_date,
                contract=row.contract,
                threshold_f=row.threshold_f,
                bucket_low_f=row.bucket_low_f,
                bucket_high_f=row.bucket_high_f,
                forecast_high_f=row.forecast_high_f,
                forecast_source=(
                    row.forecast_source
                    if row.forecast_source in {"open_meteo", "noaa"}
                    else "fixture"
                ),
                forecast_issued_at=row.forecast_issued_at,
                market_mid=row.clob_mid,
                half_spread=row.half_spread,
                official_high_f=row.official_high_f,
                station_id=row.station_id,
                resolution_source=row.resolution_source,
                close_at=row.close_at,
                print_id=print_id,
                question=row.question,
            )
        )
    return tuple(out), drops


def split_prints_by_month(
    resolved: Iterable[ResolvedTapeRow],
) -> dict[str, tuple[ResolvedWeatherRow, ...]]:
    """Group resolved rows into non-overlapping calendar-month prints.

    Independence has to come from disjoint event dates, not from scoring the
    same rows twice against a second resolution source: that would be
    manufactured independence, and ``prints_independent`` would accept it.
    """

    by_month: dict[str, list[ResolvedTapeRow]] = {}
    for row in resolved:
        key = f"{row.event_date.year:04d}-{row.event_date.month:02d}"
        by_month.setdefault(key, []).append(row)
    prints: dict[str, tuple[ResolvedWeatherRow, ...]] = {}
    for key in sorted(by_month):
        rows, _ = to_resolved_weather_rows(by_month[key], print_id=key)
        if rows:
            prints[key] = rows
    return prints


def render_tape_status_markdown(status: TapeStatus) -> str:
    """Counts-only status report. No PnL is computed or rendered here."""

    lines = [
        "# Polymarket weather point-in-time tape (collector / resolver)",
        "",
        (
            "Evidence only. This report counts observations; it does not score "
            "them and never computes PnL. Scoring happens in "
            "`traderstack-polymarket-weather-eval`, which cannot promote on a "
            "single print. `PAPER_PROMOTE_POLYMARKET_WEATHER` is not a "
            "`Settings` field and is not added here."
        ),
        "",
        f"Generated: {status.generated_at.isoformat()}",
        "",
        "## Header",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Tape | `{status.tape_path}` |",
        f"| Resolved tape | `{status.resolved_path}` |",
        (
            "| Window (event dates) | "
            + (
                f"{status.window_start.isoformat()} .. {status.window_end.isoformat()}"
                if status.window_start and status.window_end
                else "— (empty tape)"
            )
            + " |"
        ),
        f"| Print kind | {status.print_kind} |",
        (
            f"| Fee model | flat taker haircut {status.fee_haircut:.4f} "
            "(Polymarket Fee Structure V2 formula is deferred) |"
        ),
        f"| Decision rule | latest observation with lead_hours >= {status.min_lead_hours:g} |",
        f"| Settle lag | {status.settle_lag_hours:g} h after close_at |",
        (
            f"| Station match | IEM ASOS primary, NCEI GHCN-Daily cross-check, "
            f"tolerance {status.station_tolerance_f:g} °F (fail closed) |"
        ),
        "| Print kind source | one print per calendar month of event dates |",
        "",
        "## Sources reached",
        "",
        "| Source | Status | Detail |",
        "|---|---|---|",
    ]
    for source in status.sources:
        lines.append(f"| {source.name} | {source.status} | {source.detail or '—'} |")
    lines.extend(
        [
            "",
            "## Counts",
            "",
            "| Stage | Rows |",
            "|---|---|",
            f"| observations on tape | {status.observations} |",
            f"| distinct markets | {status.markets} |",
            f"| decision rows | {status.decision_rows} |",
            f"| resolved rows | {status.resolved_rows} |",
            f"| rows emitted to prints | {status.eligible_rows} |",
        ]
    )
    for stage, count in sorted(status.per_stage.items()):
        lines.append(f"| {stage} | {count} |")
    lines.extend(["", "## Per city (decision rows)", "", "| City | Rows |", "|---|---|"])
    if status.per_city:
        for city, count in sorted(status.per_city.items()):
            lines.append(f"| {city} | {count} |")
    else:
        lines.append("| — | 0 |")
    lines.extend(["", "## Drop reasons", "", "| Reason | Rows |", "|---|---|"])
    if status.drop_reasons:
        for reason, count in sorted(status.drop_reasons.items()):
            lines.append(f"| {reason} | {count} |")
    else:
        lines.append("| — | 0 |")
    lines.extend(["", "## Prints", "", "| Print (event month) | Rows |", "|---|---|"])
    if status.prints:
        for key, count in sorted(status.prints.items()):
            lines.append(f"| {key} | {count} |")
    else:
        lines.append("| — | 0 |")
    if status.notes:
        lines.extend(["", "## Notes", ""])
        lines.extend(f"- {note}" for note in status.notes)
    lines.append("")
    return "\n".join(lines)
