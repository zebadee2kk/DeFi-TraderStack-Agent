"""Historical fee-aware multi-day REPLAY of fund_z_harvest_sign_hold.

Paper/research only. Never flips PAPER_PROMOTE_*. Skip-not-invent funding.
Primary metric: funding_usd - fees_usd over N-day hold windows (MTM omitted).
Dual-print = non-overlapping HL asilletto eras when HTX hourly tape absent.
"""

from __future__ import annotations

import csv
import io
import json
import math
import statistics
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from traderstack.research.edge_series import (
    ASILLETTO81_HL_ARCHIVE_FIRST_UTC,
    ASILLETTO81_HL_ARCHIVE_LAST_UTC,
    _asilletto_decompress,
    _asilletto_yyyymmdd,
)

STRATEGY_ID = "fund_z_harvest_sign_hold"
FAMILY = "fund_z_fee_aware_replay"
ASSETS: tuple[str, ...] = ("BTC", "ETH")
DEFAULT_NOTIONAL_PER_ASSET_USD = 100.0
WINDOWS_N: tuple[int, ...] = (3, 5, 7)
ERA_A_START = datetime(2024, 1, 1, tzinfo=UTC)
ERA_A_END = datetime(2025, 4, 1, tzinfo=UTC)
ERA_B_START = datetime(2025, 4, 2, tzinfo=UTC)
ERA_B_END = ASILLETTO81_HL_ARCHIVE_LAST_UTC
FEE_SURVIVAL_FRACTION = 0.55
REPLAY_RULES = (
    "Pre-registered fund_z_harvest_sign_hold fee-aware multi-day historical "
    "REPLAY (frozen before score). Always-on sign-hold; open once per N-day "
    "window; funding = notional * daily_sum_abs(|hourly|); fee_aware = "
    "funding - fees (MTM omitted). Dual era on HL asilletto when HTX hourly "
    "absent. PAPER_PROMOTE_* stays false. can_promote=false."
)


class FeeLadder(BaseModel):
    ladder_id: str
    label: str
    fee_bps: float
    slippage_bps: float
    charge_slippage_in_fees_usd: bool
    primary: bool = False

    def open_cost_usd(self, notional_per_asset_usd: float, n_assets: int) -> float:
        bps = self.fee_bps
        if self.charge_slippage_in_fees_usd:
            bps += self.slippage_bps
        return n_assets * notional_per_asset_usd * (bps / 10_000.0)


FEE_LADDERS: tuple[FeeLadder, ...] = (
    FeeLadder(
        ladder_id="paper_fees_usd_10bps_x2",
        label="Paper #176/#181 fees_usd only (PAPER_FEE_BPS=10 × 2)",
        fee_bps=10.0,
        slippage_bps=5.0,
        charge_slippage_in_fees_usd=False,
        primary=True,
    ),
    FeeLadder(
        ladder_id="paper_fee_plus_slip_15bps_x2",
        label="Paper freeze text 10+5 × 2",
        fee_bps=10.0,
        slippage_bps=5.0,
        charge_slippage_in_fees_usd=True,
        primary=False,
    ),
    FeeLadder(
        ladder_id="research_5plus5_x2",
        label="Research dual-print 5+5 × 2",
        fee_bps=5.0,
        slippage_bps=5.0,
        charge_slippage_in_fees_usd=True,
        primary=False,
    ),
)


