"""Calendar seasonality dual-print (BTC+ETH; SOL optional).

Pre-registered before any live pull (do not retune after seeing PnL).

Treatment (frozen): positions are driven by the **UTC civil calendar**
of bar t only — not close, not return, not a residual, not a
cross-section rank, not Donchian, not TSMOM, not Bollinger. Timezone
is **UTC**. A naive ``opened_at`` is treated as UTC. Decision uses
``opened_at.astimezone(UTC).date()`` (the date of bar t). Fill at
t+1 open (same convention as tsmom / bollinger / donchian).

Frozen weekday / month / turn-of-month sets (do not grow after PnL):

* ``cal_dow_lo_mon`` — long Monday UTC, flat otherwise.
* ``cal_dow_lo_fri`` — long Friday UTC, flat otherwise.
* ``cal_dow_lo_mon_fri`` — long Monday and Friday UTC, flat otherwise.
* ``cal_dow_skip_weekend`` — long Mon–Fri UTC, flat Sat/Sun UTC
  (crypto trades 24/7; weekend means Sat/Sun UTC bars if present).
* ``cal_moy_lo_q4`` — long October–December UTC, flat otherwise.
* ``cal_moy_lo_jan`` — long January UTC, flat otherwise.
* ``cal_moy_lo_nov_dec`` — long November–December UTC, flat otherwise.
* ``cal_tom_lo_3_3`` — long the last N=3 and first M=3 **UTC calendar
  days** of the month (``calendar.monthrange``; known from the civil
  calendar — no look-ahead into future bars or prices). Crypto 24/7:
  every UTC date is a trading day if a bar exists. A missing bar is
  skipped, never zero-filled, and does **not** reassign “last 3
  trading days” onto earlier dates.

Python ``date.weekday()``: Monday=0 … Sunday=6.

Each asset is scored on its own timestamps. A missing/short series is
skipped, never zero-filled. Prices never enter the calendar decision.

Multi-asset combined bar (frozen before scoring): the same #96+A+B+C
harder gates as #104 on **BTC and ETH**. SOL walk-forward and holdout
are reported when the series exists and are **not** a gate.
Equal-weight portfolio metrics are not used.

A name is a **dual-print passer** only if it clears combined harder
gates on **both**:

1. The Kraken public Spot daily primary window (720-bar cap).
2. The #102 Binance.US Spot daily print: 720 committed BTC+ETH bars
   ending strictly before the primary Kraken first bar.

Ranking key (frozen): ``mean_holdout_excess_among_dual_print_passers``
— Kraken BTC+ETH mean holdout excess among names that already cleared
both prints. Tie-break: ``candidate_id``. Binance holdout is a gate,
never averaged. A Kraken-only combined-passer cannot promote.

The informational control ``ma_cross_10_30`` is scored on the same
windows and **cannot** enter the passer set.

Paper-executable on Kraken spot (BTC/USD + ETH/USD; SOL/USD when
present via ``paper_simulate_fills``). Empty dual-print set is
success. This module never flips ``PAPER_PROMOTE_*`` and does not add
a Settings pin unless a committed report names a dual-print passer
(default false if added). No live.
"""

from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import UTC, date, datetime

from pydantic import BaseModel, Field

from traderstack.candles import Candle
from traderstack.models import Side
from traderstack.research.binance_spot import BINANCE_TAKER_BPS_NOTE
from traderstack.research.candidates import AlwaysOnTrendStrategy
from traderstack.research.daily_robustness import KRAKEN_DAILY_CAP_NOTE
from traderstack.research.dual_print_search import (
    CAN_AVERAGE_VENUES,
    CAN_ENTER_PROMOTION_AVERAGE,
    MULTI_VENUE_BAR_PREREGISTERED,
    RANKING_KEY,
    SELECTION_RULE,
    DualPrintRow,
    _binance_slice_meta,
    _merge_row,
    _score,
    rank_dual_print_passers,
)
from traderstack.research.harder_gates import (
    HARDER_GATES_NOTE,
    CandidateHarderResult,
    _pct,
    _ratio,
    _verdict,
    kraken_daily_candles,
    paper_promote_flag_name,
)
from traderstack.research.harder_gates import (
    RANKING_KEY as KRAKEN_COMBINED_RANKING_KEY,
)
from traderstack.research.miles_candidates import SearchCandidate
from traderstack.research.second_print import (
    BINANCE_SLICE_RULE,
    SECOND_PRINT_BARS,
    SliceMeta,
    primary_first_opened_at,
    remap_binance_for_scoring,
    slice_ending_before,
)

# --- era prints / DSR / PBO (#135) ---
from traderstack.research.selection_evidence import (
    SelectionEvidence,
    render_evidence_lines,
)
from traderstack.strategies import Regime, StrategySignal

# Python date.weekday(): Monday=0 … Sunday=6. Frozen UTC civil calendar.
UTC_WEEKDAY_MON = 0
UTC_WEEKDAY_TUE = 1
UTC_WEEKDAY_WED = 2
UTC_WEEKDAY_THU = 3
UTC_WEEKDAY_FRI = 4
UTC_WEEKDAY_SAT = 5
UTC_WEEKDAY_SUN = 6
UTC_WEEKDAYS = frozenset(
    {
        UTC_WEEKDAY_MON,
        UTC_WEEKDAY_TUE,
        UTC_WEEKDAY_WED,
        UTC_WEEKDAY_THU,
        UTC_WEEKDAY_FRI,
    }
)
UTC_WEEKEND = frozenset({UTC_WEEKDAY_SAT, UTC_WEEKDAY_SUN})
TOM_LAST_N = 3
TOM_FIRST_M = 3
TIMEZONE_RULE = "utc"
DECISION_RULE = "utc_calendar_date_of_bar_t"
FILL_RULE = "next_bar_open"
TOM_RULE = "utc_calendar_last_n_first_m_days_of_month"

