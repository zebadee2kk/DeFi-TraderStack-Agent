from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import UTC, datetime

from pydantic import BaseModel, Field, model_validator


class Candle(BaseModel):
    symbol: str
    interval: str
    opened_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    open: float = Field(gt=0)
    high: float = Field(gt=0)
    low: float = Field(gt=0)
    close: float = Field(gt=0)
    volume: float = Field(ge=0)

    @model_validator(mode="after")
    def validate_ohlc(self) -> "Candle":
        if self.high < max(self.open, self.close) or self.low > min(self.open, self.close):
            raise ValueError("candle high/low must contain open and close")
        if self.high < self.low:
            raise ValueError("candle high cannot be below low")
        return self


@dataclass
class CandleHistory:
    maxlen: int = 500
    _candles: dict[tuple[str, str], deque[Candle]] = field(
        default_factory=lambda: defaultdict(deque)
    )

    def append(self, candle: Candle) -> None:
        key = (candle.symbol.upper(), candle.interval)
        bucket = self._candles[key]
        if bucket and candle.opened_at <= bucket[-1].opened_at:
            raise ValueError("candles must be appended in strictly increasing time order")
        bucket.append(candle)
        while len(bucket) > self.maxlen:
            bucket.popleft()

    def get(self, symbol: str, interval: str, limit: int | None = None) -> tuple[Candle, ...]:
        values = tuple(self._candles.get((symbol.upper(), interval), ()))
        return values[-limit:] if limit is not None else values


_INTERVAL_UNIT_SECONDS: dict[str, int] = {
    "s": 1,
    "m": 60,
    "h": 3600,
    "d": 86400,
    "w": 604_800,
}


def interval_to_seconds(interval: str) -> float:
    """Parse a candle interval label (e.g. ``"1m"``, ``"15m"``, ``"4h"``, ``"1d"``) to seconds."""
    text = interval.strip().lower()
    if not text:
        raise ValueError("interval must not be empty")
    digits = ""
    unit = ""
    for char in text:
        if char.isdigit():
            digits += char
        else:
            unit += char
    if not unit or unit not in _INTERVAL_UNIT_SECONDS:
        raise ValueError(f"unsupported candle interval '{interval}'")
    magnitude = int(digits) if digits else 1
    if magnitude <= 0:
        raise ValueError(f"candle interval '{interval}' must have a positive magnitude")
    return float(magnitude * _INTERVAL_UNIT_SECONDS[unit])


def periods_per_year(interval: str) -> float:
    """Infer the number of bars per (365-day) year implied by a candle interval label."""
    return (365.0 * 86_400.0) / interval_to_seconds(interval)
