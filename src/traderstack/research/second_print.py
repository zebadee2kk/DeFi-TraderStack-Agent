"""Second independent print for ``ema_9_21_adx15``.

Pre-registered slice rules (frozen before any Binance or Kraken-prefix
score is computed). An honest FAIL is success. This module never flips
``PAPER_PROMOTE_EMA_9_21_ADX15`` or ``PAPER_PROMOTE_EMA_9_21`` and never
enters a promotion average with the #99/#100 Kraken print.

Kraken-compatible path
----------------------
Kraken public Spot OHLC cannot retrieve a second 720-bar era: ``since``
pages forward only. A non-overlapping 720-bar Kraken slice does not
exist on that endpoint. The Kraken-compatible path that *is* available
is the **holdout-blind prefix**: drop the last ``holdout_fraction`` of
the public 720 (the primary holdout tail) and score the remaining
prefix. That is the same venue and overlapping walk-forward era — **not**
a second independent print. Gate B still requires 3×240 bars and fails
closed when the prefix is shorter than 720.

If a caller supplies a Kraken-compatible daily series long enough that
an older 720-bar slice ends before the primary window's first bar, that
slice is scored as a Kraken second era. Public OHLC cannot produce it.

Binance Spot path (the second independent print)
------------------------------------------------
Venue: Binance Spot daily klines for BTCUSDT and ETHUSDT. This
environment's ``api.binance.com`` is HTTP 451 (geo-restricted);
``api.binance.us`` is the reachable public Spot endpoint and is labeled
Binance.US, not Binance.com. Quote is USDT, not USD.

Slice rule (frozen): 720 committed daily bars whose last ``opened_at``
is strictly before the primary Kraken window's first ``opened_at``.
No overlap with the primary window (hence none with its holdout). If
either series is shorter than 720, the Binance print fails closed.

Fees: the paper-research defaults ``max(PRETRADE_FEE_BPS, PAPER_FEE_BPS)``
+ ``PRETRADE_SLIPPAGE_BPS`` (10+5; gate C at 20+10). Documented; not a
maker-rebate study. These fees are not averaged with the Kraken print.

Promotion: report-only. ``CAN_ENTER_PROMOTION_AVERAGE = False``. A
multi-venue bar is not pre-registered. Combined-pass on Binance cannot
promote and cannot flip the pin.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field

from traderstack.candles import Candle
from traderstack.research.binance_spot import BINANCE_TAKER_BPS_NOTE
from traderstack.research.daily_candidates import default_expanded_harder_gates_candidates
from traderstack.research.daily_robustness import KRAKEN_DAILY_CAP_NOTE, is_yahoo_symbol
from traderstack.research.harder_gates import (
    CandidateHarderResult,
    MULTIWINDOW_BARS,
    MULTIWINDOW_COUNT,
    RANKING_KEY,
    _pct,
    _ratio,
    _verdict,
    kraken_daily_candles,
    paper_promote_flag_name,
    run_harder_gates,
)
from traderstack.research.miles_candidates import SearchCandidate

DEFAULT_CANDIDATE_ID = "ema_9_21_adx15"
DEFAULT_PROMOTE_FLAG = "PAPER_PROMOTE_EMA_9_21_ADX15"
# #99/#100 combined-passers, frozen before this second print is scored.
SECOND_PRINT_CANDIDATE_IDS: tuple[str, ...] = (
    "ema_9_21_adx15",
    "ema_9_21_adx18",
    "ema_12_26_adx18",
    "ema_12_26_adx20",
)
SECOND_PRINT_BARS = 720
# Committed #99/#100/#100 public-OHLC first bar. Used only when this run
# has no Kraken daily BTC series from which to derive the cutoff.
DOCUMENTED_PRIMARY_FIRST_ISO = "2024-09-22T00:00:00+00:00"
KRAKEN_PREFIX_RULE = "holdout_blind_prefix"
BINANCE_SLICE_RULE = "older_720_ending_before_primary_first_bar"
CAN_ENTER_PROMOTION_AVERAGE = False
MULTI_VENUE_BAR_PREREGISTERED = False
BINANCE_TO_SCORE_SYMBOL = {"BTCUSDT": "BTC/USD", "ETHUSDT": "ETH/USD"}

SECOND_PRINT_RULES = (
    "Pre-registered before any second-print score (do not retune after "
    "seeing PnL). (1) Kraken public OHLC cannot unlock a second 720-bar "
    "era (`since` pages forward only). (2) Kraken-compatible path that "
    f"exists: `{KRAKEN_PREFIX_RULE}` — drop the last holdout_fraction of "
    "the public 720 and score the prefix. Same venue; overlapping WF; "
    "not an independent era. Gate B still needs "
    f"{MULTIWINDOW_COUNT}×{MULTIWINDOW_BARS} bars and fails closed if "
    "short. (3) A Kraken older-720 is scored only if a supplied series "
    "has 720 committed daily bars whose last open is before the primary "
    "first bar. Public OHLC cannot produce that. (4) Binance Spot daily "
    f"BTCUSDT+ETHUSDT slice `{BINANCE_SLICE_RULE}`: 720 committed bars "
    "ending strictly before the primary Kraken first bar. Labeled "
    "non-Kraken. (5) Same strategy definition and #96+A+B+C gates. "
    "(6) Fees are paper-research 10+5 (gate C 20+10). (7) "
    f"CAN_ENTER_PROMOTION_AVERAGE={str(CAN_ENTER_PROMOTION_AVERAGE).lower()}; "
    "MULTI_VENUE_BAR_PREREGISTERED="
    f"{str(MULTI_VENUE_BAR_PREREGISTERED).lower()}. Report-only. "
    f"(8) `{DEFAULT_PROMOTE_FLAG}` stays default false. No live."
)


def documented_primary_first() -> datetime:
    return datetime.fromisoformat(DOCUMENTED_PRIMARY_FIRST_ISO)


def primary_first_opened_at(
    histories: dict[str, tuple[Candle, ...]],
) -> tuple[datetime, str]:
    """Cutoff for the older slice. Prefer this run's Kraken BTC first bar."""
    btc = kraken_daily_candles(histories, "BTC/USD")
    if btc:
        return btc[0].opened_at, "this_run_kraken_btc_first_bar"
    return documented_primary_first(), "documented_primary_first_iso"


