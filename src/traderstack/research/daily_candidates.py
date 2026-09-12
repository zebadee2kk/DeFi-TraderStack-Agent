"""Pre-registered daily robustness catalog (paper/research only).

Built around the #93 Miles daily winner plus two extra families the
robustness pass is required to score:

* EMA 9/21 and 12/26, with and without ADX chop gates (no GARCH — that
  family already failed fees on the Miles window).
* Simple dual-momentum: long/short only when a fast and a slow lookback
  agree; otherwise cash. Single-asset absolute confirmation, not
  cross-sectional relative ranking.
* Buy-the-dip mean-reversion with a vol spike filter: long-only when the
  close z-score is oversold *and* short-horizon vol is not elevated
  versus a slower vol baseline.

Keep this list small and frozen. Ranking is pre-registered top-1.
"""

from __future__ import annotations

from dataclasses import dataclass

from traderstack.candles import Candle
from traderstack.indicators import momentum, realized_volatility, zscore
from traderstack.models import Side
from traderstack.research.miles_candidates import EmaCrossoverStrategy, SearchCandidate
from traderstack.strategies import Regime, StrategySignal


@dataclass(frozen=True)
class DualMomentumStrategy:
    """Fast and slow lookback returns must agree; otherwise stay flat."""

    strategy_id: str
    fast_lookback: int = 21
    slow_lookback: int = 126
    minimum_momentum: float = 0.0

    def evaluate(self, candles: tuple[Candle, ...], regime: Regime) -> StrategySignal:
        required = self.slow_lookback + 1
        if len(candles) < required:
            return StrategySignal(
                strategy_id=self.strategy_id,
                symbol=candles[-1].symbol if candles else "",
                side=None,
                score=0.0,
                confidence=0.0,
                regime=regime,
                rationale="insufficient candles for dual momentum",
            )
        fast = momentum(candles, self.fast_lookback)
        slow = momentum(candles, self.slow_lookback)
        side: Side | None = None
        if fast >= self.minimum_momentum and slow >= self.minimum_momentum:
            side = Side.BUY
        elif fast <= -self.minimum_momentum and slow <= -self.minimum_momentum:
            side = Side.SELL
        score = 0.0
        if side is Side.BUY:
            score = 1.0
        elif side is Side.SELL:
            score = -1.0
        return StrategySignal(
            strategy_id=self.strategy_id,
            symbol=candles[-1].symbol,
            side=side,
            score=score,
            confidence=1.0 if side is not None else 0.0,
            regime=regime,
            rationale=(
                f"dual-mom fast={self.fast_lookback}={fast:.4f} "
                f"slow={self.slow_lookback}={slow:.4f}"
            ),
        )


@dataclass(frozen=True)
class BuyTheDipVolFilterStrategy:
    """Long-only oversold dip; skip when short-horizon vol is elevated."""

    strategy_id: str
    lookback: int = 20
    entry_z: float = 1.5
    vol_lookback: int = 20
    baseline_vol_lookback: int = 60
    vol_multiple: float = 1.5

    def evaluate(self, candles: tuple[Candle, ...], regime: Regime) -> StrategySignal:
        required = max(self.lookback, self.baseline_vol_lookback + 1, self.vol_lookback + 1)
        if len(candles) < required:
            return StrategySignal(
                strategy_id=self.strategy_id,
                symbol=candles[-1].symbol if candles else "",
                side=None,
                score=0.0,
                confidence=0.0,
                regime=regime,
                rationale="insufficient candles for buy-the-dip",
            )
        closes = [candle.close for candle in candles[-self.lookback :]]
        current_z = zscore(closes[-1], closes)
        short_vol = realized_volatility(candles, self.vol_lookback)
        baseline_vol = realized_volatility(candles, self.baseline_vol_lookback)
        if short_vol > self.vol_multiple * baseline_vol:
            return StrategySignal(
                strategy_id=self.strategy_id,
                symbol=candles[-1].symbol,
                side=None,
                score=0.0,
                confidence=0.0,
                regime=regime,
                rationale=(
                    f"vol filter: short={short_vol:.4f} > "
                    f"{self.vol_multiple:g}× baseline={baseline_vol:.4f}"
                ),
            )
        side: Side | None = None
        if current_z <= -self.entry_z:
            side = Side.BUY
        confidence = min(abs(current_z) / max(self.entry_z * 2, 1e-9), 1.0)
        score = max(-1.0, min(1.0, -current_z / max(self.entry_z * 2, 1e-9)))
        return StrategySignal(
            strategy_id=self.strategy_id,
            symbol=candles[-1].symbol,
            side=side,
            score=score if side is not None else 0.0,
            confidence=confidence if side is not None else 0.0,
            regime=regime,
            rationale=f"buy-the-dip z={current_z:.3f} vol={short_vol:.4f}",
        )


