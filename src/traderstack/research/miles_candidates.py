"""Miles-inspired direction + GARCH-sizing candidates for strategy search.

Direction is an EMA crossover (9/21 or 12/26), optionally gated by ADX so
low-ADX chop is skipped. GARCH is composed *only* as a size overlay:
``weight *= clip(target_vol / forecast_vol, 0.25, 2.0)``. GARCH never
chooses a side.

These are standalone voters. Search scores them under fees. The only
runtime registration path is ``PAPER_PROMOTE_EMA_9_21`` (paper only),
which wires ``ema_9_21`` and nothing else.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from traderstack.candles import Candle
from traderstack.garch import GarchForecast
from traderstack.indicators import average_directional_index, ema
from traderstack.models import Side
from traderstack.strategies import Regime, StrategyEnsemble, StrategySignal

EMA_9_21_STRATEGY_ID = "ema_9_21"

CandidateFamily = Literal["ema_cross", "ema_cross_garch"]


@dataclass(frozen=True)
class EmaCrossoverStrategy:
    """Always-on EMA cross, optional ADX chop gate.

    Long when the fast EMA is above the slow EMA, short when below, flat
    when they are equal or ADX is at/below the threshold.
    """

    strategy_id: str
    fast_span: int = 9
    slow_span: int = 21
    adx_period: int = 14
    adx_threshold: float | None = None

    def evaluate(self, candles: tuple[Candle, ...], regime: Regime) -> StrategySignal:
        weight, rationale = self._raw_weight(candles)
        side: Side | None = None
        if weight > 0:
            side = Side.BUY
        elif weight < 0:
            side = Side.SELL
        score = max(-1.0, min(1.0, weight))
        return StrategySignal(
            strategy_id=self.strategy_id,
            symbol=candles[-1].symbol,
            side=side,
            score=score,
            confidence=abs(score) if side is not None else 0.0,
            regime=regime,
            rationale=rationale,
        )

    def _raw_weight(self, candles: tuple[Candle, ...]) -> tuple[float, str]:
        required = max(self.fast_span, self.slow_span)
        if self.adx_threshold is not None:
            required = max(required, 2 * self.adx_period + 1)
        if len(candles) < required:
            return 0.0, "insufficient candles for EMA crossover"
        fast = ema(candles, self.fast_span)
        slow = ema(candles, self.slow_span)
        if self.adx_threshold is not None:
            adx = average_directional_index(candles, self.adx_period)
            if adx <= self.adx_threshold:
                return 0.0, f"ADX={adx:.2f}<=threshold {self.adx_threshold:g} (skip chop)"
        if fast == slow:
            return 0.0, f"EMA {self.fast_span}/{self.slow_span} tied"
        weight = 1.0 if fast > slow else -1.0
        return weight, f"EMA {self.fast_span}/{self.slow_span} fast={fast:.4f} slow={slow:.4f}"


@dataclass(frozen=True)
class SearchCandidate:
    candidate_id: str
    family: CandidateFamily
    label: str
    params: dict[str, Any]
    strategy: EmaCrossoverStrategy
    garch_sizing: bool = False


def apply_garch_size(weight: float, forecast: GarchForecast | None) -> float:
    """Scale a signed direction weight. Missing forecast → stay flat (fail closed)."""
    if weight == 0.0:
        return 0.0
    if forecast is None:
        return 0.0
    return weight * forecast.size_multiplier


def default_miles_candidates() -> tuple[SearchCandidate, ...]:
    """Pre-registered Miles-inspired catalog. Keep small and frozen."""
    specs: tuple[tuple[str, int, int, float | None, bool], ...] = (
        ("ema_9_21", 9, 21, None, False),
        ("ema_12_26", 12, 26, None, False),
        ("ema_9_21_adx20", 9, 21, 20.0, False),
        ("ema_12_26_adx20", 12, 26, 20.0, False),
        ("ema_9_21_adx25", 9, 21, 25.0, False),
        ("ema_12_26_adx25", 12, 26, 25.0, False),
        ("ema_9_21_garch", 9, 21, None, True),
        ("ema_12_26_garch", 12, 26, None, True),
        ("ema_9_21_adx20_garch", 9, 21, 20.0, True),
        ("ema_12_26_adx20_garch", 12, 26, 20.0, True),
        ("ema_9_21_adx25_garch", 9, 21, 25.0, True),
        ("ema_12_26_adx25_garch", 12, 26, 25.0, True),
    )
    out: list[SearchCandidate] = []
    for candidate_id, fast, slow, adx_threshold, garch in specs:
        parts = [f"EMA {fast}/{slow}"]
        if adx_threshold is not None:
            parts.append(f"ADX>{adx_threshold:g}")
        if garch:
            parts.append("GARCH size [0.25, 2.0]")
        strategy = EmaCrossoverStrategy(
            strategy_id=candidate_id,
            fast_span=fast,
            slow_span=slow,
            adx_threshold=adx_threshold,
        )
        out.append(
            SearchCandidate(
                candidate_id=candidate_id,
                family="ema_cross_garch" if garch else "ema_cross",
                label=" × ".join(parts),
                params={
                    "fast_span": fast,
                    "slow_span": slow,
                    "adx_threshold": adx_threshold,
                    "garch_sizing": garch,
                    "strategy_id": candidate_id,
                },
                strategy=strategy,
                garch_sizing=garch,
            )
        )
    return tuple(out)


def ema_9_21_paper_voter() -> EmaCrossoverStrategy:
    """The pre-registered daily winner. No ADX gate, no GARCH size."""
    return EmaCrossoverStrategy(
        strategy_id=EMA_9_21_STRATEGY_ID,
        fast_span=9,
        slow_span=21,
    )


def build_ema_9_21_paper_ensemble() -> StrategyEnsemble:
    """Sole paper voter: `ema_9_21`. Defaults and the MA baseline stay off."""
    return StrategyEnsemble(
        extra_voters=(ema_9_21_paper_voter(),),
        min_agreeing=1,
        suppress_defaults=True,
    )
