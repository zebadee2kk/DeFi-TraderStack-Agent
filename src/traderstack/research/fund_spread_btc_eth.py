"""BTC-ETH relative funding / funding-spread dual-print (HL x HTX).

Frozen fund_spread_btc_eth_* catalog. Concurrent Hyperliquid x HTX preferred.
Paper-perp fees 5+5 x CARRY_LEGS. Never flips PAPER_PROMOTE_*. Distinct from
fund_z_harvest / fund_div / fund_xs_rank / BTC-ETH price RV.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from traderstack.indicators import zscore
from traderstack.research.funding_carry import (
    CARRY_LEGS,
    HARD_GATE_MIN_DAILY_BARS,
    MIN_RESEARCH_BARS,
    SHORT_STEP_SIZE,
    SHORT_TEST_SIZE,
    SHORT_TRAIN_SIZE,
    Z_LOOKBACK,
    choose_walkforward,
    utc_day_open,
)
from traderstack.research.harder_gates import paper_promote_flag_name

FAMILY = "fund_spread_btc_eth"
DEFAULT_FEE_BPS = 5.0
DEFAULT_SLIPPAGE_BPS = 5.0
HOLDOUT_FRACTION = 0.20
PAPER_PATH_READY = True
EXECUTABLE_NOTE = (
    "paper-perp BTC-ETH funding-spread; conceptually via PAPER_PERP_HEDGE; "
    "this CLI does not flip PAPER_PERP_HEDGE or PAPER_PROMOTE_*; not Kraken-spot"
)
SPREAD_RULES = (
    "Pre-registered BTC-ETH relative funding / funding-spread dual-print "
    "(frozen before score). Concurrent HL x HTX preferred. Fees 5+5 bps x 2 "
    "legs. Distinct from fund_z_harvest / fund_div / fund_xs_rank / price RV. "
    "PAPER_PROMOTE_* stays false. Empty set success."
)

# (id, label, z_threshold, demean, is_control)
SPREAD_CATALOG: tuple[tuple[str, str, float | None, bool, bool], ...] = (
    ("fund_spread_btc_eth_sign_hold", "always harvest sign(f_BTC-f_ETH)", None, False, False),
    ("fund_spread_btc_eth_z_1_0", "harvest when |z(spread)|>=1.0", 1.0, False, False),
    ("fund_spread_btc_eth_z_1_5", "harvest when |z(spread)|>=1.5", 1.5, False, False),
    ("fund_spread_btc_eth_z_2_0", "harvest when |z(spread)|>=2.0", 2.0, False, False),
    ("fund_spread_btc_eth_demean_sign", "demean then sign-harvest residual", None, True, False),
    ("fund_spread_btc_eth_flat", "always-flat control", None, False, True),
)
SPREAD_IDS: tuple[str, ...] = tuple(item[0] for item in SPREAD_CATALOG)
CONTROL_IDS = frozenset(item[0] for item in SPREAD_CATALOG if item[4])


def _lookup(
    mapping: dict[str, tuple[tuple[datetime, float], ...]] | None, symbol: str
) -> tuple[tuple[datetime, float], ...] | None:
    if not mapping:
        return None
    want = symbol.upper().replace("-", "/")
    for name, series in mapping.items():
        n = name.upper().replace("-", "/")
        if n == want or n.split("/")[0] == want.split("/")[0]:
            return series
    return None


def align_btc_eth_spread(
    btc: tuple[tuple[datetime, float], ...],
    eth: tuple[tuple[datetime, float], ...],
) -> tuple[tuple[datetime, float, float, float], ...]:
    """Return (day, f_btc, f_eth, spread) on intersection. Skip-not-invent."""
    btc_map = {utc_day_open(ts): rate for ts, rate in btc}
    eth_map = {utc_day_open(ts): rate for ts, rate in eth}
    days = sorted(set(btc_map) & set(eth_map))
    return tuple((day, btc_map[day], eth_map[day], btc_map[day] - eth_map[day]) for day in days)


def _compound(returns: list[float]) -> float:
    equity = 1.0
    for item in returns:
        equity *= 1.0 + item
    return equity - 1.0


def _want_position(
    spread_history: list[float],
    *,
    z_threshold: float | None,
    demean: bool,
    lookback: int = Z_LOOKBACK,
) -> int:
    """+1 short BTC/long ETH, -1 long BTC/short ETH, 0 flat."""
    if not spread_history:
        return 0
    hist = list(spread_history)
    if demean:
        if len(hist) < lookback:
            return 0
        window = hist[-lookback:]
        signal = hist[-1] - (sum(window) / len(window))
    else:
        signal = hist[-1]
        if z_threshold is not None:
            if len(hist) < lookback:
                return 0
            window = hist[-lookback:]
            if abs(zscore(window[-1], window)) < z_threshold:
                return 0
    if signal > 0:
        return 1
    if signal < 0:
        return -1
    return 0


def spread_per_print(
    aligned: tuple[tuple[datetime, float, float, float], ...],
    *,
    z_threshold: float | None,
    demean: bool,
    is_control: bool,
    fee_bps: float,
    slippage_bps: float,
    legs: int = CARRY_LEGS,
) -> tuple[list[float], int]:
    cost = legs * (fee_bps + slippage_bps) / 10_000.0
    position = 0
    flips = 0
    per_print: list[float] = []
    spread_hist: list[float] = []
    for _day, f_btc, f_eth, spread in aligned:
        if is_control:
            want = 0
        else:
            want = _want_position(spread_hist, z_threshold=z_threshold, demean=demean)
        fee = 0.0
        if want != position:
            fee = cost
            flips += 1
            position = want
        if position == 0:
            income = 0.0
        else:
            w_btc = -position
            w_eth = position
            income = -w_btc * f_btc - w_eth * f_eth
        per_print.append(income - fee)
        spread_hist.append(spread)
    return per_print, flips


def score_spread_series(
    aligned: tuple[tuple[datetime, float, float, float], ...],
    *,
    z_threshold: float | None,
    demean: bool,
    is_control: bool,
    fee_bps: float,
    slippage_bps: float,
    holdout_fraction: float = HOLDOUT_FRACTION,
) -> dict[str, float | int | str | None]:
    per_print, flips = spread_per_print(
        aligned,
        z_threshold=z_threshold,
        demean=demean,
        is_control=is_control,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
    )
    if len(per_print) < 2:
        return {
            "print_count": len(aligned),
            "flips": flips,
            "skipped_reason": "aligned tape too short to score",
            "mean_wf_total_return": None,
            "mean_holdout_excess_return": None,
            "full_sample_total_return": None,
        }
    holdout_size = max(int(len(per_print) * holdout_fraction), 1)
    if holdout_size >= len(per_print):
        holdout_size = max(1, len(per_print) // 5)
    research = per_print[:-holdout_size]
    holdout = per_print[-holdout_size:]
    sizes = choose_walkforward(
        len(research),
        train_size=180,
        test_size=60,
        step_size=60,
        warmup=0,
    )
    # choose_walkforward falls back to SHORT_* when tape is short
    fold_totals: list[float] = []
    if sizes is not None:
        train, test, step, _warmup = sizes
        start = 0
        while True:
            test_start = start + train
            test_end = test_start + test
            if test_end > len(research):
                break
            fold_totals.append(_compound(research[test_start:test_end]))
            start += step
    holdout_total = _compound(holdout) if holdout else None
    wf_mean = sum(fold_totals) / len(fold_totals) if fold_totals else None
    return {
        "print_count": len(aligned),
        "research_prints": len(research),
        "holdout_prints": len(holdout),
        "flips": flips,
        "skipped_reason": None if fold_totals else "walkforward_insufficient_prints",
        "mean_wf_total_return": wf_mean,
        "mean_holdout_excess_return": holdout_total,
        "full_sample_total_return": _compound(per_print),
        "fold_count": len(fold_totals),
    }


class SpreadCandidate(BaseModel):
    candidate_id: str
    family: str = FAMILY
    label: str
    is_control: bool = False
    mean_wf_total_return: float | None = None
    mean_holdout_excess_return: float | None = None
    eligible: bool = False
    flips: int = 0
    print_count: int = 0
    skipped_reason: str | None = None


class FundSpreadReport(BaseModel):
    generated_at: datetime
    print_kind: Literal["single_print", "dual_print", "unavailable"]
    dual_mode: Literal["concurrent_venues", "dual_era", "none"] = "none"
    primary_funding_venue: str = "hyperliquid"
    second_funding_venue: str | None = "htx"
    fee_bps: float
    slippage_bps: float
    legs: int = CARRY_LEGS
    keep_flag_false: bool = True
    can_promote: bool = False
    paper_path_ready: bool = PAPER_PATH_READY
    executable_note: str = EXECUTABLE_NOTE
    core_ids: list[str] = Field(default_factory=lambda: list(SPREAD_IDS))
    dual_print_passer_ids: list[str] = Field(default_factory=list)
    dual_print_passers: int = 0
    rules: str = SPREAD_RULES
    history_notes: list[dict[str, str]] = Field(default_factory=list)
    coverage: dict[str, Any] = Field(default_factory=dict)
    primary: list[SpreadCandidate] = Field(default_factory=list)
    second: list[SpreadCandidate] = Field(default_factory=list)
    recommended_promote_flag: str | None = None

    def model_dump_json_safe(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


def _eligible_metrics(metrics: dict[str, float | int | str | None]) -> bool:
    wf = metrics.get("mean_wf_total_return")
    ho = metrics.get("mean_holdout_excess_return")
    return isinstance(wf, float) and wf > 0 and isinstance(ho, float) and ho > 0


def _score_catalog(
    aligned: tuple[tuple[datetime, float, float, float], ...],
    *,
    fee_bps: float,
    slippage_bps: float,
) -> list[SpreadCandidate]:
    out: list[SpreadCandidate] = []
    for candidate_id, label, z_thr, demean, is_control in SPREAD_CATALOG:
        metrics = score_spread_series(
            aligned,
            z_threshold=z_thr,
            demean=demean,
            is_control=is_control,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
        )
        eligible = (not is_control) and _eligible_metrics(metrics)
        out.append(
            SpreadCandidate(
                candidate_id=candidate_id,
                label=label,
                is_control=is_control,
                mean_wf_total_return=(
                    metrics["mean_wf_total_return"]
                    if isinstance(metrics["mean_wf_total_return"], float)
                    else None
                ),
                mean_holdout_excess_return=(
                    metrics["mean_holdout_excess_return"]
                    if isinstance(metrics["mean_holdout_excess_return"], float)
                    else None
                ),
                eligible=eligible,
                flips=int(metrics.get("flips") or 0),
                print_count=int(metrics.get("print_count") or 0),
                skipped_reason=(
                    str(metrics["skipped_reason"]) if metrics.get("skipped_reason") else None
                ),
            )
        )
    return out


def _coverage_ok(aligned: tuple[tuple[datetime, float, float, float], ...]) -> bool:
    if len(aligned) >= HARD_GATE_MIN_DAILY_BARS:
        return True
    return len(aligned) >= MIN_RESEARCH_BARS + max(1, int(MIN_RESEARCH_BARS * 0.2))


def run_fund_spread_btc_eth(
    hl_funding: dict[str, tuple[tuple[datetime, float], ...]],
    htx_funding: dict[str, tuple[tuple[datetime, float], ...]],
    *,
    fee_bps: float = DEFAULT_FEE_BPS,
    slippage_bps: float = DEFAULT_SLIPPAGE_BPS,
    history_notes: list[dict[str, str]] | None = None,
) -> FundSpreadReport:
    notes = list(history_notes or [])
    now = datetime.now(tz=UTC)

    hl_btc = _lookup(hl_funding, "BTC/USD")
    hl_eth = _lookup(hl_funding, "ETH/USD")
    htx_btc = _lookup(htx_funding, "BTC/USD")
    htx_eth = _lookup(htx_funding, "ETH/USD")

    hl_aligned = align_btc_eth_spread(hl_btc, hl_eth) if hl_btc and hl_eth else ()
    htx_aligned = align_btc_eth_spread(htx_btc, htx_eth) if htx_btc and htx_eth else ()

    coverage: dict[str, Any] = {
        "hl_btc_days": len(hl_btc or ()),
        "hl_eth_days": len(hl_eth or ()),
        "hl_aligned_days": len(hl_aligned),
        "htx_btc_days": len(htx_btc or ()),
        "htx_eth_days": len(htx_eth or ()),
        "htx_aligned_days": len(htx_aligned),
        "hl_span": (
            [hl_aligned[0][0].isoformat(), hl_aligned[-1][0].isoformat()] if hl_aligned else None
        ),
        "htx_span": (
            [htx_aligned[0][0].isoformat(), htx_aligned[-1][0].isoformat()] if htx_aligned else None
        ),
        "min_bars_preferred": HARD_GATE_MIN_DAILY_BARS,
        "short_train": SHORT_TRAIN_SIZE,
        "short_test": SHORT_TEST_SIZE,
        "short_step": SHORT_STEP_SIZE,
    }

    hl_ok = _coverage_ok(hl_aligned)
    htx_ok = _coverage_ok(htx_aligned)
    notes.append(
        {
            "name": "coverage_freeze",
            "status": "ok" if (hl_ok or htx_ok) else "skipped",
            "reason": (
                f"hl_aligned={len(hl_aligned)} ok={hl_ok}; "
                f"htx_aligned={len(htx_aligned)} ok={htx_ok}; "
                f"prefer concurrent={hl_ok and htx_ok}"
            ),
        }
    )

    if hl_ok and htx_ok:
        notes.append(
            {
                "name": "dual_print_cells",
                "status": "ok",
                "reason": "frozen concurrent hyperliquid x htx before PnL",
            }
        )
        primary = _score_catalog(hl_aligned, fee_bps=fee_bps, slippage_bps=slippage_bps)
        second = _score_catalog(htx_aligned, fee_bps=fee_bps, slippage_bps=slippage_bps)
        passers = sorted(
            {c.candidate_id for c in primary if c.eligible}
            & {c.candidate_id for c in second if c.eligible}
        )
        return FundSpreadReport(
            generated_at=now,
            print_kind="dual_print",
            dual_mode="concurrent_venues",
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            dual_print_passer_ids=passers,
            dual_print_passers=len(passers),
            history_notes=notes,
            coverage=coverage,
            primary=primary,
            second=second,
            recommended_promote_flag=(paper_promote_flag_name(passers[0]) if passers else None),
        )

    longer_name = "hyperliquid"
    longer = hl_aligned
    if len(htx_aligned) > len(hl_aligned):
        longer_name = "htx"
        longer = htx_aligned

    min_era = MIN_RESEARCH_BARS + max(1, int(MIN_RESEARCH_BARS * 0.2))
    if len(longer) < 2 * min_era:
        notes.append(
            {
                "name": "dual_era_fallback",
                "status": "skipped",
                "reason": (
                    f"concurrent insufficient and longer venue {longer_name} "
                    f"has only {len(longer)} aligned days"
                ),
            }
        )
        return FundSpreadReport(
            generated_at=now,
            print_kind="unavailable",
            dual_mode="none",
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            history_notes=notes,
            coverage=coverage,
            second_funding_venue=None,
        )

    mid = len(longer) // 2
    era_a = longer[:mid]
    era_b = longer[mid:]
    notes.append(
        {
            "name": "dual_era_freeze",
            "status": "ok",
            "reason": (
                f"venue={longer_name}; era_a={era_a[0][0].date()}->{era_a[-1][0].date()} "
                f"({len(era_a)}d); era_b={era_b[0][0].date()}->{era_b[-1][0].date()} "
                f"({len(era_b)}d); frozen before PnL"
            ),
        }
    )
    if not (_coverage_ok(era_a) and _coverage_ok(era_b)):
        notes.append(
            {
                "name": "dual_era_coverage",
                "status": "skipped",
                "reason": "one or both eras below min coverage after freeze",
            }
        )
        return FundSpreadReport(
            generated_at=now,
            print_kind="unavailable",
            dual_mode="none",
            primary_funding_venue=longer_name,
            second_funding_venue=None,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            history_notes=notes,
            coverage=coverage,
        )

    primary = _score_catalog(era_a, fee_bps=fee_bps, slippage_bps=slippage_bps)
    second = _score_catalog(era_b, fee_bps=fee_bps, slippage_bps=slippage_bps)
    passers = sorted(
        {c.candidate_id for c in primary if c.eligible}
        & {c.candidate_id for c in second if c.eligible}
    )
    return FundSpreadReport(
        generated_at=now,
        print_kind="dual_print",
        dual_mode="dual_era",
        primary_funding_venue=longer_name,
        second_funding_venue=longer_name,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
        dual_print_passer_ids=passers,
        dual_print_passers=len(passers),
        history_notes=notes,
        coverage=coverage,
        primary=primary,
        second=second,
        recommended_promote_flag=(paper_promote_flag_name(passers[0]) if passers else None),
    )


def _pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.2f}%"


def render_fund_spread_markdown(report: FundSpreadReport) -> str:
    lines = [
        "# BTC-ETH relative funding / funding-spread HL x HTX dual-print",
        "",
        f"Generated: {report.generated_at.isoformat()}",
        (
            f"Print kind: **{report.print_kind}**. dual_mode=`{report.dual_mode}`; "
            f"funding=`{report.primary_funding_venue}`"
            + (f" x `{report.second_funding_venue}`" if report.second_funding_venue else "")
            + f"; can_promote=`{str(report.can_promote).lower()}`; "
            f"keep_flag_false=`{str(report.keep_flag_false).lower()}`; "
            f"dual_print_passers=`{report.dual_print_passers}`; "
            f"paper_path_ready=`{str(report.paper_path_ready).lower()}`"
        ),
        "",
        "## Rules",
        "",
        report.rules,
        "",
        f"Executability: {report.executable_note}",
        "",
        f"Fees: {report.fee_bps:g}+{report.slippage_bps:g} bps x {report.legs} legs.",
        "",
        "## Coverage (frozen before PnL)",
        "",
        "```",
        str(report.coverage),
        "```",
        "",
        "## History notes",
        "",
    ]
    for note in report.history_notes:
        lines.append(f"- `{note.get('name')}` **{note.get('status')}**: {note.get('reason')}")
    lines.extend(["", f"## Primary (`{report.primary_funding_venue}`)", ""])
    lines.append("| id | WF total | holdout excess | flips | eligible | control |")
    lines.append("| --- | ---: | ---: | ---: | :---: | :---: |")
    for row in report.primary:
        lines.append(
            f"| `{row.candidate_id}` | {_pct(row.mean_wf_total_return)} | "
            f"{_pct(row.mean_holdout_excess_return)} | {row.flips} | "
            f"{'yes' if row.eligible else 'no'} | "
            f"{'yes' if row.is_control else 'no'} |"
        )
    if report.second:
        label = report.second_funding_venue or "second"
        lines.extend(["", f"## Second (`{label}`)", ""])
        lines.append("| id | WF total | holdout excess | flips | eligible | control |")
        lines.append("| --- | ---: | ---: | ---: | :---: | :---: |")
        for row in report.second:
            lines.append(
                f"| `{row.candidate_id}` | {_pct(row.mean_wf_total_return)} | "
                f"{_pct(row.mean_holdout_excess_return)} | {row.flips} | "
                f"{'yes' if row.eligible else 'no'} | "
                f"{'yes' if row.is_control else 'no'} |"
            )
    lines.extend(["", "## Dual-print passers", ""])
    if report.dual_print_passer_ids:
        lines.append(", ".join(f"`{i}`" for i in report.dual_print_passer_ids))
    else:
        lines.append(f"**{report.dual_print_passers}** dual-print passers.")
    lines.extend(
        [
            "",
            "## Promotion decision",
            "",
            (
                "**No candidate is auto-enabled.** "
                f"can_promote={str(report.can_promote).lower()}; "
                f"keep_flag_false={str(report.keep_flag_false).lower()}. "
                f"Recommended pin name (defaults false if added later): "
                f"`{report.recommended_promote_flag or 'n/a'}`. "
                "No live path. PAPER_PROMOTE_* untouched."
            ),
            "",
        ]
    )
    return "\n".join(lines)
