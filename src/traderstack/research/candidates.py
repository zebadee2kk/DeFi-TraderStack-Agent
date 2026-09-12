"""Pre-registered standalone strategy candidates for `traderstack-strategy-search`.

Each candidate is a single voter: it may take a side on its own. That is
deliberate -- the paper ensemble's 2-of-3 consensus is a *combination* rule,
not an evaluation of whether MA, momentum, or mean-reversion has edge by
itself. Search scores the pieces; promotion is what may later put a winner
back into the paper voter set.

Optional feature families (liquidation z-score, cross-venue divergence) are
included in the catalog so they can be scored when a point-in-time series is
supplied. They are skipped, not invented, when the series is absent -- those
features are not on the Kraken Spot OHLC path used by paper research.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from traderstack.candles import Candle
from traderstack.indicators import moving_average, zscore
from traderstack.models import Side
from traderstack.strategies import (
    MeanReversionStrategy,
    MomentumStrategy,
    Regime,
    StrategySignal,
    TrendStrategy,
)

CandidateFamily = Literal["ma_cross", "momentum", "mean_reversion", "liquidation_z", "cross_venue"]


@dataclass(frozen=True)
class AlwaysOnTrendStrategy:
    """MA cross that always takes a side (the "spam both ways" baseline).

    Distinct from `TrendStrategy`, which stays flat unless the regime matches.
    """

    strategy_id: str = "ma_always_on_v1"
    short_window: int = 10
    long_window: int = 30

    def evaluate(self, candles: tuple[Candle, ...], regime: Regime) -> StrategySignal:
        if len(candles) < self.long_window:
            raise ValueError("insufficient candles for always-on MA")
        short = moving_average(candles, self.short_window)
        long = moving_average(candles, self.long_window)
        separation = short / long - 1.0
        side = Side.BUY if short >= long else Side.SELL
        confidence = min(abs(separation) / 0.01, 1.0)
        score = max(-1.0, min(1.0, separation / 0.01))
        return StrategySignal(
            strategy_id=self.strategy_id,
            symbol=candles[-1].symbol,
            side=side,
            score=score,
            confidence=confidence,
            regime=regime,
            rationale=f"always-on MA short={short:.4f} long={long:.4f}",
        )


@dataclass(frozen=True)
class FeatureZVoter:
    """Fade (or follow) an aligned exogenous z-score series, point-in-time only.

    `values` is `(opened_at, value)` sorted by time. Evaluation uses only
    points at or before the last candle in the window it is given.
    """

    strategy_id: str
    feature_name: str
    values: tuple[tuple[datetime, float], ...]
    lookback: int = 20
    entry_z: float = 1.5
    fade: bool = True

    def evaluate(self, candles: tuple[Candle, ...], regime: Regime) -> StrategySignal:
        cutoff = candles[-1].opened_at
        recent = [value for ts, value in self.values if ts <= cutoff][-self.lookback :]
        if len(recent) < self.lookback:
            return StrategySignal(
                strategy_id=self.strategy_id,
                symbol=candles[-1].symbol,
                side=None,
                score=0.0,
                confidence=0.0,
                regime=regime,
                rationale=f"{self.feature_name}: insufficient aligned history",
            )
        current_z = zscore(recent[-1], recent)
        side: Side | None = None
        if self.fade:
            if current_z <= -self.entry_z:
                side = Side.BUY
            elif current_z >= self.entry_z:
                side = Side.SELL
        else:
            if current_z >= self.entry_z:
                side = Side.BUY
            elif current_z <= -self.entry_z:
                side = Side.SELL
        confidence = min(abs(current_z) / max(self.entry_z * 2, 1e-9), 1.0)
        score = -current_z if self.fade else current_z
        score = max(-1.0, min(1.0, score / max(self.entry_z * 2, 1e-9)))
        return StrategySignal(
            strategy_id=self.strategy_id,
            symbol=candles[-1].symbol,
            side=side,
            score=score,
            confidence=confidence if side is not None else 0.0,
            regime=regime,
            rationale=f"{self.feature_name} z={current_z:.3f}",
        )


@dataclass(frozen=True)
class SearchCandidate:
    candidate_id: str
    family: CandidateFamily
    label: str
    params: dict[str, Any]
    strategy: object
    requires_feature: str | None = None


def build_price_strategy(family: str, params: dict[str, Any]) -> object:
    """Rebuild a price-only voter from the catalog params stored in a report."""
    if family == "ma_cross":
        if params.get("always_on"):
            return AlwaysOnTrendStrategy(
                strategy_id=str(params.get("strategy_id", "ma_always_on_v1")),
                short_window=int(params["short_window"]),
                long_window=int(params["long_window"]),
            )
        return TrendStrategy(
            strategy_id=str(params.get("strategy_id", "trend_v1")),
            short_window=int(params["short_window"]),
            long_window=int(params["long_window"]),
            minimum_separation=float(params.get("minimum_separation", 0.005)),
        )
    if family == "momentum":
        return MomentumStrategy(
            strategy_id=str(params.get("strategy_id", "momentum_v1")),
            lookback=int(params["lookback"]),
            minimum_momentum=float(params.get("minimum_momentum", 0.02)),
        )
    if family == "mean_reversion":
        return MeanReversionStrategy(
            strategy_id=str(params.get("strategy_id", "mean_reversion_v1")),
            lookback=int(params["lookback"]),
            entry_z=float(params.get("entry_z", 1.5)),
        )
    raise ValueError(f"family {family!r} is not a price-only voter")


def _ma(
    candidate_id: str,
    *,
    short_window: int,
    long_window: int,
    minimum_separation: float = 0.005,
    always_on: bool = False,
) -> SearchCandidate:
    params: dict[str, Any] = {
        "short_window": short_window,
        "long_window": long_window,
        "minimum_separation": minimum_separation,
        "always_on": always_on,
        "strategy_id": candidate_id,
    }
    strategy = build_price_strategy("ma_cross", params)
    label = f"{'always-on ' if always_on else ''}MA {short_window}/{long_window}" + (
        f" sep>={minimum_separation:g}" if not always_on else ""
    )
    return SearchCandidate(
        candidate_id=candidate_id,
        family="ma_cross",
        label=label,
        params=params,
        strategy=strategy,
    )


def _mom(candidate_id: str, *, lookback: int, minimum_momentum: float = 0.02) -> SearchCandidate:
    params: dict[str, Any] = {
        "lookback": lookback,
        "minimum_momentum": minimum_momentum,
        "strategy_id": candidate_id,
    }
    return SearchCandidate(
        candidate_id=candidate_id,
        family="momentum",
        label=f"momentum {lookback}-bar min={minimum_momentum:g}",
        params=params,
        strategy=build_price_strategy("momentum", params),
    )


def _mr(candidate_id: str, *, lookback: int, entry_z: float) -> SearchCandidate:
    params: dict[str, Any] = {
        "lookback": lookback,
        "entry_z": entry_z,
        "strategy_id": candidate_id,
    }
    return SearchCandidate(
        candidate_id=candidate_id,
        family="mean_reversion",
        label=f"mean-reversion {lookback}-bar |z|>={entry_z:g}",
        params=params,
        strategy=build_price_strategy("mean_reversion", params),
    )


def default_price_candidates() -> tuple[SearchCandidate, ...]:
    """The pre-registered price-only catalog. Keep this list small and frozen."""
    return (
        _ma("ma_cross_5_20", short_window=5, long_window=20),
        _ma("ma_cross_10_30", short_window=10, long_window=30),
        _ma("ma_cross_20_50", short_window=20, long_window=50),
        _ma("ma_cross_10_30_wide", short_window=10, long_window=30, minimum_separation=0.01),
        _ma("ma_always_on_10_30", short_window=10, long_window=30, always_on=True),
        _mom("momentum_6", lookback=6),
        _mom("momentum_12", lookback=12),
        _mom("momentum_24", lookback=24),
        _mom("momentum_12_strict", lookback=12, minimum_momentum=0.04),
        _mr("mean_reversion_20_1_5", lookback=20, entry_z=1.5),
        _mr("mean_reversion_20_2_0", lookback=20, entry_z=2.0),
        _mr("mean_reversion_10_1_5", lookback=10, entry_z=1.5),
        _mr("mean_reversion_40_2_0", lookback=40, entry_z=2.0),
    )


def feature_candidates(
    *,
    liquidation: tuple[tuple[datetime, float], ...] | None = None,
    cross_venue: tuple[tuple[datetime, float], ...] | None = None,
) -> tuple[SearchCandidate, ...]:
    """Optional families. Omitted series are not instantiated (not zero-filled)."""
    out: list[SearchCandidate] = []
    if liquidation is not None:
        params = {
            "lookback": 20,
            "entry_z": 1.5,
            "fade": True,
            "strategy_id": "liquidation_z_fade",
            "feature_name": "liquidation_z",
        }
        out.append(
            SearchCandidate(
                candidate_id="liquidation_z_fade",
                family="liquidation_z",
                label="fade liquidation z-score |z|>=1.5",
                params=params,
                strategy=FeatureZVoter(
                    strategy_id="liquidation_z_fade",
                    feature_name="liquidation_z",
                    values=liquidation,
                    lookback=20,
                    entry_z=1.5,
                    fade=True,
                ),
                requires_feature="liquidation_z",
            )
        )
    if cross_venue is not None:
        params = {
            "lookback": 20,
            "entry_z": 1.5,
            "fade": True,
            "strategy_id": "cross_venue_fade",
            "feature_name": "cross_venue_divergence_z",
        }
        out.append(
            SearchCandidate(
                candidate_id="cross_venue_fade",
                family="cross_venue",
                label="fade cross-venue divergence z |z|>=1.5",
                params=params,
                strategy=FeatureZVoter(
                    strategy_id="cross_venue_fade",
                    feature_name="cross_venue_divergence_z",
                    values=cross_venue,
                    lookback=20,
                    entry_z=1.5,
                    fade=True,
                ),
                requires_feature="cross_venue_divergence_z",
            )
        )
    return tuple(out)


FEATURE_CATALOG: tuple[tuple[CandidateFamily, str, str], ...] = (
    ("liquidation_z", "liquidation_z_fade", "fade liquidation z-score |z|>=1.5"),
    ("cross_venue", "cross_venue_fade", "fade cross-venue divergence z |z|>=1.5"),
)
