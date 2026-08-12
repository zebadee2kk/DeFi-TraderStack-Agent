from dataclasses import dataclass, field
from datetime import UTC, datetime

from prometheus_client import Counter, Gauge

cycles_total = Counter(
    "traderstack_cycles_total",
    "Completed runtime symbol cycles",
    ("symbol", "outcome"),
)
last_success_unixtime = Gauge(
    "traderstack_last_success_unixtime",
    "Unix timestamp of the last successful symbol cycle",
    ("symbol",),
)
runtime_healthy = Gauge(
    "traderstack_runtime_healthy",
    "Runtime health flag: 1 healthy, 0 unhealthy",
)


@dataclass
class RuntimeHealth:
    max_consecutive_errors: int = 5
    consecutive_errors: int = 0
    last_success_at: datetime | None = None
    last_error_at: datetime | None = None
    last_error: str | None = None
    symbol_success_at: dict[str, datetime] = field(default_factory=dict)
    symbol_consecutive_errors: dict[str, int] = field(default_factory=dict)

    @property
    def healthy(self) -> bool:
        # A success on one symbol must not mask another symbol failing every
        # cycle, so the threshold applies globally AND per symbol.
        if self.consecutive_errors >= self.max_consecutive_errors:
            return False
        return all(
            count < self.max_consecutive_errors
            for count in self.symbol_consecutive_errors.values()
        )

    def record_success(self, symbol: str) -> None:
        now = datetime.now(UTC)
        self.consecutive_errors = 0
        self.last_success_at = now
        self.symbol_success_at[symbol] = now
        self.symbol_consecutive_errors[symbol] = 0
        cycles_total.labels(symbol=symbol, outcome="success").inc()
        last_success_unixtime.labels(symbol=symbol).set(now.timestamp())
        runtime_healthy.set(1 if self.healthy else 0)

    def record_error(self, symbol: str, error: BaseException) -> None:
        self.consecutive_errors += 1
        self.symbol_consecutive_errors[symbol] = self.symbol_consecutive_errors.get(symbol, 0) + 1
        self.last_error_at = datetime.now(UTC)
        self.last_error = f"{type(error).__name__}: {error}"
        cycles_total.labels(symbol=symbol, outcome="error").inc()
        runtime_healthy.set(1 if self.healthy else 0)
