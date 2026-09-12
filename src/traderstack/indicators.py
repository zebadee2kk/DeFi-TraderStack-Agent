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


def exponential_moving_average(values: list[float], span: int) -> list[float]:
    """EMA series, seed = first value. ``span`` is the common 2/(span+1) form."""
    if span <= 0:
        raise ValueError("EMA span must be positive")
    if not values:
        raise ValueError("at least one value is required")
    alpha = 2.0 / (span + 1)
    out = [values[0]]
    for value in values[1:]:
        out.append(alpha * value + (1.0 - alpha) * out[-1])
    return out


def ema(candles: tuple[Candle, ...], span: int) -> float:
    if len(candles) < span:
        raise ValueError("insufficient candles for EMA")
    return exponential_moving_average([candle.close for candle in candles], span)[-1]


def _true_range(current: Candle, previous: Candle) -> float:
    return max(
        current.high - current.low,
        abs(current.high - previous.close),
        abs(current.low - previous.close),
    )


def _wilder_smooth(values: list[float], period: int) -> list[float]:
    if len(values) < period:
        raise ValueError("insufficient values for Wilder smoothing")
    seed = mean(values[:period])
    out = [seed]
    decay = (period - 1) / period
    gain = 1.0 / period
    for value in values[period:]:
        out.append(out[-1] * decay + value * gain)
    return out


def average_directional_index(candles: tuple[Candle, ...], period: int = 14) -> float:
    """Latest Wilder ADX. Needs ``2 * period + 1`` bars (DM/TR seed + DX seed)."""
    if period <= 1:
        raise ValueError("ADX period must be greater than 1")
    required = 2 * period + 1
    if len(candles) < required:
        raise ValueError("insufficient candles for ADX")
    plus_dm: list[float] = []
    minus_dm: list[float] = []
    true_ranges: list[float] = []
    for index in range(1, len(candles)):
        current = candles[index]
        previous = candles[index - 1]
        up_move = current.high - previous.high
        down_move = previous.low - current.low
        plus = up_move if up_move > down_move and up_move > 0 else 0.0
        minus = down_move if down_move > up_move and down_move > 0 else 0.0
        plus_dm.append(plus)
        minus_dm.append(minus)
        true_ranges.append(_true_range(current, previous))
    smooth_plus = _wilder_smooth(plus_dm, period)
    smooth_minus = _wilder_smooth(minus_dm, period)
    smooth_tr = _wilder_smooth(true_ranges, period)
    dx: list[float] = []
    for plus, minus, tr in zip(smooth_plus, smooth_minus, smooth_tr, strict=True):
        if tr <= 0:
            dx.append(0.0)
            continue
        plus_di = 100.0 * plus / tr
        minus_di = 100.0 * minus / tr
        denom = plus_di + minus_di
        dx.append(0.0 if denom <= 0 else 100.0 * abs(plus_di - minus_di) / denom)
    return _wilder_smooth(dx, period)[-1]
