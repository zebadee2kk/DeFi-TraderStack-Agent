from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class MarketSource(StrEnum):
    KRAKEN = "kraken"
    COINGECKO = "coingecko"
    COINMARKETCAP = "coinmarketcap"
    ROBINHOOD_CHAIN = "robinhood_chain"
    # --- paper-research edge data plane ---
    # Research/risk-context feeds only. Never an execution venue.
    BINANCE = "binance"
    BYBIT = "bybit"


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
    # --- order-book depth in the risk plane (#61) ---
    # allow_inf_nan=False is load-bearing, not tidiness. Depth was purely
    # informational until #61 made it a *permission* gate, and an infinite qty
    # produces infinite depth, which satisfies any minimum. A hostile or
    # malformed venue payload must fail here, before the engine sees it --
    # nan already failed the gt/ge bound, inf did not.
    price: float = Field(gt=0, allow_inf_nan=False)
    qty: float = Field(ge=0, allow_inf_nan=False)


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


# --- paper-research edge data plane -------------------------------------------
#
# Liquidation events and second-venue top-of-book are paper-research features.
# They never route orders and are not consumed by RiskEngine to size or
# authorize a trade. Adapters reduce untrusted venue payloads to these typed
# values before anything reaches the pipeline.


class LiquidationSide(StrEnum):
    """Which side of the book was force-closed.

    A Binance ``forceOrder`` with ``S=SELL`` is a long liquidation (the
    exchange sells the bankrupt long). ``S=BUY`` is a short liquidation.
    """

    LONG = "long"
    SHORT = "short"


class LiquidationEvent(BaseModel):
    source: MarketSource
    symbol: str
    asset: str
    observed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    side: LiquidationSide
    qty: float = Field(gt=0)
    price: float = Field(gt=0)
    notional: float = Field(gt=0)


class LiquidationWindowSnapshot(BaseModel):
    """Rolling-window liquidation features for one asset. Research context only."""

    asset: str
    observed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    source_id: str = "binance_liq"
    liq_notional_long_z: float | None = Field(default=None, ge=-5, le=5)
    liq_notional_short_z: float | None = Field(default=None, ge=-5, le=5)
    liq_count_long: float = Field(default=0, ge=0, le=1)
    liq_count_short: float = Field(default=0, ge=0, le=1)
    long_notional: float = Field(default=0, ge=0)
    short_notional: float = Field(default=0, ge=0)


class BookTicker(BaseModel):
    """Best bid/ask from a second venue. Paper feature only — not a venue tick."""

    source: MarketSource
    symbol: str
    asset: str
    observed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    bid: float = Field(gt=0)
    ask: float = Field(gt=0)

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2
