"""Model-implied probability versus CLOB mid (research edge, not a claim).

The NWP high is treated as the mean of a Normal with operator-configured
sigma. That sigma is a *research assumption*, not a calibrated skill score.
Do not treat a positive ``net_edge`` as evidence the strategy wins — see
``docs/EVALUATION-FRAMEWORK.md`` (Polymarket weather A/B requirements).
"""

from __future__ import annotations

import math

from traderstack.polymarket.models import (
    ContractSide,
    EdgeCalculation,
    ForecastPoint,
    ParsedTemperatureMarket,
    TemperatureContract,
)


def normal_cdf(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def _clip01(value: float) -> float:
    return min(1.0, max(0.0, value))


def model_probability(market: ParsedTemperatureMarket, forecast: ForecastPoint) -> float:
    if forecast.sigma_f <= 0:
        raise ValueError("forecast sigma_f must be > 0")
    mean = forecast.high_f
    sigma = forecast.sigma_f
    if market.contract is TemperatureContract.THRESHOLD_OR_HIGHER:
        if market.threshold_f is None:
            raise ValueError("threshold contract missing threshold_f")
        # Continuity correction: P(T >= threshold) using the high-temp point.
        z = (market.threshold_f - mean) / sigma
        return _clip01(1.0 - normal_cdf(z))
    # --- polymarket weather PIT tape (#141) ---
    if market.contract is TemperatureContract.THRESHOLD_OR_LOWER:
        if market.threshold_f is None:
            raise ValueError("threshold contract missing threshold_f")
        # Readings are whole °F, so "77°F or below" is P(T < 78) under the
        # same [low, high+1) convention the bucket branch uses.
        z = (market.threshold_f + 1.0 - mean) / sigma
        return _clip01(normal_cdf(z))
    if market.bucket_low_f is None or market.bucket_high_f is None:
        raise ValueError("bucket contract missing bounds")
    # Inclusive integer-°F buckets are modelled as [low, high+1) in continuous °F.
    z_low = (market.bucket_low_f - mean) / sigma
    z_high = (market.bucket_high_f + 1.0 - mean) / sigma
    return _clip01(normal_cdf(z_high) - normal_cdf(z_low))


def calculate_edge(
    market: ParsedTemperatureMarket,
    forecast: ForecastPoint,
    market_mid: float,
    *,
    fee_haircut: float,
) -> EdgeCalculation:
    if not 0.0 <= market_mid <= 1.0:
        raise ValueError("market_mid must be a probability-like price in [0, 1]")
    if not 0.0 <= fee_haircut < 1.0:
        raise ValueError("fee_haircut must be in [0, 1)")
    model = model_probability(market, forecast)
    raw = model - market_mid
    if raw >= 0:
        side = ContractSide.YES
        net = raw - fee_haircut
    else:
        side = ContractSide.NO
        net = (-raw) - fee_haircut
    return EdgeCalculation(
        model_probability=model,
        market_mid=market_mid,
        raw_edge=raw,
        net_edge=net,
        side=side,
        fee_haircut=fee_haircut,
    )