def _ema(
    candidate_id: str,
    *,
    fast: int,
    slow: int,
    adx_threshold: float | None = None,
) -> SearchCandidate:
    parts = [f"EMA {fast}/{slow}"]
    if adx_threshold is not None:
        parts.append(f"ADX>{adx_threshold:g}")
    return SearchCandidate(
        candidate_id=candidate_id,
        family="ema_cross",
        label=" × ".join(parts),
        params={
            "fast_span": fast,
            "slow_span": slow,
            "adx_threshold": adx_threshold,
            "garch_sizing": False,
            "strategy_id": candidate_id,
        },
        strategy=EmaCrossoverStrategy(
            strategy_id=candidate_id,
            fast_span=fast,
            slow_span=slow,
            adx_threshold=adx_threshold,
        ),
        garch_sizing=False,
    )


def _dual_mom(
    candidate_id: str,
    *,
    fast_lookback: int,
    slow_lookback: int,
    minimum_momentum: float = 0.0,
) -> SearchCandidate:
    strategy = DualMomentumStrategy(
        strategy_id=candidate_id,
        fast_lookback=fast_lookback,
        slow_lookback=slow_lookback,
        minimum_momentum=minimum_momentum,
    )
    return SearchCandidate(
        candidate_id=candidate_id,
        family="dual_momentum",
        label=f"dual-momentum {fast_lookback}/{slow_lookback} (agree or cash)",
        params={
            "fast_lookback": fast_lookback,
            "slow_lookback": slow_lookback,
            "minimum_momentum": minimum_momentum,
            "strategy_id": candidate_id,
        },
        strategy=strategy,
    )


def _dip(
    candidate_id: str,
    *,
    lookback: int,
    entry_z: float,
    vol_lookback: int,
    baseline_vol_lookback: int,
    vol_multiple: float,
) -> SearchCandidate:
    strategy = BuyTheDipVolFilterStrategy(
        strategy_id=candidate_id,
        lookback=lookback,
        entry_z=entry_z,
        vol_lookback=vol_lookback,
        baseline_vol_lookback=baseline_vol_lookback,
        vol_multiple=vol_multiple,
    )
    return SearchCandidate(
        candidate_id=candidate_id,
        family="buy_the_dip",
        label=(
            f"buy-the-dip {lookback}-bar |z|>={entry_z:g} "
            f"(skip if {vol_lookback}d vol > {vol_multiple:g}× {baseline_vol_lookback}d vol)"
        ),
        params={
            "lookback": lookback,
            "entry_z": entry_z,
            "vol_lookback": vol_lookback,
            "baseline_vol_lookback": baseline_vol_lookback,
            "vol_multiple": vol_multiple,
            "strategy_id": candidate_id,
        },
        strategy=strategy,
    )


def default_daily_robustness_candidates() -> tuple[SearchCandidate, ...]:
    """Frozen daily catalog. Do not grow this list to chase a winner."""
    return (
        _ema("ema_9_21", fast=9, slow=21),
        _ema("ema_12_26", fast=12, slow=26),
        _ema("ema_9_21_adx20", fast=9, slow=21, adx_threshold=20.0),
        _ema("ema_12_26_adx20", fast=12, slow=26, adx_threshold=20.0),
        _ema("ema_9_21_adx25", fast=9, slow=21, adx_threshold=25.0),
        _ema("ema_12_26_adx25", fast=12, slow=26, adx_threshold=25.0),
        _dual_mom("dual_mom_21_126", fast_lookback=21, slow_lookback=126),
        _dip(
            "dip_mr_20_1_5_vol",
            lookback=20,
            entry_z=1.5,
            vol_lookback=20,
            baseline_vol_lookback=60,
            vol_multiple=1.5,
        ),
    )
