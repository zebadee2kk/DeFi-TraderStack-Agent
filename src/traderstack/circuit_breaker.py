"""Strategy circuit breaker (Epic 7, control-hierarchy layer 3).

Tracks realized outcomes per strategy and suspends a strategy that is losing.
Suspension is deterministic: it is derived from recorded closed-trade PnL and
version-controlled thresholds only. Nothing here accepts a limit, an override or
a reset instruction from a runtime message -- an LLM cannot talk a tripped
strategy back into production. The only ways out are the configured cool-down
elapsing or an operator editing configuration and restarting.

Outcomes reach the breaker from two deterministic sources:

* ``record_ledger_close`` -- a closing (reducing) order that filled on the
  ``ExecutionLedger``, priced against the position's entry cost.
* ``PortfolioRealizedPnLFeeder`` -- the delta of ``InMemoryPortfolioBook``'s
  realized PnL between two observations.

State is a plain pydantic model so it can be persisted verbatim inside the
portfolio checkpoint JSON.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

from pydantic import BaseModel, Field

from traderstack.config import Settings
from traderstack.execution.ledger import ExecutionOrder, OrderLifecycleState
from traderstack.models import Side


class RealizedPnLSource(Protocol):
    """The slice of ``InMemoryPortfolioBook`` the feeder reads.

    Declared structurally so this module stays free of a portfolio import --
    ``traderstack.portfolio`` imports ``StrategyBreakerState`` from here to
    persist breaker state inside the checkpoint.
    """

    @property
    def realized_pnl_usd(self) -> float: ...

    @property
    def nav_usd(self) -> float: ...

TRIP_CONSECUTIVE_LOSSES = "consecutive_losses"
TRIP_ROLLING_DRAWDOWN = "rolling_drawdown"


class ClosedTrade(BaseModel):
    """One realized outcome for a strategy, normalised by NAV at the time."""

    pnl_usd: float
    nav_usd: float = Field(gt=0)
    closed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def pnl_fraction(self) -> float:
        return self.pnl_usd / self.nav_usd


class StrategyBreakerState(BaseModel):
    """Persisted per-strategy breaker state."""

    consecutive_losses: int = Field(default=0, ge=0)
    closed_trades: list[ClosedTrade] = Field(default_factory=list)
    tripped_at: datetime | None = None
    trip_reason: str | None = None

    @property
    def tripped(self) -> bool:
        return self.tripped_at is not None


def rolling_drawdown(trades: list[ClosedTrade]) -> float:
    """Max peak-to-trough decline of the cumulative NAV-normalised PnL curve.

    Returned as a positive fraction of NAV (0.04 == a 4% peak-to-trough dent).
    """

    cumulative = 0.0
    peak = 0.0
    worst = 0.0
    for trade in trades:
        cumulative += trade.pnl_fraction
        peak = max(peak, cumulative)
        worst = max(worst, peak - cumulative)
    return worst


@dataclass
class StrategyCircuitBreaker:
    """Deterministic per-strategy suspension on realized underperformance."""

    max_consecutive_losses: int = 3
    drawdown_window: int = 10
    max_rolling_drawdown_pct: float = 0.05
    cooldown_seconds: float = 3_600.0
    states: dict[str, StrategyBreakerState] = field(default_factory=dict)

    @classmethod
    def from_settings(cls, settings: Settings) -> StrategyCircuitBreaker:
        return cls(
            max_consecutive_losses=int(settings.strategy_max_consecutive_losses),
            drawdown_window=int(settings.strategy_drawdown_window),
            max_rolling_drawdown_pct=float(settings.strategy_max_rolling_drawdown_pct),
            cooldown_seconds=float(settings.strategy_breaker_cooldown_seconds),
        )

    # --- persistence ---------------------------------------------------

    def export(self) -> dict[str, StrategyBreakerState]:
        return {name: state.model_copy(deep=True) for name, state in self.states.items()}

    def load(self, states: dict[str, StrategyBreakerState]) -> None:
        self.states = {name: state.model_copy(deep=True) for name, state in states.items()}

    # --- observation ---------------------------------------------------

    def state_for(self, strategy_id: str) -> StrategyBreakerState:
        return self.states.setdefault(strategy_id, StrategyBreakerState())

    def record_closed_trade(
        self,
        strategy_id: str,
        *,
        pnl_usd: float,
        nav_usd: float,
        at: datetime | None = None,
    ) -> StrategyBreakerState:
        """Record one realized outcome and trip the breaker if it breaches policy."""

        if nav_usd <= 0:
            raise ValueError("nav_usd must be positive to normalise a closed trade")
        moment = at or datetime.now(UTC)
        state = self.state_for(strategy_id)
        state.closed_trades.append(
            ClosedTrade(pnl_usd=pnl_usd, nav_usd=nav_usd, closed_at=moment)
        )
        if len(state.closed_trades) > self.drawdown_window:
            del state.closed_trades[: -self.drawdown_window]

        if pnl_usd < 0:
            state.consecutive_losses += 1
        else:
            state.consecutive_losses = 0

        if state.tripped:
            return state
        if state.consecutive_losses >= self.max_consecutive_losses:
            state.tripped_at = moment
            state.trip_reason = TRIP_CONSECUTIVE_LOSSES
        elif rolling_drawdown(state.closed_trades) >= self.max_rolling_drawdown_pct:
            state.tripped_at = moment
            state.trip_reason = TRIP_ROLLING_DRAWDOWN
        return state

    def record_ledger_close(
        self,
        order: ExecutionOrder,
        *,
        strategy_id: str,
        entry_price_usd: float,
        nav_usd: float,
        at: datetime | None = None,
    ) -> StrategyBreakerState | None:
        """Record the outcome of a filled reducing order from the execution ledger.

        Only a filled SELL (a position close/reduce) realizes PnL, so anything
        else is ignored rather than guessed at.
        """

        if order.side is not Side.SELL:
            return None
        if order.state not in {OrderLifecycleState.FILLED, OrderLifecycleState.PARTIALLY_FILLED}:
            return None
        if order.average_fill_price_usd is None or order.filled_quantity <= 0:
            return None
        if entry_price_usd <= 0:
            raise ValueError("entry_price_usd must be positive")
        pnl = (order.average_fill_price_usd - entry_price_usd) * order.filled_quantity
        return self.record_closed_trade(
            strategy_id, pnl_usd=pnl, nav_usd=nav_usd, at=at or order.last_updated_at
        )

    # --- enforcement ---------------------------------------------------

    def is_tripped(self, strategy_id: str, now: datetime | None = None) -> bool:
        """True while the strategy is suspended. Clears itself once cool-down elapses."""

        state = self.states.get(strategy_id)
        if state is None or state.tripped_at is None:
            return False
        moment = now or datetime.now(UTC)
        if (moment - state.tripped_at).total_seconds() >= self.cooldown_seconds:
            self.reset(strategy_id)
            return False
        return True

    def reset(self, strategy_id: str) -> None:
        """Clear a strategy's breaker after its cool-down (or on operator restart)."""

        state = self.states.get(strategy_id)
        if state is None:
            return
        state.tripped_at = None
        state.trip_reason = None
        state.consecutive_losses = 0
        state.closed_trades = []


@dataclass
class PortfolioRealizedPnLFeeder:
    """Turns ``InMemoryPortfolioBook`` realized-PnL movement into closed trades.

    The book records realized PnL globally, so the caller supplies the strategy
    that owned the closing fill. Each ``observe`` records the delta since the
    previous observation and ignores a zero delta.
    """

    breaker: StrategyCircuitBreaker
    last_realized_pnl_usd: float = 0.0

    def observe(
        self, strategy_id: str, book: RealizedPnLSource, at: datetime | None = None
    ) -> bool:
        realized = float(book.realized_pnl_usd)
        nav = float(book.nav_usd)
        delta = realized - self.last_realized_pnl_usd
        self.last_realized_pnl_usd = realized
        if delta == 0.0 or nav <= 0:
            return False
        self.breaker.record_closed_trade(strategy_id, pnl_usd=delta, nav_usd=nav, at=at)
        return True