# (candidate_id, kind)  kind in {dow_lo, dow_skip_weekend, moy_lo, tom_lo}
CALENDAR_CATALOG: tuple[tuple[str, str], ...] = (
    ("cal_dow_lo_mon", "dow_lo"),
    ("cal_dow_lo_fri", "dow_lo"),
    ("cal_dow_lo_mon_fri", "dow_lo"),
    ("cal_dow_skip_weekend", "dow_skip_weekend"),
    ("cal_moy_lo_q4", "moy_lo"),
    ("cal_moy_lo_jan", "moy_lo"),
    ("cal_moy_lo_nov_dec", "moy_lo"),
    ("cal_tom_lo_3_3", "tom_lo"),
)
DOW_SETS: dict[str, frozenset[int]] = {
    "cal_dow_lo_mon": frozenset({UTC_WEEKDAY_MON}),
    "cal_dow_lo_fri": frozenset({UTC_WEEKDAY_FRI}),
    "cal_dow_lo_mon_fri": frozenset({UTC_WEEKDAY_MON, UTC_WEEKDAY_FRI}),
    "cal_dow_skip_weekend": UTC_WEEKDAYS,
}
MOY_SETS: dict[str, frozenset[int]] = {
    "cal_moy_lo_q4": frozenset({10, 11, 12}),
    "cal_moy_lo_jan": frozenset({1}),
    "cal_moy_lo_nov_dec": frozenset({11, 12}),
}
CALENDAR_IDS: tuple[str, ...] = tuple(item[0] for item in CALENDAR_CATALOG)
DOW_IDS: tuple[str, ...] = tuple(item[0] for item in CALENDAR_CATALOG if item[1].startswith("dow"))
MOY_IDS: tuple[str, ...] = tuple(item[0] for item in CALENDAR_CATALOG if item[1] == "moy_lo")
TOM_IDS: tuple[str, ...] = tuple(item[0] for item in CALENDAR_CATALOG if item[1] == "tom_lo")
CONTROL_ID = "ma_cross_10_30"
CONTROL_IDS: frozenset[str] = frozenset({CONTROL_ID})
CORE_IDS: tuple[str, ...] = CALENDAR_IDS + (CONTROL_ID,)
UNIVERSE: tuple[str, ...] = ("BTC/USD", "ETH/USD", "SOL/USD")
SCORE_SYMBOLS: frozenset[str] = frozenset(UNIVERSE)
ALIAS_TO_CANONICAL: dict[str, str] = {
    "BTC/USD": "BTC/USD",
    "BTCUSDT": "BTC/USD",
    "BTC-USD": "BTC/USD",
    "XBT/USD": "BTC/USD",
    "ETH/USD": "ETH/USD",
    "ETHUSDT": "ETH/USD",
    "ETH-USD": "ETH/USD",
    "SOL/USD": "SOL/USD",
    "SOLUSDT": "SOL/USD",
    "SOL-USD": "SOL/USD",
}
PAPER_PATH_READY = True
MULTI_ASSET_GATE_RULE = "btc_eth_signs_as_96_abc_sol_reported_not_required"
PRICE_PATH_OMITTED_REASON = (
    "Calendar names ignore OHLC; only the UTC civil date of bar t "
    "enters the decision. Not a price-indicator retune of #116–#120"
)

CALENDAR_RULES = (
    "Pre-registered calendar seasonality dual-print bar "
    "(frozen before any Kraken or Binance.US score). Treatment: "
    f"positions use the UTC civil calendar of bar t only "
    f"(timezone `{TIMEZONE_RULE}`; decision `{DECISION_RULE}`). "
    f"{PRICE_PATH_OMITTED_REASON}. Day-of-week long-only "
    "(`cal_dow_lo_{{mon,fri,mon_fri}}`) is long on the frozen UTC "
    "weekday set and flat otherwise (Monday=0 … Sunday=6). "
    "`cal_dow_skip_weekend` is long Mon–Fri UTC and flat Sat/Sun "
    "UTC (crypto trades 24/7; weekend bars are skipped, not "
    "invented). Month-of-year long-only (`cal_moy_lo_{{q4,jan,"
    "nov_dec}}`) is long in the frozen UTC month set. Turn-of-month "
    f"(`cal_tom_lo_3_3`; `{TOM_RULE}`; last N={TOM_LAST_N:g} / "
    f"first M={TOM_FIRST_M:g}) is long on the last N and first M "
    "UTC calendar days of the month (`calendar.monthrange`; known "
    "from the civil calendar — no look-ahead into future bars or "
    "prices). A missing bar is skipped, never zero-filled, and does "
    "not reassign last-N onto earlier dates. This is not trend, not "
    "cross-section (#117), not Donchian (#118), not TSMOM (#119), "
    "and not Bollinger fade (#120). "
    f"Decision at bar t; fill `{FILL_RULE}` (t+1 open — no look-ahead "
    "into the fill bar). Each asset uses its own timestamps; a "
    "missing/short series is skipped, never zero-filled. "
    f"Multi-asset combined bar: `{MULTI_ASSET_GATE_RULE}` — #96 "
    "balanced-holdout and A magnitude and B multi-window and C 2× "
    "fees on BTC and ETH; SOL is reported when present and is not a "
    "gate. Equal-weight portfolio metrics are not used. A dual-print "
    "passer must combined-PASS the Kraken primary 720-bar daily "
    "window AND the #102 Binance.US older-720 "
    f"(`{BINANCE_SLICE_RULE}`: {SECOND_PRINT_BARS} committed daily "
    "BTC+ETH bars ending strictly before the primary Kraken first "
    "bar). "
    f"Ranking key: {RANKING_KEY} — Kraken BTC+ETH mean holdout "
    "excess among dual-print passers (tie-break: candidate_id). "
    "Binance holdout is a gate only; "
    f"CAN_AVERAGE_VENUES={str(CAN_AVERAGE_VENUES).lower()}. "
    f"MULTI_VENUE_BAR_PREREGISTERED="
    f"{str(MULTI_VENUE_BAR_PREREGISTERED).lower()}. "
    "A Kraken-only combined-passer is not a dual-print passer and "
    "cannot promote. The informational control ma_cross_10_30 "
    "cannot enter the passer set. Missing, short, or overlapping "
    "Binance fails closed (zero dual-print passers). Fees are "
    "paper-research 10+5 (gate C 20+10). Paper-executable on "
    "Kraken spot BTC/USD+ETH/USD (SOL optional) "
    f"(PAPER_PATH_READY={str(PAPER_PATH_READY).lower()}). "
    "PAPER_PROMOTE_* stays default false. No live. An empty "
    "dual-print set is success. Not an EMA reprint, not a "
    "BTC−ETH residual reprint, not cross-sectional momentum, "
    "not Donchian / channel breakout, not TSMOM, not Bollinger "
    "fade, and not a carry/basis family."
)

CALENDAR_CATALOG_NOTE = (
    "Frozen catalog (K=9): day-of-week long-only "
    "(`cal_dow_lo_{mon,fri,mon_fri}`), skip-weekend "
    "(`cal_dow_skip_weekend`; long Mon–Fri UTC), month-of-year "
    "long-only (`cal_moy_lo_{q4,jan,nov_dec}`), turn-of-month "
    f"(`cal_tom_lo_3_3`; last {TOM_LAST_N:g} / first {TOM_FIRST_M:g} "
    f"UTC calendar days; `{TOM_RULE}`), plus informational control "
    "ma_cross_10_30 (cannot promote). Do not grow this list or "
    "retune weekday / month / N,M sets after seeing PnL. Timezone "
    f"is `{TIMEZONE_RULE}`. A missing series is skipped, never "
    "zero-filled. PAPER_PROMOTE_* stays false unless a committed "
    "dual-print report names a paper-only pin and an operator "
    "flips it."
)

