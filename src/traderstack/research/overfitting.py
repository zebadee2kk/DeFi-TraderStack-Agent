"""Selection-bias statistics for the research search harness (#135).

Pure, dependency-free (stdlib ``math``/``statistics``/``random`` and
pydantic result models only). Nothing here reads market data, touches
``Settings``, or can relax a gate: every function either returns a
number or returns ``None`` with a reason. **A missing input is a skip,
never a zero.**

Why this module exists
----------------------
The harness ranked top-1 across a catalog of ``K`` trials and called a
Bonferroni note "honesty". That ignores two things:

1. The **variance of the trial Sharpes**. Picking the max of ``K`` noisy
   draws inflates the winner's Sharpe by roughly
   ``sqrt(V[SR]) * E[max of K standard normals]`` even when every trial
   has zero true edge.
2. The **standard error of an annualised Sharpe**, which is about
   ``sqrt((1 + SR^2 / 2) / T_years)``. At ``T = 2`` years and ``SR = 1``
   that is ``0.87``: a t-statistic of 2 needs roughly six years. The
   window, not the catalog, is why a two-year print reads as zero.

Formulas vendored here (cite-checkable against the papers)
----------------------------------------------------------
* **Probabilistic Sharpe Ratio (PSR)** — Bailey & López de Prado,
  "The Sharpe Ratio Efficient Frontier", *Journal of Risk* 15(2), 2012,
  eq. (3)::

      PSR(SR*) = Phi( (SR_hat - SR*) * sqrt(n - 1)
                      / sqrt(1 - g3*SR_hat + (g4 - 1)/4 * SR_hat^2) )

  ``SR_hat`` and ``SR*`` are **per-observation** (non-annualised)
  Sharpes, ``n`` the number of observations, ``g3`` the skewness and
  ``g4`` the **raw** (non-excess) kurtosis of the return sample.

* **Expected maximum Sharpe over N independent trials** — Bailey,
  Borwein, López de Prado & Zhu, "The Probability of Backtest
  Overfitting", *Journal of Computational Finance* 20(4), 2016,
  and Bailey & López de Prado, "The Deflated Sharpe Ratio",
  *Journal of Portfolio Management* 40(5), 2014 (SSRN 2460551), eq. (5)::

      E[max SR_n] ~= sqrt(V[SR_n]) * ( (1 - gamma) * Phi^-1(1 - 1/N)
                                       + gamma * Phi^-1(1 - 1/(N*e)) )

  with ``gamma`` the Euler-Mascheroni constant.

* **Deflated Sharpe Ratio (DSR)** — Bailey & López de Prado (2014),
  SSRN 2460551: ``DSR = PSR(SR*)`` with ``SR*`` the expected maximum
  above. It is the probability that the observed Sharpe exceeds what
  the *selection procedure itself* would have produced from noise.

* **Sharpe standard error** — Lo, "The Statistics of Sharpe Ratios",
  *Financial Analysts Journal* 58(4), 2002, and Mertens (2002) for the
  non-normal correction::

      SE(SR) = sqrt( (1 + SR^2/2 - g3*SR + (g4 - 3)/4 * SR^2) / n )

  The IID-normal special case ``sqrt((1 + SR^2/2) / n)`` is the power
  formula quoted above once ``n`` is expressed in years.

* **Probability of Backtest Overfitting (PBO) by CSCV** — Bailey,
  Borwein, López de Prado & Zhu (2016), section 3. Exhaustive over
  ``C(S, S/2)`` in-sample/out-of-sample splits of ``S`` equal, disjoint,
  contiguous row blocks; no randomness, so it reproduces exactly.

* **Percentile bootstrap** — Efron & Tibshirani, *An Introduction to
  the Bootstrap* (1993), ch. 13. Every resample here is drawn from an
  explicit ``random.Random(seed)``; the module never touches the global
  RNG, so a fixed seed reproduces every number.
"""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
from itertools import combinations

from pydantic import BaseModel

EULER_MASCHERONI = 0.577215664901532860606512090082402431

# --- era prints / DSR / PBO (#135): frozen defaults, pre-registered ---
# These are *not* Settings fields on purpose. They are part of the
# pre-registered evaluation policy: an operator who can retune the
# bootstrap seed or the confidence level after seeing PnL has not run a
# pre-registered test. Change them in version control, with a note.
DEFAULT_BOOTSTRAP_SEED = 135
DEFAULT_BOOTSTRAP_ITERATIONS = 2000
# The trade-count floor evaluates the bootstrap at ~8 candidate sizes,
# so it runs at a coarser iteration count: it needs the smallest n, not
# a publication-grade interval at each n.
DEFAULT_FLOOR_ITERATIONS = 400
DEFAULT_CONFIDENCE = 0.95
DEFAULT_CSCV_SPLITS = 8
MIN_CSCV_SPLITS = 4
MIN_SAMPLE_FOR_MOMENTS = 4
# Hard ceiling for the bootstrap trade-count floor search. A floor above
# this is reported as "not reachable", never silently truncated.
MAX_TRADE_FLOOR = 4096


