"""Harder honesty gates on an expanded daily catalog.

Pre-registered before any window is scored (also written into every report).
An honest FAIL / empty promotee is the successful outcome if no name
survives.

A. **Magnitude balance**: BTC and ETH holdout excess > 0 **and**
   ``min(BTC, ETH) / max(BTC, ETH) >= 0.25``. Rejects an ETH-only
   magnitude even when both signs are positive.
B. **Rolling multi-window**: the most recent ``3 * 240`` Kraken daily
   bars are split into three contiguous 240-bar windows. Each window is
   scored with the same walk-forward hyperparameters as #96
   (train=180, test=60, step=60) and **no holdout** — the window itself
   is the robustness slice (one fold). A window passes iff BTC **and**
   ETH walk-forward mean total return > 0. Gate B requires at least
   **2 of 3** windows to pass. A short series that cannot form three
   windows is a FAIL, not a skip.
C. **Fee stress**: re-score at ``2×`` the baseline fee and slippage
   (defaults 10+5 → 20+10 bps). Must still clear the #96 balanced
   signs: BTC and ETH WF total > 0 **and** BTC and ETH holdout excess
   > 0 (plus mean holdout excess > 0 and min trades).

Yahoo / non-Kraken series stay A/B only and never enter ranking,
magnitude, multi-window, or fee-stress promotion averages.

#97 ranked the full catalog by walk-forward mean total return and
required that overall #1 also clear A+B+C. That blocked
``ema_12_26_adx20`` (combined PASS, rank 4). This run freezes a
different ranking key **before scoring**: among names that already
clear **combined** (#96 + A + B + C), take top-1 by Kraken BTC+ETH
**mean holdout excess**. Walk-forward rank of the full catalog is
informational and cannot promote a non-passer or block a passer.
Empty combined-passer set → no promotee (success). This module never
flips ``PAPER_PROMOTE_EMA_9_21`` or any new ``PAPER_PROMOTE_*`` default.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field

from traderstack.candles import Candle
from traderstack.research.daily_candidates import (
    BALANCED_HOLDOUT_GRID_NOTE,
    EXPANDED_HARDER_GATES_GRID_NOTE,
    default_balanced_holdout_candidates,
    default_daily_robustness_candidates,
    default_expanded_harder_gates_candidates,
)
from traderstack.research.daily_robustness import (
    KRAKEN_DAILY_CAP_NOTE,
    DailyRobustnessReport,
    _holdout_excess,
    is_yahoo_symbol,
    run_daily_robustness,
    series_for_asset,
)
from traderstack.research.evidence import (  # --- search evidence (#135) ---
    EVIDENCE_RULES,
    PRINT_KIND_VENUE,
    CandidateEvidence,
    CatalogEvidence,
    evaluate_catalog_evidence,
    render_evidence_lines,
)
from traderstack.research.miles_candidates import SearchCandidate
from traderstack.research.miles_search import (
    CandidateSearchResult,
    walkforward_candidate_on_window,
)

# --- harder honesty gates (pre-registered; do not retune after scoring) ---
MAGNITUDE_RATIO_MIN = 0.25
MULTIWINDOW_COUNT = 3
MULTIWINDOW_BARS = 240
MULTIWINDOW_MIN_PASSES = 2
FEE_STRESS_MULTIPLIER = 2.0
RANKING_KEY = "mean_holdout_excess_among_combined_passers"
SELECTION_RULE = "pre_registered_top1_mean_holdout_excess_among_combined_passers"
# #96 names that cleared balanced-holdout but were not #97 WF top-1.
# Re-scored under A–C for honesty. Under the expanded ranking key a
# combined-passer may be selected even if it is not WF-total #1.
PR96_ELIGIBLE_RECHECK = (
    "ema_12_26",
    "ema_12_26_adx25",
    "ema_12_26_adx20",
    "ema_9_21_adx25",
    "ema_9_21_ma200_riskoff",
    "ema_9_21_adx20",
)
HARDER_GATES_NOTE = (
    "Pre-registered harder gates (frozen before the Kraken window is "
    "scored). A — magnitude: both BTC and ETH holdout excess > 0 and "
    f"min/max holdout ratio >= {MAGNITUDE_RATIO_MIN:.2f} (reject ETH-only "
    "magnitude). B — multi-window: three contiguous "
    f"{MULTIWINDOW_BARS}-bar Kraken daily slices; each uses #96 "
    "walk-forward (train=180, test=60, step=60) with no in-window "
    "holdout; BTC and ETH WF total > 0 in at least "
    f"{MULTIWINDOW_MIN_PASSES} of {MULTIWINDOW_COUNT} windows. C — fee "
    f"stress: {FEE_STRESS_MULTIPLIER:g}× fee and slippage (defaults "
    "10+5 → 20+10 bps) must still clear #96 balanced signs. Combined "
    "requires #96 balanced-holdout and A and B and C. Ranking key "
    f"(frozen before scoring): {RANKING_KEY} — Kraken BTC+ETH mean "
    "holdout excess among combined-passers; full-catalog walk-forward "
    "rank is informational. Yahoo is A/B only. PAPER_PROMOTE_EMA_9_21 "
    "stays false."
)


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def holdout_magnitude_ratio(btc_holdout: float | None, eth_holdout: float | None) -> float | None:
    """min/max of two strictly positive holdout excesses; else None."""
    if btc_holdout is None or eth_holdout is None:
        return None
    if btc_holdout <= 0 or eth_holdout <= 0:
        return None
    larger = max(btc_holdout, eth_holdout)
    if larger <= 0:
        return None
    return min(btc_holdout, eth_holdout) / larger


def evaluate_magnitude_gate(
    btc_holdout: float | None,
    eth_holdout: float | None,
    *,
    min_ratio: float = MAGNITUDE_RATIO_MIN,
) -> tuple[bool, float | None, list[str]]:
    """Gate A. Pre-registered; do not relax the ratio after seeing the print."""
    reasons: list[str] = []
    ratio = holdout_magnitude_ratio(btc_holdout, eth_holdout)
    if btc_holdout is None:
        reasons.append("btc_holdout_missing")
    elif btc_holdout <= 0:
        reasons.append("btc_holdout_excess_not_positive")
    if eth_holdout is None:
        reasons.append("eth_holdout_missing")
    elif eth_holdout <= 0:
        reasons.append("eth_holdout_excess_not_positive")
    if ratio is None:
        if not reasons:
            reasons.append("holdout_magnitude_ratio_undefined")
    elif ratio < min_ratio:
        reasons.append("holdout_magnitude_ratio_below_minimum")
    return (not reasons, ratio, reasons)


def kraken_daily_candles(
    histories: dict[str, tuple[Candle, ...]],
    asset: str,
    *,
    interval: str = "1d",
) -> tuple[Candle, ...] | None:
    wanted = asset.upper()
    for candles in histories.values():
        if (
            candles
            and candles[0].interval == interval
            and candles[0].symbol.upper() == wanted
            and not is_yahoo_symbol(candles[0].symbol)
        ):
            return candles
    return None


def split_contiguous_windows(
    candles: tuple[Candle, ...],
    *,
    window_count: int = MULTIWINDOW_COUNT,
    window_bars: int = MULTIWINDOW_BARS,
) -> list[tuple[Candle, ...]] | None:
    """Most-recent ``window_count * window_bars`` bars, split contiguously.

    Returns None (gate B fail-closed) when the series is too short. Extra
    older bars are dropped so windows stay the latest aligned tail.
    """
    needed = window_count * window_bars
    if window_count < 3 or window_bars <= 0 or len(candles) < needed:
        return None
    tail = candles[-needed:]
    return [tail[index * window_bars : (index + 1) * window_bars] for index in range(window_count)]


class WindowScore(BaseModel):
    index: int
    label: str
    first: str
    last: str
    bars: int
    btc_wf_total: float | None = None
    eth_wf_total: float | None = None
    passed: bool = False
    reasons: list[str] = Field(default_factory=list)


def score_multiwindow(
    candidate: SearchCandidate,
    histories: dict[str, tuple[Candle, ...]],
    *,
    fee_bps: float,
    slippage_bps: float,
    starting_equity: float,
    train_size: int,
    test_size: int,
    step_size: int,
    window_count: int = MULTIWINDOW_COUNT,
    window_bars: int = MULTIWINDOW_BARS,
    min_passes: int = MULTIWINDOW_MIN_PASSES,
    interval: str = "1d",
) -> tuple[bool, list[WindowScore], list[str]]:
    """Gate B. Missing windows or a short series fail closed."""
    labels = ("W1 oldest", "W2 middle", "W3 newest")
    btc = kraken_daily_candles(histories, "BTC/USD", interval=interval)
    eth = kraken_daily_candles(histories, "ETH/USD", interval=interval)
    reasons: list[str] = []
    if btc is None:
        reasons.append("btc_kraken_daily_missing")
    if eth is None:
        reasons.append("eth_kraken_daily_missing")
    btc_windows = split_contiguous_windows(
        btc or (), window_count=window_count, window_bars=window_bars
    )
    eth_windows = split_contiguous_windows(
        eth or (), window_count=window_count, window_bars=window_bars
    )
    if btc_windows is None:
        reasons.append("btc_insufficient_bars_for_multiwindow")
    if eth_windows is None:
        reasons.append("eth_insufficient_bars_for_multiwindow")
    if reasons:
        return False, [], reasons

    scores: list[WindowScore] = []
    assert btc_windows is not None and eth_windows is not None
    for index, (btc_slice, eth_slice) in enumerate(zip(btc_windows, eth_windows, strict=True)):
        window_reasons: list[str] = []
        btc_wf = _window_wf_total(
            candidate,
            btc_slice,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            starting_equity=starting_equity,
            train_size=train_size,
            test_size=test_size,
            step_size=step_size,
        )
        eth_wf = _window_wf_total(
            candidate,
            eth_slice,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            starting_equity=starting_equity,
            train_size=train_size,
            test_size=test_size,
            step_size=step_size,
        )
        if btc_wf is None:
            window_reasons.append("btc_walkforward_missing")
        elif btc_wf <= 0:
            window_reasons.append("btc_walkforward_total_return_not_positive")
        if eth_wf is None:
            window_reasons.append("eth_walkforward_missing")
        elif eth_wf <= 0:
            window_reasons.append("eth_walkforward_total_return_not_positive")
        first = btc_slice[0].opened_at.isoformat()
        last = btc_slice[-1].opened_at.isoformat()
        scores.append(
            WindowScore(
                index=index + 1,
                label=labels[index] if index < len(labels) else f"W{index + 1}",
                first=first,
                last=last,
                bars=len(btc_slice),
                btc_wf_total=btc_wf,
                eth_wf_total=eth_wf,
                passed=not window_reasons,
                reasons=window_reasons,
            )
        )
    passed_count = sum(1 for row in scores if row.passed)
    if passed_count < min_passes:
        reasons.append("multiwindow_fewer_than_min_passes")
    return (not reasons, scores, reasons)


def _window_wf_total(
    candidate: SearchCandidate,
    candles: tuple[Candle, ...],
    *,
    fee_bps: float,
    slippage_bps: float,
    starting_equity: float,
    train_size: int,
    test_size: int,
    step_size: int,
) -> float | None:
    try:
        report = walkforward_candidate_on_window(
            candidate,
            candles,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            starting_equity=starting_equity,
            train_size=train_size,
            test_size=test_size,
            step_size=step_size,
        )
    except ValueError:
        return None
    return report.mean_total_return


def evaluate_fee_stress_gate(
    row: CandidateSearchResult, *, interval: str = "1d"
) -> tuple[bool, list[str]]:
    """Gate C: #96 balanced signs at the stressed fee print."""
    reasons: list[str] = []
    if row.mean_wf_total_return is None:
        reasons.append("walkforward_missing")
    elif row.mean_wf_total_return <= 0:
        reasons.append("walkforward_total_return_not_positive")
    if row.mean_holdout_excess_return is None:
        reasons.append("holdout_missing")
    elif row.mean_holdout_excess_return <= 0:
        reasons.append("holdout_excess_return_not_positive")
    btc = series_for_asset(row.per_series, "BTC/USD", interval=interval)
    eth = series_for_asset(row.per_series, "ETH/USD", interval=interval)
    btc_wf = btc.walkforward_mean_total_return if btc is not None else None
    eth_wf = eth.walkforward_mean_total_return if eth is not None else None
    if btc_wf is None:
        reasons.append("btc_walkforward_missing")
    elif btc_wf <= 0:
        reasons.append("btc_walkforward_total_return_not_positive")
    if eth_wf is None:
        reasons.append("eth_walkforward_missing")
    elif eth_wf <= 0:
        reasons.append("eth_walkforward_total_return_not_positive")
    btc_ho = _holdout_excess(btc)
    eth_ho = _holdout_excess(eth)
    if btc_ho is None:
        reasons.append("btc_holdout_missing")
    elif btc_ho <= 0:
        reasons.append("btc_holdout_excess_not_positive")
    if eth_ho is None:
        reasons.append("eth_holdout_missing")
    elif eth_ho <= 0:
        reasons.append("eth_holdout_excess_not_positive")
    return (not reasons, reasons)


