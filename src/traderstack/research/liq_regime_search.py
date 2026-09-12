"""Liquidation / regime-conditioned paper search (single-print unless liq exists).

Pre-registered before any live pull (do not retune after seeing PnL).

Investigation (do not invent a series):

* Live paper cycles already attach Binance USDT-M liquidation z and
  optional bookTicker cross-venue mid as ``ResearchEdgeFeatures``.
  ``RiskEngine`` does not read that slice to size, side, or authorise.
* Public historical liquidation REST is typically unusable:
  Binance ``/fapi/v1/allForceOrders`` is recent-only / often HTTP 451;
  Vision ``um/liquidationSnapshot`` was removed; OKX liquidation-orders
  span hours, not 90–180d. ``edge_series`` already records a skip.
* Cross-venue historical divergence is not built from public Spot OHLC.
* Funding / OI public history (OKX, sometimes Binance) may be present
  and is scored when aligned — never zero-filled.

Print policy (frozen):

* Dual-print requires a usable historical liquidation series on BTC and
  ETH **and** a second venue candle print. Absent that, the run is
  **single-print** (Kraken public Spot daily 720) and **cannot promote**.
* ``PAPER_PROMOTE_*`` stays default false. No live. Empty search is
  success. This module never writes a Settings pin.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from traderstack.candles import Candle
from traderstack.research.candidates import (
    FEATURE_CATALOG,
    RegimeAgreeVoter,
    SearchCandidate,
    default_price_candidates,
    expanded_price_candidates,
    feature_candidates,
)
from traderstack.research.miles_candidates import EmaCrossoverStrategy
from traderstack.research.search import (
    CandidateSearchResult,
    StrategySearchReport,
    run_search,
)

RANKING_KEY = "informational_wf_excess_single_print_cannot_promote"
SELECTION_RULE = "pre_registered_top1_informational"
PRINT_SINGLE = "single_print"
PRINT_DUAL = "dual_print"

REQUIRED_LIQ_SYMBOLS = ("BTC/USD", "ETH/USD")
MIN_LIQ_POINTS = 20
MIN_SECOND_VENUE_BARS = 360

LIQ_REGIME_CORE_IDS: tuple[str, ...] = (
    "ma_cross_10_30_vol",
    "ma_always_on_10_30_vol",
    "momentum_6_vol",
    "momentum_12_vol",
    "mean_reversion_20_1_5_vol",
    "mean_reversion_20_2_0_vol",
    "ma_cross_10_30",
    "momentum_12",
    "mean_reversion_20_1_5",
)
CONTROL_IDS: frozenset[str] = frozenset({"ma_cross_10_30", "momentum_12", "mean_reversion_20_1_5"})

EMA_LIQ_AGREE_CATALOG: tuple[tuple[str, str, str, int, int, float | None], ...] = (
    ("liquidation_z", "ema_9_21_liq_agree", "EMA 9/21 (liquidation-z must agree)", 9, 21, None),
    (
        "liquidation_z",
        "ema_9_21_adx15_liq_agree",
        "EMA 9/21 ADX>15 (liquidation-z must agree)",
        9,
        21,
        15.0,
    ),
    (
        "liquidation_z",
        "ema_12_26_liq_agree",
        "EMA 12/26 (liquidation-z must agree)",
        12,
        26,
        None,
    ),
)

LIQ_REGIME_RULES = (
    "Pre-registered liquidation/regime-conditioned search (frozen before "
    "any Kraken or edge-series pull). Candle-only vol-regime wrappers are "
    "always scored. Unconditioned MA / momentum / mean-reversion controls "
    "are informational and cannot promote. Liquidation-z, funding-z, OI-z, "
    "and cross-venue families instantiate only when an aligned historical "
    "series is supplied — never zero-filled. Public USDT-M liquidation REST "
    "is typically unusable (allForceOrders recent-only / geo-blocked; Vision "
    "um/liquidationSnapshot removed; live WS is !forceOrder@arr). Dual-print "
    "requires a usable historical liquidation series on BTC and ETH AND a "
    "second venue candle print. Absent that, this run is SINGLE-PRINT "
    "(Kraken public Spot daily 720-bar cap) and cannot promote. "
    "PAPER_PROMOTE_* stays default false. No live. Empty search is success."
)

LIQ_REGIME_CATALOG_NOTE = (
    "Frozen core (K=9): six vol-regime-agree price voters plus three "
    "unconditioned controls (ma_cross_10_30, momentum_12, "
    "mean_reversion_20_1_5). Optional families when a series is present: "
    "liquidation_z fade/follow + liq-agree wrappers on those three inners "
    "and on ema_9_21 / ema_9_21_adx15 / ema_12_26; funding_z fade/follow; "
    "oi_z fade/follow; cross_venue_fade. Do not grow this list after "
    "seeing PnL. Live paper liquidation / bookTicker snapshots are not a "
    "historical series and are not backfilled."
)


def _symbol_key(symbol: str) -> str:
    return symbol.upper()


def _lookup_series(
    mapping: dict[str, tuple[tuple[datetime, float], ...]] | None,
    symbol: str,
) -> tuple[tuple[datetime, float], ...] | None:
    if not mapping:
        return None
    key = _symbol_key(symbol)
    if key in mapping:
        return mapping[key]
    for name, series in mapping.items():
        if _symbol_key(name) == key:
            return series
    return None


def historical_liquidation_usable(
    liquidation: tuple[tuple[datetime, float], ...] | None = None,
    liquidation_by_symbol: dict[str, tuple[tuple[datetime, float], ...]] | None = None,
    *,
    required: tuple[str, ...] = REQUIRED_LIQ_SYMBOLS,
    min_points: int = MIN_LIQ_POINTS,
) -> bool:
    """True only when every required symbol has an aligned historical series."""
    if liquidation_by_symbol:
        for symbol in required:
            series = _lookup_series(liquidation_by_symbol, symbol)
            if series is None or len(series) < min_points:
                return False
        return True
    return liquidation is not None and len(liquidation) >= min_points


def second_venue_usable(
    histories: dict[str, tuple[Candle, ...]] | None,
    *,
    required: tuple[str, ...] = REQUIRED_LIQ_SYMBOLS,
    min_bars: int = MIN_SECOND_VENUE_BARS,
) -> bool:
    if not histories:
        return False
    found: dict[str, int] = {}
    for candles in histories.values():
        if not candles:
            continue
        found[_symbol_key(candles[0].symbol)] = max(
            found.get(_symbol_key(candles[0].symbol), 0), len(candles)
        )
    return all(found.get(_symbol_key(symbol), 0) >= min_bars for symbol in required)


def liq_regime_core_candidates() -> tuple[SearchCandidate, ...]:
    """Frozen candle-only core. Vol-regime wrappers + unconditioned controls."""
    expanded = {item.candidate_id: item for item in expanded_price_candidates()}
    defaults = {item.candidate_id: item for item in default_price_candidates()}
    combined = {**defaults, **expanded}
    missing = [item for item in LIQ_REGIME_CORE_IDS if item not in combined]
    if missing:
        raise ValueError(f"liq-regime core ids missing from price catalog: {missing}")
    return tuple(combined[item] for item in LIQ_REGIME_CORE_IDS)


def _any_liq_series(
    liquidation: tuple[tuple[datetime, float], ...] | None,
    liquidation_by_symbol: dict[str, tuple[tuple[datetime, float], ...]] | None,
) -> bool:
    if liquidation is not None and len(liquidation) >= MIN_LIQ_POINTS:
        return True
    if liquidation_by_symbol:
        return any(len(series) >= MIN_LIQ_POINTS for series in liquidation_by_symbol.values())
    return False


def ema_liq_agree_candidates(
    *,
    liquidation: tuple[tuple[datetime, float], ...] | None = None,
    liquidation_by_symbol: dict[str, tuple[tuple[datetime, float], ...]] | None = None,
) -> tuple[SearchCandidate, ...]:
    """EMA daily names wrapped so liquidation-z must agree. Skip if no series."""
    if not _any_liq_series(liquidation, liquidation_by_symbol):
        return ()
    by_symbol: tuple[tuple[str, tuple[tuple[datetime, float], ...]], ...] = ()
    if liquidation_by_symbol:
        by_symbol = tuple(
            (key.upper(), values) for key, values in sorted(liquidation_by_symbol.items())
        )
    out: list[SearchCandidate] = []
    for _family, candidate_id, label, fast, slow, adx in EMA_LIQ_AGREE_CATALOG:
        inner = EmaCrossoverStrategy(
            strategy_id=f"{candidate_id}_inner",
            fast_span=fast,
            slow_span=slow,
            adx_threshold=adx,
        )
        params = {
            "strategy_id": candidate_id,
            "inner_strategy_id": f"{candidate_id}_inner",
            "fast_span": fast,
            "slow_span": slow,
            "adx_threshold": adx,
            "vol_regime_filter": False,
            "liq_agree": True,
        }
        out.append(
            SearchCandidate(
                candidate_id=candidate_id,
                family="liquidation_z",
                label=label,
                params=params,
                strategy=RegimeAgreeVoter(
                    inner=inner,
                    strategy_id=candidate_id,
                    family="ma_cross",
                    vol_filter=False,
                    liquidation=liquidation or (),
                    liquidation_by_symbol=by_symbol,
                ),
                requires_feature="liquidation_z",
            )
        )
    return tuple(out)


def skipped_optional_families(
    *,
    liquidation: tuple[tuple[datetime, float], ...] | None,
    liquidation_by_symbol: dict[str, tuple[tuple[datetime, float], ...]] | None,
    funding: tuple[tuple[datetime, float], ...] | None,
    funding_by_symbol: dict[str, tuple[tuple[datetime, float], ...]] | None,
    open_interest: tuple[tuple[datetime, float], ...] | None,
    open_interest_by_symbol: dict[str, tuple[tuple[datetime, float], ...]] | None,
    cross_venue: tuple[tuple[datetime, float], ...] | None,
) -> list[dict[str, str]]:
    present = {
        *(["liquidation_z"] if liquidation is not None or liquidation_by_symbol else []),
        *(["funding_z"] if funding is not None or funding_by_symbol else []),
        *(["open_interest_z"] if open_interest is not None or open_interest_by_symbol else []),
        *(["cross_venue_divergence_z"] if cross_venue is not None else []),
    }
    skipped = [
        {
            "family": family,
            "candidate_id": candidate_id,
            "reason": (
                f"{label}: skipped — no aligned series supplied. "
                "This feature is not present on the Kraken Spot OHLC paper path."
            ),
        }
        for family, candidate_id, label in FEATURE_CATALOG
        if (family == "liquidation_z" and "liquidation_z" not in present)
        or (family == "funding_z" and "funding_z" not in present)
        or (family == "open_interest_z" and "open_interest_z" not in present)
        or (family == "cross_venue" and "cross_venue_divergence_z" not in present)
    ]
    if "liquidation_z" not in present:
        for family, candidate_id, label, *_rest in EMA_LIQ_AGREE_CATALOG:
            skipped.append(
                {
                    "family": family,
                    "candidate_id": candidate_id,
                    "reason": (
                        f"{label}: skipped — no aligned historical liquidation "
                        "series. Live WS !forceOrder@arr is not a backtest input."
                    ),
                }
            )
    return skipped


def _clear_promotion(report: StrategySearchReport) -> StrategySearchReport:
    """This CLI never promotes. Inner #89 eligible rows stay informational."""
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
                report.honesty + " This liquidation/regime search is single-print unless a "
                "historical liquidation series and a second venue print both "
                "exist; it cannot flip PAPER_PROMOTE_*."
            ),
        }
    )


