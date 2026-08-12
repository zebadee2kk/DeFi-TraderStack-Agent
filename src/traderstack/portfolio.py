from dataclasses import dataclass, field
from datetime import UTC, datetime

from pydantic import BaseModel, Field

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
    daily_anchor_date: str | None = None
    daily_anchor_nav_usd: float | None = Field(default=None, gt=0)


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
    daily_anchor_date: str | None = None
    daily_anchor_nav_usd: float | None = None

    def __post_init__(self) -> None:
        if self.starting_nav_usd <= 0:
            raise ValueError("starting_nav_usd must be positive")
        if self.cash_usd is None:
            self.cash_usd = self.starting_nav_usd
        if self.peak_nav_usd is None:
            self.peak_nav_usd = self.starting_nav_usd
        if self.daily_anchor_date is None:
            self.daily_anchor_date = datetime.now(UTC).date().isoformat()
        if self.daily_anchor_nav_usd is None:
            self.daily_anchor_nav_usd = self.nav_usd

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
            daily_anchor_date=state.daily_anchor_date,
            daily_anchor_nav_usd=state.daily_anchor_nav_usd,
        )

    def state(self) -> PortfolioState:
        assert self.cash_usd is not None
        assert self.peak_nav_usd is not None
        return PortfolioState(
            starting_nav_usd=self.starting_nav_usd,
            cash_usd=self.cash_usd,
            peak_nav_usd=self.peak_nav_usd,
            realized_pnl_usd=self.realized_pnl_usd,
            daily_anchor_date=self.daily_anchor_date,
            daily_anchor_nav_usd=self.daily_anchor_nav_usd,
            positions={
                asset: PositionState(
                    quantity=position.quantity,
                    average_cost_usd=position.average_cost_usd,
                )
                for asset, position in self.positions.items()
            },
            marks_usd=self.marks_usd.copy(),
        )

    def mark(self, asset: str, price_usd: float) -> None:
        if price_usd <= 0:
            raise ValueError("mark price must be positive")
        self.marks_usd[asset.upper()] = price_usd
        # The drawdown breaker measures against the rolling peak, so every
        # NAV move — not just fills — must ratchet it.
        if self.peak_nav_usd is not None:
            self.peak_nav_usd = max(self.peak_nav_usd, self.nav_usd)

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
            if position.quantity <= 0:
                raise ValueError("cannot sell more than current paper position")
            # Sell intents are sized in notional at the last mark but execute
            # at the live price, so a venue fill can slightly exceed the book
            # position. Clamp the excess instead of dropping the whole fill;
            # NAV reconciliation surfaces any real venue/book drift.
            quantity = min(quantity, position.quantity)
            notional = quantity * price_usd
            self.cash_usd += notional
            self.realized_pnl_usd += quantity * (price_usd - position.average_cost_usd)
            position.quantity -= quantity
            if position.quantity == 0:
                position.average_cost_usd = 0.0

        self.mark(asset, price_usd)

    @property
    def nav_usd(self) -> float:
        assert self.cash_usd is not None
        position_value = 0.0
        for asset, position in self.positions.items():
            mark = self.marks_usd.get(asset, position.average_cost_usd)
            position_value += position.quantity * mark
        return self.cash_usd + position_value

    def roll_daily_anchor(self) -> None:
        """Reset the daily PnL anchor when the UTC calendar day changes."""
        today = datetime.now(UTC).date().isoformat()
        if self.daily_anchor_date != today:
            self.daily_anchor_date = today
            self.daily_anchor_nav_usd = self.nav_usd

    def snapshot(self) -> PortfolioSnapshot:
        assert self.cash_usd is not None
        assert self.peak_nav_usd is not None
        self.roll_daily_anchor()
        anchor_nav = self.daily_anchor_nav_usd if self.daily_anchor_nav_usd else self.nav_usd
        exposures = {
            asset: position.quantity * self.marks_usd.get(asset, position.average_cost_usd)
            for asset, position in self.positions.items()
            if position.quantity > 0
        }
        return PortfolioSnapshot(
            nav_usd=self.nav_usd,
            cash_usd=self.cash_usd,
            daily_pnl_usd=self.nav_usd - anchor_nav,
            peak_nav_usd=self.peak_nav_usd,
            asset_exposure_usd=exposures,
        )