class CandidateHarderResult(BaseModel):
    candidate_id: str
    family: str
    label: str
    rank: int | None = None
    wf_rank: int | None = None
    combined_rank: int | None = None
    selected: bool = False
    eligible_96: bool = False
    pr96_recheck: bool = False
    baseline_wf_total: float | None = None
    mean_holdout_excess: float | None = None
    baseline_btc_wf: float | None = None
    baseline_eth_wf: float | None = None
    baseline_btc_holdout: float | None = None
    baseline_eth_holdout: float | None = None
    # --- cross-sectional momentum (SOL reported; not a gate) ---
    baseline_sol_wf: float | None = None
    baseline_sol_holdout: float | None = None
    holdout_magnitude_ratio: float | None = None
    gate_a_pass: bool = False
    gate_a_reasons: list[str] = Field(default_factory=list)
    windows: list[WindowScore] = Field(default_factory=list)
    windows_passed: int = 0
    gate_b_pass: bool = False
    gate_b_reasons: list[str] = Field(default_factory=list)
    stress_wf_total: float | None = None
    stress_btc_wf: float | None = None
    stress_eth_wf: float | None = None
    stress_btc_holdout: float | None = None
    stress_eth_holdout: float | None = None
    gate_c_pass: bool = False
    gate_c_reasons: list[str] = Field(default_factory=list)
    combined: bool = False
    promoted: bool = False
    # --- search evidence (#135) ---
    # DSR / PBO / bootstrap evidence for this candidate (additional gate;
    # can only withhold a promotion, never create one).
    evidence: CandidateEvidence | None = None
    evidence_pass: bool = False


