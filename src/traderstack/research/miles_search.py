"""Fee-aware walk-forward + holdout search for Miles-inspired candidates.

Honesty rules (also written into every report):

* Costs are ``max(PRETRADE_FEE_BPS, PAPER_FEE_BPS)`` plus
  ``PRETRADE_SLIPPAGE_BPS``. There is no zero-fee ranking path.
* Ranking uses only the research prefix. The holdout tail is scored after
  ranking and never used to pick a winner.
* Walk-forward folds see the train window as warmup (so GARCH/EMA/ADX have
  history) and only trade the test window.
* Promotion requires walk-forward **mean total return > 0** after fees
  *and* holdout **mean excess return > 0** after fees (plus min trades).
  Positive excess with a losing book is not an edge — that was the #89
  finding on the short 1h Kraken window.
* Multiple-testing policy is pre-registered top-1. If #1 fails holdout we
  do not promote #2.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from traderstack.backtest import BacktestMetrics, simulate_positions
from traderstack.candles import Candle
from traderstack.garch import (
    DEFAULT_MAX_SIZE,
    DEFAULT_MIN_SIZE,
    DEFAULT_MIN_TRAIN,
    DEFAULT_REFIT_EVERY,
    DEFAULT_TARGET_VOL_ANN,
    GarchForecast,
    forecast_at_window,
    forecast_series_for_candles,
)
from traderstack.models import Side
from traderstack.research.miles_candidates import (
    SearchCandidate,
    apply_garch_size,
    default_miles_candidates,
)

# --- era prints / DSR / PBO (#135) ---
from traderstack.research.selection_evidence import SelectionEvidence, build_selection_evidence
from traderstack.signal_registry import version_of
from traderstack.strategies import Regime, RegimeClassifier
from traderstack.walkforward import WalkForwardFold, WalkForwardReport

DEFAULT_HOLDOUT_FRACTION = 0.20
DEFAULT_MIN_TRADES = 3
SELECTION_RULE = "pre_registered_top1"


def research_fee_bps(pretrade_fee_bps: float, paper_fee_bps: float) -> float:
    return max(pretrade_fee_bps, paper_fee_bps)


def split_holdout(
    candles: tuple[Candle, ...],
    *,
    holdout_fraction: float = DEFAULT_HOLDOUT_FRACTION,
    min_holdout: int = 0,
) -> tuple[tuple[Candle, ...], tuple[Candle, ...]]:
    if not 0 < holdout_fraction < 1:
        raise ValueError("holdout_fraction must be in (0, 1)")
    holdout_size = max(int(len(candles) * holdout_fraction), min_holdout)
    if holdout_size <= 0 or holdout_size >= len(candles):
        raise ValueError("holdout split leaves an empty research or holdout window")
    return candles[:-holdout_size], candles[-holdout_size:]


def _safe_regime(classifier: RegimeClassifier, window: tuple[Candle, ...]) -> Regime:
    try:
        return classifier.classify(window)
    except ValueError:
        return Regime.RANGE


def _strip_trade_log(metrics: BacktestMetrics) -> BacktestMetrics:
    return metrics.model_copy(update={"trade_log": []})


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


class SeriesCandidateMetrics(BaseModel):
    asset: str
    interval: str
    candle_count: int
    research_bars: int
    holdout_bars: int
    walkforward: WalkForwardReport | None = None
    walkforward_trades: int = 0
    walkforward_mean_excess_return: float | None = None
    walkforward_mean_total_return: float | None = None
    holdout: BacktestMetrics | None = None
    skipped_reason: str | None = None


class CandidateSearchResult(BaseModel):
    candidate_id: str
    family: str
    label: str
    params: dict[str, Any]
    signal_version: str
    per_series: list[SeriesCandidateMetrics] = Field(default_factory=list)
    mean_wf_excess_return: float | None = None
    mean_wf_total_return: float | None = None
    total_wf_trades: int = 0
    mean_holdout_excess_return: float | None = None
    mean_holdout_total_return: float | None = None
    total_holdout_trades: int = 0
    rankable: bool = False
    eligible: bool = False
    ineligible_reasons: list[str] = Field(default_factory=list)
    rank: int | None = None
    selected: bool = False
    promoted: bool = False


class MilesSearchReport(BaseModel):
    generated_at: datetime
    symbols: list[str]
    intervals: list[str]
    fee_bps: float
    slippage_bps: float
    cost_note: str
    starting_equity: float
    warmup: int
    train_size: int
    test_size: int
    step_size: int
    holdout_fraction: float
    min_trades: int
    garch_min_train: int
    garch_refit_every: int
    garch_target_vol_ann: float
    selection_rule: str
    multiple_testing: dict[str, Any]
    candidates: list[CandidateSearchResult]
    # --- era prints / DSR / PBO (#135) ---
    # K is the frozen catalog length, which this report already tracks as
    # multiple_testing["n_candidates"], so the deflation term is not a guess.
    selection_evidence: SelectionEvidence | None = None
    selected_candidate_id: str | None = None
    promoted_candidate_ids: list[str] = Field(default_factory=list)
    any_promoted: bool = False
    honesty: str
    data_notes: list[str] = Field(default_factory=list)
    # Daily is the GARCH/Miles timeframe. 1h is reported but not averaged in.
    promotion_interval: str | None = None


def _position_decision(
    candidate: SearchCandidate,
    *,
    garch_series: list[GarchForecast | None] | None,
    classifier: RegimeClassifier,
):
    def decide(window: tuple[Candle, ...]) -> tuple[float, Regime, list[str]]:
        regime = _safe_regime(classifier, window)
        signal = candidate.strategy.evaluate(window, regime)
        if signal.side is None:
            return 0.0, regime, []
        weight = 1.0 if signal.side is Side.BUY else -1.0
        if candidate.garch_sizing:
            forecast = (
                forecast_at_window(garch_series, window) if garch_series is not None else None
            )
            weight = apply_garch_size(weight, forecast)
            if weight == 0.0:
                return 0.0, regime, []
        return weight, regime, [candidate.candidate_id]

    return decide


def _run_backtest(
    candidate: SearchCandidate,
    candles: tuple[Candle, ...],
    *,
    fee_bps: float,
    slippage_bps: float,
    starting_equity: float,
    warmup: int,
    garch_min_train: int,
    garch_refit_every: int,
    garch_target_vol_ann: float,
) -> BacktestMetrics:
    classifier = RegimeClassifier()
    garch_series: list[GarchForecast | None] | None = None
    if candidate.garch_sizing:
        garch_series = forecast_series_for_candles(
            candles,
            min_train=garch_min_train,
            refit_every=garch_refit_every,
            target_vol_ann=garch_target_vol_ann,
            min_size=DEFAULT_MIN_SIZE,
            max_size=DEFAULT_MAX_SIZE,
        )
    return simulate_positions(
        candles,
        _position_decision(candidate, garch_series=garch_series, classifier=classifier),
        starting_equity=starting_equity,
        warmup=warmup,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
        rebalance_threshold=0.05 if candidate.garch_sizing else 1e-9,
    )


def _walkforward_with_train_warmup(
    candidate: SearchCandidate,
    research: tuple[Candle, ...],
    *,
    fee_bps: float,
    slippage_bps: float,
    starting_equity: float,
    train_size: int,
    test_size: int,
    step_size: int,
    garch_min_train: int,
    garch_refit_every: int,
    garch_target_vol_ann: float,
) -> WalkForwardReport:
    """Each fold is train+test; warmup=train_size so only the test window trades."""
    if step_size <= 0:
        raise ValueError("step_size must be positive")
    folds: list[WalkForwardFold] = []
    train_start = 0
    while True:
        train_end = train_start + train_size
        test_end = train_end + test_size
        if test_end > len(research):
            break
        window = research[train_start:test_end]
        metrics = _run_backtest(
            candidate,
            window,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            starting_equity=starting_equity,
            warmup=train_size,
            garch_min_train=garch_min_train,
            garch_refit_every=garch_refit_every,
            garch_target_vol_ann=garch_target_vol_ann,
        )
        folds.append(
            WalkForwardFold(
                train_start=train_start,
                train_end=train_end,
                test_start=train_end,
                test_end=test_end,
                metrics=_strip_trade_log(metrics),
            )
        )
        train_start += step_size
    if not folds:
        raise ValueError("insufficient candles for one walk-forward fold")
    count = len(folds)
    return WalkForwardReport(
        folds=folds,
        mean_total_return=sum(fold.metrics.total_return for fold in folds) / count,
        mean_excess_return=sum(fold.metrics.excess_return for fold in folds) / count,
        mean_sharpe=sum(fold.metrics.sharpe for fold in folds) / count,
        worst_drawdown=max(fold.metrics.max_drawdown for fold in folds),
    )


def walkforward_candidate_on_window(
    candidate: SearchCandidate,
    candles: tuple[Candle, ...],
    *,
    fee_bps: float,
    slippage_bps: float,
    starting_equity: float,
    train_size: int,
    test_size: int,
    step_size: int,
    garch_min_train: int = DEFAULT_MIN_TRAIN,
    garch_refit_every: int = DEFAULT_REFIT_EVERY,
    garch_target_vol_ann: float = DEFAULT_TARGET_VOL_ANN,
) -> WalkForwardReport:
    """Fee-aware walk-forward on a contiguous window with no holdout split.

    Used by the harder-gates multi-window bar: each 240-bar slice is the
    robustness window itself, so a holdout tail would leave too few bars
    for the #96 train=180 / test=60 fold.
    """
    return _walkforward_with_train_warmup(
        candidate,
        candles,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
        starting_equity=starting_equity,
        train_size=train_size,
        test_size=test_size,
        step_size=step_size,
        garch_min_train=garch_min_train,
        garch_refit_every=garch_refit_every,
        garch_target_vol_ann=garch_target_vol_ann,
    )


def evaluate_candidate_on_series(
    candidate: SearchCandidate,
    candles: tuple[Candle, ...],
    *,
    fee_bps: float,
    slippage_bps: float,
    starting_equity: float,
    train_size: int,
    test_size: int,
    step_size: int,
    holdout_fraction: float,
    garch_min_train: int,
    garch_refit_every: int,
    garch_target_vol_ann: float,
) -> SeriesCandidateMetrics:
    asset = candles[0].symbol if candles else "unknown"
    interval = candles[0].interval if candles else "unknown"
    try:
        research, holdout = split_holdout(candles, holdout_fraction=holdout_fraction)
    except ValueError as exc:
        return SeriesCandidateMetrics(
            asset=asset,
            interval=interval,
            candle_count=len(candles),
            research_bars=0,
            holdout_bars=0,
            skipped_reason=str(exc),
        )

    walkforward: WalkForwardReport | None = None
    wf_reason: str | None = None
    try:
        walkforward = _walkforward_with_train_warmup(
            candidate,
            research,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            starting_equity=starting_equity,
            train_size=train_size,
            test_size=test_size,
            step_size=step_size,
            garch_min_train=garch_min_train,
            garch_refit_every=garch_refit_every,
            garch_target_vol_ann=garch_target_vol_ann,
        )
    except ValueError as exc:
        wf_reason = str(exc)

    holdout_metrics: BacktestMetrics | None = None
    try:
        # Holdout trades see the research prefix as warmup (GARCH/EMA history).
        combined = research + holdout
        holdout_metrics = _run_backtest(
            candidate,
            combined,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            starting_equity=starting_equity,
            warmup=len(research),
            garch_min_train=garch_min_train,
            garch_refit_every=garch_refit_every,
            garch_target_vol_ann=garch_target_vol_ann,
        )
        holdout_metrics = _strip_trade_log(holdout_metrics)
    except ValueError:
        holdout_metrics = None

    wf_trades = 0
    if walkforward is not None:
        wf_trades = sum(fold.metrics.trades for fold in walkforward.folds)

    return SeriesCandidateMetrics(
        asset=asset,
        interval=interval,
        candle_count=len(candles),
        research_bars=len(research),
        holdout_bars=len(holdout),
        walkforward=walkforward,
        walkforward_trades=wf_trades,
        walkforward_mean_excess_return=(
            walkforward.mean_excess_return if walkforward is not None else None
        ),
        walkforward_mean_total_return=(
            walkforward.mean_total_return if walkforward is not None else None
        ),
        holdout=holdout_metrics,
        skipped_reason=wf_reason if walkforward is None else None,
    )


def promotion_interval_for(series_rows: list[SeriesCandidateMetrics]) -> str | None:
    """Prefer daily (Miles: use the daily chart). Do not mix 1h percent returns with 1d."""
    intervals = {row.interval for row in series_rows if row.interval}
    if "1d" in intervals:
        return "1d"
    if len(intervals) == 1:
        return next(iter(intervals))
    return None


def _series_for_gate(
    per_series: list[SeriesCandidateMetrics], promotion_interval: str | None
) -> list[SeriesCandidateMetrics]:
    if promotion_interval is None:
        return per_series
    return [row for row in per_series if row.interval == promotion_interval]


def _gate_reasons(row: CandidateSearchResult, *, min_trades: int) -> list[str]:
    reasons: list[str] = []
    if row.mean_wf_total_return is None:
        reasons.append("walkforward_missing")
    elif row.mean_wf_total_return <= 0:
        reasons.append("walkforward_total_return_not_positive")
    if row.total_wf_trades < min_trades:
        reasons.append("walkforward_trade_count_below_minimum")
    if row.mean_holdout_excess_return is None:
        reasons.append("holdout_missing")
    elif row.mean_holdout_excess_return <= 0:
        reasons.append("holdout_excess_return_not_positive")
    return reasons


def run_miles_search(
    histories: dict[str, tuple[Candle, ...]],
    *,
    fee_bps: float,
    slippage_bps: float = 5.0,
    starting_equity: float = 10_000.0,
    train_size: int = 180,
    test_size: int = 60,
    step_size: int = 60,
    holdout_fraction: float = DEFAULT_HOLDOUT_FRACTION,
    min_trades: int = DEFAULT_MIN_TRADES,
    candidates: tuple[SearchCandidate, ...] | None = None,
    garch_min_train: int = DEFAULT_MIN_TRAIN,
    garch_refit_every: int = DEFAULT_REFIT_EVERY,
    garch_target_vol_ann: float = DEFAULT_TARGET_VOL_ANN,
    now: datetime | None = None,
    data_notes: list[str] | None = None,
) -> MilesSearchReport:
    if not histories:
        raise ValueError("no candle histories provided")
    catalog = list(candidates if candidates is not None else default_miles_candidates())
    sample_series = [
        SeriesCandidateMetrics(
            asset=candles[0].symbol if candles else "unknown",
            interval=candles[0].interval if candles else "unknown",
            candle_count=len(candles),
            research_bars=0,
            holdout_bars=0,
        )
        for candles in histories.values()
    ]
    promotion_interval = promotion_interval_for(sample_series)
    rows: list[CandidateSearchResult] = []
    for candidate in catalog:
        per_series = [
            evaluate_candidate_on_series(
                candidate,
                candles,
                fee_bps=fee_bps,
                slippage_bps=slippage_bps,
                starting_equity=starting_equity,
                train_size=train_size,
                test_size=test_size,
                step_size=step_size,
                holdout_fraction=holdout_fraction,
                garch_min_train=garch_min_train,
                garch_refit_every=garch_refit_every,
                garch_target_vol_ann=garch_target_vol_ann,
            )
            for candles in histories.values()
        ]
        gated = _series_for_gate(per_series, promotion_interval)
        wf_excess = [
            row.walkforward_mean_excess_return
            for row in gated
            if row.walkforward_mean_excess_return is not None
        ]
        wf_total = [
            row.walkforward_mean_total_return
            for row in gated
            if row.walkforward_mean_total_return is not None
        ]
        holdout_excess = [row.holdout.excess_return for row in gated if row.holdout is not None]
        holdout_total = [row.holdout.total_return for row in gated if row.holdout is not None]
        result = CandidateSearchResult(
            candidate_id=candidate.candidate_id,
            family=candidate.family,
            label=candidate.label,
            params=dict(candidate.params),
            signal_version=version_of(candidate.strategy),
            per_series=per_series,
            mean_wf_excess_return=_mean(wf_excess),
            mean_wf_total_return=_mean(wf_total),
            total_wf_trades=sum(row.walkforward_trades for row in gated),
            mean_holdout_excess_return=_mean(holdout_excess),
            mean_holdout_total_return=_mean(holdout_total),
            total_holdout_trades=sum(
                row.holdout.trades for row in gated if row.holdout is not None
            ),
        )
        result.rankable = (
            result.mean_wf_total_return is not None and result.total_wf_trades >= min_trades
        )
        result.ineligible_reasons = _gate_reasons(result, min_trades=min_trades)
        result.eligible = not result.ineligible_reasons
        rows.append(result)

    rankable = [row for row in rows if row.rankable]
    rankable.sort(
        key=lambda row: (
            row.mean_wf_total_return if row.mean_wf_total_return is not None else float("-inf")
        ),
        reverse=True,
    )
    for index, row in enumerate(rankable, start=1):
        row.rank = index

    selected = rankable[0] if rankable else None
    if selected is not None:
        selected.selected = True
        if selected.eligible:
            selected.promoted = True

    count = len(catalog)
    honesty = (
        "No candidate is rewritten to look profitable. "
        "Walk-forward ranking never sees the holdout tail. "
        f"Selection is pre-registered top-1 of {count} Miles-inspired catalog "
        "members (Bonferroni analogue: one promotion decision, not K independent "
        "promotions). A selected candidate is promoted only if fee-aware "
        "walk-forward mean total return is strictly greater than 0, min trades "
        "are met, and holdout mean excess return is strictly greater than 0. "
        "Positive excess with a negative total return is not an edge. "
        "1h and daily percent returns are never averaged together; when daily "
        "bars are present they are the promotion window (Miles: use the daily "
        "chart) and 1h is a robustness table only."
    )
    if selected is None or not selected.promoted:
        honesty += " No candidate cleared the bar on this data; paper promotion must stay off."

    symbols = sorted({candles[0].symbol for candles in histories.values() if candles})
    intervals = sorted({candles[0].interval for candles in histories.values() if candles})

    # --- era prints / DSR / PBO (#135) ---
    # K is `count`, the frozen catalog length this report already publishes as
    # multiple_testing["n_candidates"], so the deflation term is the real
    # number of trials rather than a guess. Imported at call time because
    # daily_robustness imports this module; see selection_evidence for the
    # same note. venue_print_available stays False: one venue is scored here,
    # and a single print withholds.
    from traderstack.research.daily_robustness import kraken_daily_candles

    evidence_interval = promotion_interval or "1d"
    evidence = build_selection_evidence(
        rows,
        primary_candles=kraken_daily_candles(histories, "BTC/USD", interval=evidence_interval),
        primary_venue="scored_venue",
        interval=evidence_interval,
        test_size=test_size,
        configured_min_trades=min_trades,
    )
    return MilesSearchReport(
        generated_at=now or datetime.now(UTC),
        symbols=symbols,
        intervals=intervals,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
        cost_note=(
            "fee_bps is max(PRETRADE_FEE_BPS, PAPER_FEE_BPS); "
            "slippage_bps is PRETRADE_SLIPPAGE_BPS. Every fill pays both."
        ),
        starting_equity=starting_equity,
        warmup=train_size,
        train_size=train_size,
        test_size=test_size,
        step_size=step_size,
        holdout_fraction=holdout_fraction,
        min_trades=min_trades,
        garch_min_train=garch_min_train,
        garch_refit_every=garch_refit_every,
        garch_target_vol_ann=garch_target_vol_ann,
        selection_rule=SELECTION_RULE,
        # --- era prints / DSR / PBO (#135) ---
        selection_evidence=evidence,
        multiple_testing={
            "method": SELECTION_RULE,
            "n_candidates": count,
            "bonferroni": (
                "K catalog members are scored on the same research window. "
                "We do not treat every excess>0 as a discovered edge. "
                "At most the single pre-registered top-1 (by walk-forward mean "
                "total return, min-trades filter) may be promoted, and only "
                "if holdout excess return is also strictly positive. "
                f"A classical Bonferroni p-cut would be 0.05/{count} ≈ "
                f"{0.05 / max(count, 1):.4f}; this search has no per-fold "
                "t-test, so holdout confirmation is the out-of-sample control."
            ),
        },
        candidates=rows,
        selected_candidate_id=selected.candidate_id if selected is not None else None,
        promoted_candidate_ids=(
            [selected.candidate_id] if selected is not None and selected.promoted else []
        ),
        any_promoted=bool(selected is not None and selected.promoted),
        honesty=honesty,
        data_notes=list(data_notes or []),
        promotion_interval=promotion_interval,
    )


def render_miles_markdown(report: MilesSearchReport) -> str:
    lines: list[str] = [
        "# Miles-inspired strategy search report",
        "",
        f"Generated: {report.generated_at.isoformat()}",
        f"Symbols: {', '.join(report.symbols)}",
        f"Intervals: {', '.join(report.intervals)}"
        + (
            f" (promotion uses {report.promotion_interval} only)"
            if report.promotion_interval
            else ""
        ),
        (
            f"Costs: fee={report.fee_bps:g} bps + slippage={report.slippage_bps:g} bps "
            f"({report.cost_note})"
        ),
        (
            f"Walk-forward: train={report.train_size} test={report.test_size} "
            f"step={report.step_size} (train is warmup; only the test window trades); "
            f"holdout_fraction={report.holdout_fraction:.0%}"
        ),
        (
            "Promotion floor: WF mean total_return > 0 **and** holdout mean "
            f"excess_return > 0 after fees, min trades={report.min_trades}"
        ),
        (
            f"GARCH: min_train={report.garch_min_train} refit_every="
            f"{report.garch_refit_every} target_vol_ann={report.garch_target_vol_ann:g} "
            "size clip [0.25, 2.0]"
        ),
        f"Selection: {report.selection_rule} (K={report.multiple_testing.get('n_candidates')})",
        "",
        "## Inspiration and honesty",
        "",
        "Methods only — not claimed YouTube PnL. Direction is EMA crossover "
        "(9/21, 12/26) with an optional ADX chop gate. GARCH(1,1) is a "
        "walk-forward vol forecast used *only* to scale size "
        "(`target_vol / forecast_vol`). " + report.honesty,
        "",
        "## Multiple testing",
        "",
        str(report.multiple_testing.get("bonferroni", "")),
        "",
    ]
    if report.data_notes:
        lines.extend(["## Data", ""])
        for note in report.data_notes:
            lines.append(f"- {note}")
        lines.append("")
    lines.extend(
        [
            "## Ranked candidates (walk-forward mean total return after fees)",
            "",
            "| rank | id | family | WF total | WF excess | WF trades | holdout excess | eligible | promoted |",
            "| ---: | --- | --- | ---: | ---: | ---: | ---: | --- | --- |",
        ]
    )
    ordered = sorted(
        report.candidates,
        key=lambda row: (
            row.rank is None,
            row.rank if row.rank is not None else 10_000,
            row.candidate_id,
        ),
    )
    for row in ordered:
        wf_x = (
            f"{row.mean_wf_excess_return:+.2%}" if row.mean_wf_excess_return is not None else "n/a"
        )
        wf_t = f"{row.mean_wf_total_return:+.2%}" if row.mean_wf_total_return is not None else "n/a"
        ho_x = (
            f"{row.mean_holdout_excess_return:+.2%}"
            if row.mean_holdout_excess_return is not None
            else "n/a"
        )
        rank = str(row.rank) if row.rank is not None else "—"
        lines.append(
            f"| {rank} | `{row.candidate_id}` | {row.family} | {wf_t} | {wf_x} | "
            f"{row.total_wf_trades} | {ho_x} | "
            f"{'yes' if row.eligible else 'no'} | {'yes' if row.promoted else 'no'} |"
        )

    lines.extend(["", "## Per-series detail", ""])
    for row in ordered:
        lines.append(f"### `{row.candidate_id}` — {row.label}")
        lines.append("")
        lines.append("| series | bars | WF total | WF excess | holdout excess | holdout total |")
        lines.append("| --- | ---: | ---: | ---: | ---: | ---: |")
        for series in row.per_series:
            name = f"{series.asset} {series.interval}"
            wf_t = (
                f"{series.walkforward_mean_total_return:+.2%}"
                if series.walkforward_mean_total_return is not None
                else "n/a"
            )
            wf_x = (
                f"{series.walkforward_mean_excess_return:+.2%}"
                if series.walkforward_mean_excess_return is not None
                else "n/a"
            )
            if series.holdout is None:
                ho_x, ho_t = "n/a", "n/a"
            else:
                ho_x = f"{series.holdout.excess_return:+.2%}"
                ho_t = f"{series.holdout.total_return:+.2%}"
            skip = f" ({series.skipped_reason})" if series.skipped_reason else ""
            lines.append(
                f"| {name}{skip} | {series.candle_count} | {wf_t} | {wf_x} | {ho_x} | {ho_t} |"
            )
        lines.append("")

    lines.extend(["## Promotion decision", ""])
    if report.any_promoted:
        garch_promoted = any(
            row.promoted and row.family == "ema_cross_garch" for row in report.candidates
        )
        lines.append(
            "Promoted on the "
            f"{report.promotion_interval or 'available'} window "
            f"(research only): {', '.join(report.promoted_candidate_ids)}."
        )
        if garch_promoted:
            lines.append(
                "`PAPER_GARCH_SIZE` remains an operator switch and still defaults "
                "false until reviewed — GARCH is a reduce-only overlay in RiskEngine."
            )
        else:
            lines.append(
                "**`PAPER_GARCH_SIZE` stays false.** No GARCH-sized candidate "
                "cleared the bar (vol-targeted size increased turnover and fee drag)."
            )
        if any(row.promoted and row.candidate_id == "ema_9_21" for row in report.candidates):
            lines.append(
                "Register `ema_9_21` as a paper voter only via "
                "`PAPER_PROMOTE_EMA_9_21=true` (default false; `TRADING_MODE=paper` "
                "only). That flag also forces paper candles to daily (`1d` / 1440m) "
                "— do not claim this daily edge on a 1h runtime. This report does "
                "not flip that flag and does not enable live."
            )
        lines.append(
            "1h robustness (not in the promotion average) is in the per-series "
            "tables. A large daily holdout on one asset is one tail, not a "
            "live-capital claim. Do not copy YouTube return figures."
        )
    else:
        lines.append(
            "**No candidate cleared the bar.** Leave `PAPER_GARCH_SIZE=false`. "
            "This is not an edge. Do not copy YouTube return claims."
        )
        if report.selected_candidate_id:
            selected = next(
                row for row in report.candidates if row.candidate_id == report.selected_candidate_id
            )
            wf = (
                f"{selected.mean_wf_total_return:+.2%}"
                if selected.mean_wf_total_return is not None
                else "n/a"
            )
            ho = (
                f"{selected.mean_holdout_excess_return:+.2%}"
                if selected.mean_holdout_excess_return is not None
                else "n/a"
            )
            reasons = ", ".join(selected.ineligible_reasons) or "n/a"
            lines.append(
                f"Pre-registered top-1 by WF total return was `{selected.candidate_id}` "
                f"(WF total={wf}, holdout excess={ho}; blocked by: {reasons})."
            )
    lines.append("")
    # --- era prints / DSR / PBO (#135) ---
    from traderstack.research.selection_evidence import render_evidence_lines

    lines.extend(render_evidence_lines(report.selection_evidence))
    return "\n".join(lines)