# --------------------------------------------------------------------------
# Normal distribution: CDF from math.erf, inverse vendored (Acklam).
# --------------------------------------------------------------------------


def normal_cdf(value: float) -> float:
    """Standard normal CDF ``Phi(x)`` via ``math.erf``."""
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


# Peter J. Acklam's rational approximation to the inverse normal CDF
# (relative error < 1.15e-9 before refinement). Coefficients as published
# at https://web.archive.org/web/20151030215612/http://home.online.no/~pjacklam/notes/invnorm/
_ACKLAM_A = (
    -3.969683028665376e01,
    2.209460984245205e02,
    -2.759285104469687e02,
    1.383577518672690e02,
    -3.066479806614716e01,
    2.506628277459239e00,
)
_ACKLAM_B = (
    -5.447609879822406e01,
    1.615858368580409e02,
    -1.556989798598866e02,
    6.680131188771972e01,
    -1.328068155288572e01,
)
_ACKLAM_C = (
    -7.784894002430293e-03,
    -3.223964580411365e-01,
    -2.400758277161838e00,
    -2.549732539343734e00,
    4.374664141464968e00,
    2.938163982698783e00,
)
_ACKLAM_D = (
    7.784695709041462e-03,
    3.224671290700398e-01,
    2.445134137142996e00,
    3.754408661907416e00,
)
_ACKLAM_P_LOW = 0.02425


def _horner(coefficients: Sequence[float], value: float) -> float:
    """Evaluate a polynomial in ``value`` with Horner's rule, highest first."""
    total = 0.0
    for coefficient in coefficients:
        total = total * value + coefficient
    return total


def _acklam_tail(q: float) -> float:
    """Acklam's lower-tail branch, for ``q = sqrt(-2 ln p)``."""
    return _horner(_ACKLAM_C, q) / _horner((*_ACKLAM_D, 1.0), q)


def _acklam_central(probability: float) -> float:
    """Acklam's central branch, for ``0.02425 <= p <= 0.97575``."""
    q = probability - 0.5
    r = q * q
    return q * _horner(_ACKLAM_A, r) / _horner((*_ACKLAM_B, 1.0), r)


def normal_ppf(probability: float) -> float:
    """Inverse standard normal CDF ``Phi^-1(p)`` for ``0 < p < 1``.

    Acklam's rational approximation followed by one Halley refinement
    step against ``math.erfc``, which takes the absolute error below
    1e-14 over the whole open interval. ``p`` outside ``(0, 1)`` raises:
    an out-of-range probability is a caller bug, not a value to clamp.
    """
    if not 0.0 < probability < 1.0:
        raise ValueError("normal_ppf requires 0 < probability < 1")

    if probability < _ACKLAM_P_LOW:
        estimate = _acklam_tail(math.sqrt(-2.0 * math.log(probability)))
    elif probability <= 1.0 - _ACKLAM_P_LOW:
        estimate = _acklam_central(probability)
    else:
        estimate = -_acklam_tail(math.sqrt(-2.0 * math.log(1.0 - probability)))

    # Halley refinement on f(x) = Phi(x) - p.
    error = 0.5 * math.erfc(-estimate / math.sqrt(2.0)) - probability
    density = math.exp(-0.5 * estimate * estimate) / math.sqrt(2.0 * math.pi)
    if density > 0.0:
        step = error / density
        estimate -= step / (1.0 + 0.5 * estimate * step)
    return estimate


# --------------------------------------------------------------------------
# Sample moments. Population (biased) forms, as the DSR papers use.
# --------------------------------------------------------------------------


def mean(sample: Sequence[float]) -> float | None:
    if not sample:
        return None
    return math.fsum(sample) / len(sample)


def stdev(sample: Sequence[float], *, population: bool = False) -> float | None:
    """Sample (``n - 1``) standard deviation, or population when asked.

    ``None`` for a constant sample. The zero test is *relative*: three
    copies of 0.1 do not sum to exactly 0.3 in binary floating point, so
    an absolute ``variance <= 0`` test would report a spread of ~1e-17
    and hand every downstream ratio a Sharpe of 1e15. Anything below
    ``1e-12`` of the sample's own scale is treated as no dispersion.
    """
    size = len(sample)
    if size < 2:
        return None
    average = math.fsum(sample) / size
    divisor = size if population else size - 1
    variance = math.fsum((value - average) ** 2 for value in sample) / divisor
    if variance <= 0.0:
        return None
    deviation = math.sqrt(variance)
    scale = max((abs(value) for value in sample), default=0.0) or 1.0
    if deviation < 1e-12 * scale:
        return None
    return deviation


