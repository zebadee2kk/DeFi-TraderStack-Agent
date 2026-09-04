"""Deterministic specialist strategy agents (Epic 6).

`docs/AGENT-ARCHITECTURE.md` lists a technical, an on-chain and a
narrative/sentiment strategy agent. They are implemented here as *deterministic*
candidate generators: each reads one slice of an `AssetFeatureVector` and emits a
`StrategySignal`. No LLM is involved, so their output is reproducible, cheap and
testable, and a provider outage degrades them to "no signal" rather than to a
hallucinated one.

Every threshold is a constructor parameter so it can be tuned in configuration
and version-controlled, never inferred at runtime.

`SpecialistCommittee.consensus` deliberately delegates to
`traderstack.strategies.combine_signals`, the same function behind
`StrategyEnsemble.consensus`, so the committee combines signals with exactly the
same majority/agreement rule as the baseline quant ensemble.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from traderstack.features import AssetFeatureVector
from traderstack.models import Side
from traderstack.signal_registry import version_of
from traderstack.strategies import Regime, StrategySignal, combine_signals


def _clamp(value: float, low: float = -1.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _side_for(score: float, threshold: float) -> Side | None:
    if score >= threshold:
        return Side.BUY
    if score <= -threshold:
        return Side.SELL
    return None


def _signal(
    strategy_id: str,
    symbol: str,
    regime: Regime,
    score: float,
    threshold: float,
    rationale: str,
    *,
    blocked: bool = False,
) -> StrategySignal:
    score = _clamp(score)
    side = None if blocked else _side_for(score, threshold)
    confidence = min(abs(score) / max(threshold * 2, 1e-9), 1.0)
    return StrategySignal(
        strategy_id=strategy_id,
        symbol=symbol,
        side=side,
        score=score,
        confidence=confidence if side is not None else 0.0,
        regime=regime,
        rationale=rationale,
    )


@dataclass(frozen=True)
class TechnicalSpecialist:
    """Reads the market slice: trend, volatility, participation and spread."""

    strategy_id: str = "technical_specialist_v1"
    # Blended trend needed before the specialist will take a side at all.
    trend_threshold: float = 0.15
    # Above this spread the book is too thin to act on a technical read.
    max_spread_bps: float = 25.0
    # Beyond this volatility z-score the technical read is treated as noise.
    max_volatility_z: float = 2.5
    # Below this relative volume the move is unconfirmed by participation.
    min_relative_volume: float = 0.5

    def evaluate(
        self,
        vector: AssetFeatureVector,
        regime: Regime = Regime.RANGE,
        symbol: str | None = None,
    ) -> StrategySignal:
        market = vector.market
        target = symbol or f"{vector.asset.upper()}/USD"
        score = (market.trend_4h + market.trend_1d) / 2.0

        blocks: list[str] = []
        if market.spread_bps > self.max_spread_bps:
            blocks.append("spread_too_wide")
        if abs(market.volatility_z) > self.max_volatility_z:
            blocks.append("volatility_out_of_band")
        if market.relative_volume < self.min_relative_volume:
            blocks.append("participation_too_low")

        rationale = f"trend_4h={market.trend_4h:.3f} trend_1d={market.trend_1d:.3f}"
        if blocks:
            rationale = f"{rationale}; blocked: {','.join(blocks)}"
        return _signal(
            self.strategy_id,
            target,
            regime,
            score,
            self.trend_threshold,
            rationale,
            blocked=bool(blocks),
        )


@dataclass(frozen=True)
class OnChainSpecialist:
    """Reads the on-chain slice: exchange netflow and large-wallet behaviour.

    Missing on-chain data yields no signal — absence of evidence is never read as
    evidence of safety.
    """

    strategy_id: str = "onchain_specialist_v1"
    # |z| of exchange netflow that counts as a full-strength flow signal.
    netflow_z_threshold: float = 1.0
    # Large-wallet accumulation (-1..1) that counts as full-strength.
    accumulation_threshold: float = 0.2
    # Blended score needed before the specialist takes a side.
    score_threshold: float = 0.3

    def evaluate(
        self,
        vector: AssetFeatureVector,
        regime: Regime = Regime.RANGE,
        symbol: str | None = None,
    ) -> StrategySignal:
        onchain = vector.onchain
        target = symbol or f"{vector.asset.upper()}/USD"
        components: list[float] = []
        parts: list[str] = []

        if onchain.exchange_netflow_z is not None:
            # Coins leaving exchanges (negative netflow) reduce sell-side supply.
            components.append(
                _clamp(-onchain.exchange_netflow_z / max(self.netflow_z_threshold * 2, 1e-9))
            )
            parts.append(f"netflow_z={onchain.exchange_netflow_z:.3f}")
        if onchain.large_wallet_accumulation is not None:
            components.append(
                _clamp(
                    onchain.large_wallet_accumulation / max(self.accumulation_threshold * 2, 1e-9)
                )
            )
            parts.append(f"accumulation={onchain.large_wallet_accumulation:.3f}")

        if not components:
            return _signal(
                self.strategy_id,
                target,
                regime,
                0.0,
                self.score_threshold,
                "no on-chain evidence available",
                blocked=True,
            )

        score = sum(components) / len(components)
        return _signal(
            self.strategy_id,
            target,
            regime,
            score,
            self.score_threshold,
            "; ".join(parts),
        )


@dataclass(frozen=True)
class NarrativeSpecialist:
    """Reads the narrative/news slice: sentiment, mention velocity and events.

    Note the asymmetry: an adverse event suppresses the signal entirely rather
    than flipping it. Narrative data is the most easily manipulated input in the
    stack, so it is allowed to withhold a candidate but not to manufacture one
    from an event alone.
    """

    strategy_id: str = "narrative_specialist_v1"
    # Sentiment (-1..1) that counts as full-strength.
    sentiment_threshold: float = 0.2
    # |z| of mention velocity that counts as full-strength.
    mention_velocity_z_threshold: float = 1.0
    # Blended score needed before the specialist takes a side.
    score_threshold: float = 0.3
    # Event score above which the tape is treated as event-driven, not tradable.
    max_event_score: float = 0.7
    # An adverse event always suppresses the signal.
    adverse_event_blocks: bool = True

    def evaluate(
        self,
        vector: AssetFeatureVector,
        regime: Regime = Regime.RANGE,
        symbol: str | None = None,
    ) -> StrategySignal:
        narrative = vector.narrative
        news = vector.news
        target = symbol or f"{vector.asset.upper()}/USD"
        components: list[float] = []
        parts: list[str] = []

        if narrative.sentiment is not None:
            components.append(_clamp(narrative.sentiment / max(self.sentiment_threshold * 2, 1e-9)))
            parts.append(f"sentiment={narrative.sentiment:.3f}")
        if narrative.mention_velocity_z is not None:
            components.append(
                _clamp(
                    narrative.mention_velocity_z / max(self.mention_velocity_z_threshold * 2, 1e-9)
                )
            )
            parts.append(f"mention_velocity_z={narrative.mention_velocity_z:.3f}")

        blocks: list[str] = []
        if self.adverse_event_blocks and news.adverse_event:
            blocks.append("adverse_event")
        if news.event_score > self.max_event_score:
            blocks.append("event_score_above_maximum")
        if not components:
            blocks.append("no_narrative_evidence")

        score = sum(components) / len(components) if components else 0.0
        rationale = "; ".join(parts) if parts else "no narrative evidence available"
        if blocks:
            rationale = f"{rationale}; blocked: {','.join(blocks)}"
        return _signal(
            self.strategy_id,
            target,
            regime,
            score,
            self.score_threshold,
            rationale,
            blocked=bool(blocks),
        )


@dataclass(frozen=True)
class SpecialistCommittee:
    """Runs every specialist and combines them like the baseline quant ensemble."""

    committee_id: str = "specialist_committee_v1"
    technical: TechnicalSpecialist = field(default_factory=TechnicalSpecialist)
    onchain: OnChainSpecialist = field(default_factory=OnChainSpecialist)
    narrative: NarrativeSpecialist = field(default_factory=NarrativeSpecialist)

    def evaluate(
        self,
        vector: AssetFeatureVector,
        regime: Regime = Regime.RANGE,
        symbol: str | None = None,
    ) -> tuple[StrategySignal, ...]:
        return (
            self.technical.evaluate(vector, regime, symbol),
            self.onchain.evaluate(vector, regime, symbol),
            self.narrative.evaluate(vector, regime, symbol),
        )

    def consensus(self, signals: tuple[StrategySignal, ...]) -> StrategySignal | None:
        return combine_signals(
            signals, strategy_id=self.committee_id, signal_version=version_of(self)
        )
