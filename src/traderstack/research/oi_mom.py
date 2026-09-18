"""HL/Bybit open-interest momentum SPOT overlay (paper research).

Pre-registered catalog ``oi_mom_*``: FeatureZ fade/follow on daily OI
momentum ``oi_ret[t] = OI[t]/OI[t-N] - 1`` for frozen N in {7,14,30} at
``|z| >= 2.0``, scored on Kraken spot BTC/ETH with a Coinbase second candle
print. Dual OI gate requires Hyperliquid asiletto81 asset_ctxs AND Bybit
linear daily OI each >=720 UTC days for BTC+ETH. Live candle feature tape
uses Bybit; HL asiletto archive ends 2026-06-01 and is not stitched past
that date. Never flips ``PAPER_PROMOTE_*``. Skip-not-invent; empty dual-print
is success.
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

OI_MOM_RULES = (
    "Pre-registered HL/Bybit open-interest momentum SPOT overlay frozen before "
    "any pull/score. Feature = UTC-daily oi_ret[t]=OI[t]/OI[t-N]-1 for N in "
    "{7,14,30}; FeatureZVoter lookback=20; fade/follow at |z|>=2.0 only. Dual OI "
    "gate = HL asiletto81 asset_ctxs AND Bybit linear daily OI each >=720 UTC days "
    "BTC+ETH. Dual-print = Kraken x Coinbase spot with Bybit OI as the live feature "
    "tape. HL archive ends 2026-06-01; live Kraken720 overlap below 720 so "
    "skip-not-invent. PAPER_PROMOTE_* stays default false. Empty dual-print set "
    "is success."
)

OI_MOM_CATALOG: tuple[tuple[str, bool, float, int], ...] = (
    ("oi_mom_fade_7", True, 2.0, 7),
    ("oi_mom_fade_14", True, 2.0, 14),
    ("oi_mom_fade_30", True, 2.0, 30),
    ("oi_mom_follow_7", False, 2.0, 7),
    ("oi_mom_follow_14", False, 2.0, 14),
    ("oi_mom_follow_30", False, 2.0, 30),
)
OI_MOM_IDS: tuple[str, ...] = tuple(item[0] for item in OI_MOM_CATALOG)
CONTROL_IDS: frozenset[str] = frozenset({"ma_cross_10_30"})
CORE_IDS: tuple[str, ...] = OI_MOM_IDS + tuple(sorted(CONTROL_IDS))

REQUIRED_SYMBOLS: tuple[str, ...] = ("BTC/USD", "ETH/USD")
PAPER_PATH_READY = True
MIN_OI_DAYS = 720


def oi_momentum_series(
    oi_points: tuple[tuple[datetime, float], ...],
    lookback_n: int,
) -> tuple[tuple[datetime, float], ...]:
    if lookback_n <= 0 or len(oi_points) <= lookback_n:
        return ()
    ordered = sorted((utc_day_open(ts), float(val)) for ts, val in oi_points)
    by_day: dict[datetime, float] = {}
    for day, val in ordered:
        by_day[day] = val
    days = sorted(by_day)
    out: list[tuple[datetime, float]] = []
    for idx in range(lookback_n, len(days)):
        day = days[idx]
        prior = days[idx - lookback_n]
        base = by_day[prior]
        cur = by_day[day]
        if base <= 0 or cur <= 0:
            continue
        out.append((day, cur / base - 1.0))
    return tuple(out)


def build_oi_ret_by_symbol(
    oi_by_symbol: dict[str, tuple[tuple[datetime, float], ...]],
    lookback_n: int,
) -> dict[str, tuple[tuple[datetime, float], ...]]:
    out: dict[str, tuple[tuple[datetime, float], ...]] = {}
    for symbol, series in oi_by_symbol.items():
        mom = oi_momentum_series(series, lookback_n)
        if mom:
            out[symbol.upper()] = mom
    return out


def dual_oi_gate(
    hl_by_symbol: dict[str, tuple[tuple[datetime, float], ...]],
    bybit_by_symbol: dict[str, tuple[tuple[datetime, float], ...]],
    *,
    min_days: int = MIN_OI_DAYS,
) -> tuple[bool, list[dict[str, str]]]:
    notes: list[dict[str, str]] = []
    ok = True
    for venue, mapping in (("hyperliquid_asilletto", hl_by_symbol), ("bybit", bybit_by_symbol)):
        for symbol in REQUIRED_SYMBOLS:
            key = symbol.upper()
            series = next((pts for name, pts in mapping.items() if name.upper() == key), None)
            n = len(series) if series else 0
            status = "ok" if n >= min_days else "unavailable"
            if status != "ok":
                ok = False
            first = series[0][0].date().isoformat() if series else ""
            last = series[-1][0].date().isoformat() if series else ""
            notes.append(
                {
                    "name": f"oi_gate:{venue}:{key}",
                    "status": status,
                    "reason": f"points={n} min={min_days} span={first}->{last}",
                }
            )
    notes.append(
        {
            "name": "oi_gate:dual",
            "status": "ok" if ok else "unavailable",
            "reason": (
                "both HL asiletto and Bybit >=720d BTC+ETH"
                if ok
                else "dual OI unavailable; refuse single-venue promote"
            ),
        }
    )
    return ok, notes


def oi_mom_candidates(
    *,
    oi_by_symbol: dict[str, tuple[tuple[datetime, float], ...]] | None,
) -> tuple[SearchCandidate, ...]:
    if not oi_by_symbol:
        return ()
    out: list[SearchCandidate] = []
    for candidate_id, fade, entry_z, lookback_n in OI_MOM_CATALOG:
        values_by_symbol = build_oi_ret_by_symbol(oi_by_symbol, lookback_n)
        if not values_by_symbol:
            continue
        verb = "fade" if fade else "follow"
        out.append(
            _feature_z_candidate(
                candidate_id=candidate_id,
                family="funding_z",
                feature_name=f"oi_mom_z_{lookback_n}",
                label=f"{verb} OI-mom N={lookback_n} z |z|>={entry_z:g}",
                values=None,
                values_by_symbol=values_by_symbol,
                fade=fade,
                entry_z=entry_z,
                lookback=Z_LOOKBACK,
            )
        )
    out.append(_ma("ma_cross_10_30", short_window=10, long_window=30))
    return tuple(out)


def skipped_oi_mom_families(
    *,
    oi_by_symbol: dict[str, tuple[tuple[datetime, float], ...]] | None,
) -> list[dict[str, str]]:
    if oi_by_symbol:
        return []
    skipped: list[dict[str, str]] = []
    for candidate_id, fade, entry_z, lookback_n in OI_MOM_CATALOG:
        verb = "fade" if fade else "follow"
        skipped.append(
            {
                "family": "oi_mom",
                "candidate_id": candidate_id,
                "reason": (
                    f"{verb} OI-mom N={lookback_n} z |z|>={entry_z:g}: skipped — no "
                    "aligned OI series. Skip rather than invent."
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
                report.honesty
                + " This oi-mom search cannot flip PAPER_PROMOTE_*; "
                "spot overlay dual-print is informational only."
            ),
        }
    )


class OiMomReport(BaseModel):
    generated_at: datetime
    print_kind: Literal["single_print", "dual_print", "unavailable"]
    primary_candle_venue: str
    second_candle_venue: str | None = None
    oi_primary_venue: str = "bybit"
    oi_second_venue: str = "hyperliquid_asilletto"
    dual_oi_available: bool = False
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
    rules: str = OI_MOM_RULES
    history_notes: list[dict[str, str]] = Field(default_factory=list)
    edge_notes: list[dict[str, str]] = Field(default_factory=list)
    skipped: list[dict[str, str]] = Field(default_factory=list)
    primary_search: StrategySearchReport | None = None
    second_search: StrategySearchReport | None = None
    recommended_promote_flag: str | None = None

    def model_dump_json_safe(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


def run_oi_mom(
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
    feature_oi_by_symbol: dict[str, tuple[tuple[datetime, float], ...]] | None = None,
    hl_oi_by_symbol: dict[str, tuple[tuple[datetime, float], ...]] | None = None,
    bybit_oi_by_symbol: dict[str, tuple[tuple[datetime, float], ...]] | None = None,
    second_histories: dict[str, tuple[Candle, ...]] | None = None,
    primary_candle_venue: str = "kraken",
    second_candle_venue: str | None = "coinbase",
    history_notes: list[dict[str, str]] | None = None,
    now: datetime | None = None,
) -> OiMomReport:
    generated = now or datetime.now(UTC)
    notes: list[dict[str, str]] = []
    dual_ok, gate_notes = dual_oi_gate(hl_oi_by_symbol or {}, bybit_oi_by_symbol or {})
    notes.extend(gate_notes)

    feature_oi = feature_oi_by_symbol or bybit_oi_by_symbol or {}
    have_feature = all(
        any(name.upper() == symbol.upper() for name in feature_oi)
        for symbol in REQUIRED_SYMBOLS
    )
    if not dual_ok or not have_feature:
        return OiMomReport(
            generated_at=generated,
            print_kind="unavailable",
            primary_candle_venue=primary_candle_venue,
            second_candle_venue=second_candle_venue,
            dual_oi_available=dual_ok,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            history_notes=list(history_notes or []),
            edge_notes=notes,
            skipped=skipped_oi_mom_families(oi_by_symbol=None),
        )

    catalog = oi_mom_candidates(oi_by_symbol=feature_oi)
    sliced = slice_histories_to_funding(histories, feature_oi, None)
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
        second_sliced = slice_histories_to_funding(second_histories, feature_oi, None)
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

    return OiMomReport(
        generated_at=generated,
        print_kind=print_kind,
        primary_candle_venue=primary_candle_venue,
        second_candle_venue=second_candle_venue if print_kind == "dual_print" else None,
        dual_oi_available=True,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
        dual_print_passer_ids=dual_passers,
        dual_print_passers=len(dual_passers),
        aligned_bars_primary=aligned,
        aligned_bars_second=second_aligned,
        history_notes=list(history_notes or []),
        edge_notes=notes,
        skipped=skipped_oi_mom_families(oi_by_symbol=feature_oi),
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


def render_oi_mom_markdown(report: OiMomReport) -> str:
    lines: list[str] = [
        "# HL/Bybit open-interest momentum SPOT overlay dual-print",
        "",
        f"Generated: {report.generated_at.isoformat()}",
        (
            f"Print kind: **{report.print_kind}**. interval=`{report.interval}`; "
            f"primary_candle=`{report.primary_candle_venue}`; "
            f"second_candle=`{report.second_candle_venue or 'none'}`; "
            f"feature_oi=`{report.oi_primary_venue}`; gate_oi=`{report.oi_second_venue}`; "
            f"dual_oi_available=`{str(report.dual_oi_available).lower()}`; "
            f"paper_path_ready=`{str(report.paper_path_ready).lower()}`; "
            f"can_promote=`{str(report.can_promote).lower()}`; "
            f"`keep_flag_false={str(report.keep_flag_false).lower()}`."
        ),
        f"Core ids={len(report.core_ids)}; dual_print_passers=`{report.dual_print_passers}`.",
        (
            f"Costs: fee={report.fee_bps:g} bps + slippage={report.slippage_bps:g} bps "
            "(pilot spot). OI is a filter only - no perp leg."
        ),
        (
            f"Aligned bars: primary={report.aligned_bars_primary}, "
            f"second={report.aligned_bars_second}."
        ),
        "",
        "## What this does / does not claim",
        "",
        (
            "Paper-research catalog of OI-momentum FeatureZ voters on spot BTC/ETH. "
            "**Not** a live-capital claim. **Not** a reason to flip `PAPER_PROMOTE_*`. "
            "Empty dual-print set is success."
        ),
        "",
        "## Probe notes",
        "",
        "- Hyperliquid asiletto81/hyperliquid asset_ctxs: AVAILABLE >=720d BTC+ETH.",
        "- Bybit linear daily open interest: AVAILABLE >=720d BTC+ETH.",
        "- HTX / Binance / OKX daily OI history: UNAVAILABLE at >=720d.",
        "- Live candle feature tape: Bybit. HL archive ends 2026-06-01; live Kraken720 "
        "overlap is below 720 so HL is gate-only for this score.",
        "",
        "## Honesty / pre-registered rules",
        "",
        report.rules,
        "",
        "## Pre-registered catalog",
        "",
        "Frozen ids: "
        + ", ".join(f"`{cid}`" for cid in OI_MOM_IDS)
        + "; control `"
        + "`, `".join(sorted(CONTROL_IDS))
        + "`.",
        "",
        "## Edge / OI gate notes",
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
            lines.append("No search result.")
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

    _table(report.primary_search, f"Primary candle print (`{report.primary_candle_venue}`)")
    if report.print_kind == "dual_print":
        _table(report.second_search, f"Second candle print (`{report.second_candle_venue}`)")

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
            "## Promotion decision",
            "",
            (
                f"**No candidate is promoted.** print_kind=`{report.print_kind}`; "
                f"dual_oi_available=`{str(report.dual_oi_available).lower()}`; "
                "can_promote=`false`; recommended_promote_flag=`none`; "
                "`keep_flag_false=true`. Do not add a Settings pin. Do not enable live."
            ),
            "",
        ]
    )
    return "\n".join(lines)
