from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from pydantic import BaseModel, Field

# --- risk plane (Epic 7) ---
from traderstack.circuit_breaker import StrategyBreakerState
from traderstack.models import PortfolioSnapshot, Side


class PositionState(BaseModel):
    quantity: float = Field(ge=0)
    average_cost_usd: float = Field(ge=0)


class PortfolioState(BaseModel):
    starting_nav_usd: float = Field(gt=0)
    cash_usd: float
    peak_nav_usd: float = Field(gt=0)
    realized_pnl_usd: float = 0.0
    positions: dict[str, PositionState] = Field(default_factory=dict)
    marks_usd: dict[str, float] = Field(default_factory=dict)
    # --- risk plane (Epic 7) ---
    # Persisted daily anchor so MAX_DAILY_LOSS_PCT means "today", not "since
    # inception". Rolls at UTC midnight. None on checkpoints written before
    # Epic 7; resolved to the current NAV/date on load.
    day_start_nav_usd: float | None = Field(default=None, gt=0)
    day_start_date: date | None = None
    # Per-strategy circuit-breaker state, persisted alongside the book so a
    # tripped strategy stays tripped across a restart.
    strategy_breakers: dict[str, StrategyBreakerState] = Field(default_factory=dict)


@dataclass
class Position:
    quantity: float = 0.0
    average_cost_usd: float = 0.0


@dataclass
class InMemoryPortfolioBook:
    starting_nav_usd: float
    cash_usd: float | None = None
    peak_nav_usd: float | None = None
    realized_pnl_usd: float = 0.0
    positions: dict[str, Position] = field(default_factory=dict)
    marks_usd: dict[str, float] = field(default_factory=dict)
    # --- risk plane (Epic 7) ---
    day_start_nav_usd: float | None = None
    day_start_date: date | None = None

    def __post_init__(self) -> None:
        if self.starting_nav_usd <= 0:
            raise ValueError("starting_nav_usd must be positive")
        if self.cash_usd is None:
            self.cash_usd = self.starting_nav_usd
        if self.peak_nav_usd is None:
            self.peak_nav_usd = self.starting_nav_usd
        # --- risk plane (Epic 7) ---
        # A book with no anchor opens the day at its current NAV. The date is
        # deliberately left unset: the first observation stamps it, so the
        # anchor is never mis-dated by whatever wall clock built the object.
        if self.day_start_nav_usd is None:
            self.day_start_nav_usd = self.nav_usd

    @classmethod
    def from_state(cls, state: PortfolioState) -> "InMemoryPortfolioBook":
        return cls(
            starting_nav_usd=state.starting_nav_usd,
            cash_usd=state.cash_usd,
            peak_nav_usd=state.peak_nav_usd,
            realized_pnl_usd=state.realized_pnl_usd,
            positions={
                asset.upper(): Position(
                    quantity=position.quantity,
                    average_cost_usd=position.average_cost_usd,
                )
                for asset, position in state.positions.items()
            },
            marks_usd={asset.upper(): price for asset, price in state.marks_usd.items()},
            # --- risk plane (Epic 7) ---
            day_start_nav_usd=state.day_start_nav_usd,
            day_start_date=state.day_start_date,
        )

    def state(self) -> PortfolioState:
        assert self.cash_usd is not None
        assert self.peak_nav_usd is not None
        return PortfolioState(
            starting_nav_usd=self.starting_nav_usd,
            cash_usd=self.cash_usd,
            peak_nav_usd=self.peak_nav_usd,
            realized_pnl_usd=self.realized_pnl_usd,
            positions={
                asset: PositionState(
                    quantity=position.quantity,
                    average_cost_usd=position.average_cost_usd,
                )
                for asset, position in self.positions.items()
            },
            marks_usd=self.marks_usd.copy(),
            # --- risk plane (Epic 7) ---
            day_start_nav_usd=self.day_start_nav_usd,
            day_start_date=self.day_start_date,
        )

    def mark(self, asset: str, price_usd: float) -> None:
        if price_usd <= 0:
            raise ValueError("mark price must be positive")
        self.marks_usd[asset.upper()] = price_usd

    def apply_fill(self, asset: str, side: Side, quantity: float, price_usd: float) -> None:
        if quantity <= 0 or price_usd <= 0:
            raise ValueError("fill quantity and price must be positive")
        asset = asset.upper()
        position = self.positions.setdefault(asset, Position())
        notional = quantity * price_usd
        assert self.cash_usd is not None

        if side is Side.BUY:
            new_quantity = position.quantity + quantity
            if new_quantity <= 0:
                raise ValueError("invalid resulting position quantity")
            position.average_cost_usd = (
                (position.quantity * position.average_cost_usd) + notional
            ) / new_quantity
            position.quantity = new_quantity
            self.cash_usd -= notional
        else:
            if quantity > position.quantity:
                raise ValueError("cannot sell more than current paper position")
            self.cash_usd += notional
            self.realized_pnl_usd += quantity * (price_usd - position.average_cost_usd)
            position.quantity -= quantity
            if position.quantity == 0:
                position.average_cost_usd = 0.0

        self.mark(asset, price_usd)
        nav = self.nav_usd
        assert self.peak_nav_usd is not None
        self.peak_nav_usd = max(self.peak_nav_usd, nav)

    @property
    def nav_usd(self) -> float:
        assert self.cash_usd is not None
        position_value = 0.0
        for asset, position in self.positions.items():
            mark = self.marks_usd.get(asset, position.average_cost_usd)
            position_value += position.quantity * mark
        return self.cash_usd + position_value

    # --- risk plane (Epic 7) ---
    def roll_day(self, now: datetime | None = None) -> bool:
        """Re-anchor the daily PnL baseline if the UTC day has changed.

        Returns True when a rollover happened. Called from ``snapshot`` so the
        anchor advances on the first observation of each new UTC day.
        """

        moment = now or datetime.now(UTC)
        today = moment.astimezone(UTC).date()
        if self.day_start_date is None:
            # First observation of an un-dated book: adopt the date and keep the
            # existing anchor. Not a rollover.
            self.day_start_date = today
            if self.day_start_nav_usd is None:
                self.day_start_nav_usd = self.nav_usd
            return False
        if self.day_start_date == today and self.day_start_nav_usd is not None:
            return False
        self.day_start_date = today
        self.day_start_nav_usd = self.nav_usd
        return True

    @property
    def daily_pnl_usd(self) -> float:
        anchor = self.day_start_nav_usd
        if anchor is None:
            anchor = self.nav_usd
        return self.nav_usd - anchor

    def snapshot(self, now: datetime | None = None) -> PortfolioSnapshot:
        assert self.cash_usd is not None
        assert self.peak_nav_usd is not None
        # --- risk plane (Epic 7) ---
        moment = now or datetime.now(UTC)
        self.roll_day(moment)
        exposures = {
            asset: position.quantity * self.marks_usd.get(asset, position.average_cost_usd)
            for asset, position in self.positions.items()
            if position.quantity > 0
        }
        return PortfolioSnapshot(
            nav_usd=self.nav_usd,
            cash_usd=max(0.0, self.cash_usd),
            # Daily, not lifetime: measured against the UTC-midnight anchor.
            daily_pnl_usd=self.daily_pnl_usd,
            peak_nav_usd=self.peak_nav_usd,
            asset_exposure_usd=exposures,
            observed_at=moment,
        )
