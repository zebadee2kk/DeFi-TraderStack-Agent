"""Basis residual / cash-and-carry residual dual-print (paper research).

Pre-registered catalog ``basis_resid_*``: mean-reversion (fade) and momentum
(follow) on PIT mark-index basis z, scored as residual PnL on OKX x Binance
Vision dual prints. Never flips ``PAPER_PROMOTE_*``. Skip-not-invent.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from traderstack.research.funding_carry import (
    CARRY_LEGS,
    DEFAULT_STEP_SIZE,
    DEFAULT_TEST_SIZE,
    DEFAULT_TRAIN_SIZE,
    HARD_GATE_MIN_DAILY_BARS,
    REQUIRED_SYMBOLS,
    Z_LOOKBACK,
    choose_walkforward,
)

BASIS_RESID_RULES = (
    "Pre-registered basis residual dual-print (frozen before score). "
    "Feature = PIT mark-index basis z (lookback=20); fade/follow at "
    "|z|>=1.0/1.5/2.0. Residual PnL: short-basis earns prev-current; "
    "long-basis earns current-prev; missing days skipped. Two-leg fees "
    "5+5 bps. Dual-print = OKX x Binance Vision. Research-only residual; "
    "not Kraken-spot. PAPER_PROMOTE_* stays false. Empty set is success."
)

BASIS_RESID_CATALOG: tuple[tuple[str, bool, float], ...] = (
    ("basis_resid_mr_fade_1_0", True, 1.0),
    ("basis_resid_mr_fade_1_5", True, 1.5),
    ("basis_resid_mr_fade_2_0", True, 2.0),
    ("basis_resid_mom_follow_1_0", False, 1.0),
    ("basis_resid_mom_follow_1_5", False, 1.5),
    ("basis_resid_mom_follow_2_0", False, 2.0),
)
BASIS_RESID_IDS: tuple[str, ...] = tuple(item[0] for item in BASIS_RESID_CATALOG)
CONTROL_IDS: frozenset[str] = frozenset({"ma_cross_10_30"})
CORE_IDS: tuple[str, ...] = BASIS_RESID_IDS + tuple(sorted(CONTROL_IDS))
DEFAULT_FEE_BPS = 5.0
DEFAULT_SLIPPAGE_BPS = 5.0
PAPER_PATH_READY = False
EXECUTABLE_NOTE = (
    "research-only residual PnL on PIT basis change; paper-perp related via "
    "PAPER_PERP_HEDGE for hedged carry but this catalog does not enable it; "
    "not Kraken-spot executable"
)


def _zscore(last: float, window: list[float]) -> float:
    if len(window) < 2:
        return 0.0
    mean = sum(window) / len(window)
    var = sum((x - mean) ** 2 for x in window) / len(window)
    std = math.sqrt(var)
    if std <= 0.0 or not math.isfinite(std):
        return 0.0
    return (last - mean) / std


def _compound(returns: list[float]) -> float:
    equity = 1.0
    for item in returns:
        equity *= 1.0 + item
    return equity - 1.0


def _position_from_z(*, z: float, fade: bool, entry_z: float) -> int:
    if abs(z) < entry_z:
        return 0
    if fade:
        return -1 if z >= entry_z else 1
    return 1 if z >= entry_z else -1


def score_basis_residual(
    series: tuple[tuple[datetime, float], ...],
    *,
    fade: bool,
    entry_z: float,
    fee_bps: float,
    slippage_bps: float,
    lookback: int = Z_LOOKBACK,
    legs: int = CARRY_LEGS,
    holdout_fraction: float = 0.20,
    train_size: int = DEFAULT_TRAIN_SIZE,
    test_size: int = DEFAULT_TEST_SIZE,
    step_size: int = DEFAULT_STEP_SIZE,
) -> dict[str, float | int | str | None]:
    cost = legs * (fee_bps + slippage_bps) / 10_000.0
    position = 0
    flips = 0
    residual_days = 0
    prev_basis: float | None = None
    per_print: list[float] = []
    for index, (_ts, value) in enumerate(series):
        history = [v for _when, v in series[:index]]
        window = history[-lookback:] if history else []
        z = _zscore(window[-1], window) if len(window) >= 2 else 0.0
        want = _position_from_z(z=z, fade=fade, entry_z=entry_z) if len(window) >= 2 else 0
        fee = 0.0
        pnl = 0.0
        if want != position:
            fee = cost
            flips += 1
            position = want
        if position != 0 and prev_basis is not None:
            delta = value - prev_basis
            pnl = delta if position > 0 else -delta
            residual_days += 1
        prev_basis = value
        per_print.append(pnl - fee)

    if len(per_print) < 2:
        return {
            "print_count": len(series),
            "flips": flips,
            "skipped_reason": "basis tape too short to score",
            "mean_wf_total_return": None,
            "mean_wf_excess_return": None,
            "mean_holdout_total_return": None,
            "mean_holdout_excess_return": None,
            "full_sample_total_return": None,
            "residual_days": residual_days,
        }

    holdout_size = max(int(len(per_print) * holdout_fraction), 1)
    if holdout_size >= len(per_print):
        holdout_size = max(1, len(per_print) // 5)
    research = per_print[:-holdout_size]
    holdout = per_print[-holdout_size:]
    sizes = choose_walkforward(
        len(research),
        train_size=train_size,
        test_size=test_size,
        step_size=step_size,
        warmup=0,
    )
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
        "skipped_reason": None if fold_totals else "walkforward_insufficient_prints",
        "mean_wf_total_return": wf_mean,
        "mean_wf_excess_return": wf_mean,
        "mean_holdout_total_return": holdout_total,
        "mean_holdout_excess_return": holdout_total,
        "full_sample_total_return": _compound(per_print),
        "fold_count": len(fold_totals),
        "residual_days": residual_days,
    }


def _asset_sign(metrics: dict[str, float | int | str | None], key: str) -> bool:
    value = metrics.get(key)
    return isinstance(value, float) and value > 0


def _eligible_asset(metrics: dict[str, float | int | str | None]) -> bool:
    return _asset_sign(metrics, "mean_wf_total_return") and _asset_sign(
        metrics, "mean_holdout_excess_return"
    )


class BasisResidCandidate(BaseModel):
    candidate_id: str
    family: str = "basis_resid"
    label: str
    fade: bool
    entry_z: float
    per_asset: dict[str, dict[str, float | int | str | None]] = Field(default_factory=dict)
    mean_wf_total_return: float | None = None
    mean_holdout_excess_return: float | None = None
    eligible: bool = False
    executable: str = EXECUTABLE_NOTE


class BasisResidReport(BaseModel):
    generated_at: datetime
    print_kind: Literal["single_print", "dual_print", "unavailable"]
    primary_basis_venue: str = "okx"
    second_basis_venue: str | None = "binance_vision"
    dual_basis_available: bool = False
    fee_bps: float
    slippage_bps: float
    keep_flag_false: bool = True
    can_promote: bool = False
    paper_path_ready: bool = PAPER_PATH_READY
    executable_note: str = EXECUTABLE_NOTE
    core_ids: list[str] = Field(default_factory=lambda: list(CORE_IDS))
    dual_print_passer_ids: list[str] = Field(default_factory=list)
    dual_print_passers: int = 0
    rules: str = BASIS_RESID_RULES
    history_notes: list[dict[str, str]] = Field(default_factory=list)
    primary: list[BasisResidCandidate] = Field(default_factory=list)
    second: list[BasisResidCandidate] = Field(default_factory=list)
    recommended_promote_flag: str | None = None

    def model_dump_json_safe(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


def _lookup(
    mapping: dict[str, tuple[tuple[datetime, float], ...]], symbol: str
) -> tuple[tuple[datetime, float], ...] | None:
    key = symbol.upper()
    for name, series in mapping.items():
        if name.upper() == key:
            return series
    return None


def dual_basis_gate(
    okx: dict[str, tuple[tuple[datetime, float], ...]],
    vision: dict[str, tuple[tuple[datetime, float], ...]],
    *,
    min_days: int = HARD_GATE_MIN_DAILY_BARS,
) -> tuple[bool, list[dict[str, str]]]:
    notes: list[dict[str, str]] = []
    ok = True
    for venue_name, mapping in (("okx", okx), ("binance_vision", vision)):
        for symbol in REQUIRED_SYMBOLS:
            series = _lookup(mapping, symbol)
            n = len(series) if series else 0
            status = "ok" if n >= min_days else "skipped"
            if n < min_days:
                ok = False
            notes.append(
                {
                    "name": f"{venue_name}_basis:{symbol}",
                    "status": status,
                    "reason": f"{n} daily points (need >={min_days})",
                    "points": str(n),
                }
            )
    return ok, notes


def _score_catalog(
    basis_by_symbol: dict[str, tuple[tuple[datetime, float], ...]],
    *,
    fee_bps: float,
    slippage_bps: float,
) -> list[BasisResidCandidate]:
    out: list[BasisResidCandidate] = []
    for candidate_id, fade, entry_z in BASIS_RESID_CATALOG:
        verb = "fade" if fade else "follow"
        per_asset: dict[str, dict[str, float | int | str | None]] = {}
        for symbol in REQUIRED_SYMBOLS:
            series = _lookup(basis_by_symbol, symbol)
            if series is None:
                per_asset[symbol] = {"skipped_reason": "missing basis series"}
                continue
            per_asset[symbol] = score_basis_residual(
                series,
                fade=fade,
                entry_z=entry_z,
                fee_bps=fee_bps,
                slippage_bps=slippage_bps,
            )
        btc = per_asset.get("BTC/USD") or {}
        eth = per_asset.get("ETH/USD") or {}
        eligible = _eligible_asset(btc) and _eligible_asset(eth)
        wf_vals: list[float] = []
        ho_vals: list[float] = []
        for asset_metrics in (btc, eth):
            wf_raw = asset_metrics.get("mean_wf_total_return")
            if isinstance(wf_raw, float):
                wf_vals.append(wf_raw)
            ho_raw = asset_metrics.get("mean_holdout_excess_return")
            if isinstance(ho_raw, float):
                ho_vals.append(ho_raw)
        out.append(
            BasisResidCandidate(
                candidate_id=candidate_id,
                label=f"{verb} basis residual z |z|>={entry_z:g}",
                fade=fade,
                entry_z=entry_z,
                per_asset=per_asset,
                mean_wf_total_return=(sum(wf_vals) / len(wf_vals) if wf_vals else None),
                mean_holdout_excess_return=(sum(ho_vals) / len(ho_vals) if ho_vals else None),
                eligible=eligible,
            )
        )
    return out


def run_basis_residual(
    *,
    okx_basis: dict[str, tuple[tuple[datetime, float], ...]],
    vision_basis: dict[str, tuple[tuple[datetime, float], ...]],
    fee_bps: float = DEFAULT_FEE_BPS,
    slippage_bps: float = DEFAULT_SLIPPAGE_BPS,
    history_notes: list[dict[str, str]] | None = None,
    now: datetime | None = None,
) -> BasisResidReport:
    generated = now or datetime.now(UTC)
    dual_ok, gate_notes = dual_basis_gate(okx_basis, vision_basis)
    notes = list(history_notes or []) + gate_notes
    if not dual_ok:
        return BasisResidReport(
            generated_at=generated,
            print_kind="unavailable",
            second_basis_venue=None,
            dual_basis_available=False,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            history_notes=notes,
        )
    primary = _score_catalog(okx_basis, fee_bps=fee_bps, slippage_bps=slippage_bps)
    second = _score_catalog(vision_basis, fee_bps=fee_bps, slippage_bps=slippage_bps)
    primary_ok = {c.candidate_id for c in primary if c.eligible}
    second_ok = {c.candidate_id for c in second if c.eligible}
    passers = sorted(primary_ok & second_ok)
    return BasisResidReport(
        generated_at=generated,
        print_kind="dual_print",
        dual_basis_available=True,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
        dual_print_passer_ids=passers,
        dual_print_passers=len(passers),
        history_notes=notes,
        primary=primary,
        second=second,
        can_promote=False,
        keep_flag_false=True,
    )


def _pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.2f}%"


def render_basis_residual_markdown(report: BasisResidReport) -> str:
    lines = [
        "# Basis residual / cash-and-carry residual dual-print",
        "",
        f"Generated: {report.generated_at.isoformat()}",
        (
            f"Print kind: **{report.print_kind}**. primary=`{report.primary_basis_venue}`; "
            f"second=`{report.second_basis_venue or 'none'}`; "
            f"dual_basis_available=`{str(report.dual_basis_available).lower()}`; "
            f"can_promote=`{str(report.can_promote).lower()}`; "
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
        f"Fees: {report.fee_bps:g}+{report.slippage_bps:g} bps x {CARRY_LEGS} legs.",
        "",
        "## History notes",
        "",
    ]
    for note in report.history_notes:
        lines.append(
            f"- `{note.get('name', '')}` **{note.get('status', '')}**: {note.get('reason', '')}"
        )
    lines.extend(["", "## Primary print (OKX)", ""])
    lines.append("| id | WF total | holdout excess | eligible |")
    lines.append("| --- | ---: | ---: | :---: |")
    for row in report.primary:
        lines.append(
            f"| `{row.candidate_id}` | {_pct(row.mean_wf_total_return)} | "
            f"{_pct(row.mean_holdout_excess_return)} | {'yes' if row.eligible else 'no'} |"
        )
    lines.extend(["", "## Second print (Binance Vision)", ""])
    lines.append("| id | WF total | holdout excess | eligible |")
    lines.append("| --- | ---: | ---: | :---: |")
    for row in report.second:
        lines.append(
            f"| `{row.candidate_id}` | {_pct(row.mean_wf_total_return)} | "
            f"{_pct(row.mean_holdout_excess_return)} | {'yes' if row.eligible else 'no'} |"
        )
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
            "## Promotion decision",
            "",
            (
                "**No candidate is promoted.** can_promote=false; keep_flag_false=true. "
                "Leave every PAPER_PROMOTE_*=false. No live path."
            ),
            "",
        ]
    )
    return "\n".join(lines)
