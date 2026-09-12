"""Binance USDT-M all-market liquidation stream (paper-research only).

Connects to ``wss://fstream.binance.com/ws/!forceOrder@arr`` (documented
All-Market Liquidation Order Snapshot Streams) and reduces each force-order
payload to a typed ``LiquidationEvent``. A rolling-window aggregator then
exposes per-asset long/short notional z-scores (clipped to [-5, 5]) and
bounded event counts in [0, 1].

Research/risk context only:
- never an execution venue;
- ``RiskEngine`` does not read these fields to size, side, or authorize a trade;
- a dead or exhausted feed degrades to missing edge features, it does not
  halt the paper-trading cycle.

Reconnect/backoff/staleness follow ``traderstack.market.streaming``, the same
loop as Kraken ticker/book. Application-level stale detection defaults to
**off** (``stale_after_seconds=0``): liquidations are sparse in calm markets,
and websocket pings remain the liveness signal.
"""

from __future__ import annotations

import asyncio
import json
import random
from collections import defaultdict, deque
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from math import sqrt
from typing import Any

import websockets
from prometheus_client import Gauge

from traderstack.market.models import (
    LiquidationEvent,
    LiquidationSide,
    LiquidationWindowSnapshot,
    MarketSource,
)
from traderstack.market.streaming import (
    DEFAULT_BACKOFF_BASE_SECONDS,
    DEFAULT_BACKOFF_MAX_SECONDS,
    DEFAULT_MAX_RECONNECT_ATTEMPTS,
    ConnectFactory,
    SleepFn,
    recv_or_stale,
    stream_with_reconnect,
)
from traderstack.market.symbols import asset_from_futures_symbol

BINANCE_FORCE_ORDER_URL = "wss://fstream.binance.com/ws/!forceOrder@arr"
ZSCORE_CLIP = 5.0

liq_window_notional_usd = Gauge(
    "traderstack_liq_window_notional_usd",
    "Current-window Binance USDT-M liquidation notional (USD), research only",
    ("asset", "side"),
)
liq_window_zscore = Gauge(
    "traderstack_liq_window_zscore",
    "Current-window Binance USDT-M liquidation notional z-score, research only",
    ("asset", "side"),
)


def _as_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _ms_to_datetime(value: object, *, fallback: datetime) -> datetime:
    millis = _as_float(value)
    if millis is None:
        return fallback
    return datetime.fromtimestamp(millis / 1000.0, tz=UTC)


def _unwrap_force_order_rows(message: object) -> list[dict[str, Any]]:
    """Accept the documented single-object payload, an array, or a combined-stream wrapper."""
    if isinstance(message, list):
        return [row for row in message if isinstance(row, dict)]
    if not isinstance(message, dict):
        return []
    if message.get("e") == "forceOrder":
        return [message]
    data = message.get("data")
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if isinstance(data, dict) and data.get("e") == "forceOrder":
        return [data]
    return []


def parse_force_order_message(
    message: object,
    *,
    assets: tuple[str, ...] | None = None,
    quote: str = "USDT",
    now: datetime | None = None,
) -> list[LiquidationEvent]:
    """Pure: reduce one recorded ``!forceOrder@arr`` payload to typed events.

    Untrusted extra fields are dropped. A ``SELL`` force order is a long
    liquidation; a ``BUY`` force order is a short liquidation.
    """
    observed = now or datetime.now(UTC)
    allow = {a.upper() for a in assets} if assets else None
    events: list[LiquidationEvent] = []
    for row in _unwrap_force_order_rows(message):
        order = row.get("o")
        if not isinstance(order, dict):
            continue
        symbol = order.get("s")
        side_raw = order.get("S")
        if not isinstance(symbol, str) or not isinstance(side_raw, str):
            continue
        asset = asset_from_futures_symbol(symbol, quote)
        if asset is None:
            continue
        if allow is not None and asset not in allow:
            continue
        if side_raw.upper() == "SELL":
            side = LiquidationSide.LONG
        elif side_raw.upper() == "BUY":
            side = LiquidationSide.SHORT
        else:
            continue
        qty = _as_float(order.get("z")) or _as_float(order.get("q"))
        price = _as_float(order.get("ap")) or _as_float(order.get("p"))
        if qty is None or price is None or qty <= 0 or price <= 0:
            continue
        events.append(
            LiquidationEvent(
                source=MarketSource.BINANCE,
                symbol=symbol.upper(),
                asset=asset,
                observed_at=_ms_to_datetime(row.get("E") or order.get("T"), fallback=observed),
                side=side,
                qty=qty,
                price=price,
                notional=qty * price,
            )
        )
    return events