class LiqRegimeSearchReport(BaseModel):
    generated_at: datetime
    print_kind: Literal["single_print", "dual_print"]
    historical_liquidation: bool
    second_venue: bool
    can_promote: bool
    keep_flag_false: bool = True
    ranking_key: str = RANKING_KEY
    selection_rule: str = SELECTION_RULE
    honesty: str
    catalog_note: str
    print_rules: str
    core_ids: list[str]
    scored_ids: list[str]
    control_ids: list[str]
    skipped_feature_families: list[dict[str, str]] = Field(default_factory=list)
    edge_notes: list[dict[str, str]] = Field(default_factory=list)
    history_notes: list[dict[str, str]] = Field(default_factory=list)
    search: StrategySearchReport
    second_print_search: StrategySearchReport | None = None
    selected_candidate_id: str | None = None
    dual_print_passer_ids: list[str] = Field(default_factory=list)
    any_promoted: bool = False
    promoted_candidate_ids: list[str] = Field(default_factory=list)
    recommended_promote_flag: str | None = None


def run_liq_regime_search(
    histories: dict[str, tuple[Candle, ...]],
    *,
    fee_bps: float,
    slippage_bps: float = 5.0,
    starting_equity: float = 10_000.0,
    warmup: int = 31,
    train_size: int = 180,
    test_size: int = 60,
    step_size: int = 60,
    holdout_fraction: float = 0.20,
    min_trades: int = 3,
    liquidation: tuple[tuple[datetime, float], ...] | None = None,
    liquidation_by_symbol: dict[str, tuple[tuple[datetime, float], ...]] | None = None,
    funding: tuple[tuple[datetime, float], ...] | None = None,
    funding_by_symbol: dict[str, tuple[tuple[datetime, float], ...]] | None = None,
    open_interest: tuple[tuple[datetime, float], ...] | None = None,
    open_interest_by_symbol: dict[str, tuple[tuple[datetime, float], ...]] | None = None,
    cross_venue: tuple[tuple[datetime, float], ...] | None = None,
    second_venue_histories: dict[str, tuple[Candle, ...]] | None = None,
    min_second_venue_bars: int = MIN_SECOND_VENUE_BARS,
    history_notes: list[dict[str, str]] | None = None,
    edge_notes: list[dict[str, str]] | None = None,
    now: datetime | None = None,
) -> LiqRegimeSearchReport:
    if not histories:
        raise ValueError("no candle histories provided")

    have_liq = historical_liquidation_usable(liquidation, liquidation_by_symbol)
    have_second = second_venue_usable(second_venue_histories, min_bars=min_second_venue_bars)
    print_kind: Literal["single_print", "dual_print"]
    if have_liq and have_second:
        print_kind = "dual_print"
    else:
        print_kind = "single_print"

    extra = ema_liq_agree_candidates(
        liquidation=liquidation, liquidation_by_symbol=liquidation_by_symbol
    )
    core = liq_regime_core_candidates()
    catalog = core + extra
    scored_ids = [item.candidate_id for item in catalog]
    scored_ids.extend(
        item.candidate_id
        for item in feature_candidates(
            liquidation=liquidation,
            liquidation_by_symbol=liquidation_by_symbol,
            funding=funding,
            funding_by_symbol=funding_by_symbol,
            open_interest=open_interest,
            open_interest_by_symbol=open_interest_by_symbol,
            cross_venue=cross_venue,
        )
    )

    search = run_search(
        histories,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
        starting_equity=starting_equity,
        warmup=warmup,
        train_size=train_size,
        test_size=test_size,
        step_size=step_size,
        holdout_fraction=holdout_fraction,
        min_trades=min_trades,
        candidates=catalog,
        liquidation=liquidation,
        liquidation_by_symbol=liquidation_by_symbol,
        funding=funding,
        funding_by_symbol=funding_by_symbol,
        open_interest=open_interest,
        open_interest_by_symbol=open_interest_by_symbol,
        cross_venue=cross_venue,
        history_notes=history_notes,
        edge_notes=edge_notes,
        now=now,
    )
    search = _clear_promotion(search)

    second_search: StrategySearchReport | None = None
    dual_passers: list[str] = []
    if print_kind == PRINT_DUAL and second_venue_histories:
        second_search = _clear_promotion(
            run_search(
                second_venue_histories,
                fee_bps=fee_bps,
                slippage_bps=slippage_bps,
                starting_equity=starting_equity,
                warmup=warmup,
                train_size=train_size,
                test_size=test_size,
                step_size=step_size,
                holdout_fraction=holdout_fraction,
                min_trades=min_trades,
                candidates=catalog,
                liquidation=liquidation,
                liquidation_by_symbol=liquidation_by_symbol,
                funding=funding,
                funding_by_symbol=funding_by_symbol,
                open_interest=open_interest,
                open_interest_by_symbol=open_interest_by_symbol,
                cross_venue=cross_venue,
                now=now,
            )
        )
        second_eligible = {
            row.candidate_id
            for row in second_search.candidates
            if row.eligible and row.candidate_id not in CONTROL_IDS
        }
        dual_passers = [
            row.candidate_id
            for row in search.candidates
            if row.eligible
            and row.candidate_id in second_eligible
            and row.candidate_id not in CONTROL_IDS
        ]

    # Single-print cannot promote. Dual-print passers would only justify a
    # documented default-false pin — this command still does not flip flags.
    can_promote = False
    skipped = skipped_optional_families(
        liquidation=liquidation,
        liquidation_by_symbol=liquidation_by_symbol,
        funding=funding,
        funding_by_symbol=funding_by_symbol,
        open_interest=open_interest,
        open_interest_by_symbol=open_interest_by_symbol,
        cross_venue=cross_venue,
    )
    selected = search.selected_candidate_id
    honesty = LIQ_REGIME_RULES
    if print_kind == PRINT_SINGLE:
        honesty += (
            " This run is labeled SINGLE-PRINT and cannot promote, even if a "
            "vol-regime or funding/OI row would clear the #89 fee-aware bar."
        )
    if not have_liq:
        honesty += (
            " No usable historical liquidation series — liquidation-z voters "
            "were skipped, not zero-filled."
        )
    if dual_passers:
        honesty += (
            f" Dual-print eligible names ({', '.join(dual_passers)}) are "
            "informational only; leave every PAPER_PROMOTE_* false."
        )

    return LiqRegimeSearchReport(
        generated_at=search.generated_at,
        print_kind=print_kind,
        historical_liquidation=have_liq,
        second_venue=have_second,
        can_promote=can_promote,
        keep_flag_false=True,
        honesty=honesty,
        catalog_note=LIQ_REGIME_CATALOG_NOTE,
        print_rules=LIQ_REGIME_RULES,
        core_ids=list(LIQ_REGIME_CORE_IDS),
        scored_ids=scored_ids,
        control_ids=sorted(CONTROL_IDS),
        skipped_feature_families=skipped,
        edge_notes=list(edge_notes or []),
        history_notes=list(history_notes or []),
        search=search,
        second_print_search=second_search,
        selected_candidate_id=selected,
        dual_print_passer_ids=dual_passers,
        any_promoted=False,
        promoted_candidate_ids=[],
        recommended_promote_flag=None,
    )


