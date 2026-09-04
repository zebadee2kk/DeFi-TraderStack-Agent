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
class StrategyEnsemble:
    classifier: RegimeClassifier = field(default_factory=RegimeClassifier)
    momentum_strategy: MomentumStrategy = field(default_factory=MomentumStrategy)
    trend_strategy: TrendStrategy = field(default_factory=TrendStrategy)
    mean_reversion_strategy: MeanReversionStrategy = field(default_factory=MeanReversionStrategy)

    def evaluate(self, candles: tuple[Candle, ...]) -> tuple[Regime, tuple[StrategySignal, ...]]:
        regime = self.classifier.classify(candles)
        signals = (
            self.momentum_strategy.evaluate(candles, regime),
            self.trend_strategy.evaluate(candles, regime),
            self.mean_reversion_strategy.evaluate(candles, regime),
        )
        return regime, signals

    def consensus(self, signals: tuple[StrategySignal, ...]) -> StrategySignal | None:
        actionable = [signal for signal in signals if signal.side is not None]
        if not actionable:
            return None
        buys = [signal for signal in actionable if signal.side is Side.BUY]
        sells = [signal for signal in actionable if signal.side is Side.SELL]
        selected = buys if len(buys) >= len(sells) else sells
        if len(selected) < 2:
            return None
        confidence = sum(signal.confidence for signal in selected) / len(selected)
        score = sum(signal.score for signal in selected) / len(selected)
        return StrategySignal(
            strategy_id="baseline_ensemble_v1",
            symbol=selected[0].symbol,
            side=selected[0].side,
            score=max(-1.0, min(1.0, score)),
            confidence=confidence,
            regime=selected[0].regime,
            rationale="; ".join(signal.rationale for signal in selected),
            signal_version=version_of(self),
        )
