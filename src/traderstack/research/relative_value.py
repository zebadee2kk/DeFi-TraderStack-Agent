"""BTC−ETH relative-value residual: fade/follow |z| dual-print search.

Pre-registered before any live pull (do not retune after seeing PnL).

Treatment (frozen): daily close-to-close excess ``r_BTC − r_ETH``,
z-scored over a 20-bar lookback, fade or follow at |z| ≥ 1.0 / 1.5 /
2.0. ETH sees the negated residual so the pair is internally consistent:
a high BTC-minus-ETH z fades BTC and buys ETH.

A name is a **dual-print passer** only if it clears combined harder
gates (#96 + A + B + C) on **both**:

1. The Kraken public Spot daily primary window (720-bar cap).
2. The #102 Binance.US Spot daily print: 720 committed bars ending
   strictly before the primary Kraken first bar.

Ranking key (frozen): ``mean_holdout_excess_among_dual_print_passers``
— Kraken BTC+ETH mean holdout excess among names that already cleared
both prints. Tie-break: ``candidate_id``. Binance holdout is a gate,
never averaged. A Kraken-only combined-passer cannot promote.

The informational control ``ma_cross_10_30`` is scored on the same
windows and **cannot** enter the passer set.

Paper-executable on Kraken spot (BTC/USD + ETH/USD long/short via
``paper_simulate_fills``). This is not a carry / perp family. Empty
dual-print set is success. This module never flips ``PAPER_PROMOTE_*``
and does not add a Settings pin unless a committed report names a
dual-print passer (default false if added). No live. Skip-not-invent:
a missing pair day is omitted, never zero-filled.
"""

from __future__ import annotations

from datetime import UTC, datetime
from itertools import pairwise

from pydantic import BaseModel, Field

from traderstack.candles import Candle
from traderstack.fee_tiers import FeeTierStamp
from traderstack.research.binance_spot import BINANCE_TAKER_BPS_NOTE
from traderstack.research.candidates import AlwaysOnTrendStrategy, FeatureZVoter
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

RELATIVE_VALUE_LOOKBACK = 20
RELATIVE_VALUE_Z_THRESHOLDS: tuple[float, ...] = (1.0, 1.5, 2.0)
RV_CATALOG: tuple[tuple[str, bool, float], ...] = (
    ("rv_fade_1_0", True, 1.0),
    ("rv_fade_1_5", True, 1.5),
    ("rv_fade_2_0", True, 2.0),
    ("rv_follow_1_0", False, 1.0),
    ("rv_follow_1_5", False, 1.5),
    ("rv_follow_2_0", False, 2.0),
)
RV_IDS: tuple[str, ...] = tuple(item[0] for item in RV_CATALOG)
CONTROL_ID = "ma_cross_10_30"
CONTROL_IDS: frozenset[str] = frozenset({CONTROL_ID})
CORE_IDS: tuple[str, ...] = RV_IDS + (CONTROL_ID,)
BTC_RESIDUAL_SYMBOLS: tuple[str, ...] = ("BTC/USD", "BTCUSDT", "BTC-USD", "XBT/USD")
ETH_RESIDUAL_SYMBOLS: tuple[str, ...] = ("ETH/USD", "ETHUSDT", "ETH-USD")
SCORE_SYMBOLS: frozenset[str] = frozenset({"BTC/USD", "ETH/USD"})
PAPER_PATH_READY = True
FEATURE_NAME = "btc_eth_residual"

