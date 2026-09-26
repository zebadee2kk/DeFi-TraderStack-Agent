"""Paper-perp funding-z threshold harvest dual-print (NOT spot overlay #162).

Frozen ``fund_z_harvest_*`` catalog. Dual HL x HTX funding with required
dual_basis (OKX x Binance Vision). Fee stress 5+5 x 2 legs. Never flips
``PAPER_PROMOTE_*``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from traderstack.research.funding_carry import (
    CARRY_LEGS,
    HARD_GATE_MIN_DAILY_BARS,
    REQUIRED_SYMBOLS,
    evaluate_carry_hard_gates,
    score_hedged_carry,
)

HARVEST_RULES = (
    "Pre-registered paper-perp funding-z harvest (frozen before score). "
    "Distinct ids from carry_hedged_*. Dual-print HL x HTX funding with "
    "required dual_basis OKX x Binance Vision. Fee 5+5 bps x 2 legs. "
    "Skip if basis missing. PAPER_PROMOTE_* stays false. Empty set success."
)

# (id, label, abs_threshold, z_threshold)
HARVEST_CATALOG: tuple[tuple[str, str, float | None, float | None], ...] = (
    ("fund_z_harvest_z_1_0", "paper-perp harvest when |funding z|>=1.0", None, 1.0),
    ("fund_z_harvest_z_1_5", "paper-perp harvest when |funding z|>=1.5", None, 1.5),
    ("fund_z_harvest_z_2_0", "paper-perp harvest when |funding z|>=2.0", None, 2.0),
    ("fund_z_harvest_abs_2bp", "paper-perp harvest when |rate|>=2bp", 0.0002, None),
    (
        "fund_z_harvest_sign_hold",
        "always harvest |rate| under this recipe fee+basis stress",
        None,
        None,
    ),
)
HARVEST_IDS: tuple[str, ...] = tuple(item[0] for item in HARVEST_CATALOG)
DEFAULT_FEE_BPS = 5.0
DEFAULT_SLIPPAGE_BPS = 5.0
PAPER_PATH_READY = True  # conceptually via PAPER_PERP_HEDGE; flag not flipped
EXECUTABLE_NOTE = (
    "paper-perp executable via PAPER_PERP_HEDGE path conceptually; this CLI "
    "does not flip PAPER_PERP_HEDGE or PAPER_PROMOTE_*; not Kraken-spot"
)


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


class HarvestCandidate(BaseModel):
    candidate_id: str
    family: str = "fund_z_harvest"
    label: str
    per_asset: dict[str, dict[str, float | int | str | None]] = Field(default_factory=dict)
    mean_wf_total_return: float | None = None
    mean_holdout_excess_return: float | None = None
    eligible: bool = False
    basis_modeled: bool = False
    executable: str = EXECUTABLE_NOTE


class FundZHarvestReport(BaseModel):
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
    keep_flag_false: bool = True
    can_promote: bool = False
    paper_path_ready: bool = PAPER_PATH_READY
    executable_note: str = EXECUTABLE_NOTE
    core_ids: list[str] = Field(default_factory=lambda: list(HARVEST_IDS))
    dual_print_passer_ids: list[str] = Field(default_factory=list)
    dual_print_passers: int = 0
    rules: str = HARVEST_RULES
    history_notes: list[dict[str, str]] = Field(default_factory=list)
    primary: list[HarvestCandidate] = Field(default_factory=list)
    second: list[HarvestCandidate] = Field(default_factory=list)
    primary_hard_gates_note: str | None = None
    second_hard_gates_note: str | None = None
    recommended_promote_flag: str | None = None

    def model_dump_json_safe(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


def _score_catalog(
    funding_by_symbol: dict[str, tuple[tuple[datetime, float], ...]],
    basis_by_symbol: dict[str, tuple[tuple[datetime, float], ...]],
    *,
    fee_bps: float,
    slippage_bps: float,
) -> list[HarvestCandidate]:
    out: list[HarvestCandidate] = []
    for candidate_id, label, abs_threshold, z_threshold in HARVEST_CATALOG:
        per_asset: dict[str, dict[str, float | int | str | None]] = {}
        basis_days = 0
        for symbol in REQUIRED_SYMBOLS:
            series = _lookup(funding_by_symbol, symbol)
            basis = _lookup(basis_by_symbol, symbol)
            if series is None:
                per_asset[symbol] = {"skipped_reason": "missing funding"}
                continue
            metrics = score_hedged_carry(
                series,
                abs_threshold=abs_threshold,
                z_threshold=z_threshold,
                fee_bps=fee_bps,
                slippage_bps=slippage_bps,
                basis=basis,
            )
            per_asset[symbol] = metrics
            bd = metrics.get("basis_days_applied")
            if isinstance(bd, int):
                basis_days += bd
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
        out.append(
            HarvestCandidate(
                candidate_id=candidate_id,
                label=label,
                per_asset=per_asset,
                mean_wf_total_return=(sum(wf_vals) / len(wf_vals) if wf_vals else None),
                mean_holdout_excess_return=(sum(ho_vals) / len(ho_vals) if ho_vals else None),
                eligible=_eligible(per_asset),
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


def run_fund_z_harvest(
    *,
    hl_funding: dict[str, tuple[tuple[datetime, float], ...]],
    htx_funding: dict[str, tuple[tuple[datetime, float], ...]],
    okx_basis: dict[str, tuple[tuple[datetime, float], ...]],
    vision_basis: dict[str, tuple[tuple[datetime, float], ...]],
    fee_bps: float = DEFAULT_FEE_BPS,
    slippage_bps: float = DEFAULT_SLIPPAGE_BPS,
    history_notes: list[dict[str, str]] | None = None,
    now: datetime | None = None,
) -> FundZHarvestReport:
    generated = now or datetime.now(UTC)
    notes = list(history_notes or [])
    dual_basis = _basis_ok(okx_basis) and _basis_ok(vision_basis)
    if not dual_basis:
        notes.append(
            {
                "name": "dual_basis",
                "status": "skipped",
                "reason": "dual_basis required for this recipe; missing or short OKX/Vision series",
            }
        )
        return FundZHarvestReport(
            generated_at=generated,
            print_kind="unavailable",
            second_funding_venue=None,
            second_basis_venue=None,
            dual_basis_available=False,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            history_notes=notes,
        )

    # Require usable funding on both venues for BTC+ETH
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
        return FundZHarvestReport(
            generated_at=generated,
            print_kind="unavailable",
            second_funding_venue=None,
            dual_basis_available=True,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            history_notes=notes,
        )

    primary = _score_catalog(hl_funding, okx_basis, fee_bps=fee_bps, slippage_bps=slippage_bps)
    second = _score_catalog(htx_funding, vision_basis, fee_bps=fee_bps, slippage_bps=slippage_bps)
    primary_ok = {c.candidate_id for c in primary if c.eligible}
    second_ok = {c.candidate_id for c in second if c.eligible}
    passers = sorted(primary_ok & second_ok)

    primary_gates = evaluate_carry_hard_gates(
        hl_funding,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
        holdout_fraction=0.20,
        candidate_id="fund_z_harvest_sign_hold",
        basis_by_symbol=okx_basis,
    )
    second_gates = evaluate_carry_hard_gates(
        htx_funding,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
        holdout_fraction=0.20,
        candidate_id="fund_z_harvest_sign_hold",
        basis_by_symbol=vision_basis,
    )

    return FundZHarvestReport(
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
        primary_hard_gates_note=primary_gates.note,
        second_hard_gates_note=second_gates.note,
        can_promote=False,
        keep_flag_false=True,
    )


def _pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.2f}%"


def render_fund_z_harvest_markdown(report: FundZHarvestReport) -> str:
    lines = [
        "# Paper-perp funding-z threshold harvest dual-print",
        "",
        f"Generated: {report.generated_at.isoformat()}",
        (
            f"Print kind: **{report.print_kind}**. funding=`{report.primary_funding_venue}` x "
            f"`{report.second_funding_venue or 'none'}`; basis=`{report.primary_basis_venue}` x "
            f"`{report.second_basis_venue or 'none'}`; "
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
    lines.extend(["", "## Primary print (HL funding x OKX basis)", ""])
    lines.append("| id | WF total | holdout excess | basis_modeled | eligible |")
    lines.append("| --- | ---: | ---: | :---: | :---: |")
    for row in report.primary:
        lines.append(
            f"| `{row.candidate_id}` | {_pct(row.mean_wf_total_return)} | "
            f"{_pct(row.mean_holdout_excess_return)} | "
            f"{'yes' if row.basis_modeled else 'no'} | "
            f"{'yes' if row.eligible else 'no'} |"
        )
    if report.primary_hard_gates_note:
        lines.extend(["", f"Hard gates (sign_hold): {report.primary_hard_gates_note}"])
    lines.extend(["", "## Second print (HTX funding x Binance Vision basis)", ""])
    lines.append("| id | WF total | holdout excess | basis_modeled | eligible |")
    lines.append("| --- | ---: | ---: | :---: | :---: |")
    for row in report.second:
        lines.append(
            f"| `{row.candidate_id}` | {_pct(row.mean_wf_total_return)} | "
            f"{_pct(row.mean_holdout_excess_return)} | "
            f"{'yes' if row.basis_modeled else 'no'} | "
            f"{'yes' if row.eligible else 'no'} |"
        )
    if report.second_hard_gates_note:
        lines.extend(["", f"Hard gates (sign_hold): {report.second_hard_gates_note}"])
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
