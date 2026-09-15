from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic import BaseModel, Field

from traderstack.candles import Candle
from traderstack.exits import (
    ExitSignal,
    bar_seconds_for,
    evaluate_position_exits,
    exit_strategy_id,
)
from traderstack.features import AssetFeatureVector, MarketFeatures, ResearchEdgeFeatures
from traderstack.intelligence import merge_external_intelligence
from traderstack.intelligence_orchestrator import ExternalIntelligence
from traderstack.market.models import MarketTick, PriceDivergence, ReferencePrice
from traderstack.market.validation import is_reference_consistent, pairwise_divergences
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
    # --- protective-exit sizing (#130) ---
    # Set only by the deterministic exit path. The execution boundary may
    # clamp such an order DOWN to the held quantity (never up); entry orders
    # leave it False so the clamp can never resize an entry.
    reduce_only: bool = False


class PipelineResult(BaseModel):
    accepted_market_data: bool
    rejection_reasons: list[str] = Field(default_factory=list)
    feature_vector: AssetFeatureVector | None = None
    pretrade_check: PreTradeCheck | None = None
    proposal: TradeProposal | None = None
    risk_result: RiskResult | None = None
    paper_order: PaperOrderIntent | None = None
    # --- providers (Epic 2): provider divergence event -------------------------
    # Every pairwise reference-price divergence beyond max_reference_divergence_bps
    # (not only primary-vs-reference), so it lands in the audit trail regardless
    # of whether the cycle was otherwise accepted.
    divergences: list[PriceDivergence] = Field(default_factory=list)
    # --- position management (#58) ---
    # Set when this cycle's proposal is a deterministic exit (stop/TP/time/...).
    exit_reason: str | None = None


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
        # --- paper-research edge data plane ---
        # Optional; informational. Merged onto the feature vector after market
        # data is accepted. RiskEngine does not read these fields to size or
        # authorize a trade.
        edge: ResearchEdgeFeatures | None = None,
        edge_source_ids: tuple[str, ...] = (),
        *,
        now: datetime | None = None,
    ) -> PipelineResult:
        asset = tick.symbol.split("/", 1)[0].upper()
        now = now or datetime.now(UTC)
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
        # --- providers (Epic 2): provider divergence event --------------------
        divergences = pairwise_divergences(primary, eligible, self.max_reference_divergence_bps)

        if reasons:
            return PipelineResult(
                accepted_market_data=False, rejection_reasons=reasons, divergences=divergences
            )

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
                # --- providers (Epic 3): altFINS technical-signal slot --------
                altfins=intelligence.altfins,
            )
            feature_vector.source_ids = [*source_ids, *feature_vector.source_ids]
        else:
            feature_vector = AssetFeatureVector(asset=asset, market=market, source_ids=source_ids)

        # --- paper-research edge data plane ---
        if edge is not None:
            feature_vector = feature_vector.model_copy(
                update={
                    "edge": edge,
                    "source_ids": [*feature_vector.source_ids, *edge_source_ids],
                }
            )

        # --- position management (#58) ---
        # Price/time exits run after market-data validation and BEFORE the
        # intelligence / pre-trade gates so an adverse-news, Crucix-outage, or
        # missing-candle reject cannot freeze a stop-loss. Kill switch still
        # withholds.
        price_exit = self._exit_result(
            asset=asset,
            tick=tick,
            portfolio=portfolio,
            feature_vector=feature_vector,
            divergences=divergences,
            age_seconds=age_seconds,
            candles=candles,
            now=now,
        )
        if price_exit is not None:
            return price_exit

        # --- paper daily promote universe (#100 honesty) ---
        # After exits so a leftover SOL position can still de-risk.
        # New risk on a name outside the BTC/USD + ETH/USD envelope is
        # skipped with an explicit reason, not scored under the daily pin.
        if not self.risk_engine.settings.promote_universe_allows(tick.symbol):
            return PipelineResult(
                accepted_market_data=True,
                rejection_reasons=["promote_universe_excluded"],
                feature_vector=feature_vector,
                divergences=divergences,
            )

        # --- crucix fail-closed ---
        # An opted-in fail-closed news provider (Crucix) that errored or
        # timed out blocks new risk. Distinct from adverse_news_event.
        # Existing positions/exits already ran above.
        if intelligence is not None and intelligence.provider_unavailable:
            return PipelineResult(
                accepted_market_data=True,
                rejection_reasons=["intelligence_provider_unavailable"],
                feature_vector=feature_vector,
                divergences=divergences,
            )
        if self.require_external_intelligence and (intelligence is None or intelligence.is_empty):
            return PipelineResult(
                accepted_market_data=True,
                rejection_reasons=["no_external_intelligence"],
                feature_vector=feature_vector,
                divergences=divergences,
            )
        if self.block_on_adverse_news and feature_vector.news.adverse_event:
            return PipelineResult(
                accepted_market_data=True,
                rejection_reasons=["adverse_news_event"],
                feature_vector=feature_vector,
                divergences=divergences,
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
                    divergences=divergences,
                )
            pretrade_check = self.pretrade_gate.evaluate(candles, now=now)
            thesis_exit = self._exit_result(
                asset=asset,
                tick=tick,
                portfolio=portfolio,
                feature_vector=feature_vector,
                divergences=divergences,
                age_seconds=age_seconds,
                candles=candles,
                now=now,
                pretrade_check=pretrade_check,
            )
            if thesis_exit is not None:
                return thesis_exit
            if not pretrade_check.passed or pretrade_check.confirmed_side is None:
                return PipelineResult(
                    accepted_market_data=True,
                    rejection_reasons=list(pretrade_check.reasons),
                    feature_vector=feature_vector,
                    pretrade_check=pretrade_check,
                    divergences=divergences,
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
        # --- risk plane (Epic 7) --- the feature vector carries the realized
        # volatility and spread the risk engine sizes and gates on.
        risk_result = self.risk_engine.evaluate(proposal, portfolio, feature_vector)
        paper_order = None
        if (
            risk_result.decision in {RiskDecision.ALLOW, RiskDecision.REDUCE}
            and risk_result.approved_notional_usd > 0
        ):
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
            divergences=divergences,
        )

    # --- position management (#58) ---
    def _exit_result(
        self,
        *,
        asset: str,
        tick: MarketTick,
        portfolio: PortfolioSnapshot,
        feature_vector: AssetFeatureVector,
        divergences: list[PriceDivergence],
        age_seconds: float,
        candles: tuple[Candle, ...] | None,
        now: datetime,
        pretrade_check: PreTradeCheck | None = None,
    ) -> PipelineResult | None:
        settings = self.risk_engine.settings
        held = portfolio.held_positions.get(asset)
        if held is None or held.quantity <= 0:
            return None
        interval = candles[-1].interval if candles else None
        signal = evaluate_position_exits(
            settings=settings,
            asset=asset,
            position=held,
            mark_price_usd=tick.last,
            now=now,
            bar_seconds=bar_seconds_for(settings, interval),
            confirmed_side=pretrade_check.confirmed_side if pretrade_check else None,
            regime=pretrade_check.regime if pretrade_check else None,
        )
        if signal is None:
            return None
        return self._build_exit_result(
            signal=signal,
            portfolio=portfolio,
            feature_vector=feature_vector,
            divergences=divergences,
            age_seconds=age_seconds,
            pretrade_check=pretrade_check,
            now=now,
        )

    def _build_exit_result(
        self,
        *,
        signal: ExitSignal,
        portfolio: PortfolioSnapshot,
        feature_vector: AssetFeatureVector,
        divergences: list[PriceDivergence],
        age_seconds: float,
        pretrade_check: PreTradeCheck | None,
        now: datetime,
    ) -> PipelineResult:
        proposal = TradeProposal(
            strategy_id=exit_strategy_id(signal.reason),
            asset=signal.asset,
            side=signal.side,
            confidence=1.0,
            requested_notional_usd=signal.requested_notional_usd,
            thesis=(
                f"Deterministic {signal.reason.value}: mark {signal.mark_price_usd:.6g} "
                f"vs entry {signal.entry_price_usd:.6g}."
            ),
            signal_ids=[signal.reason.value],
            source_freshness_seconds=age_seconds,
            created_at=now,
        )
        risk_result = self.risk_engine.evaluate(proposal, portfolio, feature_vector, now=now)
        paper_order = None
        if (
            risk_result.decision in {RiskDecision.ALLOW, RiskDecision.REDUCE}
            and risk_result.approved_notional_usd > 0
        ):
            paper_order = PaperOrderIntent(
                decision_id=str(proposal.decision_id),
                asset=signal.asset,
                side=signal.side,
                notional_usd=risk_result.approved_notional_usd,
                # --- protective-exit sizing (#130) ---
                reduce_only=True,
            )
        return PipelineResult(
            accepted_market_data=True,
            feature_vector=feature_vector,
            pretrade_check=pretrade_check,
            proposal=proposal,
            risk_result=risk_result,
            paper_order=paper_order,
            divergences=divergences,
            exit_reason=signal.reason.value,
        )
