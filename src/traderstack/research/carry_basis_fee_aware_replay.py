"""Fee-aware multi-day REPLAY: HL funding + dual-basis (OKX x Vision).

Reuses #185 fee ladders / N-windows / stats helpers. Paper/research only.
Never flips PAPER_PROMOTE_*. Skip-not-invent. can_promote=false.
"""

from __future__ import annotations

import json
import statistics
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from traderstack.research.fund_z_fee_aware_replay import (
    ASSETS,
    DEFAULT_NOTIONAL_PER_ASSET_USD,
    FEE_LADDERS,
    FEE_SURVIVAL_FRACTION,
    WINDOWS_N,
    FeeLadder,
    _fmt_pct,
    _fmt_usd,
    _iter_windows,
    _stats,
    _utc_day,
    load_asilletto_daily_sum_abs,
)

FAMILY = "carry_basis_fee_aware_replay"
STRATEGY_ID = "carry_hedged_sign_basis_dual"
ERA_START = datetime(2024, 1, 1, tzinfo=UTC)
ERA_END = datetime(2026, 6, 1, tzinfo=UTC)
REPLAY_RULES = (
    "Pre-registered hedged-carry + dual-basis fee-aware multi-day REPLAY "
    "(frozen before score). Always-on sign-hold; open once per N-day window; "
    "income = HL daily_sum_abs funding + basis Δ (prev−curr); fee_aware = "
    "funding + basis − fees (MTM omitted). Dual print OKX x Binance Vision. "
    "HTX hourly skip-not-invent. PAPER_PROMOTE_* stays false. can_promote=false."
)


class CarryWindowAgg(BaseModel):
    mode: Literal["tumbling", "sliding"]
    n_days: int
    ladder_id: str
    fees_usd: float
    n_windows: int
    mean_funding_usd: float | None = None
    mean_basis_usd: float | None = None
    mean_fee_aware_paper_pnl_usd: float | None = None
    median_fee_aware_paper_pnl_usd: float | None = None
    p10_fee_aware_paper_pnl_usd: float | None = None
    p90_fee_aware_paper_pnl_usd: float | None = None
    fraction_fee_positive: float | None = None
    fee_survival_pass: bool = False


def _day_key(ts: datetime) -> str:
    d = _utc_day(ts)
    return f"{d.year:04d}{d.month:02d}{d.day:02d}"


def load_basis_venue(
    path: Path,
    *,
    assets: tuple[str, ...] = ASSETS,
) -> tuple[dict[datetime, dict[str, float]], list[dict[str, str]]]:
    """Load PIT daily basis files ({ASSET}USD_basis_1d.json list of opened_at/value)."""
    notes: list[dict[str, str]] = []
    panel: dict[datetime, dict[str, float]] = {}
    if not path.is_dir():
        notes.append(
            {
                "name": f"basis_dir:{path.name}",
                "status": "skipped",
                "reason": f"missing {path}",
            }
        )
        return {}, notes
    per_asset_days: dict[str, dict[datetime, float]] = {a: {} for a in assets}
    for asset in assets:
        fpath = path / f"{asset}USD_basis_1d.json"
        if not fpath.is_file():
            notes.append(
                {
                    "name": f"basis_file:{path.name}:{asset}",
                    "status": "skipped",
                    "reason": f"missing {fpath.name}",
                }
            )
            continue
        try:
            rows = json.loads(fpath.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            notes.append(
                {
                    "name": f"basis_file:{path.name}:{asset}",
                    "status": "skipped",
                    "reason": f"unreadable: {type(exc).__name__}",
                }
            )
            continue
        if not isinstance(rows, list):
            notes.append(
                {
                    "name": f"basis_file:{path.name}:{asset}",
                    "status": "skipped",
                    "reason": "expected list of {opened_at,value}",
                }
            )
            continue
        n = 0
        for row in rows:
            if not isinstance(row, dict):
                continue
            raw_ts = row.get("opened_at")
            raw_val = row.get("value")
            if raw_ts is None or raw_val is None:
                continue
            try:
                raw = str(raw_ts)
                if raw.endswith("Z"):
                    raw = raw[:-1] + "+00:00"
                ts = datetime.fromisoformat(raw)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=UTC)
                val = float(raw_val)
            except (TypeError, ValueError):
                continue
            per_asset_days[asset][_utc_day(ts)] = val
            n += 1
        notes.append(
            {
                "name": f"basis_file:{path.name}:{asset}",
                "status": "ok",
                "reason": f"loaded {n} daily rows from {fpath.name}",
            }
        )
    # intersect days where all assets present
    if not all(per_asset_days[a] for a in assets):
        return {}, notes
    common = set(per_asset_days[assets[0]])
    for a in assets[1:]:
        common &= set(per_asset_days[a])
    for day in sorted(common):
        panel[day] = {a: per_asset_days[a][day] for a in assets}
    notes.append(
        {
            "name": f"basis_panel:{path.name}",
            "status": "ok" if panel else "skipped",
            "reason": f"days_with_btc_eth={len(panel)}",
        }
    )
    return panel, notes


