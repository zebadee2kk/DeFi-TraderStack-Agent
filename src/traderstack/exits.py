"""Deterministic position-management exits (issue #58).

Zone C: Settings-driven, no LLM / tool / retrieved text input. Each fired
rule produces a risk-reducing SELL (long) or BUY/cover (short, if the book
ever holds one) that still goes through ``RiskEngine.evaluate``. The kill
switch remains an unconditional halt. Live mode never evaluates these rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from traderstack.candles import interval_to_seconds
from traderstack.config import Settings
from traderstack.models import HeldPosition, Side
from traderstack.strategies import Regime

EXIT_STRATEGY_PREFIX = "exit-"

# Reason strings recorded on the proposal and in the risk audit trail.
# ``strategy_id`` is ``exit-<short>`` (e.g. ``exit-stop_loss``).


class ExitReason(StrEnum):
    STOP_LOSS = "exit_stop_loss"
    TRAILING_STOP = "exit_trailing_stop"
    TAKE_PROFIT = "exit_take_profit"
    TIME_STOP = "exit_time_stop"
    THESIS_INVALIDATED = "exit_thesis_invalidated"


@dataclass(frozen=True)
class ExitSignal:
    reason: ExitReason
    asset: str
    side: Side
    requested_notional_usd: float
    mark_price_usd: float
    entry_price_usd: float


def is_exit_strategy_id(strategy_id: str) -> bool:
    """True for proposals this module authored (``exit-stop_loss``, ...)."""

    return strategy_id.startswith(EXIT_STRATEGY_PREFIX)


def exit_strategy_id(reason: ExitReason) -> str:
    return EXIT_STRATEGY_PREFIX + reason.value.removeprefix("exit_")


def reducing_side(exposure_usd: float) -> Side | None:
    """Side that reduces the observed book. Long-only today (SELL)."""

    if exposure_usd > 0:
        return Side.SELL
    if exposure_usd < 0:
        return Side.BUY
    return None


def bar_seconds_for(settings: Settings, interval: str | None = None) -> float:
    label = interval or settings.effective_pretrade_candle_interval
    return interval_to_seconds(label)


def evaluate_position_exits(
    *,
    settings: Settings,
    asset: str,
    position: HeldPosition,
    mark_price_usd: float,
    now: datetime,
    bar_seconds: float,
    confirmed_side: Side | None = None,
    regime: Regime | None = None,
) -> ExitSignal | None:
    """Return the first fired rule, or None.

    Priority is protective first: stop-loss, trailing stop, take-profit,
    time-stop, then thesis invalidation. Classification uses the held
    position and the mark only -- never thesis text.
    """

    if not settings.position_exits_active:
        return None
    if mark_price_usd <= 0 or position.quantity <= 0:
        return None
    # Size at the live mark so the planner's notional/price conversion
    # cannot invent more quantity than is held.
    exposure = position.quantity * mark_price_usd
    side = reducing_side(exposure)
    if side is None or exposure <= 0:
        return None

    entry = position.average_cost_usd
    if entry <= 0:
        return None

    reason = _first_fired_reason(
        settings=settings,
        position=position,
        mark_price_usd=mark_price_usd,
        entry=entry,
        now=now,
        bar_seconds=bar_seconds,
        confirmed_side=confirmed_side,
        regime=regime,
        side=side,
    )
    if reason is None:
        return None
    return ExitSignal(
        reason=reason,
        asset=asset.upper(),
        side=side,
        requested_notional_usd=exposure,
        mark_price_usd=mark_price_usd,
        entry_price_usd=entry,
    )


def _first_fired_reason(
    *,
    settings: Settings,
    position: HeldPosition,
    mark_price_usd: float,
    entry: float,
    now: datetime,
    bar_seconds: float,
    confirmed_side: Side | None,
    regime: Regime | None,
    side: Side,
) -> ExitReason | None:
    if settings.exit_stop_loss_pct > 0:
        stop = entry * (1.0 - settings.exit_stop_loss_pct)
        if side is Side.SELL and mark_price_usd <= stop:
            return ExitReason.STOP_LOSS
        if side is Side.BUY and mark_price_usd >= entry * (1.0 + settings.exit_stop_loss_pct):
            return ExitReason.STOP_LOSS

    if settings.exit_trailing_stop_pct > 0:
        high_water = max(position.high_water_price_usd, entry, mark_price_usd)
        if side is Side.SELL:
            trail = high_water * (1.0 - settings.exit_trailing_stop_pct)
            # A trailing stop is only meaningful once the high-water is above
            # the entry; otherwise the hard stop-loss is the binding floor.
            if high_water > entry and mark_price_usd <= trail:
                return ExitReason.TRAILING_STOP

    if settings.exit_take_profit_pct > 0:
        target = entry * (1.0 + settings.exit_take_profit_pct)
        if side is Side.SELL and mark_price_usd >= target:
            return ExitReason.TAKE_PROFIT
        if side is Side.BUY and mark_price_usd <= entry * (1.0 - settings.exit_take_profit_pct):
            return ExitReason.TAKE_PROFIT

    if settings.exit_time_stop_bars > 0 and position.opened_at is not None and bar_seconds > 0:
        held_seconds = (now - position.opened_at).total_seconds()
        if held_seconds >= settings.exit_time_stop_bars * bar_seconds:
            return ExitReason.TIME_STOP

    if settings.exit_on_thesis_invalidation:
        if side is Side.SELL and confirmed_side is Side.SELL:
            return ExitReason.THESIS_INVALIDATED
        if side is Side.BUY and confirmed_side is Side.BUY:
            return ExitReason.THESIS_INVALIDATED
        entry_id = (position.entry_strategy_id or "").lower()
        if side is Side.SELL and regime is Regime.TRENDING_DOWN and "momentum" in entry_id:
            return ExitReason.THESIS_INVALIDATED

    return None
