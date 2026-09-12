"""NWP forecast fetch: Open-Meteo (default) and optional NOAA.

Both adapters are read-only public HTTP. Payloads are reduced to a single
daily high in °F for an allowlisted city/date.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, Literal
from urllib.parse import urlparse

import httpx

from traderstack.market.registry import ProviderRegistry
from traderstack.polymarket.models import City, ForecastPoint

NOAA_USER_AGENT = "DeFi-TraderStack-Agent/0.1 (paper research; no live orders)"


def _daily_high_from_open_meteo(payload: Any, event_date: date) -> float:
    if not isinstance(payload, dict):
        raise TypeError("unexpected Open-Meteo payload")
    daily = payload.get("daily")
    if not isinstance(daily, dict):
        raise TypeError("Open-Meteo payload missing daily block")
    times = daily.get("time")
    highs = daily.get("temperature_2m_max")
    if not isinstance(times, list) or not isinstance(highs, list):
        raise TypeError("Open-Meteo daily arrays missing")
    target = event_date.isoformat()
    for stamp, high in zip(times, highs, strict=False):
        if stamp == target and isinstance(high, int | float):
            return float(high)
    raise KeyError(f"Open-Meteo daily high missing for {target}")


def _daily_high_from_noaa(payload: Any, event_date: date) -> float:
    if not isinstance(payload, dict):
        raise TypeError("unexpected NOAA payload")
    properties = payload.get("properties")
    periods = properties.get("periods") if isinstance(properties, dict) else None
    if not isinstance(periods, list):
        raise TypeError("NOAA forecast missing periods")
    for period in periods:
        if not isinstance(period, dict) or period.get("isDaytime") is False:
            continue
        start = period.get("startTime")
        if not isinstance(start, str):
            continue
        try:
            started = datetime.fromisoformat(start)
        except ValueError:
            continue
        if started.date() != event_date:
            continue
        temp = period.get("temperature")
        unit = str(period.get("temperatureUnit") or "F").upper()
        if not isinstance(temp, int | float):
            continue
        value = float(temp)
        if unit == "C":
            value = value * 9.0 / 5.0 + 32.0
        return value
    raise KeyError(f"NOAA daytime high missing for {event_date.isoformat()}")


@dataclass
class OpenMeteoClient:
    base_url: str = "https://api.open-meteo.com"
    client: httpx.AsyncClient | None = None
    registry: ProviderRegistry | None = None
    timeout_seconds: float = 10.0

    async def daily_high(self, city: City, event_date: date, *, sigma_f: float) -> ForecastPoint:
        if self.registry is not None:
            high = await self.registry.call(
                self._daily_high,
                city,
                event_date,
                cache_key=("open_meteo", city.slug, event_date.isoformat()),
            )
        else:
            high = await self._daily_high(city, event_date)
        return ForecastPoint(
            city_slug=city.slug,
            event_date=event_date,
            high_f=high,
            source="open_meteo",
            issued_at=datetime.now(UTC),
            sigma_f=sigma_f,
        )

    async def _daily_high(self, city: City, event_date: date) -> float:
        params = {
            "latitude": f"{city.latitude:.4f}",
            "longitude": f"{city.longitude:.4f}",
            "daily": "temperature_2m_max",
            "temperature_unit": "fahrenheit",
            "timezone": city.timezone,
            "forecast_days": "16",
        }
        payload = await self._get("/v1/forecast", params)
        return _daily_high_from_open_meteo(payload, event_date)

    async def _get(self, path: str, params: Mapping[str, str]) -> Any:
        if self.client is not None:
            response = await self.client.get(path, params=dict(params))
        else:
            async with httpx.AsyncClient(
                base_url=self.base_url, timeout=self.timeout_seconds
            ) as client:
                response = await client.get(path, params=dict(params))
        response.raise_for_status()
        return response.json()


@dataclass
class NoaaClient:
    """Optional NOAA forecast. Requires a User-Agent; still read-only."""

    base_url: str = "https://api.weather.gov"
    user_agent: str = NOAA_USER_AGENT
    client: httpx.AsyncClient | None = None
    registry: ProviderRegistry | None = None
    timeout_seconds: float = 10.0

    def _headers(self) -> dict[str, str]:
        return {"User-Agent": self.user_agent, "Accept": "application/geo+json"}

    async def daily_high(self, city: City, event_date: date, *, sigma_f: float) -> ForecastPoint:
        if self.registry is not None:
            high = await self.registry.call(
                self._daily_high,
                city,
                event_date,
                cache_key=("noaa", city.slug, event_date.isoformat()),
            )
        else:
            high = await self._daily_high(city, event_date)
        return ForecastPoint(
            city_slug=city.slug,
            event_date=event_date,
            high_f=high,
            source="noaa",
            issued_at=datetime.now(UTC),
            sigma_f=sigma_f,
        )

    async def _daily_high(self, city: City, event_date: date) -> float:
        points = await self._get(f"/points/{city.latitude:.4f},{city.longitude:.4f}")
        properties = points.get("properties") if isinstance(points, dict) else None
        forecast_url = properties.get("forecast") if isinstance(properties, dict) else None
        if not isinstance(forecast_url, str) or not forecast_url:
            raise TypeError("NOAA points payload missing forecast URL")
        path = _path_under_base(forecast_url, self.base_url)
        forecast = await self._get(path)
        return _daily_high_from_noaa(forecast, event_date)

    async def _get(self, path: str) -> Any:
        if self.client is not None:
            response = await self.client.get(path, headers=self._headers())
        else:
            async with httpx.AsyncClient(
                base_url=self.base_url, timeout=self.timeout_seconds
            ) as client:
                response = await client.get(path, headers=self._headers())
        response.raise_for_status()
        return response.json()


def _path_under_base(url: str, base_url: str) -> str:
    """Keep NOAA follow-up requests on the configured host."""

    parsed = urlparse(url)
    base = urlparse(base_url)
    if parsed.netloc and parsed.netloc != base.netloc:
        raise ValueError(f"NOAA forecast URL host {parsed.netloc!r} is not {base.netloc!r}")
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    return path


ForecastProviderName = Literal["open_meteo", "noaa"]
