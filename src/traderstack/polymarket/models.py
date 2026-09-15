"""Bounded, typed values reduced from untrusted Polymarket/NWP payloads."""

from __future__ import annotations

from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class ContractSide(StrEnum):
    YES = "yes"
    NO = "no"


class TemperatureContract(StrEnum):
    THRESHOLD_OR_HIGHER = "threshold_or_higher"
    BUCKET = "bucket"
    # --- polymarket weather PIT tape (#141) ---
    # Polymarket's bottom bucket is "N°F or below"; it is a distinct contract
    # family from the top "N°F or higher" bucket, not its complement.
    THRESHOLD_OR_LOWER = "threshold_or_lower"


class IntentStatus(StrEnum):
    WOULD_TRADE = "would_trade"
    BELOW_EDGE = "below_edge"
    KILL_SWITCH = "kill_switch"
    CITY_BLOCKED = "city_blocked"
    UNPARSED = "unparsed"
    STALE_OR_MISSING = "stale_or_missing"
    MID_OUT_OF_BOUNDS = "mid_out_of_bounds"
    FORECAST_MISSING = "forecast_missing"


class City(BaseModel):
    slug: str
    name: str
    aliases: tuple[str, ...] = ()
    latitude: float
    longitude: float
    timezone: str
    climate: str
    # --- polymarket weather PIT tape (#141) ---
    # Official-resolution metadata. Empty station ids mean "not verified":
    # the resolver skips the city rather than guessing a station.
    station_icao: str = ""
    iem_station: str = ""
    iem_network: str = ""
    ghcn_id: str = ""
    resolution_station_name: str = ""
    # Unit the Polymarket buckets are quoted in. Celsius buckets are single
    # degrees and do not fit the integer-°F bucket model, so they fail closed.
    market_unit: Literal["F", "C"] = "F"


class ParsedTemperatureMarket(BaseModel):
    """Deterministic parse of a Gamma weather market into research inputs."""

    market_id: str
    question: str
    city_slug: str
    city_name: str
    event_date: date
    contract: TemperatureContract
    threshold_f: float | None = None
    bucket_low_f: float | None = None
    bucket_high_f: float | None = None
    yes_token_id: str
    no_token_id: str
    end_at: datetime | None = None
    # --- polymarket weather PIT tape (#141) ---
    condition_id: str = ""


class ForecastPoint(BaseModel):
    city_slug: str
    event_date: date
    high_f: float
    source: Literal["open_meteo", "noaa"]
    issued_at: datetime
    sigma_f: float = Field(gt=0)
    # --- polymarket weather PIT tape (#141) ---
    model: str = "best_match"


class EdgeCalculation(BaseModel):
    model_probability: float = Field(ge=0, le=1)
    market_mid: float = Field(ge=0, le=1)
    raw_edge: float
    net_edge: float
    side: ContractSide
    fee_haircut: float = Field(ge=0, lt=1)


class PaperIntent(BaseModel):
    """A would-trade record. ``venue_submitted`` is always false."""

    intent_id: UUID = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    venue: Literal["polymarket"] = "polymarket"
    trading_mode: Literal["paper"] = "paper"
    execution: Literal["paper_intent_only"] = "paper_intent_only"
    venue_submitted: Literal[False] = False
    status: IntentStatus
    strategy_id: str = "polymarket_weather_nwp_edge"
    city_slug: str | None = None
    market_id: str | None = None
    question: str | None = None
    event_date: date | None = None
    contract: TemperatureContract | None = None
    side: ContractSide | None = None
    token_id: str | None = None
    model_probability: float | None = Field(default=None, ge=0, le=1)
    market_mid: float | None = Field(default=None, ge=0, le=1)
    raw_edge: float | None = None
    net_edge: float | None = None
    forecast_high_f: float | None = None
    forecast_source: str | None = None
    paper_notional_usd: float = Field(default=0.0, ge=0)
    reasons: list[str] = Field(default_factory=list)
    kill_switch_sources: tuple[str, ...] = ()
