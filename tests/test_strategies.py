from datetime import UTC, datetime, timedelta

from traderstack.candles import Candle, CandleHistory
from traderstack.models import Side
from traderstack.strategies import Regime, RegimeClassifier, StrategyEnsemble


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