def skewness(sample: Sequence[float]) -> float | None:
    """``g3 = E[(r - mu)^3] / sigma^3`` (population third moment)."""
    if len(sample) < MIN_SAMPLE_FOR_MOMENTS:
        return None
    deviation = stdev(sample, population=True)
    if deviation is None:
        return None
    average = math.fsum(sample) / len(sample)
    third = math.fsum((value - average) ** 3 for value in sample) / len(sample)
    return third / deviation**3


def kurtosis(sample: Sequence[float]) -> float | None:
    """Raw (non-excess) kurtosis ``g4 = E[(r - mu)^4] / sigma^4``.

    3.0 for a normal sample. The PSR formula below expects this raw
    form, not the excess form, so callers must not subtract 3.
    """
    if len(sample) < MIN_SAMPLE_FOR_MOMENTS:
        return None
    deviation = stdev(sample, population=True)
    if deviation is None:
        return None
    average = math.fsum(sample) / len(sample)
    fourth = math.fsum((value - average) ** 4 for value in sample) / len(sample)
    return fourth / deviation**4


def sharpe_ratio(sample: Sequence[float]) -> float | None:
    """Per-observation Sharpe ``mean / stdev``. Not annualised."""
    if len(sample) < 2:
        return None
    deviation = stdev(sample)
    average = mean(sample)
    if deviation is None or average is None:
        return None
    return average / deviation


def annualise(per_observation_sharpe: float, periods_per_year: float) -> float:
    return per_observation_sharpe * math.sqrt(periods_per_year)


def deannualise(annual_sharpe: float, periods_per_year: float) -> float:
    if periods_per_year <= 0:
        raise ValueError("periods_per_year must be positive")
    return annual_sharpe / math.sqrt(periods_per_year)


# --------------------------------------------------------------------------
# Standard errors and the power table.
# --------------------------------------------------------------------------


def sharpe_standard_error(
    sharpe: float,
    observations: int,
    *,
    skew: float | None = None,
    raw_kurtosis: float | None = None,
) -> float | None:
    """SE of a Sharpe estimated from ``observations`` draws.

    Lo (2002) IID-normal form ``sqrt((1 + SR^2/2) / n)``, extended with
    the Mertens (2002) non-normal correction when ``skew`` and
    ``raw_kurtosis`` are supplied::

        SE(SR) = sqrt( (1 + SR^2/2 - g3*SR + (g4 - 3)/4 * SR^2) / n )

    ``SR`` must be in the same units as the observations (per-period if
    ``n`` counts periods, annual if ``n`` counts years). Returns ``None``
    for fewer than two observations or a non-positive variance term.
    """
    if observations < 2:
        return None
    variance_term = 1.0 + 0.5 * sharpe * sharpe
    if skew is not None:
        variance_term -= skew * sharpe
    if raw_kurtosis is not None:
        variance_term += (raw_kurtosis - 3.0) / 4.0 * sharpe * sharpe
    if variance_term <= 0.0:
        return None
    return math.sqrt(variance_term / observations)


def annualised_sharpe_standard_error(annual_sharpe: float, years: float) -> float | None:
    """``sqrt((1 + SR^2 / 2) / T_years)`` — the #135 power formula.

    This is ``sharpe_standard_error`` with the observation unit set to a
    year. It is what says a two-year window at ``SR = 1`` has
    ``SE ~= 0.87``, so ``t ~= 1.15``: not evidence of anything.
    """
    if years <= 0:
        return None
    return math.sqrt((1.0 + 0.5 * annual_sharpe * annual_sharpe) / years)


def years_for_sharpe_tstat(annual_sharpe: float, target_tstat: float) -> float | None:
    """Years of sample needed for ``SR / SE(SR)`` to reach ``target_tstat``.

    Solving ``SR / sqrt((1 + SR^2/2)/T) = t`` gives
    ``T = t^2 * (1 + SR^2/2) / SR^2``.
    """
    if annual_sharpe <= 0 or target_tstat <= 0:
        return None
    return target_tstat**2 * (1.0 + 0.5 * annual_sharpe**2) / (annual_sharpe**2)


# --------------------------------------------------------------------------
# Probabilistic and Deflated Sharpe Ratio.
# --------------------------------------------------------------------------


