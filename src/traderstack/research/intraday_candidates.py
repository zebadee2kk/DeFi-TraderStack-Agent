"""Pre-registered 4h/1h dual-print catalog (not a daily-EMA hunt).

Frozen before any Kraken or Binance.US pull. Do not grow after seeing PnL.

Core families are MA cross, momentum, mean-reversion, and candle-only
vol-regime wrappers from the #89/#105 price catalog, plus a small
4h-appropriate lookback grid. Two EMA names are informational controls
so a 4h reprint of the daily family cannot be mistaken for the hunt.

Funding-z / OI-z instantiate **only** when an aligned historical series
is supplied. Liquidation-z and cross-venue stay skipped (no aligned
Spot-OHLC series; #105). Never zero-fill a missing feature.
"""

from __future__ import annotations

from datetime import datetime
from typing import cast

from traderstack.research.candidates import (
    SearchCandidate as PriceCandidate,
)
from traderstack.research.candidates import (
    _ma,
    _mom,
    _mr,
    default_price_candidates,
    expanded_price_candidates,
    feature_candidates,
)
from traderstack.research.miles_candidates import (
    DirectionStrategy,
    EmaCrossoverStrategy,
    SearchCandidate,
)

ALLOWED_INTERVALS: tuple[str, ...] = ("4h", "1h")
DEFAULT_INTERVAL = "4h"

INTRADAY_DUAL_PRINT_CORE_IDS: tuple[str, ...] = (
    # #89 price-only (not EMA)
    "ma_cross_5_20",
    "ma_cross_10_30",
    "ma_cross_20_50",
    "ma_cross_10_30_wide",
    "ma_always_on_10_30",
    "momentum_6",
    "momentum_12",
    "momentum_24",
    "momentum_12_strict",
    "mean_reversion_20_1_5",
    "mean_reversion_20_2_0",
    "mean_reversion_10_1_5",
    "mean_reversion_40_2_0",
    # candle-only vol-regime wrappers
    "ma_cross_10_30_vol",
    "ma_always_on_10_30_vol",
    "momentum_6_vol",
    "momentum_12_vol",
    "mean_reversion_20_1_5_vol",
    "mean_reversion_20_2_0_vol",
    # 4h/1h lookback grid (pre-registered; not fit after the print)
    "ma_cross_8_21",
    "ma_cross_12_36",
    "ma_cross_15_45",
    "momentum_18",
    "momentum_36",
    "momentum_48",
    "mean_reversion_30_1_5",
    "mean_reversion_24_2_0",
    "ma_cross_8_21_vol",
    "momentum_18_vol",
    "mean_reversion_30_1_5_vol",
    # informational EMA controls (not the hunt family)
    "ema_9_21",
    "ema_12_26",
)

OPTIONAL_FEATURE_IDS: tuple[str, ...] = (
    "funding_z_fade",
    "funding_z_follow",
    "oi_z_fade",
    "oi_z_follow",
)

INTRADAY_DUAL_PRINT_GRID_NOTE = (
    "Pre-registered 4h/1h dual-print catalog (frozen before any Kraken or "
    "Binance.US pull). Not a daily-EMA hunt. Core K="
    f"{len(INTRADAY_DUAL_PRINT_CORE_IDS)}: MA / momentum / mean-reversion "
    "plus candle-only vol-regime wrappers and a small 4h-appropriate "
    "lookback grid. `ema_9_21` and `ema_12_26` are informational controls "
    "only. Funding-z / OI-z instantiate only when an aligned historical "
    "series is fetched (OKX public history when reachable); liquidation-z "
    "and cross-venue stay skipped (no aligned Spot series; #105). Do not "
    "grow this list after seeing PnL. PAPER_PROMOTE_* stays false unless "
    "a committed dual-print report names a paper-only pin and an operator "
    "flips it."
)


def as_miles_candidate(candidate: PriceCandidate) -> SearchCandidate:
    """Adapt a #89 price/feature voter to the harder-gates SearchCandidate."""
    if not callable(getattr(candidate.strategy, "evaluate", None)):
        raise TypeError(f"{candidate.candidate_id} is missing evaluate()")
    return SearchCandidate(
        candidate_id=candidate.candidate_id,
        family=candidate.family,
        label=candidate.label,
        params=dict(candidate.params),
        strategy=cast(DirectionStrategy, candidate.strategy),
    )


