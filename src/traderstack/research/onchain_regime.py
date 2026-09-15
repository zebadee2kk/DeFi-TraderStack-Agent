"""On-chain regime overlay on the frozen TSMOM catalog (#139).

Pre-registered before any live pull (do not retune after seeing PnL).

Treatment (frozen): every non-control name of the frozen time-series
momentum catalog (``tsmom.TSMOM_CATALOG``) is scored **ungated** and
**gated**. A gated name is the same voter wrapped in
``OnChainRegimeGateVoter``: a BUY from the inner voter is withheld (flat)
when the newest Coin Metrics community regime point with ``time``
**strictly before** the decision bar breaches the overlay rule; SELL and
flat pass through untouched. A missing or stale (> 3 days) regime point
also withholds the BUY (fail closed; never forward-filled, never
zero-filled). The BTC series gates every scored name (frozen
market-regime assumption: SOL has no community MVRV, ETH's own series is
a follow-up).

Overlay catalog (frozen): ``mvrvz_p90`` (MVRV-Z trailing-window
percentile > 0.90), ``mvrvz_p80`` (> 0.80), ``nupl_075`` (NUPL > 0.75).
Gated ids are ``<base>__<overlay>``.

Prints: the two existing non-overlapping prints (Kraken public Spot
daily 720 and the #102 Binance.US older-720), scored with the same
``#96+A+B+C`` combined gates as ``tsmom.run_tsmom_search``. For each
print the report shows ungated vs gated mean holdout excess and
walk-forward total, their deltas, and how many bars the overlay would
have blocked. Verdict per overlay × base name (frozen): ``helps`` when
the mean-HO delta is > 0 on every scored print and < 0 on none,
``hurts`` the mirror, ``mixed_fail`` when it helps on one print / metric
and hurts on another, ``neutral`` when the gate never bound, ``skipped``
when the regime series does not cover a print (a skip, never a zero). The
deltas considered are mean holdout excess **and** walk-forward total on
every scored print — a gate that lifts the holdout while cutting the
walk-forward is a FAIL, not an edge.

Passer rule (frozen): a gated name is an *overlay passer* only if it is a
dual-print passer (combined on both prints) **and** both deltas (mean HO,
WF total) are >= 0 on both prints. The control ``ma_cross_10_30`` is scored ungated,
informational, and cannot pass. Empty overlay-passer set is success.
This module never flips ``PAPER_PROMOTE_*``; ``can_promote`` is False on
every row. No live. Era prints / DSR / PBO (#135, #136) are a follow-up.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

from traderstack.candles import Candle
from traderstack.market.coinmetrics import (
    COINMETRICS_SKIPPED_METRICS_NOTE,
    COINMETRICS_SOURCE_ID,
    ONCHAIN_REGIME_FEATURE_VERSION,
    ONCHAIN_REGIME_MAX_STALE_DAYS,
    ONCHAIN_REGIME_MIN_POINTS,
    ONCHAIN_REGIME_WINDOW_DAYS,
    OnChainRegimePoint,
)
from traderstack.models import Side
from traderstack.research.binance_spot import BINANCE_TAKER_BPS_NOTE
from traderstack.research.daily_robustness import KRAKEN_DAILY_CAP_NOTE
from traderstack.research.dual_print_search import (
    CAN_AVERAGE_VENUES,
    CAN_ENTER_PROMOTION_AVERAGE,
    MULTI_VENUE_BAR_PREREGISTERED,
    RANKING_KEY,
    DualPrintRow,
    _binance_slice_meta,
    _merge_row,
    _score,
    rank_dual_print_passers,
)
from traderstack.research.harder_gates import (
    HARDER_GATES_NOTE,
    CandidateHarderResult,
    _pct,
    _verdict,
    kraken_daily_candles,
)
from traderstack.research.miles_candidates import DirectionStrategy, SearchCandidate
from traderstack.research.second_print import (
    BINANCE_SLICE_RULE,
    SECOND_PRINT_BARS,
    SliceMeta,
    primary_first_opened_at,
    remap_binance_for_scoring,
    slice_ending_before,
)
from traderstack.research.tsmom import (
    CONTROL_ID,
    CONTROL_IDS,
    MULTI_ASSET_GATE_RULE,
    TSMOM_IDS,
    _control_candidate,
    _score_symbols_only,
    tsmom_candidates,
)
from traderstack.strategies import Regime, StrategySignal

OverlayField = Literal["mvrv_z_percentile", "nupl"]
OverlayVerdict = Literal["helps", "hurts", "mixed_fail", "neutral", "skipped"]

# (overlay_id, regime field, threshold) — BUY withheld when field > threshold.
OVERLAY_CATALOG: tuple[tuple[str, OverlayField, float], ...] = (
    ("mvrvz_p90", "mvrv_z_percentile", 0.90),
    ("mvrvz_p80", "mvrv_z_percentile", 0.80),
    ("nupl_075", "nupl", 0.75),
)
OVERLAY_IDS: tuple[str, ...] = tuple(item[0] for item in OVERLAY_CATALOG)
GATED_ID_SEPARATOR = "__"
REGIME_SOURCE_ASSET = "btc"
REGIME_DECISION_RULE = "newest_regime_row_strictly_before_decision_bar"
REGIME_STALE_RULE = f"no_forward_fill_beyond_{ONCHAIN_REGIME_MAX_STALE_DAYS}_days"
OVERLAY_VERDICT_RULE = (
    "over_mean_ho_and_wf_total_deltas_on_every_scored_print:"
    "helps_if_some_gt_0_and_none_lt_0;hurts_if_some_lt_0_and_none_gt_0;"
    "mixed_fail_if_both_signs;neutral_if_all_zero"
)
OVERLAY_PASSER_RULE = (
    "gated_name_dual_print_passer_and_mean_ho_and_wf_total_deltas_ge_0_on_both_prints"
)
SELECTION_RULE = "pre_registered_top1_mean_holdout_excess_among_overlay_passers"
CAN_PROMOTE = False

ONCHAIN_REGIME_RULES = (
    "Pre-registered on-chain regime overlay (frozen before any Coin Metrics, "
    "Kraken or Binance.US score). Base catalog: the frozen TSMOM names "
    f"({', '.join(TSMOM_IDS)}); control {CONTROL_ID} is scored ungated, "
    "informational, and cannot pass. Treatment: each base name is scored "
    "ungated and gated; a gated name withholds a BUY (flat) when the newest "
    "Coin Metrics community regime row with time strictly before the "
    f"decision bar (`{REGIME_DECISION_RULE}`) breaches the overlay rule; "
    "SELL and flat pass through untouched; a missing or stale row "
    f"(`{REGIME_STALE_RULE}`) also withholds the BUY (fail closed, never "
    "forward-filled, never zero-filled). Regime features are "
    f"{ONCHAIN_REGIME_FEATURE_VERSION}: MVRV-Z = (mcap − realised cap) / "
    f"pstdev(mcap over the trailing {ONCHAIN_REGIME_WINDOW_DAYS} rows), "
    "percentile = rank of MVRV-Z inside that trailing window, NUPL = "
    f"1 − 1/MVRV; None until {ONCHAIN_REGIME_MIN_POINTS} points. Overlays "
    "(frozen): mvrvz_p90 (percentile > 0.90), mvrvz_p80 (> 0.80), nupl_075 "
    "(NUPL > 0.75). The BTC series gates every scored name (frozen "
    "market-regime assumption; SOL has no community MVRV; ETH's own series "
    "is a follow-up). Prints: Kraken public Spot daily 720 AND the #102 "
    f"Binance.US older-720 (`{BINANCE_SLICE_RULE}`: {SECOND_PRINT_BARS} "
    "committed BTC+ETH bars ending strictly before the primary Kraken first "
    "bar), each scored with the #96+A+B+C combined gates on BTC+ETH (SOL "
    f"reported, not a gate; `{MULTI_ASSET_GATE_RULE}`). An overlay whose "
    "series does not cover a print is skipped on that print (a skip, never "
    "a zero). Deltas are gated − ungated mean holdout excess AND walk-forward "
    f"total on every scored print. Verdict rule: `{OVERLAY_VERDICT_RULE}`. Passer rule: "
    f"`{OVERLAY_PASSER_RULE}`. Ranking key among overlay passers: "
    f"{RANKING_KEY} (Kraken mean holdout excess; tie-break gated id). "
    f"CAN_AVERAGE_VENUES={str(CAN_AVERAGE_VENUES).lower()}; "
    f"MULTI_VENUE_BAR_PREREGISTERED={str(MULTI_VENUE_BAR_PREREGISTERED).lower()}; "
    f"CAN_PROMOTE={str(CAN_PROMOTE).lower()}. Fees are paper-research 10+5 "
    "(gate C 20+10). PAPER_PROMOTE_* stays default false. No live. An empty "
    "overlay-passer set is success. Era prints, Deflated Sharpe and PBO "
    "(#135/#136) are a follow-up, not claimed here."
)

OVERLAY_CATALOG_NOTE = (
    "Frozen overlay catalog (3): mvrvz_p90, mvrvz_p80 (MVRV-Z trailing-window "
    "percentile) and nupl_075 (NUPL). Applied to the 8 frozen TSMOM names → 24 "
    "gated ids. Do not grow this list, move a threshold, or change the window "
    "after seeing PnL. The runtime gate (ONCHAIN_REGIME_GATE_ENABLED) uses the "
    "MVRV-Z percentile only; NUPL is published as a feature and scored here."
)


# --- point-in-time lookup -----------------------------------------------------


def _day_start(point: OnChainRegimePoint) -> datetime:
    return datetime(point.day.year, point.day.month, point.day.day, tzinfo=UTC)


@dataclass(frozen=True)
class RegimeLookup:
    """Sorted index over a regime series; same semantics as
    ``coinmetrics.regime_point_before`` (strict ``<``, stale → None)."""

    day_starts: tuple[datetime, ...]
    points: tuple[OnChainRegimePoint, ...]
    max_stale_days: int = ONCHAIN_REGIME_MAX_STALE_DAYS

    @classmethod
    def from_series(
        cls,
        series: tuple[OnChainRegimePoint, ...],
        *,
        max_stale_days: int = ONCHAIN_REGIME_MAX_STALE_DAYS,
    ) -> RegimeLookup:
        ordered = tuple(sorted(series, key=lambda point: point.day))
        return cls(
            day_starts=tuple(_day_start(point) for point in ordered),
            points=ordered,
            max_stale_days=max_stale_days,
        )

    def before(self, decision_at: datetime) -> OnChainRegimePoint | None:
        if decision_at.tzinfo is None:
            decision_at = decision_at.replace(tzinfo=UTC)
        decision_at = decision_at.astimezone(UTC)
        index = bisect.bisect_left(self.day_starts, decision_at) - 1
        if index < 0:
            return None
        point = self.points[index]
        if (decision_at.date() - point.day).days > self.max_stale_days:
            return None
        return point

    def value_before(self, decision_at: datetime, field_name: str) -> float | None:
        point = self.before(decision_at)
        if point is None:
            return None
        value = getattr(point, field_name, None)
        return value if isinstance(value, float) else None


@dataclass(frozen=True)
class OnChainRegimeGateVoter:
    """Wrap a direction voter; withhold its BUY when the regime is hot.

    Withhold-only: SELL / flat from the inner voter pass through. Missing
    or stale regime → flat (fail closed), never forward-filled.
    """

    inner: DirectionStrategy
    strategy_id: str
    overlay_id: str
    regime_field: str
    threshold: float
    lookup: RegimeLookup = field(default_factory=lambda: RegimeLookup((), ()))

    def evaluate(self, candles: tuple[Candle, ...], regime: Regime) -> StrategySignal:
        signal = self.inner.evaluate(candles, regime)
        if signal.side is not Side.BUY:
            return signal.model_copy(update={"strategy_id": self.strategy_id})
        value = self.lookup.value_before(candles[-1].opened_at, self.regime_field)
        if value is None:
            return signal.model_copy(
                update={
                    "strategy_id": self.strategy_id,
                    "side": None,
                    "score": 0.0,
                    "confidence": 0.0,
                    "rationale": (
                        f"{self.overlay_id}: no committed {self.regime_field} strictly before "
                        "the bar (or stale) → BUY withheld"
                    ),
                }
            )
        if value > self.threshold:
            return signal.model_copy(
                update={
                    "strategy_id": self.strategy_id,
                    "side": None,
                    "score": 0.0,
                    "confidence": 0.0,
                    "rationale": (
                        f"{self.overlay_id}: {self.regime_field}={value:.3f} > "
                        f"{self.threshold:g} → BUY withheld"
                    ),
                }
            )
        return signal.model_copy(update={"strategy_id": self.strategy_id})


def gated_id(base_id: str, overlay_id: str) -> str:
    return f"{base_id}{GATED_ID_SEPARATOR}{overlay_id}"


def gated_candidate(
    base: SearchCandidate,
    overlay: tuple[str, OverlayField, float],
    lookup: RegimeLookup,
) -> SearchCandidate:
    overlay_id, field_name, threshold = overlay
    ident = gated_id(base.candidate_id, overlay_id)
    return SearchCandidate(
        candidate_id=ident,
        family="tsmom_onchain_regime",
        label=f"{base.label} gated by {overlay_id} ({field_name} > {threshold:g})",
        params={
            **base.params,
            "base_id": base.candidate_id,
            "overlay_id": overlay_id,
            "regime_field": field_name,
            "regime_threshold": threshold,
            "regime_decision_rule": REGIME_DECISION_RULE,
            "regime_source_asset": REGIME_SOURCE_ASSET,
            "regime_feature_version": ONCHAIN_REGIME_FEATURE_VERSION,
            "strategy_id": ident,
        },
        strategy=OnChainRegimeGateVoter(
            inner=base.strategy,
            strategy_id=ident,
            overlay_id=overlay_id,
            regime_field=field_name,
            threshold=threshold,
            lookup=lookup,
        ),
        garch_sizing=base.garch_sizing,
    )


def regime_coverage_usable(
    series: tuple[OnChainRegimePoint, ...],
    candles: tuple[Candle, ...] | None,
    *,
    field_name: str,
    max_stale_days: int = ONCHAIN_REGIME_MAX_STALE_DAYS,
) -> tuple[bool, str | None]:
    """An overlay is usable on a print only when **every** scored bar has a
    committed, non-None value strictly before it. Otherwise skip (never
    zero-fill)."""
    if not series:
        return False, "no regime series (Coin Metrics skipped)"
    if not candles:
        return False, "no candles to cover"
    lookup = RegimeLookup.from_series(series, max_stale_days=max_stale_days)
    missing = sum(
        1 for candle in candles if lookup.value_before(candle.opened_at, field_name) is None
    )
    if missing:
        return (
            False,
            (
                f"{missing} of {len(candles)} bars lack a committed {field_name} strictly "
                f"before the bar (within {max_stale_days} d); overlay skipped on this print"
            ),
        )
    return True, None


def blocked_days(
    series: tuple[OnChainRegimePoint, ...],
    candles: tuple[Candle, ...] | None,
    *,
    field_name: str,
    threshold: float,
) -> int | None:
    if not series or not candles:
        return None
    lookup = RegimeLookup.from_series(series)
    count = 0
    for candle in candles:
        value = lookup.value_before(candle.opened_at, field_name)
        if value is not None and value > threshold:
            count += 1
    return count


def overlay_verdict(
    *,
    kraken_delta: float | None,
    binance_delta: float | None,
    kraken_scored: bool,
    binance_scored: bool,
    kraken_delta_wf: float | None = None,
    binance_delta_wf: float | None = None,
) -> OverlayVerdict:
    """Frozen verdict over BOTH metrics (mean HO, WF total) on every scored
    print. Helping on one print/metric while hurting on another is a FAIL."""
    deltas: list[float] = []
    for print_deltas, scored in (
        ((kraken_delta, kraken_delta_wf), kraken_scored),
        ((binance_delta, binance_delta_wf), binance_scored),
    ):
        if not scored:
            continue
        if print_deltas[0] is None:
            return "skipped"
        deltas.append(print_deltas[0])
        if print_deltas[1] is not None:
            deltas.append(print_deltas[1])
    if not deltas:
        return "skipped"
    positive = any(delta > 0 for delta in deltas)
    negative = any(delta < 0 for delta in deltas)
    if positive and negative:
        return "mixed_fail"
    if positive:
        return "helps"
    if negative:
        return "hurts"
    return "neutral"


# --- report models -------------------------------------------------------------


class OverlayEffectRow(BaseModel):
    overlay_id: str
    field: str
    threshold: float
    base_id: str
    gated_id: str
    kraken_scored: bool = False
    binance_scored: bool = False
    kraken_ungated_mean_ho: float | None = None
    kraken_gated_mean_ho: float | None = None
    kraken_delta_mean_ho: float | None = None
    kraken_ungated_wf: float | None = None
    kraken_gated_wf: float | None = None
    kraken_delta_wf: float | None = None
    binance_ungated_mean_ho: float | None = None
    binance_gated_mean_ho: float | None = None
    binance_delta_mean_ho: float | None = None
    binance_ungated_wf: float | None = None
    binance_gated_wf: float | None = None
    binance_delta_wf: float | None = None
    kraken_blocked_days: int | None = None
    binance_blocked_days: int | None = None
    base_dual_print: bool = False
    gated_dual_print: bool = False
    verdict: OverlayVerdict = "skipped"
    skipped_reason: str | None = None
    overlay_passer: bool = False
    can_promote: bool = False
    keep_flag_false: bool = True


class OverlayCoverage(BaseModel):
    print: str
    overlay_id: str
    usable: bool
    reason: str | None = None
    blocked_days: int | None = None
    bars: int = 0


class OnChainRegimeReport(BaseModel):
    generated_at: datetime
    ranking_key: str = RANKING_KEY
    selection_rule: str = SELECTION_RULE
    overlay_verdict_rule: str = OVERLAY_VERDICT_RULE
    overlay_passer_rule: str = OVERLAY_PASSER_RULE
    regime_decision_rule: str = REGIME_DECISION_RULE
    regime_stale_rule: str = REGIME_STALE_RULE
    base_catalog_ids: list[str] = Field(default_factory=list)
    control_id: str = CONTROL_ID
    overlay_catalog: list[dict[str, object]] = Field(default_factory=list)
    overlay_catalog_note: str = OVERLAY_CATALOG_NOTE
    fee_bps: float
    slippage_bps: float
    train_size: int
    test_size: int
    step_size: int
    holdout_fraction: float
    min_trades: int
    primary_first: str
    primary_first_source: str
    primary_last: str | None = None
    primary_bars: int | None = None
    primary_bars_eth: int | None = None
    primary_bars_sol: int | None = None
    binance_slice: SliceMeta
    binance_source: str | None = None
    regime_source_id: str = COINMETRICS_SOURCE_ID
    regime_source_asset: str = REGIME_SOURCE_ASSET
    regime_status: Literal["ok", "skipped"] = "skipped"
    regime_skip_reason: str | None = None
    regime_first_day: str | None = None
    regime_last_day: str | None = None
    regime_points: int = 0
    regime_feature_version: str = ONCHAIN_REGIME_FEATURE_VERSION
    regime_window_days: int = ONCHAIN_REGIME_WINDOW_DAYS
    regime_min_points: int = ONCHAIN_REGIME_MIN_POINTS
    regime_max_stale_days: int = ONCHAIN_REGIME_MAX_STALE_DAYS
    coverage: list[OverlayCoverage] = Field(default_factory=list)
    rows: list[DualPrintRow] = Field(default_factory=list)
    effects: list[OverlayEffectRow] = Field(default_factory=list)
    base_dual_print_passer_ids: list[str] = Field(default_factory=list)
    overlay_passer_ids: list[str] = Field(default_factory=list)
    mixed_fail_ids: list[str] = Field(default_factory=list)
    any_base_dual_print_passer: bool = False
    any_overlay_passer: bool = False
    selected_gated_id: str | None = None
    multi_venue_bar_preregistered: bool = MULTI_VENUE_BAR_PREREGISTERED
    can_average_venues: bool = CAN_AVERAGE_VENUES
    can_enter_promotion_average: bool = CAN_ENTER_PROMOTION_AVERAGE
    can_promote: bool = CAN_PROMOTE
    keep_flag_false: bool = True
    honesty: str
    recommendation: str
    rules: str = ONCHAIN_REGIME_RULES
    gates_note: str = HARDER_GATES_NOTE
    fee_note: str = BINANCE_TAKER_BPS_NOTE
    kraken_cap_note: str = KRAKEN_DAILY_CAP_NOTE
    skipped_metrics_note: str = COINMETRICS_SKIPPED_METRICS_NOTE
    data_notes: list[str] = Field(default_factory=list)


# --- search --------------------------------------------------------------------


def _coverage_candles(histories: dict[str, tuple[Candle, ...]]) -> tuple[Candle, ...] | None:
    return kraken_daily_candles(histories, "BTC/USD") or kraken_daily_candles(histories, "ETH/USD")


def _print_catalog(
    *,
    print_name: str,
    base: tuple[SearchCandidate, ...],
    series: tuple[OnChainRegimePoint, ...],
    coverage_candles: tuple[Candle, ...] | None,
    overlays: tuple[tuple[str, OverlayField, float], ...],
) -> tuple[tuple[SearchCandidate, ...], list[OverlayCoverage], dict[str, SearchCandidate]]:
    """Base + control + every gated name whose overlay covers this print."""
    catalog: list[SearchCandidate] = [*base, _control_candidate()]
    coverage: list[OverlayCoverage] = []
    gated: dict[str, SearchCandidate] = {}
    lookup = RegimeLookup.from_series(series) if series else None
    for overlay in overlays:
        overlay_id, field_name, threshold = overlay
        usable, reason = regime_coverage_usable(series, coverage_candles, field_name=field_name)
        coverage.append(
            OverlayCoverage(
                print=print_name,
                overlay_id=overlay_id,
                usable=usable,
                reason=reason,
                blocked_days=(
                    blocked_days(
                        series, coverage_candles, field_name=field_name, threshold=threshold
                    )
                    if usable
                    else None
                ),
                bars=len(coverage_candles or ()),
            )
        )
        if not usable or lookup is None:
            continue
        for candidate in base:
            if candidate.candidate_id in CONTROL_IDS:
                continue
            wrapped = gated_candidate(candidate, overlay, lookup)
            catalog.append(wrapped)
            gated[wrapped.candidate_id] = wrapped
    return tuple(catalog), coverage, gated


def _mean_ho_or_neg_inf(row: DualPrintRow) -> float:
    value = row.kraken_mean_holdout_excess
    return value if value is not None else float("-inf")


def _delta(gated: float | None, ungated: float | None) -> float | None:
    if gated is None or ungated is None:
        return None
    return gated - ungated


def _effect_row(
    *,
    overlay: tuple[str, OverlayField, float],
    base: SearchCandidate,
    kraken_by_id: dict[str, CandidateHarderResult],
    binance_by_id: dict[str, CandidateHarderResult],
    kraken_usable: bool,
    binance_usable: bool,
    kraken_blocked: int | None,
    binance_blocked: int | None,
    rows_by_id: dict[str, DualPrintRow],
) -> OverlayEffectRow:
    overlay_id, field_name, threshold = overlay
    ident = gated_id(base.candidate_id, overlay_id)
    k_base = kraken_by_id.get(base.candidate_id)
    k_gated = kraken_by_id.get(ident)
    b_base = binance_by_id.get(base.candidate_id)
    b_gated = binance_by_id.get(ident)
    kraken_scored = kraken_usable and k_base is not None and k_gated is not None
    binance_scored = binance_usable and b_base is not None and b_gated is not None
    k_delta = (
        _delta(k_gated.mean_holdout_excess, k_base.mean_holdout_excess)
        if kraken_scored and k_gated is not None and k_base is not None
        else None
    )
    b_delta = (
        _delta(b_gated.mean_holdout_excess, b_base.mean_holdout_excess)
        if binance_scored and b_gated is not None and b_base is not None
        else None
    )
    k_delta_wf = (
        _delta(k_gated.baseline_wf_total, k_base.baseline_wf_total)
        if kraken_scored and k_gated is not None and k_base is not None
        else None
    )
    b_delta_wf = (
        _delta(b_gated.baseline_wf_total, b_base.baseline_wf_total)
        if binance_scored and b_gated is not None and b_base is not None
        else None
    )
    verdict = overlay_verdict(
        kraken_delta=k_delta,
        binance_delta=b_delta,
        kraken_scored=kraken_scored,
        binance_scored=binance_scored,
        kraken_delta_wf=k_delta_wf,
        binance_delta_wf=b_delta_wf,
    )
    skipped_reason = None
    if verdict == "skipped":
        skipped_reason = (
            "overlay not scored on any print (regime coverage or base row missing); skip-not-invent"
        )
    base_row = rows_by_id.get(base.candidate_id)
    gated_row = rows_by_id.get(ident)
    gated_dual = bool(gated_row is not None and gated_row.dual_print)
    passer = bool(
        gated_dual
        and kraken_scored
        and binance_scored
        and all(
            delta is not None and delta >= 0 for delta in (k_delta, b_delta, k_delta_wf, b_delta_wf)
        )
    )
    return OverlayEffectRow(
        overlay_id=overlay_id,
        field=field_name,
        threshold=threshold,
        base_id=base.candidate_id,
        gated_id=ident,
        kraken_scored=kraken_scored,
        binance_scored=binance_scored,
        kraken_ungated_mean_ho=k_base.mean_holdout_excess if k_base else None,
        kraken_gated_mean_ho=k_gated.mean_holdout_excess if kraken_scored and k_gated else None,
        kraken_delta_mean_ho=k_delta,
        kraken_ungated_wf=k_base.baseline_wf_total if k_base else None,
        kraken_gated_wf=k_gated.baseline_wf_total if kraken_scored and k_gated else None,
        kraken_delta_wf=k_delta_wf,
        binance_ungated_mean_ho=b_base.mean_holdout_excess if b_base else None,
        binance_gated_mean_ho=b_gated.mean_holdout_excess if binance_scored and b_gated else None,
        binance_delta_mean_ho=b_delta,
        binance_ungated_wf=b_base.baseline_wf_total if b_base else None,
        binance_gated_wf=b_gated.baseline_wf_total if binance_scored and b_gated else None,
        binance_delta_wf=b_delta_wf,
        kraken_blocked_days=kraken_blocked if kraken_scored else None,
        binance_blocked_days=binance_blocked if binance_scored else None,
        base_dual_print=bool(base_row is not None and base_row.dual_print),
        gated_dual_print=gated_dual,
        verdict=verdict,
        skipped_reason=skipped_reason,
        overlay_passer=passer,
        can_promote=False,
        keep_flag_false=True,
    )


def _recommendation(
    *,
    overlay_passers: list[str],
    base_passers: list[str],
    mixed: list[str],
    regime_status: str,
    binance_meta: SliceMeta,
) -> str:
    lines = [
        (
            "**Keep every `PAPER_PROMOTE_*=false`.** This overlay search does "
            "not flip a pin, does not add a pin, and does not enable live. An "
            "empty overlay-passer set is the successful outcome."
        ),
        "",
        (
            f"- Coin Metrics community regime series: **{regime_status}**"
            + (
                "; every overlay was skipped (not zero-filled) and only the ungated "
                "base catalog was scored."
                if regime_status != "ok"
                else "."
            )
        ),
        (
            f"- Overlay passers (`{OVERLAY_PASSER_RULE}`): {len(overlay_passers)}"
            + (f" (`{'`, `'.join(overlay_passers)}`)" if overlay_passers else " (none)")
            + "."
        ),
        (
            f"- Base (ungated) dual-print passers: {len(base_passers)}"
            + (f" (`{'`, `'.join(base_passers)}`)" if base_passers else " (none)")
            + "; unchanged from `traderstack-tsmom` by construction."
        ),
        (
            f"- Binance.US `{BINANCE_SLICE_RULE}`: "
            f"{'scored' if binance_meta.available else 'FAIL-CLOSED'} "
            f"({binance_meta.venue}; {binance_meta.bars_btc} BTC / "
            f"{binance_meta.bars_eth} ETH; {binance_meta.first} → {binance_meta.last})."
        ),
    ]
    if mixed:
        lines.append(
            "- **mixed_fail** (helps on one print/metric, hurts on another): "
            + ", ".join(f"`{item}`" for item in mixed)
            + ". Reported as FAIL, not as an edge."
        )
    lines.append(
        "- The runtime gate (`ONCHAIN_REGIME_GATE_ENABLED`) stays **off** by "
        "default regardless of this table; it can only withhold new longs."
    )
    lines.append(
        "- Do not enable live. Do not fabricate PnL. Do not retune thresholds, "
        "the window, or the overlay list after seeing this table. Era prints / "
        "DSR / PBO (#135, #136) are a follow-up."
    )
    return "\n".join(lines)


def run_onchain_regime_search(
    kraken_histories: dict[str, tuple[Candle, ...]],
    binance_histories: dict[str, tuple[Candle, ...]] | None = None,
    regime_series: tuple[OnChainRegimePoint, ...] = (),
    *,
    fee_bps: float,
    slippage_bps: float = 5.0,
    starting_equity: float = 10_000.0,
    train_size: int = 180,
    test_size: int = 60,
    step_size: int = 60,
    holdout_fraction: float = 0.20,
    min_trades: int = 3,
    base_candidates: tuple[SearchCandidate, ...] | None = None,
    binance_base_candidates: tuple[SearchCandidate, ...] | None = None,
    overlays: tuple[tuple[str, OverlayField, float], ...] = OVERLAY_CATALOG,
    binance_source: str | None = None,
    regime_skip_reason: str | None = None,
    regime_source_asset: str = REGIME_SOURCE_ASSET,
    now: datetime | None = None,
    data_notes: list[str] | None = None,
) -> OnChainRegimeReport:
    generated = now or datetime.now(UTC)
    kraken = _score_symbols_only(kraken_histories)
    if not kraken:
        raise ValueError("no Kraken BTC/ETH/SOL daily histories provided")
    primary_first, primary_source = primary_first_opened_at(kraken)
    btc = kraken_daily_candles(kraken, "BTC/USD")
    eth = kraken_daily_candles(kraken, "ETH/USD")
    sol = kraken_daily_candles(kraken, "SOL/USD")

    series = tuple(sorted(regime_series, key=lambda point: point.day))
    regime_status: Literal["ok", "skipped"] = "ok" if series else "skipped"
    skip_reason = regime_skip_reason if not series else None
    if not series and skip_reason is None:
        skip_reason = "no regime series supplied"

    base = (
        tuple(item for item in base_candidates if item.candidate_id not in CONTROL_IDS)
        if base_candidates is not None
        else tsmom_candidates(kraken, include_control=False)
    )

    raw_binance = binance_histories or {}
    sliced = {
        key: slice_ending_before(candles, before=primary_first)
        for key, candles in raw_binance.items()
    }
    remapped = _score_symbols_only(remap_binance_for_scoring(sliced))
    binance_meta = _binance_slice_meta(
        raw_binance=raw_binance,
        remapped=remapped,
        primary_first=primary_first,
        binance_source=binance_source,
    )

    kraken_catalog, kraken_cov, kraken_gated = _print_catalog(
        print_name="kraken",
        base=base,
        series=series,
        coverage_candles=_coverage_candles(kraken),
        overlays=overlays,
    )
    kraken_report = _score(
        kraken,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
        starting_equity=starting_equity,
        train_size=train_size,
        test_size=test_size,
        step_size=step_size,
        holdout_fraction=holdout_fraction,
        min_trades=min_trades,
        candidates=kraken_catalog,
        now=generated,
    )
    kraken_by_id = {row.candidate_id: row for row in kraken_report.candidates}

    binance_by_id: dict[str, CandidateHarderResult] = {}
    binance_cov: list[OverlayCoverage] = []
    binance_gated: dict[str, SearchCandidate] = {}
    if binance_meta.available:
        if binance_base_candidates is not None:
            binance_base = tuple(
                item for item in binance_base_candidates if item.candidate_id not in CONTROL_IDS
            )
        elif base_candidates is not None:
            binance_base = base
        else:
            binance_base = tsmom_candidates(remapped, include_control=False)
        binance_catalog, binance_cov, binance_gated = _print_catalog(
            print_name="binance",
            base=binance_base,
            series=series,
            coverage_candles=_coverage_candles(remapped),
            overlays=overlays,
        )
        binance_report = _score(
            remapped,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            starting_equity=starting_equity,
            train_size=train_size,
            test_size=test_size,
            step_size=step_size,
            holdout_fraction=holdout_fraction,
            min_trades=min_trades,
            candidates=binance_catalog,
            now=generated,
        )
        binance_by_id = {row.candidate_id: row for row in binance_report.candidates}
    else:
        for overlay_id, _field, _threshold in overlays:
            binance_cov.append(
                OverlayCoverage(
                    print="binance",
                    overlay_id=overlay_id,
                    usable=False,
                    reason=binance_meta.fail_closed_reason or "Binance print unavailable",
                )
            )

    ungated_rows = [
        _merge_row(
            candidate,
            kraken_by_id.get(candidate.candidate_id),
            binance_by_id.get(candidate.candidate_id),
        )
        for candidate in (*base, _control_candidate())
    ]
    gated_union: dict[str, SearchCandidate] = {**binance_gated, **kraken_gated}
    gated_rows = [
        _merge_row(candidate, kraken_by_id.get(ident), binance_by_id.get(ident))
        for ident, candidate in sorted(gated_union.items())
    ]
    base_passers = rank_dual_print_passers(
        [row for row in ungated_rows if row.candidate_id not in CONTROL_IDS]
    )
    gated_passers = rank_dual_print_passers(gated_rows)
    rows = [*ungated_rows, *gated_rows]
    for row in rows:
        row.can_promote = False
    rows_by_id = {row.candidate_id: row for row in rows}

    kraken_usable = {item.overlay_id: item.usable for item in kraken_cov}
    binance_usable = {item.overlay_id: item.usable for item in binance_cov}
    kraken_blocked = {item.overlay_id: item.blocked_days for item in kraken_cov}
    binance_blocked = {item.overlay_id: item.blocked_days for item in binance_cov}
    effects = [
        _effect_row(
            overlay=overlay,
            base=candidate,
            kraken_by_id=kraken_by_id,
            binance_by_id=binance_by_id,
            kraken_usable=kraken_usable.get(overlay[0], False),
            binance_usable=binance_usable.get(overlay[0], False),
            kraken_blocked=kraken_blocked.get(overlay[0]),
            binance_blocked=binance_blocked.get(overlay[0]),
            rows_by_id=rows_by_id,
        )
        for overlay in overlays
        for candidate in base
    ]
    overlay_passer_ids = sorted(
        (item.gated_id for item in effects if item.overlay_passer),
        key=lambda ident: (-_mean_ho_or_neg_inf(rows_by_id[ident]), ident),
    )
    # A gated dual-print passer that is not an overlay passer must not be
    # ranked as one; ranks on gated rows are informational only.
    for row in gated_passers:
        row.selected = row.candidate_id == (overlay_passer_ids[0] if overlay_passer_ids else "")
    mixed_ids = [item.gated_id for item in effects if item.verdict == "mixed_fail"]
    base_passer_ids = [row.candidate_id for row in base_passers]

    honesty = (
        ONCHAIN_REGIME_RULES
        + " "
        + OVERLAY_CATALOG_NOTE
        + f" This run: regime series {regime_status}"
        + (f" ({skip_reason})" if skip_reason else "")
        + f"; base names scored {len(base)}; gated names scored on Kraken "
        f"{len(kraken_gated)} / on Binance.US {len(binance_gated)}. "
        f"Base dual-print passers: {len(base_passer_ids)}. Overlay passers: "
        f"{len(overlay_passer_ids)}. mixed_fail: {len(mixed_ids)}."
    )
    if overlay_passer_ids:
        honesty += (
            f" Overlay top-1 is `{overlay_passer_ids[0]}` by {RANKING_KEY}. It does not "
            "flip or add a PAPER_PROMOTE_* pin; the runtime gate stays opt-in and can "
            "only withhold new longs."
        )
    else:
        honesty += (
            " No overlay passer. Leave every PAPER_PROMOTE_* false. The runtime gate "
            "stays off by default."
        )

    notes = list(data_notes or [])
    if series:
        notes.append(
            f"Coin Metrics community ({regime_source_asset}) regime series: ok — "
            f"{len(series)} committed daily points {series[0].day.isoformat()} → "
            f"{series[-1].day.isoformat()} ({ONCHAIN_REGIME_FEATURE_VERSION})."
        )
    else:
        notes.append(f"Coin Metrics community regime series: skipped — {skip_reason}.")
    notes.append(COINMETRICS_SKIPPED_METRICS_NOTE)
    if not btc or not eth:
        notes.append(
            "BTC and/or ETH daily series missing on Kraken. Combined gates cannot "
            "pass. Skip-not-invent; do not zero-fill."
        )
    if sol:
        notes.append(f"SOL/USD present ({len(sol)} bars); reported, not a gate.")
    else:
        notes.append("SOL/USD absent; reported as n/a, not invented.")

    return OnChainRegimeReport(
        generated_at=generated,
        base_catalog_ids=[item.candidate_id for item in base],
        overlay_catalog=[
            {"overlay_id": ident, "field": field_name, "threshold": threshold}
            for ident, field_name, threshold in overlays
        ],
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
        train_size=train_size,
        test_size=test_size,
        step_size=step_size,
        holdout_fraction=holdout_fraction,
        min_trades=min_trades,
        primary_first=primary_first.isoformat(),
        primary_first_source=primary_source,
        primary_last=btc[-1].opened_at.isoformat() if btc else None,
        primary_bars=len(btc) if btc else None,
        primary_bars_eth=len(eth) if eth else None,
        primary_bars_sol=len(sol) if sol else None,
        binance_slice=binance_meta,
        binance_source=binance_source,
        regime_source_asset=regime_source_asset,
        regime_status=regime_status,
        regime_skip_reason=skip_reason,
        regime_first_day=series[0].day.isoformat() if series else None,
        regime_last_day=series[-1].day.isoformat() if series else None,
        regime_points=len(series),
        coverage=[*kraken_cov, *binance_cov],
        rows=rows,
        effects=effects,
        base_dual_print_passer_ids=base_passer_ids,
        overlay_passer_ids=overlay_passer_ids,
        mixed_fail_ids=mixed_ids,
        any_base_dual_print_passer=bool(base_passer_ids),
        any_overlay_passer=bool(overlay_passer_ids),
        selected_gated_id=overlay_passer_ids[0] if overlay_passer_ids else None,
        keep_flag_false=True,
        can_promote=False,
        honesty=honesty,
        recommendation=_recommendation(
            overlay_passers=overlay_passer_ids,
            base_passers=base_passer_ids,
            mixed=mixed_ids,
            regime_status=regime_status,
            binance_meta=binance_meta,
        ),
        data_notes=notes,
    )


# --- markdown ------------------------------------------------------------------


def _fmt_delta(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:+.2%}"


def _slice_lines(meta: SliceMeta) -> list[str]:
    status = "available" if meta.available else "UNAVAILABLE / fail-closed"
    return [
        f"- Rule: `{meta.rule}`",
        f"- Venue label: `{meta.venue}`",
        f"- Status: **{status}**",
        f"- Bars: BTC {meta.bars_btc} / ETH {meta.bars_eth} / SOL {meta.bars_sol}",
        f"- Span: {meta.first or 'n/a'} → {meta.last or 'n/a'}",
        f"- Overlaps primary window: {'yes' if meta.overlaps_primary_window else 'no'}",
        f"- Fail-closed reason: {meta.fail_closed_reason or '—'}",
    ]


def _effect_table(report: OnChainRegimeReport, *, print_name: str) -> list[str]:
    lines = [
        (
            "| overlay | base | ungated mean HO | gated mean HO | Δ mean HO | "
            "ungated WF | gated WF | Δ WF | blocked bars | gated dual-print | verdict |"
        ),
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :---: | --- |",
    ]
    any_row = False
    for item in report.effects:
        scored = item.kraken_scored if print_name == "kraken" else item.binance_scored
        if not scored:
            continue
        any_row = True
        if print_name == "kraken":
            values = (
                item.kraken_ungated_mean_ho,
                item.kraken_gated_mean_ho,
                item.kraken_delta_mean_ho,
                item.kraken_ungated_wf,
                item.kraken_gated_wf,
                item.kraken_delta_wf,
                item.kraken_blocked_days,
            )
        else:
            values = (
                item.binance_ungated_mean_ho,
                item.binance_gated_mean_ho,
                item.binance_delta_mean_ho,
                item.binance_ungated_wf,
                item.binance_gated_wf,
                item.binance_delta_wf,
                item.binance_blocked_days,
            )
        lines.append(
            f"| `{item.overlay_id}` | `{item.base_id}` | {_pct(values[0])} | "
            f"{_pct(values[1])} | {_fmt_delta(values[2])} | {_pct(values[3])} | "
            f"{_pct(values[4])} | {_fmt_delta(values[5])} | "
            f"{values[6] if values[6] is not None else 'n/a'} | "
            f"{'yes' if item.gated_dual_print else 'no'} | {item.verdict} |"
        )
    if not any_row:
        lines.append("| — | — | n/a | n/a | n/a | n/a | n/a | n/a | n/a | no | skipped |")
    return lines


def render_onchain_regime_markdown(report: OnChainRegimeReport) -> str:
    regime_line = (
        f"ok — {report.regime_points} committed daily points "
        f"{report.regime_first_day} → {report.regime_last_day}"
        if report.regime_status == "ok"
        else f"skipped — {report.regime_skip_reason}"
    )
    lines: list[str] = [
        "# On-chain regime overlay (MVRV-Z / NUPL) on the frozen TSMOM catalog",
        "",
        f"Generated: {report.generated_at.isoformat()}",
        (
            f"Base catalog K={len(report.base_catalog_ids)} (+ control `{report.control_id}`, "
            f"informational); overlays={len(report.overlay_catalog)}; "
            f"ranking_key=`{report.ranking_key}`."
        ),
        (
            f"Costs: fee={report.fee_bps:g} bps + slippage={report.slippage_bps:g} bps "
            f"(gate C 2× fees). Walk-forward: train={report.train_size} "
            f"test={report.test_size} step={report.step_size}; "
            f"holdout_fraction={report.holdout_fraction:.0%}. Print kind: daily bars, "
            "fill at next-bar open."
        ),
        (
            f"`can_promote={str(report.can_promote).lower()}`; "
            f"`keep_flag_false={str(report.keep_flag_false).lower()}`; "
            f"`multi_venue_bar_preregistered={str(report.multi_venue_bar_preregistered).lower()}`; "
            f"`can_average_venues={str(report.can_average_venues).lower()}`."
        ),
        "",
        "## Data sources reached (status per series)",
        "",
        "| series | status |",
        "| --- | --- |",
        (
            f"| Kraken public Spot daily (primary 720) | ok — first {report.primary_first} "
            f"(`{report.primary_first_source}`), last {report.primary_last or 'n/a'}, bars "
            f"BTC={report.primary_bars or 'n/a'} / ETH={report.primary_bars_eth or 'n/a'} / "
            f"SOL={report.primary_bars_sol or 'n/a'} |"
        ),
        (
            f"| Binance.US older-720 (`{report.binance_slice.rule}`) | "
            f"{'ok' if report.binance_slice.available else 'skipped / fail-closed'} — "
            f"{report.binance_slice.venue}; BTC {report.binance_slice.bars_btc} / ETH "
            f"{report.binance_slice.bars_eth}; {report.binance_slice.first or 'n/a'} → "
            f"{report.binance_slice.last or 'n/a'}"
            + (
                f"; {report.binance_slice.fail_closed_reason}"
                if report.binance_slice.fail_closed_reason
                else ""
            )
            + " |"
        ),
        (
            f"| Coin Metrics community `{report.regime_source_id}` "
            f"({report.regime_source_asset}; {report.regime_feature_version}; window "
            f"{report.regime_window_days} d; min points {report.regime_min_points}; stale "
            f"limit {report.regime_max_stale_days} d) | {regime_line} |"
        ),
        "| Coin Metrics `CapRealUSD`, `SplyAct1d` | skipped — HTTP 403 on the community plan |",
        "",
        "## Honesty / pre-registered rules",
        "",
        report.honesty,
        "",
        "## Overlay bar (frozen before scoring)",
        "",
        report.rules,
        "",
        "## Overlay catalog (frozen)",
        "",
        report.overlay_catalog_note,
        "",
        "| overlay | field | rule |",
        "| --- | --- | --- |",
    ]
    for entry in report.overlay_catalog:
        lines.append(
            f"| `{entry['overlay_id']}` | `{entry['field']}` | BUY withheld when "
            f"{entry['field']} > {entry['threshold']} |"
        )
    lines.extend(
        [
            "",
            "## Regime coverage per print (skip-not-invent)",
            "",
            "| print | overlay | usable | bars | bars the overlay would block | reason |",
            "| --- | --- | :---: | ---: | ---: | --- |",
        ]
    )
    for cov in report.coverage:
        lines.append(
            f"| {cov.print} | `{cov.overlay_id}` | {'yes' if cov.usable else 'no'} | "
            f"{cov.bars} | {cov.blocked_days if cov.blocked_days is not None else 'n/a'} | "
            f"{cov.reason or '—'} |"
        )
    if report.data_notes:
        lines.extend(["", "## Data", ""])
        for note in report.data_notes:
            lines.append(f"- {note}")
    lines.extend(
        [
            "",
            "## Binance.US second print (required gate)",
            "",
            report.fee_note,
            "",
        ]
    )
    lines.extend(_slice_lines(report.binance_slice))
    lines.extend(
        [
            "",
            "## Overlay effect — Kraken primary 720",
            "",
            (
                "Ungated vs gated on the same print, same bars, same costs. Δ is "
                "gated − ungated. `blocked bars` counts bars on which the overlay rule "
                "was breached strictly before the bar (whether or not the base voter "
                "was long)."
            ),
            "",
        ]
    )
    lines.extend(_effect_table(report, print_name="kraken"))
    lines.extend(["", "## Overlay effect — Binance.US older-720", ""])
    lines.extend(_effect_table(report, print_name="binance"))
    lines.extend(
        [
            "",
            "## Verdict per overlay × base (frozen rule)",
            "",
            (
                f"`{report.overlay_verdict_rule}`. Deltas are mean holdout excess and "
                "walk-forward total on every scored print. An overlay that helps on one "
                "print or metric and "
                "hurts on the other is **mixed_fail** (FAIL), not an edge."
            ),
            "",
            (
                "| gated id | Kraken Δ mean HO | Kraken Δ WF | Binance Δ mean HO | "
                "Binance Δ WF | verdict | overlay passer |"
            ),
            "| --- | ---: | ---: | ---: | ---: | --- | :---: |",
        ]
    )
    for item in report.effects:
        lines.append(
            f"| `{item.gated_id}` | {_fmt_delta(item.kraken_delta_mean_ho)} | "
            f"{_fmt_delta(item.kraken_delta_wf)} | {_fmt_delta(item.binance_delta_mean_ho)} | "
            f"{_fmt_delta(item.binance_delta_wf)} | {item.verdict} | "
            f"{'yes' if item.overlay_passer else 'no'} |"
        )
    lines.extend(
        [
            "",
            "## Overlay passers (promotion ranking)",
            "",
            (
                f"Frozen passer rule: `{report.overlay_passer_rule}`. Empty table = no "
                "overlay passer (success). This CLI cannot add or flip a "
                "`PAPER_PROMOTE_*` pin."
            ),
            "",
            "| rank | gated id | Kraken mean HO | Binance mean HO | can flip flag |",
            "| ---: | --- | ---: | ---: | :---: |",
        ]
    )
    if not report.overlay_passer_ids:
        lines.append("| — | — | n/a | n/a | no |")
    else:
        by_id = {row.candidate_id: row for row in report.rows}
        for index, ident in enumerate(report.overlay_passer_ids, start=1):
            row = by_id[ident]
            lines.append(
                f"| {index} | `{ident}` | {_pct(row.kraken_mean_holdout_excess)} | "
                f"{_pct(row.binance_mean_holdout_excess)} | no |"
            )
    lines.extend(
        [
            "",
            "## Full catalog (informational)",
            "",
            (
                "| id | family | Kraken combined | Binance combined | dual-print | "
                "Kraken mean HO | Binance mean HO | Kraken BTC HO | Kraken ETH HO |"
            ),
            "| --- | --- | :---: | :---: | :---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in report.rows:
        lines.append(
            f"| `{row.candidate_id}` | {row.family} | {_verdict(row.kraken_combined)} | "
            f"{_verdict(row.binance_combined)} | "
            f"{'yes' if row.dual_print and row.candidate_id not in CONTROL_IDS else 'no'} | "
            f"{_pct(row.kraken_mean_holdout_excess)} | "
            f"{_pct(row.binance_mean_holdout_excess)} | "
            f"{_pct(row.kraken_btc_holdout)} | {_pct(row.kraken_eth_holdout)} |"
        )
    lines.extend(
        [
            "",
            "## Operator recommendation",
            "",
            report.recommendation,
            "",
            (
                f"`keep_flag_false={str(report.keep_flag_false).lower()}`; "
                f"`can_promote={str(report.can_promote).lower()}`. Do not fabricate PnL. "
                "Do not enable live. Do not average Binance.US with the Kraken primary "
                "window. Do not retune the overlay thresholds, the 1460-day window, or "
                "the stale limit after seeing this table."
            ),
            "",
        ]
    )
    return "\n".join(lines)