class HarderGatesReport(BaseModel):
    generated_at: datetime
    symbols: list[str]
    intervals: list[str]
    fee_bps: float
    slippage_bps: float
    fee_stress_fee_bps: float
    fee_stress_slippage_bps: float
    cost_note: str
    starting_equity: float
    train_size: int
    test_size: int
    step_size: int
    holdout_fraction: float
    min_trades: int
    selection_rule: str
    magnitude_ratio_min: float
    multiwindow_count: int
    multiwindow_bars: int
    multiwindow_min_passes: int
    fee_stress_multiplier: float
    ranking_key: str
    catalog_name: str
    catalog_note: str
    kraken_cap_note: str
    gates_note: str
    candidates: list[CandidateHarderResult]
    selected_candidate_id: str | None = None
    wf_top1_candidate_id: str | None = None
    combined_passer_ids: list[str] = Field(default_factory=list)
    promoted_candidate_ids: list[str] = Field(default_factory=list)
    recommended_promote_flag: str | None = None
    any_promoted: bool = False
    ema_9_21_gate_a: bool = False
    ema_9_21_gate_b: bool = False
    ema_9_21_gate_c: bool = False
    ema_9_21_combined: bool = False
    ema_9_21_clears_balanced_holdout: bool = False
    honesty: str
    data_notes: list[str] = Field(default_factory=list)
    yahoo_notes: list[str] = Field(default_factory=list)
    # --- search evidence (#135) ---
    evidence: CatalogEvidence | None = None
    print_kind: str = PRINT_KIND_VENUE
    evidence_passer_ids: list[str] = Field(default_factory=list)
    evidence_rules: str = EVIDENCE_RULES


def paper_promote_flag_name(candidate_id: str) -> str:
    """Documented paper-only Settings name for a combined-passer id."""
    return "PAPER_PROMOTE_" + candidate_id.upper()


def rank_combined_passers(
    rows: list[CandidateHarderResult],
) -> list[CandidateHarderResult]:
    """Frozen ranking key: mean holdout excess among combined-passers.

    Tie-break is candidate_id ascending so the order is deterministic and
    does not depend on catalog iteration after seeing PnL.
    """
    passers = [row for row in rows if row.combined]
    passers.sort(
        key=lambda row: (
            -(row.mean_holdout_excess if row.mean_holdout_excess is not None else float("-inf")),
            row.candidate_id,
        )
    )
    for index, row in enumerate(passers, start=1):
        row.combined_rank = index
        row.rank = index
    return passers


def apply_combined_promotion(
    rows: list[CandidateHarderResult],
) -> CandidateHarderResult | None:
    """Select top-1 combined-passer. A non-passer is never promoted."""
    for row in rows:
        row.selected = False
        row.promoted = False
    passers = rank_combined_passers(rows)
    if not passers:
        return None
    selected = passers[0]
    selected.selected = True
    selected.promoted = True
    return selected