def holdout_blind_prefix(
    candles: tuple[Candle, ...],
    *,
    holdout_fraction: float = 0.20,
) -> tuple[Candle, ...]:
    """Drop the last holdout tail. Pre-registered; do not peek at PnL."""
    if not candles or holdout_fraction <= 0:
        return candles
    if holdout_fraction >= 1:
        return ()
    holdout = max(1, int(round(len(candles) * holdout_fraction)))
    prefix_len = len(candles) - holdout
    if prefix_len <= 0:
        return ()
    return candles[:prefix_len]


def slice_ending_before(
    candles: tuple[Candle, ...],
    *,
    before: datetime,
    bars: int = SECOND_PRINT_BARS,
) -> tuple[Candle, ...]:
    """Last ``bars`` whose ``opened_at`` is strictly before ``before``."""
    eligible = tuple(item for item in candles if item.opened_at < before)
    if len(eligible) <= bars:
        return eligible
    return eligible[-bars:]


def remap_binance_for_scoring(
    histories: dict[str, tuple[Candle, ...]],
) -> dict[str, tuple[Candle, ...]]:
    """Map BTCUSDT/ETHUSDT → BTC/USD / ETH/USD for the existing scorer.

    Venue identity stays on the original keys; the remapped copies are
    scoring adapters only and must not be labeled Kraken in the report.
    """
    remapped: dict[str, tuple[Candle, ...]] = {}
    for candles in histories.values():
        if not candles:
            continue
        source_symbol = candles[0].symbol.upper()
        target = BINANCE_TO_SCORE_SYMBOL.get(source_symbol)
        if target is None:
            continue
        copied = tuple(item.model_copy(update={"symbol": target}) for item in candles)
        remapped[f"{target}@{copied[0].interval}"] = copied
    return remapped


