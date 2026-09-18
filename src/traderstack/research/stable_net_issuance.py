"""DefiLlama stablecoin net-issuance SPOT overlay (paper research).

Pre-registered catalog ``stable_ni_*``: FeatureZ fade/follow on aggregate
stablecoin net issuance. Live DefiLlama history is **not** PIT-safe; dual-print
score refuses unless an operator PIT archive is supplied and marked safe.
Never flips ``PAPER_PROMOTE_*``. Skip-not-invent; UNAVAILABLE is success.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from traderstack.candles import Candle
from traderstack.market.defillama_stablecoins import (
    LAG_DAYS,
    PIT_SAFE_LIVE_HISTORY,
    PIT_VERDICT,
    StablecoinChartSeries,
    StableNetIssuancePoint,
    apply_lag,
    net_issuance_from_chart,
    refuse_live_history_for_backtest,
)
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

STABLE_NI_RULES = (
    "Pre-registered DefiLlama stablecoin net-issuance SPOT overlay (frozen "
    "before any pull/score). Feature = UTC-daily Δ totalCirculatingUSD.peggedUSD "
    f"on /stablecoincharts/all; non-consecutive days skipped; LAG_DAYS={LAG_DAYS}. "
    "FeatureZVoter lookback=20; fade/follow at |z|>=1.0/1.5/2.0. Dual-print = "
    "Kraken x Coinbase spot BTC/ETH with the SAME aggregate series. Live API "
    "history is NOT PIT-safe (no as_of; revisions overwrite) — refuse historical "
    "dual-print unless an operator PIT archive is marked pit_safe. Pilot fee "
    "80+5 bps. PAPER_PROMOTE_* stays default false. UNAVAILABLE / empty "
    "dual-print is success."
)

STABLE_NI_CATALOG: tuple[tuple[str, bool, float], ...] = (
    ("stable_ni_fade_1_0", True, 1.0),
    ("stable_ni_fade_1_5", True, 1.5),
    ("stable_ni_fade_2_0", True, 2.0),
    ("stable_ni_follow_1_0", False, 1.0),
    ("stable_ni_follow_1_5", False, 1.5),
    ("stable_ni_follow_2_0", False, 2.0),
)
STABLE_NI_IDS: tuple[str, ...] = tuple(item[0] for item in STABLE_NI_CATALOG)
CONTROL_IDS: frozenset[str] = frozenset({"ma_cross_10_30"})
CORE_IDS: tuple[str, ...] = STABLE_NI_IDS + tuple(sorted(CONTROL_IDS))
REQUIRED_SYMBOLS: tuple[str, ...] = ("BTC/USD", "ETH/USD")
PAPER_PATH_READY = True  # spot long/flat FeatureZ on Kraken OHLC; no perp leg


def issuance_to_symbol_series(
    points: list[StableNetIssuancePoint],
    symbols: tuple[str, ...] = REQUIRED_SYMBOLS,
) -> dict[str, tuple[tuple[datetime, float], ...]]:
    """Broadcast the aggregate series onto each required symbol (frozen)."""
    series = tuple(
        (
            utc_day_open(datetime(p.day.year, p.day.month, p.day.day, tzinfo=UTC)),
            float(p.net_issuance_usd),
        )
        for p in points
    )
    return {symbol.upper(): series for symbol in symbols}


def stable_ni_candidates(
    *,
    issuance_by_symbol: dict[str, tuple[tuple[datetime, float], ...]] | None,
) -> tuple[SearchCandidate, ...]:
    if not issuance_by_symbol:
        return ()
    out: list[SearchCandidate] = []
    for candidate_id, fade, entry_z in STABLE_NI_CATALOG:
        verb = "fade" if fade else "follow"
        out.append(
            _feature_z_candidate(
                candidate_id=candidate_id,
                family="funding_z",
                feature_name="stable_net_issuance_z",
                label=f"{verb} stable-net-iss z |z|>={entry_z:g}",
                values=None,
                values_by_symbol=issuance_by_symbol,
                fade=fade,
                entry_z=entry_z,
                lookback=Z_LOOKBACK,
            )
        )
    out.append(_ma("ma_cross_10_30", short_window=10, long_window=30))
    return tuple(out)


def skipped_stable_ni_families(
    *,
    reason: str,
) -> list[dict[str, str]]:
    skipped: list[dict[str, str]] = []
    for candidate_id, fade, entry_z in STABLE_NI_CATALOG:
        verb = "fade" if fade else "follow"
        skipped.append(
            {
                "family": "stable_net_iss",
                "candidate_id": candidate_id,
                "reason": (f"{verb} stable-net-iss z |z|>={entry_z:g}: skipped — {reason}"),
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
                report.honesty + " This stable-net-issuance search cannot flip PAPER_PROMOTE_*; "
                "spot overlay dual-print is informational only."
            ),
        }
    )


class StableNetIssuanceReport(BaseModel):
    generated_at: datetime
    print_kind: Literal["single_print", "dual_print", "unavailable"]
    primary_candle_venue: str
    second_candle_venue: str | None = None
    feature_source: str = "defillama_stablecoins"
    interval: str = "1d"
    fee_bps: float
    slippage_bps: float
    keep_flag_false: bool = True
    can_promote: bool = False
    paper_path_ready: bool = PAPER_PATH_READY
    pit_safe: bool = False
    pit_verdict: str = PIT_VERDICT
    lag_days: int = LAG_DAYS
    core_ids: list[str] = Field(default_factory=lambda: list(CORE_IDS))
    control_ids: list[str] = Field(default_factory=lambda: sorted(CONTROL_IDS))
    dual_print_passer_ids: list[str] = Field(default_factory=list)
    dual_print_passers: int = 0
    aligned_bars_primary: int = 0
    aligned_bars_second: int = 0
    rules: str = STABLE_NI_RULES
    history_notes: list[dict[str, str]] = Field(default_factory=list)
    edge_notes: list[dict[str, str]] = Field(default_factory=list)
    skipped: list[dict[str, str]] = Field(default_factory=list)
    primary_search: StrategySearchReport | None = None
    second_search: StrategySearchReport | None = None
    recommended_promote_flag: str | None = None

    def model_dump_json_safe(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


def run_stable_net_issuance(
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
    chart: StablecoinChartSeries | None = None,
    issuance_points: list[StableNetIssuancePoint] | None = None,
    pit_archive_present: bool = False,
    second_histories: dict[str, tuple[Candle, ...]] | None = None,
    primary_candle_venue: str = "kraken",
    second_candle_venue: str | None = "coinbase",
    history_notes: list[dict[str, str]] | None = None,
    now: datetime | None = None,
) -> StableNetIssuanceReport:
    generated = now or datetime.now(UTC)
    notes: list[dict[str, str]] = list(history_notes or [])
    series_pit_safe = bool(chart.pit_safe) if chart is not None else False
    allowed, refuse_reason = refuse_live_history_for_backtest(
        pit_archive_present=pit_archive_present,
        series_pit_safe=series_pit_safe,
    )
    if chart is not None:
        notes.extend(chart.notes)
        notes.append(
            {
                "name": "pit_gate",
                "status": "ok" if allowed else "refused",
                "reason": refuse_reason,
            }
        )
    else:
        notes.append(
            {
                "name": "pit_gate",
                "status": "refused",
                "reason": refuse_reason if not allowed else "no chart series",
            }
        )

    if not allowed:
        return StableNetIssuanceReport(
            generated_at=generated,
            print_kind="unavailable",
            primary_candle_venue=primary_candle_venue,
            second_candle_venue=second_candle_venue,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            pit_safe=False,
            pit_verdict=refuse_reason,
            history_notes=notes,
            edge_notes=[
                {
                    "name": "stable_net_issuance",
                    "status": "unavailable",
                    "reason": refuse_reason,
                }
            ],
            skipped=skipped_stable_ni_families(reason=refuse_reason),
            can_promote=False,
            keep_flag_false=True,
        )

    points = list(issuance_points or [])
    if not points and chart is not None:
        points, iss_notes = net_issuance_from_chart(chart)
        notes.extend(iss_notes)
        as_of = generated.date()
        points = apply_lag(points, as_of=as_of, lag_days=LAG_DAYS)
        notes.append(
            {
                "name": "lag",
                "status": "ok",
                "reason": f"applied LAG_DAYS={LAG_DAYS} as_of={as_of.isoformat()}",
            }
        )

    by_symbol = issuance_to_symbol_series(points) if points else {}
    have = all(
        symbol.upper() in by_symbol and by_symbol[symbol.upper()] for symbol in REQUIRED_SYMBOLS
    )
    if not have:
        return StableNetIssuanceReport(
            generated_at=generated,
            print_kind="unavailable",
            primary_candle_venue=primary_candle_venue,
            second_candle_venue=second_candle_venue,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            pit_safe=series_pit_safe,
            history_notes=notes,
            edge_notes=[
                {
                    "name": "stable_net_issuance",
                    "status": "skipped",
                    "reason": "no net-issuance points after lag/gap filter",
                }
            ],
            skipped=skipped_stable_ni_families(
                reason="no net-issuance points after lag/gap filter"
            ),
        )

    catalog = stable_ni_candidates(issuance_by_symbol=by_symbol)
    sliced = slice_histories_to_funding(histories, by_symbol, None)
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
        second_sliced = slice_histories_to_funding(second_histories, by_symbol, None)
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

    return StableNetIssuanceReport(
        generated_at=generated,
        print_kind=print_kind,
        primary_candle_venue=primary_candle_venue,
        second_candle_venue=second_candle_venue if print_kind == "dual_print" else None,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
        pit_safe=series_pit_safe,
        dual_print_passer_ids=dual_passers,
        dual_print_passers=len(dual_passers),
        aligned_bars_primary=aligned,
        aligned_bars_second=second_aligned,
        history_notes=notes,
        edge_notes=notes,
        skipped=[],
        primary_search=primary_search,
        second_search=second_search,
        can_promote=False,
        keep_flag_false=True,
        recommended_promote_flag=None,
    )


def render_stable_net_issuance_markdown(report: StableNetIssuanceReport) -> str:
    lines: list[str] = [
        "# DefiLlama stablecoin net-issuance SPOT overlay dual-print",
        "",
        f"Generated: {report.generated_at.isoformat()}",
        (
            f"Print kind: **{report.print_kind}**. interval=`{report.interval}`; "
            f"primary_candle=`{report.primary_candle_venue}`; "
            f"second_candle=`{report.second_candle_venue or 'none'}`; "
            f"feature=`{report.feature_source}`; "
            f"pit_safe=`{str(report.pit_safe).lower()}`; "
            f"paper_path_ready=`{str(report.paper_path_ready).lower()}`; "
            f"can_promote=`{str(report.can_promote).lower()}`; "
            f"`keep_flag_false={str(report.keep_flag_false).lower()}`."
        ),
        (f"Core ids={len(report.core_ids)}; dual_print_passers=`{report.dual_print_passers}`."),
        (f"Costs: fee={report.fee_bps:g} bps + slippage={report.slippage_bps:g} bps (pilot spot)."),
        (
            f"Aligned bars: primary={report.aligned_bars_primary}, "
            f"second={report.aligned_bars_second}."
        ),
        "",
        "## What this does / does not claim",
        "",
        (
            "Paper-research catalog of DefiLlama stablecoin net-issuance FeatureZ "
            "voters on spot BTC/ETH. **Not** a live-capital claim, **not** a reason "
            "to flip `PAPER_PROMOTE_*`. UNAVAILABLE / empty dual-print is success."
        ),
        "",
        "## PIT verdict",
        "",
        report.pit_verdict,
        "",
        f"Live history PIT-safe constant: `{PIT_SAFE_LIVE_HISTORY}`. LAG_DAYS=`{report.lag_days}`.",
        "",
        "## Honesty / pre-registered rules",
        "",
        report.rules,
        "",
        "## Pre-registered catalog",
        "",
        "Frozen ids: "
        + ", ".join(f"`{cid}`" for cid in STABLE_NI_IDS)
        + "; control `"
        + "`, `".join(sorted(CONTROL_IDS))
        + "`.",
        "",
        "## Edge / PIT notes",
        "",
    ]
    for note in report.edge_notes:
        lines.append(
            f"- `{note.get('name', '?')}` **{note.get('status', '?')}**: {note.get('reason', '')}"
        )
    if report.history_notes and report.history_notes is not report.edge_notes:
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
    lines.extend(
        [
            "",
            "## Promotion decision",
            "",
            (
                "**No candidate is promoted.** "
                f"print_kind=`{report.print_kind}`; can_promote=`false`; "
                "keep_flag_false=`true`; recommended_promote_flag=`none`. "
                "Leave every `PAPER_PROMOTE_*` false. Do not enable live."
            ),
            "",
            "## Weather pivot",
            "",
            (
                "Because live DefiLlama history is not PIT-safe, the documented "
                "parallel paper path remains Polymarket weather "
                "(`traderstack-polymarket-weather-collect` / "
                "`traderstack-polymarket-weather-eval` on main). Empty weather "
                "print is success; do not invent mids from settlement."
            ),
        ]
    )
    return "\n".join(lines) + "\n"