def _catalog_for(
    histories: dict[str, tuple[Candle, ...]],
    *,
    candidates: tuple[SearchCandidate, ...] | None,
    catalog_name: str,
) -> tuple[list[SearchCandidate], str, str]:
    if candidates is not None:
        return list(candidates), "custom", "Caller-supplied catalog."
    overlay = kraken_daily_candles(histories, "BTC/USD")
    if catalog_name == "legacy":
        return (
            list(default_daily_robustness_candidates()),
            "legacy",
            "Frozen #95 daily-robustness catalog (K=8).",
        )
    if catalog_name == "balanced":
        return (
            list(default_balanced_holdout_candidates(btc_overlay=overlay)),
            "balanced",
            BALANCED_HOLDOUT_GRID_NOTE,
        )
    return (
        list(default_expanded_harder_gates_candidates(btc_overlay=overlay)),
        "expanded",
        EXPANDED_HARDER_GATES_GRID_NOTE,
    )


def _row_by_id(report: DailyRobustnessReport, candidate_id: str) -> CandidateSearchResult | None:
    return next((row for row in report.candidates if row.candidate_id == candidate_id), None)


def run_harder_gates(
    histories: dict[str, tuple[Candle, ...]],
    *,
    fee_bps: float,
    slippage_bps: float = 5.0,
    starting_equity: float = 10_000.0,
    train_size: int = 180,
    test_size: int = 60,
    step_size: int = 60,
    holdout_fraction: float = 0.20,
    min_trades: int = 3,
    candidates: tuple[SearchCandidate, ...] | None = None,
    catalog_name: str = "expanded",
    now: datetime | None = None,
    data_notes: list[str] | None = None,
    promotion_interval: str = "1d",
) -> HarderGatesReport:
    if not histories:
        raise ValueError("no candle histories provided")
    catalog, resolved_catalog, catalog_note = _catalog_for(
        histories, candidates=candidates, catalog_name=catalog_name
    )
    baseline = run_daily_robustness(
        histories,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
        starting_equity=starting_equity,
        train_size=train_size,
        test_size=test_size,
        step_size=step_size,
        holdout_fraction=holdout_fraction,
        min_trades=min_trades,
        candidates=tuple(catalog),
        catalog_name=resolved_catalog,
        require_balanced_holdout=True,
        now=now,
        data_notes=data_notes,
        promotion_interval=promotion_interval,
    )
    stress_fee = fee_bps * FEE_STRESS_MULTIPLIER
    stress_slip = slippage_bps * FEE_STRESS_MULTIPLIER
    stressed = run_daily_robustness(
        histories,
        fee_bps=stress_fee,
        slippage_bps=stress_slip,
        starting_equity=starting_equity,
        train_size=train_size,
        test_size=test_size,
        step_size=step_size,
        holdout_fraction=holdout_fraction,
        min_trades=min_trades,
        candidates=tuple(catalog),
        catalog_name=resolved_catalog,
        require_balanced_holdout=True,
        now=now,
        data_notes=data_notes,
        promotion_interval=promotion_interval,
    )
    by_id = {item.candidate_id: item for item in catalog}
    rows: list[CandidateHarderResult] = []
    for base in baseline.candidates:
        candidate = by_id[base.candidate_id]
        btc = series_for_asset(base.per_series, "BTC/USD", interval=promotion_interval)
        eth = series_for_asset(base.per_series, "ETH/USD", interval=promotion_interval)
        # --- cross-sectional momentum (SOL reported; not a gate) ---
        sol = series_for_asset(base.per_series, "SOL/USD", interval=promotion_interval)
        btc_ho = _holdout_excess(btc)
        eth_ho = _holdout_excess(eth)
        sol_ho = _holdout_excess(sol)
        gate_a, ratio, reasons_a = evaluate_magnitude_gate(btc_ho, eth_ho)
        gate_b, windows, reasons_b = score_multiwindow(
            candidate,
            histories,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            starting_equity=starting_equity,
            train_size=train_size,
            test_size=test_size,
            step_size=step_size,
            interval=promotion_interval,
        )
        stress_row = _row_by_id(stressed, base.candidate_id)
        if stress_row is None:
            gate_c, reasons_c = False, ["fee_stress_row_missing"]
            stress_btc = stress_eth = None
            stress_btc_ho = stress_eth_ho = None
            stress_wf = None
        else:
            gate_c, reasons_c = evaluate_fee_stress_gate(stress_row, interval=promotion_interval)
            stress_btc_s = series_for_asset(
                stress_row.per_series, "BTC/USD", interval=promotion_interval
            )
            stress_eth_s = series_for_asset(
                stress_row.per_series, "ETH/USD", interval=promotion_interval
            )
            stress_btc = (
                stress_btc_s.walkforward_mean_total_return if stress_btc_s is not None else None
            )
            stress_eth = (
                stress_eth_s.walkforward_mean_total_return if stress_eth_s is not None else None
            )
            stress_btc_ho = _holdout_excess(stress_btc_s)
            stress_eth_ho = _holdout_excess(stress_eth_s)
            stress_wf = stress_row.mean_wf_total_return
        combined = bool(base.eligible and gate_a and gate_b and gate_c)
        rows.append(
            CandidateHarderResult(
                candidate_id=base.candidate_id,
                family=base.family,
                label=base.label,
                rank=None,
                wf_rank=base.rank,
                selected=False,
                eligible_96=base.eligible,
                pr96_recheck=base.candidate_id in PR96_ELIGIBLE_RECHECK,
                baseline_wf_total=base.mean_wf_total_return,
                mean_holdout_excess=base.mean_holdout_excess_return,
                baseline_btc_wf=(btc.walkforward_mean_total_return if btc is not None else None),
                baseline_eth_wf=(eth.walkforward_mean_total_return if eth is not None else None),
                baseline_btc_holdout=btc_ho,
                baseline_eth_holdout=eth_ho,
                # --- cross-sectional momentum (SOL reported; not a gate) ---
                baseline_sol_wf=(sol.walkforward_mean_total_return if sol is not None else None),
                baseline_sol_holdout=sol_ho,
                holdout_magnitude_ratio=ratio,
                gate_a_pass=gate_a,
                gate_a_reasons=reasons_a,
                windows=windows,
                windows_passed=sum(1 for window in windows if window.passed),
                gate_b_pass=gate_b,
                gate_b_reasons=reasons_b,
                stress_wf_total=stress_wf,
                stress_btc_wf=stress_btc,
                stress_eth_wf=stress_eth,
                stress_btc_holdout=stress_btc_ho,
                stress_eth_holdout=stress_eth_ho,
                gate_c_pass=gate_c,
                gate_c_reasons=reasons_c,
                combined=combined,
            )
        )

    selected = apply_combined_promotion(rows)
    # --- search evidence (#135) ---
    # Additional gate applied after the frozen ranking/selection: a raw
    # combined top-1 keeps selected=True / combined=True (the raw pass is
    # still shown) but is not promoted when its evidence fails. Evidence
    # never promotes a non-passer and never reorders the ranking.
    evidence = evaluate_catalog_evidence(baseline, interval=promotion_interval)
    evidence_by_id = {item.candidate_id: item for item in evidence.candidates}
    for row in rows:
        row.evidence = evidence_by_id.get(row.candidate_id)
        row.evidence_pass = bool(row.evidence is not None and row.evidence.evidence_pass)
    evidence_withheld: list[str] = []
    if selected is not None and not selected.evidence_pass:
        selected.promoted = False
        evidence_withheld = (
            list(selected.evidence.reasons) if selected.evidence else ["evidence_missing"]
        )
    evidence_passer_ids = [
        row.candidate_id
        for row in sorted(
            (item for item in rows if item.combined and item.evidence_pass),
            key=lambda item: (
                item.combined_rank if item.combined_rank is not None else 10**9,
                item.candidate_id,
            ),
        )
    ]
    wf_top1 = next((row for row in rows if row.wf_rank == 1), None)
    promoted_ids = [row.candidate_id for row in rows if row.promoted]
    combined_ids = [row.candidate_id for row in rows if row.combined]
    recommend_flag = paper_promote_flag_name(promoted_ids[0]) if promoted_ids else None
    ema = next((row for row in rows if row.candidate_id == "ema_9_21"), None)
    ema_a = ema.gate_a_pass if ema is not None else False
    ema_b = ema.gate_b_pass if ema is not None else False
    ema_c = ema.gate_c_pass if ema is not None else False
    ema_combined = ema.combined if ema is not None else False
    ema_96 = ema.eligible_96 if ema is not None else False

    honesty = (
        "No candidate is rewritten to look profitable. Walk-forward folds "
        "never see the holdout tail. Combined-passers are names that clear "
        "#96 balanced-holdout and A and B and C. Ranking key (frozen before "
        f"scoring): {RANKING_KEY} — top-1 of {len(catalog)} catalog members "
        "that also combined-pass, by Kraken BTC+ETH mean holdout excess "
        "(tie-break: candidate_id). Full-catalog walk-forward rank is "
        "informational and cannot promote a non-passer or block a passer. "
        "Yahoo Finance daily is a longer non-Kraken A/B and cannot enter "
        "ranking, magnitude, multi-window, or fee-stress averages. "
        + HARDER_GATES_NOTE
        + " An honest FAIL / empty promotee is a successful research "
        "outcome — it is not rewritten as a soft PASS. This run does not "
        "flip PAPER_PROMOTE_EMA_9_21 (default false) and does not enable live."
    )
    if ema is not None:
        honesty += (
            f" ema_9_21 #96 balanced-holdout: {'PASS' if ema_96 else 'FAIL'}. "
            f"Gate A magnitude: {'PASS' if ema_a else 'FAIL'}. "
            f"Gate B multi-window: {'PASS' if ema_b else 'FAIL'}. "
            f"Gate C fee stress: {'PASS' if ema_c else 'FAIL'}. "
            f"Combined: {'PASS' if ema_combined else 'FAIL'}."
        )
    if selected is not None and evidence_withheld:
        # --- search evidence (#135) ---
        honesty += (
            f" Combined-passer top-1 {selected.candidate_id} cleared #96+A+B+C "
            "but the evidence layer withheld promotion (DSR >= 0.95, PBO <= 0.50, "
            "expectancy CI > 0 on BTC and ETH; additional gates, never "
            f"replacements): {', '.join(evidence_withheld)}. Paper promotion "
            "must stay off."
        )
    elif selected is None or not selected.promoted:
        honesty += (
            " No candidate cleared the combined harder-gates bar; paper promotion must stay off."
        )
    elif selected.candidate_id == "ema_9_21":
        honesty += (
            " ema_9_21 cleared A, B, and C and was top-1 among combined-passers. "
            "That still does not flip PAPER_PROMOTE_EMA_9_21."
        )
    else:
        honesty += (
            f" Combined-passer top-1 was {selected.candidate_id} "
            f"({paper_promote_flag_name(selected.candidate_id)} default false). "
            "Document the paper-only id; do not enable live."
        )

    yahoo_notes: list[str] = []
    if ema is not None:
        base_ema = _row_by_id(baseline, "ema_9_21")
        if base_ema is not None:
            for series in base_ema.per_series:
                if not is_yahoo_symbol(series.asset):
                    continue
                ho = f"{series.holdout.excess_return:+.2%}" if series.holdout is not None else "n/a"
                wf = (
                    f"{series.walkforward_mean_total_return:+.2%}"
                    if series.walkforward_mean_total_return is not None
                    else "n/a"
                )
                yahoo_notes.append(
                    f"{series.asset} {series.candle_count} bars: WF total {wf}, "
                    f"holdout excess {ho} (non-Kraken A/B; not promotion)"
                )

    symbols = sorted({candles[0].symbol for candles in histories.values() if candles})
    intervals = sorted({candles[0].interval for candles in histories.values() if candles})
    return HarderGatesReport(
        generated_at=now or datetime.now(UTC),
        symbols=symbols,
        intervals=intervals,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
        fee_stress_fee_bps=stress_fee,
        fee_stress_slippage_bps=stress_slip,
        cost_note=(
            "fee_bps is max(PRETRADE_FEE_BPS, PAPER_FEE_BPS); "
            "slippage_bps is PRETRADE_SLIPPAGE_BPS. Every fill pays both. "
            f"Gate C re-scores at {FEE_STRESS_MULTIPLIER:g}× both legs."
        ),
        starting_equity=starting_equity,
        train_size=train_size,
        test_size=test_size,
        step_size=step_size,
        holdout_fraction=holdout_fraction,
        min_trades=min_trades,
        selection_rule=SELECTION_RULE,
        ranking_key=RANKING_KEY,
        magnitude_ratio_min=MAGNITUDE_RATIO_MIN,
        multiwindow_count=MULTIWINDOW_COUNT,
        multiwindow_bars=MULTIWINDOW_BARS,
        multiwindow_min_passes=MULTIWINDOW_MIN_PASSES,
        fee_stress_multiplier=FEE_STRESS_MULTIPLIER,
        catalog_name=resolved_catalog,
        catalog_note=catalog_note,
        kraken_cap_note=KRAKEN_DAILY_CAP_NOTE,
        gates_note=HARDER_GATES_NOTE,
        candidates=rows,
        selected_candidate_id=selected.candidate_id if selected is not None else None,
        wf_top1_candidate_id=wf_top1.candidate_id if wf_top1 is not None else None,
        combined_passer_ids=combined_ids,
        promoted_candidate_ids=promoted_ids,
        recommended_promote_flag=recommend_flag,
        any_promoted=bool(promoted_ids),
        ema_9_21_gate_a=ema_a,
        ema_9_21_gate_b=ema_b,
        ema_9_21_gate_c=ema_c,
        ema_9_21_combined=ema_combined,
        ema_9_21_clears_balanced_holdout=ema_96,
        honesty=honesty,
        data_notes=list(data_notes or []),
        yahoo_notes=yahoo_notes,
        # --- search evidence (#135) ---
        evidence=evidence,
        print_kind=evidence.print_kind,
        evidence_passer_ids=evidence_passer_ids,
        evidence_rules=EVIDENCE_RULES,
    )