RELATIVE_VALUE_RULES = (
    "Pre-registered BTC−ETH relative-value residual dual-print bar "
    "(frozen before any Kraken or Binance.US score). Treatment: fade or "
    "follow daily close-to-close excess r_BTC − r_ETH at |z| ≥ 1.0 / 1.5 "
    f"/ 2.0 with lookback {RELATIVE_VALUE_LOOKBACK}. ETH is bound to the "
    "negated residual (skip-not-invent: a day missing either close is "
    "omitted, never zero-filled). Combined on each print is #96 "
    "balanced-holdout and A magnitude and B multi-window and C 2× fees. "
    "A dual-print passer must combined-PASS the Kraken primary 720-bar "
    "daily window AND the #102 Binance.US older-720 "
    f"(`{BINANCE_SLICE_RULE}`: {SECOND_PRINT_BARS} committed daily bars "
    "ending strictly before the primary Kraken first bar). "
    f"Ranking key: {RANKING_KEY} — Kraken BTC+ETH mean holdout excess "
    "among dual-print passers (tie-break: candidate_id). Binance "
    "holdout is a gate only; "
    f"CAN_AVERAGE_VENUES={str(CAN_AVERAGE_VENUES).lower()}. "
    f"MULTI_VENUE_BAR_PREREGISTERED="
    f"{str(MULTI_VENUE_BAR_PREREGISTERED).lower()}. "
    "A Kraken-only combined-passer is not a dual-print passer and "
    "cannot promote. The informational control ma_cross_10_30 cannot "
    "enter the passer set. Missing, short, or overlapping Binance fails "
    "closed (zero dual-print passers). Fees are paper-research 10+5 "
    "(gate C 20+10). Paper-executable on Kraken spot BTC/USD+ETH/USD "
    f"(PAPER_PATH_READY={str(PAPER_PATH_READY).lower()}). "
    "PAPER_PROMOTE_* stays default false. No live. An empty dual-print "
    "set is success. Not an EMA reprint and not a carry/basis family."
)

RELATIVE_VALUE_CATALOG_NOTE = (
    "Frozen catalog (K=7): rv_fade / rv_follow at |z|>=1.0 / 1.5 / 2.0 "
    f"on the BTC−ETH residual (lookback {RELATIVE_VALUE_LOOKBACK}), plus "
    "informational control ma_cross_10_30 (cannot promote). Do not grow "
    "this list after seeing PnL. Residual is built from the venue-local "
    "BTC and ETH daily closes; a missing pair day is skipped. "
    "PAPER_PROMOTE_* stays false unless a committed dual-print report "
    "names a paper-only pin and an operator flips it."
)

PAPER_EXECUTABLE_PATH_NOTE = (
    "This family is paper-executable on Kraken spot. Signals are "
    "candle-only long/short on BTC/USD and ETH/USD; paper_simulate_fills "
    "already books Side.BUY / Side.SELL. No perp, no funding, no hedge "
    "book, no invented basis. A Settings pin is still added only if a "
    "committed dual-print passer exists, and then default false."
)


def btc_minus_eth_residual(
    btc: tuple[Candle, ...] | None,
    eth: tuple[Candle, ...] | None,
) -> tuple[tuple[datetime, float], ...]:
    """Point-in-time daily BTC minus ETH close-to-close excess return.

    Aligns on ``opened_at``. A day missing either close is skipped, not
    invented. Residual at t uses the current pair closes and the previous
    *aligned* pair day (a gap is a skip, not a zero-filled return).
    """
    if not btc or not eth:
        return ()
    btc_close = {candle.opened_at: candle.close for candle in btc}
    eth_close = {candle.opened_at: candle.close for candle in eth}
    common = sorted(set(btc_close) & set(eth_close))
    if len(common) < 2:
        return ()
    out: list[tuple[datetime, float]] = []
    for previous, current in pairwise(common):
        btc_prev = btc_close[previous]
        eth_prev = eth_close[previous]
        btc_now = btc_close[current]
        eth_now = eth_close[current]
        if min(btc_prev, eth_prev, btc_now, eth_now) <= 0:
            continue
        residual = (btc_now / btc_prev - 1.0) - (eth_now / eth_prev - 1.0)
        out.append((current, residual))
    return tuple(out)


def residual_by_symbol(
    residual: tuple[tuple[datetime, float], ...],
) -> dict[str, tuple[tuple[datetime, float], ...]]:
    """BTC sees r_BTC − r_ETH; ETH sees the negation. Never invents a z."""
    if not residual:
        return {}
    negated = tuple((ts, -value) for ts, value in residual)
    mapping: dict[str, tuple[tuple[datetime, float], ...]] = {}
    for symbol in BTC_RESIDUAL_SYMBOLS:
        mapping[symbol] = residual
    for symbol in ETH_RESIDUAL_SYMBOLS:
        mapping[symbol] = negated
    return mapping


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