PAPER_EXECUTABLE_PATH_NOTE = (
    "This family is paper-executable on Kraken spot. Signals are "
    "candle-timestamp long/flat on BTC/USD and ETH/USD (SOL/USD "
    "when present); paper_simulate_fills already books Side.BUY. "
    "No short book is required for the calendar names. No perp, no "
    "funding, no hedge book, no invented basis. A Settings pin is "
    "still added only if a committed dual-print passer exists, and "
    "then default false."
)


def utc_calendar_date(opened_at: datetime) -> date:
    """UTC civil date of the bar. Naive timestamps are treated as UTC."""
    if opened_at.tzinfo is None:
        return opened_at.replace(tzinfo=UTC).date()
    return opened_at.astimezone(UTC).date()


def is_turn_of_month(
    utc_day: date,
    *,
    last_n: int = TOM_LAST_N,
    first_m: int = TOM_FIRST_M,
) -> bool:
    """True on the last N / first M UTC calendar days of the month."""
    if last_n <= 0 or first_m <= 0:
        return False
    days_in_month = monthrange(utc_day.year, utc_day.month)[1]
    return utc_day.day <= first_m or utc_day.day > days_in_month - last_n


def calendar_position(opened_at: datetime, candidate_id: str, kind: str) -> float:
    """Long (1.0) or flat (0.0) from the UTC civil date of bar t."""
    utc_day = utc_calendar_date(opened_at)
    if kind in {"dow_lo", "dow_skip_weekend"}:
        allowed = DOW_SETS[candidate_id]
        return 1.0 if utc_day.weekday() in allowed else 0.0
    if kind == "moy_lo":
        allowed_months = MOY_SETS[candidate_id]
        return 1.0 if utc_day.month in allowed_months else 0.0
    if kind == "tom_lo":
        return 1.0 if is_turn_of_month(utc_day) else 0.0
    raise ValueError(f"unknown calendar kind {kind!r}")


def calendar_position_series(
    candles: tuple[Candle, ...],
    *,
    candidate_id: str,
    kind: str,
) -> tuple[tuple[datetime, float], ...]:
    """UTC-calendar positions. Skip-not-invent; timestamps only."""
    if not candles:
        return ()
    return tuple(
        (candle.opened_at, calendar_position(candle.opened_at, candidate_id, kind))
        for candle in candles
    )


def _histories_by_canonical(
    histories: dict[str, tuple[Candle, ...]],
) -> dict[str, tuple[Candle, ...]]:
    out: dict[str, tuple[Candle, ...]] = {}
    for candles in histories.values():
        if not candles:
            continue
        canonical = ALIAS_TO_CANONICAL.get(candles[0].symbol.upper())
        if canonical is None:
            continue
        out[canonical] = candles
    return out


def calendar_signals(
    histories: dict[str, tuple[Candle, ...]],
    *,
    candidate_id: str,
    kind: str,
) -> dict[str, tuple[tuple[datetime, float], ...]]:
    """Per-asset calendar assignments. Missing assets omitted, not invented."""
    by_canonical = _histories_by_canonical(histories)
    per_asset: dict[str, tuple[tuple[datetime, float], ...]] = {}
    for asset, candles in by_canonical.items():
        series = calendar_position_series(candles, candidate_id=candidate_id, kind=kind)
        if series:
            per_asset[asset] = series
    if not per_asset:
        return {}
    mapping: dict[str, tuple[tuple[datetime, float], ...]] = {}
    for alias, canonical in ALIAS_TO_CANONICAL.items():
        if canonical in per_asset:
            mapping[alias] = per_asset[canonical]
    return mapping


@dataclass(frozen=True)
class CalendarSeasonalityVoter:
    """Look up a precomputed same-bar UTC calendar position."""

    strategy_id: str
    signals_by_symbol: tuple[tuple[str, tuple[tuple[datetime, float], ...]], ...] = ()

    def evaluate(self, candles: tuple[Candle, ...], regime: Regime) -> StrategySignal:
        cutoff = candles[-1].opened_at
        series = self.series_for(candles[-1].symbol)
        by_ts = {ts: value for ts, value in series}
        value = by_ts.get(cutoff)
        if value is None:
            return StrategySignal(
                strategy_id=self.strategy_id,
                symbol=candles[-1].symbol,
                side=None,
                score=0.0,
                confidence=0.0,
                regime=regime,
                rationale="calendar: no same-bar assignment (skipped / missing tape)",
            )
        side: Side | None = None
        if value > 0:
            side = Side.BUY
        elif value < 0:
            side = Side.SELL
        return StrategySignal(
            strategy_id=self.strategy_id,
            symbol=candles[-1].symbol,
            side=side,
            score=max(-1.0, min(1.0, value)),
            confidence=1.0 if side is not None else 0.0,
            regime=regime,
            rationale=f"calendar assignment={value:+.0f}",
        )

    def series_for(self, symbol: str) -> tuple[tuple[datetime, float], ...]:
        key = symbol.upper()
        for name, series in self.signals_by_symbol:
            if name == key:
                return series
        return ()


def _control_candidate() -> SearchCandidate:
    return SearchCandidate(
        candidate_id=CONTROL_ID,
        family="control",
        label="always-on MA 10/30 (informational; cannot promote)",
        params={"short_window": 10, "long_window": 30, "strategy_id": CONTROL_ID},
        strategy=AlwaysOnTrendStrategy(
            strategy_id=CONTROL_ID,
            short_window=10,
            long_window=30,
        ),
    )


def _family_for(kind: str) -> str:
    if kind.startswith("dow"):
        return "cal_dow"
    if kind == "moy_lo":
        return "cal_moy"
    return "cal_tom"


def _book_label(candidate_id: str, kind: str) -> str:
    labels = {
        "cal_dow_lo_mon": "UTC Monday long-only",
        "cal_dow_lo_fri": "UTC Friday long-only",
        "cal_dow_lo_mon_fri": "UTC Monday+Friday long-only",
        "cal_dow_skip_weekend": "UTC weekday long / weekend flat",
        "cal_moy_lo_q4": "UTC Q4 (Oct–Dec) long-only",
        "cal_moy_lo_jan": "UTC January long-only",
        "cal_moy_lo_nov_dec": "UTC November+December long-only",
        "cal_tom_lo_3_3": (
            f"UTC turn-of-month last {TOM_LAST_N:g} / first {TOM_FIRST_M:g} calendar days"
        ),
    }
    return labels.get(candidate_id, f"calendar {kind} {candidate_id}")


