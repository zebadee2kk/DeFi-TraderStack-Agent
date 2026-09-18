"""Operator-dated DefiLlama stablecoin chart snapshots (PIT archive).

Live ``/stablecoincharts/*`` history is not point-in-time safe (#166). This
module writes **immutable** per-UTC-day snapshots under
``var/research/defillama/stablecoincharts/as_of=YYYY-MM-DD/`` and an
append-only ``tips.jsonl`` of tip circulating observations. Historical
dual-print scoring may use **successive tip deltas** only once
``MIN_SNAPSHOT_DAYS`` distinct ``as_of`` tips exist. A single live chart
pull must never be treated as a 720-day PIT archive.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from traderstack.market.defillama_stablecoins import (
    DEFILLAMA_STABLECOINS_BASE,
    LAG_DAYS,
    PIT_VERDICT,
    STABLECOIN_CHARTS_ALL_PATH,
    StablecoinChartSeries,
    StableNetIssuancePoint,
    fetch_stablecoin_charts_all,
    parse_stablecoin_chart_rows,
)

SCHEMA_VERSION = 1
MIN_SNAPSHOT_DAYS = 720
DEFAULT_ARCHIVE_DIR = Path("var/research/defillama/stablecoincharts")
TIPS_FILENAME = "tips.jsonl"
META_FILENAME = "meta.json"
CHART_FILENAME = "chart.json"


class SnapshotMeta(BaseModel):
    schema_version: int = SCHEMA_VERSION
    as_of: date
    fetched_at: datetime
    endpoint: str
    base_url: str = DEFILLAMA_STABLECOINS_BASE
    tip_day: date | None = None
    tip_circulating_usd: float | None = None
    tip_source_date_unix: int | None = None
    point_count: int = 0
    stablecoin_id: int | None = None
    # Full chart rows inside one snapshot are the fetch-day view — not PIT history.
    pit_safe_for_historical_score: bool = False
    lag_days: int = LAG_DAYS
    notes: list[dict[str, str]] = Field(default_factory=list)


class TipRow(BaseModel):
    as_of: date
    tip_day: date
    circulating_usd: float
    fetched_at: datetime
    endpoint: str = STABLECOIN_CHARTS_ALL_PATH
    source_date_unix: int | None = None


class ArchiveCoverage(BaseModel):
    archive_dir: str
    tip_days: int = 0
    first_as_of: date | None = None
    last_as_of: date | None = None
    min_snapshot_days: int = MIN_SNAPSHOT_DAYS
    enough_for_dual_print: bool = False
    pit_verdict: str = PIT_VERDICT
    notes: list[dict[str, str]] = Field(default_factory=list)


def as_of_from_fetched_at(fetched_at: datetime) -> date:
    if fetched_at.tzinfo is None:
        fetched_at = fetched_at.replace(tzinfo=UTC)
    return fetched_at.astimezone(UTC).date()


def snapshot_dir(archive_dir: Path, as_of: date) -> Path:
    return archive_dir / f"as_of={as_of.isoformat()}"


def tips_path(archive_dir: Path) -> Path:
    return archive_dir / TIPS_FILENAME


def tip_from_series(series: StablecoinChartSeries, *, as_of: date) -> TipRow | None:
    if not series.points:
        return None
    tip = series.points[-1]
    return TipRow(
        as_of=as_of,
        tip_day=tip.day,
        circulating_usd=float(tip.circulating_usd),
        fetched_at=series.fetched_at,
        endpoint=series.endpoint,
        source_date_unix=int(tip.source_date_unix),
    )


def build_meta(
    series: StablecoinChartSeries,
    *,
    as_of: date,
    tip: TipRow | None,
    raw_row_count: int,
) -> SnapshotMeta:
    notes = list(series.notes)
    notes.append(
        {
            "name": "snapshot_meta",
            "status": "ok",
            "reason": (
                f"as_of={as_of.isoformat()}; tip_day="
                f"{tip.tip_day.isoformat() if tip else 'none'}; "
                "pit_safe_for_historical_score=false "
                "(chart rows are fetch-day view; use tips.jsonl for PIT)"
            ),
        }
    )
    return SnapshotMeta(
        as_of=as_of,
        fetched_at=series.fetched_at,
        endpoint=series.endpoint,
        tip_day=tip.tip_day if tip else None,
        tip_circulating_usd=tip.circulating_usd if tip else None,
        tip_source_date_unix=tip.source_date_unix if tip else None,
        point_count=raw_row_count,
        stablecoin_id=series.stablecoin_id,
        pit_safe_for_historical_score=False,
        notes=notes,
    )


def write_snapshot(
    archive_dir: Path,
    *,
    series: StablecoinChartSeries,
    raw_rows: list[dict[str, Any]],
    force: bool = False,
) -> tuple[SnapshotMeta, Path]:
    """Write immutable as_of snapshot + append tip. Refuses overwrite by default."""
    as_of = as_of_from_fetched_at(series.fetched_at)
    dest = snapshot_dir(archive_dir, as_of)
    meta_file = dest / META_FILENAME
    if meta_file.exists() and not force:
        raise FileExistsError(
            f"snapshot already exists for as_of={as_of.isoformat()} at {dest}; "
            "refuse overwrite (pass force=True only for operator recovery)"
        )
    archive_dir.mkdir(parents=True, exist_ok=True)
    dest.mkdir(parents=True, exist_ok=True)
    tip = tip_from_series(series, as_of=as_of)
    meta = build_meta(series, as_of=as_of, tip=tip, raw_row_count=len(raw_rows))
    (dest / CHART_FILENAME).write_text(
        json.dumps(raw_rows, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    meta_file.write_text(
        json.dumps(meta.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if tip is not None:
        _append_tip(archive_dir, tip, replace_same_as_of=force)
    return meta, dest


def _append_tip(archive_dir: Path, tip: TipRow, *, replace_same_as_of: bool) -> None:
    path = tips_path(archive_dir)
    existing = load_tips(archive_dir)
    if any(row.as_of == tip.as_of for row in existing):
        if not replace_same_as_of:
            return
        existing = [row for row in existing if row.as_of != tip.as_of]
        path.write_text(
            "".join(
                json.dumps(row.model_dump(mode="json"), sort_keys=True) + "\n"
                for row in sorted(existing + [tip], key=lambda r: r.as_of)
            ),
            encoding="utf-8",
        )
        return
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(tip.model_dump(mode="json"), sort_keys=True) + "\n")


def load_tips(archive_dir: Path) -> list[TipRow]:
    path = tips_path(archive_dir)
    if not path.is_file():
        return []
    rows: list[TipRow] = []
    seen: set[date] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        payload = json.loads(line)
        tip = TipRow.model_validate(payload)
        if tip.as_of in seen:
            continue
        seen.add(tip.as_of)
        rows.append(tip)
    rows.sort(key=lambda r: r.as_of)
    return rows


def coverage(archive_dir: Path) -> ArchiveCoverage:
    tips = load_tips(archive_dir)
    notes: list[dict[str, str]] = []
    if not tips:
        notes.append(
            {
                "name": "coverage",
                "status": "empty",
                "reason": "no tips.jsonl rows yet; dual-print unavailable",
            }
        )
        return ArchiveCoverage(archive_dir=str(archive_dir), notes=notes)
    enough = len(tips) >= MIN_SNAPSHOT_DAYS
    notes.append(
        {
            "name": "coverage",
            "status": "ok" if enough else "insufficient",
            "reason": (
                f"tip_days={len(tips)}; min={MIN_SNAPSHOT_DAYS}; "
                f"enough_for_dual_print={str(enough).lower()}"
            ),
        }
    )
    return ArchiveCoverage(
        archive_dir=str(archive_dir),
        tip_days=len(tips),
        first_as_of=tips[0].as_of,
        last_as_of=tips[-1].as_of,
        enough_for_dual_print=enough,
        notes=notes,
    )


def net_issuance_from_tips(
    tips: list[TipRow],
) -> tuple[list[StableNetIssuancePoint], list[dict[str, str]]]:
    """PIT net-issuance from successive tip observations (skip gaps)."""
    notes: list[dict[str, str]] = []
    out: list[StableNetIssuancePoint] = []
    if len(tips) < 2:
        notes.append(
            {
                "name": "tips_net_issuance",
                "status": "skipped",
                "reason": "fewer than 2 tip rows",
            }
        )
        return out, notes
    ordered = sorted(tips, key=lambda t: t.as_of)
    for prev, cur in zip(ordered, ordered[1:], strict=False):
        as_of_gap = (cur.as_of - prev.as_of).days
        tip_gap = (cur.tip_day - prev.tip_day).days
        if as_of_gap != 1 or tip_gap != 1:
            notes.append(
                {
                    "name": f"tips_gap:{cur.as_of.isoformat()}",
                    "status": "skipped",
                    "reason": (
                        f"non-consecutive tips (as_of_gap={as_of_gap}, "
                        f"tip_gap={tip_gap}); skip-not-invent"
                    ),
                }
            )
            continue
        out.append(
            StableNetIssuancePoint(
                day=cur.tip_day,
                circulating_usd=cur.circulating_usd,
                net_issuance_usd=cur.circulating_usd - prev.circulating_usd,
            )
        )
    notes.append(
        {
            "name": "tips_net_issuance",
            "status": "ok" if out else "skipped",
            "reason": f"built {len(out)} PIT net-issuance points from {len(ordered)} tips",
        }
    )
    return out, notes


def load_pit_series_from_archive(
    archive_dir: Path,
    *,
    as_of: date | None = None,
    lag_days: int = LAG_DAYS,
    min_days: int = MIN_SNAPSHOT_DAYS,
) -> tuple[StablecoinChartSeries | None, list[StableNetIssuancePoint], list[dict[str, str]], bool]:
    """Load tip-based PIT series. Returns (marker_series, points, notes, allowed).

    ``allowed`` is True only when tip coverage >= min_days and points exist after lag.
    The returned ``StablecoinChartSeries`` is a marker with ``pit_safe=True`` when
    allowed; chart ``points`` are tip circulating levels (not revised full history).
    """
    notes: list[dict[str, str]] = []
    tips = load_tips(archive_dir)
    cov = coverage(archive_dir)
    notes.extend(cov.notes)
    if len(tips) < min_days:
        notes.append(
            {
                "name": "pit_archive_gate",
                "status": "refused",
                "reason": (
                    f"tip archive has {len(tips)} days; need >= {min_days} "
                    "distinct as_of tips before historical dual-print"
                ),
            }
        )
        return None, [], notes, False

    points, iss_notes = net_issuance_from_tips(tips)
    notes.extend(iss_notes)
    decision_as_of = as_of or datetime.now(UTC).date()
    cutoff = decision_as_of - timedelta(days=lag_days)
    lagged = [p for p in points if p.day <= cutoff]
    notes.append(
        {
            "name": "lag",
            "status": "ok",
            "reason": (
                f"applied LAG_DAYS={lag_days} as_of={decision_as_of.isoformat()}; "
                f"points_after_lag={len(lagged)}"
            ),
        }
    )
    if not lagged:
        notes.append(
            {
                "name": "pit_archive_gate",
                "status": "refused",
                "reason": "no net-issuance points after lag filter",
            }
        )
        return None, [], notes, False

    # Marker series: tip circulating levels only (audit). Mark pit_safe.
    tip_points = []
    from traderstack.market.defillama_stablecoins import StablecoinChartPoint

    for tip in tips:
        tip_points.append(
            StablecoinChartPoint(
                day=tip.tip_day,
                circulating_usd=tip.circulating_usd,
                source_date_unix=int(tip.source_date_unix or 0),
            )
        )
    series = StablecoinChartSeries(
        endpoint=f"pit_tips:{archive_dir}",
        fetched_at=datetime.now(UTC),
        pit_safe=True,
        pit_verdict=(
            f"PIT tip archive with {len(tips)} as_of days "
            f"(>= {min_days}); successive tip deltas only; LAG_DAYS={lag_days}"
        ),
        points=tip_points,
        notes=notes,
    )
    notes.append(
        {
            "name": "pit_archive_gate",
            "status": "ok",
            "reason": f"allowed; tip_days={len(tips)}; lagged_points={len(lagged)}",
        }
    )
    return series, lagged, notes, True


def refuse_live_chart_as_pit_archive(payload: Any) -> tuple[bool, str]:
    """Bare chart list / live pull is never a PIT archive."""
    if isinstance(payload, list):
        return False, (
            "bare DefiLlama chart array is not a dated tip archive; "
            f"need >= {MIN_SNAPSHOT_DAYS} as_of tips under "
            "var/research/defillama/stablecoincharts/"
        )
    if isinstance(payload, dict) and payload.get("pit_safe") is True:
        # still require tip archive semantics elsewhere
        return True, "payload claims pit_safe (caller must still verify tip coverage)"
    return False, PIT_VERDICT


def render_status_markdown(cov: ArchiveCoverage) -> str:
    lines = [
        "# DefiLlama stablecoin PIT snapshot archive status",
        "",
        f"Archive: `{cov.archive_dir}`",
        f"Tip days: **{cov.tip_days}** (min for dual-print: {cov.min_snapshot_days})",
        f"First as_of: `{cov.first_as_of}`",
        f"Last as_of: `{cov.last_as_of}`",
        f"Enough for dual-print: `{str(cov.enough_for_dual_print).lower()}`",
        "",
        "## PIT verdict",
        "",
        cov.pit_verdict,
        "",
        "## Notes",
        "",
    ]
    for note in cov.notes:
        lines.append(
            f"- `{note.get('name', '?')}` **{note.get('status', '?')}**: "
            f"{note.get('reason', '')}"
        )
    lines.extend(
        [
            "",
            "## Honesty",
            "",
            (
                "A single live `/stablecoincharts/all` pull must not be scored as "
                "historical dual-print. Accumulate operator-dated tips; leave every "
                "`PAPER_PROMOTE_*` false until a committed report names a passer."
            ),
            "",
        ]
    )
    return "\n".join(lines)


async def collect_live_snapshot(
    archive_dir: Path,
    *,
    client: Any,
    force: bool = False,
) -> tuple[SnapshotMeta, Path, ArchiveCoverage]:
    series = await fetch_stablecoin_charts_all(client)
    # Re-fetch raw rows for audit store: parse already consumed JSON; caller
    # should pass raw. Here we rebuild minimal raw from series points.
    raw_rows = [
        {
            "date": str(p.source_date_unix),
            "totalCirculatingUSD": {"peggedUSD": p.circulating_usd},
        }
        for p in series.points
    ]
    meta, dest = write_snapshot(archive_dir, series=series, raw_rows=raw_rows, force=force)
    return meta, dest, coverage(archive_dir)


def write_snapshot_from_raw(
    archive_dir: Path,
    raw_rows: list[dict[str, Any]],
    *,
    fetched_at: datetime | None = None,
    endpoint: str = STABLECOIN_CHARTS_ALL_PATH,
    force: bool = False,
) -> tuple[SnapshotMeta, Path, ArchiveCoverage]:
    fetched = fetched_at or datetime.now(UTC)
    series = parse_stablecoin_chart_rows(
        raw_rows,
        fetched_at=fetched,
        endpoint=endpoint,
    )
    meta, dest = write_snapshot(archive_dir, series=series, raw_rows=raw_rows, force=force)
    return meta, dest, coverage(archive_dir)
