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
