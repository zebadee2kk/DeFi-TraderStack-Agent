from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic import BaseModel, Field

from traderstack.candles import Candle
from traderstack.features import AssetFeatureVector, MarketFeatures
from traderstack.intelligence import merge_external_intelligence
from traderstack.intelligence_orchestrator import ExternalIntelligence
from traderstack.market.models import MarketTick, ReferencePrice
from traderstack.market.validation import is_reference_consistent
from traderstack.market_features import CandleMarketFeatureBuilder
from traderstack.models import PortfolioSnapshot, RiskDecision, RiskResult, Side, TradeProposal
from traderstack.pretrade import PreTradeBacktestGate, PreTradeCheck
from traderstack.risk import RiskEngine


class PaperOrderIntent(BaseModel):
    decision_id: str
    asset: str
    side: Side
    notional_usd: float = Field(gt=0)
    venue: str = "kraken_paper_trade"


class PipelineResult(BaseModel):
    accepted_market_data: bool
    rejection_reasons: list[str] = Field(default_factory=list)
    feature_vector: AssetFeatureVector | None = None
    pretrade_check: PreTradeCheck | None = None
    proposal: TradeProposal | None = None
    risk_result: RiskResult | None = None
    paper_order: PaperOrderIntent | None = None


@dataclass(frozen=True)
class VerticalSlicePipeline:
    risk_engine: RiskEngine
    max_tick_age_seconds: float = 10.0
    max_spread_bps: float = 30.0
    max_reference_divergence_bps: float = 100.0
    demonstration_notional_pct: float = 0.01
    pretrade_gate: PreTradeBacktestGate | None = None
    feature_builder: CandleMarketFeatureBuilder | None = None
    # Deterministic news rule: an adverse event flagged by the news providers
    # blocks new risk this cycle. Existing positions are untouched.
    block_on_adverse_news: bool = True
    # When set, a cycle with no external intelligence at all is rejected
    # instead of proceeding on market data alone.
    require_external_intelligence: bool = False

    def process(
        self,
        tick: MarketTick,
        references: list[ReferencePrice],
        portfolio: PortfolioSnapshot,
        candles: tuple[Candle, ...] | None = None,
        intelligence: ExternalIntelligence | None = None,
    ) -> PipelineResult:
        asset = tick.symbol.split("/", 1)[0].upper()
        now = datetime.now(UTC)
        reasons: list[str] = []

        age_seconds = max(0.0, (now - tick.observed_at).total_seconds())
        if age_seconds > self.max_tick_age_seconds:
            reasons.append("stale_primary_tick")
        if tick.spread_bps > self.max_spread_bps:
            reasons.append("spread_limit_exceeded")

        eligible = [r for r in references if r.asset.upper() == asset and r.currency == "USD"]
        primary = ReferencePrice(
            source=tick.source,
            asset=asset,
            currency="USD",
            observed_at=tick.observed_at,
            price=tick.last,
        )
        if not eligible:
            reasons.append("no_independent_reference_price")
        elif not is_reference_consistent(primary, eligible, self.max_reference_divergence_bps):
            reasons.append("reference_price_divergence")

        if reasons:
            return PipelineResult(accepted_market_data=False, rejection_reasons=reasons)

        source_ids = [tick.source.value, *sorted({r.source.value for r in eligible})]
        market = MarketFeatures(
            trend_4h=0.0,
            trend_1d=0.0,
            volatility_z=0.0,
            relative_volume=1.0,
            spread_bps=tick.spread_bps,
        )
        if candles and self.feature_builder is not None:
            market = self.feature_builder.build(candles, spread_bps=tick.spread_bps)
            source_ids.append(f"candles:{candles[-1].interval}")

        if intelligence is not None and intelligence.asset.upper() != asset:
            intelligence = None
        if intelligence is not None:
            feature_vector = merge_external_intelligence(
                asset,
                market,
                onchain=intelligence.onchain,
                social=intelligence.social,
                news=intelligence.news,
            )
            feature_vector.source_ids = [*source_ids, *feature_vector.source_ids]
        else:
            feature_vector = AssetFeatureVector(asset=asset, market=market, source_ids=source_ids)

        if self.require_external_intelligence and (intelligence is None or intelligence.is_empty):
            return PipelineResult(
                accepted_market_data=True,
                rejection_reasons=["no_external_intelligence"],
                feature_vector=feature_vector,
            )
        if self.block_on_adverse_news and feature_vector.news.adverse_event:
            return PipelineResult(
                accepted_market_data=True,
                rejection_reasons=["adverse_news_event"],
                feature_vector=feature_vector,
            )

        side = Side.BUY
        confidence = 0.5
        thesis = "Deterministic integration-test proposal after validated market inputs."
        signal_ids = ["validated-market-data-v1"]
        pretrade_check: PreTradeCheck | None = None
        if self.pretrade_gate is not None:
            if not candles:
                return PipelineResult(
                    accepted_market_data=True,
                    rejection_reasons=["missing_candle_history"],
                    feature_vector=feature_vector,
                )
            pretrade_check = self.pretrade_gate.evaluate(candles, now=now)
            if not pretrade_check.passed or pretrade_check.confirmed_side is None:
                return PipelineResult(
                    accepted_market_data=True,
                    rejection_reasons=list(pretrade_check.reasons),
                    feature_vector=feature_vector,
                    pretrade_check=pretrade_check,
                )
            side = pretrade_check.confirmed_side
            confidence = pretrade_check.confidence
            thesis = pretrade_check.rationale or thesis
            signal_ids = ["pretrade-backtest-gate-v1"]

        requested_notional = portfolio.nav_usd * self.demonstration_notional_pct
        proposal = TradeProposal(
            strategy_id="vertical-slice-v1",
            asset=asset,
            side=side,
            confidence=confidence,
            requested_notional_usd=requested_notional,
            thesis=thesis,
            signal_ids=signal_ids,
            source_freshness_seconds=age_seconds,
        )
        risk_result = self.risk_engine.evaluate(proposal, portfolio)
        paper_order = None
        if risk_result.decision in {RiskDecision.ALLOW, RiskDecision.REDUCE} and risk_result.approved_notional_usd > 0:
            paper_order = PaperOrderIntent(
                decision_id=str(proposal.decision_id),
                asset=asset,
                side=proposal.side,
                notional_usd=risk_result.approved_notional_usd,
            )

        return PipelineResult(
            accepted_market_data=True,
            feature_vector=feature_vector,
            pretrade_check=pretrade_check,
            proposal=proposal,
            risk_result=risk_result,
            paper_order=paper_order,
        )