def _utc_day(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return datetime(ts.year, ts.month, ts.day, tzinfo=UTC)


def _percentile(sorted_vals: list[float], q: float) -> float | None:
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = (len(sorted_vals) - 1) * q
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return sorted_vals[lo]
    frac = pos - lo
    return sorted_vals[lo] * (1.0 - frac) + sorted_vals[hi] * frac


def _stats(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {
            "n": 0,
            "mean": None,
            "median": None,
            "p10": None,
            "p90": None,
            "min": None,
            "max": None,
        }
    ordered = sorted(values)
    return {
        "n": len(values),
        "mean": statistics.fmean(values),
        "median": statistics.median(values),
        "p10": _percentile(ordered, 0.10),
        "p90": _percentile(ordered, 0.90),
        "min": ordered[0],
        "max": ordered[-1],
    }


def load_asilletto_daily_sum_abs(
    cache_dir: Path,
    *,
    coins: tuple[str, ...] = ASSETS,
    start: datetime = ASILLETTO81_HL_ARCHIVE_FIRST_UTC,
    end: datetime = ASILLETTO81_HL_ARCHIVE_LAST_UTC,
    compact_path: Path | None = None,
) -> tuple[dict[datetime, dict[str, float]], list[dict[str, str]]]:
    """Last funding per UTC hour → daily sum(|hourly|) per coin.

    Missing days/coins omitted (never zero-filled). Compact JSON used when present.
    """
    notes: list[dict[str, str]] = []
    if not cache_dir.is_dir():
        notes.append(
            {
                "name": "asilletto_dir",
                "status": "skipped",
                "reason": f"missing cache dir {cache_dir}",
            }
        )
        return {}, notes

    compact = compact_path or (cache_dir.parent / "daily_sum_abs_btc_eth.json")
    if compact.is_file() and compact.stat().st_size > 0:
        try:
            payload = json.loads(compact.read_text(encoding="utf-8"))
            days_raw = payload.get("days") or {}
            panel: dict[datetime, dict[str, float]] = {}
            for day_s, vals in days_raw.items():
                day = datetime.strptime(day_s, "%Y%m%d").replace(tzinfo=UTC)
                if day < _utc_day(start) or day > _utc_day(end):
                    continue
                panel_row = {
                    coin: float(vals[coin])
                    for coin in coins
                    if coin in vals and isinstance(vals[coin], (int, float))
                }
                if len(panel_row) == len(coins):
                    panel[day] = panel_row
            if panel:
                notes.append(
                    {
                        "name": "asilletto_daily_sum_abs_compact",
                        "status": "ok",
                        "reason": f"loaded {compact.name}; days={len(panel)}",
                    }
                )
                return panel, notes
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            notes.append(
                {
                    "name": "asilletto_daily_sum_abs_compact",
                    "status": "skipped",
                    "reason": f"compact unreadable: {type(exc).__name__}",
                }
            )

    want = set(coins)
    panel = {}
    day = _utc_day(start)
    end_d = _utc_day(end)
    files_read = 0
    files_missing = 0
    while day <= end_d:
        day_path = cache_dir / f"{_asilletto_yyyymmdd(day)}.csv.lz4"
        if not day_path.is_file() or day_path.stat().st_size <= 0:
            files_missing += 1
            day = day + timedelta(days=1)
            continue
        try:
            text = _asilletto_decompress(day_path.read_bytes())
        except (RuntimeError, OSError, UnicodeDecodeError, ValueError) as exc:
            notes.append(
                {
                    "name": f"asilletto_day:{_asilletto_yyyymmdd(day)}",
                    "status": "skipped",
                    "reason": f"decompress failed: {type(exc).__name__}",
                }
            )
            day = day + timedelta(days=1)
            continue
        reader = csv.reader(io.StringIO(text))
        try:
            header = next(reader)
        except StopIteration:
            day = day + timedelta(days=1)
            continue
        header_l = [h.strip().lower() for h in header]
        try:
            time_i = header_l.index("time")
            coin_i = header_l.index("coin")
            fund_i = header_l.index("funding")
        except ValueError:
            day = day + timedelta(days=1)
            continue
        # last funding print per (coin, utc_hour)
        last_hour: dict[tuple[str, int], float] = {}
        for csv_row in reader:
            if len(csv_row) <= max(time_i, coin_i, fund_i):
                continue
            coin = csv_row[coin_i].strip()
            if coin not in want:
                continue
            raw = csv_row[fund_i]
            if raw == "":
                continue
            try:
                value = float(raw)
            except (TypeError, ValueError):
                continue
            if math.isnan(value):
                continue
            ts_raw = csv_row[time_i].strip()
            try:
                if ts_raw.endswith("Z"):
                    ts = datetime.fromisoformat(ts_raw.rstrip("Z")).replace(tzinfo=UTC)
                else:
                    ts = datetime.fromisoformat(ts_raw)
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=UTC)
            except ValueError:
                continue
            hour = ts.astimezone(UTC).hour
            last_hour[(coin, hour)] = value
        by_coin: dict[str, float] = {c: 0.0 for c in coins}
        hours_seen: dict[str, int] = {c: 0 for c in coins}
        for (coin, _hour), value in last_hour.items():
            by_coin[coin] += abs(value)
            hours_seen[coin] += 1
        if all(hours_seen[c] > 0 for c in coins):
            panel[day] = {c: by_coin[c] for c in coins}
            files_read += 1
            if files_read % 100 == 0:
                print(
                    f"asilletto daily_sum_abs progress days={files_read} "
                    f"last={_asilletto_yyyymmdd(day)}",
                    flush=True,
                )
        day = day + timedelta(days=1)

    if panel:
        try:
            compact.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "method": (
                    "last funding per UTC hour → daily sum(|hourly|) for "
                    f"{','.join(coins)}; skip-not-invent"
                ),
                "days": {_asilletto_yyyymmdd(d): vals for d, vals in sorted(panel.items())},
            }
            compact.write_text(json.dumps(payload, separators=(",", ":")) + "\n", encoding="utf-8")
            notes.append(
                {
                    "name": "asilletto_daily_sum_abs_compact_write",
                    "status": "ok",
                    "reason": f"wrote {compact}; days={len(panel)}",
                }
            )
        except OSError as exc:
            notes.append(
                {
                    "name": "asilletto_daily_sum_abs_compact_write",
                    "status": "skipped",
                    "reason": f"write failed: {type(exc).__name__}",
                }
            )

    notes.append(
        {
            "name": "asilletto_daily_sum_abs_panel",
            "status": "ok" if files_read else "skipped",
            "reason": (
                f"days_with_btc_eth={files_read}; missing_or_empty_files={files_missing}; "
                f"span={_asilletto_yyyymmdd(start)}→{_asilletto_yyyymmdd(end)}"
            ),
        }
    )
    notes.append(
        {
            "name": "htx_hourly_funding",
            "status": "skipped",
            "reason": (
                "no HTX hourly funding tape on disk; dual-print uses non-overlapping "
                "HL asilletto eras (skip-not-invent)"
            ),
        }
    )
    return panel, notes


