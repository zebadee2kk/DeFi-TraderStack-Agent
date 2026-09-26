"""High-|funding| selective <=2d fee-survival historical REPLAY.

Paper/research only. Signals use a completed day and holds begin on the next
present day. MTM is omitted and this module can never promote a strategy.
"""

from __future__ import annotations

import math
import statistics
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from traderstack.research.edge_series import _asilletto_yyyymmdd
from traderstack.research.fund_z_fee_aware_replay import (
    ASSETS,
    DEFAULT_NOTIONAL_PER_ASSET_USD,
    ERA_A_END,
    ERA_A_START,
    ERA_B_END,
    ERA_B_START,
    FEE_LADDERS,
    FeeLadder,
    load_asilletto_daily_sum_abs,
)

STRATEGY_ID = "fund_z_hiabs_trail1_hold"
FAMILY = "fund_z_hiabs_fee_aware_replay"
WINDOWS_N: tuple[int, ...] = (1, 2, 3)
TARGET_HOLD_DAYS = 2
FEE_SURVIVAL_FRACTION = 0.55
REPLAY_RULES = (
    "Pre-registered high-|funding| selective historical REPLAY. Enter when the "
    "trailing completed present day's combined funding_usd is >= the ladder's "
    "open_cost_usd / 2; hold the next N present days starting at i+1. "
    "fee_aware = funding - open fees; MTM omitted. Always-on tumbling windows "
    "are reference-only. PAPER_PROMOTE_* stays false; can_promote=false."
)


class WindowAgg(BaseModel):
    mode: Literal["event", "always_on_ref"]
    n_days: int
    ladder_id: str
    thr_usd: float
    fees_usd: float
    n_windows: int
    mean_funding_usd: float | None = None
    mean_fee_aware_paper_pnl_usd: float | None = None
    median_fee_aware_paper_pnl_usd: float | None = None
    p10_fee_aware_paper_pnl_usd: float | None = None
    p90_fee_aware_paper_pnl_usd: float | None = None
    fraction_fee_positive: float | None = None
    fee_survival_pass: bool = False


class EraReport(BaseModel):
    era_id: str
    start: str
    end: str
    n_days_with_funding: int
    aggs: list[WindowAgg] = Field(default_factory=list)


