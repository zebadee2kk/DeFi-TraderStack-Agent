from dataclasses import dataclass, field
from enum import StrEnum

from pydantic import BaseModel, Field

from traderstack.candles import Candle
from traderstack.indicators import momentum, moving_average, realized_volatility, zscore
from traderstack.models import Side
from traderstack.signal_registry import version_of


class Regime(StrEnum):
    TRENDING_UP = "trending_up"
    TRENDING_DOWN = "trending_down"
    RANGE = "range"
    HIGH_VOLATILITY = "high_volatility"


class StrategySignal(BaseModel):
    strategy_id: str
    symbol: str
    side: Side | None = None
    score: float = Field(ge=-1, le=1)
    confidence: float = Field(ge=0, le=1)
    regime: Regime
    rationale: str
    signal_version: str | None = None


@dataclass(frozen=True)
class RegimeClassifier:
    short_window: int = 10
    long_window: int = 30
    volatility_lookback: int = 20
    high_volatility_threshold: float = 0.04

    def classify(self, candles: tuple[Candle, ...]) -> Regime:
        required = max(self.long_window, self.volatility_lookback + 1)
        if len(candles) < required:
            raise ValueError("insufficient candles for regime classification")
        volatility = realized_volatility(candles, self.volatility_lookback)
        if volatility >= self.high_volatility_threshold:
            return Regime.HIGH_VOLATILITY
        short = moving_average(candles, self.short_window)
        long = moving_average(candles, self.long_window)
        separation = short / long - 1.0
        if separation > 0.005:
            return Regime.TRENDING_UP
        if separation < -0.005:
            return Regime.TRENDING_DOWN
        return Regime.RANGE


@dataclass(frozen=True)
class MomentumStrategy:
    strategy_id: str = "momentum_v1"
    lookback: int = 12
    minimum_momentum: float = 0.02

    def evaluate(self, candles: tuple[Candle, ...], regime: Regime) -> StrategySignal:
        value = momentum(candles, self.lookback)
        strength = min(abs(value) / max(self.minimum_momentum, 1e-9), 1.0)
        side: Side | None = None
        if value >= self.minimum_momentum and regime is not Regime.TRENDING_DOWN:
            side = Side.BUY
        elif value <= -self.minimum_momentum and regime is not Regime.TRENDING_UP:
            side = Side.SELL
        score = max(-1.0, min(1.0, value / max(self.minimum_momentum * 2, 1e-9)))
        return StrategySignal(
            strategy_id=self.strategy_id,
            symbol=candles[-1].symbol,
            side=side,
            score=score,
            confidence=strength if side is not None else 0.0,
            regime=regime,
            rationale=f"{self.lookback}-bar momentum={value:.4f}",
        )


@dataclass(frozen=True)
class TrendStrategy:
    strategy_id: str = "trend_v1"
    short_window: int = 10
    long_window: int = 30
    minimum_separation: float = 0.005

    def evaluate(self, candles: tuple[Candle, ...], regime: Regime) -> StrategySignal:
        short = moving_average(candles, self.short_window)
        long = moving_average(candles, self.long_window)
        separation = short / long - 1.0
        side: Side | None = None
        if separation >= self.minimum_separation and regime is Regime.TRENDING_UP:
            side = Side.BUY
        elif separation <= -self.minimum_separation and regime is Regime.TRENDING_DOWN:
            side = Side.SELL
        confidence = min(abs(separation) / max(self.minimum_separation * 2, 1e-9), 1.0)
        score = max(-1.0, min(1.0, separation / max(self.minimum_separation * 2, 1e-9)))
        return StrategySignal(
            strategy_id=self.strategy_id,
            symbol=candles[-1].symbol,
            side=side,
            score=score,
            confidence=confidence if side is not None else 0.0,
            regime=regime,
            rationale=f"MA separation={separation:.4f}",
        )


@dataclass(frozen=True)
class MeanReversionStrategy:
    strategy_id: str = "mean_reversion_v1"
    lookback: int = 20
    entry_z: float = 1.5

    def evaluate(self, candles: tuple[Candle, ...], regime: Regime) -> StrategySignal:
        if len(candles) < self.lookback:
            raise ValueError("insufficient candles for mean reversion")
        closes = [candle.close for candle in candles[-self.lookback :]]
        current_z = zscore(closes[-1], closes)
        side: Side | None = None
        if regime is Regime.RANGE:
            if current_z <= -self.entry_z:
                side = Side.BUY
            elif current_z >= self.entry_z:
                side = Side.SELL
        confidence = min(abs(current_z) / max(self.entry_z * 2, 1e-9), 1.0)
        score = max(-1.0, min(1.0, -current_z / max(self.entry_z * 2, 1e-9)))
        return StrategySignal(
            strategy_id=self.strategy_id,
            symbol=candles[-1].symbol,
            side=side,
            score=score,
            confidence=confidence if side is not None else 0.0,
            regime=regime,
            rationale=f"price z-score={current_z:.3f}",
        )