def calendar_candidates(
    histories: dict[str, tuple[Candle, ...]] | None = None,
    *,
    include_control: bool = True,
) -> tuple[SearchCandidate, ...]:
    """Instantiate the frozen catalog. Missing OHLC → that name omitted."""
    out: list[SearchCandidate] = []
    source = histories or {}
    for candidate_id, kind in CALENDAR_CATALOG:
        mapping = calendar_signals(source, candidate_id=candidate_id, kind=kind)
        if not mapping:
            continue
        by_symbol = tuple((key.upper(), values) for key, values in sorted(mapping.items()))
        out.append(
            SearchCandidate(
                candidate_id=candidate_id,
                family=_family_for(kind),
                label=_book_label(candidate_id, kind),
                params={
                    "kind": kind,
                    "weekdays": (
                        sorted(DOW_SETS[candidate_id]) if candidate_id in DOW_SETS else None
                    ),
                    "months": (
                        sorted(MOY_SETS[candidate_id]) if candidate_id in MOY_SETS else None
                    ),
                    "tom_last_n": TOM_LAST_N if kind == "tom_lo" else None,
                    "tom_first_m": TOM_FIRST_M if kind == "tom_lo" else None,
                    "timezone": TIMEZONE_RULE,
                    "decision_rule": DECISION_RULE,
                    "fill_rule": FILL_RULE,
                    "tom_rule": TOM_RULE if kind == "tom_lo" else None,
                    "strategy_id": candidate_id,
                    "multi_asset_gate": MULTI_ASSET_GATE_RULE,
                },
                strategy=CalendarSeasonalityVoter(
                    strategy_id=candidate_id,
                    signals_by_symbol=by_symbol,
                ),
            )
        )
    if include_control:
        out.append(_control_candidate())
    return tuple(out)


def skipped_calendar_families(
    histories: dict[str, tuple[Candle, ...]],
) -> list[dict[str, str]]:
    skipped: list[dict[str, str]] = []
    for candidate_id, kind in CALENDAR_CATALOG:
        mapping = calendar_signals(histories, candidate_id=candidate_id, kind=kind)
        if mapping:
            continue
        skipped.append(
            {
                "family": _family_for(kind),
                "candidate_id": candidate_id,
                "reason": (
                    f"{_book_label(candidate_id, kind)}"
                    ": skipped — need at least one venue-local bar "
                    "with a UTC timestamp. Skip rather than invent or "
                    "zero-fill dates."
                ),
            }
        )
    return skipped


def _score_symbols_only(
    histories: dict[str, tuple[Candle, ...]],
) -> dict[str, tuple[Candle, ...]]:
    return {
        key: candles
        for key, candles in histories.items()
        if candles and candles[0].symbol.upper() in SCORE_SYMBOLS
    }


def rank_calendar_passers(rows: list[DualPrintRow]) -> list[DualPrintRow]:
    """Frozen ranking key among calendar dual-print passers. Control excluded."""
    eligible = [row for row in rows if row.candidate_id not in CONTROL_IDS]
    return rank_dual_print_passers(eligible)


def eth_carried_informational(rows: list[DualPrintRow]) -> list[DualPrintRow]:
    """Positive mean HO with a losing BTC holdout — #96 FAIL, not an edge."""
    flagged: list[DualPrintRow] = []
    for row in rows:
        if row.candidate_id in CONTROL_IDS:
            continue
        mean_ho = row.kraken_mean_holdout_excess
        btc_ho = row.kraken_btc_holdout
        if mean_ho is None or btc_ho is None:
            continue
        if mean_ho > 0 and btc_ho <= 0:
            flagged.append(row)
    return flagged


def btc_wf_fail_informational(rows: list[DualPrintRow]) -> list[DualPrintRow]:
    """Positive mean HO and BTC HO, but BTC walk-forward ≤ 0 — not an edge."""
    flagged: list[DualPrintRow] = []
    for row in rows:
        if row.candidate_id in CONTROL_IDS:
            continue
        mean_ho = row.kraken_mean_holdout_excess
        btc_ho = row.kraken_btc_holdout
        btc_wf = row.kraken_btc_wf
        if mean_ho is None or btc_ho is None or btc_wf is None:
            continue
        if mean_ho > 0 and btc_ho > 0 and btc_wf <= 0:
            flagged.append(row)
    return flagged


class CalendarSeasonalityReport(BaseModel):
    generated_at: datetime
    ranking_key: str
    selection_rule: str
    multi_asset_gate_rule: str
    catalog_k_core: int
    catalog_k_scored: int
    catalog_ids: list[str]
    catalog_note: str
    fee_bps: float
    slippage_bps: float
    train_size: int
    test_size: int
    step_size: int
    holdout_fraction: float
    min_trades: int
    primary_first: str
    primary_first_source: str
    primary_last: str | None = None
    primary_bars: int | None = None
    primary_bars_eth: int | None = None
    primary_bars_sol: int | None = None
    binance_slice: SliceMeta
    binance_source: str | None = None
    paper_path_ready: bool = True
    multi_venue_bar_preregistered: bool = True
    can_average_venues: bool = False
    can_enter_promotion_average: bool = False
    keep_flag_false: bool = True
    # --- era prints / DSR / PBO (#135) ---
    selection_evidence: SelectionEvidence | None = None
    rows: list[DualPrintRow] = Field(default_factory=list)
    dual_print_passer_ids: list[str] = Field(default_factory=list)
    kraken_combined_passer_ids: list[str] = Field(default_factory=list)
    binance_combined_passer_ids: list[str] = Field(default_factory=list)
    eth_carried_ids: list[str] = Field(default_factory=list)
    btc_wf_fail_ids: list[str] = Field(default_factory=list)
    skipped_feature_families: list[dict[str, str]] = Field(default_factory=list)
    selected_candidate_id: str | None = None
    recommended_promote_flag: str | None = None
    any_dual_print_passer: bool = False
    honesty: str
    recommendation: str
    rules: str = CALENDAR_RULES
    gates_note: str = HARDER_GATES_NOTE
    fee_note: str = BINANCE_TAKER_BPS_NOTE
    kraken_cap_note: str = KRAKEN_DAILY_CAP_NOTE
    paper_path_note: str = PAPER_EXECUTABLE_PATH_NOTE
    data_notes: list[str] = Field(default_factory=list)


