from datetime import UTC, datetime, timedelta

from traderstack.candles import Candle, CandleHistory
from traderstack.models import Side
from traderstack.strategies import (
    PaperResearchStrategy,
    Regime,
    RegimeClassifier,
    StrategyEnsemble,
    StrategySignal,
    combine_signals,
)


def make_candles(prices: list[float], symbol: str = "BTC/USD") -> tuple[Candle, ...]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    candles = []
    for index, price in enumerate(prices):
        previous = prices[index - 1] if index else price
        high = max(previous, price) * 1.001
        low = min(previous, price) * 0.999
        candles.append(
            Candle(
                symbol=symbol,
                interval="1h",
                opened_at=start + timedelta(hours=index),
                open=previous,
                high=high,
                low=low,
                close=price,
                volume=100 + index,
            )
        )
    return tuple(candles)


def test_candle_history_rejects_out_of_order_data() -> None:
    history = CandleHistory()
    candles = make_candles([100, 101])
    history.append(candles[1])
    try:
        history.append(candles[0])
    except ValueError as exc:
        assert "strictly increasing" in str(exc)
    else:
        raise AssertionError("expected out-of-order candle to be rejected")


def test_uptrend_regime_and_consensus_buy() -> None:
    prices = [100 + index * 1.5 for index in range(60)]
    candles = make_candles(prices)
    ensemble = StrategyEnsemble()

    regime, signals = ensemble.evaluate(candles)
    consensus = ensemble.consensus(signals)

    assert regime is Regime.TRENDING_UP
    assert consensus is not None
    assert consensus.side is Side.BUY
    assert consensus.confidence > 0


def test_flat_market_classifies_as_range() -> None:
    prices = [100 + (0.1 if index % 2 else -0.1) for index in range(60)]
    regime = RegimeClassifier().classify(make_candles(prices))
    assert regime is Regime.RANGE


def mild_uptrend_prices(count: int = 60) -> list[float]:
    """~0.8% per 12 bars — enough for a MA tilt, not the 2% momentum bar."""
    return [100.0 + index * 0.08 for index in range(count)]


def test_mild_kraken_like_uptrend_has_no_default_consensus() -> None:
    """Typical paper OHLC: trend may fire, momentum does not, two-voter bar fails."""
    candles = make_candles(mild_uptrend_prices())
    ensemble = StrategyEnsemble()
    _regime, signals = ensemble.evaluate(candles)
    assert ensemble.paper_research_strategy is None
    assert ensemble.min_agreeing == 2
    assert ensemble.consensus(signals) is None
    sides = {signal.strategy_id: signal.side for signal in signals}
    assert sides["momentum_v1"] is None
    assert sides["mean_reversion_v1"] is None


def test_paper_research_baseline_votes_on_mild_uptrend() -> None:
    candles = make_candles(mild_uptrend_prices())
    signal = PaperResearchStrategy().evaluate(candles, Regime.TRENDING_UP)
    assert signal.strategy_id == "paper_research_baseline_v1"
    assert signal.side is Side.BUY
    assert signal.confidence > 0


def test_paper_research_baseline_is_flat_on_identical_prices() -> None:
    candles = make_candles([100.0] * 60)
    signal = PaperResearchStrategy().evaluate(candles, Regime.RANGE)
    assert signal.side is None


def test_paper_research_ensemble_reaches_consensus_on_mild_uptrend() -> None:
    candles = make_candles(mild_uptrend_prices())
    ensemble = StrategyEnsemble(
        paper_research_strategy=PaperResearchStrategy(),
        min_agreeing=1,
    )
    _regime, signals = ensemble.evaluate(candles)
    assert len(signals) == 4
    consensus = ensemble.consensus(signals)
    assert consensus is not None
    assert consensus.side is Side.BUY
    assert "paper-research" in (consensus.rationale or "")


def test_combine_signals_split_vote_is_no_consensus() -> None:
    buy = StrategySignal(
        strategy_id="a",
        symbol="BTC/USD",
        side=Side.BUY,
        score=0.5,
        confidence=0.5,
        regime=Regime.RANGE,
        rationale="buy",
    )
    sell = StrategySignal(
        strategy_id="b",
        symbol="BTC/USD",
        side=Side.SELL,
        score=-0.5,
        confidence=0.5,
        regime=Regime.RANGE,
        rationale="sell",
    )
    assert combine_signals((buy, buy, sell, sell), strategy_id="tie") is None
    assert combine_signals((buy, sell), strategy_id="tie") is None


def test_combine_signals_min_agreeing_one_allows_a_single_voter() -> None:
    buy = StrategySignal(
        strategy_id="solo",
        symbol="BTC/USD",
        side=Side.BUY,
        score=0.4,
        confidence=0.4,
        regime=Regime.RANGE,
        rationale="solo",
    )
    flat = StrategySignal(
        strategy_id="quiet",
        symbol="BTC/USD",
        side=None,
        score=0.0,
        confidence=0.0,
        regime=Regime.RANGE,
        rationale="quiet",
    )
    assert combine_signals((buy, flat, flat), strategy_id="need-two") is None
    consensus = combine_signals((buy, flat, flat), strategy_id="need-one", min_agreeing=1)
    assert consensus is not None
    assert consensus.side is Side.BUY
