"""Official station highs for weather-market resolution (#141).

Two independent, free, unauthenticated read-only sources:

* **IEM ASOS** ``cgi-bin/request/daily.py`` — same-day availability, and the
  closest free stand-in for the NOAA hourly ``Temp`` maximum Polymarket
  actually resolves on. This is the *primary* (``resolution_source =
  iem_asos``).
* **NCEI GHCN-Daily** ``TMAX`` — a ~3-day-lagged, US-centric *cross-check*.

They are not the same measurement: GHCN-Daily TMAX is the published daily
maximum for the local climate day, IEM's ``max_temp_f`` is derived from the
ASOS observations. Verified 2026-09-15 for 2025-06-01: they agreed within
1 °F at 10 of 11 US stations checked and differed by 2 °F at KLAX; over
2025-06-01..03 at Miami they differed by 1, 3 and 0 °F. So the resolver
records both and **fails closed** when they disagree by more than the
tolerance, rather than picking the flattering one.

Nothing here writes, signs or orders. A missing series is a skip with a
reason — never a zero, and never Gamma's settlement price.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

import httpx

from traderstack.market.registry import ProviderRegistry
from traderstack.polymarket.models import City

IEM_SOURCE = "iem_asos"
GHCN_SOURCE = "ncei_ghcn_daily"


@dataclass(frozen=True)
class StationFetch:
    """Skip-not-invent record for one station series read."""

    name: str
    source: str
    status: Literal["ok", "skipped"]
    reason: str = ""
    value: float | None = None

    def as_note(self) -> str:
        if self.status == "ok" and self.value is not None:
            return f"{self.name} [{self.source}]: ok ({self.value:.1f} °F)"
        return f"{self.name} [{self.source}]: skipped ({self.reason or 'no reason recorded'})"


@dataclass(frozen=True)
class OfficialHigh:
    """Resolution outcome for one city/date. ``high_f`` is None when unmatched."""

    status: Literal["ok", "unmatched"]
    reason: str = ""
    high_f: float | None = None
    station_id: str = ""
    resolution_source: str = "missing"
    crosscheck_high_f: float | None = None
    crosscheck_source: str = "missing"
    mismatch_f: float | None = None
    fetches: tuple[StationFetch, ...] = ()


def parse_iem_daily_max_f(text: str, event_date: date, station: str) -> float:
    """Reduce the IEM CSV body to one float °F for the exact day."""

    body = text.strip()
    if not body:
        raise ValueError("empty IEM response")
    if body.upper().startswith("ERROR"):
        raise ValueError(" ".join(body.splitlines()[0].split())[:200])
    reader = csv.DictReader(io.StringIO(body))
    target = event_date.isoformat()
    for row in reader:
        if (row.get("day") or "").strip() != target:
            continue
        if (row.get("station") or "").strip().upper() != station.upper():
            continue
        raw = (row.get("max_temp_f") or "").strip()
        if not raw or raw.upper() in {"NA", "M", "NONE", "NULL"}:
            raise ValueError(f"IEM max_temp_f blank for {station} {target}")
        return float(raw)
    raise KeyError(f"IEM has no {station} row for {target}")


def parse_ghcn_tmax_f(payload: Any, event_date: date, station: str) -> float:
    """Reduce the NCEI JSON body to one float °F for the exact day."""

    if not isinstance(payload, list):
        raise TypeError("unexpected NCEI payload")
    target = event_date.isoformat()
    for row in payload:
        if not isinstance(row, dict):
            continue
        if str(row.get("DATE") or "").strip()[:10] != target:
            continue
        if str(row.get("STATION") or "").strip().upper() != station.upper():
            continue
        raw = row.get("TMAX")
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            raise ValueError(f"GHCN TMAX blank for {station} {target}")
        return float(raw)
    raise KeyError(f"GHCN has no {station} TMAX row for {target}")


@dataclass
class IemAsosClient:
    """Read-only IEM ASOS daily maxima. GET only; never signs or posts."""

    base_url: str = "https://mesonet.agron.iastate.edu"
    client: httpx.AsyncClient | None = None
    registry: ProviderRegistry | None = None
    timeout_seconds: float = 20.0

    async def daily_max_f(self, city: City, event_date: date) -> float:
        if not city.iem_network or not city.iem_station:
            raise ValueError(f"{city.slug} has no verified IEM station")
        if self.registry is not None:
            return await self.registry.call(
                self._daily_max_f,
                city,
                event_date,
                cache_key=("iem", city.iem_station, event_date.isoformat()),
            )
        return await self._daily_max_f(city, event_date)

    async def _daily_max_f(self, city: City, event_date: date) -> float:
        params = {
            "network": city.iem_network,
            "stations": city.iem_station,
            "year1": str(event_date.year),
            "month1": str(event_date.month),
            "day1": str(event_date.day),
            "year2": str(event_date.year),
            "month2": str(event_date.month),
            "day2": str(event_date.day),
            "var": "max_temp_f",
            "na": "blank",
            "format": "csv",
        }
        text = await self._get("/cgi-bin/request/daily.py", params)
        return parse_iem_daily_max_f(text, event_date, city.iem_station)

    async def _get(self, path: str, params: Mapping[str, str]) -> str:
        if self.client is not None:
            response = await self.client.get(path, params=dict(params))
        else:
            async with httpx.AsyncClient(
                base_url=self.base_url, timeout=self.timeout_seconds
            ) as client:
                response = await client.get(path, params=dict(params))
        response.raise_for_status()
        return response.text


@dataclass
class GhcnDailyClient:
    """Read-only NCEI GHCN-Daily TMAX. GET only; never signs or posts."""

    base_url: str = "https://www.ncei.noaa.gov"
    client: httpx.AsyncClient | None = None
    registry: ProviderRegistry | None = None
    timeout_seconds: float = 20.0

    async def daily_tmax_f(self, city: City, event_date: date) -> float:
        if not city.ghcn_id:
            raise ValueError(f"{city.slug} has no verified GHCN-Daily station")
        if self.registry is not None:
            return await self.registry.call(
                self._daily_tmax_f,
                city,
                event_date,
                cache_key=("ghcn", city.ghcn_id, event_date.isoformat()),
            )
        return await self._daily_tmax_f(city, event_date)

    async def _daily_tmax_f(self, city: City, event_date: date) -> float:
        params = {
            "dataset": "daily-summaries",
            "stations": city.ghcn_id,
            "startDate": event_date.isoformat(),
            "endDate": event_date.isoformat(),
            "dataTypes": "TMAX",
            "units": "standard",
            "format": "json",
        }
        payload = await self._get("/access/services/data/v1", params)
        return parse_ghcn_tmax_f(payload, event_date, city.ghcn_id)

    async def _get(self, path: str, params: Mapping[str, str]) -> Any:
        if self.client is not None:
            response = await self.client.get(path, params=dict(params))
        else:
            async with httpx.AsyncClient(
                base_url=self.base_url, timeout=self.timeout_seconds
            ) as client:
                response = await client.get(path, params=dict(params))
        response.raise_for_status()
        body = response.text.strip()
        if not body:
            return []
        return response.json()


async def resolve_official_high(
    city: City,
    event_date: date,
    *,
    iem: IemAsosClient,
    ghcn: GhcnDailyClient,
    tolerance_f: float = 1.0,
) -> OfficialHigh:
    """Official high for one city/date, or an explicit ``unmatched`` result.

    Fails closed: the primary must be present, the cross-check must be
    present, and the two must agree within ``tolerance_f``. Anything else
    returns ``status="unmatched"`` with a reason and no value. Gamma's
    ``outcomePrices`` are never consulted — settlement is not an
    observation, and reading it back would be look-ahead.
    """

    fetches: list[StationFetch] = []
    primary: float | None = None
    try:
        primary = await iem.daily_max_f(city, event_date)
        fetches.append(
            StationFetch(
                name=f"{city.slug} {city.iem_station or '-'}",
                source=IEM_SOURCE,
                status="ok",
                value=primary,
            )
        )
    except Exception as exc:  # noqa: BLE001 - any failure is a skip, never a zero.
        fetches.append(
            StationFetch(
                name=f"{city.slug} {city.iem_station or '-'}",
                source=IEM_SOURCE,
                status="skipped",
                reason=f"{type(exc).__name__}: {exc}"[:200],
            )
        )

    secondary: float | None = None
    try:
        secondary = await ghcn.daily_tmax_f(city, event_date)
        fetches.append(
            StationFetch(
                name=f"{city.slug} {city.ghcn_id or '-'}",
                source=GHCN_SOURCE,
                status="ok",
                value=secondary,
            )
        )
    except Exception as exc:  # noqa: BLE001 - any failure is a skip, never a zero.
        fetches.append(
            StationFetch(
                name=f"{city.slug} {city.ghcn_id or '-'}",
                source=GHCN_SOURCE,
                status="skipped",
                reason=f"{type(exc).__name__}: {exc}"[:200],
            )
        )

    if primary is None:
        return OfficialHigh(
            status="unmatched",
            reason="primary_station_missing",
            fetches=tuple(fetches),
        )
    if secondary is None:
        return OfficialHigh(
            status="unmatched",
            reason="crosscheck_station_missing",
            fetches=tuple(fetches),
        )
    mismatch = abs(primary - secondary)
    if mismatch > tolerance_f:
        return OfficialHigh(
            status="unmatched",
            reason=f"crosscheck_mismatch_{mismatch:.1f}F",
            crosscheck_high_f=secondary,
            crosscheck_source=GHCN_SOURCE,
            mismatch_f=mismatch,
            fetches=tuple(fetches),
        )
    return OfficialHigh(
        status="ok",
        high_f=primary,
        station_id=city.station_icao or city.iem_station,
        resolution_source=IEM_SOURCE,
        crosscheck_high_f=secondary,
        crosscheck_source=GHCN_SOURCE,
        mismatch_f=mismatch,
        fetches=tuple(fetches),
    )
