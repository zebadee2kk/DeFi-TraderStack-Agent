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
    is intentionally unread. The strategy is regime-agnostic and
    symbol-agnostic: the same voter participates for every allowlisted
    asset (BTC, ETH, SOL, …) whenever candles are healthy.

    Primary tilt is short-vs-long moving average. On a RANGE book those
    two averages converge (typical ETH 1h Spot: a few bps) while last
    close vs the long MA still has a measurable gap — that fallback is
    how the baseline keeps participating instead of going silent on one
    asset. Perfectly flat or non-positive prices stay flat.

    Live/shadow ensembles must leave this unset. See
    ``docs/RUNBOOK.md`` ("Paper research mode and strategy consensus").
    """

    strategy_id: str = "paper_research_baseline_v1"
    short_window: int = 10
    long_window: int = 30
    # 10 bps of tilt is enough to refuse a perfectly flat book while
    # still firing on typical Kraken 1h crypto drift that misses the 2%
    # 12-bar momentum bar.
    minimum_separation: float = 0.001

    def evaluate(self, candles: tuple[Candle, ...], regime: Regime) -> StrategySignal:
        required = max(self.short_window, self.long_window)
        if len(candles) < required:
            raise ValueError("insufficient candles for paper research baseline")
        short = moving_average(candles, self.short_window)
        long = moving_average(candles, self.long_window)
        close = candles[-1].close
        if short <= 0 or long <= 0 or close <= 0:
            return StrategySignal(
                strategy_id=self.strategy_id,
                symbol=candles[-1].symbol,
                side=None,
                score=0.0,
                confidence=0.0,
                regime=regime,
                rationale="unhealthy candle prices (non-positive moving average)",
            )
        ma_separation = short / long - 1.0
        price_separation = close / long - 1.0
        if abs(ma_separation) >= self.minimum_separation:
            separation = ma_separation
            rationale = f"paper-research MA separation={ma_separation:.4f}"
        elif abs(price_separation) >= self.minimum_separation:
            # RANGE / compressed-MA fallback so ETH-like Spot books still vote.
            separation = price_separation
            rationale = f"paper-research price vs long MA={price_separation:.4f}"
        else:
            return StrategySignal(
                strategy_id=self.strategy_id,
                symbol=candles[-1].symbol,
                side=None,
                score=0.0,
                confidence=0.0,
                regime=regime,
                rationale=f"paper-research MA separation={ma_separation:.4f}",
            )
        side = Side.BUY if separation > 0 else Side.SELL
        confidence = min(abs(separation) / max(self.minimum_separation * 2, 1e-9), 1.0)
        score = max(-1.0, min(1.0, separation / max(self.minimum_separation * 2, 1e-9)))
        return StrategySignal(
            strategy_id=self.strategy_id,
            symbol=candles[-1].symbol,
            side=side,
            score=score,
            confidence=confidence,
            regime=regime,
            rationale=rationale,
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
    # --- strategy search / paper voters ---
    # Extra standalone voters (promoted search winners). Default empty so the
    # paper-research ensemble is unchanged. `suppress_defaults` is the
    # promotion switch: when True, only `extra_voters` participate.
    extra_voters: tuple[object, ...] = ()
    suppress_defaults: bool = False

    def evaluate(self, candles: tuple[Candle, ...]) -> tuple[Regime, tuple[StrategySignal, ...]]:
        regime = self.classifier.classify(candles)
        signals: list[StrategySignal] = []
        if not self.suppress_defaults:
            signals.extend(
                (
                    self.momentum_strategy.evaluate(candles, regime),
                    self.trend_strategy.evaluate(candles, regime),
                    self.mean_reversion_strategy.evaluate(candles, regime),
                )
            )
            if self.paper_research_strategy is not None:
                signals.append(self.paper_research_strategy.evaluate(candles, regime))
        for voter in self.extra_voters:
            evaluate = getattr(voter, "evaluate", None)
            if evaluate is None:
                raise TypeError("extra voter is missing evaluate()")
            signals.append(evaluate(candles, regime))
        return regime, tuple(signals)

    def paper_research_position(
        self, candles: tuple[Candle, ...]
    ) -> tuple[float, Regime, list[str]] | None:
        """Isolated baseline position for the paper-research lookback.

        ``None`` when no baseline is wired (live/shadow). The current-side
        consensus still uses :meth:`evaluate` + :meth:`consensus`; this path
        exists so the backtester measures the MA voter rather than the
        regime-exclusive ensemble, which flattens on 1–1 splits and bleeds
        fees on a lookback the MA path itself would survive.
        """
        if self.paper_research_strategy is None:
            return None
        regime = self.classifier.classify(candles)
        signal = self.paper_research_strategy.evaluate(candles, regime)
        if signal.side is None:
            return 0.0, regime, []
        weight = 1.0 if signal.side is Side.BUY else -1.0
        return weight, regime, [signal.strategy_id]

    def consensus(self, signals: tuple[StrategySignal, ...]) -> StrategySignal | None:
        # --- paper research path ---
        # When intel is off (min_agreeing=1) the baseline is the paper voter.
        # An opposing regime-exclusive minority (typical RANGE mean-reversion)
        # must not cancel it with a 1–1 split — that is how ETH stayed silent
        # after the price-vs-long-MA fallback started participating.
        if self.paper_research_strategy is not None and self.min_agreeing == 1:
            baseline_id = self.paper_research_strategy.strategy_id
            baseline = next(
                (signal for signal in signals if signal.strategy_id == baseline_id),
                None,
            )
            if baseline is not None and baseline.side is not None:
                agreeing = tuple(signal for signal in signals if signal.side is baseline.side)
                return combine_signals(
                    agreeing,
                    strategy_id="baseline_ensemble_v1",
                    signal_version=version_of(self),
                    min_agreeing=1,
                )
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
    Promoted search winners may also pass 1, and only after the promotion
    gate has already required fee-aware walk-forward edge.
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