def _window_income(
    funding_panel: dict[datetime, dict[str, float]],
    basis_panel: dict[datetime, dict[str, float]],
    days: list[datetime],
    *,
    notional_per_asset_usd: float,
) -> tuple[float, float, int] | None:
    """Return (funding_usd, basis_usd, basis_steps) or None if funding incomplete."""
    if not days or any(d not in funding_panel for d in days):
        return None
    funding = 0.0
    for d in days:
        row = funding_panel[d]
        for a in ASSETS:
            if a not in row:
                return None
            funding += notional_per_asset_usd * float(row[a])
    basis_usd = 0.0
    basis_steps = 0
    prev: dict[str, float] | None = None
    for d in days:
        brow = basis_panel.get(d)
        if brow is None or any(a not in brow for a in ASSETS):
            prev = None
            continue
        if prev is not None:
            for a in ASSETS:
                basis_usd += notional_per_asset_usd * (prev[a] - brow[a])
            basis_steps += 1
        prev = {a: float(brow[a]) for a in ASSETS}
    return funding, basis_usd, basis_steps


class VenueReport(BaseModel):
    venue_id: str
    basis_venue: str
    n_funding_days: int
    n_basis_days: int
    aggs: list[CarryWindowAgg] = Field(default_factory=list)


class CarryBasisReplayReport(BaseModel):
    generated_at: datetime
    strategy_id: str = STRATEGY_ID
    family: str = FAMILY
    print_kind: Literal["dual_basis", "single_basis", "unavailable"]
    notional_per_asset_usd: float
    n_assets: int = 2
    windows_n: list[int] = Field(default_factory=lambda: list(WINDOWS_N))
    keep_flag_false: bool = True
    can_promote: bool = False
    mtm_omitted: bool = True
    rules: str = REPLAY_RULES
    history_notes: list[dict[str, str]] = Field(default_factory=list)
    venues: list[VenueReport] = Field(default_factory=list)
    dual_basis_fee_survival_passers: list[str] = Field(default_factory=list)
    dual_basis_fee_survival_passers_count: int = 0
    recipe_commit: str | None = None
    honesty: str = (
        "PAPER_RESEARCH_ONLY_NOT_LIVE_PNL_NOT_PROMOTE. "
        "fee_aware = funding_usd + basis_usd - fees_usd (MTM omitted). "
        "can_promote stays false; PAPER_PROMOTE_* Field defaults stay false."
    )

    def model_dump_json_safe(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


def score_venue(
    funding_panel: dict[datetime, dict[str, float]],
    basis_panel: dict[datetime, dict[str, float]],
    *,
    venue_id: str,
    basis_venue: str,
    start: datetime,
    end: datetime,
    notional_per_asset_usd: float,
    ladders: tuple[FeeLadder, ...] = FEE_LADDERS,
    windows_n: tuple[int, ...] = WINDOWS_N,
) -> VenueReport:
    s = _utc_day(start)
    e = _utc_day(end)
    fund_days = sorted(d for d in funding_panel if s <= d <= e)
    basis_days = sum(1 for d in basis_panel if s <= d <= e)
    aggs: list[CarryWindowAgg] = []
    for n in windows_n:
        for mode in ("tumbling", "sliding"):
            chunks = _iter_windows(fund_days, n=n, mode=mode)  # type: ignore[arg-type]
            for ladder in ladders:
                fees = ladder.open_cost_usd(notional_per_asset_usd, len(ASSETS))
                pnls: list[float] = []
                fundings: list[float] = []
                bases: list[float] = []
                for chunk in chunks:
                    got = _window_income(
                        funding_panel,
                        basis_panel,
                        chunk,
                        notional_per_asset_usd=notional_per_asset_usd,
                    )
                    if got is None:
                        continue
                    funding_usd, basis_usd, _steps = got
                    fundings.append(funding_usd)
                    bases.append(basis_usd)
                    pnls.append(funding_usd + basis_usd - fees)
                st = _stats(pnls)
                frac = sum(1 for x in pnls if x > 0) / len(pnls) if pnls else None
                aggs.append(
                    CarryWindowAgg(
                        mode=mode,  # type: ignore[arg-type]
                        n_days=n,
                        ladder_id=ladder.ladder_id,
                        fees_usd=fees,
                        n_windows=len(pnls),
                        mean_funding_usd=(statistics.fmean(fundings) if fundings else None),
                        mean_basis_usd=(statistics.fmean(bases) if bases else None),
                        mean_fee_aware_paper_pnl_usd=st["mean"],  # type: ignore[arg-type]
                        median_fee_aware_paper_pnl_usd=st["median"],  # type: ignore[arg-type]
                        p10_fee_aware_paper_pnl_usd=st["p10"],  # type: ignore[arg-type]
                        p90_fee_aware_paper_pnl_usd=st["p90"],  # type: ignore[arg-type]
                        fraction_fee_positive=frac,
                        fee_survival_pass=bool(frac is not None and frac >= FEE_SURVIVAL_FRACTION),
                    )
                )
    return VenueReport(
        venue_id=venue_id,
        basis_venue=basis_venue,
        n_funding_days=len(fund_days),
        n_basis_days=basis_days,
        aggs=aggs,
    )


def run_carry_basis_replay(
    funding_panel: dict[datetime, dict[str, float]],
    okx_basis: dict[datetime, dict[str, float]],
    vision_basis: dict[datetime, dict[str, float]],
    *,
    notional_per_asset_usd: float = DEFAULT_NOTIONAL_PER_ASSET_USD,
    history_notes: list[dict[str, str]] | None = None,
    recipe_commit: str | None = None,
    now: datetime | None = None,
) -> CarryBasisReplayReport:
    notes = list(history_notes or [])
    notes.append(
        {
            "name": "htx_hourly_funding",
            "status": "skipped",
            "reason": "no HTX hourly funding tape on disk; dual-print uses OKX x Vision basis",
        }
    )
    generated = now or datetime.now(UTC)
    if not funding_panel:
        return CarryBasisReplayReport(
            generated_at=generated,
            print_kind="unavailable",
            notional_per_asset_usd=notional_per_asset_usd,
            history_notes=notes,
            recipe_commit=recipe_commit,
        )
    venues: list[VenueReport] = []
    if okx_basis:
        venues.append(
            score_venue(
                funding_panel,
                okx_basis,
                venue_id="hl_okx",
                basis_venue="okx",
                start=ERA_START,
                end=ERA_END,
                notional_per_asset_usd=notional_per_asset_usd,
            )
        )
    if vision_basis:
        venues.append(
            score_venue(
                funding_panel,
                vision_basis,
                venue_id="hl_vision",
                basis_venue="binance_vision",
                start=ERA_START,
                end=ERA_END,
                notional_per_asset_usd=notional_per_asset_usd,
            )
        )
    usable = [v for v in venues if v.n_funding_days > 0 and v.n_basis_days > 0]
    if len(usable) >= 2:
        print_kind: Literal["dual_basis", "single_basis", "unavailable"] = "dual_basis"
    elif len(usable) == 1:
        print_kind = "single_basis"
    else:
        print_kind = "unavailable"

    passers: list[str] = []
    if print_kind == "dual_basis":
        primary_ladder = next(l.ladder_id for l in FEE_LADDERS if l.primary)
        a_map = {(a.n_days, a.ladder_id): a for a in usable[0].aggs if a.mode == "tumbling"}
        b_map = {(a.n_days, a.ladder_id): a for a in usable[1].aggs if a.mode == "tumbling"}
        for n in WINDOWS_N:
            key = (n, primary_ladder)
            aa = a_map.get(key)
            bb = b_map.get(key)
            if (
                aa is not None
                and bb is not None
                and aa.fee_survival_pass
                and bb.fee_survival_pass
                and aa.n_windows > 0
                and bb.n_windows > 0
            ):
                passers.append(f"N={n}/{primary_ladder}")

    return CarryBasisReplayReport(
        generated_at=generated,
        print_kind=print_kind,
        notional_per_asset_usd=notional_per_asset_usd,
        history_notes=notes,
        venues=venues,
        dual_basis_fee_survival_passers=passers,
        dual_basis_fee_survival_passers_count=len(passers),
        can_promote=False,
        keep_flag_false=True,
        recipe_commit=recipe_commit,
    )


def render_carry_basis_replay_markdown(report: CarryBasisReplayReport) -> str:
    lines = [
        "# Hedged-carry + dual-basis fee-aware multi-day historical REPLAY",
        "",
        f"Generated: {report.generated_at.isoformat()}",
        (
            f"Recipe commit: `{report.recipe_commit or 'unknown'}`. "
            f"Print kind: **{report.print_kind}**. "
            f"strategy=`{report.strategy_id}`; "
            f"notional=${report.notional_per_asset_usd:g}×{report.n_assets}; "
            f"can_promote=`{str(report.can_promote).lower()}`; "
            f"keep_flag_false=`{str(report.keep_flag_false).lower()}`; "
            f"mtm_omitted=`{str(report.mtm_omitted).lower()}`; "
            f"dual_basis_fee_survival_passers=`{report.dual_basis_fee_survival_passers_count}`"
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
    for note in report.history_notes:
        lines.append(
            f"- `{note.get('name', '')}` **{note.get('status', '')}**: {note.get('reason', '')}"
        )
    for venue in report.venues:
        lines.extend(
            [
                "",
                (
                    f"## Print `{venue.venue_id}` (basis=`{venue.basis_venue}`; "
                    f"funding_days={venue.n_funding_days}; "
                    f"basis_days={venue.n_basis_days})"
                ),
                "",
                "### Tumbling windows (primary)",
                "",
                (
                    "| N | ladder | n | fees_usd | mean_funding | mean_basis | "
                    "mean_fee_aware | median_fee_aware | frac_fee_pos | survival_pass |"
                ),
                "| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :---: |",
            ]
        )
        for agg in venue.aggs:
            if agg.mode != "tumbling":
                continue
            mean_basis = agg.mean_basis_usd
            lines.append(
                f"| {agg.n_days} | `{agg.ladder_id}` | {agg.n_windows} | "
                f"{_fmt_usd(agg.fees_usd)} | {_fmt_usd(agg.mean_funding_usd)} | "
                f"{_fmt_usd(mean_basis)} | "
                f"{_fmt_usd(agg.mean_fee_aware_paper_pnl_usd)} | "
                f"{_fmt_usd(agg.median_fee_aware_paper_pnl_usd)} | "
                f"{_fmt_pct(agg.fraction_fee_positive)} | "
                f"{'yes' if agg.fee_survival_pass else 'no'} |"
            )
        lines.extend(
            [
                "",
                "### Sliding windows (primary ladder only)",
                "",
                "| N | n | mean_fee_aware | median_fee_aware | frac_fee_pos |",
                "| ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for agg in venue.aggs:
            if agg.mode != "sliding" or agg.ladder_id != "paper_fees_usd_10bps_x2":
                continue
            lines.append(
                f"| {agg.n_days} | {agg.n_windows} | "
                f"{_fmt_usd(agg.mean_fee_aware_paper_pnl_usd)} | "
                f"{_fmt_usd(agg.median_fee_aware_paper_pnl_usd)} | "
                f"{_fmt_pct(agg.fraction_fee_positive)} |"
            )
    lines.extend(
        [
            "",
            "## Dual-basis fee-survival passers (informational)",
            "",
            (
                ", ".join(f"`{p}`" for p in report.dual_basis_fee_survival_passers)
                if report.dual_basis_fee_survival_passers
                else (
                    "**0** dual-basis fee-survival passers "
                    f"(need frac_fee_positive ≥ {FEE_SURVIVAL_FRACTION:.0%} on both "
                    "prints, primary ladder, tumbling)."
                )
            ),
            "",
            "## Promotion decision",
            "",
            (
                "**No promote.** can_promote=false; keep_flag_false=true. "
                "Leave every PAPER_PROMOTE_*=false. Historical fee-survival "
                "replay is not a Settings pin flip and not live PnL. No live path."
            ),
            "",
        ]
    )
    return "\n".join(lines)


# re-export for CLI convenience
__all__ = [
    "CarryBasisReplayReport",
    "load_asilletto_daily_sum_abs",
    "load_basis_venue",
    "render_carry_basis_replay_markdown",
    "run_carry_basis_replay",
]
