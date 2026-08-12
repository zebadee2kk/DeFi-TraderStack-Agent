from dataclasses import dataclass, field

from traderstack.agents.meta import ConstrainedMetaAgent, EvidencePacket
from traderstack.candles import Candle
from traderstack.features import AssetFeatureVector, MarketFeatures
from traderstack.intelligence_orchestrator import IntelligenceOrchestrator
from traderstack.market.models import MarketTick, ReferencePrice
from traderstack.market_features import CandleMarketFeatureBuilder
from traderstack.models import PortfolioSnapshot, RiskDecision, Side, TradeProposal
from traderstack.pipeline import PaperOrderIntent, PipelineResult, validate_market_inputs
from traderstack.risk import RiskEngine
from traderstack.strategies import StrategyEnsemble, StrategySignal


@dataclass(frozen=True)
class SignalPipeline:
    """Candle-driven trading pipeline for the paper loop.

    Order of gates: market-data quality → candle features → strategy ensemble
    consensus → optional external intelligence (adverse-news veto) → optional
    constrained meta-agent review (fail-closed) → deterministic risk engine.
    The meta-agent can only veto or nudge confidence; it can never originate a
    trade, change direction, or increase requested capital.
    """

    risk_engine: RiskEngine
    ensemble: StrategyEnsemble = field(default_factory=StrategyEnsemble)
    feature_builder: CandleMarketFeatureBuilder = field(default_factory=CandleMarketFeatureBuilder)
    intelligence: IntelligenceOrchestrator | None = None
    meta_agent: ConstrainedMetaAgent | None = None
    max_tick_age_seconds: float = 10.0
    max_spread_bps: float = 30.0
    max_reference_divergence_bps: float = 100.0
    base_notional_pct: float = 0.02
    min_confidence: float = 0.35
    min_order_notional_usd: float = 10.0
    strategy_id: str = "signal_ensemble_v1"
    venue: str = "kraken_paper_trade"

    async def process(
        self,
        tick: MarketTick,
        candles: tuple[Candle, ...],
        references: list[ReferencePrice],
        portfolio: PortfolioSnapshot,
    ) -> PipelineResult:
        asset = tick.symbol.split("/", 1)[0].upper()
        gate = validate_market_inputs(
            tick,
            references,
            max_tick_age_seconds=self.max_tick_age_seconds,
            max_spread_bps=self.max_spread_bps,
            max_reference_divergence_bps=self.max_reference_divergence_bps,
        )
        if gate.reasons:
            return PipelineResult(accepted_market_data=False, rejection_reasons=gate.reasons)

        try:
            market = self.feature_builder.build(candles, spread_bps=tick.spread_bps)
            regime, signals = self.ensemble.evaluate(candles)
        except ValueError:
            return PipelineResult(
                accepted_market_data=False,
                rejection_reasons=["insufficient_candle_history"],
            )

        feature_vector = await self._build_feature_vector(asset, market, tick, gate.eligible_references)
        result = PipelineResult(
            accepted_market_data=True,
            regime=regime,
            signals=list(signals),
            feature_vector=feature_vector,
        )

        consensus = self.ensemble.consensus(signals)
        if consensus is None:
            result.no_trade_reasons.append("no_consensus_signal")
            return result
        if consensus.confidence < self.min_confidence:
            result.no_trade_reasons.append("confidence_below_threshold")
            return result
        if consensus.side is Side.BUY and feature_vector.news.adverse_event:
            result.no_trade_reasons.append("adverse_news_event")
            return result

        requested_notional = portfolio.nav_usd * self.base_notional_pct * consensus.confidence
        if requested_notional < self.min_order_notional_usd:
            result.no_trade_reasons.append("notional_below_minimum")
            return result

        proposal = await self._build_proposal(
            asset,
            consensus,
            feature_vector,
            requested_notional,
            gate.tick_age_seconds,
            result,
        )
        if proposal is None:
            return result

        result.proposal = proposal
        risk_result = self.risk_engine.evaluate(proposal, portfolio)
        result.risk_result = risk_result
        if (
            risk_result.decision in {RiskDecision.ALLOW, RiskDecision.REDUCE}
            and risk_result.approved_notional_usd > 0
        ):
            result.paper_order = PaperOrderIntent(
                decision_id=str(proposal.decision_id),
                asset=asset,
                side=proposal.side,
                notional_usd=risk_result.approved_notional_usd,
                venue=self.venue,
            )
        return result

    async def _build_feature_vector(
        self,
        asset: str,
        market: MarketFeatures,
        tick: MarketTick,
        references: list[ReferencePrice],
    ) -> AssetFeatureVector:
        if self.intelligence is not None:
            try:
                return await self.intelligence.build(asset, market)
            except Exception:  # noqa: BLE001, S110 - intelligence is advisory; fall back to market-only.
                pass
        return AssetFeatureVector(
            asset=asset,
            market=market,
            source_ids=[tick.source.value, *sorted({r.source.value for r in references})],
        )

    async def _build_proposal(
        self,
        asset: str,
        consensus: StrategySignal,
        feature_vector: AssetFeatureVector,
        requested_notional: float,
        tick_age_seconds: float,
        result: PipelineResult,
    ) -> TradeProposal | None:
        if self.meta_agent is None:
            assert consensus.side is not None
            return TradeProposal(
                strategy_id=self.strategy_id,
                asset=asset,
                side=consensus.side,
                confidence=consensus.confidence,
                requested_notional_usd=requested_notional,
                thesis=consensus.rationale,
                signal_ids=[consensus.strategy_id],
                source_freshness_seconds=tick_age_seconds,
            )
        packet = EvidencePacket(
            asset=asset,
            feature_vector=feature_vector,
            strategy_signal=consensus,
            requested_notional_usd=requested_notional,
        )
        try:
            proposal = await self.meta_agent.propose(packet)
        except Exception:  # noqa: BLE001 - meta-agent failure must fail closed, never open.
            result.no_trade_reasons.append("meta_agent_unavailable")
            return None
        if proposal is None:
            result.no_trade_reasons.append("meta_agent_veto")
            return None
        return proposal
