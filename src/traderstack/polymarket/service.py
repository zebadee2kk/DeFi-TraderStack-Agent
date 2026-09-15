"""One paper research cycle: discover → forecast → edge → ledger.

Never imported by the crypto paper loop. Never posts to the CLOB. The
operator kill switch (same four-channel ``KillSwitch`` as crypto) withholds
would-trade intents and fails closed.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from traderstack.config import Settings
from traderstack.killswitch import KillSwitch
from traderstack.market.registry import ProviderRegistry
from traderstack.polymarket.cities import CITY_CATALOG, match_city, resolve_allowlist
from traderstack.polymarket.clob import ClobPublicClient
from traderstack.polymarket.edge import calculate_edge
from traderstack.polymarket.forecast import NoaaClient, OpenMeteoClient
from traderstack.polymarket.gamma import GammaClient
from traderstack.polymarket.ledger import PolymarketWeatherPaperLedger
from traderstack.polymarket.models import (
    City,
    ForecastPoint,
    IntentStatus,
    PaperIntent,
    ParsedTemperatureMarket,
)
from traderstack.polymarket.parse import parse_temperature_market


@dataclass
class WeatherFixtures:
    """Offline replacements for Gamma / CLOB / NWP HTTP."""

    events: tuple[dict[str, Any], ...] = ()
    mids: dict[str, float] = field(default_factory=dict)
    forecasts: dict[tuple[str, str], ForecastPoint] = field(default_factory=dict)


@dataclass
class WeatherCycleReport:
    trading_mode: str
    kill_switch_engaged: bool
    kill_switch_sources: tuple[str, ...]
    cities: tuple[str, ...]
    markets_seen: int
    parsed: int
    would_trade: int
    withheld: int
    below_edge: int
    skipped: int
    intents: list[PaperIntent]

    def render(self) -> str:
        lines = [
            "Polymarket weather paper cycle (research only; no CLOB orders)",
            f"TRADING_MODE={self.trading_mode}  kill_switch="
            f"{'engaged' if self.kill_switch_engaged else 'clear'}"
            + (f" ({', '.join(self.kill_switch_sources)})" if self.kill_switch_sources else ""),
            f"cities: {', '.join(self.cities)}",
            (
                f"markets seen={self.markets_seen} parsed={self.parsed} "
                f"would_trade={self.would_trade} below_edge={self.below_edge} "
                f"withheld={self.withheld} skipped={self.skipped}"
            ),
        ]
        for intent in self.intents:
            if intent.status is IntentStatus.WOULD_TRADE:
                lines.append(
                    f"  WOULD_TRADE {intent.side} {intent.city_slug} "
                    f"mid={intent.market_mid:.3f} model={intent.model_probability:.3f} "
                    f"net_edge={intent.net_edge:.3f} paper=${intent.paper_notional_usd:.2f} "
                    f"(not submitted)"
                )
            elif intent.status is IntentStatus.KILL_SWITCH:
                lines.append(
                    f"  WITHHELD kill_switch {intent.city_slug or '-'} net_edge={intent.net_edge}"
                )
            elif intent.status is IntentStatus.BELOW_EDGE:
                lines.append(f"  BELOW_EDGE {intent.city_slug} net_edge={intent.net_edge:.3f}")
        if self.would_trade:
            lines.append(
                "Claimed weather-market win rates are unproven. Treat WOULD_TRADE "
                "rows as hypotheses until the A/B gates in docs/EVALUATION-FRAMEWORK.md pass."
            )
        return "\n".join(lines)


def require_paper_trading_mode(settings: Settings) -> None:
    if settings.trading_mode != "paper":
        raise RuntimeError(
            "polymarket weather research requires TRADING_MODE=paper "
            f"(got {settings.trading_mode!r}); live/shadow CLOB trading is not implemented"
        )


def _iter_market_payloads(events: tuple[dict[str, Any], ...]) -> list[dict[str, Any]]:
    markets: list[dict[str, Any]] = []
    for event in events:
        nested = event.get("markets")
        if isinstance(nested, list) and nested:
            markets.extend(row for row in nested if isinstance(row, dict))
        elif "clobTokenIds" in event or "question" in event:
            markets.append(event)
    return markets


def _build_registries(settings: Settings) -> dict[str, ProviderRegistry]:
    quota = settings.polymarket_weather_calls_per_minute
    ttl = settings.polymarket_weather_cache_seconds
    # --- polymarket weather PIT tape (#141) ---
    # "iem" / "ghcn" are the official station-high readers used by the
    # resolver; they share the same timeout/breaker/quota wiring.
    names = ("polymarket_gamma", "polymarket_clob", "open_meteo", "noaa", "iem", "ghcn")
    return {
        name: ProviderRegistry(
            name=name,
            timeout_seconds=settings.provider_timeout_seconds,
            failure_threshold=settings.provider_failure_threshold,
            cooldown_seconds=settings.provider_breaker_cooldown_seconds,
            calls_per_minute=quota,
            cache_ttl_seconds=ttl,
        )
        for name in names
    }


@dataclass
class PolymarketWeatherPaperService:
    settings: Settings
    ledger: PolymarketWeatherPaperLedger
    kill_switch: KillSwitch
    gamma: GammaClient | None = None
    clob: ClobPublicClient | None = None
    open_meteo: OpenMeteoClient | None = None
    noaa: NoaaClient | None = None
    fixtures: WeatherFixtures | None = None
    clock: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        *,
        ledger: PolymarketWeatherPaperLedger,
        kill_switch: KillSwitch,
        fixtures: WeatherFixtures | None = None,
    ) -> PolymarketWeatherPaperService:
        require_paper_trading_mode(settings)
        if fixtures is not None:
            return cls(
                settings=settings,
                ledger=ledger,
                kill_switch=kill_switch,
                fixtures=fixtures,
            )
        registries = _build_registries(settings)
        return cls(
            settings=settings,
            ledger=ledger,
            kill_switch=kill_switch,
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
            noaa=NoaaClient(
                base_url=settings.polymarket_weather_noaa_base_url,
                user_agent=settings.polymarket_weather_noaa_user_agent,
                registry=registries["noaa"],
                timeout_seconds=settings.provider_timeout_seconds,
            ),
        )

    async def run_once(self) -> WeatherCycleReport:
        require_paper_trading_mode(self.settings)
        await self.kill_switch.refresh()
        allowlist = resolve_allowlist(self.settings.polymarket_weather_cities)
        today = self.clock().date()
        events = await self._discover()
        markets = _iter_market_payloads(events)
        intents: list[PaperIntent] = []
        parsed = 0
        would_trade = 0
        withheld = 0
        below_edge = 0
        skipped = 0
        forecast_cache: dict[tuple[str, str], ForecastPoint] = {}

        for payload in markets:
            market = parse_temperature_market(payload, allowlist=allowlist, today=today)
            if market is None:
                skipped += 1
                city = None
                question = payload.get("question") if isinstance(payload, dict) else None
                if isinstance(question, str):
                    city = match_city(question, tuple(CITY_CATALOG.values()))
                if city is not None and city not in allowlist:
                    intent = PaperIntent(
                        status=IntentStatus.CITY_BLOCKED,
                        city_slug=city.slug,
                        question=question,
                        reasons=["city not on POLYMARKET_WEATHER_CITIES allowlist"],
                    )
                    await self.ledger.append(intent)
                    intents.append(intent)
                continue
            parsed += 1
            intent = await self._evaluate(market, allowlist, forecast_cache)
            await self.ledger.append(intent)
            intents.append(intent)
            if intent.status is IntentStatus.WOULD_TRADE:
                would_trade += 1
            elif intent.status is IntentStatus.KILL_SWITCH:
                withheld += 1
            elif intent.status is IntentStatus.BELOW_EDGE:
                below_edge += 1
            else:
                skipped += 1

        return WeatherCycleReport(
            trading_mode=self.settings.trading_mode,
            kill_switch_engaged=self.kill_switch.engaged,
            kill_switch_sources=self.kill_switch.engaged_sources,
            cities=tuple(city.slug for city in allowlist),
            markets_seen=len(markets),
            parsed=parsed,
            would_trade=would_trade,
            withheld=withheld,
            below_edge=below_edge,
            skipped=skipped,
            intents=intents,
        )

    async def _discover(self) -> tuple[dict[str, Any], ...]:
        if self.fixtures is not None:
            return self.fixtures.events
        if self.gamma is None:
            raise RuntimeError("Gamma client is not configured")
        return await self.gamma.list_weather_events(
            tag_slug=self.settings.polymarket_weather_tag_slug,
            limit=self.settings.polymarket_weather_max_markets,
        )

    async def _midpoint(self, token_id: str) -> float:
        if self.fixtures is not None:
            if token_id not in self.fixtures.mids:
                raise KeyError(f"fixture mid missing for {token_id}")
            return self.fixtures.mids[token_id]
        if self.clob is None:
            raise RuntimeError("CLOB client is not configured")
        return await self.clob.midpoint(token_id)

    async def _forecast(self, city: City, event_date: date) -> ForecastPoint:
        key = (city.slug, event_date.isoformat())
        if self.fixtures is not None:
            if key not in self.fixtures.forecasts:
                raise KeyError(f"fixture forecast missing for {key}")
            return self.fixtures.forecasts[key]
        sigma = self.settings.polymarket_weather_sigma_f
        provider = self.settings.polymarket_weather_forecast_provider
        if provider == "noaa":
            if self.noaa is None:
                raise RuntimeError("NOAA client is not configured")
            return await self.noaa.daily_high(city, event_date, sigma_f=sigma)
        if self.open_meteo is None:
            raise RuntimeError("Open-Meteo client is not configured")
        return await self.open_meteo.daily_high(city, event_date, sigma_f=sigma)

    async def _evaluate(
        self,
        market: ParsedTemperatureMarket,
        allowlist: tuple[City, ...],
        forecast_cache: dict[tuple[str, str], ForecastPoint],
    ) -> PaperIntent:
        city = next(c for c in allowlist if c.slug == market.city_slug)
        cache_key = (city.slug, market.event_date.isoformat())
        try:
            if cache_key not in forecast_cache:
                forecast_cache[cache_key] = await self._forecast(city, market.event_date)
            forecast = forecast_cache[cache_key]
        except Exception as exc:  # noqa: BLE001 - missing NWP fails closed (no intent).
            return PaperIntent(
                status=IntentStatus.FORECAST_MISSING,
                city_slug=market.city_slug,
                market_id=market.market_id,
                question=market.question,
                event_date=market.event_date,
                contract=market.contract,
                reasons=[f"forecast unavailable: {type(exc).__name__}"],
                kill_switch_sources=self.kill_switch.engaged_sources,
            )

        try:
            mid = await self._midpoint(market.yes_token_id)
        except Exception as exc:  # noqa: BLE001 - missing CLOB mid fails closed.
            return PaperIntent(
                status=IntentStatus.STALE_OR_MISSING,
                city_slug=market.city_slug,
                market_id=market.market_id,
                question=market.question,
                event_date=market.event_date,
                contract=market.contract,
                forecast_high_f=forecast.high_f,
                forecast_source=forecast.source,
                reasons=[f"CLOB mid unavailable: {type(exc).__name__}"],
                kill_switch_sources=self.kill_switch.engaged_sources,
            )

        min_mid = self.settings.polymarket_weather_min_mid
        max_mid = self.settings.polymarket_weather_max_mid
        if not min_mid <= mid <= max_mid:
            return PaperIntent(
                status=IntentStatus.MID_OUT_OF_BOUNDS,
                city_slug=market.city_slug,
                market_id=market.market_id,
                question=market.question,
                event_date=market.event_date,
                contract=market.contract,
                market_mid=mid,
                forecast_high_f=forecast.high_f,
                forecast_source=forecast.source,
                reasons=[f"mid {mid} outside [{min_mid}, {max_mid}]"],
                kill_switch_sources=self.kill_switch.engaged_sources,
            )

        edge = calculate_edge(
            market,
            forecast,
            mid,
            fee_haircut=self.settings.polymarket_weather_fee_haircut,
        )
        token_id = market.yes_token_id if edge.side.value == "yes" else market.no_token_id
        reasons = [
            f"model_p={edge.model_probability:.4f}",
            f"mid={edge.market_mid:.4f}",
            f"net_edge={edge.net_edge:.4f}",
            f"min_edge={self.settings.polymarket_weather_min_edge:.4f}",
        ]
        base = PaperIntent(
            status=IntentStatus.BELOW_EDGE,
            city_slug=market.city_slug,
            market_id=market.market_id,
            question=market.question,
            event_date=market.event_date,
            contract=market.contract,
            side=edge.side,
            token_id=token_id,
            model_probability=edge.model_probability,
            market_mid=edge.market_mid,
            raw_edge=edge.raw_edge,
            net_edge=edge.net_edge,
            forecast_high_f=forecast.high_f,
            forecast_source=forecast.source,
            reasons=reasons,
            kill_switch_sources=self.kill_switch.engaged_sources,
        )
        if edge.net_edge < self.settings.polymarket_weather_min_edge:
            return base
        if self.kill_switch.engaged:
            return base.model_copy(
                update={
                    "status": IntentStatus.KILL_SWITCH,
                    "paper_notional_usd": 0.0,
                    "reasons": [
                        *reasons,
                        "kill_switch_engaged: paper intent withheld",
                    ],
                }
            )
        return base.model_copy(
            update={
                "status": IntentStatus.WOULD_TRADE,
                "paper_notional_usd": self.settings.polymarket_weather_paper_notional_usd,
                "reasons": [*reasons, "paper_intent_only: not submitted to CLOB"],
            }
        )