def _recommendation(
    *,
    selected_id: str | None,
    dual_ids: list[str],
    kraken_ids: list[str],
    binance_meta: SliceMeta,
    eth_carried: list[str],
    btc_wf_fail: list[str],
) -> str:
    lines = [
        (
            "**Keep every `PAPER_PROMOTE_*=false`.** This search does not "
            "flip a pin and does not enable live. An empty dual-print set "
            "is the successful outcome."
        ),
        "",
        (
            f"- Dual-print passers: {len(dual_ids)}"
            + (f" (`{'`, `'.join(dual_ids)}`)" if dual_ids else " (none)")
            + "."
        ),
        (
            f"- Kraken combined-passers (informational; control excluded "
            f"from ranking): {len(kraken_ids)}"
            + (f" (`{'`, `'.join(kraken_ids)}`)" if kraken_ids else "")
            + ". A Kraken-only passer cannot promote."
        ),
        (
            f"- Binance.US `{BINANCE_SLICE_RULE}`: "
            f"{'scored' if binance_meta.available else 'FAIL-CLOSED'} "
            f"({binance_meta.venue}; {binance_meta.bars_btc} BTC / "
            f"{binance_meta.bars_eth} ETH / {binance_meta.bars_sol} SOL; "
            f"{binance_meta.first} → {binance_meta.last})."
        ),
        (f"- Multi-asset gate: `{MULTI_ASSET_GATE_RULE}` (SOL reported, not required)."),
        (
            f"- Paper path: ready on Kraken spot BTC/ETH "
            f"(SOL optional; PAPER_PATH_READY={str(PAPER_PATH_READY).lower()})."
        ),
    ]
    if eth_carried:
        lines.append(
            "- #96 FAIL (ETH-carried informational mean HO; BTC holdout "
            f"≤ 0): {', '.join(f'`{item}`' for item in eth_carried)}. "
            "A positive mean with a losing BTC holdout is not an edge."
        )
    if btc_wf_fail:
        lines.append(
            "- Informational positive mean HO and BTC HO with BTC "
            f"walk-forward ≤ 0: {', '.join(f'`{item}`' for item in btc_wf_fail)}. "
            "Same honesty as #118 Donchian / #119 TSMOM / #120 "
            "Bollinger — still not an edge."
        )
    if selected_id is None:
        lines.append(
            "- Dual-print top-1: **none**. Do not add a new promote flag. "
            "Leave every existing `PAPER_PROMOTE_*` false."
        )
    else:
        flag = paper_promote_flag_name(selected_id)
        lines.append(
            f"- Dual-print top-1: `{selected_id}` by `{RANKING_KEY}`. "
            f"Documented paper-only name would be `{flag}` "
            "(default **false** if added). This run does not flip it."
        )
    lines.append(
        "- Do not enable live. Do not fabricate PnL. Do not re-run #104 "
        "or #108 EMA / 4h dual-prints. Do not re-run the #116 residual, "
        "#117 cross-sectional, #118 Donchian, #119 TSMOM, or #120 "
        "Bollinger catalogs on the same windows. Do not invent PIT "
        "basis for carry. Do not data-mine weekday or month sets "
        "after seeing PnL."
    )
    return "\n".join(lines)


