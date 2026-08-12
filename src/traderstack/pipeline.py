from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic import BaseModel, Field

from traderstack.features import AssetFeatureVector, MarketFeatures
from traderstack.market.models import MarketSource, MarketTick, ReferencePrice
from traderstack.market.validation import is_reference_consistent
from traderstack.models import PortfolioSnapshot, RiskDecision, RiskResult, Side, TradeProposal
from traderstack.risk import RiskEngine
from traderstack.strategies import Regime, StrategySignal


class PaperOrderIntent(BaseModel):
    decision_id: str
    asset: str
    side: Side
    notional_usd: float = Field(gt=0)
    venue: str = "kraken_paper_trade"


class PipelineResult(BaseModel):
    accepted_market_data: bool
    rejection_reasons: list[str] = Field(default_factory=list)
    no_trade_reasons: list[str] = Field(default_factory=list)
    regime: Regime | None = None
    signals: list[StrategySignal] = Field(default_factory=list)
    feature_vector: AssetFeatureVector | None = None
    proposal: TradeProposal | None = None
    risk_result: RiskResult | None = None
    paper_order: PaperOrderIntent | None = None


class MarketGateOutcome(BaseModel):
    reasons: list[str] = Field(default_factory=list)
    eligible_references: list[ReferencePrice] = Field(default_factory=list)
    tick_age_seconds: float = Field(ge=0)


def validate_market_inputs(
    tick: MarketTick,
    references: list[ReferencePrice],
    *,
    max_tick_age_seconds: float,
    max_spread_bps: float,
    max_reference_divergence_bps: float,
) -> MarketGateOutcome:
    """Shared deterministic market-data quality gate for all pipelines."""
    asset = tick.symbol.split("/", 1)[0].upper()
    now = datetime.now(UTC)
    reasons: list[str] = []

    age_seconds = max(0.0, (now - tick.observed_at).total_seconds())
    if age_seconds > max_tick_age_seconds:
        reasons.append("stale_primary_tick")
    if tick.spread_bps > max_spread_bps:
        reasons.append("spread_limit_exceeded")

    eligible = [r for r in references if r.asset.upper() == asset and r.currency == "USD"]
    primary = ReferencePrice(
        source=MarketSource.KRAKEN,
        asset=asset,
        currency="USD",
        observed_at=tick.observed_at,
        price=tick.last,
    )
    if not eligible:
        reasons.append("no_independent_reference_price")
    elif not is_reference_consistent(primary, eligible, max_reference_divergence_bps):
        reasons.append("reference_price_divergence")

    return MarketGateOutcome(
        reasons=reasons,
        eligible_references=eligible,
        tick_age_seconds=age_seconds,
    )


@dataclass(frozen=True)
class VerticalSlicePipeline:
    risk_engine: RiskEngine
    max_tick_age_seconds: float = 10.0
    max_spread_bps: float = 30.0
    max_reference_divergence_bps: float = 100.0
    demonstration_notional_pct: float = 0.01

    def process(
        self,
        tick: MarketTick,
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
        eligible = gate.eligible_references
        age_seconds = gate.tick_age_seconds

        feature_vector = AssetFeatureVector(
            asset=asset,
            market=MarketFeatures(
                trend_4h=0.0,
                trend_1d=0.0,
                volatility_z=0.0,
                relative_volume=1.0,
                spread_bps=tick.spread_bps,
            ),
            source_ids=[tick.source.value, *sorted({r.source.value for r in eligible})],
        )

        requested_notional = portfolio.nav_usd * self.demonstration_notional_pct
        proposal = TradeProposal(
            strategy_id="vertical-slice-v1",
            asset=asset,
            side=Side.BUY,
            confidence=0.5,
            requested_notional_usd=requested_notional,
            thesis="Deterministic integration-test proposal after validated market inputs.",
            signal_ids=["validated-market-data-v1"],
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
            proposal=proposal,
            risk_result=risk_result,
            paper_order=paper_order,
        )