def _clip_z(value: float) -> float:
    return max(-ZSCORE_CLIP, min(ZSCORE_CLIP, value))


def _zscore(current: float, history: list[float]) -> float | None:
    if len(history) < 2:
        return None
    mean = sum(history) / len(history)
    variance = sum((item - mean) ** 2 for item in history) / (len(history) - 1)
    std = sqrt(variance)
    if std == 0:
        return 0.0
    return _clip_z((current - mean) / std)


@dataclass
class _SideBuckets:
    """Non-overlapping window totals used as the z-score baseline."""

    buckets: deque[tuple[datetime, float]] = field(default_factory=deque)
    current_start: datetime | None = None
    current_sum: float = 0.0
    current_count: int = 0

    def add(self, observed_at: datetime, notional: float, window: timedelta) -> None:
        bucket_start = _align(observed_at, window)
        if self.current_start is None:
            self.current_start = bucket_start
        elif bucket_start != self.current_start:
            self.buckets.append((self.current_start, self.current_sum))
            self.current_start = bucket_start
            self.current_sum = 0.0
            self.current_count = 0
        self.current_sum += notional
        self.current_count += 1

    def prune(self, cutoff: datetime) -> None:
        while self.buckets and self.buckets[0][0] < cutoff:
            self.buckets.popleft()

    def zscore(self) -> float | None:
        return _zscore(self.current_sum, [total for _, total in self.buckets])


def _align(moment: datetime, window: timedelta) -> datetime:
    seconds = int(window.total_seconds()) or 1
    epoch = int(moment.timestamp())
    aligned = epoch - (epoch % seconds)
    return datetime.fromtimestamp(aligned, tz=UTC)


@dataclass
class LiquidationAggregator:
    """Rolling-window long/short liquidation notionals and bounded counts."""

    window_seconds: float = 60.0
    baseline_seconds: float = 900.0
    count_cap: int = 20
    _sides: dict[str, dict[LiquidationSide, _SideBuckets]] = field(
        init=False, default_factory=lambda: defaultdict(lambda: defaultdict(_SideBuckets))
    )
    _last_event_at: dict[str, datetime] = field(init=False, default_factory=dict)

    @property
    def has_events(self) -> bool:
        return bool(self._last_event_at)

    def ingest(self, event: LiquidationEvent) -> None:
        window = timedelta(seconds=self.window_seconds)
        buckets = self._sides[event.asset.upper()][event.side]
        buckets.add(event.observed_at, event.notional, window)
        buckets.prune(event.observed_at - timedelta(seconds=self.baseline_seconds))
        self._last_event_at[event.asset.upper()] = event.observed_at

    def snapshot(self, asset: str, *, now: datetime | None = None) -> LiquidationWindowSnapshot:
        moment = now or datetime.now(UTC)
        key = asset.upper()
        sides = self._sides.get(key, {})
        long_side = sides.get(LiquidationSide.LONG, _SideBuckets())
        short_side = sides.get(LiquidationSide.SHORT, _SideBuckets())
        # If the current bucket started more than one window ago, treat it as
        # closed history and report a zero current window.
        long_sum, long_count = self._current(long_side, moment)
        short_sum, short_count = self._current(short_side, moment)
        cap = max(1, self.count_cap)
        observed = self._last_event_at.get(key, moment)
        return LiquidationWindowSnapshot(
            asset=key,
            observed_at=observed,
            source_id="binance_liq",
            liq_notional_long_z=long_side.zscore() if long_sum or long_side.buckets else None,
            liq_notional_short_z=short_side.zscore() if short_sum or short_side.buckets else None,
            liq_count_long=min(long_count, cap) / cap,
            liq_count_short=min(short_count, cap) / cap,
            long_notional=long_sum,
            short_notional=short_sum,
        )

    def _current(self, side: _SideBuckets, now: datetime) -> tuple[float, int]:
        if side.current_start is None:
            return (0.0, 0)
        window = timedelta(seconds=self.window_seconds)
        if now - side.current_start >= window:
            # The in-progress bucket has aged out of the live window; it is
            # already (or should be) baseline history. Report a quiet window.
            if side.current_sum > 0:
                side.buckets.append((side.current_start, side.current_sum))
                side.prune(now - timedelta(seconds=self.baseline_seconds))
            side.current_start = None
            side.current_sum = 0.0
            side.current_count = 0
            return (0.0, 0)
        return (side.current_sum, side.current_count)


