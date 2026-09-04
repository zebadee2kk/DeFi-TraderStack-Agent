from datetime import UTC, datetime, timedelta

from traderstack.candles import Candle
from traderstack.market_features import CandleMarketFeatureBuilder
from traderstack.signal_registry import SignalRegistry, params_hash, version_of
from traderstack.strategies import MomentumStrategy, StrategyEnsemble


def make_candles(count: int = 60) -> tuple[Candle, ...]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    candles: list[Candle] = []
    price = 100.0
    for index in range(count):
        previous = price
        price = price + 0.5
        candles.append(
            Candle(
                symbol="BTC/USD",
                interval="1h",
                opened_at=start + timedelta(hours=index),
                open=previous,
                high=max(previous, price) * 1.001,
                low=min(previous, price) * 0.999,
                close=price,
                volume=1_000 + index,
            )
        )
    return tuple(candles)


def test_same_params_yield_same_version() -> None:
    a = MomentumStrategy(lookback=12, minimum_momentum=0.02)
    b = MomentumStrategy(lookback=12, minimum_momentum=0.02)
    assert version_of(a) == version_of(b)


def test_changing_a_parameter_changes_the_version() -> None:
    a = MomentumStrategy(lookback=12)
    b = MomentumStrategy(lookback=13)
    assert version_of(a) != version_of(b)


def test_version_includes_the_class_name() -> None:
    version = version_of(MomentumStrategy())
    assert version.startswith("MomentumStrategy:")


def test_nested_ensemble_parameters_affect_the_version() -> None:
    default_ensemble = StrategyEnsemble()
    tuned_ensemble = StrategyEnsemble(momentum_strategy=MomentumStrategy(lookback=99))
    assert version_of(default_ensemble) != version_of(tuned_ensemble)


def test_feature_builder_version_changes_with_lookback() -> None:
    a = CandleMarketFeatureBuilder(trend_4h_lookback=4)
    b = CandleMarketFeatureBuilder(trend_4h_lookback=8)
    assert version_of(a) != version_of(b)


def test_params_hash_is_deterministic_and_short() -> None:
    strategy = MomentumStrategy()
    first = params_hash(strategy)
    second = params_hash(strategy)
    assert first == second
    assert len(first) == 12


def test_signal_registry_records_and_looks_up_versions() -> None:
    registry = SignalRegistry()
    ensemble = StrategyEnsemble()
    entry = registry.register("baseline_ensemble", ensemble, kind="ensemble")
    assert entry.version == version_of(ensemble)
    assert registry.get("baseline_ensemble") == entry
    assert registry.get("missing") is None
    assert entry in registry.all()


def test_ensemble_consensus_populates_signal_version() -> None:
    ensemble = StrategyEnsemble()
    candles = make_candles()
    _regime, signals = ensemble.evaluate(candles)
    consensus = ensemble.consensus(signals)
    assert consensus is not None
    assert consensus.signal_version == version_of(ensemble)

    # Signals from the individual strategies are unaffected (still optional/None).
    assert all(signal.signal_version is None for signal in signals)
