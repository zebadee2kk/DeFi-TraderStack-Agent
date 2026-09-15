"""Daily robustness search: Kraken daily + balanced-holdout promotion bar.

Honesty rules (also written into every report):

* Kraken public Spot OHLC is capped at 720 committed bars (~2y daily).
  ``since`` pages forward only. That is the promotion window.
* Yahoo Finance daily (yfinance-compatible) is an optional longer A/B and
  is labeled non-Kraken. It never enters the promotion average.
* Costs are ``max(PRETRADE_FEE_BPS, PAPER_FEE_BPS)`` plus
  ``PRETRADE_SLIPPAGE_BPS``. There is no zero-fee ranking path.
* Ranking uses only the Kraken BTC/USD + ETH/USD research prefix.
  SOL/USD is supporting. Yahoo is A/B only.
* The #95 multi-asset bar required BTC **and** ETH walk-forward total
  return > 0, plus holdout **mean** excess > 0. That still lets an ETH
  tail carry a losing BTC holdout.
* The balanced-holdout bar (default) keeps #95 **and** requires BTC
  holdout excess > 0 **and** ETH holdout excess > 0. SOL is reported
  but is not a promotion gate.
* Selection is pre-registered top-1. If #1 fails the bar we do not
  promote #2.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from traderstack.candles import Candle
from traderstack.research.daily_candidates import (
    BALANCED_HOLDOUT_GRID_NOTE,
    default_balanced_holdout_candidates,
    default_daily_robustness_candidates,
)
from traderstack.research.miles_candidates import SearchCandidate
from traderstack.research.miles_search import (
    CandidateSearchResult,
    SeriesCandidateMetrics,
    evaluate_candidate_on_series,
)
from traderstack.signal_registry import version_of

DEFAULT_HOLDOUT_FRACTION = 0.20
DEFAULT_MIN_TRADES = 3
SELECTION_RULE = "pre_registered_top1"
PROMOTION_ASSETS = ("BTC/USD", "ETH/USD")
KRAKEN_PUBLIC_OHLC_MAX_BARS = 720
KRAKEN_DAILY_CAP_NOTE = (
    "Kraken public Spot OHLC (`GET /0/public/OHLC`) returns at most 720 of the "
    "most recent committed bars per pair/interval — about two calendar years "
    "of daily. `since` pages forward only; older history cannot be retrieved "
    "from this endpoint. Charts-spot PI_* is a different print (research-only, "
    "often zero volume) and is not used here. Yahoo Finance daily is an "
    "optional longer A/B and is labeled non-Kraken; it is not the paper path."
)


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _base_asset(symbol: str) -> str:
    return symbol.upper()


def is_yahoo_symbol(symbol: str) -> bool:
    return "-" in symbol and "/" not in symbol


def is_promotion_series(row: SeriesCandidateMetrics, *, interval: str = "1d") -> bool:
    """Kraken BTC/USD or ETH/USD on the promotion interval. Yahoo and SOL do not gate."""
    return (
        row.interval == interval
        and not is_yahoo_symbol(row.asset)
        and _base_asset(row.asset) in PROMOTION_ASSETS
    )


def series_for_asset(
    per_series: list[SeriesCandidateMetrics],
    asset: str,
    *,
    interval: str = "1d",
) -> SeriesCandidateMetrics | None:
    wanted = _base_asset(asset)
    for row in per_series:
        if (
            row.interval == interval
            and not is_yahoo_symbol(row.asset)
            and _base_asset(row.asset) == wanted
        ):
            return row
    return None


# --- era prints / DSR / PBO (#135) ---
# Moved down from harder_gates: it sits with its siblings
# (series_for_asset, is_yahoo_symbol) so miles_search can reuse the one
# implementation instead of importing a higher layer or copying it.
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


def _holdout_excess(row: SeriesCandidateMetrics | None) -> float | None:
    if row is None or row.holdout is None:
        return None
    return row.holdout.excess_return


def _gate_reasons(
    row: CandidateSearchResult,
    *,
    min_trades: int,
    require_balanced_holdout: bool,
    promotion_interval: str = "1d",
) -> list[str]:
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
    btc = series_for_asset(row.per_series, "BTC/USD", interval=promotion_interval)
    eth = series_for_asset(row.per_series, "ETH/USD", interval=promotion_interval)
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
    if require_balanced_holdout:
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
    return reasons


class DailyRobustnessReport(BaseModel):
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
    selection_rule: str
    multiple_testing: dict[str, Any]
    promotion_assets: list[str]
    kraken_cap_note: str
    candidates: list[CandidateSearchResult]
    selected_candidate_id: str | None = None
    promoted_candidate_ids: list[str] = Field(default_factory=list)
    any_promoted: bool = False
    recommended_promote_flag: str | None = None
    recommended_promote_id: str | None = None
    require_balanced_holdout: bool = True
    catalog_name: str = "balanced"
    catalog_note: str = ""
    ema_9_21_clears_multi_asset: bool = False
    ema_9_21_clears_balanced_holdout: bool = False
    honesty: str
    data_notes: list[str] = Field(default_factory=list)


def _wf_worst_drawdown(row: SeriesCandidateMetrics) -> float | None:
    if row.walkforward is None:
        return None
    return row.walkforward.worst_drawdown


def _holdout_max_drawdown(row: SeriesCandidateMetrics) -> float | None:
    if row.holdout is None:
        return None
    return row.holdout.max_drawdown


def _kraken_btc_daily(histories: dict[str, tuple[Candle, ...]]) -> tuple[Candle, ...] | None:
    for candles in histories.values():
        if (
            candles
            and candles[0].interval == "1d"
            and candles[0].symbol == "BTC/USD"
            and not is_yahoo_symbol(candles[0].symbol)
        ):
            return candles
    return None


def run_daily_robustness(
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
    catalog_name: str = "balanced",
    require_balanced_holdout: bool = True,
    now: datetime | None = None,
    data_notes: list[str] | None = None,
    promotion_interval: str = "1d",
) -> DailyRobustnessReport:
    if not histories:
        raise ValueError("no candle histories provided")
    if candidates is not None:
        catalog = list(candidates)
        resolved_catalog = "custom"
        catalog_note = "Caller-supplied catalog."
    elif catalog_name == "legacy":
        catalog = list(default_daily_robustness_candidates())
        resolved_catalog = "legacy"
        catalog_note = "Frozen #95 daily-robustness catalog (K=8)."
    else:
        overlay = _kraken_btc_daily(histories)
        catalog = list(default_balanced_holdout_candidates(btc_overlay=overlay))
        resolved_catalog = "balanced"
        catalog_note = BALANCED_HOLDOUT_GRID_NOTE
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
                garch_min_train=120,
                garch_refit_every=21,
                garch_target_vol_ann=0.50,
            )
            for candles in histories.values()
        ]
        gated = [row for row in per_series if is_promotion_series(row, interval=promotion_interval)]
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
        result.ineligible_reasons = _gate_reasons(
            result,
            min_trades=min_trades,
            require_balanced_holdout=require_balanced_holdout,
            promotion_interval=promotion_interval,
        )
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

    ema_row = next((row for row in rows if row.candidate_id == "ema_9_21"), None)
    ema_clears_legacy = False
    ema_clears_balanced = False
    if ema_row is not None:
        ema_clears_legacy = not _gate_reasons(
            ema_row,
            min_trades=min_trades,
            require_balanced_holdout=False,
            promotion_interval=promotion_interval,
        )
        ema_clears_balanced = not _gate_reasons(
            ema_row,
            min_trades=min_trades,
            require_balanced_holdout=True,
            promotion_interval=promotion_interval,
        )
    promoted_ids = [selected.candidate_id] if selected is not None and selected.promoted else []
    recommend_flag: str | None = None
    recommend_id: str | None = None
    if promoted_ids:
        recommend_id = promoted_ids[0]
        if recommend_id == "ema_9_21":
            recommend_flag = "PAPER_PROMOTE_EMA_9_21"
        else:
            recommend_flag = "PAPER_PROMOTE_SEARCHED_STRATEGY_ID"

    count = len(catalog)
    bar_name = (
        "balanced-holdout bar (BTC and ETH WF total > 0 **and** BTC and ETH "
        "holdout excess > 0, plus mean holdout excess > 0 and min trades)"
        if require_balanced_holdout
        else "multi-asset bar (BTC and ETH WF total > 0 plus holdout mean excess > 0)"
    )
    honesty = (
        "No candidate is rewritten to look profitable. "
        "Walk-forward ranking never sees the holdout tail. "
        f"Selection is pre-registered top-1 of {count} daily-robustness "
        "catalog members. Promotion uses Kraken daily BTC/USD and ETH/USD "
        "only. The #95 bar required both walk-forward totals > 0 and a "
        "positive **mean** holdout excess — an ETH tail could still carry "
        "that mean. The balanced-holdout bar additionally requires BTC "
        "holdout excess > 0 **and** ETH holdout excess > 0 so one asset "
        "cannot hide a losing holdout. SOL/USD is supporting and is not "
        "required to promote. Yahoo Finance daily is a longer non-Kraken "
        "A/B and cannot promote. Positive excess with a negative total "
        "return is not an edge. A large ETH holdout on a two-year window "
        "is one tail, not a live-capital claim. "
        f"This run's promotion decision uses the {bar_name}."
    )
    if ema_row is not None:
        honesty += (
            f" ema_9_21 #95 multi-asset bar: "
            f"{'PASS' if ema_clears_legacy else 'FAIL'}. "
            f"ema_9_21 balanced-holdout bar: "
            f"{'PASS' if ema_clears_balanced else 'FAIL'}."
        )
    if selected is None or not selected.promoted:
        honesty += (
            " No candidate cleared the promotion bar on this Kraken daily "
            "window; paper promotion must stay off."
        )
    elif selected.candidate_id == "ema_9_21":
        honesty += (
            " ema_9_21 cleared this run's promotion bar. That does not "
            "flip PAPER_PROMOTE_EMA_9_21 (default false) and does not "
            "enable live."
        )
    else:
        honesty += (
            f" A candidate other than ema_9_21 cleared ({selected.candidate_id}). "
            "Document the paper-only id; do not enable live; leave "
            "PAPER_GARCH_SIZE false unless that id is a GARCH variant "
            "and the operator explicitly pins it."
        )

    symbols = sorted({candles[0].symbol for candles in histories.values() if candles})
    intervals = sorted({candles[0].interval for candles in histories.values() if candles})
    return DailyRobustnessReport(
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
        selection_rule=SELECTION_RULE,
        multiple_testing={
            "method": SELECTION_RULE,
            "n_candidates": count,
            "catalog": resolved_catalog,
            "require_balanced_holdout": require_balanced_holdout,
            "bonferroni": (
                "K catalog members are scored on the same Kraken BTC/ETH daily "
                "research window. At most the single pre-registered top-1 "
                "(by walk-forward mean total return on BTC+ETH, min-trades "
                "filter) may be promoted, and only if BTC and ETH both have "
                "WF total > 0"
                + (
                    ", BTC holdout excess > 0, ETH holdout excess > 0, and holdout mean excess > 0"
                    if require_balanced_holdout
                    else " and holdout mean excess > 0"
                )
                + ". "
                f"A classical Bonferroni p-cut would be 0.05/{count} ≈ "
                f"{0.05 / max(count, 1):.4f}; this search has no per-fold "
                "t-test, so per-asset holdout confirmation is the "
                "out-of-sample control."
            ),
        },
        promotion_assets=list(PROMOTION_ASSETS),
        kraken_cap_note=KRAKEN_DAILY_CAP_NOTE,
        candidates=rows,
        selected_candidate_id=selected.candidate_id if selected is not None else None,
        promoted_candidate_ids=promoted_ids,
        any_promoted=bool(selected is not None and selected.promoted),
        recommended_promote_flag=recommend_flag,
        recommended_promote_id=recommend_id,
        require_balanced_holdout=require_balanced_holdout,
        catalog_name=resolved_catalog,
        catalog_note=catalog_note,
        ema_9_21_clears_multi_asset=ema_clears_legacy,
        ema_9_21_clears_balanced_holdout=ema_clears_balanced,
        honesty=honesty,
        data_notes=list(data_notes or []),
    )


def _pct(value: float | None) -> str:
    return f"{value:+.2%}" if value is not None else "n/a"


def _series_drawdowns(row: CandidateSearchResult) -> tuple[float | None, float | None]:
    gated = [series for series in row.per_series if is_promotion_series(series)]
    wf_dd = [dd for dd in (_wf_worst_drawdown(series) for series in gated) if dd is not None]
    ho_dd = [dd for dd in (_holdout_max_drawdown(series) for series in gated) if dd is not None]
    return _mean(wf_dd), _mean(ho_dd)


def render_daily_robustness_markdown(report: DailyRobustnessReport) -> str:
    lines: list[str] = [
        "# Daily robustness report",
        "",
        f"Generated: {report.generated_at.isoformat()}",
        f"Symbols: {', '.join(report.symbols)}",
        f"Intervals: {', '.join(report.intervals)} (promotion uses Kraken 1d BTC+ETH only)",
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
            "Promotion floor: **BTC and ETH** Kraken daily WF mean total_return > 0"
            + (
                ", **BTC holdout excess > 0 and ETH holdout excess > 0** "
                "(balanced holdout — ETH cannot carry a losing BTC tail)"
                if report.require_balanced_holdout
                else ""
            )
            + f", holdout mean excess_return > 0 after fees, min trades="
            f"{report.min_trades}. SOL is supporting (not required). "
            "Yahoo is non-Kraken A/B and never enters the promotion average."
        ),
        (
            f"Selection: {report.selection_rule} "
            f"(K={report.multiple_testing.get('n_candidates')}, "
            f"catalog={report.catalog_name})"
        ),
        "",
        "## Honesty",
        "",
        report.honesty,
        "",
        "## Multiple testing",
        "",
        str(report.multiple_testing.get("bonferroni", "")),
        "",
        "## Pre-registered catalog",
        "",
        report.catalog_note or "See `default_balanced_holdout_candidates`.",
        "",
        "## Kraken public OHLC cap",
        "",
        report.kraken_cap_note,
        "",
    ]
    if report.data_notes:
        lines.extend(["## Data", ""])
        for note in report.data_notes:
            lines.append(f"- {note}")
        lines.append("")
    lines.extend(
        [
            "## Ranked candidates (Kraken BTC+ETH daily, walk-forward mean total after fees)",
            "",
            "| rank | id | family | WF total | WF excess | WF trades | WF maxDD | holdout excess | holdout maxDD | BTC WF | ETH WF | BTC holdout | ETH holdout | eligible | promoted |",
            "| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |",
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
        btc = series_for_asset(row.per_series, "BTC/USD")
        eth = series_for_asset(row.per_series, "ETH/USD")
        wf_dd, ho_dd = _series_drawdowns(row)
        rank = str(row.rank) if row.rank is not None else "—"
        lines.append(
            f"| {rank} | `{row.candidate_id}` | {row.family} | "
            f"{_pct(row.mean_wf_total_return)} | {_pct(row.mean_wf_excess_return)} | "
            f"{row.total_wf_trades} | {_pct(wf_dd)} | "
            f"{_pct(row.mean_holdout_excess_return)} | {_pct(ho_dd)} | "
            f"{_pct(btc.walkforward_mean_total_return if btc else None)} | "
            f"{_pct(eth.walkforward_mean_total_return if eth else None)} | "
            f"{_pct(_holdout_excess(btc))} | {_pct(_holdout_excess(eth))} | "
            f"{'yes' if row.eligible else 'no'} | {'yes' if row.promoted else 'no'} |"
        )

    lines.extend(["", "## Per-series detail", ""])
    for row in ordered:
        lines.append(f"### `{row.candidate_id}` — {row.label}")
        lines.append("")
        lines.append(
            "| series | source | bars | WF total | WF excess | WF trades | WF maxDD | "
            "holdout excess | holdout total | holdout trades | holdout maxDD |"
        )
        lines.append("| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
        for series in row.per_series:
            source = "yahoo (non-Kraken)" if is_yahoo_symbol(series.asset) else "kraken"
            name = f"{series.asset} {series.interval}"
            holdout_excess = "n/a"
            holdout_total = "n/a"
            holdout_trades = "n/a"
            holdout_dd = "n/a"
            if series.holdout is not None:
                holdout_excess = _pct(series.holdout.excess_return)
                holdout_total = _pct(series.holdout.total_return)
                holdout_trades = str(series.holdout.trades)
                holdout_dd = _pct(series.holdout.max_drawdown)
            skip = f" ({series.skipped_reason})" if series.skipped_reason else ""
            lines.append(
                f"| {name}{skip} | {source} | {series.candle_count} | "
                f"{_pct(series.walkforward_mean_total_return)} | "
                f"{_pct(series.walkforward_mean_excess_return)} | "
                f"{series.walkforward_trades} | {_pct(_wf_worst_drawdown(series))} | "
                f"{holdout_excess} | {holdout_total} | {holdout_trades} | {holdout_dd} |"
            )
        if row.ineligible_reasons:
            lines.append("")
            lines.append("Blocked by: " + ", ".join(row.ineligible_reasons))
        lines.append("")

    ema = next((row for row in report.candidates if row.candidate_id == "ema_9_21"), None)
    if ema is not None:
        btc = series_for_asset(ema.per_series, "BTC/USD")
        eth = series_for_asset(ema.per_series, "ETH/USD")
        if (
            btc is not None
            and eth is not None
            and btc.holdout is not None
            and eth.holdout is not None
        ):
            balanced_verdict = "PASS" if report.ema_9_21_clears_balanced_holdout else "FAIL"
            legacy_verdict = "PASS" if report.ema_9_21_clears_multi_asset else "FAIL"
            lines.extend(
                [
                    "## Holdout concentration (honesty)",
                    "",
                    (
                        f"`ema_9_21` Kraken holdout excess: "
                        f"BTC {_pct(btc.holdout.excess_return)} vs ETH "
                        f"{_pct(eth.holdout.excess_return)}. "
                        f"#95 multi-asset bar (WF both > 0, mean holdout > 0): "
                        f"**{legacy_verdict}**. "
                        f"Balanced-holdout bar (also BTC holdout > 0 **and** "
                        f"ETH holdout > 0): **{balanced_verdict}**. "
                        "Magnitude skew is reported, not gated — both signs "
                        "must be positive, but ETH can still be much larger. "
                        "A +50% ETH tail on one ~144-day window is not a "
                        "live-capital claim."
                    ),
                    "",
                ]
            )

    yahoo_rows = [
        series
        for row in report.candidates
        if row.candidate_id == "ema_9_21"
        for series in row.per_series
        if is_yahoo_symbol(series.asset)
    ]
    if yahoo_rows:
        lines.extend(["## Yahoo Finance A/B (non-Kraken, not promotion)", ""])
        lines.append(
            "Yahoo `range=max` downsamples crypto to monthly; this A/B uses "
            "`period1`/`period2` so the series stays daily. High/low are "
            "expanded to contain open/close when Yahoo's print is inconsistent. "
            "Closes are not Kraken Spot. This block cannot promote."
        )
        lines.append("")
        for series in yahoo_rows:
            wf = _pct(series.walkforward_mean_total_return)
            ho = _pct(series.holdout.excess_return) if series.holdout is not None else "n/a"
            lines.append(
                f"- `{series.asset}` {series.candle_count} bars: WF total {wf}, "
                f"holdout excess {ho}"
                + (f" ({series.skipped_reason})" if series.skipped_reason else "")
            )
        lines.append("")

    lines.extend(["## Promotion decision", ""])
    lines.append(
        f"`ema_9_21` #95 multi-asset bar: "
        f"**{'PASS' if report.ema_9_21_clears_multi_asset else 'FAIL'}**. "
        f"`ema_9_21` balanced-holdout bar: "
        f"**{'PASS' if report.ema_9_21_clears_balanced_holdout else 'FAIL'}**."
    )
    if report.any_promoted:
        lines.append(
            "Cleared the balanced-holdout bar on Kraken daily BTC+ETH "
            f"(research only): `{report.recommended_promote_id}`."
        )
        if report.recommended_promote_flag == "PAPER_PROMOTE_EMA_9_21":
            lines.append(
                "Documented paper-only switch: `PAPER_PROMOTE_EMA_9_21=true` "
                "(default false; `TRADING_MODE=paper` only). This report does "
                "not flip that flag and does not enable live."
            )
        else:
            garch_note = ""
            promoted = next(
                row
                for row in report.candidates
                if row.candidate_id == report.recommended_promote_id
            )
            if promoted.family == "ema_cross_garch":
                garch_note = (
                    " Leave `PAPER_GARCH_SIZE=false` until an operator "
                    "explicitly reviews this GARCH-sized pin; RiskEngine "
                    "may only reduce notional."
                )
            lines.append(
                f"Documented paper-only pin: `{report.recommended_promote_flag}="
                f"{report.recommended_promote_id}`. Leave "
                "`PAPER_PROMOTE_SEARCHED_STRATEGIES=false` and "
                "`PAPER_PROMOTE_EMA_9_21=false` until an operator reviews "
                f"this report.{garch_note} This is not a live-capital claim."
            )
    else:
        lines.append(
            "**No candidate cleared the balanced-holdout bar.** "
            "ETH-only holdout tails cannot carry promotion. Leave "
            "`PAPER_PROMOTE_EMA_9_21=false` and "
            "`PAPER_PROMOTE_SEARCHED_STRATEGIES=false`. "
            "Finding no promotee is a successful research outcome."
        )
        if report.selected_candidate_id:
            selected = next(
                row for row in report.candidates if row.candidate_id == report.selected_candidate_id
            )
            reasons = ", ".join(selected.ineligible_reasons) or "n/a"
            btc = series_for_asset(selected.per_series, "BTC/USD")
            eth = series_for_asset(selected.per_series, "ETH/USD")
            lines.append(
                f"Pre-registered top-1 by BTC+ETH WF total was "
                f"`{selected.candidate_id}` "
                f"(WF total={_pct(selected.mean_wf_total_return)}, "
                f"holdout excess={_pct(selected.mean_holdout_excess_return)}, "
                f"BTC holdout={_pct(_holdout_excess(btc))}, "
                f"ETH holdout={_pct(_holdout_excess(eth))}; "
                f"blocked by: {reasons})."
            )
        if not report.ema_9_21_clears_balanced_holdout:
            lines.append("`ema_9_21` does **not** clear the balanced-holdout bar on this window.")
    lines.append("")
    lines.append(
        "Yahoo rows above are a longer non-Kraken A/B. Do not average them "
        "with Kraken prints. Do not copy YouTube or Yahoo-backtest return figures."
    )
    lines.append("")
    return "\n".join(lines)