def _pct(value: float | None) -> str:
    return f"{value:+.2%}" if value is not None else "n/a"


def _ratio(value: float | None) -> str:
    return f"{value:.3f}" if value is not None else "n/a"


def _verdict(passed: bool) -> str:
    return "PASS" if passed else "FAIL"


def render_harder_gates_markdown(report: HarderGatesReport) -> str:
    ema = next((row for row in report.candidates if row.candidate_id == "ema_9_21"), None)
    lines: list[str] = [
        "# Expanded catalog harder-gates report",
        "",
        f"Generated: {report.generated_at.isoformat()}",
        f"Symbols: {', '.join(report.symbols)}",
        f"Intervals: {', '.join(report.intervals)} (promotion uses Kraken 1d BTC+ETH only)",
        (
            f"Baseline costs: fee={report.fee_bps:g} bps + slippage="
            f"{report.slippage_bps:g} bps. Gate C costs: fee="
            f"{report.fee_stress_fee_bps:g} bps + slippage="
            f"{report.fee_stress_slippage_bps:g} bps ({report.cost_note})"
        ),
        (
            f"Walk-forward: train={report.train_size} test={report.test_size} "
            f"step={report.step_size}; holdout_fraction={report.holdout_fraction:.0%} "
            f"on the full series (gate C / #96). Gate B windows use the same "
            f"train/test/step and no holdout."
        ),
        (
            f"Selection: {report.selection_rule} "
            f"(ranking_key={report.ranking_key}; catalog={report.catalog_name})"
        ),
        "",
        "## Pre-registered gates (frozen before scoring)",
        "",
        report.gates_note,
        "",
        "| gate | rule |",
        "| --- | --- |",
        (
            f"| A Magnitude | BTC and ETH holdout excess > 0 **and** "
            f"min/max ratio ≥ {report.magnitude_ratio_min:.2f} |"
        ),
        (
            f"| B Multi-window | {report.multiwindow_count} contiguous "
            f"{report.multiwindow_bars}-bar Kraken daily slices; BTC **and** "
            f"ETH WF total > 0 in ≥ {report.multiwindow_min_passes} of "
            f"{report.multiwindow_count} |"
        ),
        (
            f"| C Fee stress | {report.fee_stress_multiplier:g}× fees "
            f"({report.fee_stress_fee_bps:g}+{report.fee_stress_slippage_bps:g} "
            "bps) still clear #96 balanced signs |"
        ),
        (
            "| Combined | #96 balanced-holdout **and** A **and** B **and** C. "
            f"Top-1 among those passers by `{report.ranking_key}`. "
            "A non-passer is never promoted. |"
        ),
        "",
        "## Honesty",
        "",
        report.honesty,
        "",
        "## Kraken public OHLC cap",
        "",
        report.kraken_cap_note,
        "",
        "## Pre-registered catalog",
        "",
        report.catalog_note,
        "",
    ]
    if report.data_notes:
        lines.extend(["## Data", ""])
        for note in report.data_notes:
            lines.append(f"- {note}")
        lines.append("")

    lines.extend(
        [
            "## `ema_9_21` PASS / FAIL",
            "",
            "| gate | verdict | evidence |",
            "| --- | --- | --- |",
        ]
    )
    if ema is None:
        lines.append("| A Magnitude | FAIL | `ema_9_21` not in catalog |")
        lines.append("| B Multi-window | FAIL | `ema_9_21` not in catalog |")
        lines.append("| C Fee stress | FAIL | `ema_9_21` not in catalog |")
        lines.append("| Combined | FAIL | `ema_9_21` not in catalog |")
    else:
        a_ev = (
            f"BTC holdout {_pct(ema.baseline_btc_holdout)}, ETH holdout "
            f"{_pct(ema.baseline_eth_holdout)}, ratio {_ratio(ema.holdout_magnitude_ratio)} "
            f"(min {report.magnitude_ratio_min:.2f})"
        )
        if ema.gate_a_reasons:
            a_ev += "; blocked by: " + ", ".join(ema.gate_a_reasons)
        b_ev = f"{ema.windows_passed}/{report.multiwindow_count} windows passed"
        if ema.windows:
            bits = [
                f"{window.label} BTC {_pct(window.btc_wf_total)} / ETH {_pct(window.eth_wf_total)}"
                for window in ema.windows
            ]
            b_ev += " — " + "; ".join(bits)
        if ema.gate_b_reasons:
            b_ev += "; blocked by: " + ", ".join(ema.gate_b_reasons)
        c_ev = (
            f"2× fees BTC WF {_pct(ema.stress_btc_wf)} / ETH WF "
            f"{_pct(ema.stress_eth_wf)}; BTC holdout {_pct(ema.stress_btc_holdout)} / "
            f"ETH holdout {_pct(ema.stress_eth_holdout)}"
        )
        if ema.gate_c_reasons:
            c_ev += "; blocked by: " + ", ".join(ema.gate_c_reasons)
        comb_ev = (
            f"#96 balanced-holdout {_verdict(ema.eligible_96)}; "
            f"A {_verdict(ema.gate_a_pass)}; B {_verdict(ema.gate_b_pass)}; "
            f"C {_verdict(ema.gate_c_pass)}"
        )
        lines.append(f"| A Magnitude | **{_verdict(ema.gate_a_pass)}** | {a_ev} |")
        lines.append(f"| B Multi-window | **{_verdict(ema.gate_b_pass)}** | {b_ev} |")
        lines.append(f"| C Fee stress | **{_verdict(ema.gate_c_pass)}** | {c_ev} |")
        lines.append(f"| Combined | **{_verdict(ema.combined)}** | {comb_ev} |")
    lines.append("")

    if ema is not None and ema.windows:
        lines.extend(
            [
                "### `ema_9_21` multi-window detail",
                "",
                "| window | bars | first → last | BTC WF | ETH WF | passed |",
                "| --- | ---: | --- | ---: | ---: | --- |",
            ]
        )
        for window in ema.windows:
            lines.append(
                f"| {window.label} | {window.bars} | {window.first} → {window.last} | "
                f"{_pct(window.btc_wf_total)} | {_pct(window.eth_wf_total)} | "
                f"{'yes' if window.passed else 'no'} |"
            )
        lines.append("")

    passers = sorted(
        [row for row in report.candidates if row.combined],
        key=lambda row: (
            row.combined_rank if row.combined_rank is not None else 10_000,
            row.candidate_id,
        ),
    )
    lines.extend(
        [
            "## Combined-passers (promotion ranking)",
            "",
            (
                f"Frozen ranking key: `{report.ranking_key}`. "
                "Only names that already clear #96 + A + B + C appear here. "
                "Empty table = no promotee (success)."
            ),
            "",
            "| combined rank | id | mean HO excess | BTC HO | ETH HO | ratio | WF total | WF rank | promoted |",
            "| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    if passers:
        for row in passers:
            cr = str(row.combined_rank) if row.combined_rank is not None else "—"
            wr = str(row.wf_rank) if row.wf_rank is not None else "—"
            lines.append(
                f"| {cr} | `{row.candidate_id}` | {_pct(row.mean_holdout_excess)} | "
                f"{_pct(row.baseline_btc_holdout)} | {_pct(row.baseline_eth_holdout)} | "
                f"{_ratio(row.holdout_magnitude_ratio)} | {_pct(row.baseline_wf_total)} | "
                f"{wr} | {'yes' if row.promoted else 'no'} |"
            )
    else:
        lines.append("| — | — | — | — | — | — | — | — | no combined-passers |")
    lines.append("")

    lines.extend(
        [
            "## Full catalog (informational WF rank; A/B/C overlay)",
            "",
            "| WF rank | id | WF total | mean HO | BTC HO | ETH HO | ratio | A | B | C | #96 | combined | promoted |",
            "| ---: | --- | ---: | ---: | ---: | ---: | ---: | --- | --- | --- | --- | --- | --- |",
        ]
    )
    ordered = sorted(
        report.candidates,
        key=lambda row: (
            row.wf_rank is None,
            row.wf_rank if row.wf_rank is not None else 10_000,
            row.candidate_id,
        ),
    )
    for row in ordered:
        rank = str(row.wf_rank) if row.wf_rank is not None else "—"
        lines.append(
            f"| {rank} | `{row.candidate_id}` | {_pct(row.baseline_wf_total)} | "
            f"{_pct(row.mean_holdout_excess)} | "
            f"{_pct(row.baseline_btc_holdout)} | {_pct(row.baseline_eth_holdout)} | "
            f"{_ratio(row.holdout_magnitude_ratio)} | "
            f"{_verdict(row.gate_a_pass)} | {_verdict(row.gate_b_pass)} | "
            f"{_verdict(row.gate_c_pass)} | {_verdict(row.eligible_96)} | "
            f"{_verdict(row.combined)} | {'yes' if row.promoted else 'no'} |"
        )
    lines.append("")

    recheck = [row for row in ordered if row.pr96_recheck]
    lines.extend(
        [
            "## #96 eligible re-check (ADX / SMA variants)",
            "",
            (
                "These names cleared #96 balanced-holdout on the committed "
                "2026-09-12 window (or are the pre-registered ADX/SMA set). "
                "They are re-scored under A–C. Under the expanded ranking "
                "key a combined-passer **can** be selected even if it is not "
                "walk-forward #1. A non-passer is still never promoted."
            ),
            "",
            "| id | #96 | A | B | C | combined | combined rank | note |",
            "| --- | --- | --- | --- | --- | --- | ---: | --- |",
        ]
    )
    for row in recheck:
        if row.promoted:
            note = "combined-passer top-1 under frozen ranking key"
        elif row.combined:
            note = "combined PASS but not top-1 among passers"
        else:
            note = "combined FAIL"
        cr = str(row.combined_rank) if row.combined_rank is not None else "—"
        lines.append(
            f"| `{row.candidate_id}` | {_verdict(row.eligible_96)} | "
            f"{_verdict(row.gate_a_pass)} | {_verdict(row.gate_b_pass)} | "
            f"{_verdict(row.gate_c_pass)} | {_verdict(row.combined)} | "
            f"{cr} | {note} |"
        )
    if not recheck:
        lines.append("| — | — | — | — | — | — | — | re-check set not in this catalog |")
    lines.append("")

    if report.yahoo_notes:
        lines.extend(
            [
                "## Yahoo Finance A/B (non-Kraken, not promotion)",
                "",
                (
                    "Yahoo rows are a longer non-Kraken A/B. They are never "
                    "averaged into ranking, magnitude, multi-window, or fee "
                    "stress. A negative Yahoo BTC holdout cannot be washed out "
                    "by a large ETH print, and a positive Yahoo ETH print "
                    "cannot promote."
                ),
                "",
            ]
        )
        for note in report.yahoo_notes:
            lines.append(f"- {note}")
        lines.append("")

    # --- search evidence (#135) ---
    lines.append(
        f"Print kind: `{report.print_kind}` (era prints are #136; evidence passers: "
        f"{len(report.evidence_passer_ids)})."
    )
    lines.append("")
    lines.extend(
        render_evidence_lines(
            report.evidence, heading="## Evidence (DSR / PBO / bootstrap; additional gates)"
        )
    )

    lines.extend(["## Promotion decision", ""])
    lines.append(
        f"`ema_9_21` #96 balanced-holdout: "
        f"**{_verdict(report.ema_9_21_clears_balanced_holdout)}**. "
        f"Gate A: **{_verdict(report.ema_9_21_gate_a)}**. "
        f"Gate B: **{_verdict(report.ema_9_21_gate_b)}**. "
        f"Gate C: **{_verdict(report.ema_9_21_gate_c)}**. "
        f"Combined: **{_verdict(report.ema_9_21_combined)}**."
    )
    if report.any_promoted:
        winner = next(
            row for row in report.candidates if row.candidate_id == report.promoted_candidate_ids[0]
        )
        flag = report.recommended_promote_flag or paper_promote_flag_name(winner.candidate_id)
        lines.append(
            "Cleared the combined harder-gates bar on Kraken daily BTC+ETH "
            f"and ranked top-1 among combined-passers by `{report.ranking_key}` "
            f"(research only): `{winner.candidate_id}` "
            f"(mean holdout excess={_pct(winner.mean_holdout_excess)}, "
            f"WF rank={winner.wf_rank if winner.wf_rank is not None else '—'})."
        )
        lines.append(
            f"Documented paper-only switch: `{flag}=true` (default **false**; "
            "`TRADING_MODE=paper` only). This report does not flip that "
            "flag, does not flip `PAPER_PROMOTE_EMA_9_21`, and does not "
            "enable live."
        )
    else:
        lines.append(
            "**No candidate cleared the combined harder-gates bar.** "
            "An empty promotee is the successful outcome. Leave "
            "`PAPER_PROMOTE_EMA_9_21=false` and "
            "`PAPER_PROMOTE_SEARCHED_STRATEGIES=false`."
        )
        if report.wf_top1_candidate_id:
            wf_top = next(
                row for row in report.candidates if row.candidate_id == report.wf_top1_candidate_id
            )
            blocked = []
            if not wf_top.eligible_96:
                blocked.append("#96 balanced-holdout")
            if not wf_top.gate_a_pass:
                blocked.append("A magnitude (" + ", ".join(wf_top.gate_a_reasons) + ")")
            if not wf_top.gate_b_pass:
                blocked.append("B multi-window (" + ", ".join(wf_top.gate_b_reasons) + ")")
            if not wf_top.gate_c_pass:
                blocked.append("C fee stress (" + ", ".join(wf_top.gate_c_reasons) + ")")
            lines.append(
                f"Informational walk-forward #1 was `{wf_top.candidate_id}` "
                f"(WF total={_pct(wf_top.baseline_wf_total)}, "
                f"holdout ratio={_ratio(wf_top.holdout_magnitude_ratio)}; "
                f"blocked by: {'; '.join(blocked) or 'n/a'}). "
                "WF rank cannot promote a non-passer."
            )
        if not report.ema_9_21_combined:
            lines.append(
                "`ema_9_21` does **not** clear the combined harder-gates bar on this window."
            )
        # --- search evidence (#135) ---
        if report.selected_candidate_id:
            withheld = next(
                row for row in report.candidates if row.candidate_id == report.selected_candidate_id
            )
            reasons = ", ".join(withheld.evidence.reasons) if withheld.evidence else "n/a"
            lines.append(
                f"Raw combined top-1 `{withheld.candidate_id}` cleared #96+A+B+C but was "
                f"**withheld by the evidence layer** ({reasons}). Evidence is an "
                "additional gate, never a replacement; it cannot promote."
            )
    lines.append("")
    lines.append(
        "Yahoo rows above are a longer non-Kraken A/B. Do not average them "
        "with Kraken prints. Do not copy YouTube or Yahoo-backtest return "
        "figures. Do not flip `PAPER_PROMOTE_EMA_9_21`."
    )
    lines.append("")
    return "\n".join(lines)