def _pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:+.2%}"


def _row_by_id(report: StrategySearchReport, candidate_id: str) -> CandidateSearchResult | None:
    for row in report.candidates:
        if row.candidate_id == candidate_id:
            return row
    return None


def render_liq_regime_markdown(report: LiqRegimeSearchReport) -> str:
    lines: list[str] = [
        "# Liquidation / regime-conditioned strategy search",
        "",
        f"Generated: {report.generated_at.isoformat()}",
        (
            f"Print kind: **{report.print_kind}**. "
            f"`historical_liquidation={str(report.historical_liquidation).lower()}`; "
            f"`second_venue={str(report.second_venue).lower()}`; "
            f"`can_promote={str(report.can_promote).lower()}`; "
            f"`keep_flag_false={str(report.keep_flag_false).lower()}`."
        ),
        (
            f"Core K={len(report.core_ids)}; scored ids={len(report.scored_ids)}; "
            f"ranking_key=`{report.ranking_key}` (informational)."
        ),
        (
            f"Costs: fee={report.search.fee_bps:g} bps + "
            f"slippage={report.search.slippage_bps:g} bps "
            f"({report.search.cost_note})"
        ),
        (
            f"Walk-forward: train={report.search.train_size} "
            f"test={report.search.test_size} step={report.search.step_size}; "
            f"holdout_fraction={report.search.holdout_fraction:.0%}."
        ),
        "",
        "## What this does / does not claim",
        "",
        (
            "This is a paper-research catalog search conditioned on "
            "liquidation-z / funding-z / OI-z / cross-venue series when those "
            "series exist, plus candle-only vol-regime wrappers that always "
            "score. It is **not** a live-capital claim, not a PnL forecast, "
            "and not a reason to flip `PAPER_PROMOTE_*` or `TRADING_MODE`."
        ),
        "",
        (
            "Crucix already maps high-tier alerts to `NewsSnapshot.adverse_event` "
            "and the pipeline already rejects with `adverse_news_event` when "
            "`INTELLIGENCE_BLOCK_ON_ADVERSE_NEWS=true`. That path was not "
            "changed here. Live liquidation / bookTicker features stay "
            "research context on the paper cycle; they do not size or side."
        ),
        "",
        "## Honesty / pre-registered rules",
        "",
        report.honesty,
        "",
        "## Print policy (frozen before scoring)",
        "",
        report.print_rules,
        "",
        "| print | when | can promote? |",
        "| --- | --- | --- |",
        (
            "| single-print | no usable historical liquidation series on "
            "BTC+ETH, or no second venue candle print | **no** |"
        ),
        (
            "| dual-print | historical liquidation series on BTC and ETH "
            "**and** a second venue print | still **no** Settings flip; "
            "a passer would only justify a documented default-false pin |"
        ),
        "",
        "## Pre-registered catalog",
        "",
        report.catalog_note,
        "",
        f"Frozen core ids: {', '.join(f'`{item}`' for item in report.core_ids)}.",
        "",
        "Unconditioned controls (cannot promote): "
        + ", ".join(f"`{item}`" for item in report.control_ids)
        + ".",
        "",
        "## Data",
        "",
    ]
    if report.history_notes:
        for item in report.history_notes:
            detail = item.get("note") or item.get("reason") or ""
            symbol = item.get("symbol") or item.get("name") or ""
            if symbol and symbol != "?":
                lines.append(
                    f"- `{symbol}` {item.get('interval', '')} "
                    f"source={item.get('source', '?')} "
                    f"n={item.get('candles', item.get('candle_count', '?'))}"
                    + (f" — {detail}" if detail else "")
                )
            elif detail:
                lines.append(f"- {detail}")
    else:
        lines.append("- (no history notes)")

    lines.extend(["", "## Edge series", ""])
    if report.edge_notes:
        for item in report.edge_notes:
            lines.append(
                f"- `{item.get('name', '?')}` **{item.get('status', '?')}**: "
                f"{item.get('reason', '')} (source={item.get('source', '')}, "
                f"points={item.get('points', '0')})"
            )
    else:
        lines.append(
            "- No edge-series fetch notes. Liquidation / funding / OI / "
            "cross-venue families were not supplied."
        )

    if report.skipped_feature_families:
        lines.extend(["", "## Skipped optional families", ""])
        for item in report.skipped_feature_families:
            lines.append(f"- `{item['candidate_id']}` ({item['family']}): {item['reason']}")

    lines.extend(
        [
            "",
            "## Ranked candidates (walk-forward mean excess after fees)",
            "",
            "Informational. Eligible under the #89 fee-aware bar does not mean promoted.",
            "Controls cannot promote.",
            "",
            "| rank | id | family | WF excess | WF total | holdout excess | eligible | control |",
            "| ---: | --- | --- | ---: | ---: | ---: | :---: | :---: |",
        ]
    )
    ordered = sorted(
        report.search.candidates,
        key=lambda row: (
            row.rank is None,
            row.rank if row.rank is not None else 10_000,
            row.candidate_id,
        ),
    )
    for row in ordered:
        rank = str(row.rank) if row.rank is not None else "—"
        control = "yes" if row.candidate_id in CONTROL_IDS else "no"
        lines.append(
            f"| {rank} | `{row.candidate_id}` | {row.family} | "
            f"{_pct(row.mean_wf_excess_return)} | "
            f"{_pct(row.mean_wf_total_return)} | "
            f"{_pct(row.mean_holdout_excess_return)} | "
            f"{'yes' if row.eligible else 'no'} | {control} |"
        )

    lines.extend(["", "## Dual-print passers", ""])
    if report.print_kind != PRINT_DUAL:
        lines.append("Not a dual-print run. A Kraken-only (or funding/OI-only) row cannot promote.")
    elif not report.dual_print_passer_ids:
        lines.append(
            "Dual-print was eligible (historical liq + second venue) but "
            "no conditioned name cleared the #89 bar on **both** prints. "
            "Empty set is success."
        )
    else:
        lines.append(
            "Names that cleared the #89 bar on both prints (informational; "
            "no Settings pin): "
            + ", ".join(f"`{item}`" for item in report.dual_print_passer_ids)
            + "."
        )
        if report.second_print_search is not None:
            lines.extend(
                [
                    "",
                    "| id | Kraken HO | second-venue HO |",
                    "| --- | ---: | ---: |",
                ]
            )
            for candidate_id in report.dual_print_passer_ids:
                kraken_row = _row_by_id(report.search, candidate_id)
                other_row = _row_by_id(report.second_print_search, candidate_id)
                lines.append(
                    f"| `{candidate_id}` | "
                    f"{_pct(kraken_row.mean_holdout_excess_return if kraken_row else None)} | "
                    f"{_pct(other_row.mean_holdout_excess_return if other_row else None)} |"
                )

    lines.extend(
        [
            "",
            "## Promotion decision",
            "",
            (
                "**No candidate is promoted.** "
                f"print_kind=`{report.print_kind}`; "
                f"can_promote=`{str(report.can_promote).lower()}`; "
                "recommended_promote_flag=`none`. "
                "Leave every `PAPER_PROMOTE_*` false. Do not add a new pin. "
                "Do not enable live."
            ),
        ]
    )
    if report.selected_candidate_id:
        selected = _row_by_id(report.search, report.selected_candidate_id)
        if selected is not None:
            lines.append(
                f"Informational top-1 by WF excess was `{selected.candidate_id}` "
                f"(WF excess={_pct(selected.mean_wf_excess_return)}, "
                f"WF total={_pct(selected.mean_wf_total_return)}, "
                f"holdout excess={_pct(selected.mean_holdout_excess_return)}; "
                f"eligible={selected.eligible})."
            )
    lines.append("")
    return "\n".join(lines)
