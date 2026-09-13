"""Dual-print daily search: Kraken harder gates + Binance.US older 720.

Pre-registered before any live pull (do not retune after seeing PnL).

A name is a **dual-print passer** only if it clears combined harder
gates (#96 + A + B + C) on **both**:

1. The Kraken public Spot daily primary window (720-bar cap).
2. The #102 Binance.US Spot daily print: 720 committed bars ending
   strictly before the primary Kraken first bar. Labeled Binance.US,
   not Binance.com. Quote is USDT. Report-only venue identity.

Ranking key (frozen): ``mean_holdout_excess_among_dual_print_passers``
— Kraken BTC+ETH mean holdout excess among names that already cleared
both prints. Tie-break: ``candidate_id``. Binance holdout is a gate,
never averaged into the ranking key. A Kraken-only combined-passer
(including the #99 top-1 ``ema_9_21_adx15``) cannot promote.

``MULTI_VENUE_BAR_PREREGISTERED = True`` — unlike #102, this search
does require Binance combined-pass. Venues are still not averaged.

Empty dual-print set is success. This module never flips
``PAPER_PROMOTE_*`` and does not add a Settings pin unless a committed
report names a dual-print passer (default false if added). No live.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field

from traderstack.candles import Candle
from traderstack.research.binance_spot import BINANCE_TAKER_BPS_NOTE
from traderstack.research.daily_candidates import (
    DUAL_PRINT_SEARCH_CORE_IDS,
    DUAL_PRINT_SEARCH_GRID_NOTE,
    DUAL_PRINT_SEARCH_OVERLAY_IDS,
    default_dual_print_search_candidates,
)
from traderstack.research.daily_robustness import KRAKEN_DAILY_CAP_NOTE, is_yahoo_symbol
from traderstack.research.evidence import (  # --- search evidence (#135) ---
    EVIDENCE_RULES,
    PRINT_KIND_VENUE,
    CandidateEvidence,
    CatalogEvidence,
    EraCoverage,
    era_coverage,
    render_era_coverage_lines,
    render_evidence_lines,
)
from traderstack.research.harder_gates import (
    HARDER_GATES_NOTE,
    CandidateHarderResult,
    HarderGatesReport,
    _pct,
    _ratio,
    _verdict,
    kraken_daily_candles,
    paper_promote_flag_name,
    run_harder_gates,
)
from traderstack.research.harder_gates import (
    RANKING_KEY as KRAKEN_COMBINED_RANKING_KEY,
)
from traderstack.research.miles_candidates import SearchCandidate
from traderstack.research.second_print import (
    BINANCE_SLICE_RULE,
    BINANCE_TO_SCORE_SYMBOL,
    SECOND_PRINT_BARS,
    SliceMeta,
    _overlaps_primary,
    _span,
    primary_first_opened_at,
    remap_binance_for_scoring,
    slice_ending_before,
)

RANKING_KEY = "mean_holdout_excess_among_dual_print_passers"
SELECTION_RULE = "pre_registered_top1_mean_holdout_excess_among_dual_print_passers"
MULTI_VENUE_BAR_PREREGISTERED = True
CAN_AVERAGE_VENUES = False
CAN_ENTER_PROMOTION_AVERAGE = False

DUAL_PRINT_RULES = (
    "Pre-registered dual-print bar (frozen before any Kraken or "
    "Binance.US score). Combined on each print is #96 balanced-holdout "
    "and A magnitude and B multi-window and C 2× fees. A dual-print "
    "passer must combined-PASS the Kraken primary 720-bar daily window "
    "AND the #102 Binance.US older-720 "
    f"(`{BINANCE_SLICE_RULE}`: {SECOND_PRINT_BARS} committed daily bars "
    "ending strictly before the primary Kraken first bar). "
    f"Ranking key: {RANKING_KEY} — Kraken BTC+ETH mean holdout excess "
    "among dual-print passers (tie-break: candidate_id). Binance "
    "holdout is a gate only; "
    f"CAN_AVERAGE_VENUES={str(CAN_AVERAGE_VENUES).lower()}. "
    f"MULTI_VENUE_BAR_PREREGISTERED="
    f"{str(MULTI_VENUE_BAR_PREREGISTERED).lower()}. "
    "A Kraken-only combined-passer is not a dual-print passer and "
    "cannot promote. Missing, short, or overlapping Binance fails "
    "closed (zero dual-print passers). Fees are paper-research 10+5 "
    "(gate C 20+10). PAPER_PROMOTE_* stays default false. No live. "
    "An empty dual-print set is success."
)


def dual_print_candidates(
    *,
    btc_overlay: tuple[Candle, ...] | None = None,
    candidates: tuple[SearchCandidate, ...] | None = None,
) -> tuple[SearchCandidate, ...]:
    if candidates is not None:
        return candidates
    return default_dual_print_search_candidates(btc_overlay=btc_overlay)


class DualPrintRow(BaseModel):
    candidate_id: str
    family: str
    label: str
    kraken_combined: bool = False
    binance_combined: bool = False
    dual_print: bool = False
    dual_print_rank: int | None = None
    kraken_combined_rank: int | None = None
    kraken_wf_rank: int | None = None
    kraken_mean_holdout_excess: float | None = None
    binance_mean_holdout_excess: float | None = None
    kraken_btc_holdout: float | None = None
    kraken_eth_holdout: float | None = None
    # --- cross-sectional momentum (SOL reported; not a gate) ---
    kraken_sol_holdout: float | None = None
    binance_sol_holdout: float | None = None
    kraken_holdout_ratio: float | None = None
    kraken_btc_wf: float | None = None
    kraken_eth_wf: float | None = None
    binance_btc_holdout: float | None = None
    binance_eth_holdout: float | None = None
    binance_holdout_ratio: float | None = None
    kraken_eligible_96: bool = False
    kraken_gate_a: bool = False
    kraken_gate_b: bool = False
    kraken_gate_c: bool = False
    binance_eligible_96: bool = False
    binance_gate_a: bool = False
    binance_gate_b: bool = False
    binance_gate_c: bool = False
    selected: bool = False
    can_promote: bool = False
    # --- search evidence (#135) ---
    # Per-print DSR / PBO / bootstrap evidence. evidence_pass requires
    # dual_print AND both prints' evidence; evidence_selected marks the
    # first ranked dual-print passer whose evidence also passes. Neither
    # changes dual_print, dual_print_rank or selected (raw pass stays shown).
    kraken_evidence: CandidateEvidence | None = None
    binance_evidence: CandidateEvidence | None = None
    kraken_evidence_pass: bool = False
    binance_evidence_pass: bool = False
    evidence_pass: bool = False
    evidence_selected: bool = False


class DualPrintReport(BaseModel):
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
    multi_venue_bar_preregistered: bool = True
    can_average_venues: bool = False
    can_enter_promotion_average: bool = False
    keep_flag_false: bool = True
    rows: list[DualPrintRow] = Field(default_factory=list)
    dual_print_passer_ids: list[str] = Field(default_factory=list)
    kraken_combined_passer_ids: list[str] = Field(default_factory=list)
    binance_combined_passer_ids: list[str] = Field(default_factory=list)
    selected_candidate_id: str | None = None
    recommended_promote_flag: str | None = None
    any_dual_print_passer: bool = False
    honesty: str
    recommendation: str
    rules: str = DUAL_PRINT_RULES
    gates_note: str = HARDER_GATES_NOTE
    fee_note: str = BINANCE_TAKER_BPS_NOTE
    kraken_cap_note: str = KRAKEN_DAILY_CAP_NOTE
    data_notes: list[str] = Field(default_factory=list)
    # --- search evidence (#135) ---
    print_kind: str = PRINT_KIND_VENUE
    kraken_evidence: CatalogEvidence | None = None
    binance_evidence: CatalogEvidence | None = None
    evidence_passer_ids: list[str] = Field(default_factory=list)
    evidence_selected_candidate_id: str | None = None
    era_coverage: list[EraCoverage] = Field(default_factory=list)
    evidence_rules: str = EVIDENCE_RULES


def rank_dual_print_passers(rows: list[DualPrintRow]) -> list[DualPrintRow]:
    """Frozen ranking key: Kraken mean HO among dual-print passers."""
    passers = [row for row in rows if row.dual_print]
    passers.sort(
        key=lambda row: (
            -(
                row.kraken_mean_holdout_excess
                if row.kraken_mean_holdout_excess is not None
                else float("-inf")
            ),
            row.candidate_id,
        )
    )
    for index, row in enumerate(passers, start=1):
        row.dual_print_rank = index
        row.selected = index == 1
        row.can_promote = False
    # --- search evidence (#135) ---
    # Evidence never reorders: the first ranked passer whose evidence also
    # passes is evidence_selected. A non-dual-print row can never be.
    for row in rows:
        row.evidence_selected = False
    for row in passers:
        if row.dual_print and row.evidence_pass:
            row.evidence_selected = True
            break
    return passers


# --- search evidence (#135) ---
def evidence_selected_row(rows: list[DualPrintRow]) -> DualPrintRow | None:
    """The evidence-selected dual-print passer, if any (never a non-passer)."""
    return next((row for row in rows if row.evidence_selected and row.dual_print), None)


def evidence_passer_ids_of(passers: list[DualPrintRow]) -> list[str]:
    """Dual-print passers whose evidence also passes, in ranking order."""
    return [row.candidate_id for row in passers if row.dual_print and row.evidence_pass]


def print_era_coverage(
    kraken: dict[str, tuple[Candle, ...]],
    remapped: dict[str, tuple[Candle, ...]],
    *,
    binance_source: str | None,
) -> list[EraCoverage]:
    """Era coverage for the Kraken primary and the remapped Binance slice."""
    return era_coverage(kraken, venue="kraken") + era_coverage(
        remapped, venue=binance_source or "binance_spot"
    )


def evidence_summary(*, evidence_ids: list[str], evidence_selected_id: str | None) -> str:
    """Honesty sentence shared by the dual-print families."""
    text = (
        f" Evidence passers: {len(evidence_ids)} (DSR>=0.95, PBO<=0.50, "
        "expectancy CI>0 on both prints; additional gates, never replacements)."
    )
    if evidence_selected_id is None:
        text += (
            " No dual-print passer also clears the evidence layer; the "
            "recommended promote flag is withheld (None)."
        )
    else:
        text += f" Evidence-selected: `{evidence_selected_id}` (first ranked passer with evidence)."
    return text


def print_policy_lines(
    *,
    print_kind: str,
    era_rows: list[EraCoverage],
    evidence_ids: list[str],
    evidence_selected_id: str | None,
) -> list[str]:
    """Print-policy line + era-coverage table."""
    lines = [
        (
            f"Print policy: print_kind=`{print_kind}` (venue prints: Kraken primary + "
            "Binance.US older-720; era prints are #136). Evidence passers: "
            f"{len(evidence_ids)}; evidence-selected: "
            f"{('`' + evidence_selected_id + '`') if evidence_selected_id else 'none'}."
        ),
        "",
        "## Print policy / era coverage",
        "",
        (
            "Frozen era windows (#136 boundaries). An era is scoreable only with "
            "at least 720 bars on every series of that venue; a missing era is a "
            "skip, never a zero."
        ),
        "",
    ]
    lines.extend(render_era_coverage_lines(era_rows))
    lines.append("")
    return lines


def _kraken_only(histories: dict[str, tuple[Candle, ...]]) -> dict[str, tuple[Candle, ...]]:
    return {
        key: candles
        for key, candles in histories.items()
        if candles
        and not is_yahoo_symbol(candles[0].symbol)
        and candles[0].symbol.upper() not in BINANCE_TO_SCORE_SYMBOL
    }


def _score(
    histories: dict[str, tuple[Candle, ...]],
    *,
    fee_bps: float,
    slippage_bps: float,
    starting_equity: float,
    train_size: int,
    test_size: int,
    step_size: int,
    holdout_fraction: float,
    min_trades: int,
    candidates: tuple[SearchCandidate, ...],
    now: datetime,
) -> HarderGatesReport:
    return run_harder_gates(
        histories,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
        starting_equity=starting_equity,
        train_size=train_size,
        test_size=test_size,
        step_size=step_size,
        holdout_fraction=holdout_fraction,
        min_trades=min_trades,
        candidates=candidates,
        catalog_name="custom",
        now=now,
    )


def _binance_slice_meta(
    *,
    raw_binance: dict[str, tuple[Candle, ...]],
    remapped: dict[str, tuple[Candle, ...]],
    primary_first: datetime,
    binance_source: str | None,
) -> SliceMeta:
    score_btc = remapped.get("BTC/USD@1d")
    score_eth = remapped.get("ETH/USD@1d")
    # --- cross-sectional momentum (SOL reported; not a #102 gate) ---
    score_sol = remapped.get("SOL/USD@1d")
    short = (
        score_btc is None
        or score_eth is None
        or len(score_btc) < SECOND_PRINT_BARS
        or len(score_eth) < SECOND_PRINT_BARS
    )
    first, last, _n = _span(score_btc)
    overlap = bool(score_btc and _overlaps_primary(score_btc, primary_first))
    if not raw_binance:
        reason = "Binance Spot daily missing or failed (empty print is success)"
    elif short:
        reason = (
            f"Binance slice shorter than {SECOND_PRINT_BARS} committed "
            f"bars (BTC={len(score_btc or ())}, ETH={len(score_eth or ())}); "
            "fail closed"
        )
    elif overlap:
        reason = "Binance slice overlaps the primary Kraken window; rejected"
    else:
        reason = None
    available = reason is None and not short and not overlap
    return SliceMeta(
        rule=BINANCE_SLICE_RULE,
        venue=binance_source or "binance_spot",
        available=available,
        bars_btc=len(score_btc or ()),
        bars_eth=len(score_eth or ()),
        bars_sol=len(score_sol or ()),
        first=first,
        last=last,
        overlaps_primary_window=overlap,
        overlaps_primary_holdout=False,
        fail_closed_reason=reason,
    )


def _empty_harder_row(candidate: SearchCandidate) -> CandidateHarderResult:
    return CandidateHarderResult(
        candidate_id=candidate.candidate_id,
        family=candidate.family,
        label=candidate.label,
        combined=False,
    )


def _merge_row(
    candidate: SearchCandidate,
    kraken: CandidateHarderResult | None,
    binance: CandidateHarderResult | None,
) -> DualPrintRow:
    kraken_row = kraken or _empty_harder_row(candidate)
    binance_row = binance or _empty_harder_row(candidate)
    dual = bool(kraken_row.combined and binance_row.combined)
    return DualPrintRow(
        candidate_id=candidate.candidate_id,
        family=candidate.family,
        label=candidate.label,
        kraken_combined=kraken_row.combined,
        binance_combined=binance_row.combined,
        dual_print=dual,
        kraken_combined_rank=kraken_row.combined_rank,
        kraken_wf_rank=kraken_row.wf_rank,
        kraken_mean_holdout_excess=kraken_row.mean_holdout_excess,
        binance_mean_holdout_excess=binance_row.mean_holdout_excess,
        kraken_btc_holdout=kraken_row.baseline_btc_holdout,
        kraken_eth_holdout=kraken_row.baseline_eth_holdout,
        # --- cross-sectional momentum (SOL reported; not a gate) ---
        kraken_sol_holdout=kraken_row.baseline_sol_holdout,
        binance_sol_holdout=binance_row.baseline_sol_holdout,
        kraken_holdout_ratio=kraken_row.holdout_magnitude_ratio,
        kraken_btc_wf=kraken_row.baseline_btc_wf,
        kraken_eth_wf=kraken_row.baseline_eth_wf,
        binance_btc_holdout=binance_row.baseline_btc_holdout,
        binance_eth_holdout=binance_row.baseline_eth_holdout,
        binance_holdout_ratio=binance_row.holdout_magnitude_ratio,
        kraken_eligible_96=kraken_row.eligible_96,
        kraken_gate_a=kraken_row.gate_a_pass,
        kraken_gate_b=kraken_row.gate_b_pass,
        kraken_gate_c=kraken_row.gate_c_pass,
        binance_eligible_96=binance_row.eligible_96,
        binance_gate_a=binance_row.gate_a_pass,
        binance_gate_b=binance_row.gate_b_pass,
        binance_gate_c=binance_row.gate_c_pass,
        selected=False,
        can_promote=False,
        # --- search evidence (#135) ---
        kraken_evidence=kraken_row.evidence,
        binance_evidence=binance_row.evidence,
        kraken_evidence_pass=kraken_row.evidence_pass,
        binance_evidence_pass=binance_row.evidence_pass,
        evidence_pass=bool(dual and kraken_row.evidence_pass and binance_row.evidence_pass),
        evidence_selected=False,
    )


def _recommendation(
    *,
    selected_id: str | None,
    dual_ids: list[str],
    kraken_ids: list[str],
    binance_meta: SliceMeta,
    evidence_ids: list[str] | None = None,
    evidence_selected_id: str | None = None,
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
            f"- Kraken combined-passers (informational): {len(kraken_ids)}"
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
    ]
    if selected_id is None:
        lines.append(
            "- Dual-print top-1: **none**. Do not add a new promote flag. "
            "Leave `PAPER_PROMOTE_EMA_9_21` and "
            "`PAPER_PROMOTE_EMA_9_21_ADX15` false."
        )
    else:
        flag = paper_promote_flag_name(selected_id)
        lines.append(
            f"- Dual-print top-1: `{selected_id}` by `{RANKING_KEY}`. "
            f"Documented paper-only name would be `{flag}` "
            "(default **false** if added). This run does not flip it."
        )
    # --- search evidence (#135) ---
    evidence_ids = evidence_ids or []
    lines.append(
        f"- Evidence passers: {len(evidence_ids)} (DSR>=0.95, PBO<=0.50, expectancy CI>0)"
        + (f" (`{'`, `'.join(evidence_ids)}`)" if evidence_ids else "")
        + ". Additional gates, never replacements. The recommended flag "
        "is derived from the evidence-selected passer"
        + (f": `{evidence_selected_id}`." if evidence_selected_id else "; none, so it is None.")
    )
    lines.append("- Do not enable live. Do not fabricate PnL.")
    return "\n".join(lines)


def run_dual_print_search(
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
) -> DualPrintReport:
    generated = now or datetime.now(UTC)
    kraken = _kraken_only(kraken_histories)
    if not kraken:
        raise ValueError("no Kraken daily histories provided")
    primary_first, primary_source = primary_first_opened_at(kraken)
    btc = kraken_daily_candles(kraken, "BTC/USD")
    primary_last = btc[-1].opened_at.isoformat() if btc else None
    primary_bars = len(btc) if btc else None

    catalog = dual_print_candidates(btc_overlay=btc, candidates=candidates)

    raw_binance = binance_histories or {}
    sliced_binance = {
        key: slice_ending_before(candles, before=primary_first)
        for key, candles in raw_binance.items()
    }
    remapped = remap_binance_for_scoring(sliced_binance)
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
    )
    kraken_by_id = {row.candidate_id: row for row in kraken_report.candidates}
    # --- search evidence (#135) ---
    kraken_evidence = kraken_report.evidence
    binance_evidence: CatalogEvidence | None = None

    binance_by_id: dict[str, CandidateHarderResult] = {}
    if binance_meta.available:
        binance_btc = remapped.get("BTC/USD@1d")
        binance_catalog = dual_print_candidates(btc_overlay=binance_btc, candidates=candidates)
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
        # --- search evidence (#135) ---
        binance_evidence = binance_report.evidence

    rows = [
        _merge_row(
            candidate,
            kraken_by_id.get(candidate.candidate_id),
            binance_by_id.get(candidate.candidate_id),
        )
        for candidate in catalog
    ]
    passers = rank_dual_print_passers(rows)
    selected = passers[0] if passers else None
    dual_ids = [row.candidate_id for row in passers]
    kraken_ids = [
        row.candidate_id
        for row in sorted(
            (item for item in rows if item.kraken_combined),
            key=lambda item: (
                item.kraken_combined_rank if item.kraken_combined_rank is not None else 10**9,
                item.candidate_id,
            ),
        )
    ]
    binance_ids = [row.candidate_id for row in rows if row.binance_combined]
    # --- search evidence (#135) ---
    # selected_candidate_id / dual_print_passer_ids stay raw; the recommended
    # flag is derived from the evidence-selected passer (evidence can only
    # withhold).
    evidence_selected = evidence_selected_row(passers)
    evidence_ids = evidence_passer_ids_of(passers)
    evidence_selected_id = evidence_selected.candidate_id if evidence_selected else None
    recommended = paper_promote_flag_name(evidence_selected_id) if evidence_selected_id else None
    eras = print_era_coverage(kraken, remapped, binance_source=binance_source)
    honesty = (
        DUAL_PRINT_RULES
        + " "
        + DUAL_PRINT_SEARCH_GRID_NOTE
        + f" This run scored K={len(catalog)} (core ids frozen at "
        f"{len(DUAL_PRINT_SEARCH_CORE_IDS)}; overlays "
        f"{len(DUAL_PRINT_SEARCH_OVERLAY_IDS)} when BTC is bound). "
        f"Kraken combined-passers: {len(kraken_ids)}. "
        f"Binance combined-passers: {len(binance_ids)}. "
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
    # --- search evidence (#135) ---
    honesty += evidence_summary(
        evidence_ids=evidence_ids, evidence_selected_id=evidence_selected_id
    )

    return DualPrintReport(
        generated_at=generated,
        ranking_key=RANKING_KEY,
        selection_rule=SELECTION_RULE,
        catalog_k_core=len(DUAL_PRINT_SEARCH_CORE_IDS),
        catalog_k_scored=len(catalog),
        catalog_ids=[item.candidate_id for item in catalog],
        catalog_note=DUAL_PRINT_SEARCH_GRID_NOTE,
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
        multi_venue_bar_preregistered=MULTI_VENUE_BAR_PREREGISTERED,
        can_average_venues=CAN_AVERAGE_VENUES,
        can_enter_promotion_average=CAN_ENTER_PROMOTION_AVERAGE,
        keep_flag_false=True,
        rows=rows,
        dual_print_passer_ids=dual_ids,
        kraken_combined_passer_ids=kraken_ids,
        binance_combined_passer_ids=binance_ids,
        selected_candidate_id=selected.candidate_id if selected is not None else None,
        recommended_promote_flag=recommended,
        any_dual_print_passer=bool(dual_ids),
        honesty=honesty,
        recommendation=_recommendation(
            selected_id=selected.candidate_id if selected is not None else None,
            dual_ids=dual_ids,
            kraken_ids=kraken_ids,
            binance_meta=binance_meta,
            evidence_ids=evidence_ids,
            evidence_selected_id=evidence_selected_id,
        ),
        data_notes=list(data_notes or []),
        # --- search evidence (#135) ---
        print_kind=PRINT_KIND_VENUE,
        kraken_evidence=kraken_evidence,
        binance_evidence=binance_evidence,
        evidence_passer_ids=evidence_ids,
        evidence_selected_candidate_id=evidence_selected_id,
        era_coverage=eras,
        evidence_rules=EVIDENCE_RULES,
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


def render_dual_print_markdown(report: DualPrintReport) -> str:
    dual_rows = [row for row in report.rows if row.dual_print]
    dual_rows.sort(key=lambda row: row.dual_print_rank or 10**9)
    kraken_rows = [row for row in report.rows if row.kraken_combined]
    kraken_rows.sort(key=lambda row: row.kraken_combined_rank or 10**9)
    binance_rows = [row for row in report.rows if row.binance_combined]
    binance_rows.sort(key=lambda row: row.candidate_id)
    lines: list[str] = [
        "# Dual-print daily strategy search",
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
            f"{report.primary_last or 'n/a'}; bars={report.primary_bars or 'n/a'})."
        ),
        (
            f"`multi_venue_bar_preregistered="
            f"{str(report.multi_venue_bar_preregistered).lower()}`; "
            f"`can_average_venues={str(report.can_average_venues).lower()}`; "
            f"`keep_flag_false={str(report.keep_flag_false).lower()}`."
        ),
        # --- search evidence (#135) ---
        *print_policy_lines(
            print_kind=report.print_kind,
            era_rows=report.era_coverage,
            evidence_ids=report.evidence_passer_ids,
            evidence_selected_id=report.evidence_selected_candidate_id,
        ),
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
        "## Pre-registered catalog",
        "",
        report.catalog_note,
        "",
        ("Frozen core ids: " + ", ".join(f"`{item}`" for item in DUAL_PRINT_SEARCH_CORE_IDS) + "."),
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
            # --- search evidence (#135) ---
            *render_evidence_lines(
                report.kraken_evidence,
                heading="## Evidence — Kraken primary (DSR / PBO / bootstrap; additional gates)",
            ),
            *render_evidence_lines(
                report.binance_evidence,
                heading=(
                    "## Evidence — Binance.US older-720 (DSR / PBO / bootstrap; additional gates)"
                ),
            ),
            "## Dual-print passers (promotion ranking)",
            "",
            (
                f"Frozen ranking key: `{report.ranking_key}`. Only names that "
                "already clear combined on **both** prints appear here. "
                "Empty table = no promotee (success). A new Settings pin is "
                "added only if this table is non-empty, and then default "
                "**false**. `evidence` is the #135 additional gate (both prints); "
                "the recommended flag follows the evidence-selected row only."
            ),
            "",
            (
                "| dual rank | id | Kraken mean HO | Binance mean HO | "
                "Kraken BTC HO | Kraken ETH HO | selected | evidence | can flip flag |"
            ),
            "| ---: | --- | ---: | ---: | ---: | ---: | :---: | :---: | :---: |",
        ]
    )
    if not dual_rows:
        lines.append("| — | — | n/a | n/a | n/a | n/a | no | no | no |")
    else:
        for row in dual_rows:
            lines.append(
                f"| {row.dual_print_rank} | `{row.candidate_id}` | "
                f"{_pct(row.kraken_mean_holdout_excess)} | "
                f"{_pct(row.binance_mean_holdout_excess)} | "
                f"{_pct(row.kraken_btc_holdout)} | {_pct(row.kraken_eth_holdout)} | "
                f"{'yes' if row.selected else 'no'} | "
                f"{_verdict(row.evidence_pass)}"
                f"{' (selected)' if row.evidence_selected else ''} | no |"
            )
    lines.extend(
        [
            "",
            "## Kraken combined-passers (informational)",
            "",
            (
                "These names cleared #96+A+B+C on the Kraken primary window. "
                "They are **not** promotees unless they also appear in the "
                "dual-print table."
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
                "These names cleared #96+A+B+C on the Binance.US older-720. "
                "They cannot promote unless they also cleared Kraken."
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
                "| id | Kraken combined | Binance combined | dual-print | "
                "Kraken mean HO | Binance mean HO |"
            ),
            "| --- | :---: | :---: | :---: | ---: | ---: |",
        ]
    )
    ordered = sorted(
        report.rows,
        key=lambda row: (
            row.kraken_wf_rank if row.kraken_wf_rank is not None else 10**9,
            row.candidate_id,
        ),
    )
    for row in ordered:
        lines.append(
            f"| `{row.candidate_id}` | {_verdict(row.kraken_combined)} | "
            f"{_verdict(row.binance_combined)} | "
            f"{'yes' if row.dual_print else 'no'} | "
            f"{_pct(row.kraken_mean_holdout_excess)} | "
            f"{_pct(row.binance_mean_holdout_excess)} |"
        )
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
                "Binance.US with the Kraken primary window."
            ),
            "",
        ]
    )
    return "\n".join(lines)
