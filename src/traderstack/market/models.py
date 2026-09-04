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


# --- providers (Epic 2): order-book snapshot handling -------------------------


class BookLevel(BaseModel):
    price: float = Field(gt=0)
    qty: float = Field(ge=0)


class BookSnapshot(BaseModel):
    """Best-N levels of an order book on each side, as of ``observed_at``.

    ``bids`` and ``asks`` are best-to-worst (index 0 is the top of book).
    """

    source: MarketSource
    symbol: str
    observed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    bids: tuple[BookLevel, ...] = ()
    asks: tuple[BookLevel, ...] = ()

    @property
    def best_bid(self) -> float | None:
        return self.bids[0].price if self.bids else None

    @property
    def best_ask(self) -> float | None:
        return self.asks[0].price if self.asks else None

    @property
    def mid(self) -> float | None:
        bid, ask = self.best_bid, self.best_ask
        if bid is None or ask is None:
            return None
        return (bid + ask) / 2

    def depth_within_bps(self, bps: float) -> tuple[float, float]:
        """Notional (quote-currency) depth within ``bps`` of the mid on each side.

        Returns ``(bid_depth_usd, ask_depth_usd)``. ``(0.0, 0.0)`` if there is no
        two-sided market or ``bps`` is not positive.
        """
        mid = self.mid
        if mid is None or bps <= 0:
            return (0.0, 0.0)
        bid_floor = mid * (1 - bps / 10_000)
        ask_ceiling = mid * (1 + bps / 10_000)
        bid_depth = sum(level.price * level.qty for level in self.bids if level.price >= bid_floor)
        ask_depth = sum(
            level.price * level.qty for level in self.asks if level.price <= ask_ceiling
        )
        return (bid_depth, ask_depth)
