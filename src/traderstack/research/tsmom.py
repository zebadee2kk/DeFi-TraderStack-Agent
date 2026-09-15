"""Time-series momentum (TSMOM) dual-print search (BTC+ETH; SOL optional).

Pre-registered before any live pull (do not retune after seeing PnL).

Treatment (frozen): on each asset, use **that asset's** trailing
N-day close-to-close return — not a cross-section rank, not a
Donchian channel, not an EMA cross. At bar t the return is
close[t] / close[t−N] − 1 (closes through t; same window as
``xs_momentum``). Long-only names are long when that return is > 0
and flat otherwise. Long/short names are long when the return is
> 0 and short when it is < 0 (flat on an exact zero).

N in {21, 63, 126, 252}. Vol-scaled *sign* variants
(``sign(return/vol)``) are **omitted**: when vol > 0 that sign
equals ``sign(return)``, so those ids would be duplicates. A
``return/vol`` *size* overlay would be GARCH-class sizing and is
out of scope. Do not add either after seeing PnL.

Fill at t+1 open (same convention as relative_value / xs_momentum /
donchian). Each asset is scored on its own closes. A missing/short
series is skipped, never zero-filled.

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

from dataclasses import dataclass
from datetime import UTC, datetime

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

TSMOM_LOOKBACKS: tuple[int, ...] = (21, 63, 126, 252)
# (candidate_id, lookback, long_short)
TSMOM_CATALOG: tuple[tuple[str, int, bool], ...] = (
    ("tsmom_lo_21", 21, False),
    ("tsmom_lo_63", 63, False),
    ("tsmom_lo_126", 126, False),
    ("tsmom_lo_252", 252, False),
    ("tsmom_ls_21", 21, True),
    ("tsmom_ls_63", 63, True),
    ("tsmom_ls_126", 126, True),
    ("tsmom_ls_252", 252, True),
)
TSMOM_IDS: tuple[str, ...] = tuple(item[0] for item in TSMOM_CATALOG)
CONTROL_ID = "ma_cross_10_30"
CONTROL_IDS: frozenset[str] = frozenset({CONTROL_ID})
CORE_IDS: tuple[str, ...] = TSMOM_IDS + (CONTROL_ID,)
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
DECISION_RULE = "closes_through_t"
FILL_RULE = "next_bar_open"
VOL_SCALED_OMITTED_REASON = (
    "sign(return/vol) equals sign(return) whenever vol > 0; a "
    "return/vol size overlay is GARCH-class sizing and is out of scope"
)

TSMOM_RULES = (
    "Pre-registered time-series momentum dual-print bar "
    "(frozen before any Kraken or Binance.US score). Treatment: "
    "each asset uses its own trailing N-day close-to-close return "
    f"(decision `{DECISION_RULE}`: close[t] / close[t-N] − 1). "
    "Long-only is long when that return is > 0 and flat otherwise. "
    "Long/short is long when the return is > 0 and short when it is "
    "< 0 (flat on an exact zero). N in {21, 63, 126, 252}. Vol-scaled "
    f"sign variants omitted ({VOL_SCALED_OMITTED_REASON}). This is "
    "not cross-sectional top-1 (#117) and not Donchian / channel "
    "breakout (#118). "
    f"Decision at bar t; fill `{FILL_RULE}` (t+1 open — no look-ahead "
    "into the fill bar). Each asset uses its own closes; a "
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
    "not Donchian / channel breakout, and not a carry/basis family."
)

TSMOM_CATALOG_NOTE = (
    "Frozen catalog (K=9): long-only time-series momentum "
    "(`tsmom_lo_{21,63,126,252}`), long/short symmetric "
    "(`tsmom_ls_{21,63,126,252}`), plus informational control "
    "ma_cross_10_30 (cannot promote). Vol-scaled sign variants "
    f"omitted ({VOL_SCALED_OMITTED_REASON}). Do not grow this list "
    "after seeing PnL. Trailing return is built from venue-local "
    "closes; a missing series is skipped, never zero-filled. "
    "PAPER_PROMOTE_* stays false unless a committed dual-print report "
    "names a paper-only pin and an operator flips it."
)

PAPER_EXECUTABLE_PATH_NOTE = (
    "This family is paper-executable on Kraken spot. Signals are "
    "candle-only long/short/flat on BTC/USD and ETH/USD (SOL/USD "
    "when present); paper_simulate_fills already books Side.BUY / "
    "Side.SELL. No perp, no funding, no hedge book, no invented "
    "basis. A Settings pin is still added only if a committed "
    "dual-print passer exists, and then default false."
)


def trailing_close_to_close_return(
    candles: tuple[Candle, ...],
    index: int,
    lookback: int,
) -> float | None:
    """N-day close-to-close return using closes through ``index``. No t+1."""
    if lookback <= 0 or index < lookback or index >= len(candles):
        return None
    start = candles[index - lookback].close
    end = candles[index].close
    if start <= 0 or end <= 0:
        return None
    return end / start - 1.0


def tsmom_position(
    trailing_return: float,
    *,
    long_short: bool,
) -> float:
    if trailing_return > 0:
        return 1.0
    if trailing_return < 0:
        return -1.0 if long_short else 0.0
    return 0.0


def tsmom_position_series(
    candles: tuple[Candle, ...],
    *,
    lookback: int,
    long_short: bool,
) -> tuple[tuple[datetime, float], ...]:
    """Point-in-time TSMOM positions. Skip-not-invent; no t+1 close."""
    if lookback <= 0 or len(candles) < lookback + 1:
        return ()
    out: list[tuple[datetime, float]] = []
    for index in range(lookback, len(candles)):
        trailing = trailing_close_to_close_return(candles, index, lookback)
        if trailing is None:
            continue
        out.append(
            (
                candles[index].opened_at,
                tsmom_position(trailing, long_short=long_short),
            )
        )
    return tuple(out)


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


def tsmom_signals(
    histories: dict[str, tuple[Candle, ...]],
    *,
    lookback: int,
    long_short: bool,
) -> dict[str, tuple[tuple[datetime, float], ...]]:
    """Per-asset TSMOM assignments. Missing assets omitted, not invented."""
    by_canonical = _histories_by_canonical(histories)
    per_asset: dict[str, tuple[tuple[datetime, float], ...]] = {}
    for asset, candles in by_canonical.items():
        series = tsmom_position_series(
            candles,
            lookback=lookback,
            long_short=long_short,
        )
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
class TimeSeriesMomentumVoter:
    """Look up a precomputed same-bar TSMOM position."""

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
                rationale="tsmom: no same-bar assignment (warmup / skipped)",
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
            rationale=f"tsmom assignment={value:+.0f}",
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


def _book_label(*, lookback: int, long_short: bool) -> str:
    book = "long/short" if long_short else "long-only"
    return f"{book} TSMOM {lookback}d trailing close-to-close"


def tsmom_candidates(
    histories: dict[str, tuple[Candle, ...]] | None = None,
    *,
    include_control: bool = True,
) -> tuple[SearchCandidate, ...]:
    """Instantiate the frozen catalog. Missing OHLC → that name omitted."""
    out: list[SearchCandidate] = []
    source = histories or {}
    for candidate_id, lookback, long_short in TSMOM_CATALOG:
        mapping = tsmom_signals(
            source,
            lookback=lookback,
            long_short=long_short,
        )
        if not mapping:
            continue
        by_symbol = tuple((key.upper(), values) for key, values in sorted(mapping.items()))
        out.append(
            SearchCandidate(
                candidate_id=candidate_id,
                family="tsmom",
                label=_book_label(lookback=lookback, long_short=long_short),
                params={
                    "lookback": lookback,
                    "long_short": long_short,
                    "decision_rule": DECISION_RULE,
                    "fill_rule": FILL_RULE,
                    "strategy_id": candidate_id,
                    "multi_asset_gate": MULTI_ASSET_GATE_RULE,
                },
                strategy=TimeSeriesMomentumVoter(
                    strategy_id=candidate_id,
                    signals_by_symbol=by_symbol,
                ),
            )
        )
    if include_control:
        out.append(_control_candidate())
    return tuple(out)


def skipped_tsmom_families(
    histories: dict[str, tuple[Candle, ...]],
) -> list[dict[str, str]]:
    skipped: list[dict[str, str]] = []
    for candidate_id, lookback, long_short in TSMOM_CATALOG:
        mapping = tsmom_signals(
            histories,
            lookback=lookback,
            long_short=long_short,
        )
        if mapping:
            continue
        skipped.append(
            {
                "family": "tsmom",
                "candidate_id": candidate_id,
                "reason": (
                    f"{_book_label(lookback=lookback, long_short=long_short)}"
                    ": skipped — need venue-local closes with at least "
                    f"{lookback + 1} bars. Skip rather than invent or "
                    "zero-fill closes."
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


def rank_tsmom_passers(rows: list[DualPrintRow]) -> list[DualPrintRow]:
    """Frozen ranking key among TSMOM dual-print passers. Control excluded."""
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


class TimeSeriesMomentumReport(BaseModel):
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
    rules: str = TSMOM_RULES
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
            "Same honesty as #118 Donchian — still not an edge."
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
        "or #108 EMA dual-prints. Do not re-run the #116 residual, "
        "#117 cross-sectional, or #118 Donchian catalogs on the same "
        "windows. Do not invent PIT basis for carry."
    )
    return "\n".join(lines)


def run_tsmom_search(
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
) -> TimeSeriesMomentumReport:
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

    catalog = candidates if candidates is not None else tsmom_candidates(kraken)
    skipped = skipped_tsmom_families(kraken)

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
            binance_catalog = tsmom_candidates(remapped)
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
    passers = rank_tsmom_passers(rows)
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
        TSMOM_RULES
        + " "
        + TSMOM_CATALOG_NOTE
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

    return TimeSeriesMomentumReport(
        # --- era prints / DSR / PBO (#135) ---
        selection_evidence=kraken_report.selection_evidence,
        generated_at=generated,
        ranking_key=RANKING_KEY,
        selection_rule=SELECTION_RULE,
        multi_asset_gate_rule=MULTI_ASSET_GATE_RULE,
        catalog_k_core=len(CORE_IDS),
        catalog_k_scored=len(catalog),
        catalog_ids=[item.candidate_id for item in catalog],
        catalog_note=TSMOM_CATALOG_NOTE,
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


def render_tsmom_markdown(
    report: TimeSeriesMomentumReport,
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
        "# Time-series momentum dual-print (BTC+ETH; SOL optional)",
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
            "On each asset at bar t, the signal is that asset's "
            f"trailing N-day close-to-close return (`{DECISION_RULE}`: "
            "close[t] / close[t−N] − 1). Long-only is long when the "
            "return is > 0 and flat otherwise. Long/short is long when "
            "the return is > 0 and short when it is < 0. The shared "
            f"backtest fills at `{FILL_RULE}` (bar t+1 open), so the "
            "decision never looks ahead into the fill bar. A missing "
            "series is skipped, never zero-filled. Vol-scaled sign "
            f"variants omitted ({VOL_SCALED_OMITTED_REASON}). Not "
            "cross-sectional top-1 (#117) and not Donchian (#118)."
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
                f"Frozen ranking key: `{report.ranking_key}`. Only TSMOM "
                "names that already clear combined on **both** prints "
                f"appear here. `{CONTROL_ID}` is excluded. Empty table = "
                "no promotee (success). A new Settings pin is added only "
                "if this table is non-empty, and then default **false**."
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
                "These TSMOM names cleared #96+A+B+C on the Kraken "
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
                "These TSMOM names cleared #96+A+B+C on the Binance.US "
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
                    "same honesty as `xs_mom_lo_vol_63` in #117: the mean "
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
                    "total is ≤ 0. Same honesty as #118 Donchian "
                    "(`donchian_ls_20` / `donchian_lo_20` / "
                    "`donchian_lo_atr_55`). Still not an edge."
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
    family_by_id = {item: ("control" if item in CONTROL_IDS else "tsmom") for item in CORE_IDS}
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
                "catalog, the #117 cross-sectional catalog, or the #118 "
                "Donchian catalog on the same windows. Do not invent "
                "carry basis."
            ),
            "",
        ]
    )
    return "\n".join(lines)
