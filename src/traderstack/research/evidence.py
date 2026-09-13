"""Search-report evidence layer (#135, first slice of #48).

Pure, deterministic, stdlib-only statistics that every search report
carries *in addition to* its existing gates:

* **Deflated Sharpe Ratio** (Bailey & López de Prado, SSRN 2460551) per
  candidate per promotion asset, computed from the candidate's holdout
  per-bar returns with trial count ``N = catalog K`` and the variance of
  holdout period-Sharpes across the catalog.
* **Probability of backtest overfitting** (Bailey, Borwein, López de
  Prado & Zhu) per asset via combinatorially symmetric cross-validation
  over the matrix of walk-forward fold Sharpes (folds × candidates).
* **Seeded bootstrap confidence intervals**: circular-block bootstrap on
  annualised Sharpe (report-only) and iid bootstrap on per-trade
  expectancy, plus the trade count needed for the expectancy CI to
  exclude zero (an *additional* floor beside the unchanged
  ``min_trades``).
* A frozen **era-print policy**: ``ERA_WINDOWS`` and ``era_coverage``
  report which eras a venue series covers and whether each is
  scoreable; ``print_kind`` is stamped on every report.

Honesty rules (also written into every report via ``EVIDENCE_RULES``):

* Thresholds are module constants, never ``Settings``. Nothing env- or
  LLM-reachable can move them.
* Evidence is an additional gate, never a replacement. It can only
  withhold a promotion recommendation; it never ranks, selects, or
  sizes.
* A missing or undefined statistic is a fail-closed reason string,
  never a zero. An empty evidence-passer set is a successful result.
* DSR uses holdout returns (post-holdout information). That is
  acceptable only because it is used to withhold, never to pick a
  winner; the ranking key is untouched.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from itertools import combinations
from statistics import NormalDist

from pydantic import BaseModel, Field

from traderstack.candles import Candle, interval_to_seconds, periods_per_year
from traderstack.research.daily_robustness import (
    PROMOTION_ASSETS,
    DailyRobustnessReport,
    series_for_asset,
)
from traderstack.research.miles_search import SeriesCandidateMetrics

# --- frozen evidence thresholds (pre-registered; never Settings) ---
EVIDENCE_SEED = 20260913
BOOTSTRAP_RESAMPLES = 2000
BOOTSTRAP_CONFIDENCE = 0.95
DSR_MIN = 0.95
PBO_MAX = 0.50
CSCV_MIN_GROUPS = 4
CSCV_MAX_GROUPS = 16
EULER_GAMMA = 0.5772156649015329
PRINT_KIND_VENUE = "venue"
PRINT_KIND_ERA = "era"
# (label, start_iso, end_iso) — the #136 era boundaries. Frozen.
ERA_WINDOWS: tuple[tuple[str, str, str], ...] = (
    ("era_1_2016_2019", "2016-01-01", "2019-12-31"),
    ("era_2_2020_2022h1", "2020-01-01", "2022-06-30"),
    ("era_3_2022h2_2024h1", "2022-07-01", "2024-06-30"),
    ("era_4_2024h2_2026", "2024-07-01", "2026-12-31"),
)
ERA_MIN_BARS = 720
REPORT_ASSETS: tuple[str, ...] = ("BTC/USD", "ETH/USD", "SOL/USD")

EVIDENCE_RULES = (
    "Pre-registered evidence layer (#135; frozen before any window is "
    f"scored). Deflated Sharpe: DSR >= {DSR_MIN:.2f} on BTC and ETH, with "
    "N = catalog K trials and the variance of holdout period-Sharpes across "
    "the catalog (expected max Sharpe via the Euler-Mascheroni "
    "approximation; PSR adjusts for skew and kurtosis). Probability of "
    f"backtest overfitting: CSCV PBO <= {PBO_MAX:.2f} per asset over the "
    "walk-forward fold-Sharpe matrix (symmetric half splits; at most "
    f"{CSCV_MAX_GROUPS} groups by averaging adjacent folds; an odd count "
    f"drops the oldest fold; fewer than {CSCV_MIN_GROUPS} groups is "
    "undefined). Bootstrap: seeded circular-block bootstrap CI on "
    "annualised Sharpe (report-only) and seeded iid bootstrap CI on "
    f"per-trade expectancy at {BOOTSTRAP_CONFIDENCE:.0%} with "
    f"{BOOTSTRAP_RESAMPLES} resamples (seed {EVIDENCE_SEED}); the "
    "expectancy CI must exclude zero on BTC and ETH, and the report "
    "prints the trade count needed for it to do so. SOL is reported, "
    "not gated. These are additional gates, never replacements: "
    "min_trades, RANKING_KEY, SELECTION_RULE and every A/B/C threshold "
    "are unchanged, and evidence can only withhold a promotion "
    "recommendation. DSR uses holdout returns (post-holdout information) "
    "and is therefore never used to rank or select. Any undefined "
    "statistic is a fail-closed reason, never a zero. An empty "
    f"evidence-passer set is success. print_kind={PRINT_KIND_VENUE} "
    "until #136 scores era prints; era coverage is reported so a reader "
    "sees which eras the series can support."
)

_NORMAL = NormalDist()


# --- power arithmetic (the odds-brief table) ---


def sharpe_standard_error(sr_annual: float, years: float) -> float | None:
    """Lo (2002) large-sample SE of an annualised Sharpe: sqrt((1 + SR²/2) / T)."""
    if years <= 0:
        return None
    return math.sqrt((1.0 + sr_annual * sr_annual / 2.0) / years)


def years_for_t_stat(sr_annual: float, t: float = 2.0) -> float | None:
    """Years of history for ``SR / SE(SR)`` to reach ``t`` under the SE above."""
    if sr_annual <= 0 or t <= 0:
        return None
    return t * t * (1.0 + sr_annual * sr_annual / 2.0) / (sr_annual * sr_annual)


class PowerRow(BaseModel):
    sharpe: float
    se_2y: float
    se_4y: float
    years_for_t2: float


def power_table_rows(
    sharpes: Sequence[float] = (0.5, 1.0, 1.5, 2.0),
) -> list[PowerRow]:
    rows: list[PowerRow] = []
    for sharpe in sharpes:
        se2 = sharpe_standard_error(sharpe, 2.0)
        se4 = sharpe_standard_error(sharpe, 4.0)
        years = years_for_t_stat(sharpe, 2.0)
        if se2 is None or se4 is None or years is None:
            continue
        rows.append(PowerRow(sharpe=sharpe, se_2y=se2, se_4y=se4, years_for_t2=years))
    return rows


# --- moments / Sharpe ---


class Moments(BaseModel):
    n: int
    mean: float
    std: float
    skew: float
    kurtosis: float


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _sample_std(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    avg = _mean(values)
    variance = sum((value - avg) ** 2 for value in values) / (len(values) - 1)
    return math.sqrt(variance) if variance > 0 else 0.0


def _sample_variance(values: Sequence[float]) -> float:
    std = _sample_std(values)
    return std * std


def moments(returns: Sequence[float]) -> Moments | None:
    """Mean, sample std, and population skew / (non-excess) kurtosis."""
    n = len(returns)
    if n < 2:
        return None
    avg = _mean(returns)
    std = _sample_std(returns)
    m2 = sum((value - avg) ** 2 for value in returns) / n
    if m2 <= 0:
        return Moments(n=n, mean=avg, std=std, skew=0.0, kurtosis=3.0)
    m3 = sum((value - avg) ** 3 for value in returns) / n
    m4 = sum((value - avg) ** 4 for value in returns) / n
    return Moments(n=n, mean=avg, std=std, skew=m3 / m2**1.5, kurtosis=m4 / (m2 * m2))


def period_sharpe(returns: Sequence[float]) -> float | None:
    """Per-bar Sharpe (mean / sample std). None when undefined — never zero."""
    if len(returns) < 2:
        return None
    std = _sample_std(returns)
    if std <= 0:
        return None
    return _mean(returns) / std


# --- Deflated Sharpe (Bailey & López de Prado) ---


def expected_max_sharpe(trial_count: int, trial_sharpe_variance: float) -> float:
    """E[max SR] over N iid trials with variance V of trial Sharpes.

    sqrt(V) * ((1 - γ) Φ⁻¹(1 - 1/N) + γ Φ⁻¹(1 - 1/(N e))). Zero for N < 2
    or V <= 0 (a single trial has nothing to deflate against).
    """
    if trial_count < 2 or trial_sharpe_variance <= 0:
        return 0.0
    first = _NORMAL.inv_cdf(1.0 - 1.0 / trial_count)
    second = _NORMAL.inv_cdf(1.0 - 1.0 / (trial_count * math.e))
    return math.sqrt(trial_sharpe_variance) * ((1.0 - EULER_GAMMA) * first + EULER_GAMMA * second)


def probabilistic_sharpe(
    sr: float,
    sr_benchmark: float,
    n: int,
    skew: float,
    kurtosis: float,
) -> float | None:
    """PSR = Φ((SR - SR*) sqrt(n - 1) / sqrt(1 - γ3 SR + (γ4 - 1)/4 SR²)).

    ``sr`` and ``sr_benchmark`` are per-period Sharpes; ``kurtosis`` is
    non-excess. None when n < 2 or the radicand is not positive.
    """
    if n < 2:
        return None
    radicand = 1.0 - skew * sr + (kurtosis - 1.0) / 4.0 * sr * sr
    if radicand <= 0:
        return None
    return _NORMAL.cdf((sr - sr_benchmark) * math.sqrt(n - 1) / math.sqrt(radicand))


class DeflatedSharpe(BaseModel):
    dsr: float | None = None
    period_sharpe: float | None = None
    sr0: float = 0.0
    trial_count: int = 0
    trial_variance: float = 0.0
    skew: float | None = None
    kurtosis: float | None = None
    n: int = 0
    reason: str | None = None


def deflated_sharpe(
    period_returns: Sequence[float],
    trial_period_sharpes: Sequence[float],
) -> DeflatedSharpe:
    """DSR of one candidate against the catalog it was selected from."""
    trial_count = len(trial_period_sharpes)
    trial_variance = _sample_variance(trial_period_sharpes)
    sr0 = expected_max_sharpe(trial_count, trial_variance)
    n = len(period_returns)
    stats = moments(period_returns)
    if stats is None:
        return DeflatedSharpe(
            sr0=sr0,
            trial_count=trial_count,
            trial_variance=trial_variance,
            n=n,
            reason="holdout_returns_too_short",
        )
    sharpe = period_sharpe(period_returns)
    if sharpe is None:
        return DeflatedSharpe(
            sr0=sr0,
            trial_count=trial_count,
            trial_variance=trial_variance,
            skew=stats.skew,
            kurtosis=stats.kurtosis,
            n=n,
            reason="period_sharpe_undefined",
        )
    dsr = probabilistic_sharpe(sharpe, sr0, n, stats.skew, stats.kurtosis)
    return DeflatedSharpe(
        dsr=dsr,
        period_sharpe=sharpe,
        sr0=sr0,
        trial_count=trial_count,
        trial_variance=trial_variance,
        skew=stats.skew,
        kurtosis=stats.kurtosis,
        n=n,
        reason=None if dsr is not None else "psr_radicand_not_positive",
    )


# --- seeded bootstrap ---


class BootstrapCI(BaseModel):
    low: float
    high: float
    point: float
    resamples: int
    confidence: float
    block_len: int
    seed: int


def _circular_block_sample(
    values: Sequence[float], rng: random.Random, block_len: int
) -> list[float]:
    total = len(values)
    sample: list[float] = []
    while len(sample) < total:
        start = rng.randrange(total)
        for offset in range(block_len):
            if len(sample) >= total:
                break
            sample.append(values[(start + offset) % total])
    return sample


def block_bootstrap_ci(
    values: Sequence[float],
    statistic: Callable[[Sequence[float]], float | None],
    *,
    resamples: int = BOOTSTRAP_RESAMPLES,
    confidence: float = BOOTSTRAP_CONFIDENCE,
    seed: int = EVIDENCE_SEED,
    block_len: int = 1,
) -> BootstrapCI | None:
    """Percentile CI from a seeded circular-block bootstrap.

    ``random.Random(seed)`` only — no module-global RNG, so the numbers
    reproduce exactly. ``block_len=1`` is the iid bootstrap. None when the
    point estimate or fewer than two resample statistics are undefined.
    """
    if len(values) < 2 or resamples < 2 or not 0 < confidence < 1:
        return None
    point = statistic(values)
    if point is None:
        return None
    rng = random.Random(seed)
    width = max(1, block_len)
    draws: list[float] = []
    for _ in range(resamples):
        value = statistic(_circular_block_sample(values, rng, width))
        if value is not None:
            draws.append(value)
    if len(draws) < 2:
        return None
    draws.sort()
    alpha = 1.0 - confidence
    low_index = math.floor(alpha / 2.0 * len(draws))
    high_index = math.ceil((1.0 - alpha / 2.0) * len(draws)) - 1
    low_index = min(max(low_index, 0), len(draws) - 1)
    high_index = min(max(high_index, low_index), len(draws) - 1)
    return BootstrapCI(
        low=draws[low_index],
        high=draws[high_index],
        point=point,
        resamples=len(draws),
        confidence=confidence,
        block_len=width,
        seed=seed,
    )


def bootstrap_sharpe_ci(
    period_returns: Sequence[float],
    periods_per_year_value: float,
    *,
    resamples: int = BOOTSTRAP_RESAMPLES,
    confidence: float = BOOTSTRAP_CONFIDENCE,
    seed: int = EVIDENCE_SEED,
) -> BootstrapCI | None:
    """Circular-block bootstrap on annualised Sharpe; block length ≈ T^(1/3)."""
    scale = math.sqrt(periods_per_year_value)

    def annual_sharpe(sample: Sequence[float]) -> float | None:
        value = period_sharpe(sample)
        return None if value is None else value * scale

    block_len = max(1, round(len(period_returns) ** (1.0 / 3.0)))
    return block_bootstrap_ci(
        period_returns,
        annual_sharpe,
        resamples=resamples,
        confidence=confidence,
        seed=seed,
        block_len=block_len,
    )


def _mean_or_none(sample: Sequence[float]) -> float | None:
    return _mean(sample) if sample else None


def bootstrap_expectancy_ci(
    trade_returns: Sequence[float],
    *,
    resamples: int = BOOTSTRAP_RESAMPLES,
    confidence: float = BOOTSTRAP_CONFIDENCE,
    seed: int = EVIDENCE_SEED,
) -> BootstrapCI | None:
    """iid bootstrap on mean per-trade return."""
    return block_bootstrap_ci(
        trade_returns,
        _mean_or_none,
        resamples=resamples,
        confidence=confidence,
        seed=seed,
        block_len=1,
    )


def trades_needed_to_exclude_zero(
    trade_returns: Sequence[float],
    *,
    confidence: float = BOOTSTRAP_CONFIDENCE,
) -> int | None:
    """Trades for a normal-approximation CI on expectancy to exclude zero.

    ceil((z * sd / mean)²) when mean > 0 and sd > 0; None otherwise (a
    non-positive expectancy never excludes zero from above).
    """
    if len(trade_returns) < 2 or not 0 < confidence < 1:
        return None
    avg = _mean(trade_returns)
    std = _sample_std(trade_returns)
    if avg <= 0 or std <= 0:
        return None
    z = _NORMAL.inv_cdf(1.0 - (1.0 - confidence) / 2.0)
    return max(1, math.ceil((z * std / avg) ** 2))


# --- CSCV probability of backtest overfitting ---


class PboResult(BaseModel):
    pbo: float | None = None
    groups: int = 0
    trials: int = 0
    combinations: int = 0
    folds: int = 0
    dropped_oldest_fold: bool = False
    merged_folds: bool = False
    reason: str | None = None


def _merge_groups(folds: list[float], target: int) -> list[float]:
    """Average adjacent folds into ``target`` contiguous groups."""
    count = len(folds)
    groups: list[float] = []
    for index in range(target):
        start = index * count // target
        end = (index + 1) * count // target
        chunk = folds[start:end]
        groups.append(_mean(chunk))
    return groups


def cscv_pbo(groups_by_trial: dict[str, Sequence[float]]) -> PboResult:
    """Probability of backtest overfitting via CSCV over fold Sharpes.

    Every trial must carry the same number of folds (they share
    boundaries when scored on one series with one train/test/step). An
    odd fold count drops the oldest fold; more than ``CSCV_MAX_GROUPS``
    folds are averaged into 16 contiguous groups; fewer than
    ``CSCV_MIN_GROUPS`` groups is undefined (None with a reason). For
    each symmetric half split the trial that is best in-sample is
    ranked out-of-sample; PBO is the fraction of splits where that rank
    is at or below the median (logit <= 0). Ties rank conservatively.
    """
    trial_ids = sorted(groups_by_trial)
    trials = len(trial_ids)
    if trials < 2:
        return PboResult(trials=trials, reason="fewer_than_2_trials")
    lengths = {len(groups_by_trial[trial_id]) for trial_id in trial_ids}
    if len(lengths) != 1:
        return PboResult(trials=trials, reason="fold_count_mismatch_across_trials")
    fold_count = next(iter(lengths))
    matrix = {trial_id: list(groups_by_trial[trial_id]) for trial_id in trial_ids}
    dropped = False
    if fold_count % 2 == 1:
        matrix = {trial_id: values[1:] for trial_id, values in matrix.items()}
        dropped = True
    merged = False
    group_count = fold_count - (1 if dropped else 0)
    if group_count > CSCV_MAX_GROUPS:
        matrix = {
            trial_id: _merge_groups(values, CSCV_MAX_GROUPS) for trial_id, values in matrix.items()
        }
        group_count = CSCV_MAX_GROUPS
        merged = True
    if group_count < CSCV_MIN_GROUPS:
        return PboResult(
            groups=group_count,
            trials=trials,
            folds=fold_count,
            dropped_oldest_fold=dropped,
            merged_folds=merged,
            reason=f"fewer_than_{CSCV_MIN_GROUPS}_groups",
        )
    half = group_count // 2
    overfit = 0
    total = 0
    for train in combinations(range(group_count), half):
        train_set = set(train)
        test = [index for index in range(group_count) if index not in train_set]
        best_id = trial_ids[0]
        best_score = float("-inf")
        for trial_id in trial_ids:
            score = _mean([matrix[trial_id][index] for index in train])
            if score > best_score:
                best_score = score
                best_id = trial_id
        test_scores = {
            trial_id: _mean([matrix[trial_id][index] for index in test]) for trial_id in trial_ids
        }
        selected = test_scores[best_id]
        rank = 1 + sum(1 for value in test_scores.values() if value < selected)
        omega = rank / (trials + 1)
        if omega <= 0.5:
            overfit += 1
        total += 1
    return PboResult(
        pbo=overfit / total if total else None,
        groups=group_count,
        trials=trials,
        combinations=total,
        folds=fold_count,
        dropped_oldest_fold=dropped,
        merged_folds=merged,
        reason=None if total else "no_combinations",
    )


# --- era-print policy ---


class EraCoverage(BaseModel):
    era: str
    start: str
    end: str
    venue: str
    series: int = 0
    first: str | None = None
    last: str | None = None
    bars: int = 0
    expected_bars: int = 0
    fraction: float = 0.0
    scoreable: bool = False
    reason: str | None = None


def _era_bounds(start_iso: str, end_iso: str) -> tuple[datetime, datetime]:
    start = datetime.fromisoformat(start_iso).replace(tzinfo=UTC)
    end = datetime.fromisoformat(end_iso).replace(hour=23, minute=59, second=59, tzinfo=UTC)
    return start, end


def era_coverage(
    histories: dict[str, tuple[Candle, ...]],
    *,
    venue: str,
    min_bars: int = ERA_MIN_BARS,
) -> list[EraCoverage]:
    """One row per ``ERA_WINDOWS`` entry for this venue.

    ``bars`` is the minimum bar count across the venue's series inside
    the era (every scored series must cover it); ``scoreable`` requires
    at least one series and ``bars >= min_bars``. A missing era is a
    skip with a reason, never a zero-filled print.
    """
    rows: list[EraCoverage] = []
    series = [candles for candles in histories.values() if candles]
    for era, start_iso, end_iso in ERA_WINDOWS:
        start, end = _era_bounds(start_iso, end_iso)
        counts: list[int] = []
        firsts: list[datetime] = []
        lasts: list[datetime] = []
        expected = 0
        for candles in series:
            interval_seconds = interval_to_seconds(candles[0].interval)
            expected = max(expected, int((end - start).total_seconds() // interval_seconds) + 1)
            inside = [item for item in candles if start <= item.opened_at <= end]
            counts.append(len(inside))
            if inside:
                firsts.append(inside[0].opened_at)
                lasts.append(inside[-1].opened_at)
        bars = min(counts) if counts else 0
        fraction = min(1.0, bars / expected) if expected > 0 else 0.0
        if not series:
            reason: str | None = "no_series"
        elif bars < min_bars:
            reason = f"fewer_than_{min_bars}_bars_in_era"
        else:
            reason = None
        rows.append(
            EraCoverage(
                era=era,
                start=start_iso,
                end=end_iso,
                venue=venue,
                series=len(series),
                first=min(firsts).isoformat() if firsts else None,
                last=max(lasts).isoformat() if lasts else None,
                bars=bars,
                expected_bars=expected,
                fraction=fraction,
                scoreable=reason is None,
                reason=reason,
            )
        )
    return rows


# --- catalog evidence ---


class CandidateSeriesEvidence(BaseModel):
    asset: str
    bars: int = 0
    trades: int = 0
    sharpe_annual: float | None = None
    period_sharpe: float | None = None
    dsr: float | None = None
    dsr_pass: bool = False
    sr0: float = 0.0
    sharpe_ci_low: float | None = None
    sharpe_ci_high: float | None = None
    expectancy: float | None = None
    expectancy_ci_low: float | None = None
    expectancy_ci_high: float | None = None
    expectancy_ci_excludes_zero: bool = False
    trades_needed_for_ci: int | None = None
    skew: float | None = None
    kurtosis: float | None = None
    reasons: list[str] = Field(default_factory=list)


class CandidateEvidence(BaseModel):
    candidate_id: str
    series: list[CandidateSeriesEvidence] = Field(default_factory=list)
    evidence_pass: bool = False
    reasons: list[str] = Field(default_factory=list)


class CatalogEvidence(BaseModel):
    print_kind: str = PRINT_KIND_VENUE
    trial_count: int = 0
    seed: int = EVIDENCE_SEED
    resamples: int = BOOTSTRAP_RESAMPLES
    confidence: float = BOOTSTRAP_CONFIDENCE
    dsr_min: float = DSR_MIN
    pbo_max: float = PBO_MAX
    promotion_assets: list[str] = Field(default_factory=lambda: list(PROMOTION_ASSETS))
    pbo_by_asset: dict[str, PboResult] = Field(default_factory=dict)
    trial_sharpe_variance_by_asset: dict[str, float] = Field(default_factory=dict)
    excluded_trials_by_asset: dict[str, list[str]] = Field(default_factory=dict)
    candidates: list[CandidateEvidence] = Field(default_factory=list)
    evidence_passer_ids: list[str] = Field(default_factory=list)
    era_coverage: list[EraCoverage] = Field(default_factory=list)
    rules: str = EVIDENCE_RULES


def _series_evidence(
    series: SeriesCandidateMetrics,
    *,
    asset: str,
    trial_period_sharpes: Sequence[float],
    interval: str,
    seed: int,
    resamples: int,
    confidence: float,
) -> CandidateSeriesEvidence:
    reasons: list[str] = []
    returns = list(series.holdout_period_returns)
    trades = list(series.holdout_trade_returns)
    deflated = deflated_sharpe(returns, trial_period_sharpes)
    if deflated.reason is not None:
        reasons.append(f"dsr_undefined:{deflated.reason}")
    dsr_pass = deflated.dsr is not None and deflated.dsr >= DSR_MIN
    if deflated.dsr is not None and not dsr_pass:
        reasons.append("dsr_below_min")
    sharpe_ci = bootstrap_sharpe_ci(
        returns,
        periods_per_year(interval),
        resamples=resamples,
        confidence=confidence,
        seed=seed,
    )
    if sharpe_ci is None:
        reasons.append("sharpe_ci_undefined")
    expectancy_ci = bootstrap_expectancy_ci(
        trades, resamples=resamples, confidence=confidence, seed=seed
    )
    if expectancy_ci is None:
        reasons.append("expectancy_ci_undefined")
    excludes_zero = expectancy_ci is not None and expectancy_ci.low > 0
    if expectancy_ci is not None and not excludes_zero:
        reasons.append("expectancy_ci_includes_zero")
    return CandidateSeriesEvidence(
        asset=asset,
        bars=len(returns),
        trades=len(trades),
        sharpe_annual=series.holdout.sharpe if series.holdout is not None else None,
        period_sharpe=deflated.period_sharpe,
        dsr=deflated.dsr,
        dsr_pass=dsr_pass,
        sr0=deflated.sr0,
        sharpe_ci_low=sharpe_ci.low if sharpe_ci is not None else None,
        sharpe_ci_high=sharpe_ci.high if sharpe_ci is not None else None,
        expectancy=_mean_or_none(trades),
        expectancy_ci_low=expectancy_ci.low if expectancy_ci is not None else None,
        expectancy_ci_high=expectancy_ci.high if expectancy_ci is not None else None,
        expectancy_ci_excludes_zero=excludes_zero,
        trades_needed_for_ci=trades_needed_to_exclude_zero(trades, confidence=confidence),
        skew=deflated.skew,
        kurtosis=deflated.kurtosis,
        reasons=reasons,
    )


def evaluate_catalog_evidence(
    report: DailyRobustnessReport,
    *,
    promotion_assets: Sequence[str] = PROMOTION_ASSETS,
    report_assets: Sequence[str] = REPORT_ASSETS,
    interval: str = "1d",
    seed: int = EVIDENCE_SEED,
    resamples: int = BOOTSTRAP_RESAMPLES,
    confidence: float = BOOTSTRAP_CONFIDENCE,
) -> CatalogEvidence:
    """DSR / PBO / bootstrap evidence for one scored catalog.

    Trial count is the catalog size ``K``. Per asset, the DSR trial
    variance is the sample variance of holdout period-Sharpes across the
    catalog and the PBO matrix is every candidate's walk-forward fold
    Sharpes. ``evidence_pass`` requires, on every promotion asset: DSR
    defined and >= ``DSR_MIN``, catalog PBO defined and <= ``PBO_MAX``,
    and the expectancy CI low bound > 0. Missing data fails closed with
    a reason. Assets outside ``promotion_assets`` are reported only.
    """
    assets = list(dict.fromkeys([*promotion_assets, *report_assets]))
    trial_count = len(report.candidates)
    pbo_by_asset: dict[str, PboResult] = {}
    variance_by_asset: dict[str, float] = {}
    excluded_by_asset: dict[str, list[str]] = {}
    sharpes_by_asset: dict[str, list[float]] = {}
    series_by_asset: dict[str, dict[str, SeriesCandidateMetrics]] = {}
    for asset in assets:
        excluded: list[str] = []
        sharpes: list[float] = []
        fold_matrix: dict[str, Sequence[float]] = {}
        found: dict[str, SeriesCandidateMetrics] = {}
        for row in report.candidates:
            series = series_for_asset(row.per_series, asset, interval=interval)
            if series is None:
                excluded.append(row.candidate_id)
                continue
            found[row.candidate_id] = series
            sharpe = period_sharpe(series.holdout_period_returns)
            if sharpe is not None:
                sharpes.append(sharpe)
            if series.walkforward is not None and series.walkforward.folds:
                fold_matrix[row.candidate_id] = [
                    fold.metrics.sharpe for fold in series.walkforward.folds
                ]
        pbo_by_asset[asset] = (
            cscv_pbo(fold_matrix) if fold_matrix else PboResult(reason="no_walkforward_folds")
        )
        variance_by_asset[asset] = _sample_variance(sharpes)
        excluded_by_asset[asset] = excluded
        sharpes_by_asset[asset] = sharpes
        series_by_asset[asset] = found

    candidates: list[CandidateEvidence] = []
    for row in report.candidates:
        entries: list[CandidateSeriesEvidence] = []
        reasons: list[str] = []
        for asset in assets:
            series = series_by_asset[asset].get(row.candidate_id)
            gated = asset in promotion_assets
            if series is None:
                if gated:
                    reasons.append(f"{asset}:series_missing")
                continue
            entry = _series_evidence(
                series,
                asset=asset,
                trial_period_sharpes=sharpes_by_asset[asset],
                interval=interval,
                seed=seed,
                resamples=resamples,
                confidence=confidence,
            )
            entries.append(entry)
            if not gated:
                continue
            if not entry.dsr_pass:
                reasons.append(f"{asset}:dsr_not_passed")
            pbo = pbo_by_asset[asset]
            if pbo.pbo is None:
                reasons.append(f"{asset}:pbo_undefined:{pbo.reason}")
            elif pbo.pbo > PBO_MAX:
                reasons.append(f"{asset}:pbo_above_max")
            if not entry.expectancy_ci_excludes_zero:
                reasons.append(f"{asset}:expectancy_ci_not_positive")
        candidates.append(
            CandidateEvidence(
                candidate_id=row.candidate_id,
                series=entries,
                evidence_pass=not reasons,
                reasons=reasons,
            )
        )
    return CatalogEvidence(
        print_kind=PRINT_KIND_VENUE,
        trial_count=trial_count,
        seed=seed,
        resamples=resamples,
        confidence=confidence,
        dsr_min=DSR_MIN,
        pbo_max=PBO_MAX,
        promotion_assets=list(promotion_assets),
        pbo_by_asset=pbo_by_asset,
        trial_sharpe_variance_by_asset=variance_by_asset,
        excluded_trials_by_asset=excluded_by_asset,
        candidates=candidates,
        evidence_passer_ids=[item.candidate_id for item in candidates if item.evidence_pass],
        rules=EVIDENCE_RULES,
    )


# --- markdown ---


def _num(value: float | None, digits: int = 3) -> str:
    return f"{value:.{digits}f}" if value is not None else "n/a"


def _pct(value: float | None) -> str:
    return f"{value:+.2%}" if value is not None else "n/a"


def render_era_coverage_lines(rows: Sequence[EraCoverage]) -> list[str]:
    lines = [
        "| era | window | venue | series | bars | expected | fraction | first → last | scoreable |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    if not rows:
        lines.append("| — | — | — | 0 | 0 | 0 | 0.00 | n/a | no (no series) |")
        return lines
    for row in rows:
        verdict = "yes" if row.scoreable else f"no ({row.reason})"
        lines.append(
            f"| `{row.era}` | {row.start} → {row.end} | `{row.venue}` | {row.series} | "
            f"{row.bars} | {row.expected_bars} | {row.fraction:.2f} | "
            f"{row.first or 'n/a'} → {row.last or 'n/a'} | {verdict} |"
        )
    return lines


def render_evidence_lines(
    evidence: CatalogEvidence | None,
    *,
    heading: str = "## Evidence (DSR / PBO / bootstrap; additional gates)",
) -> list[str]:
    """Markdown block for one catalog's evidence. Never hides a None."""
    lines: list[str] = [heading, ""]
    if evidence is None:
        lines.append(
            "Evidence not computed for this print (no scored catalog). "
            "A missing print is a skip, never a zero; it cannot pass."
        )
        lines.append("")
        return lines
    lines.extend(
        [
            (
                f"print_kind=`{evidence.print_kind}`; trial count N={evidence.trial_count}; "
                f"DSR_MIN={evidence.dsr_min:.2f}; PBO_MAX={evidence.pbo_max:.2f}; "
                f"bootstrap {evidence.confidence:.0%} × {evidence.resamples} "
                f"(seed {evidence.seed}). Evidence passers: "
                f"{len(evidence.evidence_passer_ids)}"
                + (
                    " (" + ", ".join(f"`{item}`" for item in evidence.evidence_passer_ids) + ")"
                    if evidence.evidence_passer_ids
                    else " (none; empty is success)"
                )
                + "."
            ),
            "",
            evidence.rules,
            "",
            "| asset | PBO | groups | combos | folds | trial SR variance | excluded trials |",
            "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for asset, pbo in evidence.pbo_by_asset.items():
        gated = "" if asset in evidence.promotion_assets else " (reported, not gated)"
        pbo_text = _num(pbo.pbo) if pbo.pbo is not None else f"n/a ({pbo.reason})"
        excluded = evidence.excluded_trials_by_asset.get(asset, [])
        lines.append(
            f"| {asset}{gated} | {pbo_text} | {pbo.groups} | {pbo.combinations} | "
            f"{pbo.folds} | {_num(evidence.trial_sharpe_variance_by_asset.get(asset), 4)} | "
            f"{len(excluded)} |"
        )
    lines.extend(
        [
            "",
            (
                "| id | asset | bars | trades | SR ann | DSR | SR0 | SR CI | expectancy | "
                "expectancy CI | trades needed | skew | kurt | pass | reasons |"
            ),
            (
                "| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | ---: | --- | ---: | "
                "---: | ---: | --- | --- |"
            ),
        ]
    )
    for candidate in evidence.candidates:
        if not candidate.series:
            lines.append(
                f"| `{candidate.candidate_id}` | — | 0 | 0 | n/a | n/a | n/a | n/a | n/a | "
                f"n/a | n/a | n/a | n/a | no | {', '.join(candidate.reasons) or 'n/a'} |"
            )
            continue
        for entry in candidate.series:
            sr_ci = (
                f"[{_num(entry.sharpe_ci_low, 2)}, {_num(entry.sharpe_ci_high, 2)}]"
                if entry.sharpe_ci_low is not None
                else "n/a"
            )
            ex_ci = (
                f"[{_pct(entry.expectancy_ci_low)}, {_pct(entry.expectancy_ci_high)}]"
                if entry.expectancy_ci_low is not None
                else "n/a"
            )
            needed = str(entry.trades_needed_for_ci) if entry.trades_needed_for_ci else "n/a"
            lines.append(
                f"| `{candidate.candidate_id}` | {entry.asset} | {entry.bars} | {entry.trades} | "
                f"{_num(entry.sharpe_annual, 2)} | {_num(entry.dsr)} | {_num(entry.sr0)} | "
                f"{sr_ci} | {_pct(entry.expectancy)} | {ex_ci} | {needed} | "
                f"{_num(entry.skew, 2)} | {_num(entry.kurtosis, 2)} | "
                f"{'yes' if candidate.evidence_pass else 'no'} | "
                f"{', '.join(candidate.reasons) or '—'} |"
            )
    lines.append("")
    return lines
