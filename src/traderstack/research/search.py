"""Fee-aware walk-forward + holdout search over a pre-registered candidate set.

Honesty rules (also written into every report):

* Costs are the conservative of ``PRETRADE_FEE_BPS`` and ``PAPER_FEE_BPS``,
  plus ``PRETRADE_SLIPPAGE_BPS``. There is no zero-fee run hiding in the
  ranking.
* Ranking uses only the research window (walk-forward folds). The holdout
  tail is scored after ranking and never used to pick a winner.
* Multiple-testing policy is **pre-registered top-1**. With K candidates we
  take one bite at the apple: the single best walk-forward mean excess
  return (among those with enough trades). We do not then promote #2 if #1
  fails holdout. A Bonferroni note is recorded (K looks, one selection);
  we do not invent per-fold p-values we do not have.
* Promotion requires walk-forward mean **total** return strictly greater
  than the configured floor (default 0) after fees — beating buy-and-hold
  while still losing money is not an edge — plus min trades, and (by
  default) holdout mean excess return strictly above the floor. Ranking
  stays pre-registered top-1 by walk-forward mean *excess*; a top-1 that
  fails the total-return gate does **not** unlock #2. No candidate is
  rewritten to look like a winner.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from traderstack.backtest import BacktestMetrics, BaselineBacktester
from traderstack.candles import Candle
from traderstack.research.candidates import (
    FEATURE_CATALOG,
    SearchCandidate,
    default_price_candidates,
    feature_candidates,
)
from traderstack.signal_registry import version_of
from traderstack.strategies import StrategyEnsemble
from traderstack.walkforward import WalkForwardEvaluator, WalkForwardReport

DEFAULT_HOLDOUT_FRACTION = 0.20
DEFAULT_MIN_TRADES = 3
DEFAULT_MIN_WF_EXCESS = 0.0
SELECTION_RULE = "pre_registered_top1"


class AssetCandidateMetrics(BaseModel):
    asset: str
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
    requires_feature: str | None = None
    skipped_reason: str | None = None
    per_asset: list[AssetCandidateMetrics] = Field(default_factory=list)
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


class StrategySearchReport(BaseModel):
    generated_at: datetime
    symbols: list[str]
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
    min_wf_excess_return: float
    min_wf_total_return: float = 0.0
    require_wf_total_return: bool = True
    require_holdout_confirmation: bool
    selection_rule: str
    multiple_testing: dict[str, Any]
    skipped_feature_families: list[dict[str, str]]
    history_notes: list[dict[str, str]] = Field(default_factory=list)
    edge_notes: list[dict[str, str]] = Field(default_factory=list)
    candidates: list[CandidateSearchResult]
    selected_candidate_id: str | None = None
    promoted_candidate_ids: list[str] = Field(default_factory=list)
    any_promoted: bool = False
    honesty: str
    allowed_promote_id: str | None = None


def research_fee_bps(pretrade_fee_bps: float, paper_fee_bps: float) -> float:
    """Conservative fee used for search and for paper-gate cost alignment."""
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


def ensemble_for(strategy: object) -> StrategyEnsemble:
    """One standalone voter; consensus min_agreeing=1 so the piece can trade."""
    return StrategyEnsemble(
        extra_voters=(strategy,),
        min_agreeing=1,
        suppress_defaults=True,
    )


def backtester_for(
    strategy: object,
    *,
    fee_bps: float,
    slippage_bps: float,
    starting_equity: float,
    warmup: int,
) -> BaselineBacktester:
    return BaselineBacktester(
        ensemble=ensemble_for(strategy),
        starting_equity=starting_equity,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
        warmup=warmup,
    )


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _gate_reasons(
    row: CandidateSearchResult,
    *,
    min_trades: int,
    min_wf_excess_return: float,
    require_holdout_confirmation: bool,
    require_wf_total_return: bool = True,
    min_wf_total_return: float = 0.0,
) -> list[str]:
    reasons: list[str] = []
    if row.skipped_reason:
        reasons.append(row.skipped_reason)
        return reasons
    if row.mean_wf_excess_return is None:
        reasons.append("walkforward_missing")
    elif row.mean_wf_excess_return <= min_wf_excess_return:
        reasons.append("walkforward_excess_return_not_positive")
    if require_wf_total_return:
        if row.mean_wf_total_return is None:
            reasons.append("walkforward_total_return_missing")
        elif row.mean_wf_total_return <= min_wf_total_return:
            reasons.append("walkforward_total_return_not_positive")
    if row.total_wf_trades < min_trades:
        reasons.append("walkforward_trade_count_below_minimum")
    if require_holdout_confirmation:
        if row.mean_holdout_excess_return is None:
            reasons.append("holdout_missing")
        elif row.mean_holdout_excess_return <= min_wf_excess_return:
            reasons.append("holdout_excess_return_not_positive")
    return reasons


def evaluate_candidate_on_asset(
    candidate: SearchCandidate,
    candles: tuple[Candle, ...],
    *,
    fee_bps: float,
    slippage_bps: float,
    starting_equity: float,
    warmup: int,
    train_size: int,
    test_size: int,
    step_size: int,
    holdout_fraction: float,
) -> AssetCandidateMetrics:
    asset = candles[0].symbol if candles else "unknown"
    try:
        research, holdout = split_holdout(candles, holdout_fraction=holdout_fraction)
    except ValueError as exc:
        return AssetCandidateMetrics(
            asset=asset,
            candle_count=len(candles),
            research_bars=0,
            holdout_bars=0,
            skipped_reason=str(exc),
        )

    backtester = backtester_for(
        candidate.strategy,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
        starting_equity=starting_equity,
        warmup=warmup,
    )
    walkforward: WalkForwardReport | None = None
    wf_reason: str | None = None
    try:
        walkforward = WalkForwardEvaluator(
            backtester=backtester,
            train_size=train_size,
            test_size=test_size,
            step_size=step_size,
        ).evaluate(research)
    except ValueError as exc:
        wf_reason = str(exc)

    holdout_metrics: BacktestMetrics | None = None
    try:
        holdout_metrics = backtester.run(holdout)
    except ValueError:
        holdout_metrics = None

    wf_trades = 0
    if walkforward is not None:
        wf_trades = sum(fold.metrics.trades for fold in walkforward.folds)
        # Ranked reports do not need per-fill logs; they balloon the artifact.
        walkforward = walkforward.model_copy(
            update={
                "folds": [
                    fold.model_copy(
                        update={"metrics": fold.metrics.model_copy(update={"trade_log": []})}
                    )
                    for fold in walkforward.folds
                ]
            }
        )
    if holdout_metrics is not None:
        holdout_metrics = holdout_metrics.model_copy(update={"trade_log": []})

    return AssetCandidateMetrics(
        asset=asset,
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


def run_search(
    histories: dict[str, tuple[Candle, ...]],
    *,
    fee_bps: float,
    slippage_bps: float = 5.0,
    starting_equity: float = 10_000.0,
    warmup: int = 31,
    train_size: int = 180,
    test_size: int = 60,
    step_size: int = 60,
    holdout_fraction: float = DEFAULT_HOLDOUT_FRACTION,
    min_trades: int = DEFAULT_MIN_TRADES,
    min_wf_excess_return: float = DEFAULT_MIN_WF_EXCESS,
    min_wf_total_return: float = 0.0,
    require_wf_total_return: bool = True,
    require_holdout_confirmation: bool = True,
    candidates: tuple[SearchCandidate, ...] | None = None,
    liquidation: tuple[tuple[datetime, float], ...] | None = None,
    liquidation_by_symbol: dict[str, tuple[tuple[datetime, float], ...]] | None = None,
    funding: tuple[tuple[datetime, float], ...] | None = None,
    funding_by_symbol: dict[str, tuple[tuple[datetime, float], ...]] | None = None,
    open_interest: tuple[tuple[datetime, float], ...] | None = None,
    open_interest_by_symbol: dict[str, tuple[tuple[datetime, float], ...]] | None = None,
    cross_venue: tuple[tuple[datetime, float], ...] | None = None,
    history_notes: list[dict[str, str]] | None = None,
    edge_notes: list[dict[str, str]] | None = None,
    now: datetime | None = None,
) -> StrategySearchReport:
    if not histories:
        raise ValueError("no candle histories provided")

    catalog = list(candidates if candidates is not None else default_price_candidates())
    catalog.extend(
        feature_candidates(
            liquidation=liquidation,
            liquidation_by_symbol=liquidation_by_symbol,
            funding=funding,
            funding_by_symbol=funding_by_symbol,
            open_interest=open_interest,
            open_interest_by_symbol=open_interest_by_symbol,
            cross_venue=cross_venue,
        )
    )

    present_features = {
        *(["liquidation_z"] if liquidation is not None or liquidation_by_symbol else []),
        *(["funding_z"] if funding is not None or funding_by_symbol else []),
        *(["open_interest_z"] if open_interest is not None or open_interest_by_symbol else []),
        *(["cross_venue_divergence_z"] if cross_venue is not None else []),
    }
    skipped_feature_families = [
        {
            "family": family,
            "candidate_id": candidate_id,
            "reason": (
                f"{label}: skipped — no aligned series supplied. "
                "This feature is not present on the Kraken Spot OHLC paper path."
            ),
        }
        for family, candidate_id, label in FEATURE_CATALOG
        if (family == "liquidation_z" and "liquidation_z" not in present_features)
        or (family == "funding_z" and "funding_z" not in present_features)
        or (family == "open_interest_z" and "open_interest_z" not in present_features)
        or (family == "cross_venue" and "cross_venue_divergence_z" not in present_features)
    ]

    rows: list[CandidateSearchResult] = []
    for candidate in catalog:
        per_asset = [
            evaluate_candidate_on_asset(
                candidate,
                candles,
                fee_bps=fee_bps,
                slippage_bps=slippage_bps,
                starting_equity=starting_equity,
                warmup=warmup,
                train_size=train_size,
                test_size=test_size,
                step_size=step_size,
                holdout_fraction=holdout_fraction,
            )
            for candles in histories.values()
        ]
        wf_excess = [
            row.walkforward_mean_excess_return
            for row in per_asset
            if row.walkforward_mean_excess_return is not None
        ]
        wf_total = [
            row.walkforward_mean_total_return
            for row in per_asset
            if row.walkforward_mean_total_return is not None
        ]
        holdout_excess = [row.holdout.excess_return for row in per_asset if row.holdout is not None]
        holdout_total = [row.holdout.total_return for row in per_asset if row.holdout is not None]
        result = CandidateSearchResult(
            candidate_id=candidate.candidate_id,
            family=candidate.family,
            label=candidate.label,
            params=dict(candidate.params),
            signal_version=version_of(candidate.strategy),
            requires_feature=candidate.requires_feature,
            per_asset=per_asset,
            mean_wf_excess_return=_mean(wf_excess),
            mean_wf_total_return=_mean(wf_total),
            total_wf_trades=sum(row.walkforward_trades for row in per_asset),
            mean_holdout_excess_return=_mean(holdout_excess),
            mean_holdout_total_return=_mean(holdout_total),
            total_holdout_trades=sum(
                row.holdout.trades for row in per_asset if row.holdout is not None
            ),
        )
        result.rankable = (
            result.mean_wf_excess_return is not None and result.total_wf_trades >= min_trades
        )
        result.ineligible_reasons = _gate_reasons(
            result,
            min_trades=min_trades,
            min_wf_excess_return=min_wf_excess_return,
            require_holdout_confirmation=require_holdout_confirmation,
            require_wf_total_return=require_wf_total_return,
            min_wf_total_return=min_wf_total_return,
        )
        result.eligible = not result.ineligible_reasons
        rows.append(result)

    rankable = [row for row in rows if row.rankable]
    rankable.sort(
        key=lambda row: (
            row.mean_wf_excess_return if row.mean_wf_excess_return is not None else float("-inf")
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

    k = len(catalog)
    honesty = (
        "No candidate is rewritten to look profitable. "
        "Walk-forward ranking never sees the holdout tail. "
        f"Selection is pre-registered top-1 of {k} catalog members "
        "(Bonferroni analogue: one promotion decision, not K independent promotions). "
        "A selected candidate is promoted only if fee-aware walk-forward mean "
        "total return is strictly above the floor (and excess is recorded), "
        "min trades are met"
        + (
            ", and holdout mean excess return is also strictly above the floor."
            if require_holdout_confirmation
            else "."
        )
    )
    if selected is None or not selected.promoted:
        honesty += " No candidate cleared the bar on this data; paper promotion must stay off."

    return StrategySearchReport(
        generated_at=now or datetime.now(UTC),
        symbols=sorted(histories),
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
        cost_note=(
            "fee_bps is max(PRETRADE_FEE_BPS, PAPER_FEE_BPS); "
            "slippage_bps is PRETRADE_SLIPPAGE_BPS. Every fill pays both."
        ),
        starting_equity=starting_equity,
        warmup=warmup,
        train_size=train_size,
        test_size=test_size,
        step_size=step_size,
        holdout_fraction=holdout_fraction,
        min_trades=min_trades,
        min_wf_excess_return=min_wf_excess_return,
        min_wf_total_return=min_wf_total_return,
        require_wf_total_return=require_wf_total_return,
        require_holdout_confirmation=require_holdout_confirmation,
        selection_rule=SELECTION_RULE,
        multiple_testing={
            "method": SELECTION_RULE,
            "n_candidates": k,
            "bonferroni": (
                "K catalog members are scored on the same research window. "
                "We do not treat every excess>0 as a discovered edge. "
                "At most the single pre-registered top-1 (by walk-forward mean "
                "excess return, min-trades filter) may be promoted, and only "
                "if it also clears the configured floors. "
                f"A classical Bonferroni p-cut would be 0.05/{k} ≈ {0.05 / max(k, 1):.4f}; "
                "this search has no per-fold t-test, so holdout confirmation "
                "is the out-of-sample control instead of a p-value."
            ),
        },
        skipped_feature_families=skipped_feature_families,
        history_notes=list(history_notes or []),
        edge_notes=list(edge_notes or []),
        candidates=rows,
        selected_candidate_id=selected.candidate_id if selected is not None else None,
        promoted_candidate_ids=(
            [selected.candidate_id] if selected is not None and selected.promoted else []
        ),
        any_promoted=bool(selected is not None and selected.promoted),
        honesty=honesty,
        allowed_promote_id=(
            selected.candidate_id if selected is not None and selected.promoted else None
        ),
    )


def render_search_markdown(report: StrategySearchReport) -> str:
    lines: list[str] = [
        "# Strategy search report",
        "",
        f"Generated: {report.generated_at.isoformat()}",
        f"Symbols: {', '.join(report.symbols)}",
        (
            f"Costs: fee={report.fee_bps:g} bps + slippage={report.slippage_bps:g} bps "
            f"({report.cost_note})"
        ),
        (
            f"Walk-forward: train={report.train_size} test={report.test_size} "
            f"step={report.step_size} warmup={report.warmup}; "
            f"holdout_fraction={report.holdout_fraction:.0%}"
        ),
        (
            f"Promotion floor: WF total > {report.min_wf_total_return:g} "
            f"(require_wf_total={report.require_wf_total_return}), "
            f"WF excess > {report.min_wf_excess_return:g}, "
            f"min trades={report.min_trades}, "
            f"holdout confirmation={'on' if report.require_holdout_confirmation else 'off'}"
        ),
        f"Selection: {report.selection_rule} (K={report.multiple_testing.get('n_candidates')})",
        "",
        "## Honesty",
        "",
        report.honesty,
        "",
        "## Multiple testing",
        "",
        str(report.multiple_testing.get("bonferroni", "")),
        "",
        "## Ranked candidates (walk-forward mean excess after fees)",
        "",
        "| rank | id | family | WF excess | WF total | WF trades | holdout excess | eligible | promoted |",
        "| ---: | --- | --- | ---: | ---: | ---: | ---: | --- | --- |",
    ]

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
            f"| {rank} | `{row.candidate_id}` | {row.family} | {wf_x} | {wf_t} | "
            f"{row.total_wf_trades} | {ho_x} | "
            f"{'yes' if row.eligible else 'no'} | {'yes' if row.promoted else 'no'} |"
        )

    if report.history_notes:
        lines.extend(["", "## History sources", ""])
        for item in report.history_notes:
            detail = item.get("note") or item.get("reason") or ""
            lines.append(
                f"- `{item.get('symbol', '?')}` {item.get('interval', '')} "
                f"source={item.get('source', '?')} n={item.get('candles', item.get('candle_count', '?'))}"
                + (f" — {detail}" if detail else "")
            )

    if report.edge_notes:
        lines.extend(["", "## Edge series", ""])
        for item in report.edge_notes:
            lines.append(
                f"- `{item.get('name', '?')}` {item.get('status', '?')}: "
                f"{item.get('reason', '')} (source={item.get('source', '')}, "
                f"points={item.get('points', '0')})"
            )

    if report.skipped_feature_families:
        lines.extend(["", "## Skipped optional families", ""])
        for item in report.skipped_feature_families:
            lines.append(f"- `{item['candidate_id']}` ({item['family']}): {item['reason']}")

    lines.extend(["", "## Promotion decision", ""])
    if report.any_promoted:
        lines.append(
            "Promoted (may register as paper voters if "
            f"`PAPER_PROMOTE_SEARCHED_STRATEGIES=true` **and** "
            f"`PAPER_PROMOTE_SEARCHED_STRATEGY_ID` is exactly "
            f"`{report.allowed_promote_id}`): {', '.join(report.promoted_candidate_ids)}"
        )
    else:
        lines.append(
            "**No candidate cleared the bar.** Leave "
            "`PAPER_PROMOTE_SEARCHED_STRATEGIES=false`. This is not an edge."
        )
        if report.selected_candidate_id:
            selected = next(
                row for row in report.candidates if row.candidate_id == report.selected_candidate_id
            )
            wf = (
                f"{selected.mean_wf_excess_return:+.2%}"
                if selected.mean_wf_excess_return is not None
                else "n/a"
            )
            ho = (
                f"{selected.mean_holdout_excess_return:+.2%}"
                if selected.mean_holdout_excess_return is not None
                else "n/a"
            )
            reasons = ", ".join(selected.ineligible_reasons) or "n/a"
            lines.append(
                f"Pre-registered top-1 by WF excess was `{selected.candidate_id}` "
                f"(WF excess={wf}, holdout excess={ho}; blocked by: {reasons})."
            )
    lines.append("")
    return "\n".join(lines)