@dataclass
class BinanceForceOrderProvider:
    """Streaming collector + snapshot reader for Binance USDT-M force orders."""

    url: str = BINANCE_FORCE_ORDER_URL
    assets: tuple[str, ...] = ()
    quote: str = "USDT"
    window_seconds: float = 60.0
    baseline_seconds: float = 900.0
    count_cap: int = 20
    max_age_seconds: float = 0.0
    connect: ConnectFactory = field(default=websockets.connect)
    max_reconnect_attempts: int = DEFAULT_MAX_RECONNECT_ATTEMPTS
    backoff_base_seconds: float = DEFAULT_BACKOFF_BASE_SECONDS
    backoff_max_seconds: float = DEFAULT_BACKOFF_MAX_SECONDS
    stale_after_seconds: float = 0.0
    sleep: SleepFn = field(default=asyncio.sleep)
    random_jitter: Callable[[], float] = field(default=random.random)
    aggregator: LiquidationAggregator = field(init=False, default_factory=LiquidationAggregator)
    feed_name: str = "binance_force_order"
    _last_message_at: datetime | None = field(init=False, default=None)

    def __post_init__(self) -> None:
        self.aggregator = LiquidationAggregator(
            window_seconds=self.window_seconds,
            baseline_seconds=self.baseline_seconds,
            count_cap=self.count_cap,
        )

    async def stream_events(self) -> AsyncIterator[LiquidationEvent]:
        async for event in stream_with_reconnect(
            self._stream_once,
            feed_name=self.feed_name,
            max_reconnect_attempts=self.max_reconnect_attempts,
            backoff_base_seconds=self.backoff_base_seconds,
            backoff_max_seconds=self.backoff_max_seconds,
            sleep=self.sleep,
            random_jitter=self.random_jitter,
        ):
            yield event

    async def _stream_once(self) -> AsyncIterator[LiquidationEvent]:
        async with self.connect(self.url, ping_interval=20, ping_timeout=20) as ws:
            while True:
                raw = await recv_or_stale(
                    ws,
                    stale_after_seconds=self.stale_after_seconds,
                    feed_name=self.feed_name,
                )
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                events = parse_force_order_message(payload, assets=self.assets, quote=self.quote)
                if not events:
                    continue
                self._last_message_at = datetime.now(UTC)
                for event in events:
                    yield event

    async def collect(self) -> None:
        """Background loop: ingest every event into the rolling aggregator."""
        async for event in self.stream_events():
            self.aggregator.ingest(event)

    def snapshot(self, asset: str, *, now: datetime | None = None) -> LiquidationWindowSnapshot | None:
        moment = now or datetime.now(UTC)
        if self._last_message_at is None and not self.aggregator.has_events:
            return None
        if self.max_age_seconds > 0 and self._last_message_at is not None:
            age = (moment - self._last_message_at).total_seconds()
            if age > self.max_age_seconds:
                return None
        snap = self.aggregator.snapshot(asset, now=moment)
        if snap.liq_notional_long_z is not None:
            liq_window_zscore.labels(asset=snap.asset, side="long").set(snap.liq_notional_long_z)
        if snap.liq_notional_short_z is not None:
            liq_window_zscore.labels(asset=snap.asset, side="short").set(snap.liq_notional_short_z)
        liq_window_notional_usd.labels(asset=snap.asset, side="long").set(snap.long_notional)
        liq_window_notional_usd.labels(asset=snap.asset, side="short").set(snap.short_notional)
        return snap