class DeflatedSharpeResult(BaseModel):
    """One catalog run's DSR, with every input it was computed from."""

    computed: bool = False
    skipped_reason: str | None = None
    trials: int = 0
    observations: int = 0
    observed_sharpe: float | None = None
    observed_sharpe_annualised: float | None = None
    trial_sharpe_variance: float | None = None
    expected_max_sharpe: float | None = None
    skew: float | None = None
    raw_kurtosis: float | None = None
    probabilistic_sharpe: float | None = None
    deflated_sharpe: float | None = None
    standard_error: float | None = None
    tstat: float | None = None


def probabilistic_sharpe_ratio(
    *,
    observed_sharpe: float,
    benchmark_sharpe: float,
    observations: int,
    skew: float | None = None,
    raw_kurtosis: float | None = None,
) -> float | None:
    """PSR — Bailey & López de Prado (2012), eq. (3).

    All Sharpes per-observation. ``skew``/``raw_kurtosis`` default to the
    normal case (0 and 3) only when they are genuinely unavailable *and*
    the caller has said so; passing ``None`` here means "assume normal",
    which is why the evidence builder always supplies real moments when
    the sample is long enough and records a skip when it is not.
    """
    if observations < 2:
        return None
    g3 = 0.0 if skew is None else skew
    g4 = 3.0 if raw_kurtosis is None else raw_kurtosis
    variance_term = 1.0 - g3 * observed_sharpe + (g4 - 1.0) / 4.0 * observed_sharpe**2
    if variance_term <= 0.0:
        return None
    numerator = (observed_sharpe - benchmark_sharpe) * math.sqrt(observations - 1)
    return normal_cdf(numerator / math.sqrt(variance_term))


def expected_max_sharpe(*, trial_sharpe_variance: float, trials: int) -> float | None:
    """``E[max SR_n]`` over ``N`` trials — Bailey & López de Prado (2014).

    ``sqrt(V) * ((1 - gamma) * Phi^-1(1 - 1/N) + gamma * Phi^-1(1 - 1/(N e)))``.
    Needs ``N >= 2`` (with one trial there is no selection to deflate)
    and a strictly positive trial-Sharpe variance.
    """
    if trials < 2 or trial_sharpe_variance <= 0.0:
        return None
    upper = 1.0 - 1.0 / trials
    lower = 1.0 - 1.0 / (trials * math.e)
    if not (0.0 < upper < 1.0 and 0.0 < lower < 1.0):
        return None
    return math.sqrt(trial_sharpe_variance) * (
        (1.0 - EULER_MASCHERONI) * normal_ppf(upper) + EULER_MASCHERONI * normal_ppf(lower)
    )


def deflated_sharpe_ratio(
    *,
    returns: Sequence[float],
    trial_sharpes: Sequence[float],
    periods_per_year: float = 1.0,
) -> DeflatedSharpeResult:
    """DSR for the selected strategy given the whole trial catalog.

    ``returns`` is the selected strategy's return sample (the unit the
    Sharpe is measured on). ``trial_sharpes`` is one **per-observation**
    Sharpe per catalog trial, including the selected one, so the
    variance term reflects the search that actually happened.

    Every early return records ``skipped_reason`` and leaves the numbers
    ``None``: a DSR that could not be computed is a skip, never a zero
    and never a pass.
    """
    observations = len(returns)
    trials = len(trial_sharpes)
    if observations < 2:
        return DeflatedSharpeResult(
            skipped_reason="fewer_than_two_return_observations",
            trials=trials,
            observations=observations,
        )
    observed = sharpe_ratio(returns)
    if observed is None:
        return DeflatedSharpeResult(
            skipped_reason="return_sample_has_no_dispersion",
            trials=trials,
            observations=observations,
        )
    if trials < 2:
        return DeflatedSharpeResult(
            skipped_reason="fewer_than_two_trials",
            trials=trials,
            observations=observations,
            observed_sharpe=observed,
            observed_sharpe_annualised=annualise(observed, periods_per_year),
        )
    variance = stdev(trial_sharpes)
    trial_variance = None if variance is None else variance**2
    if trial_variance is None:
        return DeflatedSharpeResult(
            skipped_reason="trial_sharpes_have_no_dispersion",
            trials=trials,
            observations=observations,
            observed_sharpe=observed,
            observed_sharpe_annualised=annualise(observed, periods_per_year),
        )
    benchmark = expected_max_sharpe(trial_sharpe_variance=trial_variance, trials=trials)
    if benchmark is None:
        return DeflatedSharpeResult(
            skipped_reason="expected_max_sharpe_unavailable",
            trials=trials,
            observations=observations,
            observed_sharpe=observed,
            observed_sharpe_annualised=annualise(observed, periods_per_year),
            trial_sharpe_variance=trial_variance,
        )
    skew = skewness(returns)
    raw_kurt = kurtosis(returns)
    psr = probabilistic_sharpe_ratio(
        observed_sharpe=observed,
        benchmark_sharpe=0.0,
        observations=observations,
        skew=skew,
        raw_kurtosis=raw_kurt,
    )
    dsr = probabilistic_sharpe_ratio(
        observed_sharpe=observed,
        benchmark_sharpe=benchmark,
        observations=observations,
        skew=skew,
        raw_kurtosis=raw_kurt,
    )
    if dsr is None:
        return DeflatedSharpeResult(
            skipped_reason="psr_variance_term_not_positive",
            trials=trials,
            observations=observations,
            observed_sharpe=observed,
            observed_sharpe_annualised=annualise(observed, periods_per_year),
            trial_sharpe_variance=trial_variance,
            expected_max_sharpe=benchmark,
            skew=skew,
            raw_kurtosis=raw_kurt,
        )
    annual = annualise(observed, periods_per_year)
    standard_error = sharpe_standard_error(observed, observations, skew=skew, raw_kurtosis=raw_kurt)
    tstat = None if standard_error is None or standard_error <= 0 else observed / standard_error
    return DeflatedSharpeResult(
        computed=True,
        trials=trials,
        observations=observations,
        observed_sharpe=observed,
        observed_sharpe_annualised=annual,
        trial_sharpe_variance=trial_variance,
        expected_max_sharpe=benchmark,
        skew=skew,
        raw_kurtosis=raw_kurt,
        probabilistic_sharpe=psr,
        deflated_sharpe=dsr,
        standard_error=standard_error,
        tstat=tstat,
    )


