"""Fee and slippage models for the research backtester.

`BaselineBacktester` (and the baseline strategies in `research.baselines`) delegate the
cost of every fill to a `CostModel`. `FlatCostModel` reproduces the historical flat
fee-plus-slippage behaviour; `VolumeAwareSlippageModel` scales slippage with how large
the order is relative to the bar's traded volume, capped at a maximum.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from traderstack.candles import Candle


@runtime_checkable
class CostModel(Protocol):
    """Computes the round-trip-leg cost (in basis points) of filling one order."""

    def cost_bps(self, candle: Candle, notional_usd: float) -> float:
        """Return the total cost, in basis points of notional, for a single fill.

        `candle` is the bar the fill occurs on (its `close`/`volume` describe the
        liquidity available); `notional_usd` is the dollar size of the order.
        """
        ...


@dataclass(frozen=True)
class FlatCostModel:
    """Fixed fee + slippage in basis points, independent of order size or liquidity.

    This reproduces the backtester's original behaviour and is the default cost model.
    """

    fee_bps: float = 10.0
    slippage_bps: float = 5.0

    def cost_bps(self, candle: Candle, notional_usd: float) -> float:
        return self.fee_bps + self.slippage_bps


@dataclass(frozen=True)
class VolumeAwareSlippageModel:
    """Slippage grows with the order's participation in the bar's traded volume.

    `participation` is the order notional divided by the bar's dollar volume
    (`close * volume`). Slippage is `base_slippage_bps + participation *
    participation_sensitivity_bps`, capped at `max_slippage_bps`. A larger order
    relative to available liquidity always pays at least as much as a smaller one.
    """

    fee_bps: float = 10.0
    base_slippage_bps: float = 5.0
    participation_sensitivity_bps: float = 200.0
    max_slippage_bps: float = 250.0

    def cost_bps(self, candle: Candle, notional_usd: float) -> float:
        bar_notional = candle.close * candle.volume
        participation = notional_usd / bar_notional if bar_notional > 0 else 1.0
        slippage = self.base_slippage_bps + participation * self.participation_sensitivity_bps
        slippage = min(max(slippage, 0.0), self.max_slippage_bps)
        return self.fee_bps + slippage