class WindowResult(BaseModel):
    start_day: str
    end_day: str
    n_days: int
    funding_usd: float
    fees_usd: float
    fee_aware_paper_pnl_usd: float
    per_asset_funding_usd: dict[str, float] = Field(default_factory=dict)


class WindowAgg(BaseModel):
    mode: Literal["tumbling", "sliding"]
    n_days: int
    ladder_id: str
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


class FeeAwareReplayReport(BaseModel):
    generated_at: datetime
    strategy_id: str = STRATEGY_ID
    family: str = FAMILY
    print_kind: Literal["dual_era", "single_era", "unavailable"]
    notional_per_asset_usd: float
    n_assets: int = 2
    windows_n: list[int] = Field(default_factory=lambda: list(WINDOWS_N))
    keep_flag_false: bool = True
    can_promote: bool = False
    mtm_omitted: bool = True
    rules: str = REPLAY_RULES
    history_notes: list[dict[str, str]] = Field(default_factory=list)
    eras: list[EraReport] = Field(default_factory=list)
    dual_era_fee_survival_passers: list[str] = Field(default_factory=list)
    dual_era_fee_survival_passers_count: int = 0
    recipe_commit: str | None = None
    honesty: str = (
        "PAPER_RESEARCH_ONLY_NOT_LIVE_PNL_NOT_PROMOTE. "
        "fee_aware_paper_pnl_usd = funding_usd - fees_usd (MTM omitted). "
        "can_promote stays false; PAPER_PROMOTE_* Field defaults stay false."
    )

    def model_dump_json_safe(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


def _ordered_days(
    panel: dict[datetime, dict[str, float]],
    *,
    start: datetime,
    end: datetime,
) -> list[datetime]:
    s = _utc_day(start)
    e = _utc_day(end)
    return sorted(d for d in panel if s <= d <= e)


def _window_funding(
    panel: dict[datetime, dict[str, float]],
    days: list[datetime],
    *,
    notional_per_asset_usd: float,
) -> tuple[float, dict[str, float]] | None:
    if not days:
        return None
    if any(d not in panel for d in days):
        return None
    per_asset = {a: 0.0 for a in ASSETS}
    for d in days:
        row = panel[d]
        for a in ASSETS:
            if a not in row:
                return None
            per_asset[a] += notional_per_asset_usd * float(row[a])
    return sum(per_asset.values()), per_asset


def _iter_windows(
    days: list[datetime],
    *,
    n: int,
    mode: Literal["tumbling", "sliding"],
) -> list[list[datetime]]:
    if n <= 0 or len(days) < n:
        return []
    step = n if mode == "tumbling" else 1
    out: list[list[datetime]] = []
    for i in range(0, len(days) - n + 1, step):
        chunk = days[i : i + n]
        # tumbling/sliding on the sorted present-day list (gaps already dropped)
        out.append(chunk)
    return out


def score_era(
    panel: dict[datetime, dict[str, float]],
    *,
    era_id: str,
    start: datetime,
    end: datetime,
    notional_per_asset_usd: float,
    ladders: tuple[FeeLadder, ...] = FEE_LADDERS,
    windows_n: tuple[int, ...] = WINDOWS_N,
) -> EraReport:
    days = _ordered_days(panel, start=start, end=end)
    aggs: list[WindowAgg] = []
    for n in windows_n:
        for mode in ("tumbling", "sliding"):
            chunks = _iter_windows(days, n=n, mode=mode)  # type: ignore[arg-type]
            for ladder in ladders:
                fees = ladder.open_cost_usd(notional_per_asset_usd, len(ASSETS))
                pnls: list[float] = []
                fundings: list[float] = []
                for chunk in chunks:
                    funded = _window_funding(
                        panel, chunk, notional_per_asset_usd=notional_per_asset_usd
                    )
                    if funded is None:
                        continue
                    funding_usd, _per = funded
                    fundings.append(funding_usd)
                    pnls.append(funding_usd - fees)
                st = _stats(pnls)
                frac = sum(1 for x in pnls if x > 0) / len(pnls) if pnls else None
                aggs.append(
                    WindowAgg(
                        mode=mode,  # type: ignore[arg-type]
                        n_days=n,
                        ladder_id=ladder.ladder_id,
                        fees_usd=fees,
                        n_windows=len(pnls),
                        mean_funding_usd=(statistics.fmean(fundings) if fundings else None),
                        mean_fee_aware_paper_pnl_usd=st["mean"],  # type: ignore[arg-type]
                        median_fee_aware_paper_pnl_usd=st["median"],  # type: ignore[arg-type]
                        p10_fee_aware_paper_pnl_usd=st["p10"],  # type: ignore[arg-type]
                        p90_fee_aware_paper_pnl_usd=st["p90"],  # type: ignore[arg-type]
                        fraction_fee_positive=frac,
                        fee_survival_pass=bool(frac is not None and frac >= FEE_SURVIVAL_FRACTION),
                    )
                )
    return EraReport(
        era_id=era_id,
        start=_asilletto_yyyymmdd(start),
        end=_asilletto_yyyymmdd(end),
        n_days_with_funding=len(days),
        aggs=aggs,
    )


def run_fee_aware_replay(
    panel: dict[datetime, dict[str, float]],
    *,
    notional_per_asset_usd: float = DEFAULT_NOTIONAL_PER_ASSET_USD,
    history_notes: list[dict[str, str]] | None = None,
    recipe_commit: str | None = None,
    now: datetime | None = None,
) -> FeeAwareReplayReport:
    notes = list(history_notes or [])
    generated = now or datetime.now(UTC)
    if not panel:
        return FeeAwareReplayReport(
            generated_at=generated,
            print_kind="unavailable",
            notional_per_asset_usd=notional_per_asset_usd,
            history_notes=notes,
            recipe_commit=recipe_commit,
        )

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
    eras = [era_a, era_b]
    usable = [e for e in eras if e.n_days_with_funding > 0]
    if len(usable) >= 2:
        print_kind: Literal["dual_era", "single_era", "unavailable"] = "dual_era"
    elif len(usable) == 1:
        print_kind = "single_era"
    else:
        print_kind = "unavailable"

    # Dual-era fee-survival passers: primary ladder + tumbling only
    passers: list[str] = []
    if print_kind == "dual_era":
        primary_ladder = next(l.ladder_id for l in FEE_LADDERS if l.primary)
        a_map = {(a.n_days, a.ladder_id): a for a in era_a.aggs if a.mode == "tumbling"}
        b_map = {(a.n_days, a.ladder_id): a for a in era_b.aggs if a.mode == "tumbling"}
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

    return FeeAwareReplayReport(
        generated_at=generated,
        print_kind=print_kind,
        notional_per_asset_usd=notional_per_asset_usd,
        history_notes=notes,
        eras=eras,
        dual_era_fee_survival_passers=passers,
        dual_era_fee_survival_passers_count=len(passers),
        can_promote=False,
        keep_flag_false=True,
        recipe_commit=recipe_commit,
    )


def _fmt_pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.1f}%"


