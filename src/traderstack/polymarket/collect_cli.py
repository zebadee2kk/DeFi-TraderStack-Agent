"""``traderstack-polymarket-weather-collect``: point-in-time tape collector (#141).

Runs from the operator host every 30-60 minutes while weather markets are
open, and appends one bounded observation per open market: the decision-time
CLOB top of book next to the forecast that was available at that instant.

It emits **observations, not intents**. Nothing here sizes, sides, or
submits anything, so it consults no kill switch and writes no paper ledger:
the only intent path remains ``traderstack-polymarket-weather-paper``, whose
kill-switch withholding is unchanged. Do not route intents through this
collector.

GET-only public endpoints (Gamma, CLOB ``/book``, Open-Meteo).
``TRADING_MODE`` must be ``paper``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from traderstack.config import Settings
from traderstack.logging_config import configure_logging
from traderstack.polymarket.cities import CITY_CATALOG, match_city, resolve_allowlist
from traderstack.polymarket.clob import BookTop, ClobPublicClient, book_top_from_payload
from traderstack.polymarket.forecast import OpenMeteoClient
from traderstack.polymarket.gamma import GammaClient
from traderstack.polymarket.models import City, ForecastPoint
from traderstack.polymarket.parse import parse_temperature_market
from traderstack.polymarket.service import (
    _build_registries,
    _iter_market_payloads,
    require_paper_trading_mode,
)
from traderstack.polymarket.tape import (
    PolymarketWeatherTape,
    TapeObservation,
    lead_hours,
    local_close_at,
)

SKIP_REASONS = (
    "city_blocked",
    "unit_unsupported",
    "station_unverified",
    "unparsed",
    "book_one_sided",
    "book_unavailable",
    "forecast_missing",
    "closed",
)


@dataclass
class CollectFixtures:
    """Offline replacements for the Gamma / CLOB / Open-Meteo GETs."""

    events: tuple[dict[str, Any], ...] = ()
    books: dict[str, Any] = field(default_factory=dict)
    forecasts: dict[tuple[str, str], ForecastPoint] = field(default_factory=dict)


@dataclass
class CollectReport:
    trading_mode: str
    tape_path: str
    cities: tuple[str, ...]
    pages: int
    events_seen: int
    markets_seen: int
    parsed: int
    observed: int
    skipped: dict[str, int]

    def render(self) -> str:
        skipped = ", ".join(f"{key}={value}" for key, value in sorted(self.skipped.items()))
        return "\n".join(
            [
                "Polymarket weather PIT tape collector (observations only; no orders)",
                f"TRADING_MODE={self.trading_mode}  tape={self.tape_path}",
                f"cities: {', '.join(self.cities) or '(none resolvable)'}",
                (
                    f"pages={self.pages} events={self.events_seen} "
                    f"markets={self.markets_seen} parsed={self.parsed} "
                    f"observed={self.observed}"
                ),
                f"skipped: {skipped or '(none)'}",
                (
                    "Observations are evidence, not intents: nothing here is sized, "
                    "sided or submitted. Scoring happens in "
                    "traderstack-polymarket-weather-eval after the resolver runs."
                ),
            ]
        )


def _drop_reason(payload: dict[str, Any], allowed: dict[str, City]) -> str:
    """Why a market payload could not be turned into an observation."""

    question = payload.get("question") or payload.get("title")
    if isinstance(question, str):
        city = match_city(question, tuple(CITY_CATALOG.values()))
        if city is not None and city.slug not in allowed:
            return "city_blocked"
        if city is not None and city.market_unit != "F":
            return "unit_unsupported"
    return "unparsed"


@dataclass
class PolymarketWeatherTapeCollector:
    settings: Settings
    tape: PolymarketWeatherTape
    gamma: GammaClient | None = None
    clob: ClobPublicClient | None = None
    open_meteo: OpenMeteoClient | None = None
    fixtures: CollectFixtures | None = None
    cities_raw: str | None = None
    max_pages: int = 6
    page_size: int = 100
    forecast_model: str = "best_match"
    # Seconds to wait between CLOB reads. The ProviderRegistry quota *raises*
    # rather than throttling, so an unpaced cycle would turn every market past
    # the budget into a skip with a misleading reason.
    request_pause_seconds: float = 0.0
    clock: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        *,
        tape: PolymarketWeatherTape,
        fixtures: CollectFixtures | None = None,
        cities_raw: str | None = None,
        max_pages: int = 6,
        forecast_model: str = "best_match",
        request_pause_seconds: float | None = None,
    ) -> PolymarketWeatherTapeCollector:
        require_paper_trading_mode(settings)
        quota = settings.polymarket_weather_calls_per_minute
        pause = (
            request_pause_seconds
            if request_pause_seconds is not None
            else (60.0 / quota if quota else 0.0)
        )
        if fixtures is not None:
            return cls(
                settings=settings,
                tape=tape,
                fixtures=fixtures,
                cities_raw=cities_raw,
                max_pages=max_pages,
                forecast_model=forecast_model,
            )
        registries = _build_registries(settings)
        return cls(
            settings=settings,
            tape=tape,
            cities_raw=cities_raw,
            max_pages=max_pages,
            forecast_model=forecast_model,
            request_pause_seconds=pause,
            gamma=GammaClient(
                base_url=settings.polymarket_gamma_base_url,
                registry=registries["polymarket_gamma"],
                timeout_seconds=settings.provider_timeout_seconds,
            ),
            clob=ClobPublicClient(
                base_url=settings.polymarket_clob_base_url,
                registry=registries["polymarket_clob"],
                timeout_seconds=settings.provider_timeout_seconds,
            ),
            open_meteo=OpenMeteoClient(
                base_url=settings.polymarket_weather_open_meteo_base_url,
                registry=registries["open_meteo"],
                timeout_seconds=settings.provider_timeout_seconds,
            ),
        )

    async def run_once(self) -> CollectReport:
        require_paper_trading_mode(self.settings)
        allowlist = resolve_allowlist(self.cities_raw or self.settings.polymarket_weather_cities)
        by_slug = {city.slug: city for city in allowlist}
        now = self.clock()
        today = now.date()
        skipped = dict.fromkeys(SKIP_REASONS, 0)
        forecast_cache: dict[tuple[str, str], ForecastPoint] = {}
        events_seen = 0
        markets_seen = 0
        parsed = 0
        observed = 0

        pages = await self._discover()
        for page in pages:
            events_seen += len(page)
            for payload in _iter_market_payloads(page):
                markets_seen += 1
                market = parse_temperature_market(payload, allowlist=allowlist, today=today)
                if market is None:
                    skipped[_drop_reason(payload, by_slug)] += 1
                    continue
                parsed += 1
                city = by_slug[market.city_slug]
                if city.market_unit != "F":
                    skipped["unit_unsupported"] += 1
                    continue
                if not city.iem_network or not city.iem_station:
                    skipped["station_unverified"] += 1
                    continue
                close_at = local_close_at(city, market.event_date)
                if now >= close_at:
                    skipped["closed"] += 1
                    continue
                try:
                    top = await self._book_top(market.yes_token_id)
                except ValueError:
                    # A genuinely one-sided or crossed book: no decision-time
                    # mid exists, and inventing one would be the worst kind of
                    # research input.
                    skipped["book_one_sided"] += 1
                    continue
                except Exception:  # noqa: BLE001 - quota/HTTP/breaker, named separately.
                    skipped["book_unavailable"] += 1
                    continue
                key = (city.slug, market.event_date.isoformat())
                try:
                    if key not in forecast_cache:
                        forecast_cache[key] = await self._forecast(city, market.event_date)
                    forecast = forecast_cache[key]
                except Exception:  # noqa: BLE001 - a missing forecast is a skip.
                    skipped["forecast_missing"] += 1
                    continue
                if forecast.issued_at >= close_at:
                    skipped["closed"] += 1
                    continue
                await self.tape.append(
                    TapeObservation(
                        # Only a real event id: the market's own ``id`` would
                        # be a duplicate wearing the wrong label.
                        event_id=str(payload.get("eventId") or payload.get("event_id") or ""),
                        market_id=market.market_id,
                        condition_id=market.condition_id,
                        city_slug=city.slug,
                        station_icao=city.station_icao,
                        event_date=market.event_date,
                        contract=market.contract,
                        threshold_f=market.threshold_f,
                        bucket_low_f=market.bucket_low_f,
                        bucket_high_f=market.bucket_high_f,
                        yes_token_id=market.yes_token_id,
                        no_token_id=market.no_token_id,
                        observed_at=now,
                        clob_mid=top.mid,
                        best_bid=top.best_bid,
                        best_ask=top.best_ask,
                        half_spread=top.half_spread,
                        forecast_high_f=forecast.high_f,
                        forecast_model=forecast.model,
                        forecast_source=forecast.source,
                        forecast_issued_at=forecast.issued_at,
                        close_at=close_at,
                        lead_hours=lead_hours(now, close_at),
                        question=market.question,
                    )
                )
                observed += 1

        return CollectReport(
            trading_mode=self.settings.trading_mode,
            tape_path=str(self.tape.path),
            cities=tuple(city.slug for city in allowlist),
            pages=len(pages),
            events_seen=events_seen,
            markets_seen=markets_seen,
            parsed=parsed,
            observed=observed,
            skipped=skipped,
        )

    async def _discover(self) -> list[tuple[dict[str, Any], ...]]:
        if self.fixtures is not None:
            return [self.fixtures.events] if self.fixtures.events else []
        if self.gamma is None:
            raise RuntimeError("Gamma client is not configured")
        pages: list[tuple[dict[str, Any], ...]] = []
        for index in range(max(1, self.max_pages)):
            page = await self.gamma.list_weather_events_page(
                tag_slug=self.settings.polymarket_weather_tag_slug,
                limit=self.page_size,
                offset=index * self.page_size,
            )
            if not page:
                break
            pages.append(page)
            if not any(
                "highest temperature" in str(event.get("title") or "").lower() for event in page
            ):
                break
        return pages

    async def _book_top(self, token_id: str) -> BookTop:
        if self.fixtures is not None:
            if token_id not in self.fixtures.books:
                raise KeyError(f"fixture book missing for {token_id}")
            return book_top_from_payload(self.fixtures.books[token_id])
        if self.clob is None:
            raise RuntimeError("CLOB client is not configured")
        if self.request_pause_seconds > 0:
            await asyncio.sleep(self.request_pause_seconds)
        return await self.clob.book_top(token_id)

    async def _forecast(self, city: City, event_date: date) -> ForecastPoint:
        key = (city.slug, event_date.isoformat())
        if self.fixtures is not None:
            if key not in self.fixtures.forecasts:
                raise KeyError(f"fixture forecast missing for {key}")
            return self.fixtures.forecasts[key]
        if self.open_meteo is None:
            raise RuntimeError("Open-Meteo client is not configured")
        return await self.open_meteo.daily_high(
            city,
            event_date,
            sigma_f=self.settings.polymarket_weather_sigma_f,
            model=self.forecast_model,
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Collect a point-in-time Polymarket weather tape: decision-time "
            "CLOB top of book plus the as-issued NWP high, appended to JSONL. "
            "Observations only — never an intent, never a CLOB order."
        )
    )
    parser.add_argument(
        "--once", action="store_true", default=True, help="run a single cycle and exit (default)"
    )
    parser.add_argument(
        "--tape-path", default=None, help="JSONL tape (default POLYMARKET_WEATHER_TAPE_PATH)"
    )
    parser.add_argument(
        "--fixtures-dir",
        type=Path,
        default=None,
        help="offline Gamma/CLOB/forecast fixtures (no network)",
    )
    parser.add_argument("--cities", default=None, help="comma-separated catalog slugs")
    parser.add_argument("--max-pages", type=int, default=6, help="Gamma pages to walk (default 6)")
    parser.add_argument(
        "--forecast-model", default="best_match", help="Open-Meteo model (default best_match)"
    )
    parser.add_argument(
        "--request-pause-seconds",
        type=float,
        default=None,
        help=(
            "pause between CLOB book reads (default 60 / "
            "POLYMARKET_WEATHER_CALLS_PER_MINUTE); the registry quota raises "
            "rather than throttling"
        ),
    )
    parser.add_argument("--json", action="store_true", help="emit JSON instead of the table")
    return parser


def load_fixtures(directory: Path) -> CollectFixtures:
    events = json.loads((directory / "events.json").read_text(encoding="utf-8"))
    if not isinstance(events, list):
        raise TypeError(f"{directory / 'events.json'}: expected a JSON array")
    books = json.loads((directory / "books.json").read_text(encoding="utf-8"))
    if not isinstance(books, dict):
        raise TypeError(f"{directory / 'books.json'}: expected a JSON object")
    forecasts_raw = json.loads((directory / "forecasts.json").read_text(encoding="utf-8"))
    if not isinstance(forecasts_raw, dict):
        raise TypeError(f"{directory / 'forecasts.json'}: expected a JSON object")
    forecasts: dict[tuple[str, str], ForecastPoint] = {}
    for key, row in forecasts_raw.items():
        if not isinstance(row, dict):
            raise TypeError(f"forecast {key!r} is not an object")
        point = ForecastPoint.model_validate(row)
        forecasts[(point.city_slug, point.event_date.isoformat())] = point
    return CollectFixtures(
        events=tuple(row for row in events if isinstance(row, dict)),
        books={str(key): value for key, value in books.items()},
        forecasts=forecasts,
    )


def _report_json(report: CollectReport) -> dict[str, Any]:
    return {
        "trading_mode": report.trading_mode,
        "tape_path": report.tape_path,
        "cities": list(report.cities),
        "pages": report.pages,
        "events_seen": report.events_seen,
        "markets_seen": report.markets_seen,
        "parsed": report.parsed,
        "observed": report.observed,
        "skipped": report.skipped,
        "venue_submitted": False,
        "emits": "observations_only",
    }


async def _run(args: argparse.Namespace) -> CollectReport:
    settings = Settings()
    require_paper_trading_mode(settings)
    configure_logging(settings)
    tape_path = Path(args.tape_path or settings.polymarket_weather_tape_path)
    fixtures = load_fixtures(args.fixtures_dir) if args.fixtures_dir is not None else None
    collector = PolymarketWeatherTapeCollector.from_settings(
        settings,
        tape=PolymarketWeatherTape(tape_path),
        fixtures=fixtures,
        cities_raw=args.cities,
        max_pages=args.max_pages,
        forecast_model=args.forecast_model,
        request_pause_seconds=args.request_pause_seconds,
    )
    return await collector.run_once()


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    report = asyncio.run(_run(args))
    if args.json:
        print(json.dumps(_report_json(report), indent=2, default=str))
    else:
        print(report.render())


if __name__ == "__main__":
    main()