class HiAbsFeeAwareReplayReport(BaseModel):
    generated_at: datetime
    strategy_id: str = STRATEGY_ID
    family: str = FAMILY
    print_kind: Literal["dual_era", "single_era", "unavailable"]
    notional_per_asset_usd: float
    n_assets: int = 2
    windows_n: list[int] = Field(default_factory=lambda: list(WINDOWS_N))
    target_hold_days: int = TARGET_HOLD_DAYS
    fee_survival_fraction: float = FEE_SURVIVAL_FRACTION
    keep_flag_false: bool = True
    can_promote: bool = False
    mtm_omitted: bool = True
    rules: str = REPLAY_RULES
    history_notes: list[dict[str, str]] = Field(default_factory=list)
    eras: list[EraReport] = Field(default_factory=list)
    dual_era_fee_survival_passers: list[str] = Field(default_factory=list)
    dual_era_fee_survival_passers_count: int = 0
    le2d_path_exists: bool = False
    recipe_commit: str | None = None
    honesty: str = (
        "PAPER_RESEARCH_ONLY_NOT_LIVE_PNL_NOT_PROMOTE. Selective fee survival "
        "is informational; can_promote stays false and PAPER_PROMOTE_* stays false."
    )

    def model_dump_json_safe(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


def threshold_usd(
    ladder: FeeLadder,
    notional_per_asset_usd: float,
    *,
    target_hold_days: int = TARGET_HOLD_DAYS,
) -> float:
    return ladder.open_cost_usd(notional_per_asset_usd, len(ASSETS)) / target_hold_days


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    if lo == hi:
        return ordered[lo]
    return ordered[lo] * (hi - pos) + ordered[hi] * (pos - lo)


def _combined_funding_usd(row: dict[str, float], notional: float) -> float | None:
    if any(asset not in row for asset in ASSETS):
        return None
    return sum(notional * float(row[asset]) for asset in ASSETS)


def _agg(
    *,
    mode: Literal["event", "always_on_ref"],
    n: int,
    ladder: FeeLadder,
    threshold: float,
    fees: float,
    fundings: list[float],
) -> WindowAgg:
    pnls = [funding - fees for funding in fundings]
    fraction = sum(pnl > 0 for pnl in pnls) / len(pnls) if pnls else None
    return WindowAgg(
        mode=mode,
        n_days=n,
        ladder_id=ladder.ladder_id,
        thr_usd=threshold,
        fees_usd=fees,
        n_windows=len(pnls),
        mean_funding_usd=statistics.fmean(fundings) if fundings else None,
        mean_fee_aware_paper_pnl_usd=statistics.fmean(pnls) if pnls else None,
        median_fee_aware_paper_pnl_usd=statistics.median(pnls) if pnls else None,
        p10_fee_aware_paper_pnl_usd=_percentile(pnls, 0.10),
        p90_fee_aware_paper_pnl_usd=_percentile(pnls, 0.90),
        fraction_fee_positive=fraction,
        fee_survival_pass=bool(pnls and fraction is not None and fraction >= FEE_SURVIVAL_FRACTION),
    )


def score_era(
    panel: dict[datetime, dict[str, float]],
    *,
    era_id: str,
    start: datetime,
    end: datetime,
    notional_per_asset_usd: float = DEFAULT_NOTIONAL_PER_ASSET_USD,
    ladders: tuple[FeeLadder, ...] = FEE_LADDERS,
    windows_n: tuple[int, ...] = WINDOWS_N,
) -> EraReport:
    days = sorted(day for day in panel if start <= day <= end)
    daily = [_combined_funding_usd(panel[day], notional_per_asset_usd) for day in days]
    aggs: list[WindowAgg] = []
    for n in windows_n:
        for ladder in ladders:
            fees = ladder.open_cost_usd(notional_per_asset_usd, len(ASSETS))
            threshold = fees / TARGET_HOLD_DAYS
            event_fundings: list[float] = []
            for i, signal_funding in enumerate(daily):
                if signal_funding is None or signal_funding < threshold or i + n >= len(days):
                    continue
                hold = daily[i + 1 : i + 1 + n]
                if len(hold) == n and all(value is not None for value in hold):
                    event_fundings.append(sum(value for value in hold if value is not None))
            aggs.append(
                _agg(
                    mode="event",
                    n=n,
                    ladder=ladder,
                    threshold=threshold,
                    fees=fees,
                    fundings=event_fundings,
                )
            )

            reference_fundings: list[float] = []
            for i in range(0, len(days) - n + 1, n):
                hold = daily[i : i + n]
                if len(hold) == n and all(value is not None for value in hold):
                    reference_fundings.append(sum(value for value in hold if value is not None))
            aggs.append(
                _agg(
                    mode="always_on_ref",
                    n=n,
                    ladder=ladder,
                    threshold=threshold,
                    fees=fees,
                    fundings=reference_fundings,
                )
            )
    return EraReport(
        era_id=era_id,
        start=_asilletto_yyyymmdd(start),
        end=_asilletto_yyyymmdd(end),
        n_days_with_funding=len(days),
        aggs=aggs,
    )


def run_hiabs_fee_aware_replay(
    panel: dict[datetime, dict[str, float]],
    *,
    notional_per_asset_usd: float = DEFAULT_NOTIONAL_PER_ASSET_USD,
    history_notes: list[dict[str, str]] | None = None,
    recipe_commit: str | None = None,
    now: datetime | None = None,
) -> HiAbsFeeAwareReplayReport:
    generated = now or datetime.now(UTC)
    common = {
        "generated_at": generated,
        "notional_per_asset_usd": notional_per_asset_usd,
        "history_notes": list(history_notes or []),
        "recipe_commit": recipe_commit,
    }
    if not panel:
        return HiAbsFeeAwareReplayReport(print_kind="unavailable", **common)
    era_a = score_era(
        panel,
        era_id="era_a",
        start=ERA_A_START,
        end=ERA_A_END,
        notional_per_asset_usd=notional_per_asset_usd,
    )
    era_b = score_era(
        panel,
        era_id="era_b",
        start=ERA_B_START,
        end=ERA_B_END,
        notional_per_asset_usd=notional_per_asset_usd,
    )
    usable = sum(era.n_days_with_funding > 0 for era in (era_a, era_b))
    print_kind: Literal["dual_era", "single_era", "unavailable"] = (
        "dual_era" if usable == 2 else "single_era" if usable == 1 else "unavailable"
    )
    passers: list[str] = []
    primary = next(ladder.ladder_id for ladder in FEE_LADDERS if ladder.primary)
    if print_kind == "dual_era":
        maps = [
            {(agg.n_days, agg.ladder_id): agg for agg in era.aggs if agg.mode == "event"}
            for era in (era_a, era_b)
        ]
        for n in WINDOWS_N:
            pair = [mapping.get((n, primary)) for mapping in maps]
            if all(
                agg is not None and agg.n_windows >= 1 and agg.fee_survival_pass for agg in pair
            ):
                passers.append(f"N={n}/{primary}")
    return HiAbsFeeAwareReplayReport(
        print_kind=print_kind,
        eras=[era_a, era_b],
        dual_era_fee_survival_passers=passers,
        dual_era_fee_survival_passers_count=len(passers),
        le2d_path_exists=any(p.startswith(("N=1/", "N=2/")) for p in passers),
        can_promote=False,
        keep_flag_false=True,
        **common,
    )


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.4f}"