def _fmt_usd(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.4f}"


def render_fee_aware_replay_markdown(report: FeeAwareReplayReport) -> str:
    lines = [
        "# fund_z_harvest_sign_hold fee-aware multi-day historical REPLAY",
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
            f"dual_era_fee_survival_passers=`{report.dual_era_fee_survival_passers_count}`"
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
    for era in report.eras:
        lines.extend(
            [
                "",
                (
                    f"## Era `{era.era_id}` ({era.start} → {era.end}; "
                    f"days_with_funding={era.n_days_with_funding})"
                ),
                "",
                "### Tumbling windows (primary)",
                "",
                (
                    "| N | ladder | n | fees_usd | mean_funding | mean_fee_aware | "
                    "median_fee_aware | p10 | p90 | frac_fee_pos | survival_pass |"
                ),
                "| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :---: |",
            ]
        )
        for agg in era.aggs:
            if agg.mode != "tumbling":
                continue
            lines.append(
                f"| {agg.n_days} | `{agg.ladder_id}` | {agg.n_windows} | "
                f"{_fmt_usd(agg.fees_usd)} | {_fmt_usd(agg.mean_funding_usd)} | "
                f"{_fmt_usd(agg.mean_fee_aware_paper_pnl_usd)} | "
                f"{_fmt_usd(agg.median_fee_aware_paper_pnl_usd)} | "
                f"{_fmt_usd(agg.p10_fee_aware_paper_pnl_usd)} | "
                f"{_fmt_usd(agg.p90_fee_aware_paper_pnl_usd)} | "
                f"{_fmt_pct(agg.fraction_fee_positive)} | "
                f"{'yes' if agg.fee_survival_pass else 'no'} |"
            )
        lines.extend(
            [
                "",
                "### Sliding windows (step=1; denser distribution)",
                "",
                "| N | ladder | n | fees_usd | mean_fee_aware | median_fee_aware | frac_fee_pos |",
                "| ---: | --- | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for agg in era.aggs:
            if agg.mode != "sliding":
                continue
            # Only primary ladder in sliding summary table for readability
            if agg.ladder_id != "paper_fees_usd_10bps_x2":
                continue
            lines.append(
                f"| {agg.n_days} | `{agg.ladder_id}` | {agg.n_windows} | "
                f"{_fmt_usd(agg.fees_usd)} | "
                f"{_fmt_usd(agg.mean_fee_aware_paper_pnl_usd)} | "
                f"{_fmt_usd(agg.median_fee_aware_paper_pnl_usd)} | "
                f"{_fmt_pct(agg.fraction_fee_positive)} |"
            )

    lines.extend(
        [
            "",
            "## Dual-era fee-survival passers (informational)",
            "",
            (
                ", ".join(f"`{p}`" for p in report.dual_era_fee_survival_passers)
                if report.dual_era_fee_survival_passers
                else "**0** dual-era fee-survival passers "
                f"(need frac_fee_positive ≥ {FEE_SURVIVAL_FRACTION:.0%} on both eras, "
                "primary ladder, tumbling)."
            ),
            "",
            "## Promotion decision",
            "",
            (
                "**No promote.** can_promote=false; keep_flag_false=true. "
                "Leave every PAPER_PROMOTE_*=false (including "
                "`PAPER_PROMOTE_FUND_Z_HARVEST_SIGN_HOLD`). Historical fee-survival "
                "replay is not a Settings pin flip and not live PnL. No live path."
            ),
            "",
        ]
    )
    return "\n".join(lines)
