"""DefiLlama stablecoin circulating / net-issuance fetcher (paper research).

Public host: ``https://stablecoins.llama.fi``. Historical charts from a live
pull are **not** point-in-time safe (no ``as_of``, revisions overwrite). This
module fetches and normalises series, stamps ``fetched_at``, and refuses to
claim PIT safety for live history. Skip-not-invent on missing days.
"""

from __future__ import annotations

import itertools
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
from pydantic import BaseModel, Field

DEFILLAMA_STABLECOINS_BASE = "https://stablecoins.llama.fi"
STABLECOIN_CHARTS_ALL_PATH = "/stablecoincharts/all"
STABLECOINS_LIST_PATH = "/stablecoins"
LAG_DAYS = 2
PIT_SAFE_LIVE_HISTORY = False
PIT_VERDICT = (
    "NOT_PIT_SAFE: DefiLlama /stablecoincharts/* returns the current view of "
    "history with no as_of/revision feed; past circulating values may be "
    "rewritten. Live pulls must not score historical dual-prints. Forward "
    "paper use requires operator-dated snapshot archives + LAG_DAYS="
    f"{LAG_DAYS}."
)


class StablecoinChartPoint(BaseModel):
    day: date
    circulating_usd: float
    source_date_unix: int


class StableNetIssuancePoint(BaseModel):
    day: date
    circulating_usd: float
    net_issuance_usd: float


class StablecoinChartSeries(BaseModel):
    source: str = "defillama_stablecoins"
    endpoint: str
    stablecoin_id: int | None = None
    fetched_at: datetime
    pit_safe: bool = False
    pit_verdict: str = PIT_VERDICT
    lag_days: int = LAG_DAYS
    points: list[StablecoinChartPoint] = Field(default_factory=list)
    skipped_days: list[str] = Field(default_factory=list)
    notes: list[dict[str, str]] = Field(default_factory=list)


def _pegged_usd(blob: Any) -> float | None:
    if not isinstance(blob, dict):
        return None
    raw = blob.get("peggedUSD")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def parse_stablecoin_chart_rows(
    rows: list[dict[str, Any]],
    *,
    fetched_at: datetime | None = None,
    endpoint: str = STABLECOIN_CHARTS_ALL_PATH,
    stablecoin_id: int | None = None,
) -> StablecoinChartSeries:
    """Parse DefiLlama chart JSON into dated circulating points (skip-not-invent)."""
    fetched = fetched_at or datetime.now(UTC)
    points: list[StablecoinChartPoint] = []
    skipped: list[str] = []
    notes: list[dict[str, str]] = []
    if not isinstance(rows, list):
        notes.append(
            {
                "name": "parse_stablecoin_chart_rows",
                "status": "skipped",
                "reason": "payload is not a list",
            }
        )
        return StablecoinChartSeries(
            endpoint=endpoint,
            stablecoin_id=stablecoin_id,
            fetched_at=fetched,
            pit_safe=False,
            notes=notes,
            skipped_days=skipped,
        )
    for row in rows:
        if not isinstance(row, dict):
            skipped.append("non_object_row")
            continue
        try:
            ts = int(row["date"])
        except (KeyError, TypeError, ValueError):
            skipped.append("bad_date")
            continue
        circ = _pegged_usd(row.get("totalCirculatingUSD"))
        if circ is None:
            circ = _pegged_usd(row.get("totalCirculating"))
        if circ is None:
            skipped.append(str(ts))
            continue
        day = datetime.fromtimestamp(ts, tz=UTC).date()
        points.append(StablecoinChartPoint(day=day, circulating_usd=circ, source_date_unix=ts))
    points.sort(key=lambda p: p.day)
    # drop duplicate days keeping last
    dedup: dict[date, StablecoinChartPoint] = {}
    for point in points:
        dedup[point.day] = point
    ordered = [dedup[k] for k in sorted(dedup)]
    notes.append(
        {
            "name": "parse_stablecoin_chart_rows",
            "status": "ok",
            "reason": (
                f"parsed {len(ordered)} circulating days; skipped={len(skipped)}; "
                f"pit_safe=false ({PIT_VERDICT[:80]}…)"
            ),
        }
    )
    return StablecoinChartSeries(
        endpoint=endpoint,
        stablecoin_id=stablecoin_id,
        fetched_at=fetched,
        pit_safe=False,
        points=ordered,
        skipped_days=sorted(set(skipped))[:50],
        notes=notes,
    )


