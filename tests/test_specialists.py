from traderstack.agents.specialists import (
    NarrativeSpecialist,
    OnChainSpecialist,
    SpecialistCommittee,
    TechnicalSpecialist,
)
from traderstack.features import (
    AssetFeatureVector,
    MarketFeatures,
    NarrativeFeatures,
    NewsFeatures,
    OnChainFeatures,
)
from traderstack.models import Side
from traderstack.strategies import Regime


def vector(
    *,
    trend_4h: float = 0.0,
    trend_1d: float = 0.0,
    volatility_z: float = 0.0,
    relative_volume: float = 1.0,
    spread_bps: float = 3.0,
    onchain: OnChainFeatures | None = None,
    narrative: NarrativeFeatures | None = None,
    news: NewsFeatures | None = None,
) -> AssetFeatureVector:
    return AssetFeatureVector(
        asset="BTC",
        market=MarketFeatures(
            trend_4h=trend_4h,
            trend_1d=trend_1d,
            volatility_z=volatility_z,
            relative_volume=relative_volume,
            spread_bps=spread_bps,
        ),
        onchain=onchain or OnChainFeatures(),
        narrative=narrative or NarrativeFeatures(),
        news=news or NewsFeatures(),
    )


def test_technical_specialist_takes_a_side_on_agreeing_trends() -> None:
    signal = TechnicalSpecialist().evaluate(vector(trend_4h=0.6, trend_1d=0.4))

    assert signal.strategy_id == "technical_specialist_v1"
    assert signal.side is Side.BUY
    assert signal.confidence > 0
    assert signal.symbol == "BTC/USD"


def test_technical_specialist_is_flat_when_trends_disagree() -> None:
    assert TechnicalSpecialist().evaluate(vector(trend_4h=0.6, trend_1d=-0.6)).side is None


def test_technical_specialist_blocks_on_wide_spread_and_wild_volatility() -> None:
    wide = TechnicalSpecialist().evaluate(vector(trend_4h=0.8, trend_1d=0.8, spread_bps=99))
    wild = TechnicalSpecialist().evaluate(vector(trend_4h=0.8, trend_1d=0.8, volatility_z=9))
    thin = TechnicalSpecialist().evaluate(vector(trend_4h=0.8, trend_1d=0.8, relative_volume=0.05))

    assert wide.side is None and "spread_too_wide" in wide.rationale
    assert wild.side is None and "volatility_out_of_band" in wild.rationale
    assert thin.side is None and "participation_too_low" in thin.rationale


def test_technical_thresholds_are_constructor_parameters() -> None:
    lenient = TechnicalSpecialist(trend_threshold=0.01)
    strict = TechnicalSpecialist(trend_threshold=0.9)
    features = vector(trend_4h=0.2, trend_1d=0.2)

    assert lenient.evaluate(features).side is Side.BUY
    assert strict.evaluate(features).side is None


def test_onchain_specialist_reads_outflow_as_bullish() -> None:
    signal = OnChainSpecialist().evaluate(
        vector(onchain=OnChainFeatures(exchange_netflow_z=-2.0, large_wallet_accumulation=0.5))
    )

    assert signal.strategy_id == "onchain_specialist_v1"
    assert signal.side is Side.BUY
    assert signal.score > 0


def test_onchain_specialist_reads_inflow_as_bearish() -> None:
    signal = OnChainSpecialist().evaluate(
        vector(onchain=OnChainFeatures(exchange_netflow_z=2.0, large_wallet_accumulation=-0.5))
    )

    assert signal.side is Side.SELL


def test_onchain_specialist_emits_nothing_without_onchain_evidence() -> None:
    signal = OnChainSpecialist().evaluate(vector())

    assert signal.side is None
    assert signal.confidence == 0.0
    assert "no on-chain evidence" in signal.rationale


def test_narrative_specialist_combines_sentiment_and_mentions() -> None:
    signal = NarrativeSpecialist().evaluate(
        vector(narrative=NarrativeFeatures(sentiment=0.6, mention_velocity_z=2.0))
    )

    assert signal.strategy_id == "narrative_specialist_v1"
    assert signal.side is Side.BUY


def test_narrative_specialist_is_suppressed_by_an_adverse_event() -> None:
    signal = NarrativeSpecialist().evaluate(
        vector(
            narrative=NarrativeFeatures(sentiment=0.9, mention_velocity_z=3.0),
            news=NewsFeatures(event_score=0.9, adverse_event=True),
        )
    )

    assert signal.side is None
    assert "adverse_event" in signal.rationale


def test_narrative_specialist_is_suppressed_by_a_hot_event_tape() -> None:
    signal = NarrativeSpecialist(max_event_score=0.5).evaluate(
        vector(
            narrative=NarrativeFeatures(sentiment=0.9),
            news=NewsFeatures(event_score=0.8, adverse_event=False),
        )
    )

    assert signal.side is None
    assert "event_score_above_maximum" in signal.rationale


def test_committee_reaches_consensus_when_two_specialists_agree() -> None:
    committee = SpecialistCommittee()
    signals = committee.evaluate(
        vector(
            trend_4h=0.6,
            trend_1d=0.5,
            onchain=OnChainFeatures(exchange_netflow_z=-2.5),
            narrative=NarrativeFeatures(sentiment=0.1),
        ),
        Regime.TRENDING_UP,
    )
    consensus = committee.consensus(signals)

    assert len(signals) == 3
    assert consensus is not None
    assert consensus.strategy_id == "specialist_committee_v1"
    assert consensus.side is Side.BUY
    assert consensus.regime is Regime.TRENDING_UP


def test_committee_has_no_consensus_from_a_single_specialist() -> None:
    committee = SpecialistCommittee()
    signals = committee.evaluate(vector(trend_4h=0.9, trend_1d=0.9))

    assert committee.consensus(signals) is None


def test_committee_has_no_consensus_when_specialists_split() -> None:
    committee = SpecialistCommittee()
    signals = committee.evaluate(
        vector(
            trend_4h=0.9,
            trend_1d=0.9,
            onchain=OnChainFeatures(exchange_netflow_z=3.0),
        )
    )

    assert committee.consensus(signals) is None


def test_specialists_are_deterministic() -> None:
    committee = SpecialistCommittee()
    features = vector(
        trend_4h=0.4,
        trend_1d=0.3,
        onchain=OnChainFeatures(exchange_netflow_z=-1.2),
        narrative=NarrativeFeatures(sentiment=0.4),
    )

    first = committee.evaluate(features)
    second = committee.evaluate(features)

    assert [s.model_dump() for s in first] == [s.model_dump() for s in second]
