"""Fee-aware Polymarket weather evaluation (report-only; no promotion).

Implements the calculator for gates 1 / 4 / 5 in
``docs/EVALUATION-FRAMEWORK.md`` ("Polymarket weather — validation A/B").
It does **not** claim the edge is real. Empty or negative results are
success. This module never writes a ``PAPER_PROMOTE_*`` pin and never
submits CLOB orders.

Print policy (frozen before any score):

* A row is eligible only when the city is allowlisted, the forecast and
  mid are point-in-time (issued before market close), the official
  station high is paired (gate 4), and the mid is inside the paper
  module's ``[min_mid, max_mid]`` band.
* Treatment (A) is the #44 NWP-vs-mid rule: trade only when
  ``|model − mid| − fee_haircut >= min_edge``.
* Controls (B): ``always_hold`` (0) and ``fade_the_mid`` (opposite side
  on the same trade mask, same conservative costs).
* Primary costs are conservative: fill at mid ± half-spread, then
  subtract the documented taker-fee haircut. Fill-at-mid is reported
  and is forbidden as the promotion metric (gate 5).
* Dual independent prints are required before anyone may talk about
  promotion. Independence is non-overlapping ``event_date`` sets **or**
  overlapping dates with disjoint resolution sources. A single print
  cannot promote even if treatment excess is positive.
* A pre-registered crypto overlay (``polymarket_weather_vs_btc_daily``)
  is scored only when an aligned BTC daily close series is supplied.
  Missing series is skipped, never invented.

Gate 2 (walk-forward parameter fit) and gate 3 (a full season of live
paper A/B) are **not** claimed here. Holdout on a dated split is
reported when ``n`` clears the pre-registered floor; parameters stay
frozen at Settings / CLI defaults.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from traderstack.polymarket.cities import DEFAULT_CITY_SLUGS
from traderstack.polymarket.edge import calculate_edge
from traderstack.polymarket.models import (
    ContractSide,
    ForecastPoint,
    ParsedTemperatureMarket,
    TemperatureContract,
)

PRINT_SINGLE = "single_print"
PRINT_DUAL = "dual_print"
CRYPTO_OVERLAY_ID = "polymarket_weather_vs_btc_daily"
STRATEGY_ID = "polymarket_weather_nwp_edge"
DEFAULT_PROMOTE_FLAG = "PAPER_PROMOTE_POLYMARKET_WEATHER"
CAN_ENTER_PROMOTION_AVERAGE = False
MULTI_PRINT_BAR_PREREGISTERED = True
MIN_ELIGIBLE_PER_PRINT = 20
MIN_TRADES_PER_PRINT = 8
MIN_ROWS_FOR_HOLDOUT = 10
DEFAULT_HALF_SPREAD = 0.01
DEFAULT_HOLD_FRACTION = 0.20

WEATHER_EVAL_RULES = (
    "Pre-registered Polymarket weather evaluation (frozen before any "
    "resolved-row score). (1) Universe is the #44 warm/stable city "
    f"allowlist ({', '.join(DEFAULT_CITY_SLUGS)}); unknown slugs are "
    "dropped, not researched. (2) Point-in-time only: forecast_issued_at "
    "must be strictly before close_at. (3) Station match: official_high_f "
    "+ station_id required or the row is dropped (gate 4). (4) Treatment "
    "is the #44 NWP Normal(high, sigma_f) vs CLOB mid rule; trade only "
    "when net_edge >= min_edge after fee_haircut. (5) Controls: "
    "always_hold and fade_the_mid on the same trade mask. (6) Primary "
    "PnL is conservative (mid ± half-spread − documented taker-fee "
    "haircut). Mid-fill is reported and cannot promote (gate 5). "
    f"(7) Dual independent prints required (MULTI_PRINT_BAR_PREREGISTERED="
    f"{str(MULTI_PRINT_BAR_PREREGISTERED).lower()}). Independence = "
    "non-overlapping event_date sets or overlapping dates with disjoint "
    "resolution sources. (8) "
    f"MIN_ELIGIBLE_PER_PRINT={MIN_ELIGIBLE_PER_PRINT}, "
    f"MIN_TRADES_PER_PRINT={MIN_TRADES_PER_PRINT}. "
    f"(9) CAN_ENTER_PROMOTION_AVERAGE="
    f"{str(CAN_ENTER_PROMOTION_AVERAGE).lower()}. "
    f"`{DEFAULT_PROMOTE_FLAG}` is not a Settings field and is not added. "
    "Every existing PAPER_PROMOTE_* stays default false. No live. "
    "Empty / negative is success. (10) Crypto overlay "
    f"`{CRYPTO_OVERLAY_ID}` is skipped unless an aligned BTC daily "
    "close series is supplied — never invented."
)


class ResolvedWeatherRow(BaseModel):
    """One resolved weather contract. External / fixture input; untrusted."""

    market_id: str
    city_slug: str
    event_date: date
    contract: TemperatureContract
    threshold_f: float | None = None
    bucket_low_f: float | None = None
    bucket_high_f: float | None = None
    forecast_high_f: float
    forecast_source: Literal["open_meteo", "noaa", "fixture"] = "fixture"
    forecast_issued_at: datetime
    market_mid: float = Field(ge=0, le=1)
    half_spread: float | None = Field(default=None, ge=0, lt=1)
    official_high_f: float | None = None
    station_id: str | None = None
    resolution_source: str = "missing"
    yes_resolved: bool | None = None
    close_at: datetime
    print_id: str = "print_a"
    question: str = ""


class DailyClose(BaseModel):
    opened_at: datetime
    close: float = Field(gt=0)


class RowDisposition(BaseModel):
    market_id: str
    print_id: str
    city_slug: str
    event_date: date
    status: str
    reason: str = ""
    side: ContractSide | None = None
    net_edge: float | None = None
    conservative_pnl: float | None = None
    fade_pnl: float | None = None
    midfill_pnl: float | None = None
    yes_resolved: bool | None = None


class PrintMetrics(BaseModel):
    print_id: str
    n_rows: int
    n_city_blocked: int
    n_lookahead_dropped: int
    n_station_dropped: int
    n_mid_dropped: int
    n_unparsed: int
    n_eligible: int
    n_would_trade: int
    n_below_edge: int
    treatment_pnl: float
    fade_pnl: float
    hold_pnl: float
    midfill_treatment_pnl: float
    treatment_excess_vs_hold: float
    treatment_excess_vs_fade: float
    midfill_excess_vs_hold: float
    holdout_n: int | None = None
    holdout_would_trade: int | None = None
    holdout_treatment_excess_vs_hold: float | None = None
    holdout_treatment_excess_vs_fade: float | None = None
    fail_closed_reason: str | None = None
    used_mid_fill_as_primary: bool = False
    half_spread_default_used: int = 0


class CryptoOverlayResult(BaseModel):
    candidate_id: str = CRYPTO_OVERLAY_ID
    status: Literal["skipped", "scored"]
    reason: str
    n_signal_days: int = 0
    n_aligned: int = 0
    pnl_after_fees: float | None = None
    can_promote: bool = False


class WeatherEvalReport(BaseModel):
    honesty: str = WEATHER_EVAL_RULES
    print_kind: Literal["single_print", "dual_print"]
    independent: bool
    independence_reason: str
    prints: list[PrintMetrics]
    crypto_overlay: CryptoOverlayResult
    can_promote: bool
    can_enter_promotion_average: bool = CAN_ENTER_PROMOTION_AVERAGE
    keep_flag_false: bool = True
    recommended_promote_flag: str = "none"
    min_edge: float
    fee_haircut: float
    sigma_f: float
    default_half_spread: float
    holdout_fraction: float
    allowlist: tuple[str, ...]
    dispositions: list[RowDisposition] = Field(default_factory=list)
    data_notes: list[str] = Field(default_factory=list)


def _clip01(value: float) -> float:
    return min(1.0, max(0.0, value))


def yes_won(row: ResolvedWeatherRow) -> bool | None:
    if row.yes_resolved is not None:
        return row.yes_resolved
    if row.official_high_f is None:
        return None
    high = row.official_high_f
    if row.contract is TemperatureContract.THRESHOLD_OR_HIGHER:
        if row.threshold_f is None:
            return None
        return high >= row.threshold_f
    # --- polymarket weather PIT tape (#141) ---
    if row.contract is TemperatureContract.THRESHOLD_OR_LOWER:
        if row.threshold_f is None:
            return None
        return high <= row.threshold_f
    if row.bucket_low_f is None or row.bucket_high_f is None:
        return None
    return row.bucket_low_f <= high <= row.bucket_high_f


def _as_market(row: ResolvedWeatherRow) -> ParsedTemperatureMarket:
    return ParsedTemperatureMarket(
        market_id=row.market_id,
        question=row.question or row.market_id,
        city_slug=row.city_slug,
        city_name=row.city_slug,
        event_date=row.event_date,
        contract=row.contract,
        threshold_f=row.threshold_f,
        bucket_low_f=row.bucket_low_f,
        bucket_high_f=row.bucket_high_f,
        yes_token_id="eval-yes",
        no_token_id="eval-no",
        end_at=row.close_at,
    )


def _as_forecast(row: ResolvedWeatherRow, *, sigma_f: float) -> ForecastPoint:
    source: Literal["open_meteo", "noaa"] = (
        row.forecast_source if row.forecast_source in {"open_meteo", "noaa"} else "open_meteo"
    )
    return ForecastPoint(
        city_slug=row.city_slug,
        event_date=row.event_date,
        high_f=row.forecast_high_f,
        source=source,
        issued_at=row.forecast_issued_at,
        sigma_f=sigma_f,
    )


def conservative_entry(side: ContractSide, mid: float, half_spread: float) -> float:
    if side is ContractSide.YES:
        return _clip01(mid + half_spread)
    return _clip01((1.0 - mid) + half_spread)


def realized_pnl(entry: float, *, won: bool, fee_haircut: float) -> float:
    gross = (1.0 - entry) if won else (-entry)
    return gross - fee_haircut


def _row_reason(
    row: ResolvedWeatherRow,
    *,
    allowlist: tuple[str, ...],
    min_mid: float,
    max_mid: float,
) -> str | None:
    if row.city_slug not in allowlist:
        return "city_blocked"
    if row.forecast_issued_at >= row.close_at:
        return "lookahead"
    if not row.station_id or row.station_id.strip() == "" or row.official_high_f is None:
        return "station_unmatched"
    if not (min_mid <= row.market_mid <= max_mid):
        return "mid_out_of_bounds"
    if row.contract is TemperatureContract.THRESHOLD_OR_HIGHER and row.threshold_f is None:
        return "unparsed"
    # --- polymarket weather PIT tape (#141) ---
    if row.contract is TemperatureContract.THRESHOLD_OR_LOWER and row.threshold_f is None:
        return "unparsed"
    if row.contract is TemperatureContract.BUCKET and (
        row.bucket_low_f is None or row.bucket_high_f is None
    ):
        return "unparsed"
    if yes_won(row) is None:
        return "unparsed"
    return None


def prints_independent(
    print_a: tuple[ResolvedWeatherRow, ...],
    print_b: tuple[ResolvedWeatherRow, ...],
) -> tuple[bool, str]:
    if not print_a or not print_b:
        return False, "missing_print"
    dates_a = {row.event_date for row in print_a}
    dates_b = {row.event_date for row in print_b}
    overlap = dates_a & dates_b
    if not overlap:
        return True, "non_overlapping_event_dates"
    sources_a = {
        row.resolution_source
        for row in print_a
        if row.event_date in overlap and row.resolution_source not in {"", "missing"}
    }
    sources_b = {
        row.resolution_source
        for row in print_b
        if row.event_date in overlap and row.resolution_source not in {"", "missing"}
    }
    if sources_a and sources_b and sources_a.isdisjoint(sources_b):
        return True, "overlapping_dates_independent_resolution_sources"
    return False, "overlapping_dates_same_or_missing_resolution_source"


def _score_rows(
    rows: tuple[ResolvedWeatherRow, ...],
    *,
    min_edge: float,
    fee_haircut: float,
    sigma_f: float,
    default_half_spread: float,
    holdout_fraction: float,
    allowlist: tuple[str, ...],
    min_mid: float,
    max_mid: float,
    print_id: str,
) -> tuple[PrintMetrics, list[RowDisposition]]:
    counts = {
        "city_blocked": 0,
        "lookahead": 0,
        "station_unmatched": 0,
        "mid_out_of_bounds": 0,
        "unparsed": 0,
    }
    dispositions: list[RowDisposition] = []
    eligible: list[tuple[ResolvedWeatherRow, RowDisposition]] = []
    half_spread_default_used = 0

    for row in rows:
        reason = _row_reason(row, allowlist=allowlist, min_mid=min_mid, max_mid=max_mid)
        if reason is not None:
            counts[reason] = counts.get(reason, 0) + 1
            dispositions.append(
                RowDisposition(
                    market_id=row.market_id,
                    print_id=print_id,
                    city_slug=row.city_slug,
                    event_date=row.event_date,
                    status=reason,
                    reason=reason,
                )
            )
            continue
        try:
            edge = calculate_edge(
                _as_market(row),
                _as_forecast(row, sigma_f=sigma_f),
                row.market_mid,
                fee_haircut=fee_haircut,
            )
        except ValueError as exc:
            counts["unparsed"] += 1
            dispositions.append(
                RowDisposition(
                    market_id=row.market_id,
                    print_id=print_id,
                    city_slug=row.city_slug,
                    event_date=row.event_date,
                    status="unparsed",
                    reason=str(exc),
                )
            )
            continue
        won = yes_won(row)
        assert won is not None
        half_spread = row.half_spread if row.half_spread is not None else default_half_spread
        if row.half_spread is None:
            half_spread_default_used += 1
        would_trade = edge.net_edge >= min_edge
        treatment_pnl = 0.0
        fade_pnl = 0.0
        midfill_pnl = 0.0
        if would_trade:
            treat_won = won if edge.side is ContractSide.YES else not won
            fade_side = ContractSide.NO if edge.side is ContractSide.YES else ContractSide.YES
            fade_won = won if fade_side is ContractSide.YES else not won
            treatment_pnl = realized_pnl(
                conservative_entry(edge.side, row.market_mid, half_spread),
                won=treat_won,
                fee_haircut=fee_haircut,
            )
            fade_pnl = realized_pnl(
                conservative_entry(fade_side, row.market_mid, half_spread),
                won=fade_won,
                fee_haircut=fee_haircut,
            )
            mid_entry = row.market_mid if edge.side is ContractSide.YES else (1.0 - row.market_mid)
            midfill_pnl = realized_pnl(mid_entry, won=treat_won, fee_haircut=fee_haircut)
        disposition = RowDisposition(
            market_id=row.market_id,
            print_id=print_id,
            city_slug=row.city_slug,
            event_date=row.event_date,
            status="would_trade" if would_trade else "below_edge",
            side=edge.side if would_trade else None,
            net_edge=edge.net_edge,
            conservative_pnl=treatment_pnl if would_trade else 0.0,
            fade_pnl=fade_pnl if would_trade else 0.0,
            midfill_pnl=midfill_pnl if would_trade else 0.0,
            yes_resolved=won,
        )
        dispositions.append(disposition)
        eligible.append((row, disposition))

    n_would = sum(1 for _, item in eligible if item.status == "would_trade")
    treatment = sum(item.conservative_pnl or 0.0 for _, item in eligible)
    fade = sum(item.fade_pnl or 0.0 for _, item in eligible)
    midfill = sum(item.midfill_pnl or 0.0 for _, item in eligible)

    holdout_n: int | None = None
    holdout_would: int | None = None
    holdout_vs_hold: float | None = None
    holdout_vs_fade: float | None = None
    if len(eligible) >= MIN_ROWS_FOR_HOLDOUT:
        ordered = sorted(eligible, key=lambda pair: (pair[0].event_date, pair[0].market_id))
        cut = max(1, int(len(ordered) * (1.0 - holdout_fraction)))
        holdout = ordered[cut:]
        holdout_n = len(holdout)
        holdout_would = sum(1 for _, item in holdout if item.status == "would_trade")
        holdout_vs_hold = sum(item.conservative_pnl or 0.0 for _, item in holdout)
        holdout_vs_fade = holdout_vs_hold - sum(item.fade_pnl or 0.0 for _, item in holdout)

    fail_closed: str | None = None
    if not rows:
        fail_closed = "empty_print"
    elif not eligible:
        fail_closed = "no_eligible_rows"
    elif n_would < MIN_TRADES_PER_PRINT:
        fail_closed = "below_min_trades"
    elif len(eligible) < MIN_ELIGIBLE_PER_PRINT:
        fail_closed = "below_min_eligible"

    return (
        PrintMetrics(
            print_id=print_id,
            n_rows=len(rows),
            n_city_blocked=counts["city_blocked"],
            n_lookahead_dropped=counts["lookahead"],
            n_station_dropped=counts["station_unmatched"],
            n_mid_dropped=counts["mid_out_of_bounds"],
            n_unparsed=counts["unparsed"],
            n_eligible=len(eligible),
            n_would_trade=n_would,
            n_below_edge=sum(1 for _, item in eligible if item.status == "below_edge"),
            treatment_pnl=treatment,
            fade_pnl=fade,
            hold_pnl=0.0,
            midfill_treatment_pnl=midfill,
            treatment_excess_vs_hold=treatment,
            treatment_excess_vs_fade=treatment - fade,
            midfill_excess_vs_hold=midfill,
            holdout_n=holdout_n,
            holdout_would_trade=holdout_would,
            holdout_treatment_excess_vs_hold=holdout_vs_hold,
            holdout_treatment_excess_vs_fade=holdout_vs_fade,
            fail_closed_reason=fail_closed,
            half_spread_default_used=half_spread_default_used,
        ),
        dispositions,
    )


def print_clears_calculator(metrics: PrintMetrics) -> bool:
    """Pre-registered calculator bar. Does not write a Settings pin."""
    if metrics.used_mid_fill_as_primary:
        return False
    if metrics.fail_closed_reason:
        return False
    if metrics.n_eligible < MIN_ELIGIBLE_PER_PRINT:
        return False
    if metrics.n_would_trade < MIN_TRADES_PER_PRINT:
        return False
    if metrics.treatment_excess_vs_hold <= 0:
        return False
    if metrics.treatment_excess_vs_fade <= 0:
        return False
    if metrics.holdout_treatment_excess_vs_hold is None:
        return False
    if metrics.holdout_treatment_excess_vs_hold <= 0:
        return False
    if metrics.holdout_treatment_excess_vs_fade is None:
        return False
    return metrics.holdout_treatment_excess_vs_fade > 0


def score_crypto_overlay(
    dispositions: list[RowDisposition],
    btc_daily: tuple[DailyClose, ...] | None,
    *,
    fee_bps: float,
) -> CryptoOverlayResult:
    if not btc_daily:
        return CryptoOverlayResult(
            status="skipped",
            reason="no aligned BTC daily close series; overlay not invented",
        )
    by_day: dict[date, list[RowDisposition]] = {}
    for item in dispositions:
        if item.status != "would_trade" or item.side is None:
            continue
        by_day.setdefault(item.event_date, []).append(item)
    if not by_day:
        return CryptoOverlayResult(
            status="scored",
            reason="no would_trade weather rows to align",
            n_signal_days=0,
            n_aligned=0,
            pnl_after_fees=0.0,
            can_promote=False,
        )
    closes = {point.opened_at.date(): point.close for point in btc_daily}
    ordered_days = sorted(closes)
    next_day = {ordered_days[i]: ordered_days[i + 1] for i in range(len(ordered_days) - 1)}
    fee = fee_bps / 10_000.0
    pnl = 0.0
    aligned = 0
    for day, rows in by_day.items():
        yes = sum(1 for item in rows if item.side is ContractSide.YES)
        no = sum(1 for item in rows if item.side is ContractSide.NO)
        if yes == no:
            continue
        signal = 1.0 if yes > no else -1.0
        nxt = next_day.get(day)
        if nxt is None or day not in closes:
            continue
        ret = (closes[nxt] - closes[day]) / closes[day]
        pnl += signal * ret - fee
        aligned += 1
    return CryptoOverlayResult(
        status="scored",
        reason="next-day BTC close-to-close on majority weather side; report-only",
        n_signal_days=len(by_day),
        n_aligned=aligned,
        pnl_after_fees=pnl,
        can_promote=False,
    )


def run_weather_eval(
    prints: dict[str, tuple[ResolvedWeatherRow, ...]],
    *,
    min_edge: float,
    fee_haircut: float,
    sigma_f: float,
    default_half_spread: float = DEFAULT_HALF_SPREAD,
    holdout_fraction: float = DEFAULT_HOLD_FRACTION,
    allowlist: tuple[str, ...] = DEFAULT_CITY_SLUGS,
    min_mid: float = 0.02,
    max_mid: float = 0.98,
    btc_daily: tuple[DailyClose, ...] | None = None,
    crypto_fee_bps: float = 10.0,
    data_notes: list[str] | None = None,
) -> WeatherEvalReport:
    ordered_ids = tuple(prints.keys())
    metrics: list[PrintMetrics] = []
    dispositions: list[RowDisposition] = []
    for print_id in ordered_ids:
        scored, rows = _score_rows(
            prints[print_id],
            min_edge=min_edge,
            fee_haircut=fee_haircut,
            sigma_f=sigma_f,
            default_half_spread=default_half_spread,
            holdout_fraction=holdout_fraction,
            allowlist=allowlist,
            min_mid=min_mid,
            max_mid=max_mid,
            print_id=print_id,
        )
        metrics.append(scored)
        dispositions.extend(rows)

    nonempty = [item for item in metrics if item.n_rows > 0]
    if len(nonempty) >= 2:
        a_rows = prints[ordered_ids[0]]
        b_rows = prints[ordered_ids[1]]
        independent, independence_reason = prints_independent(a_rows, b_rows)
        print_kind: Literal["single_print", "dual_print"] = (
            "dual_print" if independent else "single_print"
        )
    else:
        independent = False
        independence_reason = "fewer_than_two_prints"
        print_kind = "single_print"

    overlay = score_crypto_overlay(dispositions, btc_daily, fee_bps=crypto_fee_bps)
    calculator_ok = (
        print_kind == PRINT_DUAL
        and independent
        and len(nonempty) >= 2
        and print_clears_calculator(nonempty[0])
        and print_clears_calculator(nonempty[1])
    )
    notes = list(data_notes or [])
    if not any(item.n_rows for item in metrics):
        notes.append(
            "No resolved rows: there is no public point-in-time CLOB mid + "
            "official station-high tape in this repository. Empty print is "
            "success. Do not invent historical mids from settlement prices "
            "(look-ahead)."
        )
    if calculator_ok:
        notes.append(
            "Calculator bar cleared on two independent prints. This CLI "
            "still does not write a Settings pin; a default-false flag "
            "would be a separate, documented change."
        )
    return WeatherEvalReport(
        print_kind=print_kind,
        independent=independent,
        independence_reason=independence_reason,
        prints=metrics,
        crypto_overlay=overlay,
        can_promote=False,
        recommended_promote_flag="none",
        min_edge=min_edge,
        fee_haircut=fee_haircut,
        sigma_f=sigma_f,
        default_half_spread=default_half_spread,
        holdout_fraction=holdout_fraction,
        allowlist=allowlist,
        dispositions=dispositions,
        data_notes=notes,
        # Calculator bar is recorded in notes only; a True would still not
        # flip Settings. We keep can_promote False so this CLI cannot
        # authorise a pin even if a later fixture pack clears the numbers.
    )


def empty_live_report(
    *,
    min_edge: float,
    fee_haircut: float,
    sigma_f: float,
    default_half_spread: float = DEFAULT_HALF_SPREAD,
    holdout_fraction: float = DEFAULT_HOLD_FRACTION,
    allowlist: tuple[str, ...] = DEFAULT_CITY_SLUGS,
    extra_notes: list[str] | None = None,
) -> WeatherEvalReport:
    notes = [
        (
            "Live / historical tape: UNAVAILABLE. Gamma closed events without "
            "a stored decision-time mid and an official ASOS/NCEI station high "
            "are not scored (using the settlement price as the mid is look-ahead)."
        ),
        "This empty print is the successful outcome. Do not fabricate PnL.",
    ]
    if extra_notes:
        notes.extend(extra_notes)
    return run_weather_eval(
        {"live_historical": ()},
        min_edge=min_edge,
        fee_haircut=fee_haircut,
        sigma_f=sigma_f,
        default_half_spread=default_half_spread,
        holdout_fraction=holdout_fraction,
        allowlist=allowlist,
        data_notes=notes,
    )


def load_resolved_rows(payload: object, *, default_print_id: str) -> tuple[ResolvedWeatherRow, ...]:
    if not isinstance(payload, list):
        raise TypeError("resolved rows must be a JSON array")
    rows: list[ResolvedWeatherRow] = []
    for item in payload:
        if not isinstance(item, dict):
            raise TypeError("each resolved row must be an object")
        data: dict[str, Any] = dict(item)
        data.setdefault("print_id", default_print_id)
        rows.append(ResolvedWeatherRow.model_validate(data))
    return tuple(rows)


def load_daily_closes(payload: object) -> tuple[DailyClose, ...]:
    if not isinstance(payload, list):
        raise TypeError("BTC daily series must be a JSON array")
    rows = [DailyClose.model_validate(item) for item in payload]
    return tuple(sorted(rows, key=lambda item: item.opened_at))


def _pct(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:+.4f}"


def render_weather_eval_markdown(report: WeatherEvalReport) -> str:
    lines = [
        "# Polymarket weather fee-aware evaluation",
        "",
        (
            "Report-only. Not a live-capital claim. Not a reason to flip "
            "`PAPER_PROMOTE_*` or `TRADING_MODE`. An empty or negative result "
            "is success."
        ),
        "",
        "## What this does / does not claim",
        "",
        (
            "This CLI scores the #44 NWP-vs-CLOB weather rule against "
            "`always_hold` and `fade_the_mid` after conservative costs "
            "(mid ± half-spread − documented taker-fee haircut). It is "
            "**not** a validated weather-market edge, not a crypto signal, "
            "and not a CLOB trading path."
        ),
        "",
        (
            "Crucix fail-closed-on-outage is **not** this change. Crucix "
            "already maps high-tier alerts to `adverse_event`; a dedicated "
            "opt-in outage veto remains a follow-up."
        ),
        "",
        "## Honesty / pre-registered rules",
        "",
        report.honesty,
        "",
        "## Print policy (frozen before scoring)",
        "",
        "| print | when | can promote? |",
        "| --- | --- | --- |",
        (
            "| single-print | fewer than two independent resolved packs, "
            "or overlapping dates with the same resolution source | **no** |"
        ),
        (
            "| dual-print | two packs with non-overlapping `event_date` "
            "sets **or** overlapping dates with disjoint resolution "
            "sources; each pack must also clear the calculator floor | "
            "still **no** Settings flip |"
        ),
        "",
        (
            f"This run: print_kind=`{report.print_kind}`; "
            f"independent=`{str(report.independent).lower()}` "
            f"({report.independence_reason})."
        ),
        "",
        "## Parameters",
        "",
        (
            f"- min_edge={report.min_edge:.3f}; fee_haircut={report.fee_haircut:.3f}; "
            f"sigma_f={report.sigma_f:.2f}°F; default_half_spread="
            f"{report.default_half_spread:.3f}; holdout_fraction="
            f"{report.holdout_fraction:.0%}."
        ),
        f"- allowlist: {', '.join(f'`{item}`' for item in report.allowlist)}.",
        (
            f"- calculator floor: n_eligible ≥ {MIN_ELIGIBLE_PER_PRINT}, "
            f"would_trade ≥ {MIN_TRADES_PER_PRINT}, treatment excess vs "
            "hold **and** fade > 0 on the full eligible set **and** on "
            "the dated holdout tail."
        ),
        "",
        "## Data",
        "",
    ]
    if report.data_notes:
        for note in report.data_notes:
            lines.append(f"- {note}")
    else:
        lines.append("- (no data notes)")

    lines.extend(["", "## Prints", ""])
    for metrics in report.prints:
        lines.extend(
            [
                f"### `{metrics.print_id}`",
                "",
                (
                    f"rows={metrics.n_rows} eligible={metrics.n_eligible} "
                    f"would_trade={metrics.n_would_trade} "
                    f"below_edge={metrics.n_below_edge}; "
                    f"dropped city={metrics.n_city_blocked} "
                    f"lookahead={metrics.n_lookahead_dropped} "
                    f"station={metrics.n_station_dropped} "
                    f"mid={metrics.n_mid_dropped} unparsed={metrics.n_unparsed}."
                ),
                (
                    f"Conservative treatment PnL (probability points, $1 "
                    f"notional): {_pct(metrics.treatment_pnl)} vs hold "
                    f"{_pct(metrics.treatment_excess_vs_hold)} vs fade "
                    f"{_pct(metrics.treatment_excess_vs_fade)}. Mid-fill "
                    f"treatment (cannot promote): {_pct(metrics.midfill_treatment_pnl)}."
                ),
            ]
        )
        if metrics.holdout_n is None:
            lines.append(
                f"Holdout: fail-closed (n_eligible={metrics.n_eligible} < {MIN_ROWS_FOR_HOLDOUT})."
            )
        else:
            lines.append(
                f"Holdout n={metrics.holdout_n} would_trade="
                f"{metrics.holdout_would_trade}: vs hold "
                f"{_pct(metrics.holdout_treatment_excess_vs_hold)} vs fade "
                f"{_pct(metrics.holdout_treatment_excess_vs_fade)}."
            )
        if metrics.fail_closed_reason:
            lines.append(f"Fail-closed reason: `{metrics.fail_closed_reason}`.")
        if metrics.half_spread_default_used:
            lines.append(
                f"{metrics.half_spread_default_used} row(s) used the documented "
                f"default half-spread {report.default_half_spread:.3f}."
            )
        lines.append("")

    overlay = report.crypto_overlay
    lines.extend(
        [
            "## Crypto overlay",
            "",
            (
                f"`{overlay.candidate_id}` **{overlay.status}**: {overlay.reason} "
                f"(signal_days={overlay.n_signal_days}, aligned={overlay.n_aligned}, "
                f"pnl_after_fees={_pct(overlay.pnl_after_fees)}, "
                f"can_promote=`{str(overlay.can_promote).lower()}`)."
            ),
            "",
            "## Promotion decision",
            "",
            (
                "**No candidate is promoted.** "
                f"print_kind=`{report.print_kind}`; "
                f"can_promote=`{str(report.can_promote).lower()}`; "
                f"can_enter_promotion_average="
                f"`{str(report.can_enter_promotion_average).lower()}`; "
                f"keep_flag_false=`{str(report.keep_flag_false).lower()}`; "
                f"recommended_promote_flag=`{report.recommended_promote_flag}`. "
                f"`{DEFAULT_PROMOTE_FLAG}` is not a Settings field. "
                "Leave every `PAPER_PROMOTE_*` false. Do not enable live."
            ),
            "",
        ]
    )
    return "\n".join(lines)