def second_print_candidates(
    *,
    candidate_ids: tuple[str, ...] = SECOND_PRINT_CANDIDATE_IDS,
    btc_overlay: tuple[Candle, ...] | None = None,
) -> tuple[SearchCandidate, ...]:
    catalog = default_expanded_harder_gates_candidates(btc_overlay=btc_overlay)
    by_id = {item.candidate_id: item for item in catalog}
    missing = [item for item in candidate_ids if item not in by_id]
    if missing:
        raise ValueError(f"second-print ids not in expanded catalog: {missing}")
    return tuple(by_id[item] for item in candidate_ids)


def _span(candles: tuple[Candle, ...] | None) -> tuple[str | None, str | None, int]:
    if not candles:
        return None, None, 0
    return candles[0].opened_at.isoformat(), candles[-1].opened_at.isoformat(), len(candles)


def _overlaps_primary(candles: tuple[Candle, ...], primary_first: datetime) -> bool:
    return any(item.opened_at >= primary_first for item in candles)


class PrintCandidateRow(BaseModel):
    candidate_id: str
    venue: str
    eligible_96: bool = False
    gate_a_pass: bool = False
    gate_b_pass: bool = False
    gate_c_pass: bool = False
    combined: bool = False
    combined_rank: int | None = None
    mean_holdout_excess: float | None = None
    baseline_wf_total: float | None = None
    baseline_btc_wf: float | None = None
    baseline_eth_wf: float | None = None
    baseline_btc_holdout: float | None = None
    baseline_eth_holdout: float | None = None
    holdout_magnitude_ratio: float | None = None
    windows_passed: int = 0
    gate_a_reasons: list[str] = Field(default_factory=list)
    gate_b_reasons: list[str] = Field(default_factory=list)
    gate_c_reasons: list[str] = Field(default_factory=list)
    can_promote: bool = False


class SliceMeta(BaseModel):
    rule: str
    venue: str
    available: bool
    bars_btc: int = 0
    bars_eth: int = 0
    first: str | None = None
    last: str | None = None
    overlaps_primary_window: bool = False
    overlaps_primary_holdout: bool = False
    fail_closed_reason: str | None = None


class SecondPrintReport(BaseModel):
    generated_at: datetime
    candidate_id: str
    promote_flag: str
    candidate_ids: list[str]
    ranking_key: str
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
    kraken_second_720: SliceMeta
    kraken_prefix: SliceMeta
    binance_slice: SliceMeta
    binance_source: str | None = None
    kraken_prefix_rows: list[PrintCandidateRow] = Field(default_factory=list)
    binance_rows: list[PrintCandidateRow] = Field(default_factory=list)
    target_prefix: PrintCandidateRow | None = None
    target_binance: PrintCandidateRow | None = None
    binance_combined_pass: bool = False
    binance_print_fail_closed: bool = True
    can_enter_promotion_average: bool = False
    multi_venue_bar_preregistered: bool = False
    keep_flag_false: bool = True
    honesty: str
    recommendation: str
    rules: str = SECOND_PRINT_RULES
    fee_note: str = BINANCE_TAKER_BPS_NOTE
    kraken_cap_note: str = KRAKEN_DAILY_CAP_NOTE
    data_notes: list[str] = Field(default_factory=list)


def _row_from_harder(
    row: CandidateHarderResult,
    *,
    venue: str,
) -> PrintCandidateRow:
    return PrintCandidateRow(
        candidate_id=row.candidate_id,
        venue=venue,
        eligible_96=row.eligible_96,
        gate_a_pass=row.gate_a_pass,
        gate_b_pass=row.gate_b_pass,
        gate_c_pass=row.gate_c_pass,
        combined=row.combined,
        combined_rank=row.combined_rank,
        mean_holdout_excess=row.mean_holdout_excess,
        baseline_wf_total=row.baseline_wf_total,
        baseline_btc_wf=row.baseline_btc_wf,
        baseline_eth_wf=row.baseline_eth_wf,
        baseline_btc_holdout=row.baseline_btc_holdout,
        baseline_eth_holdout=row.baseline_eth_holdout,
        holdout_magnitude_ratio=row.holdout_magnitude_ratio,
        windows_passed=row.windows_passed,
        gate_a_reasons=list(row.gate_a_reasons),
        gate_b_reasons=list(row.gate_b_reasons),
        gate_c_reasons=list(row.gate_c_reasons),
        can_promote=False,
    )


