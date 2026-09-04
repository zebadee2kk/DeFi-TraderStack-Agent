"""Deterministic synthetic market data for the acceptance drills (Epic 10).

One seeded geometric random walk per symbol produces both the candle history the
pre-trade gate backtests and the live ticks the pipeline validates, so an
acceptance or soak run is byte-for-byte reproducible from its seed and never
touches the network.

The default parameters describe a low-volatility uptrend on purpose: the
deterministic strategy ensemble reaches a BUY consensus on it, which is what
lets the drills observe the *whole* path (proposal -> risk -> plan -> submit ->
reconcile) rather than only the market-data rejections.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from traderstack.candles import Candle, interval_to_seconds
from traderstack.market.models import MarketSource, MarketTick, ReferencePrice


@dataclass
class _Walk:
    """One symbol's price path: a fixed candle history plus a live tick cursor."""

    candles: tuple[Candle, ...]
    price: float
    rng: random.Random


@dataclass
class SyntheticMarket:
    """A reproducible multi-symbol market built from a single seed."""

    symbols: tuple[str, ...] = ("BTC/USD",)
    interval: str = "1h"
    start_price: float = 20_000.0
    #: Expected per-bar return of the candle history.
    drift: float = 0.006
    #: Per-bar noise, also used for tick-to-tick moves.
    volatility: float = 0.0008
    seed: int = 7
    spread_bps: float = 4.0
    history: int = 320
    #: Wall-clock anchor for the newest candle. Defaults to "now" at construction.
    anchor: datetime | None = None
    source: MarketSource = MarketSource.KRAKEN
    _walks: dict[str, _Walk] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        if not self.symbols:
            raise ValueError("at least one symbol is required")
        if self.history < 2:
            raise ValueError("history must contain at least two candles")
        anchor = self.anchor or datetime.now(UTC)
        step = timedelta(seconds=interval_to_seconds(self.interval))
        for index, symbol in enumerate(self.symbols):
            # Deterministic simulation, not security: a seeded PRNG is the point.
            rng = random.Random(self.seed + index)
            self._walks[symbol.upper()] = self._build(symbol.upper(), rng, anchor, step)

    def _build(self, symbol: str, rng: random.Random, anchor: datetime, step: timedelta) -> _Walk:
        candles: list[Candle] = []
        price = self.start_price
        opened_at = anchor - step * self.history
        for _ in range(self.history):
            open_price = price
            close = max(open_price * (1.0 + self.drift + rng.gauss(0.0, self.volatility)), 1e-6)
            wick = abs(rng.gauss(0.0, self.volatility)) * open_price
            candles.append(
                Candle(
                    symbol=symbol,
                    interval=self.interval,
                    opened_at=opened_at,
                    open=open_price,
                    high=max(open_price, close) + wick,
                    low=max(min(open_price, close) - wick, 1e-9),
                    close=close,
                    volume=1_000.0 + abs(rng.gauss(0.0, 50.0)),
                )
            )
            price = close
            opened_at += step
        return _Walk(candles=tuple(candles), price=price, rng=rng)

    # --- accessors ---------------------------------------------------------

    def _walk(self, symbol: str) -> _Walk:
        walk = self._walks.get(symbol.upper())
        if walk is None:
            raise KeyError(f"unknown symbol {symbol!r}")
        return walk

    def candles(self, symbol: str, *, count: int | None = None) -> tuple[Candle, ...]:
        history = self._walk(symbol).candles
        return history[-count:] if count is not None else history

    def last(self, symbol: str) -> float:
        return self._walk(symbol).price

    def price_of(self, asset: str) -> float:
        """Latest price for a base asset (``"BTC"``), for reference providers."""

        wanted = asset.upper()
        for symbol, walk in self._walks.items():
            if symbol.split("/", 1)[0] == wanted:
                return walk.price
        raise KeyError(f"no synthetic market for asset {asset!r}")

    def advance(self, symbol: str) -> float:
        """Step one tick forward and return the new price."""

        walk = self._walk(symbol)
        walk.price = max(walk.price * (1.0 + walk.rng.gauss(0.0, self.volatility)), 1e-6)
        return walk.price

    def tick(self, symbol: str, *, observed_at: datetime | None = None) -> MarketTick:
        price = self.advance(symbol)
        half_spread = price * (self.spread_bps / 2 / 10_000)
        return MarketTick(
            source=self.source,
            symbol=symbol,
            observed_at=observed_at or datetime.now(UTC),
            bid=price - half_spread,
            ask=price + half_spread,
            last=price,
        )

    def reference(
        self,
        asset: str,
        source: MarketSource,
        *,
        observed_at: datetime | None = None,
        price: float | None = None,
    ) -> ReferencePrice:
        return ReferencePrice(
            source=source,
            asset=asset.upper(),
            currency="USD",
            observed_at=observed_at or datetime.now(UTC),
            price=price if price is not None else self.price_of(asset),
        )
