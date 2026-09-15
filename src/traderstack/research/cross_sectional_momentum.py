"""Cross-sectional momentum: BTC+ETH+SOL dual-print search.

Pre-registered before any live pull (do not retune after seeing PnL).

Treatment (frozen): among {BTC, ETH, SOL}, rank by trailing N-day
close-to-close return (N in {21, 63, 126}). Long the top-1 name;
dollar-neutral variants also short the bottom-1. Optional vol-scaled
rank uses trailing return / trailing sample vol over the same N.
Long-only variants are labeled ``lo``; dollar-neutral long/short
variants are labeled ``ls``.

A ranking day requires **all three** venue-local closes. A day missing
any asset is skipped, not ranked on a two-asset subset and not
zero-filled. Tie-break (frozen): higher score first, then
alphabetical canonical symbol (BTC/USD < ETH/USD < SOL/USD). Signal
is valid only on the same ``opened_at`` (no stale hold).

Multi-asset combined bar (frozen before scoring): the same #96+A+B+C
harder gates as #104 on **BTC and ETH**. SOL walk-forward and holdout
are reported and are **not** a gate. Equal-weight portfolio metrics
are not used (that would be a different bar).

A name is a **dual-print passer** only if it clears combined harder
gates on **both**:

1. The Kraken public Spot daily primary window (720-bar cap).
2. The #102 Binance.US Spot daily print: 720 committed BTC+ETH bars
   ending strictly before the primary Kraken first bar. SOL is
   required to instantiate the catalog on that venue.

Ranking key (frozen): ``mean_holdout_excess_among_dual_print_passers``
— Kraken BTC+ETH mean holdout excess among names that already cleared
both prints. Tie-break: ``candidate_id``. Binance holdout is a gate,
never averaged. A Kraken-only combined-passer cannot promote.

The informational control ``ma_cross_10_30`` is scored on the same
windows and **cannot** enter the passer set.

Paper-executable on Kraken spot (BTC/USD + ETH/USD + SOL/USD via
``paper_simulate_fills``). Empty dual-print set is success. This
module never flips ``PAPER_PROMOTE_*`` and does not add a Settings
pin unless a committed report names a dual-print passer (default
false if added). No live.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import pairwise

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

XS_LOOKBACKS: tuple[int, ...] = (21, 63, 126)
# (candidate_id, lookback, long_short, vol_scaled)
XS_CATALOG: tuple[tuple[str, int, bool, bool], ...] = (
    ("xs_mom_ls_21", 21, True, False),
    ("xs_mom_ls_63", 63, True, False),
    ("xs_mom_ls_126", 126, True, False),
    ("xs_mom_lo_21", 21, False, False),
    ("xs_mom_lo_63", 63, False, False),
    ("xs_mom_lo_126", 126, False, False),
    ("xs_mom_ls_vol_21", 21, True, True),
    ("xs_mom_ls_vol_63", 63, True, True),
    ("xs_mom_ls_vol_126", 126, True, True),
    ("xs_mom_lo_vol_21", 21, False, True),
    ("xs_mom_lo_vol_63", 63, False, True),
    ("xs_mom_lo_vol_126", 126, False, True),
)
XS_IDS: tuple[str, ...] = tuple(item[0] for item in XS_CATALOG)
CONTROL_ID = "ma_cross_10_30"
CONTROL_IDS: frozenset[str] = frozenset({CONTROL_ID})
CORE_IDS: tuple[str, ...] = XS_IDS + (CONTROL_ID,)
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

CROSS_SECTIONAL_RULES = (
    "Pre-registered BTC+ETH+SOL cross-sectional momentum dual-print "
    "bar (frozen before any Kraken or Binance.US score). Treatment: "
    "long top-1 by trailing N-day return among {BTC, ETH, SOL}; "
    "dollar-neutral `ls` also shorts bottom-1. N in {21, 63, 126}. "
    "Optional `vol` ranks by trailing return / trailing sample vol "
    "over the same N (ranking transform, not a size overlay). "
    "Long-only variants are labeled `lo`. A ranking day requires all "
    "three venue-local closes; a missing asset day is skipped, not "
    "ranked on a two-asset subset and not zero-filled. Tie-break: "
    "higher score, then alphabetical canonical symbol. Signal is "
    "valid only on the same opened_at (no stale hold). "
    f"Multi-asset combined bar: `{MULTI_ASSET_GATE_RULE}` — #96 "
    "balanced-holdout and A magnitude and B multi-window and C 2× "
    "fees on BTC and ETH; SOL is reported and is not a gate. "
    "Equal-weight portfolio metrics are not used. A dual-print "
    "passer must combined-PASS the Kraken primary 720-bar daily "
    "window AND the #102 Binance.US older-720 "
    f"(`{BINANCE_SLICE_RULE}`: {SECOND_PRINT_BARS} committed daily "
    "BTC+ETH bars ending strictly before the primary Kraken first "
    "bar). SOL must exist on a venue to instantiate the XS catalog "
    "there (skip-not-invent). "
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
    "Kraken spot BTC/USD+ETH/USD+SOL/USD "
    f"(PAPER_PATH_READY={str(PAPER_PATH_READY).lower()}). "
    "PAPER_PROMOTE_* stays default false. No live. An empty "
    "dual-print set is success. Not an EMA reprint, not a "
    "BTC−ETH residual reprint, and not a carry/basis family."
)

CROSS_SECTIONAL_CATALOG_NOTE = (
    "Frozen catalog (K=13): dollar-neutral long-top-1 / short-bottom-1 "
    "(`xs_mom_ls_{N}`) and long-only top-1 (`xs_mom_lo_{N}`) at N in "
    "{21, 63, 126}, plus the same books with vol-scaled ranking "
    "(`_vol_`), plus informational control ma_cross_10_30 (cannot "
    "promote). Do not grow this list after seeing PnL. Ranking is "
    "built from venue-local BTC, ETH, and SOL daily closes; a day "
    "missing any of the three is skipped. PAPER_PROMOTE_* stays "
    "false unless a committed dual-print report names a paper-only "
    "pin and an operator flips it."
)

PAPER_EXECUTABLE_PATH_NOTE = (
    "This family is paper-executable on Kraken spot. Signals are "
    "candle-only long/short/flat on BTC/USD, ETH/USD, and SOL/USD; "
    "paper_simulate_fills already books Side.BUY / Side.SELL. No "
    "perp, no funding, no hedge book, no invented basis. A Settings "
    "pin is still added only if a committed dual-print passer "
    "exists, and then default false."
)


def _sample_stdev(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    variance = sum((item - mean) ** 2 for item in values) / (len(values) - 1)
    if variance <= 0:
        return None
    return variance**0.5


def _closes_by_canonical(
    histories: dict[str, tuple[Candle, ...]],
) -> dict[str, dict[datetime, float]]:
    out: dict[str, dict[datetime, float]] = {name: {} for name in UNIVERSE}
    for candles in histories.values():
        if not candles:
            continue
        canonical = ALIAS_TO_CANONICAL.get(candles[0].symbol.upper())
        if canonical is None:
            continue
        for candle in candles:
            if candle.close > 0:
                out[canonical][candle.opened_at] = candle.close
    return out


def aligned_triple_days(
    closes: dict[str, dict[datetime, float]],
) -> tuple[datetime, ...]:
    """Intersection of BTC, ETH, and SOL timestamps. Skip if any missing."""
    if any(not closes.get(name) for name in UNIVERSE):
        return ()
    common = set(closes[UNIVERSE[0]])
    for name in UNIVERSE[1:]:
        common &= set(closes[name])
    return tuple(sorted(common))


def xs_momentum_signals(
    histories: dict[str, tuple[Candle, ...]],
    *,
    lookback: int,
    long_short: bool,
    vol_scaled: bool,
) -> dict[str, tuple[tuple[datetime, float], ...]]:
    """Point-in-time top-1 / bottom-1 assignments. Skip-not-invent."""
    closes = _closes_by_canonical(histories)
    days = aligned_triple_days(closes)
    if len(days) < lookback + 1:
        return {}
    per_asset: dict[str, list[tuple[datetime, float]]] = {name: [] for name in UNIVERSE}
    for index in range(lookback, len(days)):
        ts = days[index]
        window = days[index - lookback : index + 1]
        scores: list[tuple[float, str]] = []
        for asset in UNIVERSE:
            prices = [closes[asset][day] for day in window]
            if min(prices) <= 0:
                continue
            trailing = prices[-1] / prices[0] - 1.0
            if vol_scaled:
                returns = [later / previous - 1.0 for previous, later in pairwise(prices)]
                vol = _sample_stdev(returns)
                if vol is None:
                    continue
                trailing = trailing / vol
            scores.append((trailing, asset))
        if len(scores) < 3:
            continue
        ranked = sorted(scores, key=lambda item: (-item[0], item[1]))
        top = ranked[0][1]
        bottom = ranked[-1][1]
        if top == bottom:
            continue
        for asset in UNIVERSE:
            signal = 0.0
            if asset == top:
                signal = 1.0
            elif long_short and asset == bottom:
                signal = -1.0
            per_asset[asset].append((ts, signal))
    if not any(per_asset.values()):
        return {}
    mapping: dict[str, tuple[tuple[datetime, float], ...]] = {}
    for alias, canonical in ALIAS_TO_CANONICAL.items():
        mapping[alias] = tuple(per_asset[canonical])
    return mapping


@dataclass(frozen=True)
class CrossSectionalMomentumVoter:
    """Look up a precomputed same-bar cross-sectional assignment."""

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
                rationale="xs_momentum: no same-bar assignment (skipped day)",
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
            rationale=f"xs_momentum assignment={value:+.0f}",
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


def _book_label(*, long_short: bool, vol_scaled: bool, lookback: int) -> str:
    book = "dollar-neutral long top-1 / short bottom-1" if long_short else "long-only top-1"
    scale = "vol-scaled trailing return" if vol_scaled else "trailing return"
    return f"{book} by {lookback}d {scale} among BTC/ETH/SOL"


def xs_momentum_candidates(
    histories: dict[str, tuple[Candle, ...]] | None = None,
    *,
    include_control: bool = True,
) -> tuple[SearchCandidate, ...]:
    """Instantiate the frozen catalog. Missing triple → XS names omitted."""
    out: list[SearchCandidate] = []
    source = histories or {}
    for candidate_id, lookback, long_short, vol_scaled in XS_CATALOG:
        mapping = xs_momentum_signals(
            source,
            lookback=lookback,
            long_short=long_short,
            vol_scaled=vol_scaled,
        )
        if not mapping:
            continue
        by_symbol = tuple((key.upper(), values) for key, values in sorted(mapping.items()))
        out.append(
            SearchCandidate(
                candidate_id=candidate_id,
                family="xs_momentum",
                label=_book_label(long_short=long_short, vol_scaled=vol_scaled, lookback=lookback),
                params={
                    "lookback": lookback,
                    "long_short": long_short,
                    "vol_scaled": vol_scaled,
                    "universe": list(UNIVERSE),
                    "strategy_id": candidate_id,
                    "multi_asset_gate": MULTI_ASSET_GATE_RULE,
                },
                strategy=CrossSectionalMomentumVoter(
                    strategy_id=candidate_id,
                    signals_by_symbol=by_symbol,
                ),
            )
        )
    if include_control:
        out.append(_control_candidate())
    return tuple(out)


def skipped_xs_families(
    histories: dict[str, tuple[Candle, ...]],
) -> list[dict[str, str]]:
    skipped: list[dict[str, str]] = []
    for candidate_id, lookback, long_short, vol_scaled in XS_CATALOG:
        mapping = xs_momentum_signals(
            histories,
            lookback=lookback,
            long_short=long_short,
            vol_scaled=vol_scaled,
        )
        if mapping:
            continue
        skipped.append(
            {
                "family": "xs_momentum",
                "candidate_id": candidate_id,
                "reason": (
                    f"{_book_label(long_short=long_short, vol_scaled=vol_scaled, lookback=lookback)}"
                    ": skipped — need aligned BTC+ETH+SOL daily closes "
                    f"with at least {lookback + 1} triple days. Skip rather "
                    "than invent a two-asset cross-section."
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


def rank_xs_momentum_passers(rows: list[DualPrintRow]) -> list[DualPrintRow]:
    """Frozen ranking key among XS dual-print passers. Control excluded."""
    eligible = [row for row in rows if row.candidate_id not in CONTROL_IDS]
    return rank_dual_print_passers(eligible)


class CrossSectionalMomentumReport(BaseModel):
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
    aligned_triple_days: int = 0
    aligned_first: str | None = None
    aligned_last: str | None = None
    binance_aligned_triple_days: int = 0
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
    skipped_feature_families: list[dict[str, str]] = Field(default_factory=list)
    selected_candidate_id: str | None = None
    recommended_promote_flag: str | None = None
    any_dual_print_passer: bool = False
    honesty: str
    recommendation: str
    rules: str = CROSS_SECTIONAL_RULES
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
    aligned_days: int,
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
        (
            f"- Aligned BTC+ETH+SOL triple-days (Kraken): {aligned_days}. "
            "Missing-asset days were skipped."
        ),
        (f"- Multi-asset gate: `{MULTI_ASSET_GATE_RULE}` (SOL reported, not required)."),
        (
            f"- Paper path: ready on Kraken spot BTC/ETH/SOL "
            f"(PAPER_PATH_READY={str(PAPER_PATH_READY).lower()})."
        ),
    ]
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
        "or #108 EMA dual-prints. Do not re-run the #116 residual "
        "catalog on the same windows. Do not invent PIT basis for carry."
    )
    return "\n".join(lines)


def run_cross_sectional_momentum_search(
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
) -> CrossSectionalMomentumReport:
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
    aligned = aligned_triple_days(_closes_by_canonical(kraken))
    aligned_points = len(aligned)
    aligned_first = aligned[0].isoformat() if aligned else None
    aligned_last = aligned[-1].isoformat() if aligned else None

    catalog = candidates if candidates is not None else xs_momentum_candidates(kraken)
    skipped = skipped_xs_families(kraken)

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
    binance_aligned = aligned_triple_days(_closes_by_canonical(remapped))

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
            binance_catalog = xs_momentum_candidates(remapped)
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
    passers = rank_xs_momentum_passers(rows)
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
    recommended = paper_promote_flag_name(selected.candidate_id) if selected is not None else None
    honesty = (
        CROSS_SECTIONAL_RULES
        + " "
        + CROSS_SECTIONAL_CATALOG_NOTE
        + f" This run scored K={len(catalog)} (core ids frozen at "
        f"{len(CORE_IDS)}). Aligned triple-days: {aligned_points}. "
        f"Kraken combined-passers (ex-control): {len(kraken_ids)}. "
        f"Binance combined-passers (ex-control): {len(binance_ids)}. "
        f"Dual-print passers: {len(dual_ids)}."
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
    if aligned:
        notes.append(
            f"BTC+ETH+SOL aligned triple-days: {aligned_points} "
            f"{aligned_first} → {aligned_last} (skipped days omitted)."
        )
    else:
        notes.append(
            "BTC+ETH+SOL aligned triple unavailable (need all three "
            "closes). XS names skipped, not invented as a two-asset book."
        )
    if binance_meta.available:
        notes.append(
            f"Binance.US aligned triple-days: {len(binance_aligned)} (same skip-not-invent rule)."
        )

    return CrossSectionalMomentumReport(
        # --- era prints / DSR / PBO (#135) ---
        selection_evidence=kraken_report.selection_evidence,
        generated_at=generated,
        ranking_key=RANKING_KEY,
        selection_rule=SELECTION_RULE,
        multi_asset_gate_rule=MULTI_ASSET_GATE_RULE,
        catalog_k_core=len(CORE_IDS),
        catalog_k_scored=len(catalog),
        catalog_ids=[item.candidate_id for item in catalog],
        catalog_note=CROSS_SECTIONAL_CATALOG_NOTE,
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
        aligned_triple_days=aligned_points,
        aligned_first=aligned_first,
        aligned_last=aligned_last,
        binance_aligned_triple_days=len(binance_aligned),
        paper_path_ready=PAPER_PATH_READY,
        multi_venue_bar_preregistered=MULTI_VENUE_BAR_PREREGISTERED,
        can_average_venues=CAN_AVERAGE_VENUES,
        can_enter_promotion_average=CAN_ENTER_PROMOTION_AVERAGE,
        keep_flag_false=True,
        rows=rows,
        dual_print_passer_ids=dual_ids,
        kraken_combined_passer_ids=kraken_ids,
        binance_combined_passer_ids=binance_ids,
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
            aligned_days=aligned_points,
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


def render_cross_sectional_momentum_markdown(
    report: CrossSectionalMomentumReport,
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
        "# Cross-sectional momentum dual-print (BTC+ETH+SOL)",
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
            f"Aligned triple-days: {report.aligned_triple_days} "
            f"({report.aligned_first or 'n/a'} → {report.aligned_last or 'n/a'})."
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
            "bar; SOL required to instantiate the catalog; must "
            "combined-PASS | **no** (gate only; not averaged) |"
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
            "printed in the tables and **do not** gate. Equal-weight "
            "three-asset portfolio metrics were considered and "
            "**rejected** before scoring — that would be a different "
            "bar and is not used here."
        ),
        "",
        "## Treatment (frozen)",
        "",
        (
            "On each aligned BTC+ETH+SOL day t, compute trailing N-day "
            "close-to-close return (and, for `vol` names, divide by the "
            "sample stdev of the N daily returns). Long the top-1 name; "
            "`ls` also shorts the bottom-1 (dollar-neutral book: one long "
            "leg and one short leg; the middle name is flat). `lo` is "
            "long-only top-1. Decision uses closes through bar t; the "
            "shared backtest fills at bar t+1 open. A day missing any of "
            "the three closes is skipped. A signal is applied only when "
            "the candle `opened_at` matches an assignment (no stale hold)."
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
                "SOL on Binance skips XS names on that venue (not a "
                "two-asset fallback)."
            ),
            "",
            "## Dual-print passers (promotion ranking)",
            "",
            (
                f"Frozen ranking key: `{report.ranking_key}`. Only XS names "
                "that already clear combined on **both** prints appear here. "
                f"`{CONTROL_ID}` is excluded. Empty table = no promotee "
                "(success). A new Settings pin is added only if this table "
                "is non-empty, and then default **false**."
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
                "These XS names cleared #96+A+B+C on the Kraken primary "
                "window (BTC+ETH gates). They are **not** promotees unless "
                "they also appear in the dual-print table. Control omitted. "
                "SOL holdout is reported."
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
                "These XS names cleared #96+A+B+C on the Binance.US "
                "older-720. They cannot promote unless they also cleared "
                "Kraken. Control omitted. SOL holdout is reported."
            ),
            "",
        ]
    )
    lines.extend(_passer_table(binance_rows, venue="binance"))
    lines.extend(
        [
            "",
            "## Full catalog (informational)",
            "",
            (
                "| id | family | Kraken combined | Binance combined | dual-print | "
                "Kraken mean HO | Binance mean HO | Kraken SOL HO |"
            ),
            "| --- | --- | :---: | :---: | :---: | ---: | ---: | ---: |",
        ]
    )
    family_by_id = {
        item: ("control" if item in CONTROL_IDS else "xs_momentum") for item in CORE_IDS
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
            f"{_pct(row.kraken_sol_holdout)} |"
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
                "dead EMA dual-prints (#104 / #108) or the #116 residual "
                "catalog on the same windows. Do not invent carry basis."
            ),
            "",
        ]
    )
    return "\n".join(lines)