def _score_histories(
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
    venue: str,
) -> list[PrintCandidateRow]:
    if not histories:
        return []
    report = run_harder_gates(
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
    return [_row_from_harder(row, venue=venue) for row in report.candidates]


def _kraken_only(histories: dict[str, tuple[Candle, ...]]) -> dict[str, tuple[Candle, ...]]:
    return {
        key: candles
        for key, candles in histories.items()
        if candles and not is_yahoo_symbol(candles[0].symbol)
        and candles[0].symbol.upper() not in BINANCE_TO_SCORE_SYMBOL
    }


def _recommendation(
    *,
    promote_flag: str,
    candidate_id: str,
    kraken_second: SliceMeta,
    prefix: SliceMeta,
    binance: SliceMeta,
    target_binance: PrintCandidateRow | None,
) -> str:
    lines = [
        f"**Keep `{promote_flag}=false`.** This second print is "
        "report-only. A multi-venue bar was not pre-registered, so a "
        "Binance combined-pass cannot enter the promotion average and "
        "cannot flip the pin. An honest FAIL is success.",
        "",
        f"- Kraken second 720-bar era: "
        f"{'available' if kraken_second.available else 'UNAVAILABLE'}"
        + (
            f" ({kraken_second.fail_closed_reason})"
            if kraken_second.fail_closed_reason
            else ""
        )
        + ".",
        f"- Kraken `{KRAKEN_PREFIX_RULE}`: "
        f"{prefix.bars_btc} BTC / {prefix.bars_eth} ETH bars "
        f"({prefix.first} → {prefix.last}). Same venue; not independent.",
        f"- Binance `{BINANCE_SLICE_RULE}`: "
        f"{'scored' if binance.available else 'FAIL-CLOSED'} "
        f"({binance.venue}; {binance.bars_btc} BTC / {binance.bars_eth} ETH; "
        f"{binance.first} → {binance.last}).",
    ]
    if target_binance is None:
        lines.append(
            f"- `{candidate_id}` Binance combined: **FAIL** (no scorable "
            "print). Empty/failed Binance is success."
        )
    else:
        lines.append(
            f"- `{candidate_id}` Binance #96={_verdict(target_binance.eligible_96)} "
            f"A={_verdict(target_binance.gate_a_pass)} "
            f"B={_verdict(target_binance.gate_b_pass)} "
            f"C={_verdict(target_binance.gate_c_pass)} "
            f"combined=**{_verdict(target_binance.combined)}** "
            "(cannot promote)."
        )
    lines.append(
        f"- `{promote_flag}` stays default **false**. Do not enable live."
    )
    return "\n".join(lines)


def run_second_print(
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
    candidate_id: str = DEFAULT_CANDIDATE_ID,
    candidate_ids: tuple[str, ...] = SECOND_PRINT_CANDIDATE_IDS,
    binance_source: str | None = None,
    now: datetime | None = None,
    data_notes: list[str] | None = None,
) -> SecondPrintReport:
    if candidate_id not in candidate_ids:
        raise ValueError(f"{candidate_id} is not in the second-print id list")
    generated = now or datetime.now(UTC)
    kraken = _kraken_only(kraken_histories)
    primary_first, primary_source = primary_first_opened_at(kraken)
    btc = kraken_daily_candles(kraken, "BTC/USD")
    eth = kraken_daily_candles(kraken, "ETH/USD")
    primary_last = btc[-1].opened_at.isoformat() if btc else None
    primary_bars = len(btc) if btc else None
    holdout_start: datetime | None = None
    if btc:
        prefix_preview = holdout_blind_prefix(btc, holdout_fraction=holdout_fraction)
        if prefix_preview:
            holdout_start = prefix_preview[-1].opened_at

    kraken_old_btc = slice_ending_before(btc or (), before=primary_first)
    kraken_old_eth = slice_ending_before(eth or (), before=primary_first)
    kraken_second_available = (
        len(kraken_old_btc) >= SECOND_PRINT_BARS and len(kraken_old_eth) >= SECOND_PRINT_BARS
    )
    kraken_second = SliceMeta(
        rule="older_720_ending_before_primary_first_bar",
        venue="kraken_public_ohlc",
        available=kraken_second_available,
        bars_btc=len(kraken_old_btc),
        bars_eth=len(kraken_old_eth),
        first=kraken_old_btc[0].opened_at.isoformat() if kraken_old_btc else None,
        last=kraken_old_btc[-1].opened_at.isoformat() if kraken_old_btc else None,
        overlaps_primary_window=False,
        overlaps_primary_holdout=False,
        fail_closed_reason=(
            None
            if kraken_second_available
            else (
                "Kraken public OHLC cannot retrieve bars older than the "
                f"most recent {SECOND_PRINT_BARS}; no non-overlapping "
                "second 720 exists"
            )
        ),
    )

    prefix_btc = holdout_blind_prefix(btc or (), holdout_fraction=holdout_fraction)
    prefix_eth = holdout_blind_prefix(eth or (), holdout_fraction=holdout_fraction)
    prefix_first, prefix_last, _prefix_n = _span(prefix_btc)
    prefix_available = bool(prefix_btc and prefix_eth)
    prefix_overlaps_holdout = False
    if prefix_btc and holdout_start is not None:
        prefix_overlaps_holdout = any(item.opened_at > holdout_start for item in prefix_btc)
    kraken_prefix = SliceMeta(
        rule=KRAKEN_PREFIX_RULE,
        venue="kraken_public_ohlc_holdout_blind_prefix",
        available=prefix_available,
        bars_btc=len(prefix_btc),
        bars_eth=len(prefix_eth),
        first=prefix_first,
        last=prefix_last,
        overlaps_primary_window=True,
        overlaps_primary_holdout=prefix_overlaps_holdout,
        fail_closed_reason=(
            None
            if prefix_available
            else "Kraken BTC/ETH daily missing; prefix not scored"
        ),
    )

    raw_binance = binance_histories or {}
    sliced_binance: dict[str, tuple[Candle, ...]] = {}
    for key, candles in raw_binance.items():
        sliced_binance[key] = slice_ending_before(candles, before=primary_first)
    remapped = remap_binance_for_scoring(sliced_binance)
    score_btc = remapped.get("BTC/USD@1d")
    score_eth = remapped.get("ETH/USD@1d")
    binance_short = (
        score_btc is None
        or score_eth is None
        or len(score_btc) < SECOND_PRINT_BARS
        or len(score_eth) < SECOND_PRINT_BARS
    )
    bn_first, bn_last, _bn_n = _span(score_btc)
    overlap = bool(score_btc and _overlaps_primary(score_btc, primary_first))
    holdout_overlap = False
    if score_btc and holdout_start is not None:
        holdout_overlap = any(item.opened_at > holdout_start for item in score_btc)
    if not raw_binance:
        bn_reason = "Binance Spot daily missing or failed (empty print is success)"
    elif binance_short:
        bn_reason = (
            f"Binance slice shorter than {SECOND_PRINT_BARS} committed "
            f"bars (BTC={len(score_btc or ())}, ETH={len(score_eth or ())}); "
            "fail closed"
        )
    elif overlap:
        bn_reason = "Binance slice overlaps the primary Kraken window; rejected"
    else:
        bn_reason = None
    binance_available = bn_reason is None and not binance_short and not overlap
    binance_slice = SliceMeta(
        rule=BINANCE_SLICE_RULE,
        venue=binance_source or "binance_spot",
        available=binance_available,
        bars_btc=len(score_btc or ()),
        bars_eth=len(score_eth or ()),
        first=bn_first,
        last=bn_last,
        overlaps_primary_window=overlap,
        overlaps_primary_holdout=holdout_overlap,
        fail_closed_reason=bn_reason,
    )

    catalog = second_print_candidates(candidate_ids=candidate_ids)
    prefix_rows: list[PrintCandidateRow] = []
    if prefix_available:
        prefix_histories = {
            "BTC/USD@1d": prefix_btc,
            "ETH/USD@1d": prefix_eth,
        }
        prefix_rows = _score_histories(
            prefix_histories,
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
            venue=kraken_prefix.venue,
        )

    binance_rows: list[PrintCandidateRow] = []
    if binance_available:
        binance_rows = _score_histories(
            remapped,
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
            venue=binance_slice.venue,
        )

    target_prefix = next(
        (row for row in prefix_rows if row.candidate_id == candidate_id), None
    )
    target_binance = next(
        (row for row in binance_rows if row.candidate_id == candidate_id), None
    )
    binance_combined = bool(target_binance is not None and target_binance.combined)

    honesty = (
        f"Second print for `{candidate_id}` and the #99/#100 "
        f"combined-passers ({', '.join(f'`{item}`' for item in candidate_ids)}). "
        + SECOND_PRINT_RULES
        + " Yahoo remains a longer non-Kraken A/B from the honesty pack "
        "and is not re-averaged here. Empty or failed Binance is success. "
        f"This run does not flip `{paper_promote_flag_name(candidate_id)}` "
        "(default false) and does not enable live."
    )
    if target_binance is None:
        honesty += (
            f" `{candidate_id}` has no scorable Binance print "
            f"({binance_slice.fail_closed_reason or 'missing'})."
        )
    elif binance_combined:
        honesty += (
            f" `{candidate_id}` combined-PASSES on the Binance slice. "
            "That is report-only and cannot enter the promotion average."
        )
    else:
        honesty += (
            f" `{candidate_id}` combined-FAILS on the Binance slice. "
            "An honest FAIL is the successful outcome."
        )

    return SecondPrintReport(
        generated_at=generated,
        candidate_id=candidate_id,
        promote_flag=paper_promote_flag_name(candidate_id),
        candidate_ids=list(candidate_ids),
        ranking_key=RANKING_KEY,
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
        kraken_second_720=kraken_second,
        kraken_prefix=kraken_prefix,
        binance_slice=binance_slice,
        binance_source=binance_source,
        kraken_prefix_rows=prefix_rows,
        binance_rows=binance_rows,
        target_prefix=target_prefix,
        target_binance=target_binance,
        binance_combined_pass=binance_combined,
        binance_print_fail_closed=not binance_available,
        can_enter_promotion_average=CAN_ENTER_PROMOTION_AVERAGE,
        multi_venue_bar_preregistered=MULTI_VENUE_BAR_PREREGISTERED,
        keep_flag_false=True,
        honesty=honesty,
        recommendation=_recommendation(
            promote_flag=paper_promote_flag_name(candidate_id),
            candidate_id=candidate_id,
            kraken_second=kraken_second,
            prefix=kraken_prefix,
            binance=binance_slice,
            target_binance=target_binance,
        ),
        data_notes=list(data_notes or []),
    )


def _gate_table(row: PrintCandidateRow | None) -> list[str]:
    if row is None:
        return [
            "| field | value |",
            "| --- | --- |",
            "| combined | **FAIL** (no scorable print) |",
        ]
    return [
        "| field | value |",
        "| --- | --- |",
        f"| id | `{row.candidate_id}` |",
        f"| venue | {row.venue} |",
        f"| #96 balanced-holdout | **{_verdict(row.eligible_96)}** |",
        f"| A Magnitude | **{_verdict(row.gate_a_pass)}** |",
        f"| B Multi-window | **{_verdict(row.gate_b_pass)}** |",
        f"| C Fee stress | **{_verdict(row.gate_c_pass)}** |",
        f"| Combined | **{_verdict(row.combined)}** |",
        f"| can promote | **no** |",
        (
            f"| combined rank (in this print) | "
            f"{row.combined_rank if row.combined_rank is not None else '—'} |"
        ),
        f"| mean HO excess | {_pct(row.mean_holdout_excess)} |",
        f"| BTC holdout | {_pct(row.baseline_btc_holdout)} |",
        f"| ETH holdout | {_pct(row.baseline_eth_holdout)} |",
        f"| min/max ratio | {_ratio(row.holdout_magnitude_ratio)} |",
        f"| BTC WF total | {_pct(row.baseline_btc_wf)} |",
        f"| ETH WF total | {_pct(row.baseline_eth_wf)} |",
        f"| mean WF total | {_pct(row.baseline_wf_total)} |",
        f"| gate B windows | {row.windows_passed}/{MULTIWINDOW_COUNT} |",
    ]


def _slice_lines(meta: SliceMeta) -> list[str]:
    status = "available" if meta.available else "UNAVAILABLE / fail-closed"
    return [
        f"- Rule: `{meta.rule}`",
        f"- Venue label: `{meta.venue}`",
        f"- Status: **{status}**",
        f"- Bars: BTC {meta.bars_btc} / ETH {meta.bars_eth}",
        f"- Span: {meta.first or 'n/a'} → {meta.last or 'n/a'}",
        f"- Overlaps primary window: {'yes' if meta.overlaps_primary_window else 'no'}",
        f"- Overlaps primary holdout: {'yes' if meta.overlaps_primary_holdout else 'no'}",
        f"- Fail-closed reason: {meta.fail_closed_reason or '—'}",
    ]


def _passer_table(rows: list[PrintCandidateRow]) -> list[str]:
    lines = [
        (
            "| id | #96 | A | B | C | combined | mean HO | BTC HO | ETH HO | "
            "can promote |"
        ),
        "| --- | :---: | :---: | :---: | :---: | :---: | ---: | ---: | ---: | :---: |",
    ]
    if not rows:
        lines.append("| — | — | — | — | — | FAIL | n/a | n/a | n/a | no |")
        return lines
    for row in rows:
        lines.append(
            f"| `{row.candidate_id}` | {_verdict(row.eligible_96)} | "
            f"{_verdict(row.gate_a_pass)} | {_verdict(row.gate_b_pass)} | "
            f"{_verdict(row.gate_c_pass)} | **{_verdict(row.combined)}** | "
            f"{_pct(row.mean_holdout_excess)} | {_pct(row.baseline_btc_holdout)} | "
            f"{_pct(row.baseline_eth_holdout)} | no |"
        )
    return lines


def render_second_print_markdown(report: SecondPrintReport) -> str:
    lines: list[str] = [
        f"# `{report.candidate_id}` second print",
        "",
        f"Generated: {report.generated_at.isoformat()}",
        (
            f"Candidate: `{report.candidate_id}` (documented paper pin "
            f"`{report.promote_flag}`, default **false**)"
        ),
        (
            f"Also re-scored (informational): "
            + ", ".join(f"`{item}`" for item in report.candidate_ids)
            + "."
        ),
        (
            f"Baseline costs: fee={report.fee_bps:g} bps + slippage="
            f"{report.slippage_bps:g} bps. Walk-forward: train="
            f"{report.train_size} test={report.test_size} step="
            f"{report.step_size}; holdout_fraction={report.holdout_fraction:.0%}."
        ),
        (
            f"Primary Kraken window first bar: {report.primary_first} "
            f"(source=`{report.primary_first_source}`; last="
            f"{report.primary_last or 'n/a'}; bars={report.primary_bars or 'n/a'})."
        ),
        (
            f"`can_enter_promotion_average="
            f"{str(report.can_enter_promotion_average).lower()}`; "
            f"`multi_venue_bar_preregistered="
            f"{str(report.multi_venue_bar_preregistered).lower()}`; "
            f"`keep_flag_false={str(report.keep_flag_false).lower()}`."
        ),
        "",
        "## Honesty / pre-registered rules",
        "",
        report.honesty,
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
            "## 1. Kraken-compatible path",
            "",
            "### 1a. Second 720-bar Kraken era",
            "",
        ]
    )
    lines.extend(_slice_lines(report.kraken_second_720))
    lines.extend(
        [
            "",
            "This is **not** invented from Yahoo, charts-spot, or a shuffled "
            "offset inside the same 720. Public OHLC cannot page backward.",
            "",
            "### 1b. Holdout-blind prefix (same venue; not independent)",
            "",
        ]
    )
    lines.extend(_slice_lines(report.kraken_prefix))
    lines.extend(
        [
            "",
            (
                "Same Kraken public print as #99/#100 with the primary "
                "holdout tail removed. Walk-forward still overlaps the "
                "primary research prefix. Gate B needs 720 bars and fails "
                "closed on a shorter prefix — that is not retuned to 2×240 "
                "after seeing the length."
            ),
            "",
            f"#### `{report.candidate_id}` on the prefix",
            "",
        ]
    )
    lines.extend(_gate_table(report.target_prefix))
    if report.target_prefix is not None and report.target_prefix.gate_b_reasons:
        lines.extend(
            [
                "",
                "Gate B reasons: "
                + ", ".join(f"`{item}`" for item in report.target_prefix.gate_b_reasons)
                + ".",
            ]
        )
    lines.extend(
        [
            "",
            "Other #99/#100 combined-passers on the prefix (informational):",
            "",
        ]
    )
    lines.extend(_passer_table(report.kraken_prefix_rows))
    lines.extend(
        [
            "",
            "## 2. Binance Spot daily (non-Kraken; report-only)",
            "",
            "### 2a. Venue and fees",
            "",
            (
                f"Source this run: `{report.binance_source or 'n/a'}`. "
                "`api.binance.com` is HTTP 451 from this environment; "
                "`api.binance.us` is the reachable public Spot kline host "
                "and is labeled **Binance.US**, not Binance.com. Pairs are "
                "BTCUSDT and ETHUSDT. Do not average with Kraken."
            ),
            "",
            report.fee_note,
            "",
            "### 2b. Slice",
            "",
        ]
    )
    lines.extend(_slice_lines(report.binance_slice))
    lines.extend(
        [
            "",
            (
                "Pre-registered: 720 committed daily bars ending strictly "
                "before the primary Kraken first bar. This window does not "
                "overlap the primary holdout. A short or overlapping series "
                "fails closed and is not rewritten as a soft PASS."
            ),
            "",
            f"### 2c. `{report.candidate_id}` vs harder gates",
            "",
        ]
    )
    lines.extend(_gate_table(report.target_binance))
    if report.target_binance is not None:
        reason_blocks = []
        if report.target_binance.gate_a_reasons:
            reason_blocks.append(
                "A: " + ", ".join(f"`{item}`" for item in report.target_binance.gate_a_reasons)
            )
        if report.target_binance.gate_b_reasons:
            reason_blocks.append(
                "B: " + ", ".join(f"`{item}`" for item in report.target_binance.gate_b_reasons)
            )
        if report.target_binance.gate_c_reasons:
            reason_blocks.append(
                "C: " + ", ".join(f"`{item}`" for item in report.target_binance.gate_c_reasons)
            )
        if reason_blocks:
            lines.extend(["", "Fail reasons: " + "; ".join(reason_blocks) + "."])
    lines.extend(
        [
            "",
            (
                f"Binance combined for `{report.candidate_id}`: "
                f"**{_verdict(report.binance_combined_pass)}**. "
                "Cannot enter the promotion average. Cannot flip "
                f"`{report.promote_flag}`."
            ),
            "",
            "### 2d. Other #99/#100 combined-passers (informational)",
            "",
        ]
    )
    lines.extend(_passer_table(report.binance_rows))
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
                "this print with the #99/#100 Kraken window."
            ),
            "",
        ]
    )
    return "\n".join(lines)