def render_hiabs_fee_aware_replay_markdown(report: HiAbsFeeAwareReplayReport) -> str:
    lines = [
        "# fund_z high-|funding| selective ≤2d fee-survival historical REPLAY",
        "",
        f"Generated: {report.generated_at.isoformat()}",
        (
            f"Recipe commit: `{report.recipe_commit or 'unknown'}`. Print kind: "
            f"**{report.print_kind}**. strategy=`{report.strategy_id}`; "
            f"family=`{report.family}`; notional=${report.notional_per_asset_usd:g}"
            f"×{report.n_assets}; can_promote=`false`; "
            f"le2d_path_exists=`{str(report.le2d_path_exists).lower()}`."
        ),
        "",
        "## Rules",
        "",
        report.rules,
        "",
        f"Honesty: {report.honesty}",
        "",
        "## History notes",
        "",
    ]
    lines.extend(
        f"- `{n.get('name', '')}` **{n.get('status', '')}**: {n.get('reason', '')}"
        for n in report.history_notes
    )
    for era in report.eras:
        lines.extend(
            [
                "",
                f"## Era `{era.era_id}` ({era.start} → {era.end}; days={era.n_days_with_funding})",
                "",
            ]
        )
        for mode, title in (
            ("event", "Selective event windows (primary)"),
            ("always_on_ref", "Always-on tumbling reference"),
        ):
            lines.extend(
                [
                    f"### {title}",
                    "",
                    "| N | ladder | threshold | n | fees | mean funding | mean fee-aware | frac fee-positive | pass |",
                    "| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | :---: |",
                ]
            )
            for agg in era.aggs:
                if agg.mode != mode:
                    continue
                frac = (
                    "n/a"
                    if agg.fraction_fee_positive is None
                    else f"{agg.fraction_fee_positive:.1%}"
                )
                lines.append(
                    f"| {agg.n_days} | `{agg.ladder_id}` | {_fmt(agg.thr_usd)} | {agg.n_windows} | {_fmt(agg.fees_usd)} | {_fmt(agg.mean_funding_usd)} | {_fmt(agg.mean_fee_aware_paper_pnl_usd)} | {frac} | {'yes' if agg.fee_survival_pass else 'no'} |"
                )
            lines.append("")
    passer_text = ", ".join(f"`{p}`" for p in report.dual_era_fee_survival_passers) or "**0**"
    lines.extend(
        [
            "## Dual-era event-mode fee-survival passers",
            "",
            passer_text,
            "",
            "## Promotion decision",
            "",
            (
                "**No promote.** can_promote=false; keep_flag_false=true. Leave every "
                "PAPER_PROMOTE_*=false. This historical replay is not live PnL."
            ),
            "",
        ]
    )
    return "\n".join(lines)


__all__ = [
    "FEE_LADDERS",
    "FEE_SURVIVAL_FRACTION",
    "TARGET_HOLD_DAYS",
    "WINDOWS_N",
    "FeeLadder",
    "load_asilletto_daily_sum_abs",
    "render_hiabs_fee_aware_replay_markdown",
    "run_hiabs_fee_aware_replay",
    "score_era",
    "threshold_usd",
]