def run_calendar_seasonality_search(
    kraken_histories: dict[str, tuple[Candle, ...]],
    binance_histories: dict[str, tuple[Candle, ...]] | None = None,
    *,
    fee_bps: float,
    slippage_bps: float = 5.0,
    starting_equity: float = 10_000.0,
    train_size: int = 180,
    test_size: int = 60,
    step_size: int = 60,
    holdout_fraction: float = 0.20,
    min_trades: int = 3,
    candidates: tuple[SearchCandidate, ...] | None = None,
    binance_source: str | None = None,
    now: datetime | None = None,
    data_notes: list[str] | None = None,
) -> CalendarSeasonalityReport:
    generated = now or datetime.now(UTC)
    kraken = _score_symbols_only(kraken_histories)
    if not kraken:
        raise ValueError("no Kraken BTC/ETH/SOL daily histories provided")
    primary_first, primary_source = primary_first_opened_at(kraken)
    btc = kraken_daily_candles(kraken, "BTC/USD")
    eth = kraken_daily_candles(kraken, "ETH/USD")
    sol = kraken_daily_candles(kraken, "SOL/USD")
    primary_last = btc[-1].opened_at.isoformat() if btc else None
    primary_bars = len(btc) if btc else None

    catalog = candidates if candidates is not None else calendar_candidates(kraken)
    skipped = skipped_calendar_families(kraken)

    raw_binance = binance_histories or {}
    sliced_binance = {
        key: slice_ending_before(candles, before=primary_first)
        for key, candles in raw_binance.items()
    }
    remapped = _score_symbols_only(remap_binance_for_scoring(sliced_binance))
    binance_meta = _binance_slice_meta(
        raw_binance=raw_binance,
        remapped=remapped,
        primary_first=primary_first,
        binance_source=binance_source,
    )

    kraken_report = _score(
        kraken,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
        starting_equity=starting_equity,
        train_size=train_size,
        test_size=test_size,
        step_size=step_size,
        holdout_fraction=holdout_fraction,
        min_trades=min_trades,
        candidates=catalog,
        now=generated,
        # --- era prints / DSR / PBO (#135) ---
        venue_print_available=binance_meta.available,
        venue_label="kraken_spot",
    )
    kraken_by_id = {row.candidate_id: row for row in kraken_report.candidates}

    binance_by_id: dict[str, CandidateHarderResult] = {}
    if binance_meta.available:
        if candidates is not None:
            binance_catalog = candidates
        else:
            binance_catalog = calendar_candidates(remapped)
        binance_report = _score(
            remapped,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            starting_equity=starting_equity,
            train_size=train_size,
            test_size=test_size,
            step_size=step_size,
            holdout_fraction=holdout_fraction,
            min_trades=min_trades,
            candidates=binance_catalog,
            now=generated,
        )
        binance_by_id = {row.candidate_id: row for row in binance_report.candidates}

    rows = [
        _merge_row(
            candidate,
            kraken_by_id.get(candidate.candidate_id),
            binance_by_id.get(candidate.candidate_id),
        )
        for candidate in catalog
    ]
    passers = rank_calendar_passers(rows)
    selected = passers[0] if passers else None
    dual_ids = [row.candidate_id for row in passers]
    kraken_ids = [
        row.candidate_id
        for row in sorted(
            (
                item
                for item in rows
                if item.kraken_combined and item.candidate_id not in CONTROL_IDS
            ),
            key=lambda item: (
                item.kraken_combined_rank if item.kraken_combined_rank is not None else 10**9,
                item.candidate_id,
            ),
        )
    ]
    binance_ids = [
        row.candidate_id
        for row in rows
        if row.binance_combined and row.candidate_id not in CONTROL_IDS
    ]
    eth_carried = eth_carried_informational(rows)
    eth_carried_ids = [row.candidate_id for row in eth_carried]
    wf_fail = btc_wf_fail_informational(rows)
    btc_wf_fail_ids = [row.candidate_id for row in wf_fail]
    recommended = paper_promote_flag_name(selected.candidate_id) if selected is not None else None
    honesty = (
        CALENDAR_RULES
        + " "
        + CALENDAR_CATALOG_NOTE
        + f" This run scored K={len(catalog)} (core ids frozen at "
        f"{len(CORE_IDS)}). "
        f"Kraken combined-passers (ex-control): {len(kraken_ids)}. "
        f"Binance combined-passers (ex-control): {len(binance_ids)}. "
        f"Dual-print passers: {len(dual_ids)}."
    )
    if eth_carried_ids:
        honesty += (
            " Informational #96 FAIL (ETH-carried mean HO): "
            + ", ".join(f"`{item}`" for item in eth_carried_ids)
            + "."
        )
    if btc_wf_fail_ids:
        honesty += (
            " Informational BTC walk-forward fail (positive mean HO "
            "and BTC HO): " + ", ".join(f"`{item}`" for item in btc_wf_fail_ids) + "."
        )
    if selected is None:
        honesty += (
            " No dual-print passer. Leave every PAPER_PROMOTE_* false. "
            "Do not add a new promote flag."
        )
    else:
        honesty += (
            f" Dual-print top-1 is `{selected.candidate_id}` by "
            f"{RANKING_KEY}. Document a paper-only pin only; default "
            "false; do not enable live."
        )

    notes = list(data_notes or [])
    if not btc or not eth:
        notes.append(
            "BTC and/or ETH daily series missing on Kraken. Combined "
            "gates cannot pass. Skip-not-invent; do not zero-fill."
        )
    if sol:
        notes.append(f"SOL/USD present ({len(sol)} bars); reported, not a gate.")
    else:
        notes.append("SOL/USD absent; reported as n/a, not invented.")

    return CalendarSeasonalityReport(
        # --- era prints / DSR / PBO (#135) ---
        selection_evidence=kraken_report.selection_evidence,
        generated_at=generated,
        ranking_key=RANKING_KEY,
        selection_rule=SELECTION_RULE,
        multi_asset_gate_rule=MULTI_ASSET_GATE_RULE,
        catalog_k_core=len(CORE_IDS),
        catalog_k_scored=len(catalog),
        catalog_ids=[item.candidate_id for item in catalog],
        catalog_note=CALENDAR_CATALOG_NOTE,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
        train_size=train_size,
        test_size=test_size,
        step_size=step_size,
        holdout_fraction=holdout_fraction,
        min_trades=min_trades,
        primary_first=primary_first.isoformat(),
        primary_first_source=primary_source,
        primary_last=primary_last,
        primary_bars=primary_bars,
        primary_bars_eth=len(eth) if eth else None,
        primary_bars_sol=len(sol) if sol else None,
        binance_slice=binance_meta,
        binance_source=binance_source,
        paper_path_ready=PAPER_PATH_READY,
        multi_venue_bar_preregistered=MULTI_VENUE_BAR_PREREGISTERED,
        can_average_venues=CAN_AVERAGE_VENUES,
        can_enter_promotion_average=CAN_ENTER_PROMOTION_AVERAGE,
        keep_flag_false=True,
        rows=rows,
        dual_print_passer_ids=dual_ids,
        kraken_combined_passer_ids=kraken_ids,
        binance_combined_passer_ids=binance_ids,
        eth_carried_ids=eth_carried_ids,
        btc_wf_fail_ids=btc_wf_fail_ids,
        skipped_feature_families=skipped,
        selected_candidate_id=selected.candidate_id if selected is not None else None,
        recommended_promote_flag=recommended,
        any_dual_print_passer=bool(dual_ids),
        honesty=honesty,
        recommendation=_recommendation(
            selected_id=selected.candidate_id if selected is not None else None,
            dual_ids=dual_ids,
            kraken_ids=kraken_ids,
            binance_meta=binance_meta,
            eth_carried=eth_carried_ids,
            btc_wf_fail=btc_wf_fail_ids,
        ),
        data_notes=notes,
    )


def _slice_lines(meta: SliceMeta) -> list[str]:
    status = "available" if meta.available else "UNAVAILABLE / fail-closed"
    return [
        f"- Rule: `{meta.rule}`",
        f"- Venue label: `{meta.venue}`",
        f"- Status: **{status}**",
        f"- Bars: BTC {meta.bars_btc} / ETH {meta.bars_eth} / SOL {meta.bars_sol}",
        f"- Span: {meta.first or 'n/a'} → {meta.last or 'n/a'}",
        f"- Overlaps primary window: {'yes' if meta.overlaps_primary_window else 'no'}",
        f"- Fail-closed reason: {meta.fail_closed_reason or '—'}",
    ]


def _passer_table(rows: list[DualPrintRow], *, venue: str) -> list[str]:
    if venue == "kraken":
        header = (
            "| rank | id | mean HO | BTC HO | ETH HO | SOL HO | ratio | "
            "#96 | A | B | C | dual-print |"
        )
        sep = (
            "| ---: | --- | ---: | ---: | ---: | ---: | ---: | :---: | "
            ":---: | :---: | :---: | :---: |"
        )
    else:
        header = (
            "| id | mean HO | BTC HO | ETH HO | SOL HO | ratio | #96 | A | B | C | dual-print |"
        )
        sep = "| --- | ---: | ---: | ---: | ---: | ---: | :---: | :---: | :---: | :---: | :---: |"
    lines = [header, sep]
    if not rows:
        if venue == "kraken":
            lines.append("| — | — | n/a | n/a | n/a | n/a | n/a | — | — | — | — | no |")
        else:
            lines.append("| — | n/a | n/a | n/a | n/a | n/a | — | — | — | — | no |")
        return lines
    for row in rows:
        if venue == "kraken":
            lines.append(
                f"| {row.kraken_combined_rank or '—'} | `{row.candidate_id}` | "
                f"{_pct(row.kraken_mean_holdout_excess)} | "
                f"{_pct(row.kraken_btc_holdout)} | {_pct(row.kraken_eth_holdout)} | "
                f"{_pct(row.kraken_sol_holdout)} | "
                f"{_ratio(row.kraken_holdout_ratio)} | "
                f"{_verdict(row.kraken_eligible_96)} | {_verdict(row.kraken_gate_a)} | "
                f"{_verdict(row.kraken_gate_b)} | {_verdict(row.kraken_gate_c)} | "
                f"{'yes' if row.dual_print else 'no'} |"
            )
        else:
            lines.append(
                f"| `{row.candidate_id}` | {_pct(row.binance_mean_holdout_excess)} | "
                f"{_pct(row.binance_btc_holdout)} | {_pct(row.binance_eth_holdout)} | "
                f"{_pct(row.binance_sol_holdout)} | "
                f"{_ratio(row.binance_holdout_ratio)} | "
                f"{_verdict(row.binance_eligible_96)} | {_verdict(row.binance_gate_a)} | "
                f"{_verdict(row.binance_gate_b)} | {_verdict(row.binance_gate_c)} | "
                f"{'yes' if row.dual_print else 'no'} |"
            )
    return lines