def net_issuance_from_chart(
    series: StablecoinChartSeries,
) -> tuple[list[StableNetIssuancePoint], list[dict[str, str]]]:
    """Consecutive Δ circulating; gaps skip (never invent)."""
    notes: list[dict[str, str]] = []
    out: list[StableNetIssuancePoint] = []
    points = series.points
    if len(points) < 2:
        notes.append(
            {
                "name": "net_issuance",
                "status": "skipped",
                "reason": "fewer than 2 circulating points",
            }
        )
        return out, notes
    for prev, cur in itertools.pairwise(points):
        gap = (cur.day - prev.day).days
        if gap != 1:
            notes.append(
                {
                    "name": f"net_issuance_gap:{cur.day.isoformat()}",
                    "status": "skipped",
                    "reason": f"non-consecutive days (gap={gap}); skip-not-invent",
                }
            )
            continue
        out.append(
            StableNetIssuancePoint(
                day=cur.day,
                circulating_usd=cur.circulating_usd,
                net_issuance_usd=cur.circulating_usd - prev.circulating_usd,
            )
        )
    notes.append(
        {
            "name": "net_issuance",
            "status": "ok" if out else "skipped",
            "reason": f"built {len(out)} net-issuance points from {len(points)} circ days",
        }
    )
    return out, notes


def apply_lag(
    points: list[StableNetIssuancePoint],
    *,
    as_of: date,
    lag_days: int = LAG_DAYS,
) -> list[StableNetIssuancePoint]:
    """Keep feature days with day <= as_of - lag_days (forward paper lag)."""
    cutoff = as_of - timedelta(days=lag_days)
    return [p for p in points if p.day <= cutoff]


def refuse_live_history_for_backtest(
    *,
    pit_archive_present: bool,
    series_pit_safe: bool = False,
) -> tuple[bool, str]:
    """Return (allowed, reason). Live history never allowed for dual-print score."""
    if pit_archive_present and series_pit_safe:
        return True, "operator PIT archive marked pit_safe"
    if pit_archive_present and not series_pit_safe:
        return False, "pit archive present but not marked pit_safe; refuse"
    return False, PIT_VERDICT


async def fetch_stablecoin_charts_all(
    client: httpx.AsyncClient,
    *,
    stablecoin_id: int | None = None,
    timeout: float = 60.0,
) -> StablecoinChartSeries:
    params: dict[str, Any] = {}
    if stablecoin_id is not None:
        params["stablecoin"] = int(stablecoin_id)
    response = await client.get(
        STABLECOIN_CHARTS_ALL_PATH,
        params=params or None,
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        raise TypeError("stablecoincharts/all did not return a list")
    endpoint = STABLECOIN_CHARTS_ALL_PATH
    if stablecoin_id is not None:
        endpoint = f"{STABLECOIN_CHARTS_ALL_PATH}?stablecoin={stablecoin_id}"
    return parse_stablecoin_chart_rows(
        payload,
        fetched_at=datetime.now(UTC),
        endpoint=endpoint,
        stablecoin_id=stablecoin_id,
    )


async def fetch_stablecoins_catalog(
    client: httpx.AsyncClient,
    *,
    timeout: float = 60.0,
) -> list[dict[str, Any]]:
    response = await client.get(STABLECOINS_LIST_PATH, timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    assets = payload.get("peggedAssets", []) if isinstance(payload, dict) else []
    if not isinstance(assets, list):
        return []
    return assets
