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
# --- execution hardening (Epic 8) ---
reconciliation_blocked = Gauge(
    "traderstack_reconciliation_blocked",
    "Submission block flag: 1 when venue state is unreconciled or drifting, 0 otherwise",
)


@dataclass
class RuntimeHealth:
    max_consecutive_errors: int = 5
    consecutive_errors: int = 0
    last_success_at: datetime | None = None
    last_error_at: datetime | None = None
    last_error: str | None = None
    symbol_success_at: dict[str, datetime] = field(default_factory=dict)
    # --- execution hardening (Epic 8) ---
    # Set when a reconciliation pass fails or NAV drifts beyond threshold. It
    # blocks *new risk* only: data collection, decisions and auditing continue,
    # and existing positions are untouched. Cleared by the next good pass.
    reconciliation_blocked: bool = False
    last_reconciliation_at: datetime | None = None
    last_reconciliation_error: str | None = None

    @property
    def healthy(self) -> bool:
        return self.consecutive_errors < self.max_consecutive_errors

    # --- execution hardening (Epic 8) ---
    def record_reconciliation_success(self) -> None:
        self.reconciliation_blocked = False
        self.last_reconciliation_at = datetime.now(UTC)
        self.last_reconciliation_error = None
        reconciliation_blocked.set(0)

    def record_reconciliation_failure(self, reason: str) -> None:
        self.reconciliation_blocked = True
        self.last_reconciliation_error = reason
        reconciliation_blocked.set(1)

    def record_success(self, symbol: str) -> None:
        now = datetime.now(UTC)
        self.consecutive_errors = 0
        self.last_success_at = now
        self.symbol_success_at[symbol] = now
        cycles_total.labels(symbol=symbol, outcome="success").inc()
        last_success_unixtime.labels(symbol=symbol).set(now.timestamp())
        runtime_healthy.set(1)

    def record_error(self, symbol: str, error: BaseException) -> None:
        self.consecutive_errors += 1
        self.last_error_at = datetime.now(UTC)
        self.last_error = f"{type(error).__name__}: {error}"
        cycles_total.labels(symbol=symbol, outcome="error").inc()
        runtime_healthy.set(1 if self.healthy else 0)