@dataclass(frozen=True)
class PaperResearchStrategy:
    """Candle-only baseline voter used in paper research mode.

    Optional intel (on-chain, narrative, altFINS / other edge fields, Crucix)
    is intentionally unread. The strategy takes the short-vs-long moving-average
    side when candles are healthy (enough history, positive prices) and the
    averages are not identical. It is regime-agnostic so it can pair with the
    trend/momentum voters that the default ensemble otherwise mutually excludes
    by regime, or stand alone when ``min_agreeing`` is 1.

    Live/shadow ensembles must leave this unset. See
    ``docs/RUNBOOK.md`` ("Paper research mode and strategy consensus").
    """

    strategy_id: str = "paper_research_baseline_v1"
    short_window: int = 10
    long_window: int = 30
    # 10 bps of MA separation is enough to refuse a perfectly flat book while
    # still firing on typical Kraken 1h crypto drift that misses the 2%
    # 12-bar momentum bar.
    minimum_separation: float = 0.001

    def evaluate(self, candles: tuple[Candle, ...], regime: Regime) -> StrategySignal:
        required = max(self.short_window, self.long_window)
        if len(candles) < required:
            raise ValueError("insufficient candles for paper research baseline")
        short = moving_average(candles, self.short_window)
        long = moving_average(candles, self.long_window)
        if short <= 0 or long <= 0:
            return StrategySignal(
                strategy_id=self.strategy_id,
                symbol=candles[-1].symbol,
                side=None,
                score=0.0,
                confidence=0.0,
                regime=regime,
                rationale="unhealthy candle prices (non-positive moving average)",
            )
        separation = short / long - 1.0
        side: Side | None = None
        if separation >= self.minimum_separation:
            side = Side.BUY
        elif separation <= -self.minimum_separation:
            side = Side.SELL
        confidence = min(abs(separation) / max(self.minimum_separation * 2, 1e-9), 1.0)
        score = max(-1.0, min(1.0, separation / max(self.minimum_separation * 2, 1e-9)))
        return StrategySignal(
            strategy_id=self.strategy_id,
            symbol=candles[-1].symbol,
            side=side,
            score=score,
            confidence=confidence if side is not None else 0.0,
            regime=regime,
            rationale=f"paper-research MA separation={separation:.4f}",
        )


@dataclass(frozen=True)
class StrategyEnsemble:
    classifier: RegimeClassifier = field(default_factory=RegimeClassifier)
    momentum_strategy: MomentumStrategy = field(default_factory=MomentumStrategy)
    trend_strategy: TrendStrategy = field(default_factory=TrendStrategy)
    mean_reversion_strategy: MeanReversionStrategy = field(default_factory=MeanReversionStrategy)
    # --- paper research mode ---
    # Unset in live/shadow. When set, the candle-only baseline participates in
    # evaluate() so paper dry-runs are not structurally unable to reach
    # two-of-three (the default members are regime-exclusive).
    paper_research_strategy: PaperResearchStrategy | None = None
    # Majority size. Default 2 is the live/shadow / specialist-committee rule.
    # Paper research mode may drop this to 1 when optional intel is unset.
    min_agreeing: int = 2

    def evaluate(self, candles: tuple[Candle, ...]) -> tuple[Regime, tuple[StrategySignal, ...]]:
        regime = self.classifier.classify(candles)
        signals: list[StrategySignal] = [
            self.momentum_strategy.evaluate(candles, regime),
            self.trend_strategy.evaluate(candles, regime),
            self.mean_reversion_strategy.evaluate(candles, regime),
        ]
        if self.paper_research_strategy is not None:
            signals.append(self.paper_research_strategy.evaluate(candles, regime))
        return regime, tuple(signals)

    def consensus(self, signals: tuple[StrategySignal, ...]) -> StrategySignal | None:
        return combine_signals(
            signals,
            strategy_id="baseline_ensemble_v1",
            signal_version=version_of(self),
            min_agreeing=self.min_agreeing,
        )


def combine_signals(
    signals: tuple[StrategySignal, ...],
    *,
    strategy_id: str,
    signal_version: str | None = None,
    min_agreeing: int = 2,
) -> StrategySignal | None:
    """Majority-side consensus requiring ``min_agreeing`` agreeing actionable signals.

    Shared by the quant ensemble and the specialist committee so both combine
    their members identically; each caller stamps its own id and version.

    A split vote (equal buy and sell counts) is no consensus — fail closed
    rather than silently preferring BUY. ``min_agreeing`` defaults to 2; paper
    research mode may pass 1 when optional intel voters cannot participate.
    """
    if min_agreeing < 1:
        raise ValueError("min_agreeing must be >= 1")
    actionable = [signal for signal in signals if signal.side is not None]
    if not actionable:
        return None
    buys = [signal for signal in actionable if signal.side is Side.BUY]
    sells = [signal for signal in actionable if signal.side is Side.SELL]
    if len(buys) == len(sells):
        return None
    selected = buys if len(buys) > len(sells) else sells
    if len(selected) < min_agreeing:
        return None
    confidence = sum(signal.confidence for signal in selected) / len(selected)
    score = sum(signal.score for signal in selected) / len(selected)
    return StrategySignal(
        strategy_id=strategy_id,
        symbol=selected[0].symbol,
        side=selected[0].side,
        score=max(-1.0, min(1.0, score)),
        confidence=confidence,
        regime=selected[0].regime,
        rationale="; ".join(signal.rationale for signal in selected),
        signal_version=signal_version,
    )