def relative_value_candidates(
    *,
    residual: tuple[tuple[datetime, float], ...] | None = None,
    residual_map: dict[str, tuple[tuple[datetime, float], ...]] | None = None,
    include_control: bool = True,
) -> tuple[SearchCandidate, ...]:
    """Instantiate the frozen catalog. Empty residual → RV names omitted."""
    mapping = residual_map if residual_map is not None else residual_by_symbol(residual or ())
    out: list[SearchCandidate] = []
    if mapping:
        by_symbol = tuple((key.upper(), values) for key, values in sorted(mapping.items()))
        for candidate_id, fade, entry_z in RV_CATALOG:
            verb = "fade" if fade else "follow"
            out.append(
                SearchCandidate(
                    candidate_id=candidate_id,
                    family="relative_value",
                    label=(
                        f"{verb} BTC−ETH residual z |z|>={entry_z:g} "
                        f"(lookback {RELATIVE_VALUE_LOOKBACK})"
                    ),
                    params={
                        "lookback": RELATIVE_VALUE_LOOKBACK,
                        "entry_z": entry_z,
                        "fade": fade,
                        "strategy_id": candidate_id,
                        "feature_name": FEATURE_NAME,
                    },
                    strategy=FeatureZVoter(
                        strategy_id=candidate_id,
                        feature_name=FEATURE_NAME,
                        values=mapping.get("BTC/USD", ()),
                        values_by_symbol=by_symbol,
                        lookback=RELATIVE_VALUE_LOOKBACK,
                        entry_z=entry_z,
                        fade=fade,
                    ),
                )
            )
    if include_control:
        out.append(_control_candidate())
    return tuple(out)


def skipped_residual_families(
    residual: tuple[tuple[datetime, float], ...],
) -> list[dict[str, str]]:
    if residual:
        return []
    return [
        {
            "family": "relative_value",
            "candidate_id": candidate_id,
            "reason": (
                f"{'fade' if fade else 'follow'} BTC−ETH residual z "
                f"|z|>={entry_z:g}: skipped — no aligned BTC and ETH "
                "daily pair. Skip rather than invent a residual."
            ),
        }
        for candidate_id, fade, entry_z in RV_CATALOG
    ]


def _btc_eth_only(histories: dict[str, tuple[Candle, ...]]) -> dict[str, tuple[Candle, ...]]:
    return {
        key: candles
        for key, candles in histories.items()
        if candles and candles[0].symbol.upper() in SCORE_SYMBOLS
    }


def rank_relative_value_passers(rows: list[DualPrintRow]) -> list[DualPrintRow]:
    """Frozen ranking key among RV dual-print passers. Control excluded."""
    eligible = [row for row in rows if row.candidate_id not in CONTROL_IDS]
    return rank_dual_print_passers(eligible)


class RelativeValueReport(BaseModel):
    generated_at: datetime
    ranking_key: str
    selection_rule: str
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
    binance_slice: SliceMeta
    binance_source: str | None = None
    residual_points: int = 0
    residual_first: str | None = None
    residual_last: str | None = None
    binance_residual_points: int = 0
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
    rules: str = RELATIVE_VALUE_RULES
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
    residual_points: int,
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
            f"- Residual points (Kraken-aligned pair days after the first "
            f"return): {residual_points}. Missing pair days were skipped."
        ),
        (
            f"- Paper path: ready on Kraken spot BTC/ETH "
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
        "or #108 EMA dual-prints. Do not invent PIT basis for carry."
    )
    return "\n".join(lines)


