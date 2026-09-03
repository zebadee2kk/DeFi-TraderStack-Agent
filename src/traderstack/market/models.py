from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class MarketSource(StrEnum):
    KRAKEN = "kraken"
    COINGECKO = "coingecko"
    COINMARKETCAP = "coinmarketcap"
    ROBINHOOD_CHAIN = "robinhood_chain"


class MarketTick(BaseModel):
    source: MarketSource
    symbol: str
    observed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    bid: float = Field(gt=0)
    ask: float = Field(gt=0)
    last: float = Field(gt=0)

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
    price: float = Field(gt=0)


class PriceDivergence(BaseModel):
    primary_source: MarketSource
    reference_source: MarketSource
    asset: str
    primary_price: float = Field(gt=0)
    reference_price: float = Field(gt=0)
    divergence_bps: float = Field(ge=0)
