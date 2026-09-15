"""BTC→ETH lead-lag dual-print (ETH follows lagged BTC; not #116 residual).

Pre-registered before any live pull (do not retune after seeing PnL).

Treatment (frozen): the **traded** asset's position follows (or fades)
the **lead** asset's trailing L-day close-to-close return. This is
**not** same-bar residual z-score on ``r_BTC − r_ETH`` (#116) and
**not** own-asset TSMOM (#119).

Decision rule (frozen): ``lead_closes_through_t``. At aligned pair-day
t the lead return is lead_close[t] / lead_close[t−L] − 1. L ≥ 1.
The gate uses the lead asset's close at t and **never** the traded
asset's same-bar close. When trading ETH, same-bar ETH does not
enter the signal. Fill at t+1 open of the **traded** asset (no
look-ahead into the fill bar).

Unpaired BTC/ETH days are skipped, never zero-filled. L-day return
is measured on the aligned pair series (L aligned pair-days), not
across a gap that invented a close.

Other-leg book (frozen): every catalog id produces **both** BTC and
ETH books. ETH-traded names: ETH = lead-lag vs lagged BTC; BTC =
**flat**. BTC-traded mirror names: BTC = lead-lag vs lagged ETH;
ETH = **flat**. Combined #96+A+B+C still requires **both** legs
(standing #96). The other leg is not ``ma_cross_10_30`` and not
own-asset TSMOM — those would reprint another family.

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

Paper-executable on Kraken spot (BTC/USD + ETH/USD via
``paper_simulate_fills``). Empty dual-print set is success. This
module never flips ``PAPER_PROMOTE_*`` and does not add a Settings
pin unless a committed report names a dual-print passer (default
false if added). No live.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic import BaseModel, Field

from traderstack.candles import Candle
from traderstack.fee_tiers import FeeTierStamp
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

# (candidate_id, traded, lead, lookback, book)
# book in {follow_lo, follow_ls, fade_lo}
LEADLAG_CATALOG: tuple[tuple[str, str, str, int, str], ...] = (
    ("leadlag_eth_follow_lo_1", "ETH", "BTC", 1, "follow_lo"),
    ("leadlag_eth_follow_lo_2", "ETH", "BTC", 2, "follow_lo"),
    ("leadlag_eth_follow_lo_3", "ETH", "BTC", 3, "follow_lo"),
    ("leadlag_eth_follow_lo_5", "ETH", "BTC", 5, "follow_lo"),
    ("leadlag_eth_follow_ls_1", "ETH", "BTC", 1, "follow_ls"),
    ("leadlag_eth_follow_ls_2", "ETH", "BTC", 2, "follow_ls"),
    ("leadlag_eth_follow_ls_3", "ETH", "BTC", 3, "follow_ls"),
    ("leadlag_eth_fade_lo_1", "ETH", "BTC", 1, "fade_lo"),
    ("leadlag_eth_fade_lo_2", "ETH", "BTC", 2, "fade_lo"),
    ("leadlag_eth_fade_lo_3", "ETH", "BTC", 3, "fade_lo"),
    ("leadlag_btc_follow_lo_1", "BTC", "ETH", 1, "follow_lo"),
    ("leadlag_btc_follow_lo_2", "BTC", "ETH", 2, "follow_lo"),
)
LEADLAG_IDS: tuple[str, ...] = tuple(item[0] for item in LEADLAG_CATALOG)
ETH_TRADED_IDS: tuple[str, ...] = tuple(item[0] for item in LEADLAG_CATALOG if item[1] == "ETH")
BTC_TRADED_IDS: tuple[str, ...] = tuple(item[0] for item in LEADLAG_CATALOG if item[1] == "BTC")
CONTROL_ID = "ma_cross_10_30"
CONTROL_IDS: frozenset[str] = frozenset({CONTROL_ID})
CORE_IDS: tuple[str, ...] = LEADLAG_IDS + (CONTROL_ID,)
UNIVERSE: tuple[str, ...] = ("BTC/USD", "ETH/USD")
SCORE_SYMBOLS: frozenset[str] = frozenset(UNIVERSE)
ALIAS_TO_CANONICAL: dict[str, str] = {
    "BTC/USD": "BTC/USD",
    "BTCUSDT": "BTC/USD",
    "BTC-USD": "BTC/USD",
    "XBT/USD": "BTC/USD",
    "ETH/USD": "ETH/USD",
    "ETHUSDT": "ETH/USD",
    "ETH-USD": "ETH/USD",
}
CANONICAL_TO_ASSET: dict[str, str] = {"BTC/USD": "BTC", "ETH/USD": "ETH"}
ASSET_TO_CANONICAL: dict[str, str] = {"BTC": "BTC/USD", "ETH": "ETH/USD"}
PAPER_PATH_READY = True
MULTI_ASSET_GATE_RULE = "btc_eth_both_legs_96_abc_other_leg_flat"
DECISION_RULE = "lead_closes_through_t"
FILL_RULE = "next_bar_open"
OTHER_LEG_RULE = "flat_on_aligned_pair_days"
RESIDUAL_OMITTED_REASON = (
    "not same-bar residual z-score on r_BTC − r_ETH (#116); the gate "
    "uses only the lead asset's L-day return (L≥1)"
)

LEADLAG_RULES = (
    "Pre-registered BTC→ETH lead-lag dual-print bar "
    "(frozen before any Kraken or Binance.US score). Treatment: "
    "the traded asset follows or fades the lead asset's trailing "
    f"L-day close-to-close return (decision `{DECISION_RULE}`: "
    "lead_close[t] / lead_close[t-L] − 1 on aligned pair-days). "
    "L ≥ 1, so when trading ETH the gate does not use same-bar ETH. "
    f"{RESIDUAL_OMITTED_REASON}. Follow long-only is long the traded "
    "asset when the lead return is > 0 and flat otherwise. Follow "
    "long/short is the sign of the lead return (flat on exact zero). "
    "Fade long-only is long the traded asset when the lead return is "
    "< 0 and flat otherwise (mean-revert the lead). Mirror names "
    "trade BTC following lagged ETH (small frozen set). "
    f"Other-leg book `{OTHER_LEG_RULE}`: ETH-traded names keep BTC "
    "flat; BTC-traded names keep ETH flat. Combined #96+A+B+C still "
    "requires both legs (standing #96). The other leg is not "
    "ma_cross_10_30 and not own-asset TSMOM. "
    f"Decision at bar t; fill `{FILL_RULE}` on the traded asset "
    "(t+1 open — no look-ahead into the fill bar). Unpaired BTC/ETH "
    "days are skipped, never zero-filled. "
    f"Multi-asset combined bar: `{MULTI_ASSET_GATE_RULE}` — #96 "
    "balanced-holdout and A magnitude and B multi-window and C 2× "
    "fees on BTC and ETH (both legs). Equal-weight portfolio "
    "metrics are not used. A dual-print passer must combined-PASS "
    "the Kraken primary 720-bar daily window AND the #102 "
    "Binance.US older-720 "
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
    "Kraken spot BTC/USD+ETH/USD "
    f"(PAPER_PATH_READY={str(PAPER_PATH_READY).lower()}). "
    "PAPER_PROMOTE_* stays default false. No live. An empty "
    "dual-print set is success. Not an EMA reprint, not a "
    "BTC−ETH residual reprint, not cross-sectional momentum, "
    "not Donchian / channel breakout, not TSMOM, not Bollinger "
    "fade, not calendar seasonality, and not a carry/basis family."
)

LEADLAG_CATALOG_NOTE = (
    "Frozen catalog (K=13): ETH follows lagged BTC long-only "
    "(`leadlag_eth_follow_lo_{1,2,3,5}`), ETH follows lagged BTC "
    "long/short (`leadlag_eth_follow_ls_{1,2,3}`), ETH fades lagged "
    "BTC long-only (`leadlag_eth_fade_lo_{1,2,3}`), BTC follows "
    "lagged ETH long-only mirror (`leadlag_btc_follow_lo_{1,2}`), "
    "plus informational control ma_cross_10_30 (cannot promote). "
    "Do not grow this list or retune L after seeing PnL. Lead "
    f"return uses `{DECISION_RULE}` on aligned pair-days; unpaired "
    "days are skipped, never zero-filled. Other-leg book is "
    f"`{OTHER_LEG_RULE}`. PAPER_PROMOTE_* stays false unless a "
    "committed dual-print report names a paper-only pin and an "
    "operator flips it."
)

PAPER_EXECUTABLE_PATH_NOTE = (
    "This family is paper-executable on Kraken spot. Signals are "
    "candle-only long/short/flat on BTC/USD and ETH/USD; "
    "paper_simulate_fills already books Side.BUY / Side.SELL. No "
    "perp, no funding, no hedge book, no invented basis. A Settings "
    "pin is still added only if a committed dual-print passer "
    "exists, and then default false."
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


def aligned_pair_days(
    btc: tuple[Candle, ...] | None,
    eth: tuple[Candle, ...] | None,
) -> tuple[tuple[datetime, float, float], ...]:
    """Common ``opened_at`` days with both closes > 0. Skip unpaired."""
    if not btc or not eth:
        return ()
    btc_close = {candle.opened_at: candle.close for candle in btc}
    eth_close = {candle.opened_at: candle.close for candle in eth}
    common = sorted(set(btc_close) & set(eth_close))
    out: list[tuple[datetime, float, float]] = []
    for ts in common:
        btc_px = btc_close[ts]
        eth_px = eth_close[ts]
        if btc_px <= 0 or eth_px <= 0:
            continue
        out.append((ts, btc_px, eth_px))
    return tuple(out)


def lead_trailing_return(
    lead_closes: tuple[float, ...],
    index: int,
    lookback: int,
) -> float | None:
    """L-day close-to-close using closes through ``index``. No t+1."""
    if lookback <= 0 or index < lookback or index >= len(lead_closes):
        return None
    start = lead_closes[index - lookback]
    end = lead_closes[index]
    if start <= 0 or end <= 0:
        return None
    return end / start - 1.0


def leadlag_position(lead_return: float, *, book: str) -> float:
    if book == "follow_lo":
        return 1.0 if lead_return > 0 else 0.0
    if book == "follow_ls":
        if lead_return > 0:
            return 1.0
        if lead_return < 0:
            return -1.0
        return 0.0
    if book == "fade_lo":
        return 1.0 if lead_return < 0 else 0.0
    raise ValueError(f"unknown lead-lag book: {book}")


def leadlag_position_series(
    pair_days: tuple[tuple[datetime, float, float], ...],
    *,
    lead: str,
    lookback: int,
    book: str,
) -> tuple[tuple[datetime, float], ...]:
    """Point-in-time lead-lag positions on aligned pair-days. No t+1."""
    if lookback <= 0 or len(pair_days) < lookback + 1:
        return ()
    if lead == "BTC":
        lead_closes = tuple(row[1] for row in pair_days)
    elif lead == "ETH":
        lead_closes = tuple(row[2] for row in pair_days)
    else:
        raise ValueError(f"unknown lead asset: {lead}")
    out: list[tuple[datetime, float]] = []
    for index in range(lookback, len(pair_days)):
        trailing = lead_trailing_return(lead_closes, index, lookback)
        if trailing is None:
            continue
        out.append((pair_days[index][0], leadlag_position(trailing, book=book)))
    return tuple(out)


def leadlag_signals(
    histories: dict[str, tuple[Candle, ...]],
    *,
    traded: str,
    lead: str,
    lookback: int,
    book: str,
) -> dict[str, tuple[tuple[datetime, float], ...]]:
    """Traded-leg lead-lag + other-leg flat. Missing pair → empty."""
    by_canonical = _histories_by_canonical(histories)
    btc = by_canonical.get("BTC/USD")
    eth = by_canonical.get("ETH/USD")
    pair_days = aligned_pair_days(btc, eth)
    series = leadlag_position_series(
        pair_days,
        lead=lead,
        lookback=lookback,
        book=book,
    )
    if not series:
        return {}
    flat = tuple((ts, 0.0) for ts, _ in series)
    traded_canonical = ASSET_TO_CANONICAL[traded]
    mapping: dict[str, tuple[tuple[datetime, float], ...]] = {}
    for alias, canonical in ALIAS_TO_CANONICAL.items():
        mapping[alias] = series if canonical == traded_canonical else flat
    return mapping


@dataclass(frozen=True)
class LeadLagVoter:
    """Look up a precomputed same-bar lead-lag position."""

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
                rationale="leadlag: no same-bar assignment (warmup / unpaired)",
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
            rationale=f"leadlag assignment={value:+.0f}",
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


def _book_label(*, traded: str, lead: str, lookback: int, book: str) -> str:
    verbs = {
        "follow_lo": "follow long-only",
        "follow_ls": "follow long/short",
        "fade_lo": "fade long-only",
    }
    return f"{verbs[book]} {traded} on lagged {lead} {lookback}d ({DECISION_RULE})"


def leadlag_candidates(
    histories: dict[str, tuple[Candle, ...]] | None = None,
    *,
    include_control: bool = True,
) -> tuple[SearchCandidate, ...]:
    """Instantiate the frozen catalog. Missing pair → that name omitted."""
    out: list[SearchCandidate] = []
    source = histories or {}
    for candidate_id, traded, lead, lookback, book in LEADLAG_CATALOG:
        mapping = leadlag_signals(
            source,
            traded=traded,
            lead=lead,
            lookback=lookback,
            book=book,
        )
        if not mapping:
            continue
        by_symbol = tuple((key.upper(), values) for key, values in sorted(mapping.items()))
        out.append(
            SearchCandidate(
                candidate_id=candidate_id,
                family="lead_lag",
                label=_book_label(traded=traded, lead=lead, lookback=lookback, book=book),
                params={
                    "traded": traded,
                    "lead": lead,
                    "lookback": lookback,
                    "book": book,
                    "decision_rule": DECISION_RULE,
                    "fill_rule": FILL_RULE,
                    "other_leg_rule": OTHER_LEG_RULE,
                    "strategy_id": candidate_id,
                    "multi_asset_gate": MULTI_ASSET_GATE_RULE,
                },
                strategy=LeadLagVoter(
                    strategy_id=candidate_id,
                    signals_by_symbol=by_symbol,
                ),
            )
        )
    if include_control:
        out.append(_control_candidate())
    return tuple(out)


def skipped_leadlag_families(
    histories: dict[str, tuple[Candle, ...]],
) -> list[dict[str, str]]:
    skipped: list[dict[str, str]] = []
    for candidate_id, traded, lead, lookback, book in LEADLAG_CATALOG:
        mapping = leadlag_signals(
            histories,
            traded=traded,
            lead=lead,
            lookback=lookback,
            book=book,
        )
        if mapping:
            continue
        skipped.append(
            {
                "family": "lead_lag",
                "candidate_id": candidate_id,
                "reason": (
                    f"{_book_label(traded=traded, lead=lead, lookback=lookback, book=book)}"
                    ": skipped — need aligned BTC and ETH daily pair "
                    f"with at least {lookback + 1} pair-days. Skip "
                    "rather than invent or zero-fill unpaired days."
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


def rank_leadlag_passers(rows: list[DualPrintRow]) -> list[DualPrintRow]:
    """Frozen ranking key among lead-lag dual-print passers. Control excluded."""
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


class LeadLagReport(BaseModel):
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
    pair_days: int = 0
    pair_first: str | None = None
    pair_last: str | None = None
    binance_slice: SliceMeta
    binance_source: str | None = None
    binance_pair_days: int = 0
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
    rules: str = LEADLAG_RULES
    gates_note: str = HARDER_GATES_NOTE
    fee_note: str = BINANCE_TAKER_BPS_NOTE
    kraken_cap_note: str = KRAKEN_DAILY_CAP_NOTE
    paper_path_note: str = PAPER_EXECUTABLE_PATH_NOTE
    data_notes: list[str] = Field(default_factory=list)
    # --- fee realism (#138) ---
    fee_tier: FeeTierStamp | None = None


def _recommendation(
    *,
    selected_id: str | None,
    dual_ids: list[str],
    kraken_ids: list[str],
    binance_meta: SliceMeta,
    eth_carried: list[str],
    btc_wf_fail: list[str],
    pair_days: int,
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
            f"{binance_meta.bars_eth} ETH; "
            f"{binance_meta.first} → {binance_meta.last})."
        ),
        (
            f"- Multi-asset gate: `{MULTI_ASSET_GATE_RULE}` (other leg "
            f"`{OTHER_LEG_RULE}`; both BTC and ETH must clear #96+A+B+C)."
        ),
        (
            f"- Aligned pair-days (Kraken): {pair_days}. Unpaired days "
            "were skipped, not zero-filled."
        ),
        (
            f"- Paper path: ready on Kraken spot BTC/ETH "
            f"(PAPER_PATH_READY={str(PAPER_PATH_READY).lower()})."
        ),
    ]
    if eth_carried:
        lines.append(
            "- #96 FAIL (ETH-carried informational mean HO; BTC holdout "
            f"≤ 0): {', '.join(f'`{item}`' for item in eth_carried)}. "
            "A positive mean with a losing BTC holdout is not an edge. "
            "ETH-traded names keep BTC flat, so a losing BTC holdout vs "
            "buy-and-hold is the expected #96 fail-closed posture."
        )
    if btc_wf_fail:
        lines.append(
            "- Informational positive mean HO and BTC HO with BTC "
            f"walk-forward ≤ 0: {', '.join(f'`{item}`' for item in btc_wf_fail)}. "
            "Same honesty as #118 Donchian / #119 TSMOM — still not an edge."
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
        "#117 cross-sectional, #118 Donchian, #119 TSMOM, #120 "
        "Bollinger, or #121 calendar catalogs on the same windows. "
        "Do not invent PIT basis for carry."
    )
    return "\n".join(lines)


def run_lead_lag_search(
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
    # --- fee realism (#138) ---
    fee_tier: FeeTierStamp | None = None,
) -> LeadLagReport:
    generated = now or datetime.now(UTC)
    kraken = _score_symbols_only(kraken_histories)
    if not kraken:
        raise ValueError("no Kraken BTC/ETH daily histories provided")
    primary_first, primary_source = primary_first_opened_at(kraken)
    btc = kraken_daily_candles(kraken, "BTC/USD")
    eth = kraken_daily_candles(kraken, "ETH/USD")
    primary_last = btc[-1].opened_at.isoformat() if btc else None
    primary_bars = len(btc) if btc else None
    pair_days = aligned_pair_days(btc, eth)
    pair_count = len(pair_days)
    pair_first = pair_days[0][0].isoformat() if pair_days else None
    pair_last = pair_days[-1][0].isoformat() if pair_days else None

    catalog = candidates if candidates is not None else leadlag_candidates(kraken)
    skipped = skipped_leadlag_families(kraken)

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
    binance_pair = aligned_pair_days(
        remapped.get("BTC/USD@1d"),
        remapped.get("ETH/USD@1d"),
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
            binance_catalog = leadlag_candidates(remapped)
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
    passers = rank_leadlag_passers(rows)
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
        LEADLAG_RULES
        + " "
        + LEADLAG_CATALOG_NOTE
        + f" This run scored K={len(catalog)} (core ids frozen at "
        f"{len(CORE_IDS)}). Aligned pair-days: {pair_count}. "
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
    if pair_days:
        notes.append(
            f"BTC+ETH aligned pair-days: {pair_count} "
            f"{pair_first} → {pair_last} (unpaired days omitted)."
        )
    else:
        notes.append(
            "BTC+ETH pair unavailable (need aligned BTC and ETH "
            "closes). Lead-lag names skipped, not invented."
        )
    if not btc or not eth:
        notes.append(
            "BTC and/or ETH daily series missing on Kraken. Combined "
            "gates cannot pass. Skip-not-invent; do not zero-fill."
        )
    if binance_meta.available:
        notes.append(
            f"Binance.US aligned pair-days: {len(binance_pair)} (same skip-not-invent rule)."
        )

    return LeadLagReport(
        # --- era prints / DSR / PBO (#135) ---
        selection_evidence=kraken_report.selection_evidence,
        generated_at=generated,
        ranking_key=RANKING_KEY,
        selection_rule=SELECTION_RULE,
        multi_asset_gate_rule=MULTI_ASSET_GATE_RULE,
        catalog_k_core=len(CORE_IDS),
        catalog_k_scored=len(catalog),
        catalog_ids=[item.candidate_id for item in catalog],
        catalog_note=LEADLAG_CATALOG_NOTE,
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
        pair_days=pair_count,
        pair_first=pair_first,
        pair_last=pair_last,
        binance_slice=binance_meta,
        binance_source=binance_source,
        binance_pair_days=len(binance_pair),
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
            pair_days=pair_count,
        ),
        data_notes=notes,
        # --- fee realism (#138) ---
        fee_tier=fee_tier,
    )


def _slice_lines(meta: SliceMeta) -> list[str]:
    status = "available" if meta.available else "UNAVAILABLE / fail-closed"
    return [
        f"- Rule: `{meta.rule}`",
        f"- Venue label: `{meta.venue}`",
        f"- Status: **{status}**",
        f"- Bars: BTC {meta.bars_btc} / ETH {meta.bars_eth}",
        f"- Span: {meta.first or 'n/a'} → {meta.last or 'n/a'}",
        f"- Overlaps primary window: {'yes' if meta.overlaps_primary_window else 'no'}",
        f"- Fail-closed reason: {meta.fail_closed_reason or '—'}",
    ]


def _passer_table(rows: list[DualPrintRow], *, venue: str) -> list[str]:
    if venue == "kraken":
        header = "| rank | id | mean HO | BTC HO | ETH HO | ratio | #96 | A | B | C | dual-print |"
        sep = "| ---: | --- | ---: | ---: | ---: | ---: | :---: | :---: | :---: | :---: | :---: |"
    else:
        header = "| id | mean HO | BTC HO | ETH HO | ratio | #96 | A | B | C | dual-print |"
        sep = "| --- | ---: | ---: | ---: | ---: | ---: | :---: | :---: | :---: | :---: |"
    lines = [header, sep]
    if not rows:
        if venue == "kraken":
            lines.append("| — | — | n/a | n/a | n/a | n/a | — | — | — | — | no |")
        else:
            lines.append("| — | n/a | n/a | n/a | n/a | — | — | — | — | no |")
        return lines
    for row in rows:
        if venue == "kraken":
            lines.append(
                f"| {row.kraken_combined_rank or '—'} | `{row.candidate_id}` | "
                f"{_pct(row.kraken_mean_holdout_excess)} | "
                f"{_pct(row.kraken_btc_holdout)} | {_pct(row.kraken_eth_holdout)} | "
                f"{_ratio(row.kraken_holdout_ratio)} | "
                f"{_verdict(row.kraken_eligible_96)} | {_verdict(row.kraken_gate_a)} | "
                f"{_verdict(row.kraken_gate_b)} | {_verdict(row.kraken_gate_c)} | "
                f"{'yes' if row.dual_print else 'no'} |"
            )
        else:
            lines.append(
                f"| `{row.candidate_id}` | {_pct(row.binance_mean_holdout_excess)} | "
                f"{_pct(row.binance_btc_holdout)} | {_pct(row.binance_eth_holdout)} | "
                f"{_ratio(row.binance_holdout_ratio)} | "
                f"{_verdict(row.binance_eligible_96)} | {_verdict(row.binance_gate_a)} | "
                f"{_verdict(row.binance_gate_b)} | {_verdict(row.binance_gate_c)} | "
                f"{'yes' if row.dual_print else 'no'} |"
            )
    return lines


def render_lead_lag_markdown(report: LeadLagReport) -> str:
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
        "# BTC→ETH lead-lag dual-print",
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
        # --- fee realism (#138) ---
        *([report.fee_tier.render_line()] if report.fee_tier is not None else []),
        (
            f"Primary Kraken first bar: {report.primary_first} "
            f"(source=`{report.primary_first_source}`; last="
            f"{report.primary_last or 'n/a'}; bars BTC="
            f"{report.primary_bars or 'n/a'} / ETH="
            f"{report.primary_bars_eth or 'n/a'})."
        ),
        (
            f"Aligned pair-days: {report.pair_days} "
            f"({report.pair_first or 'n/a'} → {report.pair_last or 'n/a'})."
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
            f"#96+A+B+C on BTC+ETH (other leg `{OTHER_LEG_RULE}`); "
            f"rank among dual-print passers by `{report.ranking_key}` "
            "| **Kraken mean HO only** |"
        ),
        (
            "| Binance.US older 720 | same #102 definition: 720 committed "
            "daily BTC+ETH bars ending before the primary Kraken first "
            "bar; must combined-PASS | **no** (gate only; not averaged) |"
        ),
        (
            f"| Kraken-only combined ranking (`{KRAKEN_COMBINED_RANKING_KEY}`) "
            "| informational | no |"
        ),
        "",
        "## Multi-asset gate (frozen)",
        "",
        (
            f"`{report.multi_asset_gate_rule}`: every catalog id "
            "produces a BTC book and an ETH book. ETH-traded names "
            "run the lead-lag rule on ETH and keep BTC **flat**. "
            "BTC-traded mirror names run the lead-lag rule on BTC "
            "and keep ETH **flat**. Combined #96+A+B+C still "
            "requires **both** legs (standing #96 — ETH-only "
            "strength cannot promote). The other leg is not "
            "`ma_cross_10_30` and not own-asset TSMOM. "
            "Equal-weight portfolio metrics were considered and "
            "**rejected** before scoring."
        ),
        "",
        "## Treatment (frozen)",
        "",
        (
            "At aligned pair-day t the lead return is the lead "
            f"asset's trailing L-day close-to-close "
            f"(`{DECISION_RULE}`: lead_close[t] / lead_close[t−L] "
            "− 1). L ≥ 1. The gate uses the lead close at t and "
            "**never** the traded asset's same-bar close — when "
            "trading ETH, same-bar ETH does not enter the signal. "
            "This is not #116 residual z-score on `r_BTC − r_ETH`. "
            "Follow long-only: long the traded asset when the lead "
            "return is > 0, else flat. Follow long/short: sign of "
            "the lead return. Fade long-only: long the traded "
            "asset when the lead return is < 0, else flat. The "
            f"shared backtest fills at `{FILL_RULE}` on the traded "
            "asset (bar t+1 open), so the decision never looks "
            "ahead into the fill bar. Unpaired BTC/ETH days are "
            "skipped, never zero-filled."
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
                "Binance means zero dual-print passers (success)."
            ),
            "",
            "## Dual-print passers (promotion ranking)",
            "",
            (
                f"Frozen ranking key: `{report.ranking_key}`. Only "
                "lead-lag names that already clear combined on **both** "
                f"prints appear here. `{CONTROL_ID}` is excluded. Empty "
                "table = no promotee (success). A new Settings pin is "
                "added only if this table is non-empty, and then "
                "default **false**."
            ),
            "",
            (
                "| dual rank | id | Kraken mean HO | Binance mean HO | "
                "Kraken BTC HO | Kraken ETH HO | selected | can flip flag |"
            ),
            "| ---: | --- | ---: | ---: | ---: | ---: | :---: | :---: |",
        ]
    )
    if not dual_rows:
        lines.append("| — | — | n/a | n/a | n/a | n/a | no | no |")
    else:
        for row in dual_rows:
            lines.append(
                f"| {row.dual_print_rank} | `{row.candidate_id}` | "
                f"{_pct(row.kraken_mean_holdout_excess)} | "
                f"{_pct(row.binance_mean_holdout_excess)} | "
                f"{_pct(row.kraken_btc_holdout)} | {_pct(row.kraken_eth_holdout)} | "
                f"{'yes' if row.selected else 'no'} | no |"
            )
    lines.extend(
        [
            "",
            "## Kraken combined-passers (informational)",
            "",
            (
                "These lead-lag names cleared #96+A+B+C on the Kraken "
                "primary window (both BTC and ETH legs). They are "
                "**not** promotees unless they also appear in the "
                "dual-print table. Control omitted."
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
                "These lead-lag names cleared #96+A+B+C on the "
                "Binance.US older-720. They cannot promote unless they "
                "also cleared Kraken. Control omitted."
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
                    "`tsmom_lo_63` / `tsmom_ls_63` in #119: the mean is "
                    "ETH-carried. **#96 FAIL**, not a combined-passer. "
                    "ETH-traded names keep BTC flat, so a losing BTC "
                    "holdout vs buy-and-hold is expected and is not an "
                    "edge."
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
                    "total is ≤ 0. Same honesty as #118 Donchian / "
                    "#119 TSMOM. Still not an edge."
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
    family_by_id = {item: ("control" if item in CONTROL_IDS else "lead_lag") for item in CORE_IDS}
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
                "Donchian catalog, the #119 TSMOM catalog, the #120 "
                "Bollinger catalog, or the #121 calendar catalog on the "
                "same windows. Do not invent carry basis."
            ),
            "",
        ]
    )
    return "\n".join(lines)
