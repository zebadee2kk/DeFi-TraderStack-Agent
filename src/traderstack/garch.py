"""Minimal GARCH(1,1) walk-forward volatility forecast and vol-targeted size.

This is a sizing layer, not a direction model. Every public helper is a
function of returns that already exist at the decision bar — parameters are
estimated on a strictly earlier window, then the recursion is rolled one
step with the latest observed residual. That is the same no-lookahead
contract as milesdeutscher/garchmethod (MIT): ``σ²_t = ω + α ε²_{t-1} +
β σ²_{t-1}``, size ``target_vol / forecast_vol`` clipped to
``[min_size, max_size]`` (default ``[0.25, 2.0]``).

The implementation is pure Python (Gaussian, variance-targeting MLE). We
do not vendor ``arch`` / numpy. Credit for the *method family*: Engle
(ARCH) and Bollerslev (GARCH). Credit for the composition pattern
(walk-forward refit + capped vol targeting as a size overlay on an
independent direction signal): the public garchmethod skill. We do not
copy claimed PnL.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import log, sqrt

from traderstack.candles import Candle, periods_per_year

HONESTY_NOTE = (
    "GARCH forecasts magnitude (volatility), not direction. It tells you how "
    "violent the next bar is likely to be — not which way it goes."
)

DEFAULT_MIN_TRAIN = 120
DEFAULT_REFIT_EVERY = 21
DEFAULT_TARGET_VOL_ANN = 0.50
DEFAULT_MIN_SIZE = 0.25
DEFAULT_MAX_SIZE = 2.0
DEFAULT_REGIME_LOOKBACK = 365
_GRID_ALPHA = (0.02, 0.04, 0.06, 0.08, 0.10, 0.15, 0.20)
_GRID_BETA = (0.70, 0.80, 0.85, 0.90, 0.94, 0.97)
_VAR_FLOOR = 1e-12
_IMPOSSIBLE = 1e18


@dataclass(frozen=True)
class GarchParams:
    omega: float
    alpha: float
    beta: float
    variance: float


@dataclass(frozen=True)
class GarchForecast:
    """One-step-ahead forecast made at the close of the bar that produced it."""

    variance: float
    vol: float
    vol_ann: float
    size_multiplier: float
    regime: str
    vol_percentile: float | None
    note: str = HONESTY_NOTE


def close_returns(closes: list[float]) -> list[float]:
    """Simple close-to-close returns. Skips a pair only if a price is non-positive."""
    out: list[float] = []
    for index in range(1, len(closes)):
        start = closes[index - 1]
        end = closes[index]
        if start <= 0 or end <= 0:
            raise ValueError("close prices must be positive")
        out.append(end / start - 1.0)
    return out


def candle_returns(candles: tuple[Candle, ...]) -> list[float]:
    return close_returns([candle.close for candle in candles])


def sample_variance(returns: list[float]) -> float:
    if len(returns) < 2:
        raise ValueError("at least two returns are required")
    mean = sum(returns) / len(returns)
    return sum((value - mean) ** 2 for value in returns) / (len(returns) - 1)


def size_from_vol(
    forecast_vol_ann: float,
    target_vol_ann: float = DEFAULT_TARGET_VOL_ANN,
    *,
    min_size: float = DEFAULT_MIN_SIZE,
    max_size: float = DEFAULT_MAX_SIZE,
) -> float:
    """``target / forecast``, clipped. Non-positive forecast → ``min_size``."""
    if min_size <= 0 or max_size < min_size:
        raise ValueError("size caps must satisfy 0 < min_size <= max_size")
    if forecast_vol_ann <= 0 or target_vol_ann <= 0:
        return min_size
    raw = target_vol_ann / forecast_vol_ann
    return min(max(raw, min_size), max_size)


def paper_risk_garch_factor(
    forecast_vol_ann: float | None,
    target_vol_ann: float,
) -> float:
    """RiskEngine overlay: never invent size. Missing/invalid → 1.0; else ≤ 1.0."""
    if forecast_vol_ann is None or forecast_vol_ann <= 0 or target_vol_ann <= 0:
        return 1.0
    return min(1.0, target_vol_ann / forecast_vol_ann)


def _neg_loglik(alpha: float, beta: float, returns: list[float], variance: float) -> float:
    persist = alpha + beta
    if alpha < 0.0 or beta < 0.0 or persist >= 0.999:
        return _IMPOSSIBLE
    omega = max(variance * (1.0 - persist), _VAR_FLOOR)
    sigma2 = max(variance, _VAR_FLOOR)
    total = 0.0
    for residual in returns:
        sigma2 = max(sigma2, _VAR_FLOOR)
        total += log(sigma2) + (residual * residual) / sigma2
        sigma2 = omega + alpha * residual * residual + beta * sigma2
    return total


def fit_garch11(returns: list[float]) -> GarchParams:
    """Variance-targeting Gaussian GARCH(1,1) by coarse grid + local refine."""
    if len(returns) < 20:
        raise ValueError("insufficient returns for GARCH(1,1)")
    variance = max(sample_variance(returns), _VAR_FLOOR)
    best_score = _IMPOSSIBLE
    best_alpha = 0.05
    best_beta = 0.90
    for alpha in _GRID_ALPHA:
        for beta in _GRID_BETA:
            if alpha + beta >= 0.999:
                continue
            score = _neg_loglik(alpha, beta, returns, variance)
            if score < best_score:
                best_score = score
                best_alpha = alpha
                best_beta = beta
    step = 0.02
    for _ in range(8):
        improved = False
        for delta_alpha, delta_beta in (
            (step, 0.0),
            (-step, 0.0),
            (0.0, step),
            (0.0, -step),
            (step, step),
            (-step, -step),
        ):
            trial_alpha = best_alpha + delta_alpha
            trial_beta = best_beta + delta_beta
            score = _neg_loglik(trial_alpha, trial_beta, returns, variance)
            if score < best_score:
                best_score = score
                best_alpha = trial_alpha
                best_beta = trial_beta
                improved = True
        if not improved:
            step *= 0.5
    persist = min(best_alpha + best_beta, 0.998)
    omega = max(variance * (1.0 - persist), _VAR_FLOOR)
    return GarchParams(omega=omega, alpha=best_alpha, beta=best_beta, variance=variance)


def _conditional_variance(params: GarchParams, returns: list[float]) -> float:
    sigma2 = max(params.variance, _VAR_FLOOR)
    for residual in returns:
        sigma2 = params.omega + params.alpha * residual * residual + params.beta * sigma2
        sigma2 = max(sigma2, _VAR_FLOOR)
    return sigma2


def _regime(percentile: float | None) -> str:
    if percentile is None:
        return "unknown"
    if percentile < 1.0 / 3.0:
        return "calm"
    if percentile < 2.0 / 3.0:
        return "normal"
    return "storm"


def walkforward_forecasts(
    returns: list[float],
    *,
    periods: float,
    min_train: int = DEFAULT_MIN_TRAIN,
    refit_every: int = DEFAULT_REFIT_EVERY,
    target_vol_ann: float = DEFAULT_TARGET_VOL_ANN,
    min_size: float = DEFAULT_MIN_SIZE,
    max_size: float = DEFAULT_MAX_SIZE,
    regime_lookback: int = DEFAULT_REGIME_LOOKBACK,
) -> list[GarchForecast | None]:
    """Forecast of bar ``t+1`` vol, made after observing ``returns[t]``.

    Params are fit on ``returns[:t]`` (strictly prior) and refreshed every
    ``refit_every`` steps. Between refits the recursion is rolled forward
    with the last fitted params — still no lookahead.
    """
    if min_train < 20:
        raise ValueError("min_train must be at least 20")
    if refit_every <= 0:
        raise ValueError("refit_every must be positive")
    if periods <= 0:
        raise ValueError("periods_per_year must be positive")
    out: list[GarchForecast | None] = [None] * len(returns)
    if len(returns) <= min_train:
        return out
    params: GarchParams | None = None
    sigma2 = 0.0
    prior_vols: list[float] = []
    for index in range(min_train, len(returns)):
        if params is None or (index - min_train) % refit_every == 0:
            params = fit_garch11(returns[:index])
            sigma2 = _conditional_variance(params, returns[:index])
        residual = returns[index]
        sigma2 = params.omega + params.alpha * residual * residual + params.beta * sigma2
        sigma2 = max(sigma2, _VAR_FLOOR)
        vol = sqrt(sigma2)
        vol_ann = vol * sqrt(periods)
        lookback = prior_vols[-regime_lookback:] if prior_vols else []
        if lookback:
            percentile = sum(1 for value in lookback if value < vol) / len(lookback)
        else:
            percentile = None
        prior_vols.append(vol)
        out[index] = GarchForecast(
            variance=sigma2,
            vol=vol,
            vol_ann=vol_ann,
            size_multiplier=size_from_vol(
                vol_ann, target_vol_ann, min_size=min_size, max_size=max_size
            ),
            regime=_regime(percentile),
            vol_percentile=percentile,
        )
    return out


def one_step_forecast(
    returns: list[float],
    *,
    periods: float,
    target_vol_ann: float = DEFAULT_TARGET_VOL_ANN,
    min_size: float = DEFAULT_MIN_SIZE,
    max_size: float = DEFAULT_MAX_SIZE,
    min_train: int = DEFAULT_MIN_TRAIN,
) -> GarchForecast | None:
    """Fit on all but the last return; roll the last residual for the next bar."""
    if len(returns) < min_train + 1:
        return None
    params = fit_garch11(returns[:-1])
    sigma2 = _conditional_variance(params, returns[:-1])
    residual = returns[-1]
    sigma2 = max(
        params.omega + params.alpha * residual * residual + params.beta * sigma2,
        _VAR_FLOOR,
    )
    vol = sqrt(sigma2)
    vol_ann = vol * sqrt(periods)
    return GarchForecast(
        variance=sigma2,
        vol=vol,
        vol_ann=vol_ann,
        size_multiplier=size_from_vol(
            vol_ann, target_vol_ann, min_size=min_size, max_size=max_size
        ),
        regime="unknown",
        vol_percentile=None,
    )


def forecast_series_for_candles(
    candles: tuple[Candle, ...],
    *,
    min_train: int = DEFAULT_MIN_TRAIN,
    refit_every: int = DEFAULT_REFIT_EVERY,
    target_vol_ann: float = DEFAULT_TARGET_VOL_ANN,
    min_size: float = DEFAULT_MIN_SIZE,
    max_size: float = DEFAULT_MAX_SIZE,
) -> list[GarchForecast | None]:
    """Walk-forward forecasts aligned to ``candle_returns(candles)``.

    ``series[i]`` is the forecast made at ``candles[i + 1]`` (after that
    bar's close-to-close return) for the *next* bar. A decide() call whose
    window ends at ``candles[j]`` therefore reads ``series[j - 1]``.
    """
    if len(candles) < 2:
        return []
    return walkforward_forecasts(
        candle_returns(candles),
        periods=periods_per_year(candles[0].interval),
        min_train=min_train,
        refit_every=refit_every,
        target_vol_ann=target_vol_ann,
        min_size=min_size,
        max_size=max_size,
    )


def forecast_at_window(
    series: list[GarchForecast | None],
    window: tuple[Candle, ...],
) -> GarchForecast | None:
    """Look up the forecast that belongs to the last bar of ``window``."""
    index = len(window) - 2
    if index < 0 or index >= len(series):
        return None
    return series[index]
