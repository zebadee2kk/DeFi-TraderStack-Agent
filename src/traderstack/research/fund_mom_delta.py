"""Same-asset funding-momentum (rate-change) dual-print (HL x HTX).

Frozen fund_mom_* catalog. Concurrent Hyperliquid x HTX. Paper-perp fees
5+5 x CARRY_LEGS. Never flips PAPER_PROMOTE_*. Distinct from fund_z_harvest
sign_hold, fund_spread_btc_eth (#180), and fund_xs_rank (#179).
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
    REQUIRED_SYMBOLS,
    Z_LOOKBACK,
    choose_walkforward,
)
from traderstack.research.harder_gates import paper_promote_flag_name

FAMILY = "fund_mom"
DEFAULT_FEE_BPS = 5.0
DEFAULT_SLIPPAGE_BPS = 5.0
HOLDOUT_FRACTION = 0.20
PAPER_PATH_READY = True
EXECUTABLE_NOTE = (
    "paper-perp funding-momentum (rate-change); conceptually via PAPER_PERP_HEDGE; "
    "this CLI does not flip PAPER_PERP_HEDGE or PAPER_PROMOTE_*; not Kraken-spot"
)
MOM_RULES = (
    "Pre-registered same-asset funding-momentum / rate-change dual-print "
    "(frozen before score). Concurrent HL x HTX. Fees 5+5 bps x 2 legs. "
    "Distinct from fund_z_harvest_sign_hold, fund_spread_btc_eth #180, "
    "fund_xs_rank #179. PAPER_PROMOTE_* stays false. Empty set success."
)

# (id, label, mode, z_threshold, is_control)
# mode: delta_sign | confirm_sign | flat
MOM_CATALOG: tuple[tuple[str, str, str, float | None, bool], ...] = (
    ("fund_mom_delta_sign", "position=-sign(Δf)", "delta_sign", None, False),
    ("fund_mom_delta_z_1_0", "delta_sign when |z(Δf)|>=1.0", "delta_sign", 1.0, False),
    ("fund_mom_delta_z_1_5", "delta_sign when |z(Δf)|>=1.5", "delta_sign", 1.5, False),
    ("fund_mom_delta_z_2_0", "delta_sign when |z(Δf)|>=2.0", "delta_sign", 2.0, False),
    (
        "fund_mom_confirm_sign",
        "harvest -sign(rate) only when sign(Δf)==sign(rate)",
        "confirm_sign",
        None,
        False,
    ),
    ("fund_mom_flat", "always-flat control", "flat", None, True),
)
MOM_IDS: tuple[str, ...] = tuple(item[0] for item in MOM_CATALOG)
CONTROL_IDS = frozenset(item[0] for item in MOM_CATALOG if item[4])


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


def _compound(returns: list[float]) -> float:
    equity = 1.0
    for item in returns:
        equity *= 1.0 + item
    return equity - 1.0


def _sign(value: float) -> int:
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0


def _want_position(
    history: list[float],
    *,
    mode: str,
    z_threshold: float | None,
    lookback: int = Z_LOOKBACK,
) -> int:
    """Return position in {-1, 0, +1}. Decision uses history only (no current)."""
    if mode == "flat":
        return 0
    if len(history) < 2:
        return 0
    delta = history[-1] - history[-2]
    deltas = [history[i] - history[i - 1] for i in range(1, len(history))]
    if z_threshold is not None:
        if len(deltas) < lookback:
            return 0
        window = deltas[-lookback:]
        if abs(zscore(window[-1], window)) < z_threshold:
            return 0
    if mode == "delta_sign":
        # Rising funding -> short (collect if funding stays positive).
        return -_sign(delta)
    if mode == "confirm_sign":
        rate = history[-1]
        if _sign(delta) == 0 or _sign(rate) == 0:
            return 0
        if _sign(delta) != _sign(rate):
            return 0
        return -_sign(rate)
    return 0


def mom_per_print(
    series: tuple[tuple[datetime, float], ...],
    *,
    mode: str,
    z_threshold: float | None,
    fee_bps: float,
    slippage_bps: float,
    legs: int = CARRY_LEGS,
) -> tuple[list[float], int]:
    cost = legs * (fee_bps + slippage_bps) / 10_000.0
    position = 0
    flips = 0
    per_print: list[float] = []
    for index, (_ts, rate) in enumerate(series):
        history = [value for _when, value in series[:index]]
        want = _want_position(history, mode=mode, z_threshold=z_threshold)
        fee = 0.0
        if want != position:
            fee = cost
            flips += 1
            position = want
        income = -position * rate
        per_print.append(income - fee)
    return per_print, flips


def score_mom_series(
    series: tuple[tuple[datetime, float], ...],
    *,
    mode: str,
    z_threshold: float | None,
    fee_bps: float,
    slippage_bps: float,
    holdout_fraction: float = HOLDOUT_FRACTION,
) -> dict[str, float | int | str | None]:
    per_print, flips = mom_per_print(
        series,
        mode=mode,
        z_threshold=z_threshold,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
    )
    if len(per_print) < 2:
        return {
            "print_count": len(series),
            "flips": flips,
            "skipped_reason": "funding tape too short to score",
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
        "mean_holdout_excess_return": holdout_total,
        "full_sample_total_return": _compound(per_print),
        "fold_count": len(fold_totals),
    }


def _asset_sign(metrics: dict[str, float | int | str | None], key: str) -> bool:
    value = metrics.get(key)
    return isinstance(value, float) and value > 0


def _eligible(per_asset: dict[str, dict[str, float | int | str | None]]) -> bool:
    btc = per_asset.get("BTC/USD") or {}
    eth = per_asset.get("ETH/USD") or {}
    return all(
        _asset_sign(btc, key) and _asset_sign(eth, key)
        for key in ("mean_wf_total_return", "mean_holdout_excess_return")
    )


class MomCandidate(BaseModel):
    candidate_id: str
    family: str = FAMILY
    label: str
    is_control: bool = False
    per_asset: dict[str, dict[str, float | int | str | None]] = Field(default_factory=dict)
    mean_wf_total_return: float | None = None
    mean_holdout_excess_return: float | None = None
    eligible: bool = False
    flips: int = 0


class FundMomReport(BaseModel):
    generated_at: datetime
    print_kind: Literal["single_print", "dual_print", "unavailable"]
    dual_mode: Literal["concurrent_venues", "none"] = "none"
    primary_funding_venue: str = "hyperliquid"
    second_funding_venue: str | None = "htx"
    fee_bps: float
    slippage_bps: float
    legs: int = CARRY_LEGS
    keep_flag_false: bool = True
    can_promote: bool = False
    paper_path_ready: bool = PAPER_PATH_READY
    executable_note: str = EXECUTABLE_NOTE
    core_ids: list[str] = Field(default_factory=lambda: list(MOM_IDS))
    dual_print_passer_ids: list[str] = Field(default_factory=list)
    dual_print_passers: int = 0
    rules: str = MOM_RULES
    history_notes: list[dict[str, str]] = Field(default_factory=list)
    coverage: dict[str, Any] = Field(default_factory=dict)
    primary: list[MomCandidate] = Field(default_factory=list)
    second: list[MomCandidate] = Field(default_factory=list)
    recommended_promote_flag: str | None = None

    def model_dump_json_safe(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


def _score_catalog(
    funding_by_symbol: dict[str, tuple[tuple[datetime, float], ...]],
    *,
    fee_bps: float,
    slippage_bps: float,
) -> list[MomCandidate]:
    out: list[MomCandidate] = []
    for candidate_id, label, mode, z_thr, is_control in MOM_CATALOG:
        per_asset: dict[str, dict[str, float | int | str | None]] = {}
        flips_total = 0
        for symbol in REQUIRED_SYMBOLS:
            series = _lookup(funding_by_symbol, symbol)
            if series is None:
                per_asset[symbol] = {"skipped_reason": "missing funding"}
                continue
            metrics = score_mom_series(
                series,
                mode=mode,
                z_threshold=z_thr,
                fee_bps=fee_bps,
                slippage_bps=slippage_bps,
            )
            per_asset[symbol] = metrics
            flips_total += int(metrics.get("flips") or 0)
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
            MomCandidate(
                candidate_id=candidate_id,
                label=label,
                is_control=is_control,
                per_asset=per_asset,
                mean_wf_total_return=(sum(wf_vals) / len(wf_vals) if wf_vals else None),
                mean_holdout_excess_return=(sum(ho_vals) / len(ho_vals) if ho_vals else None),
                eligible=(not is_control) and _eligible(per_asset),
                flips=flips_total,
            )
        )
    return out


def _funding_ok(mapping: dict[str, tuple[tuple[datetime, float], ...]]) -> bool:
    for symbol in REQUIRED_SYMBOLS:
        series = _lookup(mapping, symbol)
        if series is None:
            return False
        if len(series) >= HARD_GATE_MIN_DAILY_BARS:
            continue
        if len(series) < MIN_RESEARCH_BARS + max(1, int(MIN_RESEARCH_BARS * 0.2)):
            return False
    return True


def run_fund_mom_delta(
    hl_funding: dict[str, tuple[tuple[datetime, float], ...]],
    htx_funding: dict[str, tuple[tuple[datetime, float], ...]],
    *,
    fee_bps: float = DEFAULT_FEE_BPS,
    slippage_bps: float = DEFAULT_SLIPPAGE_BPS,
    history_notes: list[dict[str, str]] | None = None,
) -> FundMomReport:
    notes = list(history_notes or [])
    now = datetime.now(tz=UTC)

    coverage: dict[str, Any] = {
        "hl_btc_days": len(_lookup(hl_funding, "BTC/USD") or ()),
        "hl_eth_days": len(_lookup(hl_funding, "ETH/USD") or ()),
        "htx_btc_days": len(_lookup(htx_funding, "BTC/USD") or ()),
        "htx_eth_days": len(_lookup(htx_funding, "ETH/USD") or ()),
        "min_bars_preferred": HARD_GATE_MIN_DAILY_BARS,
    }

    hl_ok = _funding_ok(hl_funding)
    htx_ok = _funding_ok(htx_funding)
    notes.append(
        {
            "name": "coverage_freeze",
            "status": "ok" if (hl_ok and htx_ok) else "skipped",
            "reason": (
                f"hl_ok={hl_ok} days={coverage['hl_btc_days']}/{coverage['hl_eth_days']}; "
                f"htx_ok={htx_ok} days={coverage['htx_btc_days']}/{coverage['htx_eth_days']}; "
                "concurrent required"
            ),
        }
    )

    if not (hl_ok and htx_ok):
        return FundMomReport(
            generated_at=now,
            print_kind="unavailable",
            dual_mode="none",
            second_funding_venue=None,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            history_notes=notes,
            coverage=coverage,
        )

    notes.append(
        {
            "name": "dual_print_cells",
            "status": "ok",
            "reason": "frozen concurrent hyperliquid x htx before PnL",
        }
    )
    primary = _score_catalog(hl_funding, fee_bps=fee_bps, slippage_bps=slippage_bps)
    second = _score_catalog(htx_funding, fee_bps=fee_bps, slippage_bps=slippage_bps)
    passers = sorted(
        {c.candidate_id for c in primary if c.eligible}
        & {c.candidate_id for c in second if c.eligible}
    )
    return FundMomReport(
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


def _pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.2f}%"


def render_fund_mom_markdown(report: FundMomReport) -> str:
    lines = [
        "# Funding-momentum (rate-change) HL x HTX dual-print",
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
