from math import sqrt

from traderstack.candles import Candle


def simple_return(start: float, end: float) -> float:
    if start <= 0:
        raise ValueError("start price must be positive")
    return end / start - 1.0


def mean(values: list[float]) -> float:
    if not values:
        raise ValueError("at least one value is required")
    return sum(values) / len(values)


def standard_deviation(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    avg = mean(values)
    variance = sum((value - avg) ** 2 for value in values) / (len(values) - 1)
    return sqrt(variance)


def moving_average(candles: tuple[Candle, ...], window: int) -> float:
    if window <= 0 or len(candles) < window:
        raise ValueError("insufficient candles for moving average")
    return mean([candle.close for candle in candles[-window:]])


def momentum(candles: tuple[Candle, ...], lookback: int) -> float:
    if lookback <= 0 or len(candles) <= lookback:
        raise ValueError("insufficient candles for momentum")
    return simple_return(candles[-lookback - 1].close, candles[-1].close)


def realized_volatility(candles: tuple[Candle, ...], lookback: int) -> float:
    if lookback <= 1 or len(candles) <= lookback:
        raise ValueError("insufficient candles for realized volatility")
    closes = [candle.close for candle in candles[-lookback - 1 :]]
    returns = [simple_return(closes[index - 1], closes[index]) for index in range(1, len(closes))]
    return standard_deviation(returns)


def volume_ratio(candles: tuple[Candle, ...], lookback: int) -> float:
    if lookback <= 1 or len(candles) < lookback:
        raise ValueError("insufficient candles for volume ratio")
    baseline = mean([candle.volume for candle in candles[-lookback:-1]])
    if baseline <= 0:
        return 0.0
    return candles[-1].volume / baseline


def zscore(value: float, population: list[float]) -> float:
    deviation = standard_deviation(population)
    if deviation == 0:
        return 0.0
    return (value - mean(population)) / deviation
