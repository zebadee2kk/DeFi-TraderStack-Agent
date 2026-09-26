"""fund_z flip-cost / >=N-day hold-gate dual-print (NEW ids).

Re-scores sign_hold / always-harvest under an explicit flip-cost gate:
enter only when N * |rate| covers open fees (N from #183 BE table).
Optional sticky min-hold. Dual HL x HTX + required dual_basis.
Never flips PAPER_PROMOTE_*. Honesty: filtered sign_hold is not a new edge.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from traderstack.research.funding_carry import (
    CARRY_LEGS,
    HARD_GATE_MIN_DAILY_BARS,
    REQUIRED_SYMBOLS,
    choose_walkforward,
    evaluate_carry_hard_gates,
    utc_day_open,
)
from traderstack.research.harder_gates import paper_promote_flag_name

FAMILY = "fund_z_flipcost"
DEFAULT_FEE_BPS = 5.0
DEFAULT_SLIPPAGE_BPS = 5.0
HOLDOUT_FRACTION = 0.20
# N from #183 BE table (ceil mean days-to-BE)
N_RESEARCH_BE = 3  # ceil(2.7) @ research 5+5 x 2
N_PAPER_BE = 5  # ceil(4.1) @ paper 10+5 x 2
PAPER_PATH_READY = True
EXECUTABLE_NOTE = (
    "paper-perp flip-cost hold-gate; conceptually via PAPER_PERP_HEDGE; "
    "this CLI does not flip PAPER_PERP_HEDGE or PAPER_PROMOTE_*; not Kraken-spot"
)
FLIPCOST_RULES = (
    "Pre-registered fund_z flip-cost / >=N-day hold-gate dual-print "
    "(frozen before score). N in {3,5} from #183 BE table. Enter when "
    "N*|rate| >= open_cost; sticky ids keep min_hold=N. Dual HL x HTX + "
    "required dual_basis OKX x Binance Vision. Fee 5+5 bps x 2 legs. "
    "NEW ids distinct from fund_z_harvest_*. Honesty: unfiltered "
    "sign_hold_ref passer is not a new edge. PAPER_PROMOTE_* stays false. "
    "Empty set success."
)

# (id, label, mode, n_days, sticky, is_control)
# mode: magnitude | sign_hold | flat
FLIPCOST_CATALOG: tuple[tuple[str, str, str, int | None, bool, bool], ...] = (
    (
        "fund_z_flipcost_be3d",
        "magnitude enter N=3; exit when gate fails",
        "magnitude",
        N_RESEARCH_BE,
        False,
        False,
    ),
    (
        "fund_z_flipcost_be5d",
        "magnitude enter N=5; exit when gate fails",
        "magnitude",
        N_PAPER_BE,
        False,
        False,
    ),
    (
        "fund_z_flipcost_be3d_sticky",
        "N=3 magnitude enter + min_hold=3",
        "magnitude",
        N_RESEARCH_BE,
        True,
        False,
    ),
    (
        "fund_z_flipcost_be5d_sticky",
        "N=5 magnitude enter + min_hold=5",
        "magnitude",
        N_PAPER_BE,
        True,
        False,
    ),
    (
        "fund_z_flipcost_sign_hold_ref",
        "unfiltered always-harvest reference (honesty baseline)",
        "sign_hold",
        None,
        False,
        False,
    ),
    (
        "fund_z_flipcost_flat",
        "always-flat control",
        "flat",
        None,
        False,
        True,
    ),
)
FLIPCOST_IDS: tuple[str, ...] = tuple(item[0] for item in FLIPCOST_CATALOG)
CONTROL_IDS = frozenset(item[0] for item in FLIPCOST_CATALOG if item[5])


def _lookup(
    mapping: dict[str, tuple[tuple[datetime, float], ...]] | None, symbol: str
) -> tuple[tuple[datetime, float], ...] | None:
    if not mapping:
        return None
    key = symbol.upper()
    for name, series in mapping.items():
        if name.upper() == key:
            return series
    return None


def _compound(returns: list[float]) -> float:
    equity = 1.0
    for item in returns:
        equity *= 1.0 + item
    return equity - 1.0


def _open_cost(fee_bps: float, slippage_bps: float, legs: int = CARRY_LEGS) -> float:
    return legs * (fee_bps + slippage_bps) / 10_000.0


def _want_raw(
    history: list[float],
    *,
    mode: str,
    n_days: int | None,
    open_cost: float,
) -> bool:
    if mode == "flat":
        return False
    if not history:
        return False
    if mode == "sign_hold":
        return True
    # magnitude gate: N * |last_rate| >= open_cost
    assert n_days is not None and n_days > 0
    return n_days * abs(history[-1]) >= open_cost


def _flipcost_per_print(
    series: tuple[tuple[datetime, float], ...],
    *,
    mode: str,
    n_days: int | None,
    sticky: bool,
    fee_bps: float,
    slippage_bps: float,
    legs: int = CARRY_LEGS,
    basis: tuple[tuple[datetime, float], ...] | None = None,
) -> tuple[list[float], int, int, float]:
    """Return (per_print, flips, basis_days, mean_hold_when_closed)."""
    cost = _open_cost(fee_bps, slippage_bps, legs=legs)
    basis_by_ts = {utc_day_open(ts): value for ts, value in (basis or ())}
    position = False
    flips = 0
    basis_days = 0
    prev_basis: float | None = None
    held = 0
    hold_lengths: list[int] = []
    per_print: list[float] = []
    min_hold = n_days if sticky and n_days is not None else 0
    for index, (ts, rate) in enumerate(series):
        history = [value for _when, value in series[:index]]
        raw = _want_raw(history, mode=mode, n_days=n_days, open_cost=cost)
        if position:
            # sticky: refuse exit until held >= min_hold
            want = True if held < min_hold else raw
        else:
            want = raw
        income = 0.0
        fee = 0.0
        basis_pnl = 0.0
        if want != position:
            fee = cost
            flips += 1
            if position and held > 0:
                hold_lengths.append(held)
            position = want
            held = 1 if want else 0
            if not want:
                prev_basis = None
        elif position:
            held += 1
        if position:
            income = abs(rate)
            current_basis = basis_by_ts.get(utc_day_open(ts))
            if prev_basis is not None and current_basis is not None:
                basis_pnl = prev_basis - current_basis
                basis_days += 1
            if current_basis is not None:
                prev_basis = current_basis
        per_print.append(income - fee + basis_pnl)
    if position and held > 0:
        hold_lengths.append(held)
    mean_hold = sum(hold_lengths) / len(hold_lengths) if hold_lengths else 0.0
    return per_print, flips, basis_days, mean_hold


def score_flipcost(
    series: tuple[tuple[datetime, float], ...],
    *,
    mode: str,
    n_days: int | None,
    sticky: bool,
    fee_bps: float,
    slippage_bps: float,
    holdout_fraction: float = HOLDOUT_FRACTION,
    basis: tuple[tuple[datetime, float], ...] | None = None,
) -> dict[str, float | int | str | None]:
    per_print, flips, basis_days, mean_hold = _flipcost_per_print(
        series,
        mode=mode,
        n_days=n_days,
        sticky=sticky,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
        basis=basis,
    )
    if len(per_print) < 2:
        return {
            "print_count": len(series),
            "flips": flips,
            "mean_hold_days": mean_hold,
            "skipped_reason": "funding tape too short to score",
            "mean_wf_total_return": None,
            "mean_holdout_excess_return": None,
            "basis_days_applied": basis_days,
        }
    holdout_size = max(int(len(per_print) * holdout_fraction), 1)
    if holdout_size >= len(per_print):
        holdout_size = max(1, len(per_print) // 5)
    research = per_print[:-holdout_size]
    holdout = per_print[-holdout_size:]
    sizes = choose_walkforward(len(research))
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
        "print_count": len(series),
        "research_prints": len(research),
        "holdout_prints": len(holdout),
        "flips": flips,
        "mean_hold_days": mean_hold,
        "skipped_reason": None if fold_totals else "walkforward_insufficient_prints",
        "mean_wf_total_return": wf_mean,
        "mean_wf_excess_return": wf_mean,
        "mean_holdout_total_return": holdout_total,
        "mean_holdout_excess_return": holdout_total,
        "full_sample_total_return": _compound(per_print),
        "fold_count": len(fold_totals),
        "basis_days_applied": basis_days,
        "basis_modeled": bool(basis) and basis_days > 0,
        "open_cost": _open_cost(fee_bps, slippage_bps),
    }


def _asset_sign(metrics: dict[str, float | int | str | None], key: str) -> bool:
    value = metrics.get(key)
    return isinstance(value, float) and value > 0


def _eligible(metrics_by_symbol: dict[str, dict[str, float | int | str | None]]) -> bool:
    btc = metrics_by_symbol.get("BTC/USD") or {}
    eth = metrics_by_symbol.get("ETH/USD") or {}
    return all(
        _asset_sign(btc, key) and _asset_sign(eth, key)
        for key in ("mean_wf_total_return", "mean_holdout_excess_return")
    )


class FlipcostCandidate(BaseModel):
    candidate_id: str
    family: str = FAMILY
    label: str
    is_control: bool = False
    per_asset: dict[str, dict[str, float | int | str | None]] = Field(default_factory=dict)
    mean_wf_total_return: float | None = None
    mean_holdout_excess_return: float | None = None
    mean_hold_days: float | None = None
    eligible: bool = False
    basis_modeled: bool = False
    executable: str = EXECUTABLE_NOTE


class FundZFlipcostReport(BaseModel):
    generated_at: datetime
    print_kind: Literal["single_print", "dual_print", "unavailable"]
    primary_funding_venue: str = "hyperliquid"
    second_funding_venue: str | None = "htx"
    primary_basis_venue: str = "okx"
    second_basis_venue: str | None = "binance_vision"
    dual_basis_required: bool = True
    dual_basis_available: bool = False
    fee_bps: float
    slippage_bps: float
    n_research_be: int = N_RESEARCH_BE
    n_paper_be: int = N_PAPER_BE
    keep_flag_false: bool = True
    can_promote: bool = False
    paper_path_ready: bool = PAPER_PATH_READY
    executable_note: str = EXECUTABLE_NOTE
    core_ids: list[str] = Field(default_factory=lambda: list(FLIPCOST_IDS))
    dual_print_passer_ids: list[str] = Field(default_factory=list)
    dual_print_passers: int = 0
    honesty_note: str = (
        "If only fund_z_flipcost_sign_hold_ref passes, that is the known "
        "sign_hold shape under a NEW id — not a new edge. Magnitude/sticky "
        "gates are filters on the same harvest family."
    )
    structurally_fee_survivable_ge_3d: bool = False
    rules: str = FLIPCOST_RULES
    history_notes: list[dict[str, str]] = Field(default_factory=list)
    primary: list[FlipcostCandidate] = Field(default_factory=list)
    second: list[FlipcostCandidate] = Field(default_factory=list)
    primary_hard_gates_note: str | None = None
    second_hard_gates_note: str | None = None
    recommended_promote_flag: str | None = None
    recipe_commit: str | None = None

    def model_dump_json_safe(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


def _score_catalog(
    funding_by_symbol: dict[str, tuple[tuple[datetime, float], ...]],
    basis_by_symbol: dict[str, tuple[tuple[datetime, float], ...]],
    *,
    fee_bps: float,
    slippage_bps: float,
) -> list[FlipcostCandidate]:
    out: list[FlipcostCandidate] = []
    for candidate_id, label, mode, n_days, sticky, is_control in FLIPCOST_CATALOG:
        per_asset: dict[str, dict[str, float | int | str | None]] = {}
        basis_days = 0
        hold_vals: list[float] = []
        for symbol in REQUIRED_SYMBOLS:
            series = _lookup(funding_by_symbol, symbol)
            basis = _lookup(basis_by_symbol, symbol)
            if series is None:
                per_asset[symbol] = {"skipped_reason": "missing funding"}
                continue
            metrics = score_flipcost(
                series,
                mode=mode,
                n_days=n_days,
                sticky=sticky,
                fee_bps=fee_bps,
                slippage_bps=slippage_bps,
                basis=basis,
            )
            per_asset[symbol] = metrics
            bd = metrics.get("basis_days_applied")
            if isinstance(bd, int):
                basis_days += bd
            mh = metrics.get("mean_hold_days")
            if isinstance(mh, float):
                hold_vals.append(mh)
        btc = per_asset.get("BTC/USD") or {}
        eth = per_asset.get("ETH/USD") or {}
        wf_vals: list[float] = []
        ho_vals: list[float] = []
        for asset_metrics in (btc, eth):
            wf_raw = asset_metrics.get("mean_wf_total_return")
            if isinstance(wf_raw, float):
                wf_vals.append(wf_raw)
            ho_raw = asset_metrics.get("mean_holdout_excess_return")
            if isinstance(ho_raw, float):
                ho_vals.append(ho_raw)
        eligible = False if is_control else _eligible(per_asset)
        out.append(
            FlipcostCandidate(
                candidate_id=candidate_id,
                label=label,
                is_control=is_control,
                per_asset=per_asset,
                mean_wf_total_return=(sum(wf_vals) / len(wf_vals) if wf_vals else None),
                mean_holdout_excess_return=(sum(ho_vals) / len(ho_vals) if ho_vals else None),
                mean_hold_days=(sum(hold_vals) / len(hold_vals) if hold_vals else None),
                eligible=eligible,
                basis_modeled=basis_days > 0,
            )
        )
    return out


def _basis_ok(
    mapping: dict[str, tuple[tuple[datetime, float], ...]],
    *,
    min_days: int = HARD_GATE_MIN_DAILY_BARS,
) -> bool:
    for symbol in REQUIRED_SYMBOLS:
        series = _lookup(mapping, symbol)
        if series is None or len(series) < min_days:
            return False
    return True


def run_fund_z_flipcost(
    *,
    hl_funding: dict[str, tuple[tuple[datetime, float], ...]],
    htx_funding: dict[str, tuple[tuple[datetime, float], ...]],
    okx_basis: dict[str, tuple[tuple[datetime, float], ...]],
    vision_basis: dict[str, tuple[tuple[datetime, float], ...]],
    fee_bps: float = DEFAULT_FEE_BPS,
    slippage_bps: float = DEFAULT_SLIPPAGE_BPS,
    history_notes: list[dict[str, str]] | None = None,
    recipe_commit: str | None = None,
    now: datetime | None = None,
) -> FundZFlipcostReport:
    generated = now or datetime.now(UTC)
    notes = list(history_notes or [])
    dual_basis = _basis_ok(okx_basis) and _basis_ok(vision_basis)
    if not dual_basis:
        notes.append(
            {
                "name": "dual_basis",
                "status": "skipped",
                "reason": "dual_basis required; missing or short OKX/Vision series",
            }
        )
        return FundZFlipcostReport(
            generated_at=generated,
            print_kind="unavailable",
            second_funding_venue=None,
            second_basis_venue=None,
            dual_basis_available=False,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            history_notes=notes,
            recipe_commit=recipe_commit,
        )

    def funding_ok(mapping: dict[str, tuple[tuple[datetime, float], ...]]) -> bool:
        for symbol in REQUIRED_SYMBOLS:
            series = _lookup(mapping, symbol)
            if series is None or len(series) < HARD_GATE_MIN_DAILY_BARS:
                return False
        return True

    if not funding_ok(hl_funding) or not funding_ok(htx_funding):
        notes.append(
            {
                "name": "funding_dual",
                "status": "skipped",
                "reason": "HL and HTX each need >=720 daily funding points on BTC+ETH",
            }
        )
        return FundZFlipcostReport(
            generated_at=generated,
            print_kind="unavailable",
            second_funding_venue=None,
            dual_basis_available=True,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            history_notes=notes,
            recipe_commit=recipe_commit,
        )

    primary = _score_catalog(hl_funding, okx_basis, fee_bps=fee_bps, slippage_bps=slippage_bps)
    second = _score_catalog(htx_funding, vision_basis, fee_bps=fee_bps, slippage_bps=slippage_bps)
    primary_ok = {c.candidate_id for c in primary if c.eligible}
    second_ok = {c.candidate_id for c in second if c.eligible}
    passers = sorted(primary_ok & second_ok)

    # Structurally fee-survivable at >=3d: a non-ref magnitude/sticky passer
    # with mean_hold_days >= 3 on both prints (averaged across assets).
    ge3_ids = {
        "fund_z_flipcost_be3d",
        "fund_z_flipcost_be5d",
        "fund_z_flipcost_be3d_sticky",
        "fund_z_flipcost_be5d_sticky",
    }
    structurally = False
    for pid in passers:
        if pid not in ge3_ids:
            continue
        p = next(c for c in primary if c.candidate_id == pid)
        s = next(c for c in second if c.candidate_id == pid)
        if (
            p.mean_hold_days is not None
            and s.mean_hold_days is not None
            and p.mean_hold_days >= 3.0
            and s.mean_hold_days >= 3.0
        ):
            structurally = True
            break

    primary_gates = evaluate_carry_hard_gates(
        hl_funding,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
        holdout_fraction=HOLDOUT_FRACTION,
        candidate_id="fund_z_flipcost_sign_hold_ref",
        basis_by_symbol=okx_basis,
    )
    second_gates = evaluate_carry_hard_gates(
        htx_funding,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
        holdout_fraction=HOLDOUT_FRACTION,
        candidate_id="fund_z_flipcost_sign_hold_ref",
        basis_by_symbol=vision_basis,
    )

    return FundZFlipcostReport(
        generated_at=generated,
        print_kind="dual_print",
        dual_basis_available=True,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
        dual_print_passer_ids=passers,
        dual_print_passers=len(passers),
        structurally_fee_survivable_ge_3d=structurally,
        history_notes=notes,
        primary=primary,
        second=second,
        primary_hard_gates_note=primary_gates.note,
        second_hard_gates_note=second_gates.note,
        can_promote=False,
        keep_flag_false=True,
        recipe_commit=recipe_commit,
        recommended_promote_flag=(
            paper_promote_flag_name("fund_z_flipcost_sign_hold_ref")
            if "fund_z_flipcost_sign_hold_ref" in passers and not structurally
            else (paper_promote_flag_name(passers[0]) if passers and structurally else None)
        ),
    )


def _pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.2f}%"


def _hold(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.1f}d"


def render_fund_z_flipcost_markdown(report: FundZFlipcostReport) -> str:
    lines = [
        "# fund_z flip-cost / >=N-day hold-gate dual-print",
        "",
        f"Generated: {report.generated_at.isoformat()}",
        (
            f"Recipe commit: `{report.recipe_commit or 'unpinned'}`. "
            f"Print kind: **{report.print_kind}**. funding=`{report.primary_funding_venue}` x "
            f"`{report.second_funding_venue or 'none'}`; basis=`{report.primary_basis_venue}` x "
            f"`{report.second_basis_venue or 'none'}`; "
            f"dual_basis_available=`{str(report.dual_basis_available).lower()}`; "
            f"N_research={report.n_research_be}; N_paper={report.n_paper_be}; "
            f"can_promote=`{str(report.can_promote).lower()}`; "
            f"keep_flag_false=`{str(report.keep_flag_false).lower()}`; "
            f"dual_print_passers=`{report.dual_print_passers}`; "
            f"structurally_fee_survivable_ge_3d=`{str(report.structurally_fee_survivable_ge_3d).lower()}`; "
            f"paper_path_ready=`{str(report.paper_path_ready).lower()}`"
        ),
        "",
        "## Rules",
        "",
        report.rules,
        "",
        f"Executability: {report.executable_note}",
        "",
        f"Fees: {report.fee_bps:g}+{report.slippage_bps:g} bps x {CARRY_LEGS} legs.",
        "",
        "## Honesty",
        "",
        report.honesty_note,
        "",
        "## History notes",
        "",
    ]
    for note in report.history_notes:
        lines.append(
            f"- `{note.get('name', '')}` **{note.get('status', '')}**: {note.get('reason', '')}"
        )
    lines.extend(["", "## Primary print (HL funding x OKX basis)", ""])
    lines.append("| id | WF total | holdout excess | mean hold | basis_modeled | eligible |")
    lines.append("| --- | ---: | ---: | ---: | :---: | :---: |")
    for row in report.primary:
        lines.append(
            f"| `{row.candidate_id}` | {_pct(row.mean_wf_total_return)} | "
            f"{_pct(row.mean_holdout_excess_return)} | {_hold(row.mean_hold_days)} | "
            f"{'yes' if row.basis_modeled else 'no'} | "
            f"{'yes' if row.eligible else 'no'} |"
        )
    if report.primary_hard_gates_note:
        lines.extend(["", f"Hard gates (sign_hold_ref): {report.primary_hard_gates_note}"])
    lines.extend(["", "## Second print (HTX funding x Binance Vision basis)", ""])
    lines.append("| id | WF total | holdout excess | mean hold | basis_modeled | eligible |")
    lines.append("| --- | ---: | ---: | ---: | :---: | :---: |")
    for row in report.second:
        lines.append(
            f"| `{row.candidate_id}` | {_pct(row.mean_wf_total_return)} | "
            f"{_pct(row.mean_holdout_excess_return)} | {_hold(row.mean_hold_days)} | "
            f"{'yes' if row.basis_modeled else 'no'} | "
            f"{'yes' if row.eligible else 'no'} |"
        )
    if report.second_hard_gates_note:
        lines.extend(["", f"Hard gates (sign_hold_ref): {report.second_hard_gates_note}"])
    lines.extend(
        [
            "",
            "## Dual-print passers",
            "",
            (
                ", ".join(f"`{i}`" for i in report.dual_print_passer_ids)
                if report.dual_print_passer_ids
                else "**0** dual-print passers."
            ),
            "",
            "## Fee-survivability (>=3d structural hold)",
            "",
            (
                f"structurally_fee_survivable_ge_3d=**{str(report.structurally_fee_survivable_ge_3d).lower()}** "
                "(magnitude/sticky passer with mean_hold_days >= 3 on both prints)."
            ),
            "",
            "## Promotion decision",
            "",
            (
                "**No candidate is auto-enabled.** can_promote=false; "
                "keep_flag_false=true. Leave every PAPER_PROMOTE_*=false. "
                "No live path."
            ),
            "",
        ]
    )
    return "\n".join(lines)
