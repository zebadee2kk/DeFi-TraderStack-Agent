"""Fee-aware evaluation for the #142 Polymarket crypto wedge tape.

Report-only. Never invents settlement fills. Never writes a ``PAPER_PROMOTE_*``
pin. ``can_promote`` is always False in this CLI — dual independent prints and
a separate Settings pin (out of scope) would still be required later.
Empty / negative is success.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from traderstack.polymarket.crypto_gate import apply_crucix_gate, stand_aside
from traderstack.polymarket.crypto_models import (
    DEFAULT_PROMOTE_FLAG,
    MIN_ROWS_PER_PRINT,
    MIN_TRADES_PER_PRINT,
    MULTI_PRINT_BAR_PREREGISTERED,
    POLYMARKET_CRYPTO_TAKER_FEE_CAP_PER_100_SHARES,
    POLYMARKET_CRYPTO_TAKER_FEE_RATE,
    PREREGISTERED_WEDGE_THRESHOLD,
    PRIMARY_MODEL_VERSION,
    CryptoWedgeRow,
    WedgeRowStatus,
)

PRINT_SINGLE = "single_print"
PRINT_DUAL = "dual_print"
CAN_ENTER_PROMOTION_AVERAGE = False
MIN_ROWS_FOR_HOLDOUT = 10
DEFAULT_HOLDOUT_FRACTION = 0.20
SHARES_NOTIONAL = 100.0  # fee formula denominated per 100 shares


class SettlementRow(BaseModel):
    """Resolved outcome for one market. Never used as a decision-time mid."""

    market_id: str
    yes_won: bool
    resolution_source: str
    resolves_at: datetime | None = None
    print_id: str | None = None


class ContractSide(str):
    YES = "yes"
    NO = "no"


class RowDisposition(BaseModel):
    market_id: str
    print_id: str
    asset: str
    resolves_on: date | None = None
    status: str
    reason: str | None = None
    side: str | None = None
    wedge: float | None = None
    conservative_pnl: float | None = None
    fade_pnl: float | None = None
    midfill_pnl: float | None = None
    yes_resolved: bool | None = None


class PrintMetrics(BaseModel):
    print_id: str
    n_rows: int = 0
    n_decision: int = 0
    n_lookahead: int = 0
    n_non_ok: int = 0
    n_stand_aside: int = 0
    n_below_threshold: int = 0
    n_unsettled: int = 0
    n_eligible: int = 0
    n_would_trade: int = 0
    treatment_pnl: float = 0.0
    fade_pnl: float = 0.0
    hold_pnl: float = 0.0
    midfill_treatment_pnl: float = 0.0
    treatment_excess_vs_hold: float = 0.0
    treatment_excess_vs_fade: float = 0.0
    holdout_n: int | None = None
    holdout_would_trade: int | None = None
    holdout_treatment_excess_vs_hold: float | None = None
    holdout_treatment_excess_vs_fade: float | None = None
    fail_closed_reason: str | None = None
    used_mid_fill_as_primary: bool = False
    hedged_status: str = "skipped_not_invented"


class CryptoWedgeEvalReport(BaseModel):
    strategy_id: str = "polymarket_crypto_threshold_wedge"
    model_version: str = PRIMARY_MODEL_VERSION
    print_kind: Literal["single_print", "dual_print"]
    independent: bool
    independence_reason: str
    can_promote: bool = False
    can_enter_promotion_average: bool = False
    keep_flag_false: bool = True
    recommended_promote_flag: str = "none"
    promote_flag_name: str = DEFAULT_PROMOTE_FLAG
    multi_print_bar_preregistered: bool = MULTI_PRINT_BAR_PREREGISTERED
    wedge_threshold: float = PREREGISTERED_WEDGE_THRESHOLD
    holdout_fraction: float = DEFAULT_HOLDOUT_FRACTION
    prints: list[PrintMetrics] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    dispositions: list[RowDisposition] = Field(default_factory=list)


def _clip01(value: float) -> float:
    return min(1.0, max(0.0, value))


def polymarket_taker_fee(price: float, *, shares: float = SHARES_NOTIONAL) -> float:
    """Frozen Fee Structure V2: shares * 0.07 * p * (1-p), capped per 100 shares."""
    p = _clip01(price)
    raw = shares * POLYMARKET_CRYPTO_TAKER_FEE_RATE * p * (1.0 - p)
    cap = POLYMARKET_CRYPTO_TAKER_FEE_CAP_PER_100_SHARES * (shares / 100.0)
    return min(raw, cap)


def half_spread_from_row(row: CryptoWedgeRow) -> float | None:
    if row.poly_best_bid is None or row.poly_best_ask is None:
        return None
    if row.poly_best_ask < row.poly_best_bid:
        return None
    return 0.5 * (row.poly_best_ask - row.poly_best_bid)


def conservative_entry(side: str, mid: float, half_spread: float) -> float:
    if side == ContractSide.YES:
        return _clip01(mid + half_spread)
    return _clip01((1.0 - mid) + half_spread)


def realized_pnl(entry: float, *, won: bool, fee: float) -> float:
    gross = (1.0 - entry) if won else (-entry)
    return gross - fee


def treatment_side(wedge: float) -> str:
    """poly rich (wedge>0) → sell YES; poly cheap → buy YES."""
    if wedge > 0:
        return ContractSide.NO
    return ContractSide.YES


def load_tape_jsonl(path: Path) -> tuple[CryptoWedgeRow, ...]:
    rows: list[CryptoWedgeRow] = []
    text = path.read_text(encoding="utf-8")
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(CryptoWedgeRow.model_validate_json(line))
    return tuple(rows)


def load_settlements(payload: object) -> tuple[SettlementRow, ...]:
    if payload is None:
        return ()
    if isinstance(payload, dict) and "settlements" in payload:
        payload = payload["settlements"]
    if not isinstance(payload, list):
        raise TypeError("settlements payload must be a JSON array or {settlements:[...]}")
    return tuple(SettlementRow.model_validate(item) for item in payload)


def decision_rows(tape: tuple[CryptoWedgeRow, ...]) -> tuple[CryptoWedgeRow, ...]:
    """Latest ok observation per market_id with observed_at < resolves_at."""
    best: dict[str, CryptoWedgeRow] = {}
    for row in tape:
        if row.status is not WedgeRowStatus.OK:
            continue
        if row.observed_at >= row.resolves_at:
            continue
        if row.poly_mid is None or row.deribit_prob is None or row.wedge is None:
            continue
        prev = best.get(row.market_id)
        if prev is None or row.observed_at > prev.observed_at:
            best[row.market_id] = row
    return tuple(sorted(best.values(), key=lambda r: (r.resolves_at, r.market_id)))


def prints_independent(
    print_a: tuple[CryptoWedgeRow, ...],
    print_b: tuple[CryptoWedgeRow, ...],
    settlements_a: tuple[SettlementRow, ...],
    settlements_b: tuple[SettlementRow, ...],
) -> tuple[bool, str]:
    if not print_a or not print_b:
        return False, "missing_print"
    assets_a = {row.asset for row in print_a}
    assets_b = {row.asset for row in print_b}
    if assets_a and assets_b and assets_a.isdisjoint(assets_b):
        return True, "disjoint_assets_btc_vs_eth"
    dates_a = {row.resolves_at.date() for row in print_a}
    dates_b = {row.resolves_at.date() for row in print_b}
    overlap = dates_a & dates_b
    if not overlap:
        return True, "non_overlapping_resolution_dates"
    sources_a = {
        s.resolution_source for s in settlements_a if s.resolution_source not in {"", "missing"}
    }
    sources_b = {
        s.resolution_source for s in settlements_b if s.resolution_source not in {"", "missing"}
    }
    if sources_a and sources_b and sources_a.isdisjoint(sources_b):
        return True, "overlapping_dates_independent_resolution_sources"
    return False, "overlapping_dates_same_or_missing_resolution_source"


def print_clears_calculator(metrics: PrintMetrics) -> bool:
    if metrics.used_mid_fill_as_primary:
        return False
    if metrics.fail_closed_reason:
        return False
    if metrics.n_eligible < MIN_ROWS_PER_PRINT:
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


def _score_print(
    rows: tuple[CryptoWedgeRow, ...],
    settlements: dict[str, SettlementRow],
    *,
    print_id: str,
    wedge_threshold: float,
    holdout_fraction: float,
    default_half_spread: float,
) -> tuple[PrintMetrics, list[RowDisposition]]:
    dispositions: list[RowDisposition] = []
    eligible: list[tuple[CryptoWedgeRow, RowDisposition]] = []
    n_lookahead = 0
    n_non_ok = 0
    n_stand_aside = 0
    n_below = 0
    n_unsettled = 0

    # Count non-decision tape rows for transparency (caller may pass decisions only).
    for row in rows:
        if row.status is not WedgeRowStatus.OK:
            n_non_ok += 1
            dispositions.append(
                RowDisposition(
                    market_id=row.market_id,
                    print_id=print_id,
                    asset=str(row.asset),
                    status="non_ok",
                    reason=str(row.status),
                )
            )
            continue
        if row.observed_at >= row.resolves_at:
            n_lookahead += 1
            dispositions.append(
                RowDisposition(
                    market_id=row.market_id,
                    print_id=print_id,
                    asset=str(row.asset),
                    status="lookahead",
                    reason="observed_at_ge_resolves_at",
                )
            )
            continue
        if row.wedge is None or row.poly_mid is None:
            n_non_ok += 1
            dispositions.append(
                RowDisposition(
                    market_id=row.market_id,
                    print_id=print_id,
                    asset=str(row.asset),
                    status="non_ok",
                    reason="missing_wedge_or_mid",
                )
            )
            continue
        if stand_aside(row.crucix_status):
            n_stand_aside += 1
            dispositions.append(
                RowDisposition(
                    market_id=row.market_id,
                    print_id=print_id,
                    asset=str(row.asset),
                    resolves_on=row.resolves_at.date(),
                    status="stand_aside",
                    reason=str(row.crucix_status),
                    wedge=row.wedge,
                )
            )
            continue
        if abs(row.wedge) < wedge_threshold:
            n_below += 1
            dispositions.append(
                RowDisposition(
                    market_id=row.market_id,
                    print_id=print_id,
                    asset=str(row.asset),
                    resolves_on=row.resolves_at.date(),
                    status="below_threshold",
                    wedge=row.wedge,
                )
            )
            continue
        settlement = settlements.get(row.market_id)
        if settlement is None:
            n_unsettled += 1
            dispositions.append(
                RowDisposition(
                    market_id=row.market_id,
                    print_id=print_id,
                    asset=str(row.asset),
                    resolves_on=row.resolves_at.date(),
                    status="unsettled",
                    reason="settlement_missing_skip_not_invent",
                    wedge=row.wedge,
                )
            )
            continue

        side = treatment_side(row.wedge)
        hs = half_spread_from_row(row)
        half_spread = hs if hs is not None else default_half_spread
        entry = conservative_entry(side, row.poly_mid, half_spread)
        fee = polymarket_taker_fee(entry) / SHARES_NOTIONAL  # per $1 notional
        won_yes = settlement.yes_won
        treat_won = won_yes if side == ContractSide.YES else (not won_yes)
        fade_side = ContractSide.NO if side == ContractSide.YES else ContractSide.YES
        fade_won = won_yes if fade_side == ContractSide.YES else (not won_yes)
        fade_entry = conservative_entry(fade_side, row.poly_mid, half_spread)
        fade_fee = polymarket_taker_fee(fade_entry) / SHARES_NOTIONAL
        mid_entry = row.poly_mid if side == ContractSide.YES else (1.0 - row.poly_mid)
        mid_fee = polymarket_taker_fee(mid_entry) / SHARES_NOTIONAL
        treat_pnl = realized_pnl(entry, won=treat_won, fee=fee)
        fade_pnl = realized_pnl(fade_entry, won=fade_won, fee=fade_fee)
        mid_pnl = realized_pnl(mid_entry, won=treat_won, fee=mid_fee)
        disp = RowDisposition(
            market_id=row.market_id,
            print_id=print_id,
            asset=str(row.asset),
            resolves_on=row.resolves_at.date(),
            status="would_trade",
            side=side,
            wedge=row.wedge,
            conservative_pnl=treat_pnl,
            fade_pnl=fade_pnl,
            midfill_pnl=mid_pnl,
            yes_resolved=won_yes,
        )
        dispositions.append(disp)
        eligible.append((row, disp))

    # Crucix subset invariant on the would-trade mask (documented; gate already applied).
    mask = tuple(True for _ in eligible)
    statuses = tuple(row.crucix_status for row, _ in eligible)
    gated = apply_crucix_gate(mask, statuses)
    assert gated == mask  # all eligible already clear

    n_would = len(eligible)
    treatment = sum(d.conservative_pnl or 0.0 for _, d in eligible)
    fade = sum(d.fade_pnl or 0.0 for _, d in eligible)
    midfill = sum(d.midfill_pnl or 0.0 for _, d in eligible)

    holdout_n = holdout_would = None
    holdout_vs_hold = holdout_vs_fade = None
    if len(eligible) >= MIN_ROWS_FOR_HOLDOUT:
        ordered = sorted(
            eligible,
            key=lambda pair: (pair[0].resolves_at, pair[0].market_id),
        )
        cut = max(1, int(len(ordered) * (1.0 - holdout_fraction)))
        holdout = ordered[cut:]
        holdout_n = len(holdout)
        holdout_would = len(holdout)
        holdout_vs_hold = sum(d.conservative_pnl or 0.0 for _, d in holdout)
        holdout_vs_fade = holdout_vs_hold - sum(d.fade_pnl or 0.0 for _, d in holdout)

    fail_closed: str | None = None
    if not rows:
        fail_closed = "empty_print"
    elif n_would == 0 and n_unsettled > 0 and n_stand_aside + n_below == 0:
        fail_closed = "no_settlements_skip_not_invent"
    elif n_would == 0:
        fail_closed = "no_eligible_trades"
    elif n_would < MIN_TRADES_PER_PRINT:
        fail_closed = "below_min_trades"
    elif n_would < MIN_ROWS_PER_PRINT:
        fail_closed = "below_min_eligible"

    metrics = PrintMetrics(
        print_id=print_id,
        n_rows=len(rows),
        n_decision=sum(1 for r in rows if r.status is WedgeRowStatus.OK),
        n_lookahead=n_lookahead,
        n_non_ok=n_non_ok,
        n_stand_aside=n_stand_aside,
        n_below_threshold=n_below,
        n_unsettled=n_unsettled,
        n_eligible=n_would,
        n_would_trade=n_would,
        treatment_pnl=treatment,
        fade_pnl=fade,
        hold_pnl=0.0,
        midfill_treatment_pnl=midfill,
        treatment_excess_vs_hold=treatment,
        treatment_excess_vs_fade=treatment - fade,
        holdout_n=holdout_n,
        holdout_would_trade=holdout_would,
        holdout_treatment_excess_vs_hold=holdout_vs_hold,
        holdout_treatment_excess_vs_fade=holdout_vs_fade,
        fail_closed_reason=fail_closed,
        hedged_status="skipped_not_invented",
    )
    return metrics, dispositions


def run_crypto_wedge_eval(
    prints: dict[str, tuple[CryptoWedgeRow, ...]],
    settlements_by_print: dict[str, tuple[SettlementRow, ...]] | None = None,
    *,
    wedge_threshold: float = PREREGISTERED_WEDGE_THRESHOLD,
    holdout_fraction: float = DEFAULT_HOLDOUT_FRACTION,
    default_half_spread: float = 0.01,
    data_notes: list[str] | None = None,
) -> CryptoWedgeEvalReport:
    settlements_by_print = settlements_by_print or {}
    notes = list(data_notes or [])
    metrics_list: list[PrintMetrics] = []
    all_disp: list[RowDisposition] = []
    decision_prints: dict[str, tuple[CryptoWedgeRow, ...]] = {}

    for print_id, rows in prints.items():
        decisions = decision_rows(rows) if rows else ()
        # If caller already passed decision-only rows, decision_rows is idempotent.
        if not decisions and rows:
            decisions = ()
        decision_prints[print_id] = decisions if decisions else rows
        sett_map = {s.market_id: s for s in settlements_by_print.get(print_id, ())}
        # Also accept settlements keyed under any print for single-pack runs.
        if not sett_map:
            for pack in settlements_by_print.values():
                for s in pack:
                    sett_map.setdefault(s.market_id, s)
        scored_rows = decisions if decisions else rows
        metrics, disp = _score_print(
            scored_rows,
            sett_map,
            print_id=print_id,
            wedge_threshold=wedge_threshold,
            holdout_fraction=holdout_fraction,
            default_half_spread=default_half_spread,
        )
        metrics_list.append(metrics)
        all_disp.extend(disp)

    print_ids = list(prints.keys())
    independent = False
    independence_reason = "fewer_than_two_prints"
    if len(print_ids) >= 2:
        a, b = print_ids[0], print_ids[1]
        independent, independence_reason = prints_independent(
            decision_prints.get(a, ()),
            decision_prints.get(b, ()),
            settlements_by_print.get(a, ()),
            settlements_by_print.get(b, ()),
        )
    print_kind: Literal["single_print", "dual_print"] = (
        PRINT_DUAL if independent and len(print_ids) >= 2 else PRINT_SINGLE
    )
    notes.append(
        "Primary metric is unhedged Polymarket conservative PnL after frozen "
        "taker fee. Hedged Deribit path skipped_not_invented without option fills."
    )
    notes.append(f"{DEFAULT_PROMOTE_FLAG} is not a Settings field; can_promote stays false.")
    return CryptoWedgeEvalReport(
        print_kind=print_kind,
        independent=independent,
        independence_reason=independence_reason,
        can_promote=False,
        can_enter_promotion_average=CAN_ENTER_PROMOTION_AVERAGE,
        keep_flag_false=True,
        recommended_promote_flag="none",
        holdout_fraction=holdout_fraction,
        wedge_threshold=wedge_threshold,
        prints=metrics_list,
        notes=notes,
        dispositions=all_disp,
    )


def empty_live_report(
    *,
    holdout_fraction: float = DEFAULT_HOLDOUT_FRACTION,
    wedge_threshold: float = PREREGISTERED_WEDGE_THRESHOLD,
    extra_notes: list[str] | None = None,
) -> CryptoWedgeEvalReport:
    notes = [
        "Live / historical settled PIT tape: UNAVAILABLE in this environment.",
        "No point-in-time CryptoWedgeRow tape + settlement pack was supplied.",
        "Empty print is the successful outcome. Do not invent fills or settlements.",
        "TRADING_MODE=paper; report-only; venue_submitted=false",
    ]
    if extra_notes:
        notes.extend(extra_notes)
    metrics = PrintMetrics(
        print_id="live_historical",
        fail_closed_reason="empty_print",
        hedged_status="skipped_not_invented",
    )
    return CryptoWedgeEvalReport(
        print_kind=PRINT_SINGLE,
        independent=False,
        independence_reason="fewer_than_two_prints",
        can_promote=False,
        keep_flag_false=True,
        holdout_fraction=holdout_fraction,
        wedge_threshold=wedge_threshold,
        prints=[metrics],
        notes=notes,
    )


def render_crypto_wedge_eval_markdown(report: CryptoWedgeEvalReport) -> str:
    lines: list[str] = [
        "# Polymarket crypto-threshold vs Deribit — fee-aware evaluation",
        "",
        (
            "Report-only. Not a live-capital claim. Not a reason to flip "
            "`PAPER_PROMOTE_*` or `TRADING_MODE`. An empty or negative result is success."
        ),
        "",
        "## What this does / does not claim",
        "",
        (
            "This CLI scores the pre-registered #142 wedge rule "
            f"(`|wedge| >= {report.wedge_threshold}` + Crucix clear) after "
            "conservative Polymarket taker fees. It is **not** a validated wedge "
            "edge, not an arbitrage (expiry_gap_hours), and not a CLOB/Deribit "
            "trading path. Hedged PnL is skipped unless option fill inputs exist."
        ),
        "",
        "## Honesty / pre-registered rules",
        "",
        (
            "Frozen in `crypto_models.CRYPTO_WEDGE_RULES` and "
            "`docs/artifacts/strategy-search/polymarket-crypto-wedge-eval-recipe.md` "
            "before scoring. Settlement is never a mid. "
            f"`{report.promote_flag_name}` is not a Settings field. "
            "Every existing `PAPER_PROMOTE_*` stays default false. No live. "
            "Empty / negative is success."
        ),
        "",
        "## Print policy (frozen before scoring)",
        "",
        "| print | when | can promote? |",
        "| --- | --- | --- |",
        "| single-print | fewer than two independent packs | **no** |",
        (
            "| dual-print | BTC vs ETH or non-overlapping dates / "
            "disjoint resolution sources; each clears calculator floor | still **no** Settings flip |"
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
            f"- wedge_threshold={report.wedge_threshold}; "
            f"model={report.model_version}; "
            f"holdout_fraction={report.holdout_fraction:.0%}; "
            f"MIN_ROWS_PER_PRINT={MIN_ROWS_PER_PRINT}; "
            f"MIN_TRADES_PER_PRINT={MIN_TRADES_PER_PRINT}."
        ),
        (f"- multi_print_bar_preregistered={str(report.multi_print_bar_preregistered).lower()}."),
        "",
        "## Data",
        "",
    ]
    for note in report.notes:
        lines.append(f"- {note}")
    lines.extend(["", "## Prints", ""])
    for m in report.prints:
        lines.append(f"### `{m.print_id}`")
        lines.append("")
        lines.append(
            f"rows={m.n_rows} decision={m.n_decision} would_trade={m.n_would_trade} "
            f"stand_aside={m.n_stand_aside} below_threshold={m.n_below_threshold} "
            f"unsettled={m.n_unsettled} lookahead={m.n_lookahead} non_ok={m.n_non_ok}."
        )
        lines.append(
            f"Conservative treatment PnL (probability points, $1 notional): "
            f"{m.treatment_pnl:+.4f} vs hold {m.treatment_excess_vs_hold:+.4f} "
            f"vs fade {m.treatment_excess_vs_fade:+.4f}. "
            f"Mid-fill treatment (cannot promote): {m.midfill_treatment_pnl:+.4f}."
        )
        if m.holdout_n is None:
            lines.append("Holdout: fail-closed (insufficient eligible rows).")
        else:
            lines.append(
                f"Holdout n={m.holdout_n} would_trade={m.holdout_would_trade}: "
                f"excess vs hold {m.holdout_treatment_excess_vs_hold:+.4f} "
                f"vs fade {m.holdout_treatment_excess_vs_fade:+.4f}."
            )
        lines.append(
            f"Fail-closed reason: `{m.fail_closed_reason or 'none'}`. "
            f"Hedged: `{m.hedged_status}`. "
            f"clears_calculator={str(print_clears_calculator(m)).lower()}."
        )
        lines.append("")
    lines.extend(
        [
            "## Promotion decision",
            "",
            (
                "**No candidate is promoted.** "
                f"print_kind=`{report.print_kind}`; "
                f"can_promote=`{str(report.can_promote).lower()}`; "
                f"can_enter_promotion_average=`{str(report.can_enter_promotion_average).lower()}`; "
                f"keep_flag_false=`{str(report.keep_flag_false).lower()}`; "
                f"recommended_promote_flag=`{report.recommended_promote_flag}`. "
                f"`{report.promote_flag_name}` is not a Settings field. "
                "Leave every `PAPER_PROMOTE_*` false. Do not enable live."
            ),
            "",
        ]
    )
    return "\n".join(lines)
