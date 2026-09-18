"""HL-HTX funding-divergence SPOT overlay (paper research).

Pre-registered catalog ``fund_div_hl_htx_*``: FeatureZ fade/follow on the
aligned HL-minus-HTX daily funding divergence, scored on Kraken spot
BTC/ETH with a Coinbase second candle print. Not hedged carry. Never
flips ``PAPER_PROMOTE_*``. Skip-not-invent; empty dual-print is success.
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
    resample_funding_to_daily,
    slice_histories_to_funding,
    utc_day_open,
)
from traderstack.research.search import StrategySearchReport, run_search

FUND_DIV_RULES = (
    "Pre-registered HL-HTX funding-divergence SPOT overlay (frozen before "
    "any pull/score). Feature = UTC-daily HL funding sum minus HTX funding "
    "sum on the intersection of days per symbol; empty days omitted, never "
    "zero-filled. FeatureZVoter lookback=20; fade/follow at |z|>=1.0/1.5/2.0. "
    "Dual-print = Kraken x Coinbase spot BTC/ETH with the SAME divergence "
    "feature (both funding venues required). Hedged carry is excluded. "
    "Pilot fee 80+5 bps. BitMEX not used. PAPER_PROMOTE_* stays default "
    "false. Empty dual-print set is success."
)

FUND_DIV_CATALOG: tuple[tuple[str, bool, float], ...] = (
    ("fund_div_hl_htx_fade_1_0", True, 1.0),
    ("fund_div_hl_htx_fade_1_5", True, 1.5),
    ("fund_div_hl_htx_fade_2_0", True, 2.0),
    ("fund_div_hl_htx_follow_1_0", False, 1.0),
    ("fund_div_hl_htx_follow_1_5", False, 1.5),
    ("fund_div_hl_htx_follow_2_0", False, 2.0),
)
FUND_DIV_IDS: tuple[str, ...] = tuple(item[0] for item in FUND_DIV_CATALOG)
CONTROL_IDS: frozenset[str] = frozenset({"ma_cross_10_30"})
CORE_IDS: tuple[str, ...] = FUND_DIV_IDS + tuple(sorted(CONTROL_IDS))

REQUIRED_SYMBOLS: tuple[str, ...] = ("BTC/USD", "ETH/USD")
PAPER_PATH_READY = True  # spot long/flat FeatureZ on Kraken OHLC; no perp leg


def align_funding_divergence(
    primary_by_symbol: dict[str, tuple[tuple[datetime, float], ...]],
    secondary_by_symbol: dict[str, tuple[tuple[datetime, float], ...]],
    *,
    already_daily: bool = False,
) -> tuple[dict[str, tuple[tuple[datetime, float], ...]], list[dict[str, str]]]:
    """HL-minus-HTX daily divergence on the intersection of days (skip-not-invent).

    Missing days on either venue are omitted — never zero-filled. Symbols
    absent on either map are skipped with a note.
    """
    notes: list[dict[str, str]] = []
    out: dict[str, tuple[tuple[datetime, float], ...]] = {}

    def _lookup(
        mapping: dict[str, tuple[tuple[datetime, float], ...]], symbol: str
    ) -> tuple[tuple[datetime, float], ...] | None:
        key = symbol.upper()
        for name, series in mapping.items():
            if name.upper() == key:
                return series
        return None

    symbols = sorted(
        {key.upper() for key in primary_by_symbol} & {key.upper() for key in secondary_by_symbol}
    )
    for symbol in symbols:
        prim_series = _lookup(primary_by_symbol, symbol)
        sec_series = _lookup(secondary_by_symbol, symbol)
        if prim_series is None or sec_series is None:
            notes.append(
                {
                    "name": f"funding_div:{symbol}",
                    "status": "skipped",
                    "reason": "symbol missing on one funding venue",
                }
            )
            continue
        if already_daily:
            prim_daily = {utc_day_open(ts): float(v) for ts, v in prim_series}
            sec_daily = {utc_day_open(ts): float(v) for ts, v in sec_series}
        else:
            prim_res = resample_funding_to_daily(prim_series)
            sec_res = resample_funding_to_daily(sec_series)
            notes.append(
                {
                    "name": f"funding_div_resample:{symbol}:hl",
                    "status": "ok",
                    "reason": f"resampled {len(prim_series)} -> {len(prim_res)} UTC daily sums",
                }
            )
            notes.append(
                {
                    "name": f"funding_div_resample:{symbol}:htx",
                    "status": "ok",
                    "reason": f"resampled {len(sec_series)} -> {len(sec_res)} UTC daily sums",
                }
            )
            prim_daily = {utc_day_open(ts): float(v) for ts, v in prim_res}
            sec_daily = {utc_day_open(ts): float(v) for ts, v in sec_res}
        common = sorted(set(prim_daily) & set(sec_daily))
        if not common:
            notes.append(
                {
                    "name": f"funding_div:{symbol}",
                    "status": "skipped",
                    "reason": "no intersecting UTC days after resample",
                }
            )
            continue
        points = tuple((day, prim_daily[day] - sec_daily[day]) for day in common)
        out[symbol] = points
        notes.append(
            {
                "name": f"funding_div:{symbol}",
                "status": "ok",
                "reason": (
                    f"HL-minus-HTX on {len(points)} intersecting UTC days "
                    f"({points[0][0].date()} -> {points[-1][0].date()})"
                ),
            }
        )
    for symbol in REQUIRED_SYMBOLS:
        key = symbol.upper()
        if key not in out:
            notes.append(
                {
                    "name": f"funding_div:{key}",
                    "status": "skipped",
                    "reason": "required symbol has no aligned divergence series",
                }
            )
    return out, notes


def fund_div_candidates(
    *,
    divergence_by_symbol: dict[str, tuple[tuple[datetime, float], ...]] | None,
) -> tuple[SearchCandidate, ...]:
    if not divergence_by_symbol:
        return ()
    out: list[SearchCandidate] = []
    for candidate_id, fade, entry_z in FUND_DIV_CATALOG:
        verb = "fade" if fade else "follow"
        out.append(
            _feature_z_candidate(
                candidate_id=candidate_id,
                family="funding_z",  # FeatureZ family bucket; ids remain fund_div_*
                feature_name="funding_div_z",
                label=f"{verb} HL-HTX funding-div z |z|>={entry_z:g}",
                values=None,
                values_by_symbol=divergence_by_symbol,
                fade=fade,
                entry_z=entry_z,
                lookback=Z_LOOKBACK,
            )
        )
    out.append(_ma("ma_cross_10_30", short_window=10, long_window=30))
    return tuple(out)


def skipped_fund_div_families(
    *,
    divergence_by_symbol: dict[str, tuple[tuple[datetime, float], ...]] | None,
) -> list[dict[str, str]]:
    if divergence_by_symbol:
        return []
    skipped: list[dict[str, str]] = []
    for candidate_id, fade, entry_z in FUND_DIV_CATALOG:
        verb = "fade" if fade else "follow"
        skipped.append(
            {
                "family": "funding_div",
                "candidate_id": candidate_id,
                "reason": (
                    f"{verb} HL-HTX funding-div z |z|>={entry_z:g}: skipped — no "
                    "aligned HL and HTX funding intersection. Skip rather than invent."
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
                report.honesty + " This funding-div search cannot flip PAPER_PROMOTE_*; "
                "spot overlay dual-print is informational only."
            ),
        }
    )


class FundingDivReport(BaseModel):
    generated_at: datetime
    print_kind: Literal["single_print", "dual_print", "unavailable"]
    primary_candle_venue: str
    second_candle_venue: str | None = None
    funding_primary_venue: str = "hyperliquid"
    funding_second_venue: str = "htx"
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
    rules: str = FUND_DIV_RULES
    history_notes: list[dict[str, str]] = Field(default_factory=list)
    edge_notes: list[dict[str, str]] = Field(default_factory=list)
    skipped: list[dict[str, str]] = Field(default_factory=list)
    primary_search: StrategySearchReport | None = None
    second_search: StrategySearchReport | None = None
    recommended_promote_flag: str | None = None

    def model_dump_json_safe(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


def run_funding_div(
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
    hl_funding_by_symbol: dict[str, tuple[tuple[datetime, float], ...]] | None = None,
    htx_funding_by_symbol: dict[str, tuple[tuple[datetime, float], ...]] | None = None,
    second_histories: dict[str, tuple[Candle, ...]] | None = None,
    primary_candle_venue: str = "kraken",
    second_candle_venue: str | None = "coinbase",
    history_notes: list[dict[str, str]] | None = None,
    now: datetime | None = None,
) -> FundingDivReport:
    generated = now or datetime.now(UTC)
    notes: list[dict[str, str]] = []
    divergence, div_notes = align_funding_divergence(
        hl_funding_by_symbol or {},
        htx_funding_by_symbol or {},
        already_daily=False,
    )
    notes.extend(div_notes)
    have_div = all(symbol.upper() in {k.upper() for k in divergence} for symbol in REQUIRED_SYMBOLS)
    if not have_div:
        return FundingDivReport(
            generated_at=generated,
            print_kind="unavailable",
            primary_candle_venue=primary_candle_venue,
            second_candle_venue=second_candle_venue,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            history_notes=list(history_notes or []),
            edge_notes=notes,
            skipped=skipped_fund_div_families(divergence_by_symbol=None),
        )

    catalog = fund_div_candidates(divergence_by_symbol=divergence)
    sliced = slice_histories_to_funding(histories, divergence, None)
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
        second_sliced = slice_histories_to_funding(second_histories, divergence, None)
        second_aligned = min((len(item) for item in second_sliced.values()), default=0)
        if catalog and second_sliced:
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
                    candidates=catalog,
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

    return FundingDivReport(
        generated_at=generated,
        print_kind=print_kind,
        primary_candle_venue=primary_candle_venue,
        second_candle_venue=second_candle_venue if print_kind == "dual_print" else None,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
        dual_print_passer_ids=dual_passers,
        dual_print_passers=len(dual_passers),
        aligned_bars_primary=aligned,
        aligned_bars_second=second_aligned,
        history_notes=list(history_notes or []),
        edge_notes=notes,
        skipped=skipped_fund_div_families(divergence_by_symbol=divergence if have_div else None),
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


def render_funding_div_markdown(report: FundingDivReport) -> str:
    lines: list[str] = [
        "# HL-HTX funding-divergence SPOT overlay dual-print",
        "",
        f"Generated: {report.generated_at.isoformat()}",
        (
            f"Print kind: **{report.print_kind}**. interval=`{report.interval}`; "
            f"primary_candle=`{report.primary_candle_venue}`; "
            f"second_candle=`{report.second_candle_venue or 'none'}`; "
            f"funding=`{report.funding_primary_venue}`-minus-`{report.funding_second_venue}`; "
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
            "Paper-research catalog of HL-HTX funding-divergence FeatureZ voters on "
            "spot BTC/ETH. **Not** a live-capital claim, **not** hedged carry, **not** "
            "a reason to flip `PAPER_PROMOTE_*`. Empty dual-print set is success."
        ),
        "",
        "## Honesty / pre-registered rules",
        "",
        report.rules,
        "",
        "## Pre-registered catalog",
        "",
        "Frozen ids: "
        + ", ".join(f"`{cid}`" for cid in FUND_DIV_IDS)
        + "; control `"
        + "`, `".join(sorted(CONTROL_IDS))
        + "`.",
        "",
        "## Edge / divergence notes",
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

    lines.extend(
        [
            "",
            "## Dual-print passers",
            "",
        ]
    )
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
            "## Promotion decision",
            "",
            (
                f"**No candidate is promoted.** print_kind=`{report.print_kind}`; "
                f"can_promote=`false`; recommended_promote_flag=`none`; "
                f"`keep_flag_false=true`. Do not add a Settings pin. Do not enable live."
            ),
            "",
        ]
    )
    return "\n".join(lines)
