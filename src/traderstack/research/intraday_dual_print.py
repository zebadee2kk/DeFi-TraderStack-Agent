"""4h/1h dual-print search: Kraken Spot harder gates + Binance.US older 720.

Pre-registered before any live pull (do not retune after seeing PnL).

A name is a **dual-print passer** only if it clears combined harder
gates (#96 + A + B + C) on **both**:

1. The Kraken public Spot primary window at the frozen interval
   (default ``4h``; ``1h`` is the alternate). 720-bar cap.
2. The #102-style Binance.US Spot print: 720 committed bars of the
   **same interval** ending strictly before the primary Kraken first
   bar. Labeled Binance.US, not Binance.com. Quote is USDT.

Ranking key (frozen): ``mean_holdout_excess_among_dual_print_passers``
— Kraken BTC+ETH mean holdout excess among names that already cleared
both prints. Tie-break: ``candidate_id``. Binance holdout is a gate,
never averaged. A Kraken-only combined-passer cannot promote.

Catalog is the non-EMA 4h/1h grid in ``intraday_candidates``. Funding/OI
variants instantiate only when an aligned series is fetched.

Empty dual-print set is success. This module never flips
``PAPER_PROMOTE_*`` and does not add a Settings pin unless a committed
report names a dual-print passer (default false if added). No live.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field

from traderstack.candles import Candle
from traderstack.research.binance_spot import BINANCE_TAKER_BPS_NOTE
from traderstack.research.daily_robustness import is_yahoo_symbol
from traderstack.research.harder_gates import (
    CandidateHarderResult,
    HarderGatesReport,
    _pct,
    _ratio,
    _verdict,
    kraken_daily_candles,
    paper_promote_flag_name,
    run_harder_gates,
)
from traderstack.research.intraday_candidates import (
    ALLOWED_INTERVALS,
    DEFAULT_INTERVAL,
    INTRADAY_DUAL_PRINT_CORE_IDS,
    INTRADAY_DUAL_PRINT_GRID_NOTE,
    OPTIONAL_FEATURE_IDS,
    default_intraday_dual_print_candidates,
    skipped_optional_families,
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

# --- era prints / DSR / PBO (#135) ---
from traderstack.research.selection_evidence import (
    SelectionEvidence,
    render_evidence_lines,
)

RANKING_KEY = "mean_holdout_excess_among_dual_print_passers"
SELECTION_RULE = "pre_registered_top1_mean_holdout_excess_among_dual_print_passers"
MULTI_VENUE_BAR_PREREGISTERED = True
CAN_AVERAGE_VENUES = False
CAN_ENTER_PROMOTION_AVERAGE = False

KRAKEN_INTRADAY_CAP_NOTE = (
    "Kraken public Spot OHLC (`GET /0/public/OHLC`) returns at most 720 of "
    "the most recent committed bars per pair/interval. `since` pages "
    "forward only. 4h ≈ 120 calendar days; 1h ≈ 30 days. Charts-spot PI_* "
    "is a different print (research-only, often zero volume) and is not "
    "used here. This is not the daily EMA promotion window."
)

HARDER_GATES_INTRADAY_NOTE = (
    "Same #96+A+B+C bar as the daily harder gates, applied to the frozen "
    "4h/1h interval (bar counts unchanged). A — magnitude: BTC and ETH "
    "holdout excess > 0 and min/max ratio >= 0.25. B — three contiguous "
    "240-bar slices of this interval; each uses train=180 / test=60 / "
    "step=60 with no in-window holdout; BTC and ETH WF total > 0 in at "
    "least 2 of 3. C — 2× fees (20+10 bps) must still clear #96 balanced "
    "signs. Combined requires #96 and A and B and C on **each** print."
)

INTRADAY_DUAL_PRINT_RULES = (
    "Pre-registered 4h/1h dual-print bar (frozen before any Kraken or "
    "Binance.US score). Combined on each print is #96 balanced-holdout "
    "and A magnitude and B multi-window and C 2× fees. A dual-print "
    "passer must combined-PASS the Kraken primary 720-bar window at the "
    f"frozen interval AND the #102-style Binance.US older-720 "
    f"(`{BINANCE_SLICE_RULE}`: {SECOND_PRINT_BARS} committed bars of the "
    "same interval ending strictly before the primary Kraken first bar). "
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
    "An empty dual-print set is success. Funding/OI variants score only "
    "when an aligned series is fetched; they are skipped, not invented."
)


def _validate_interval(interval: str) -> str:
    if interval not in ALLOWED_INTERVALS:
        raise ValueError(f"interval must be one of {ALLOWED_INTERVALS}, got {interval!r}")
    return interval


def intraday_dual_print_candidates(
    *,
    candidates: tuple[SearchCandidate, ...] | None = None,
    funding_by_symbol: dict[str, tuple[tuple[datetime, float], ...]] | None = None,
    open_interest_by_symbol: dict[str, tuple[tuple[datetime, float], ...]] | None = None,
) -> tuple[SearchCandidate, ...]:
    if candidates is not None:
        return candidates
    return default_intraday_dual_print_candidates(
        funding_by_symbol=funding_by_symbol,
        open_interest_by_symbol=open_interest_by_symbol,
    )


class IntradayDualPrintRow(BaseModel):
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


class IntradayDualPrintReport(BaseModel):
    generated_at: datetime
    interval: str
    ranking_key: str
    selection_rule: str
    catalog_k_core: int
    catalog_k_scored: int
    catalog_ids: list[str]
    catalog_note: str
    optional_feature_ids: list[str] = Field(default_factory=list)
    skipped_families: list[str] = Field(default_factory=list)
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
    # --- era prints / DSR / PBO (#135) ---
    selection_evidence: SelectionEvidence | None = None
    rows: list[IntradayDualPrintRow] = Field(default_factory=list)
    dual_print_passer_ids: list[str] = Field(default_factory=list)
    kraken_combined_passer_ids: list[str] = Field(default_factory=list)
    binance_combined_passer_ids: list[str] = Field(default_factory=list)
    selected_candidate_id: str | None = None
    recommended_promote_flag: str | None = None
    any_dual_print_passer: bool = False
    honesty: str
    recommendation: str
    rules: str = INTRADAY_DUAL_PRINT_RULES
    gates_note: str = HARDER_GATES_INTRADAY_NOTE
    fee_note: str = BINANCE_TAKER_BPS_NOTE
    kraken_cap_note: str = KRAKEN_INTRADAY_CAP_NOTE
    data_notes: list[str] = Field(default_factory=list)


def rank_dual_print_passers(rows: list[IntradayDualPrintRow]) -> list[IntradayDualPrintRow]:
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
    return passers


def _kraken_only(
    histories: dict[str, tuple[Candle, ...]], *, interval: str
) -> dict[str, tuple[Candle, ...]]:
    return {
        key: candles
        for key, candles in histories.items()
        if candles
        and candles[0].interval == interval
        and not is_yahoo_symbol(candles[0].symbol)
        and candles[0].symbol.upper() not in BINANCE_TO_SCORE_SYMBOL
    }


def _score(
    histories: dict[str, tuple[Candle, ...]],
    *,
    interval: str,
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
    # --- era prints / DSR / PBO (#135) ---
    venue_print_available: bool = False,
    venue_label: str = "scored_venue",
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
        promotion_interval=interval,
        # --- era prints / DSR / PBO (#135) ---
        venue_print_available=venue_print_available,
        venue_label=venue_label,
    )


def _binance_slice_meta(
    *,
    interval: str,
    raw_binance: dict[str, tuple[Candle, ...]],
    remapped: dict[str, tuple[Candle, ...]],
    primary_first: datetime,
    binance_source: str | None,
) -> SliceMeta:
    key = f"BTC/USD@{interval}"
    eth_key = f"ETH/USD@{interval}"
    score_btc = remapped.get(key)
    score_eth = remapped.get(eth_key)
    short = (
        score_btc is None
        or score_eth is None
        or len(score_btc) < SECOND_PRINT_BARS
        or len(score_eth) < SECOND_PRINT_BARS
    )
    first, last, _n = _span(score_btc)
    overlap = bool(score_btc and _overlaps_primary(score_btc, primary_first))
    if not raw_binance:
        reason = f"Binance Spot {interval} missing or failed (empty print is success)"
    elif short:
        reason = (
            f"Binance slice shorter than {SECOND_PRINT_BARS} committed "
            f"{interval} bars (BTC={len(score_btc or ())}, ETH={len(score_eth or ())}); "
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
) -> IntradayDualPrintRow:
    kraken_row = kraken or _empty_harder_row(candidate)
    binance_row = binance or _empty_harder_row(candidate)
    dual = bool(kraken_row.combined and binance_row.combined)
    return IntradayDualPrintRow(
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
    )


def _recommendation(
    *,
    selected_id: str | None,
    dual_ids: list[str],
    kraken_ids: list[str],
    binance_meta: SliceMeta,
    interval: str,
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
            f"- Kraken {interval} combined-passers (informational): {len(kraken_ids)}"
            + (f" (`{'`, `'.join(kraken_ids)}`)" if kraken_ids else "")
            + ". A Kraken-only passer cannot promote."
        ),
        (
            f"- Binance.US `{BINANCE_SLICE_RULE}` {interval}: "
            f"{'scored' if binance_meta.available else 'FAIL-CLOSED'} "
            f"({binance_meta.venue}; {binance_meta.bars_btc} BTC / "
            f"{binance_meta.bars_eth} ETH; "
            f"{binance_meta.first} → {binance_meta.last})."
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
    lines.append("- Do not enable live. Do not fabricate PnL.")
    return "\n".join(lines)


def run_intraday_dual_print(
    kraken_histories: dict[str, tuple[Candle, ...]],
    binance_histories: dict[str, tuple[Candle, ...]] | None = None,
    *,
    interval: str = DEFAULT_INTERVAL,
    fee_bps: float,
    slippage_bps: float = 5.0,
    starting_equity: float = 10_000.0,
    train_size: int = 180,
    test_size: int = 60,
    step_size: int = 60,
    holdout_fraction: float = 0.20,
    min_trades: int = 3,
    candidates: tuple[SearchCandidate, ...] | None = None,
    funding_by_symbol: dict[str, tuple[tuple[datetime, float], ...]] | None = None,
    open_interest_by_symbol: dict[str, tuple[tuple[datetime, float], ...]] | None = None,
    binance_source: str | None = None,
    now: datetime | None = None,
    data_notes: list[str] | None = None,
) -> IntradayDualPrintReport:
    interval = _validate_interval(interval)
    generated = now or datetime.now(UTC)
    kraken = _kraken_only(kraken_histories, interval=interval)
    if not kraken:
        raise ValueError(f"no Kraken {interval} histories provided")
    primary_first, primary_source = primary_first_opened_at(kraken, interval=interval)
    btc = kraken_daily_candles(kraken, "BTC/USD", interval=interval)
    primary_last = btc[-1].opened_at.isoformat() if btc else None
    primary_bars = len(btc) if btc else None

    catalog = intraday_dual_print_candidates(
        candidates=candidates,
        funding_by_symbol=funding_by_symbol,
        open_interest_by_symbol=open_interest_by_symbol,
    )
    optional_ids = [
        item.candidate_id for item in catalog if item.candidate_id in OPTIONAL_FEATURE_IDS
    ]
    skipped = skipped_optional_families(
        funding_present=bool(funding_by_symbol),
        open_interest_present=bool(open_interest_by_symbol),
    )

    raw_binance = binance_histories or {}
    sliced_binance = {
        key: slice_ending_before(candles, before=primary_first)
        for key, candles in raw_binance.items()
    }
    remapped = remap_binance_for_scoring(sliced_binance)
    binance_meta = _binance_slice_meta(
        interval=interval,
        raw_binance=raw_binance,
        remapped=remapped,
        primary_first=primary_first,
        binance_source=binance_source,
    )

    kraken_report = _score(
        kraken,
        interval=interval,
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
        binance_report = _score(
            remapped,
            interval=interval,
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
        binance_by_id = {row.candidate_id: row for row in binance_report.candidates}

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
    recommended = paper_promote_flag_name(selected.candidate_id) if selected is not None else None
    honesty = (
        INTRADAY_DUAL_PRINT_RULES
        + " "
        + INTRADAY_DUAL_PRINT_GRID_NOTE
        + f" Interval={interval}. This run scored K={len(catalog)} "
        f"(core ids frozen at {len(INTRADAY_DUAL_PRINT_CORE_IDS)}; "
        f"optional feature ids present: {optional_ids or 'none'}). "
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

    return IntradayDualPrintReport(
        # --- era prints / DSR / PBO (#135) ---
        selection_evidence=kraken_report.selection_evidence,
        generated_at=generated,
        interval=interval,
        ranking_key=RANKING_KEY,
        selection_rule=SELECTION_RULE,
        catalog_k_core=len(INTRADAY_DUAL_PRINT_CORE_IDS),
        catalog_k_scored=len(catalog),
        catalog_ids=[item.candidate_id for item in catalog],
        catalog_note=INTRADAY_DUAL_PRINT_GRID_NOTE,
        optional_feature_ids=optional_ids,
        skipped_families=skipped,
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
            interval=interval,
        ),
        data_notes=list(data_notes or []),
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


def _passer_table(rows: list[IntradayDualPrintRow], *, venue: str) -> list[str]:
    if venue == "kraken":
        header = "| rank | id | family | mean HO | BTC HO | ETH HO | ratio | #96 | A | B | C | dual-print |"
        sep = "| ---: | --- | --- | ---: | ---: | ---: | ---: | :---: | :---: | :---: | :---: | :---: |"
    else:
        header = (
            "| id | family | mean HO | BTC HO | ETH HO | ratio | #96 | A | B | C | dual-print |"
        )
        sep = "| --- | --- | ---: | ---: | ---: | ---: | :---: | :---: | :---: | :---: | :---: |"
    lines = [header, sep]
    if not rows:
        if venue == "kraken":
            lines.append("| — | — | — | n/a | n/a | n/a | n/a | — | — | — | — | no |")
        else:
            lines.append("| — | — | n/a | n/a | n/a | n/a | — | — | — | — | no |")
        return lines
    for row in rows:
        if venue == "kraken":
            lines.append(
                f"| {row.kraken_combined_rank or '—'} | `{row.candidate_id}` | "
                f"{row.family} | {_pct(row.kraken_mean_holdout_excess)} | "
                f"{_pct(row.kraken_btc_holdout)} | {_pct(row.kraken_eth_holdout)} | "
                f"{_ratio(row.kraken_holdout_ratio)} | "
                f"{_verdict(row.kraken_eligible_96)} | {_verdict(row.kraken_gate_a)} | "
                f"{_verdict(row.kraken_gate_b)} | {_verdict(row.kraken_gate_c)} | "
                f"{'yes' if row.dual_print else 'no'} |"
            )
        else:
            lines.append(
                f"| `{row.candidate_id}` | {row.family} | "
                f"{_pct(row.binance_mean_holdout_excess)} | "
                f"{_pct(row.binance_btc_holdout)} | {_pct(row.binance_eth_holdout)} | "
                f"{_ratio(row.binance_holdout_ratio)} | "
                f"{_verdict(row.binance_eligible_96)} | {_verdict(row.binance_gate_a)} | "
                f"{_verdict(row.binance_gate_b)} | {_verdict(row.binance_gate_c)} | "
                f"{'yes' if row.dual_print else 'no'} |"
            )
    return lines


def render_intraday_dual_print_markdown(report: IntradayDualPrintReport) -> str:
    dual_rows = [row for row in report.rows if row.dual_print]
    dual_rows.sort(key=lambda row: row.dual_print_rank or 10**9)
    kraken_rows = [row for row in report.rows if row.kraken_combined]
    kraken_rows.sort(key=lambda row: row.kraken_combined_rank or 10**9)
    binance_rows = [row for row in report.rows if row.binance_combined]
    binance_rows.sort(key=lambda row: row.candidate_id)
    lines: list[str] = [
        f"# Intraday ({report.interval}) dual-print strategy search",
        "",
        f"Generated: {report.generated_at.isoformat()}",
        (
            f"Interval: **{report.interval}** (allowed: 4h primary, 1h alternate). "
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
        "",
        "## Honesty / pre-registered rules",
        "",
        report.honesty,
        "",
        "## Dual-print bar (frozen before scoring)",
        "",
        report.rules,
        "",
        report.gates_note,
        "",
        "| print | rule | can enter ranking average? |",
        "| --- | --- | --- |",
        (
            f"| Kraken primary 720 {report.interval} | public Spot, 720-bar cap; "
            f"#96+A+B+C; rank among dual-print passers by `{report.ranking_key}` "
            "| **Kraken mean HO only** |"
        ),
        (
            f"| Binance.US older 720 {report.interval} | same #102 definition: "
            f"720 committed {report.interval} bars ending before the primary "
            "Kraken first bar; must combined-PASS | **no** (gate only; not averaged) |"
        ),
        ("| Kraken-only combined ranking | informational | no |"),
        "",
        "## Pre-registered catalog",
        "",
        report.catalog_note,
        "",
        (
            "Frozen core ids: "
            + ", ".join(f"`{item}`" for item in INTRADAY_DUAL_PRINT_CORE_IDS)
            + "."
        ),
        "",
        (
            "Optional feature ids (only when aligned series present): "
            + ", ".join(f"`{item}`" for item in OPTIONAL_FEATURE_IDS)
            + f". Present this run: {report.optional_feature_ids or 'none'}."
        ),
        "",
        "## Skipped optional families",
        "",
    ]
    for note in report.skipped_families:
        lines.append(f"- {note}")
    lines.extend(
        [
            "",
            "## Kraken public OHLC cap",
            "",
            report.kraken_cap_note,
            "",
        ]
    )
    if report.data_notes:
        lines.extend(["## Data", ""])
        for note in report.data_notes:
            lines.append(f"- {note}")
        lines.append("")

    lines.extend(
        [
            f"## Binance.US second print (required {report.interval} gate)",
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
                f"Frozen ranking key: `{report.ranking_key}`. Only names that "
                "already clear combined on **both** prints appear here. "
                "Empty table = no promotee (success). A new Settings pin is "
                "added only if this table is non-empty, and then default "
                "**false**."
            ),
            "",
            (
                "| dual rank | id | family | Kraken mean HO | Binance mean HO | "
                "Kraken BTC HO | Kraken ETH HO | selected | can flip flag |"
            ),
            "| ---: | --- | --- | ---: | ---: | ---: | ---: | :---: | :---: |",
        ]
    )
    if not dual_rows:
        lines.append("| — | — | — | n/a | n/a | n/a | n/a | no | no |")
    else:
        for row in dual_rows:
            lines.append(
                f"| {row.dual_print_rank} | `{row.candidate_id}` | {row.family} | "
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
                "| id | family | Kraken combined | Binance combined | dual-print | "
                "Kraken mean HO | Binance mean HO |"
            ),
            "| --- | --- | :---: | :---: | :---: | ---: | ---: |",
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
            f"| `{row.candidate_id}` | {row.family} | {_verdict(row.kraken_combined)} | "
            f"{_verdict(row.binance_combined)} | "
            f"{'yes' if row.dual_print else 'no'} | "
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
                "Binance.US with the Kraken primary window. Do not claim a "
                "4h/1h print as the daily EMA edge."
            ),
            "",
        ]
    )
    return "\n".join(lines)
