from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import UTC, datetime
from statistics import NormalDist
from typing import Mapping, Sequence


@dataclass(frozen=True)
class DiscoveryRow:
    candidate_at: datetime
    label: float
    features: Mapping[str, float]


@dataclass(frozen=True)
class FeatureDiscoveryResult:
    feature: str
    trial_count: int
    discovery_n: int
    holdout_n: int
    discovery_correlation: float | None
    holdout_correlation: float | None
    holdout_ci_low: float | None
    holdout_ci_high: float | None
    placebo_abs_correlation: float | None
    adjusted_alpha: float
    status: str


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _finite(value: float) -> bool:
    return math.isfinite(float(value))


def _pearson(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    if len(xs) != len(ys) or len(xs) < 2:
        return None
    mx = sum(xs) / len(xs)
    my = sum(ys) / len(ys)
    dx = [x - mx for x in xs]
    dy = [y - my for y in ys]
    sx = sum(value * value for value in dx)
    sy = sum(value * value for value in dy)
    if sx <= 0.0 or sy <= 0.0:
        return None
    return sum(x * y for x, y in zip(dx, dy, strict=True)) / math.sqrt(sx * sy)


def _fisher_ci(correlation: float | None, n: int, alpha: float) -> tuple[float | None, float | None]:
    if correlation is None or n <= 3:
        return None, None
    r = max(-0.999999, min(0.999999, correlation))
    z = math.atanh(r)
    zcrit = NormalDist().inv_cdf(1.0 - alpha / 2.0)
    se = 1.0 / math.sqrt(n - 3)
    return math.tanh(z - zcrit * se), math.tanh(z + zcrit * se)


def _paired_values(rows: Sequence[DiscoveryRow], feature: str) -> tuple[list[float], list[float]]:
    xs: list[float] = []
    ys: list[float] = []
    for row in rows:
        raw = row.features.get(feature)
        if raw is None:
            continue
        x = float(raw)
        y = float(row.label)
        if not _finite(x) or not _finite(y):
            continue
        xs.append(x)
        ys.append(y)
    return xs, ys


def evaluate_feature_family(
    rows: Sequence[DiscoveryRow],
    *,
    features: Sequence[str],
    holdout_fraction: float = 0.30,
    min_samples: int = 20,
    seed: int = 7,
    family_alpha: float = 0.05,
) -> list[FeatureDiscoveryResult]:
    if not 0.0 < holdout_fraction < 1.0:
        raise ValueError("holdout_fraction must be between 0 and 1")
    if min_samples < 4:
        raise ValueError("min_samples must be at least 4")
    unique_features = tuple(dict.fromkeys(feature for feature in features if feature))
    if not unique_features:
        raise ValueError("at least one feature is required")
    if not 0.0 < family_alpha <= 0.05:
        raise ValueError("family_alpha must be in (0, 0.05]")

    ordered = sorted(rows, key=lambda row: _utc(row.candidate_at))
    split = max(1, min(len(ordered) - 1, int(len(ordered) * (1.0 - holdout_fraction))))
    discovery = ordered[:split]
    holdout = ordered[split:]
    trial_count = len(unique_features)
    adjusted_alpha = family_alpha / trial_count

    output: list[FeatureDiscoveryResult] = []
    for index, feature in enumerate(unique_features):
        dx, dy = _paired_values(discovery, feature)
        hx, hy = _paired_values(holdout, feature)
        discovery_corr = _pearson(dx, dy)
        holdout_corr = _pearson(hx, hy)

        placebo = list(hy)
        random.Random(seed + index).shuffle(placebo)
        placebo_corr = _pearson(hx, placebo)
        ci_low, ci_high = _fisher_ci(holdout_corr, len(hx), adjusted_alpha)

        if len(dx) < min_samples or len(hx) < min_samples:
            status = "insufficient_evidence"
        elif discovery_corr is None or holdout_corr is None:
            status = "insufficient_variation"
        else:
            # A discovery result is evidence only. It never becomes a production
            # strategy or promotion decision inside this module.
            status = "research_evidence"

        output.append(
            FeatureDiscoveryResult(
                feature=feature,
                trial_count=trial_count,
                discovery_n=len(dx),
                holdout_n=len(hx),
                discovery_correlation=discovery_corr,
                holdout_correlation=holdout_corr,
                holdout_ci_low=ci_low,
                holdout_ci_high=ci_high,
                placebo_abs_correlation=abs(placebo_corr) if placebo_corr is not None else None,
                adjusted_alpha=adjusted_alpha,
                status=status,
            )
        )

    return sorted(
        output,
        key=lambda result: (
            -(abs(result.discovery_correlation) if result.discovery_correlation is not None else -1.0),
            result.feature,
        ),
    )