# --------------------------------------------------------------------------
# Percentile bootstrap.
# --------------------------------------------------------------------------


class BootstrapInterval(BaseModel):
    """A percentile bootstrap CI on one statistic."""

    statistic: str
    computed: bool = False
    skipped_reason: str | None = None
    observations: int = 0
    iterations: int = 0
    confidence: float = DEFAULT_CONFIDENCE
    seed: int = DEFAULT_BOOTSTRAP_SEED
    point: float | None = None
    low: float | None = None
    high: float | None = None
    excludes_zero: bool = False


def _percentile(sorted_values: list[float], fraction: float) -> float:
    """Linear-interpolated percentile of an already-sorted list."""
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = fraction * (len(sorted_values) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return sorted_values[int(position)]
    weight = position - lower
    return sorted_values[lower] * (1.0 - weight) + sorted_values[upper] * weight


def _resample_statistic(
    sample: Sequence[float],
    rng: random.Random,
    size: int,
    statistic: str,
) -> float | None:
    draw = [sample[rng.randrange(len(sample))] for _ in range(size)]
    if statistic == "sharpe":
        return sharpe_ratio(draw)
    return mean(draw)


def bootstrap_interval(
    sample: Sequence[float],
    *,
    statistic: str = "mean",
    confidence: float = DEFAULT_CONFIDENCE,
    iterations: int = DEFAULT_BOOTSTRAP_ITERATIONS,
    seed: int = DEFAULT_BOOTSTRAP_SEED,
    resample_size: int | None = None,
) -> BootstrapInterval:
    """Percentile bootstrap CI (Efron & Tibshirani 1993, ch. 13).

    ``statistic`` is ``"mean"`` (expectancy) or ``"sharpe"``. Draws come
    from ``random.Random(seed)`` created inside this call, so the global
    RNG is never touched and a fixed seed reproduces the interval
    exactly. Fewer than two observations, or a degenerate sample, is a
    skip with a reason — never a zero-width interval.
    """
    if statistic not in {"mean", "sharpe"}:
        raise ValueError("statistic must be 'mean' or 'sharpe'")
    size = resample_size if resample_size is not None else len(sample)

    def skipped(reason: str, point: float | None = None) -> BootstrapInterval:
        return BootstrapInterval(
            statistic=statistic,
            skipped_reason=reason,
            observations=len(sample),
            iterations=iterations,
            confidence=confidence,
            seed=seed,
            point=point,
        )

    if not 0.0 < confidence < 1.0:
        raise ValueError("confidence must be in (0, 1)")
    if iterations < 1:
        raise ValueError("iterations must be positive")
    if len(sample) < 2 or size < 2:
        return skipped("fewer_than_two_observations")
    if stdev(sample) is None:
        # A constant sample has no sampling distribution to resample:
        # reporting a zero-width interval that "excludes zero" would be a
        # fabricated pass.
        return skipped("sample_has_no_dispersion")
    point = sharpe_ratio(sample) if statistic == "sharpe" else mean(sample)
    if point is None:
        return skipped("sample_has_no_dispersion")

    rng = random.Random(seed)
    draws: list[float] = []
    for _ in range(iterations):
        value = _resample_statistic(sample, rng, size, statistic)
        if value is not None:
            draws.append(value)
    if len(draws) < 2:
        return skipped("bootstrap_draws_degenerate", point=point)
    draws.sort()
    tail = (1.0 - confidence) / 2.0
    low = _percentile(draws, tail)
    high = _percentile(draws, 1.0 - tail)
    return BootstrapInterval(
        statistic=statistic,
        computed=True,
        observations=len(sample),
        iterations=iterations,
        confidence=confidence,
        seed=seed,
        point=point,
        low=low,
        high=high,
        excludes_zero=(low > 0.0 or high < 0.0),
    )


class TradeCountFloor(BaseModel):
    """Trade count a bootstrap CI on expectancy needs to exclude zero.

    ``required_observations`` is in the units of the sample that was
    bootstrapped, named by ``observation_unit``. When the sample is not
    itself per-trade (the search harness bootstraps **walk-forward fold
    expectancies**, because per-trade logs are stripped from the reports),
    ``trades_per_observation`` carries the observed conversion factor and
    ``required_trades`` is the scaled-up answer. Both are reported so a
    reviewer can see the conversion rather than guess at it.
    """

    computed: bool = False
    skipped_reason: str | None = None
    confidence: float = DEFAULT_CONFIDENCE
    seed: int = DEFAULT_BOOTSTRAP_SEED
    iterations: int = DEFAULT_BOOTSTRAP_ITERATIONS
    observation_unit: str = "trade"
    trades_per_observation: float = 1.0
    observed_observations: int = 0
    observed_trades: int = 0
    required_observations: int | None = None
    required_trades: int | None = None
    analytic_required_observations: int | None = None
    # The configured fixed floor this run started from. The effective
    # floor is max(configured, required): the bootstrap can only raise it.
    configured_min_trades: int = 0
    effective_min_trades: int = 0
    meets_floor: bool = False


def analytic_observation_floor(sample: Sequence[float], *, confidence: float) -> int | None:
    """``n > (z * s / |mu|)^2`` — the closed form the bootstrap brackets.

    A normal-approximation cross-check on ``bootstrap_trade_floor``;
    reported alongside it so a reviewer can see the two agree in order
    of magnitude without re-running the resampling.
    """
    average = mean(sample)
    deviation = stdev(sample)
    if average is None or deviation is None or average == 0.0:
        return None
    z = normal_ppf(1.0 - (1.0 - confidence) / 2.0)
    needed = (z * deviation / abs(average)) ** 2
    return max(2, math.ceil(needed))


def bootstrap_trade_floor(
    sample: Sequence[float],
    *,
    observed_trades: int,
    configured_min_trades: int = 0,
    observation_unit: str = "trade",
    trades_per_observation: float = 1.0,
    confidence: float = DEFAULT_CONFIDENCE,
    iterations: int = DEFAULT_FLOOR_ITERATIONS,
    seed: int = DEFAULT_BOOTSTRAP_SEED,
) -> TradeCountFloor:
    """Smallest resample size whose expectancy CI excludes zero.

    Replaces "at least 3 trades" with "enough trades that a percentile
    bootstrap CI on expectancy, resampled from the observed expectancy
    distribution, does not straddle zero at ``confidence``". The search
    is a doubling bracket followed by a bisection, each candidate size
    evaluated with its own ``random.Random(seed)`` so the answer does not
    depend on the search path and a fixed seed reproduces it exactly.

    ``trades_per_observation`` scales the answer back into trades when
    the sample is not per-trade (see ``TradeCountFloor``).

    The result **never lowers** an existing threshold:
    ``effective_min_trades = max(configured_min_trades, required_trades)``.
    """

    def skipped(reason: str, analytic: int | None = None) -> TradeCountFloor:
        return TradeCountFloor(
            skipped_reason=reason,
            confidence=confidence,
            seed=seed,
            iterations=iterations,
            observation_unit=observation_unit,
            trades_per_observation=trades_per_observation,
            observed_observations=len(sample),
            observed_trades=observed_trades,
            analytic_required_observations=analytic,
            configured_min_trades=configured_min_trades,
            effective_min_trades=configured_min_trades,
            meets_floor=observed_trades >= configured_min_trades,
        )

    if len(sample) < 2:
        return skipped("fewer_than_two_observations")
    if mean(sample) == 0.0 or stdev(sample) is None:
        return skipped("sample_has_no_dispersion")

    def excludes_zero_at(size: int) -> bool:
        interval = bootstrap_interval(
            sample,
            statistic="mean",
            confidence=confidence,
            iterations=iterations,
            seed=seed,
            resample_size=size,
        )
        return interval.computed and interval.excludes_zero

    # Bracket from the analytic estimate when there is one: it is within
    # a small factor of the bootstrap answer, so the doubling costs two or
    # three evaluations instead of twelve. The answer is still the
    # smallest bracketed size whose interval excludes zero, and it still
    # depends only on (sample, confidence, iterations, seed).
    analytic = analytic_observation_floor(sample, confidence=confidence)
    upper = 2 if analytic is None else max(2, analytic // 4)
    while upper <= MAX_TRADE_FLOOR and not excludes_zero_at(upper):
        upper *= 2
    if upper > MAX_TRADE_FLOOR:
        return skipped("required_observations_exceeds_cap", analytic=analytic)
    low, high = (2 if analytic is None else max(2, analytic // 4)), upper
    if low == upper:
        low = 1
    while low + 1 < high:
        middle = (low + high) // 2
        if excludes_zero_at(middle):
            high = middle
        else:
            low = middle
    required = max(2, high)
    scale = trades_per_observation if trades_per_observation > 0 else 1.0
    required_trades = max(2, math.ceil(required * scale))
    effective = max(configured_min_trades, required_trades)
    return TradeCountFloor(
        computed=True,
        confidence=confidence,
        seed=seed,
        iterations=iterations,
        observation_unit=observation_unit,
        trades_per_observation=trades_per_observation,
        observed_observations=len(sample),
        observed_trades=observed_trades,
        required_observations=required,
        required_trades=required_trades,
        analytic_required_observations=analytic,
        configured_min_trades=configured_min_trades,
        effective_min_trades=effective,
        meets_floor=observed_trades >= effective,
    )


# --------------------------------------------------------------------------
# Probability of backtest overfitting, by CSCV.
# --------------------------------------------------------------------------


class PboResult(BaseModel):
    """CSCV probability of backtest overfitting for one catalog run."""

    computed: bool = False
    skipped_reason: str | None = None
    trials: int = 0
    observations: int = 0
    splits: int = 0
    combinations: int = 0
    pbo: float | None = None
    median_logit: float | None = None
    # Share of splits whose IS winner also beat the OOS median. 1 - pbo
    # when every combination produced a usable rank.
    oos_outperformance_rate: float | None = None


def _column_sharpe(matrix: Sequence[Sequence[float]], rows: Sequence[int], column: int) -> float:
    values = [matrix[row][column] for row in rows]
    result = sharpe_ratio(values)
    if result is not None:
        return result
    # No dispersion: rank by mean so a flat-but-positive trial still
    # orders above a flat-but-negative one instead of being dropped.
    average = mean(values)
    return 0.0 if average is None else average


def _choose_splits(observations: int, splits: int) -> int | None:
    """Even block count ``S <= splits`` that wastes the fewest rows.

    CSCV needs ``S`` equal, disjoint, contiguous blocks, so
    ``observations % S`` rows are dropped. Among the even candidates in
    ``[MIN_CSCV_SPLITS, min(splits, observations)]`` this picks the one
    with the smallest remainder, breaking ties toward the larger ``S``
    (more combinations). Deterministic; no RNG.
    """
    ceiling = min(splits, observations)
    candidates = [size for size in range(MIN_CSCV_SPLITS, ceiling + 1) if size % 2 == 0]
    if not candidates:
        return None
    return min(candidates, key=lambda size: (observations % size, -size))


def cscv_pbo(
    matrix: Sequence[Sequence[float]],
    *,
    splits: int = DEFAULT_CSCV_SPLITS,
) -> PboResult:
    """PBO by combinatorially symmetric cross-validation.

    ``matrix`` is ``M`` rows (time slices, oldest first) by ``N`` columns
    (catalog trials): ``matrix[m][n]`` is trial ``n``'s return in slice
    ``m``. The rows are cut into ``S`` equal, disjoint, contiguous blocks;
    for each of the ``C(S, S/2)`` ways of choosing half the blocks as
    in-sample, the IS-best trial's out-of-sample **relative rank**
    ``w = rank / (N + 1)`` gives a logit ``lambda = ln(w / (1 - w))``.
    ``PBO`` is the share of combinations with ``lambda <= 0`` — the
    probability that the procedure's winner is below the OOS median.

    Exhaustive, so there is no RNG and no seed: the number reproduces
    bit-for-bit. Too few rows, too few trials, or an odd ``splits`` is a
    skip with a reason, never a zero.
    """
    observations = len(matrix)
    trials = len(matrix[0]) if observations else 0

    def skipped(reason: str) -> PboResult:
        return PboResult(
            skipped_reason=reason,
            trials=trials,
            observations=observations,
            splits=0,
            combinations=0,
        )

    if trials < 2:
        return skipped("fewer_than_two_trials")
    if any(len(row) != trials for row in matrix):
        return skipped("ragged_matrix")

    usable = _choose_splits(observations, splits)
    if usable is None:
        return skipped("fewer_rows_than_minimum_splits")

    block_size = observations // usable
    # Drop the oldest leftover rows so every block is the same length.
    offset = observations - block_size * usable
    blocks = [
        list(range(offset + index * block_size, offset + (index + 1) * block_size))
        for index in range(usable)
    ]

    half = usable // 2
    logits: list[float] = []
    below_median = 0
    for chosen in combinations(range(usable), half):
        is_rows = [row for index in chosen for row in blocks[index]]
        oos_rows = [row for index in range(usable) if index not in chosen for row in blocks[index]]
        if len(is_rows) < 2 or len(oos_rows) < 2:
            continue
        is_scores = [_column_sharpe(matrix, is_rows, column) for column in range(trials)]
        best = max(range(trials), key=lambda column: (is_scores[column], -column))
        oos_scores = [_column_sharpe(matrix, oos_rows, column) for column in range(trials)]
        # Rank 1 = worst OOS, rank N = best OOS. Ties resolve by column
        # index so the rank is deterministic.
        order = sorted(range(trials), key=lambda column: (oos_scores[column], -column))
        rank = order.index(best) + 1
        relative = rank / (trials + 1.0)
        logits.append(math.log(relative / (1.0 - relative)))
        if relative <= 0.5:
            below_median += 1
    if not logits:
        return PboResult(
            skipped_reason="no_usable_combinations",
            trials=trials,
            observations=observations,
            splits=usable,
            combinations=0,
        )
    logits.sort()
    median = _percentile(logits, 0.5)
    pbo = below_median / len(logits)
    return PboResult(
        computed=True,
        trials=trials,
        observations=observations,
        splits=usable,
        combinations=len(logits),
        pbo=pbo,
        median_logit=median,
        oos_outperformance_rate=1.0 - pbo,
    )


class PowerRow(BaseModel):
    """One row of the Sharpe power table written into every report."""

    annual_sharpe: float
    years: float
    standard_error: float
    tstat: float
    years_for_tstat_2: float


def power_table(
    *,
    sharpes: Sequence[float] = (0.5, 0.75, 1.0, 1.5, 2.0),
    years: float,
) -> list[PowerRow]:
    """SE / t-stat of an annualised Sharpe at a given window length.

    The table that makes the #135 point concrete: at ``years = 2`` no
    plausible crypto Sharpe clears ``t = 2``, so a two-year window
    cannot distinguish a real edge from noise however large the catalog.
    """
    rows: list[PowerRow] = []
    for sharpe in sharpes:
        standard_error = annualised_sharpe_standard_error(sharpe, years)
        needed = years_for_sharpe_tstat(sharpe, 2.0)
        if standard_error is None or standard_error <= 0 or needed is None:
            continue
        rows.append(
            PowerRow(
                annual_sharpe=sharpe,
                years=years,
                standard_error=standard_error,
                tstat=sharpe / standard_error,
                years_for_tstat_2=needed,
            )
        )
    return rows


__all__ = [
    "DEFAULT_BOOTSTRAP_ITERATIONS",
    "DEFAULT_BOOTSTRAP_SEED",
    "DEFAULT_CONFIDENCE",
    "DEFAULT_CSCV_SPLITS",
    "DEFAULT_FLOOR_ITERATIONS",
    "EULER_MASCHERONI",
    "BootstrapInterval",
    "DeflatedSharpeResult",
    "PboResult",
    "PowerRow",
    "TradeCountFloor",
    "analytic_observation_floor",
    "annualise",
    "annualised_sharpe_standard_error",
    "bootstrap_interval",
    "bootstrap_trade_floor",
    "cscv_pbo",
    "deannualise",
    "deflated_sharpe_ratio",
    "expected_max_sharpe",
    "kurtosis",
    "mean",
    "normal_cdf",
    "normal_ppf",
    "power_table",
    "probabilistic_sharpe_ratio",
    "sharpe_ratio",
    "sharpe_standard_error",
    "skewness",
    "stdev",
    "years_for_sharpe_tstat",
]
