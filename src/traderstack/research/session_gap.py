"""Overnight vs session open-close gap SPOT dual-print (paper research).

Pre-registered catalog ``sess_gap_*``: FeatureZ fade/follow on overnight
gap (open[t]/close[t-1]-1) and session return (close[t]/open[t]-1) from
daily OHLC, scored on Kraken spot BTC/ETH with a Coinbase second candle
print. No intraday archive required. Never flips ``PAPER_PROMOTE_*``.
Skip-not-invent; empty dual-print is success.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from traderstack.candles import Candle
from traderstack.research.candidates import SearchCandidate, _feature_z_candidate, _ma
from traderstack.research.funding_carry import (
    DEFAULT_STEP_SIZE,
    DEFAULT_TEST_SIZE,
    DEFAULT_TRAIN_SIZE,
    DEFAULT_WARMUP,
    Z_LOOKBACK,
    choose_walkforward,
    slice_histories_to_funding,
    utc_day_open,
)
from traderstack.research.search import StrategySearchReport, run_search

SESS_GAP_RULES = (
    "Pre-registered overnight vs session open-close gap SPOT overlay "
    "(frozen before any score). Features from daily OHLC only: "
    "(1) overnight_gap[t] = open[t]/close[t-1]-1; "
    "(2) session_ret[t] = close[t]/open[t]-1. "
    "A missing/non-positive prior close or open is skipped, never zero-filled. "
    "FeatureZVoter lookback=20; fade/follow at |z|>=1.0/1.5/2.0 for each feature. "
    "Dual-print = Kraken x Coinbase spot BTC/ETH; each venue uses its OWN "
    "OHLC-derived features (venues never averaged). Pilot fee 80+5 bps. "
    "BitMEX not used. PAPER_PROMOTE_* stays default false. Empty dual-print "
    "set is success. Not a calendar reprint, not funding-div, not xs-topk."
)

# (id, fade, entry_z, kind) kind in {"overnight", "session"}
SESS_GAP_CATALOG: tuple[tuple[str, bool, float, str], ...] = (
    ("sess_gap_on_fade_1_0", True, 1.0, "overnight"),
    ("sess_gap_on_fade_1_5", True, 1.5, "overnight"),
    ("sess_gap_on_fade_2_0", True, 2.0, "overnight"),
    ("sess_gap_on_follow_1_0", False, 1.0, "overnight"),
    ("sess_gap_on_follow_1_5", False, 1.5, "overnight"),
    ("sess_gap_on_follow_2_0", False, 2.0, "overnight"),
    ("sess_gap_sess_fade_1_0", True, 1.0, "session"),
    ("sess_gap_sess_fade_1_5", True, 1.5, "session"),
    ("sess_gap_sess_fade_2_0", True, 2.0, "session"),
    ("sess_gap_sess_follow_1_0", False, 1.0, "session"),
    ("sess_gap_sess_follow_1_5", False, 1.5, "session"),
    ("sess_gap_sess_follow_2_0", False, 2.0, "session"),
)
SESS_GAP_IDS: tuple[str, ...] = tuple(item[0] for item in SESS_GAP_CATALOG)
CONTROL_IDS: frozenset[str] = frozenset({"ma_cross_10_30"})
CORE_IDS: tuple[str, ...] = SESS_GAP_IDS + tuple(sorted(CONTROL_IDS))

REQUIRED_SYMBOLS: tuple[str, ...] = ("BTC/USD", "ETH/USD")
PAPER_PATH_READY = True  # spot long/flat FeatureZ on Kraken OHLC; no perp leg


def overnight_gap_series(
    candles: tuple[Candle, ...],
) -> tuple[tuple[datetime, float], ...]:
    """open[t]/close[t-1]-1 stamped at utc_day_open(opened_at[t]). Skip-not-invent."""
    if len(candles) < 2:
        return ()
    points: list[tuple[datetime, float]] = []
    for index in range(1, len(candles)):
        prev = candles[index - 1]
        cur = candles[index]
        if prev.close <= 0 or cur.open <= 0:
            continue
        gap = (cur.open / prev.close) - 1.0
        points.append((utc_day_open(cur.opened_at), gap))
    return tuple(points)


def session_return_series(
    candles: tuple[Candle, ...],
) -> tuple[tuple[datetime, float], ...]:
    """close[t]/open[t]-1 stamped at utc_day_open(opened_at[t]). Skip-not-invent."""
    if not candles:
        return ()
    points: list[tuple[datetime, float]] = []
    for candle in candles:
        if candle.open <= 0:
            continue
        ret = (candle.close / candle.open) - 1.0
        points.append((utc_day_open(candle.opened_at), ret))
    return tuple(points)


def build_gap_features(
    histories: dict[str, tuple[Candle, ...]],
) -> tuple[
    dict[str, tuple[tuple[datetime, float], ...]],
    dict[str, tuple[tuple[datetime, float], ...]],
    list[dict[str, str]],
]:
    """Overnight + session features from daily OHLC (skip-not-invent)."""
    notes: list[dict[str, str]] = []
    overnight: dict[str, tuple[tuple[datetime, float], ...]] = {}
    session: dict[str, tuple[tuple[datetime, float], ...]] = {}

    def _lookup(symbol: str) -> tuple[Candle, ...] | None:
        key = symbol.upper()
        for name, series in histories.items():
            if name.upper() == key:
                return series
        return None

    min_points = Z_LOOKBACK + 5
    for symbol in REQUIRED_SYMBOLS:
        candles = _lookup(symbol)
        if candles is None:
            notes.append(
                {
                    "name": f"sess_gap:{symbol}",
                    "status": "skipped",
                    "reason": "required symbol missing from candle histories",
                }
            )
            continue
        on_series = overnight_gap_series(candles)
        sess_series = session_return_series(candles)
        if len(on_series) < min_points:
            notes.append(
                {
                    "name": f"sess_gap_overnight:{symbol}",
                    "status": "skipped",
                    "reason": (
                        f"overnight gap points={len(on_series)} below "
                        f"min_points={min_points}; skip-not-invent"
                    ),
                }
            )
        else:
            overnight[symbol.upper()] = on_series
            notes.append(
                {
                    "name": f"sess_gap_overnight:{symbol}",
                    "status": "ok",
                    "reason": (
                        f"{len(on_series)} overnight gaps "
                        f"{on_series[0][0].date()} -> {on_series[-1][0].date()}"
                    ),
                }
            )
        if len(sess_series) < min_points:
            notes.append(
                {
                    "name": f"sess_gap_session:{symbol}",
                    "status": "skipped",
                    "reason": (
                        f"session return points={len(sess_series)} below "
                        f"min_points={min_points}; skip-not-invent"
                    ),
                }
            )
        else:
            session[symbol.upper()] = sess_series
            notes.append(
                {
                    "name": f"sess_gap_session:{symbol}",
                    "status": "ok",
                    "reason": (
                        f"{len(sess_series)} session returns "
                        f"{sess_series[0][0].date()} -> {sess_series[-1][0].date()}"
                    ),
                }
            )
    return overnight, session, notes


def _feature_union(
    overnight: dict[str, tuple[tuple[datetime, float], ...]],
    session: dict[str, tuple[tuple[datetime, float], ...]],
) -> dict[str, tuple[tuple[datetime, float], ...]]:
    """Union of feature stamps per symbol for history slicing."""
    out: dict[str, tuple[tuple[datetime, float], ...]] = {}
    for symbol in set(overnight) | set(session):
        stamps: dict[datetime, float] = {}
        for ts, value in overnight.get(symbol, ()):
            stamps[ts] = value
        for ts, value in session.get(symbol, ()):
            stamps.setdefault(ts, value)
        if stamps:
            out[symbol] = tuple(sorted(stamps.items(), key=lambda item: item[0]))
    return out


def sess_gap_candidates(
    *,
    overnight_by_symbol: dict[str, tuple[tuple[datetime, float], ...]] | None,
    session_by_symbol: dict[str, tuple[tuple[datetime, float], ...]] | None,
) -> tuple[SearchCandidate, ...]:
    overnight_by_symbol = overnight_by_symbol or {}
    session_by_symbol = session_by_symbol or {}
    out: list[SearchCandidate] = []
    for candidate_id, fade, entry_z, kind in SESS_GAP_CATALOG:
        values_by_symbol = overnight_by_symbol if kind == "overnight" else session_by_symbol
        if not all(symbol.upper() in values_by_symbol for symbol in REQUIRED_SYMBOLS):
            continue
        verb = "fade" if fade else "follow"
        feature_name = "overnight_gap_z" if kind == "overnight" else "session_ret_z"
        out.append(
            _feature_z_candidate(
                candidate_id=candidate_id,
                family="funding_z",  # FeatureZ family bucket; ids remain sess_gap_*
                feature_name=feature_name,
                label=f"{verb} {kind} gap z |z|>={entry_z:g}",
                values=None,
                values_by_symbol=values_by_symbol,
                fade=fade,
                entry_z=entry_z,
                lookback=Z_LOOKBACK,
            )
        )
    if out:
        out.append(_ma("ma_cross_10_30", short_window=10, long_window=30))
    return tuple(out)


def skipped_sess_gap_families(
    *,
    overnight_by_symbol: dict[str, tuple[tuple[datetime, float], ...]] | None,
    session_by_symbol: dict[str, tuple[tuple[datetime, float], ...]] | None,
) -> list[dict[str, str]]:
    overnight_by_symbol = overnight_by_symbol or {}
    session_by_symbol = session_by_symbol or {}
    skipped: list[dict[str, str]] = []
    for candidate_id, fade, entry_z, kind in SESS_GAP_CATALOG:
        values_by_symbol = overnight_by_symbol if kind == "overnight" else session_by_symbol
        if all(symbol.upper() in values_by_symbol for symbol in REQUIRED_SYMBOLS):
            continue
        verb = "fade" if fade else "follow"
        skipped.append(
            {
                "family": "sess_gap",
                "candidate_id": candidate_id,
                "reason": (
                    f"{verb} {kind} gap z |z|>={entry_z:g}: skipped — BTC/ETH "
                    "feature series unavailable. Skip rather than invent."
                ),
            }
        )
    return skipped


def _clear_promotion(report: StrategySearchReport) -> StrategySearchReport:
    cleared = [
        row.model_copy(update={"promoted": False, "selected": row.selected})
        for row in report.candidates
    ]
    return report.model_copy(
        update={
            "candidates": cleared,
            "promoted_candidate_ids": [],
            "any_promoted": False,
            "allowed_promote_id": None,
            "honesty": (
                report.honesty + " This sess-gap search cannot flip PAPER_PROMOTE_*; "
                "spot overlay dual-print is informational only."
            ),
        }
    )


class SessGapReport(BaseModel):
    generated_at: datetime
    print_kind: Literal["single_print", "dual_print", "unavailable"]
    primary_candle_venue: str
    second_candle_venue: str | None = None
    interval: str = "1d"
    fee_bps: float
    slippage_bps: float
    keep_flag_false: bool = True
    can_promote: bool = False
    paper_path_ready: bool = PAPER_PATH_READY
    core_ids: list[str] = Field(default_factory=lambda: list(CORE_IDS))
    control_ids: list[str] = Field(default_factory=lambda: sorted(CONTROL_IDS))
    dual_print_passer_ids: list[str] = Field(default_factory=list)
    dual_print_passers: int = 0
    aligned_bars_primary: int = 0
    aligned_bars_second: int = 0
    rules: str = SESS_GAP_RULES
    history_notes: list[dict[str, str]] = Field(default_factory=list)
    edge_notes: list[dict[str, str]] = Field(default_factory=list)
    skipped: list[dict[str, str]] = Field(default_factory=list)
    primary_search: StrategySearchReport | None = None
    second_search: StrategySearchReport | None = None
    recommended_promote_flag: str | None = None

    def model_dump_json_safe(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


def run_sess_gap(
    histories: dict[str, tuple[Candle, ...]],
    *,
    fee_bps: float,
    slippage_bps: float = 5.0,
    starting_equity: float = 10_000.0,
    warmup: int = DEFAULT_WARMUP,
    train_size: int = DEFAULT_TRAIN_SIZE,
    test_size: int = DEFAULT_TEST_SIZE,
    step_size: int = DEFAULT_STEP_SIZE,
    holdout_fraction: float = 0.20,
    min_trades: int = 3,
    interval: str = "1d",
    second_histories: dict[str, tuple[Candle, ...]] | None = None,
    primary_candle_venue: str = "kraken",
    second_candle_venue: str | None = "coinbase",
    history_notes: list[dict[str, str]] | None = None,
    now: datetime | None = None,
) -> SessGapReport:
    generated = now or datetime.now(UTC)
    overnight, session, feat_notes = build_gap_features(histories)
    notes = list(feat_notes)
    have_on = all(symbol.upper() in overnight for symbol in REQUIRED_SYMBOLS)
    have_sess = all(symbol.upper() in session for symbol in REQUIRED_SYMBOLS)
    if not (have_on or have_sess):
        return SessGapReport(
            generated_at=generated,
            print_kind="unavailable",
            primary_candle_venue=primary_candle_venue,
            second_candle_venue=second_candle_venue,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            history_notes=list(history_notes or []),
            edge_notes=notes,
            skipped=skipped_sess_gap_families(overnight_by_symbol=None, session_by_symbol=None),
        )

    catalog = sess_gap_candidates(
        overnight_by_symbol=overnight if have_on else None,
        session_by_symbol=session if have_sess else None,
    )
    feature_for_slice = _feature_union(
        overnight if have_on else {},
        session if have_sess else {},
    )
    sliced = slice_histories_to_funding(histories, feature_for_slice, None)
    aligned = min((len(item) for item in sliced.values()), default=0)
    n_research = int(aligned * (1.0 - holdout_fraction)) if aligned else 0
    sizes = choose_walkforward(
        n_research,
        train_size=train_size,
        test_size=test_size,
        step_size=step_size,
        warmup=warmup,
    )
    use_train, use_test, use_step, use_warmup = train_size, test_size, step_size, warmup
    if sizes is not None:
        use_train, use_test, use_step, use_warmup = sizes

    primary_search: StrategySearchReport | None = None
    if catalog and sliced:
        primary_search = _clear_promotion(
            run_search(
                sliced,
                fee_bps=fee_bps,
                slippage_bps=slippage_bps,
                starting_equity=starting_equity,
                warmup=use_warmup,
                train_size=use_train,
                test_size=use_test,
                step_size=use_step,
                holdout_fraction=holdout_fraction,
                min_trades=min_trades,
                candidates=catalog,
                history_notes=history_notes,
                edge_notes=notes,
                now=generated,
                include_feature_candidates=False,
            )
        )

    second_search: StrategySearchReport | None = None
    second_aligned = 0
    print_kind: Literal["single_print", "dual_print", "unavailable"] = "single_print"
    if second_histories:
        on2, sess2, notes2 = build_gap_features(second_histories)
        notes.extend(notes2)
        have_on2 = all(symbol.upper() in on2 for symbol in REQUIRED_SYMBOLS)
        have_sess2 = all(symbol.upper() in sess2 for symbol in REQUIRED_SYMBOLS)
        catalog2 = sess_gap_candidates(
            overnight_by_symbol=on2 if have_on2 else None,
            session_by_symbol=sess2 if have_sess2 else None,
        )
        feature2 = _feature_union(on2 if have_on2 else {}, sess2 if have_sess2 else {})
        second_sliced = slice_histories_to_funding(second_histories, feature2, None)
        second_aligned = min((len(item) for item in second_sliced.values()), default=0)
        if catalog2 and second_sliced:
            second_search = _clear_promotion(
                run_search(
                    second_sliced,
                    fee_bps=fee_bps,
                    slippage_bps=slippage_bps,
                    starting_equity=starting_equity,
                    warmup=use_warmup,
                    train_size=use_train,
                    test_size=use_test,
                    step_size=use_step,
                    holdout_fraction=holdout_fraction,
                    min_trades=min_trades,
                    candidates=catalog2,
                    now=generated,
                    include_feature_candidates=False,
                )
            )
            print_kind = "dual_print"

    dual_passers: list[str] = []
    if print_kind == "dual_print" and primary_search is not None and second_search is not None:
        primary_eligible = {
            row.candidate_id
            for row in primary_search.candidates
            if row.eligible and row.candidate_id not in CONTROL_IDS
        }
        second_eligible = {
            row.candidate_id
            for row in second_search.candidates
            if row.eligible and row.candidate_id not in CONTROL_IDS
        }
        dual_passers = sorted(primary_eligible & second_eligible)

    return SessGapReport(
        generated_at=generated,
        print_kind=print_kind,
        primary_candle_venue=primary_candle_venue,
        second_candle_venue=second_candle_venue if print_kind == "dual_print" else None,
        interval=interval,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
        dual_print_passer_ids=dual_passers,
        dual_print_passers=len(dual_passers),
        aligned_bars_primary=aligned,
        aligned_bars_second=second_aligned,
        history_notes=list(history_notes or []),
        edge_notes=notes,
        skipped=skipped_sess_gap_families(
            overnight_by_symbol=overnight if have_on else None,
            session_by_symbol=session if have_sess else None,
        ),
        primary_search=primary_search,
        second_search=second_search,
        can_promote=False,
        keep_flag_false=True,
        recommended_promote_flag=None,
    )


def _pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.2f}%"


def render_sess_gap_markdown(report: SessGapReport) -> str:
    lines: list[str] = [
        "# Overnight vs session gap SPOT dual-print (Kraken x Coinbase)",
        "",
        f"Generated: {report.generated_at.isoformat()}",
        (
            f"Print kind: **{report.print_kind}**. interval=`{report.interval}`; "
            f"primary_candle=`{report.primary_candle_venue}`; "
            f"second_candle=`{report.second_candle_venue or 'none'}`; "
            f"paper_path_ready=`{str(report.paper_path_ready).lower()}`; "
            f"can_promote=`{str(report.can_promote).lower()}`; "
            f"`keep_flag_false={str(report.keep_flag_false).lower()}`."
        ),
        (f"Core ids={len(report.core_ids)}; dual_print_passers=`{report.dual_print_passers}`."),
        (
            f"Costs: fee={report.fee_bps:g} bps + slippage={report.slippage_bps:g} bps "
            "(pilot spot). No hedged-carry legs."
        ),
        (
            f"Aligned bars: primary={report.aligned_bars_primary}, "
            f"second={report.aligned_bars_second}."
        ),
        "",
        "## What this does / does not claim",
        "",
        (
            "Paper-research catalog of overnight-gap and session-return FeatureZ voters "
            "on spot BTC/ETH from daily OHLC. **Not** a live-capital claim, **not** a "
            "reason to flip `PAPER_PROMOTE_*`. Empty dual-print set is success."
        ),
        "",
        "## Honesty / pre-registered rules",
        "",
        report.rules,
        "",
        "## Pre-registered catalog",
        "",
        "Frozen ids: "
        + ", ".join(f"`{cid}`" for cid in SESS_GAP_IDS)
        + "; control `"
        + "`, `".join(sorted(CONTROL_IDS))
        + "`.",
        "",
        "## Edge / feature notes",
        "",
    ]
    for note in report.edge_notes:
        lines.append(
            f"- `{note.get('name', '?')}` **{note.get('status', '?')}**: {note.get('reason', '')}"
        )
    if report.history_notes:
        lines.extend(["", "## Candle notes", ""])
        for note in report.history_notes:
            lines.append(
                f"- `{note.get('name', note.get('symbol', '?'))}`: "
                f"{note.get('reason', note.get('status', ''))}"
            )
    if report.skipped:
        lines.extend(["", "## Skipped families", ""])
        for row in report.skipped:
            lines.append(f"- `{row.get('candidate_id', '?')}`: {row.get('reason', '')}")

    def _table(search: StrategySearchReport | None, title: str) -> None:
        lines.extend(["", f"## {title}", ""])
        if search is None:
            lines.append("No search result (skipped / unavailable).")
            return
        lines.append(
            "| rank | id | family | WF excess | WF total | holdout excess | eligible | control |"
        )
        lines.append("| ---: | --- | --- | ---: | ---: | ---: | :---: | :---: |")
        ranked = sorted(
            search.candidates,
            key=lambda row: (
                -(row.mean_wf_excess_return if row.mean_wf_excess_return is not None else -1e9),
                row.candidate_id,
            ),
        )
        for index, row in enumerate(ranked, start=1):
            control = "yes" if row.candidate_id in CONTROL_IDS else "no"
            lines.append(
                f"| {index} | `{row.candidate_id}` | {row.family} | "
                f"{_pct(row.mean_wf_excess_return)} | {_pct(row.mean_wf_total_return)} | "
                f"{_pct(row.mean_holdout_excess_return)} | "
                f"{'yes' if row.eligible else 'no'} | {control} |"
            )

    _table(
        report.primary_search,
        f"Primary candle print (`{report.primary_candle_venue}`)",
    )
    if report.print_kind == "dual_print":
        _table(
            report.second_search,
            f"Second candle print (`{report.second_candle_venue}`)",
        )

    lines.extend(["", "## Dual-print passers", ""])
    if report.dual_print_passer_ids:
        lines.append(
            "Names that cleared the fee-aware bar on both candle venues "
            "(informational; no Settings pin): "
            + ", ".join(f"`{cid}`" for cid in report.dual_print_passer_ids)
            + "."
        )
    else:
        lines.append(
            f"**dual_print_passers={report.dual_print_passers}.** "
            "Empty set is success. Leave every `PAPER_PROMOTE_*` false."
        )

    lines.extend(
        [
            "",
            "## Operator recommendation",
            "",
            (
                f"**No candidate is promoted.** print_kind=`{report.print_kind}`; "
                f"can_promote=`false`; recommended_promote_flag=`none`; "
                f"`keep_flag_false=true`. Do not add a Settings pin. Do not enable live."
            ),
            "",
        ]
    )
    return "\n".join(lines) + "\n"
