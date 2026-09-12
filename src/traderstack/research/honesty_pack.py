"""Focused honesty pack for one harder-gates combined-passer.

Reprints the Kraken combined A/B/C row (is it still top-1?), scores
Yahoo Finance daily A/B for **that** id only (``period1``/``period2``,
labeled non-Kraken, cannot promote), and compares walk-forward max
drawdown on BTC/ETH/SOL against the paper DD ceiling
(``PAPER_PROMOTE_EMA_9_21_MAX_DRAWDOWN_PCT``, default 0.30).

This module never flips ``PAPER_PROMOTE_EMA_9_21_ADX15`` or
``PAPER_PROMOTE_EMA_9_21``. Empty or negative Yahoo is success.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field

from traderstack.candles import Candle
from traderstack.config import EMA_9_21_PAPER_MAX_DRAWDOWN_PCT
from traderstack.research.daily_robustness import (
    KRAKEN_DAILY_CAP_NOTE,
    _holdout_excess,
    _holdout_max_drawdown,
    _wf_worst_drawdown,
    is_yahoo_symbol,
    run_daily_robustness,
)
from traderstack.research.harder_gates import (
    MULTIWINDOW_BARS,
    MULTIWINDOW_COUNT,
    MULTIWINDOW_MIN_PASSES,
    RANKING_KEY,
    WindowScore,
    _catalog_for,
    _pct,
    _ratio,
    _verdict,
    paper_promote_flag_name,
    run_harder_gates,
)
from traderstack.research.miles_candidates import SearchCandidate
from traderstack.research.miles_search import SeriesCandidateMetrics
from traderstack.research.yahoo_daily import YAHOO_PERIOD1_ISO, YAHOO_PERIOD1_UNIX

DEFAULT_CANDIDATE_ID = "ema_9_21_adx15"
DEFAULT_PROMOTE_FLAG = "PAPER_PROMOTE_EMA_9_21_ADX15"
PAPER_DD_CEILING = EMA_9_21_PAPER_MAX_DRAWDOWN_PCT
KRAKEN_DD_ASSETS = ("BTC/USD", "ETH/USD", "SOL/USD")


def honesty_md_name(candidate_id: str) -> str:
    return candidate_id.replace("_", "-") + "-honesty.md"


def kraken_only_histories(
    histories: dict[str, tuple[Candle, ...]],
) -> dict[str, tuple[Candle, ...]]:
    """Yahoo never enters ranking, magnitude, multi-window, or fee stress."""
    return {
        key: candles
        for key, candles in histories.items()
        if candles and not is_yahoo_symbol(candles[0].symbol)
    }


def _sign(value: float | None) -> str:
    if value is None:
        return "n/a"
    if value > 0:
        return "+"
    if value < 0:
        return "−"
    return "0"


def _span(histories: dict[str, tuple[Candle, ...]], asset: str) -> tuple[str | None, str | None]:
    wanted = asset.upper()
    for candles in histories.values():
        if candles and candles[0].symbol.upper() == wanted:
            return candles[0].opened_at.isoformat(), candles[-1].opened_at.isoformat()
    return None, None


class SeriesHonestyRow(BaseModel):
    asset: str
    interval: str = "1d"
    source: str
    bars: int
    first: str | None = None
    last: str | None = None
    wf_total: float | None = None
    wf_excess: float | None = None
    wf_max_drawdown: float | None = None
    holdout_excess: float | None = None
    holdout_total: float | None = None
    holdout_max_drawdown: float | None = None
    wf_total_sign: str = "n/a"
    wf_excess_sign: str = "n/a"
    holdout_excess_sign: str = "n/a"
    blows_past_dd_ceiling: bool | None = None
    skipped_reason: str | None = None


class HonestyPackReport(BaseModel):
    generated_at: datetime
    candidate_id: str
    promote_flag: str
    paper_dd_ceiling: float
    ranking_key: str
    catalog_name: str
    fee_bps: float
    slippage_bps: float
    train_size: int
    test_size: int
    step_size: int
    holdout_fraction: float
    min_trades: int
    yahoo_period1_unix: int
    yahoo_period1_iso: str
    yahoo_period2_unix: int | None = None
    still_combined_pass: bool = False
    still_combined_top1: bool = False
    combined_rank: int | None = None
    wf_rank: int | None = None
    mean_holdout_excess: float | None = None
    baseline_wf_total: float | None = None
    baseline_btc_wf: float | None = None
    baseline_eth_wf: float | None = None
    baseline_btc_holdout: float | None = None
    baseline_eth_holdout: float | None = None
    holdout_magnitude_ratio: float | None = None
    gate_a_pass: bool = False
    gate_b_pass: bool = False
    gate_c_pass: bool = False
    eligible_96: bool = False
    windows: list[WindowScore] = Field(default_factory=list)
    windows_passed: int = 0
    combined_passer_ids: list[str] = Field(default_factory=list)
    selected_candidate_id: str | None = None
    yahoo_rows: list[SeriesHonestyRow] = Field(default_factory=list)
    kraken_dd_rows: list[SeriesHonestyRow] = Field(default_factory=list)
    sol_blows_past_ceiling: bool | None = None
    remaining_gaps: list[str] = Field(default_factory=list)
    keep_flag_false: bool = True
    honesty: str
    recommendation: str
    data_notes: list[str] = Field(default_factory=list)
    kraken_cap_note: str = KRAKEN_DAILY_CAP_NOTE


def _row_from_series(
    series: SeriesCandidateMetrics,
    *,
    histories: dict[str, tuple[Candle, ...]],
    ceiling: float,
) -> SeriesHonestyRow:
    first, last = _span(histories, series.asset)
    wf_dd = _wf_worst_drawdown(series)
    ho_dd = _holdout_max_drawdown(series)
    ho = _holdout_excess(series)
    yahoo = is_yahoo_symbol(series.asset)
    blows: bool | None
    if yahoo or wf_dd is None:
        blows = None
    else:
        blows = wf_dd > ceiling
    return SeriesHonestyRow(
        asset=series.asset,
        interval=series.interval,
        source="yahoo (non-Kraken)" if yahoo else "kraken",
        bars=series.candle_count,
        first=first,
        last=last,
        wf_total=series.walkforward_mean_total_return,
        wf_excess=series.walkforward_mean_excess_return,
        wf_max_drawdown=wf_dd,
        holdout_excess=ho,
        holdout_total=series.holdout.total_return if series.holdout is not None else None,
        holdout_max_drawdown=ho_dd,
        wf_total_sign=_sign(series.walkforward_mean_total_return),
        wf_excess_sign=_sign(series.walkforward_mean_excess_return),
        holdout_excess_sign=_sign(ho),
        blows_past_dd_ceiling=blows,
        skipped_reason=series.skipped_reason,
    )


def remaining_gaps(
    *,
    candidate_id: str,
    promote_flag: str,
    still_combined_pass: bool,
    still_combined_top1: bool,
    yahoo_rows: list[SeriesHonestyRow],
    kraken_dd_rows: list[SeriesHonestyRow],
    paper_dd_ceiling: float,
    yahoo_fetch_failed: bool,
) -> list[str]:
    """Operator gaps that keep the paper pin default-false.

    Pre-registered: do not drop a gap after seeing a pretty Kraken print.
    """
    gaps: list[str] = [
        (
            "Single 720-bar Kraken public Spot daily window "
            "(~2y; `since` cannot unlock older prints). One combined-passer "
            "top-1 is not a second independent venue or era."
        ),
        (
            "Yahoo Finance daily is labeled non-Kraken and cannot enter "
            "ranking, magnitude, multi-window, or fee-stress averages even "
            "if both signs are positive."
        ),
    ]
    if not still_combined_pass:
        gaps.append(
            f"`{candidate_id}` no longer clears combined (#96 + A + B + C) on this reprint."
        )
    elif not still_combined_top1:
        gaps.append(
            f"`{candidate_id}` still combined-passes but is no longer top-1 by `{RANKING_KEY}`."
        )
    if yahoo_fetch_failed or not yahoo_rows:
        gaps.append(
            "Yahoo Finance A/B missing or failed. An empty Yahoo print is "
            "success; it is not treated as confirmation."
        )
    for row in yahoo_rows:
        if row.wf_total is not None and row.wf_total <= 0:
            gaps.append(
                f"Yahoo `{row.asset}` walk-forward total is {_pct(row.wf_total)} "
                "(non-Kraken A/B; cannot promote)."
            )
        if row.wf_excess is not None and row.wf_excess <= 0:
            gaps.append(
                f"Yahoo `{row.asset}` walk-forward excess is {_pct(row.wf_excess)} "
                "(non-Kraken A/B; cannot promote)."
            )
        if row.holdout_excess is not None and row.holdout_excess <= 0:
            gaps.append(
                f"Yahoo `{row.asset}` holdout excess is {_pct(row.holdout_excess)} "
                "(non-Kraken A/B; cannot promote)."
            )
        if row.skipped_reason:
            gaps.append(
                f"Yahoo `{row.asset}` skipped: {row.skipped_reason} "
                "(non-Kraken A/B; cannot promote)."
            )
    for row in kraken_dd_rows:
        if row.wf_max_drawdown is None:
            gaps.append(f"Kraken `{row.asset}` walk-forward maxDD missing.")
            continue
        if row.blows_past_dd_ceiling:
            extra = ""
            if row.asset.upper() == "SOL/USD":
                extra = (
                    " SOL is in `mvp_assets` but the #98 paper DD envelope "
                    "is BTC+ETH only; a SOL cycle on the promote path can "
                    "hit `backtest_drawdown_above_maximum`."
                )
            gaps.append(
                f"Kraken `{row.asset}` WF maxDD {_pct(row.wf_max_drawdown)} "
                f"exceeds paper DD ceiling {paper_dd_ceiling:.0%}.{extra}"
            )
    gaps.append(
        f"`{promote_flag}` stays default **false**. This pack does not "
        "enable live and does not flip `PAPER_PROMOTE_EMA_9_21`."
    )
    return gaps


def _recommendation(promote_flag: str, gaps: list[str]) -> str:
    bullets = "\n".join(f"- {gap}" for gap in gaps)
    return (
        f"**Keep `{promote_flag}=false`** until the remaining gaps below "
        "are closed or an operator explicitly accepts them as residual "
        "research risk. This is not a live-capital claim and not a "
        "YouTube / Yahoo PnL copy.\n\n"
        f"{bullets}"
    )


def run_honesty_pack(
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
    candidate_id: str = DEFAULT_CANDIDATE_ID,
    candidates: tuple[SearchCandidate, ...] | None = None,
    catalog_name: str = "expanded",
    paper_dd_ceiling: float = PAPER_DD_CEILING,
    now: datetime | None = None,
    data_notes: list[str] | None = None,
) -> HonestyPackReport:
    if not histories:
        raise ValueError("no candle histories provided")
    catalog, resolved_catalog, _catalog_note = _catalog_for(
        histories, candidates=candidates, catalog_name=catalog_name
    )
    target = next((item for item in catalog if item.candidate_id == candidate_id), None)
    if target is None:
        raise ValueError(f"{candidate_id} is not in the {resolved_catalog} harder-gates catalog")

    generated = now or datetime.now(UTC)
    kraken_histories = kraken_only_histories(histories)
    harder = run_harder_gates(
        kraken_histories,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
        starting_equity=starting_equity,
        train_size=train_size,
        test_size=test_size,
        step_size=step_size,
        holdout_fraction=holdout_fraction,
        min_trades=min_trades,
        candidates=candidates,
        catalog_name=catalog_name,
        now=generated,
        data_notes=data_notes,
    )
    detail = run_daily_robustness(
        histories,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
        starting_equity=starting_equity,
        train_size=train_size,
        test_size=test_size,
        step_size=step_size,
        holdout_fraction=holdout_fraction,
        min_trades=min_trades,
        candidates=(target,),
        catalog_name="custom",
        require_balanced_holdout=True,
        now=generated,
        data_notes=data_notes,
    )
    harder_row = next(row for row in harder.candidates if row.candidate_id == candidate_id)
    detail_row = next(row for row in detail.candidates if row.candidate_id == candidate_id)
    yahoo_rows = [
        _row_from_series(series, histories=histories, ceiling=paper_dd_ceiling)
        for series in detail_row.per_series
        if is_yahoo_symbol(series.asset)
    ]
    yahoo_rows.sort(key=lambda row: row.asset)
    kraken_dd_rows = [
        _row_from_series(series, histories=histories, ceiling=paper_dd_ceiling)
        for series in detail_row.per_series
        if not is_yahoo_symbol(series.asset)
        and series.asset.upper() in {item.upper() for item in KRAKEN_DD_ASSETS}
    ]
    kraken_dd_rows.sort(
        key=lambda row: KRAKEN_DD_ASSETS.index(row.asset) if row.asset in KRAKEN_DD_ASSETS else 99
    )
    sol = next((row for row in kraken_dd_rows if row.asset.upper() == "SOL/USD"), None)
    yahoo_notes = list(data_notes or [])
    yahoo_fetch_failed = not yahoo_rows and any(
        "Yahoo" in note and ("skipped" in note or "no committed" in note) for note in yahoo_notes
    )
    if not yahoo_rows and not yahoo_fetch_failed:
        # Histories simply had no Yahoo series (offline JSON / --no-yahoo).
        yahoo_fetch_failed = not any(
            candles and is_yahoo_symbol(candles[0].symbol) for candles in histories.values()
        )
    flag = paper_promote_flag_name(candidate_id)
    still_top1 = bool(harder_row.promoted and harder_row.combined)
    gaps = remaining_gaps(
        candidate_id=candidate_id,
        promote_flag=flag,
        still_combined_pass=harder_row.combined,
        still_combined_top1=still_top1,
        yahoo_rows=yahoo_rows,
        kraken_dd_rows=kraken_dd_rows,
        paper_dd_ceiling=paper_dd_ceiling,
        yahoo_fetch_failed=yahoo_fetch_failed,
    )
    yahoo_period2: int | None = None
    for candles in histories.values():
        if candles and is_yahoo_symbol(candles[0].symbol):
            yahoo_period2 = int(candles[-1].opened_at.timestamp())
            break

    honesty = (
        f"Honesty pack for `{candidate_id}` only. No candidate is rewritten "
        "to look profitable. Combined ranking uses Kraken BTC+ETH only "
        f"(`{RANKING_KEY}`). Yahoo Finance daily is a longer non-Kraken A/B "
        f"fetched with period1={YAHOO_PERIOD1_UNIX} ({YAHOO_PERIOD1_ISO}) / "
        "period2=now so the series stays daily; `range=max` would downsample "
        "crypto to monthly. Yahoo cannot promote. Empty or negative Yahoo is "
        "a successful research outcome — it is not rewritten as a soft PASS. "
        f"Walk-forward maxDD is compared to the paper ceiling "
        f"{paper_dd_ceiling:.0%} (`PAPER_PROMOTE_EMA_9_21_MAX_DRAWDOWN_PCT`). "
        f"This run does not flip `{flag}` (default false) and does not "
        "enable live."
    )
    if still_top1:
        honesty += (
            f" `{candidate_id}` still clears combined and is still top-1 "
            "among combined-passers on this reprint."
        )
    elif harder_row.combined:
        honesty += (
            f" `{candidate_id}` still combined-passes but is not top-1 "
            f"(combined rank={harder_row.combined_rank})."
        )
    else:
        honesty += f" `{candidate_id}` does not clear combined on this reprint."

    return HonestyPackReport(
        generated_at=generated,
        candidate_id=candidate_id,
        promote_flag=flag,
        paper_dd_ceiling=paper_dd_ceiling,
        ranking_key=harder.ranking_key,
        catalog_name=harder.catalog_name,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
        train_size=train_size,
        test_size=test_size,
        step_size=step_size,
        holdout_fraction=holdout_fraction,
        min_trades=min_trades,
        yahoo_period1_unix=YAHOO_PERIOD1_UNIX,
        yahoo_period1_iso=YAHOO_PERIOD1_ISO,
        yahoo_period2_unix=yahoo_period2,
        still_combined_pass=harder_row.combined,
        still_combined_top1=still_top1,
        combined_rank=harder_row.combined_rank,
        wf_rank=harder_row.wf_rank,
        mean_holdout_excess=harder_row.mean_holdout_excess,
        baseline_wf_total=harder_row.baseline_wf_total,
        baseline_btc_wf=harder_row.baseline_btc_wf,
        baseline_eth_wf=harder_row.baseline_eth_wf,
        baseline_btc_holdout=harder_row.baseline_btc_holdout,
        baseline_eth_holdout=harder_row.baseline_eth_holdout,
        holdout_magnitude_ratio=harder_row.holdout_magnitude_ratio,
        gate_a_pass=harder_row.gate_a_pass,
        gate_b_pass=harder_row.gate_b_pass,
        gate_c_pass=harder_row.gate_c_pass,
        eligible_96=harder_row.eligible_96,
        windows=harder_row.windows,
        windows_passed=harder_row.windows_passed,
        combined_passer_ids=[
            row.candidate_id
            for row in sorted(
                (item for item in harder.candidates if item.combined),
                key=lambda item: (
                    item.combined_rank if item.combined_rank is not None else 10_000,
                    item.candidate_id,
                ),
            )
        ],
        selected_candidate_id=harder.selected_candidate_id,
        yahoo_rows=yahoo_rows,
        kraken_dd_rows=kraken_dd_rows,
        sol_blows_past_ceiling=sol.blows_past_dd_ceiling if sol is not None else None,
        remaining_gaps=gaps,
        keep_flag_false=True,
        honesty=honesty,
        recommendation=_recommendation(flag, gaps),
        data_notes=list(data_notes or []),
        kraken_cap_note=KRAKEN_DAILY_CAP_NOTE,
    )


def _dd_vs_ceiling(value: float | None, ceiling: float) -> str:
    if value is None:
        return "n/a"
    return "over" if value > ceiling else "under"


def render_honesty_pack_markdown(report: HonestyPackReport) -> str:
    period2 = str(report.yahoo_period2_unix) if report.yahoo_period2_unix is not None else "n/a"
    lines: list[str] = [
        f"# `{report.candidate_id}` honesty pack",
        "",
        f"Generated: {report.generated_at.isoformat()}",
        (
            f"Candidate: `{report.candidate_id}` (documented paper pin "
            f"`{report.promote_flag}`, default **false**)"
        ),
        (
            f"Baseline costs: fee={report.fee_bps:g} bps + slippage="
            f"{report.slippage_bps:g} bps. Walk-forward: train="
            f"{report.train_size} test={report.test_size} step="
            f"{report.step_size}; holdout_fraction={report.holdout_fraction:.0%}."
        ),
        (
            f"Catalog: {report.catalog_name}. Ranking key: `{report.ranking_key}`. "
            f"Paper DD ceiling: {report.paper_dd_ceiling:.0%} "
            "(`PAPER_PROMOTE_EMA_9_21_MAX_DRAWDOWN_PCT`)."
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
    ]
    if report.data_notes:
        lines.extend(["## Data", ""])
        for note in report.data_notes:
            lines.append(f"- {note}")
        lines.append("")

    lines.extend(
        [
            "## 1. Kraken combined harder-gates reprint",
            "",
            (
                "Fresh pull of the same pre-registered A/B/C + #96 combined "
                "bar. Yahoo is stripped from this ranking. Confirm whether "
                f"`{report.candidate_id}` is still a combined-passer and "
                "still top-1 among passers."
            ),
            "",
            "| field | value |",
            "| --- | --- |",
            f"| id | `{report.candidate_id}` |",
            f"| #96 balanced-holdout | **{_verdict(report.eligible_96)}** |",
            f"| A Magnitude | **{_verdict(report.gate_a_pass)}** |",
            f"| B Multi-window | **{_verdict(report.gate_b_pass)}** |",
            f"| C Fee stress | **{_verdict(report.gate_c_pass)}** |",
            f"| Combined | **{_verdict(report.still_combined_pass)}** |",
            (
                f"| combined rank | "
                f"{report.combined_rank if report.combined_rank is not None else '—'} |"
            ),
            f"| still top-1 | **{'yes' if report.still_combined_top1 else 'no'}** |",
            f"| mean HO excess | {_pct(report.mean_holdout_excess)} |",
            f"| BTC holdout | {_pct(report.baseline_btc_holdout)} |",
            f"| ETH holdout | {_pct(report.baseline_eth_holdout)} |",
            f"| min/max ratio | {_ratio(report.holdout_magnitude_ratio)} |",
            f"| BTC WF total | {_pct(report.baseline_btc_wf)} |",
            f"| ETH WF total | {_pct(report.baseline_eth_wf)} |",
            f"| mean WF total | {_pct(report.baseline_wf_total)} |",
            f"| WF rank (informational) | {report.wf_rank if report.wf_rank is not None else '—'} |",
            (f"| catalog top-1 | `{report.selected_candidate_id or 'none'}` |"),
            "",
        ]
    )
    if report.combined_passer_ids:
        lines.extend(
            [
                "Combined-passers on this reprint (informational): "
                + ", ".join(f"`{item}`" for item in report.combined_passer_ids)
                + ".",
                "",
            ]
        )
    else:
        lines.extend(["No combined-passers on this reprint.", ""])

    lines.extend(
        [
            "## 2. Yahoo Finance A/B (non-Kraken; cannot promote)",
            "",
            (
                "Yahoo `range=max` downsamples crypto to monthly "
                "(`dataGranularity=1mo`). This A/B uses "
                f"`period1={report.yahoo_period1_unix}` "
                f"({report.yahoo_period1_iso}) / `period2={period2}` so the "
                "series stays daily. High/low are expanded to contain "
                "open/close when Yahoo's print is inconsistent. Closes are "
                f"**not** Kraken Spot. These rows are for `{report.candidate_id}` "
                "only — the older `ema_9_21` Yahoo BTC-USD holdout (−9.28% on "
                "the #97 window) is a different path and is not copied here."
            ),
            "",
            (
                "| series | bars | first → last | WF total | WF excess | "
                "holdout excess | WF / HO signs |"
            ),
            "| --- | ---: | --- | ---: | ---: | ---: | :---: |",
        ]
    )
    if report.yahoo_rows:
        for row in report.yahoo_rows:
            span = f"{row.first} → {row.last}" if row.first and row.last else "n/a"
            skip = f" ({row.skipped_reason})" if row.skipped_reason else ""
            signs = f"{row.wf_total_sign} / {row.holdout_excess_sign}"
            lines.append(
                f"| `{row.asset}`{skip} | {row.bars} | {span} | "
                f"{_pct(row.wf_total)} | {_pct(row.wf_excess)} | "
                f"{_pct(row.holdout_excess)} | {signs} |"
            )
    else:
        lines.append("| — | — | — | n/a | n/a | n/a | n/a |")
    lines.extend(
        [
            "",
            (
                "**Cannot promote.** A negative or empty Yahoo print is "
                "success. Do not average these rows with Kraken, and do not "
                "wash a losing BTC-USD holdout out with a large ETH-USD tail."
            ),
            "",
            "## 3. Walk-forward maxDD vs paper DD ceiling",
            "",
            (
                f"`PAPER_PROMOTE_EMA_9_21_MAX_DRAWDOWN_PCT` default "
                f"**{report.paper_dd_ceiling:.0%}** is the BTC+ETH research "
                "envelope (#98). SOL is in `mvp_assets` and is supporting-"
                "only for that ceiling. `ema_9_21` SOL WF maxDD was ~50% on "
                "the committed #95 window — the question here is whether "
                f"`{report.candidate_id}` still blows past."
            ),
            "",
            "| series | source | WF maxDD | vs ceiling | blows past? |",
            "| --- | --- | ---: | --- | --- |",
        ]
    )
    for row in report.kraken_dd_rows:
        blows = (
            "yes"
            if row.blows_past_dd_ceiling
            else "no"
            if row.blows_past_dd_ceiling is False
            else "n/a"
        )
        lines.append(
            f"| `{row.asset}` | {row.source} | {_pct(row.wf_max_drawdown)} | "
            f"{_dd_vs_ceiling(row.wf_max_drawdown, report.paper_dd_ceiling)} | "
            f"**{blows}** |"
        )
    if not report.kraken_dd_rows:
        lines.append("| — | — | n/a | n/a | n/a |")
    sol_line = (
        "yes"
        if report.sol_blows_past_ceiling
        else "no"
        if report.sol_blows_past_ceiling is False
        else "n/a (no SOL series)"
    )
    lines.extend(
        [
            "",
            f"SOL still blows past the {report.paper_dd_ceiling:.0%} ceiling: **{sol_line}**.",
            "",
            "## 4. Multi-window (gate B) for this id",
            "",
            (
                f"Three contiguous {MULTIWINDOW_BARS}-bar Kraken daily slices; a "
                "window passes iff BTC **and** ETH WF total > 0. Gate B needs "
                f"≥ {MULTIWINDOW_MIN_PASSES} of {MULTIWINDOW_COUNT}."
            ),
            "",
            "| window | bars | first → last | BTC WF | ETH WF | passed |",
            "| --- | ---: | --- | ---: | ---: | --- |",
        ]
    )
    if report.windows:
        for window in report.windows:
            lines.append(
                f"| {window.label} | {window.bars} | {window.first} → {window.last} | "
                f"{_pct(window.btc_wf_total)} | {_pct(window.eth_wf_total)} | "
                f"{'yes' if window.passed else 'no'} |"
            )
    else:
        lines.append("| — | — | — | n/a | n/a | no windows |")
    lines.extend(
        [
            "",
            (
                f"Windows passed: {report.windows_passed}/3. Gate B: "
                f"**{_verdict(report.gate_b_pass)}**."
            ),
            "",
            "## Operator recommendation",
            "",
            report.recommendation,
            "",
            (
                f"`keep_flag_false={str(report.keep_flag_false).lower()}`. "
                "Do not fabricate PnL. Do not enable live."
            ),
            "",
        ]
    )
    return "\n".join(lines)