def _ema_control(candidate_id: str, *, fast: int, slow: int) -> SearchCandidate:
    return SearchCandidate(
        candidate_id=candidate_id,
        family="ema_cross",
        label=f"EMA {fast}/{slow} (intraday control; not the hunt family)",
        params={
            "fast_span": fast,
            "slow_span": slow,
            "strategy_id": candidate_id,
        },
        strategy=EmaCrossoverStrategy(
            strategy_id=candidate_id,
            fast_span=fast,
            slow_span=slow,
        ),
    )


def _extra_price_candidates() -> tuple[PriceCandidate, ...]:
    return (
        _ma("ma_cross_8_21", short_window=8, long_window=21),
        _ma("ma_cross_12_36", short_window=12, long_window=36),
        _ma("ma_cross_15_45", short_window=15, long_window=45),
        _mom("momentum_18", lookback=18),
        _mom("momentum_36", lookback=36),
        _mom("momentum_48", lookback=48),
        _mr("mean_reversion_30_1_5", lookback=30, entry_z=1.5),
        _mr("mean_reversion_24_2_0", lookback=24, entry_z=2.0),
        _ma("ma_cross_8_21_vol", short_window=8, long_window=21, vol_regime_filter=True),
        _mom("momentum_18_vol", lookback=18, vol_regime_filter=True),
        _mr("mean_reversion_30_1_5_vol", lookback=30, entry_z=1.5, vol_regime_filter=True),
    )


def _price_core() -> tuple[SearchCandidate, ...]:
    expanded = {item.candidate_id: item for item in expanded_price_candidates()}
    defaults = {item.candidate_id: item for item in default_price_candidates()}
    extras = {item.candidate_id: item for item in _extra_price_candidates()}
    combined = {**defaults, **expanded, **extras}
    out: list[SearchCandidate] = []
    for candidate_id in INTRADAY_DUAL_PRINT_CORE_IDS:
        if candidate_id in {"ema_9_21", "ema_12_26"}:
            fast, slow = (9, 21) if candidate_id == "ema_9_21" else (12, 26)
            out.append(_ema_control(candidate_id, fast=fast, slow=slow))
            continue
        item = combined.get(candidate_id)
        if item is None:
            raise RuntimeError(f"intraday core id missing from price catalog: {candidate_id}")
        out.append(as_miles_candidate(item))
    return tuple(out)


def default_intraday_dual_print_candidates(
    *,
    funding: tuple[tuple[datetime, float], ...] | None = None,
    funding_by_symbol: dict[str, tuple[tuple[datetime, float], ...]] | None = None,
    open_interest: tuple[tuple[datetime, float], ...] | None = None,
    open_interest_by_symbol: dict[str, tuple[tuple[datetime, float], ...]] | None = None,
) -> tuple[SearchCandidate, ...]:
    """Frozen catalog. Feature families omitted when no series is supplied."""
    core = _price_core()
    extras = feature_candidates(
        funding=funding,
        funding_by_symbol=funding_by_symbol,
        open_interest=open_interest,
        open_interest_by_symbol=open_interest_by_symbol,
    )
    allowed = set(OPTIONAL_FEATURE_IDS)
    optional = tuple(as_miles_candidate(item) for item in extras if item.candidate_id in allowed)
    catalog = core + optional
    scored_ids = [item.candidate_id for item in catalog]
    if scored_ids[: len(INTRADAY_DUAL_PRINT_CORE_IDS)] != list(INTRADAY_DUAL_PRINT_CORE_IDS):
        raise RuntimeError("intraday dual-print catalog drifted from the frozen id list")
    unexpected = [
        item for item in scored_ids[len(INTRADAY_DUAL_PRINT_CORE_IDS) :] if item not in allowed
    ]
    if unexpected:
        raise RuntimeError(f"intraday optional catalog drifted: {unexpected}")
    return catalog


def skipped_optional_families(
    *,
    funding_present: bool,
    open_interest_present: bool,
) -> list[str]:
    notes: list[str] = [
        "liquidation_z: skipped — no aligned historical Spot series (#105). Not invented.",
        "cross_venue: skipped — no aligned two-venue historical series. Not invented.",
    ]
    if not funding_present:
        notes.append("funding_z: skipped — no aligned funding-rate history supplied. Not invented.")
    if not open_interest_present:
        notes.append(
            "open_interest_z: skipped — no aligned open-interest history supplied. Not invented."
        )
    return notes