def render_calendar_seasonality_markdown(
    report: CalendarSeasonalityReport,
) -> str:
    dual_rows = [
        row for row in report.rows if row.dual_print and row.candidate_id not in CONTROL_IDS
    ]
    dual_rows.sort(key=lambda row: row.dual_print_rank or 10**9)
    kraken_rows = [
        row for row in report.rows if row.kraken_combined and row.candidate_id not in CONTROL_IDS
    ]
    kraken_rows.sort(key=lambda row: row.kraken_combined_rank or 10**9)
    binance_rows = [
        row for row in report.rows if row.binance_combined and row.candidate_id not in CONTROL_IDS
    ]
    binance_rows.sort(key=lambda row: row.candidate_id)
    lines: list[str] = [
        "# Calendar seasonality dual-print (BTC+ETH; SOL optional)",
        "",
        f"Generated: {report.generated_at.isoformat()}",
        (
            f"Catalog K scored={report.catalog_k_scored} "
            f"(frozen core={report.catalog_k_core}; "
            f"ranking_key=`{report.ranking_key}`)."
        ),
        (
            f"Baseline costs: fee={report.fee_bps:g} bps + slippage="
            f"{report.slippage_bps:g} bps. Walk-forward: train="
            f"{report.train_size} test={report.test_size} step="
            f"{report.step_size}; holdout_fraction={report.holdout_fraction:.0%}."
        ),
        (
            f"Primary Kraken first bar: {report.primary_first} "
            f"(source=`{report.primary_first_source}`; last="
            f"{report.primary_last or 'n/a'}; bars BTC="
            f"{report.primary_bars or 'n/a'} / ETH="
            f"{report.primary_bars_eth or 'n/a'} / SOL="
            f"{report.primary_bars_sol or 'n/a'})."
        ),
        (
            f"`multi_asset_gate_rule={report.multi_asset_gate_rule}`; "
            f"`multi_venue_bar_preregistered="
            f"{str(report.multi_venue_bar_preregistered).lower()}`; "
            f"`can_average_venues={str(report.can_average_venues).lower()}`; "
            f"`paper_path_ready={str(report.paper_path_ready).lower()}`; "
            f"`keep_flag_false={str(report.keep_flag_false).lower()}`."
        ),
        "",
        "## Honesty / pre-registered rules",
        "",
        report.honesty,
        "",
        "## Dual-print bar (frozen before scoring)",
        "",
        report.rules,
        "",
        "| print | rule | can enter ranking average? |",
        "| --- | --- | --- |",
        (
            "| Kraken primary 720 | public Spot daily, 720-bar cap; "
            f"#96+A+B+C on BTC+ETH (SOL reported); rank among "
            f"dual-print passers by `{report.ranking_key}` "
            "| **Kraken mean HO only** |"
        ),
        (
            "| Binance.US older 720 | same #102 definition: 720 committed "
            "daily BTC+ETH bars ending before the primary Kraken first "
            "bar; SOL optional report-only; must combined-PASS "
            "| **no** (gate only; not averaged) |"
        ),
        (
            f"| Kraken-only combined ranking (`{KRAKEN_COMBINED_RANKING_KEY}`) "
            "| informational | no |"
        ),
        "",
        "## Multi-asset gate (frozen)",
        "",
        (
            f"`{report.multi_asset_gate_rule}`: require BTC and ETH "
            "walk-forward total > 0 and holdout excess > 0, plus A/B/C, "
            "exactly as #96+#104. SOL walk-forward and holdout are "
            "printed in the tables when the series exists and **do not** "
            "gate. Equal-weight portfolio metrics were considered and "
            "**rejected** before scoring — that would be a different "
            "bar and is not used here."
        ),
        "",
        "## Treatment (frozen)",
        "",
        (
            "On each asset at bar t, the position is a function of the "
            f"**UTC civil date** of `opened_at` only (timezone "
            f"`{TIMEZONE_RULE}`; decision `{DECISION_RULE}`). "
            "Day-of-week names long a frozen UTC weekday set. "
            "`cal_dow_skip_weekend` longs Mon–Fri UTC and is flat "
            "Sat/Sun UTC (crypto 24/7; weekend bars if present). "
            "Month-of-year names long a frozen UTC month set. "
            f"Turn-of-month (`{TOM_RULE}`) longs the last "
            f"{TOM_LAST_N:g} and first {TOM_FIRST_M:g} UTC calendar "
            "days of the month (`calendar.monthrange`; no look-ahead "
            "into future bars or prices). The shared backtest fills "
            f"at `{FILL_RULE}` (bar t+1 open), so the decision never "
            "looks ahead into the fill bar. A missing series is "
            f"skipped, never zero-filled. {PRICE_PATH_OMITTED_REASON}. "
            "Not trend, not cross-sectional (#117), not Donchian "
            "(#118), not TSMOM (#119), not Bollinger fade (#120)."
        ),
        "",
        "## Pre-registered catalog",
        "",
        report.catalog_note,
        "",
        ("Frozen core ids: " + ", ".join(f"`{item}`" for item in CORE_IDS) + "."),
        "",
        "## Paper path",
        "",
        report.paper_path_note,
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
    if report.skipped_feature_families:
        lines.extend(["## Skipped (not invented)", ""])
        for item in report.skipped_feature_families:
            lines.append(f"- `{item['candidate_id']}`: {item['reason']}")
        lines.append("")

    lines.extend(
        [
            "## Binance.US second print (required gate)",
            "",
            report.fee_note,
            "",
        ]
    )
    lines.extend(_slice_lines(report.binance_slice))
    lines.extend(
        [
            "",
            (
                "`api.binance.com` is HTTP 451 from this environment; "
                "`api.binance.us` is labeled **Binance.US**, not Binance.com. "
                "A short or overlapping BTC/ETH series fails closed. Empty "
                "Binance means zero dual-print passers (success). Missing "
                "SOL on Binance is report-only (not a two-asset fallback "
                "and not a gate)."
            ),
            "",
            "## Dual-print passers (promotion ranking)",
            "",
            (
                f"Frozen ranking key: `{report.ranking_key}`. Only "
                "calendar names that already clear combined on **both** "
                f"prints appear here. `{CONTROL_ID}` is excluded. Empty "
                "table = no promotee (success). A new Settings pin is "
                "added only if this table is non-empty, and then default "
                "**false**."
            ),
            "",
            (
                "| dual rank | id | Kraken mean HO | Binance mean HO | "
                "Kraken BTC HO | Kraken ETH HO | Kraken SOL HO | "
                "selected | can flip flag |"
            ),
            "| ---: | --- | ---: | ---: | ---: | ---: | ---: | :---: | :---: |",
        ]
    )
    if not dual_rows:
        lines.append("| — | — | n/a | n/a | n/a | n/a | n/a | no | no |")
    else:
        for row in dual_rows:
            lines.append(
                f"| {row.dual_print_rank} | `{row.candidate_id}` | "
                f"{_pct(row.kraken_mean_holdout_excess)} | "
                f"{_pct(row.binance_mean_holdout_excess)} | "
                f"{_pct(row.kraken_btc_holdout)} | {_pct(row.kraken_eth_holdout)} | "
                f"{_pct(row.kraken_sol_holdout)} | "
                f"{'yes' if row.selected else 'no'} | no |"
            )
    lines.extend(
        [
            "",
            "## Kraken combined-passers (informational)",
            "",
            (
                "These calendar names cleared #96+A+B+C on the Kraken "
                "primary window (BTC+ETH gates). They are **not** "
                "promotees unless they also appear in the dual-print "
                "table. Control omitted. SOL holdout is reported."
            ),
            "",
        ]
    )
    lines.extend(_passer_table(kraken_rows, venue="kraken"))
    lines.extend(
        [
            "",
            "## Binance.US combined-passers (informational)",
            "",
            (
                "These calendar names cleared #96+A+B+C on the Binance.US "
                "older-720. They cannot promote unless they also cleared "
                "Kraken. Control omitted. SOL holdout is reported."
            ),
            "",
        ]
    )
    lines.extend(_passer_table(binance_rows, venue="binance"))
    if report.eth_carried_ids:
        lines.extend(
            [
                "",
                "## #96 FAIL informational names (ETH-carried)",
                "",
                (
                    "These names have a **positive** Kraken mean holdout "
                    "excess while BTC holdout excess is ≤ 0. That is the "
                    "same honesty as `xs_mom_lo_vol_63` in #117 and "
                    "`tsmom_lo_63` / `tsmom_ls_63` in #119: the mean "
                    "is ETH-carried. **#96 FAIL**, not a combined-passer."
                ),
                "",
                "| id | Kraken mean HO | BTC HO | ETH HO |",
                "| --- | ---: | ---: | ---: |",
            ]
        )
        carried = {row.candidate_id: row for row in report.rows}
        for candidate_id in report.eth_carried_ids:
            row = carried[candidate_id]
            lines.append(
                f"| `{candidate_id}` | {_pct(row.kraken_mean_holdout_excess)} | "
                f"{_pct(row.kraken_btc_holdout)} | {_pct(row.kraken_eth_holdout)} |"
            )
    if report.btc_wf_fail_ids:
        lines.extend(
            [
                "",
                "## Informational BTC walk-forward fails",
                "",
                (
                    "These names have a **positive** Kraken mean holdout "
                    "and **positive** BTC holdout, but BTC walk-forward "
                    "total is ≤ 0. Same honesty as #118 Donchian, "
                    "#119 TSMOM, and #120 Bollinger. Still not an edge."
                ),
                "",
                "| id | Kraken mean HO | BTC HO | BTC WF |",
                "| --- | ---: | ---: | ---: |",
            ]
        )
        by_id = {row.candidate_id: row for row in report.rows}
        for candidate_id in report.btc_wf_fail_ids:
            row = by_id[candidate_id]
            lines.append(
                f"| `{candidate_id}` | {_pct(row.kraken_mean_holdout_excess)} | "
                f"{_pct(row.kraken_btc_holdout)} | {_pct(row.kraken_btc_wf)} |"
            )
    lines.extend(
        [
            "",
            "## Full catalog (informational)",
            "",
            (
                "| id | family | Kraken combined | Binance combined | dual-print | "
                "Kraken mean HO | Binance mean HO | Kraken BTC HO | Kraken ETH HO |"
            ),
            "| --- | --- | :---: | :---: | :---: | ---: | ---: | ---: | ---: |",
        ]
    )
    family_by_id = {
        item: (
            "control"
            if item in CONTROL_IDS
            else ("cal_dow" if item in DOW_IDS else ("cal_moy" if item in MOY_IDS else "cal_tom"))
        )
        for item in CORE_IDS
    }
    for row in report.rows:
        family_by_id[row.candidate_id] = (
            "control" if row.candidate_id in CONTROL_IDS else row.family
        )
    ordered = sorted(
        report.rows,
        key=lambda row: (
            0 if row.candidate_id not in CONTROL_IDS else 1,
            row.kraken_wf_rank if row.kraken_wf_rank is not None else 10**9,
            row.candidate_id,
        ),
    )
    for row in ordered:
        lines.append(
            f"| `{row.candidate_id}` | {family_by_id.get(row.candidate_id, row.family)} | "
            f"{_verdict(row.kraken_combined)} | "
            f"{_verdict(row.binance_combined)} | "
            f"{'yes' if row.dual_print and row.candidate_id not in CONTROL_IDS else 'no'} | "
            f"{_pct(row.kraken_mean_holdout_excess)} | "
            f"{_pct(row.binance_mean_holdout_excess)} | "
            f"{_pct(row.kraken_btc_holdout)} | {_pct(row.kraken_eth_holdout)} |"
        )
    # --- era prints / DSR / PBO (#135) ---
    lines.extend(render_evidence_lines(report.selection_evidence))
    lines.extend(
        [
            "",
            "## Operator recommendation",
            "",
            report.recommendation,
            "",
            (
                f"`keep_flag_false={str(report.keep_flag_false).lower()}`. "
                "Do not fabricate PnL. Do not enable live. Do not average "
                "Binance.US with the Kraken primary window. Do not re-run "
                "dead EMA dual-prints (#104 / #108), the #116 residual "
                "catalog, the #117 cross-sectional catalog, the #118 "
                "Donchian catalog, the #119 TSMOM catalog, or the #120 "
                "Bollinger catalog on the same windows. Do not invent "
                "carry basis. Do not data-mine weekday or month sets "
                "after seeing PnL."
            ),
            "",
        ]
    )
    return "\n".join(lines)