def run_relative_value_search(
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
) -> RelativeValueReport:
    generated = now or datetime.now(UTC)
    kraken = _btc_eth_only(kraken_histories)
    if not kraken:
        raise ValueError("no Kraken BTC/ETH daily histories provided")
    primary_first, primary_source = primary_first_opened_at(kraken)
    btc = kraken_daily_candles(kraken, "BTC/USD")
    eth = kraken_daily_candles(kraken, "ETH/USD")
    primary_last = btc[-1].opened_at.isoformat() if btc else None
    primary_bars = len(btc) if btc else None
    residual = btc_minus_eth_residual(btc, eth)
    residual_points, residual_first, residual_last = (
        len(residual),
        residual[0][0].isoformat() if residual else None,
        residual[-1][0].isoformat() if residual else None,
    )

    catalog = candidates if candidates is not None else relative_value_candidates(residual=residual)
    skipped = skipped_residual_families(residual)

    raw_binance = binance_histories or {}
    sliced_binance = {
        key: slice_ending_before(candles, before=primary_first)
        for key, candles in raw_binance.items()
    }
    remapped = remap_binance_for_scoring(sliced_binance)
    remapped = _btc_eth_only(remapped)
    binance_meta = _binance_slice_meta(
        raw_binance=raw_binance,
        remapped=remapped,
        primary_first=primary_first,
        binance_source=binance_source,
    )
    binance_residual = btc_minus_eth_residual(
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
            binance_catalog = relative_value_candidates(residual=binance_residual)
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
    passers = rank_relative_value_passers(rows)
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
        RELATIVE_VALUE_RULES
        + " "
        + RELATIVE_VALUE_CATALOG_NOTE
        + f" This run scored K={len(catalog)} (core ids frozen at "
        f"{len(CORE_IDS)}). Residual pair-days: {residual_points}. "
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
    if residual:
        notes.append(
            f"BTC−ETH residual: {residual_points} aligned pair-days "
            f"{residual_first} → {residual_last} (skipped days omitted)."
        )
    else:
        notes.append(
            "BTC−ETH residual unavailable (need aligned BTC and ETH "
            "closes). RV names skipped, not invented."
        )
    if binance_meta.available:
        notes.append(
            f"Binance.US residual: {len(binance_residual)} aligned pair-days "
            "(same skip-not-invent rule)."
        )

    return RelativeValueReport(
        # --- era prints / DSR / PBO (#135) ---
        selection_evidence=kraken_report.selection_evidence,
        generated_at=generated,
        ranking_key=RANKING_KEY,
        selection_rule=SELECTION_RULE,
        catalog_k_core=len(CORE_IDS),
        catalog_k_scored=len(catalog),
        catalog_ids=[item.candidate_id for item in catalog],
        catalog_note=RELATIVE_VALUE_CATALOG_NOTE,
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
        binance_slice=binance_meta,
        binance_source=binance_source,
        residual_points=residual_points,
        residual_first=residual_first,
        residual_last=residual_last,
        binance_residual_points=len(binance_residual),
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
            residual_points=residual_points,
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


def render_relative_value_markdown(report: RelativeValueReport) -> str:
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
        "# BTC−ETH relative-value residual dual-print",
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
            f"{report.primary_last or 'n/a'}; bars={report.primary_bars or 'n/a'})."
        ),
        (
            f"Residual pair-days: {report.residual_points} "
            f"({report.residual_first or 'n/a'} → {report.residual_last or 'n/a'})."
        ),
        (
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
            f"#96+A+B+C; rank among dual-print passers by `{report.ranking_key}` "
            "| **Kraken mean HO only** |"
        ),
        (
            "| Binance.US older 720 | same #102 definition: 720 committed "
            "daily bars ending before the primary Kraken first bar; "
            "must combined-PASS | **no** (gate only; not averaged) |"
        ),
        (
            f"| Kraken-only combined ranking (`{KRAKEN_COMBINED_RANKING_KEY}`) "
            "| informational | no |"
        ),
        "",
        "## Treatment (frozen)",
        "",
        (
            "Daily BTC minus ETH close-to-close excess return, z-scored "
            f"over {RELATIVE_VALUE_LOOKBACK} aligned pair-days. Fade: sell "
            "the outperformer / buy the underperformer at |z| ≥ threshold. "
            "Follow: the opposite. Decision uses residual through bar t; "
            "the shared backtest fills at bar t+1 open. A missing pair day "
            "is skipped, not zero-filled."
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
                "A short or overlapping series fails closed. Empty Binance "
                "means zero dual-print passers (success)."
            ),
            "",
            "## Dual-print passers (promotion ranking)",
            "",
            (
                f"Frozen ranking key: `{report.ranking_key}`. Only RV names "
                "that already clear combined on **both** prints appear here. "
                f"`{CONTROL_ID}` is excluded. Empty table = no promotee "
                "(success). A new Settings pin is added only if this table "
                "is non-empty, and then default **false**."
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
                "These RV names cleared #96+A+B+C on the Kraken primary "
                "window. They are **not** promotees unless they also appear "
                "in the dual-print table. Control omitted."
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
                "These RV names cleared #96+A+B+C on the Binance.US "
                "older-720. They cannot promote unless they also cleared "
                "Kraken. Control omitted."
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
                "Kraken mean HO | Binance mean HO |"
            ),
            "| --- | --- | :---: | :---: | :---: | ---: | ---: |",
        ]
    )
    family_by_id = {
        item: ("control" if item in CONTROL_IDS else "relative_value") for item in CORE_IDS
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
            f"{_pct(row.binance_mean_holdout_excess)} |"
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
                "dead EMA dual-prints (#104 / #108). Do not invent carry "
                "basis."
            ),
            "",
        ]
    )
    return "\n".join(lines)
