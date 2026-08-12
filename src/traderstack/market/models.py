from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field, model_validator

# Upper bound for any USD price accepted from an external provider; a value
# beyond this (or inf/NaN) is corrupt data, not a market move.
MAX_PLAUSIBLE_PRICE_USD = 1e12


class MarketSource(StrEnum):
    KRAKEN = "kraken"
    COINGECKO = "coingecko"
    COINMARKETCAP = "coinmarketcap"


class MarketTick(BaseModel):
    source: MarketSource
    symbol: str
    observed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    bid: float = Field(gt=0, lt=MAX_PLAUSIBLE_PRICE_USD, allow_inf_nan=False)
    ask: float = Field(gt=0, lt=MAX_PLAUSIBLE_PRICE_USD, allow_inf_nan=False)
    last: float = Field(gt=0, lt=MAX_PLAUSIBLE_PRICE_USD, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_quote(self) -> "MarketTick":
        if self.ask < self.bid:
            raise ValueError("crossed tick: ask below bid")
        return self

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2

    @property
    def spread_bps(self) -> float:
        return ((self.ask - self.bid) / self.mid) * 10_000


class ReferencePrice(BaseModel):
    source: MarketSource
    asset: str
    currency: str = "USD"
    observed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    price: float = Field(gt=0, lt=MAX_PLAUSIBLE_PRICE_USD, allow_inf_nan=False)


class PriceDivergence(BaseModel):
    primary_source: MarketSource
    reference_source: MarketSource
    asset: str
    primary_price: float = Field(gt=0)
    reference_price: float = Field(gt=0)
    divergence_bps: float = Field(ge=0)
