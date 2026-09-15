"""Coin Metrics community on-chain regime adapter (#139).

Read-only. ``GET /v4/timeseries/asset-metrics`` on the community API
(no key) for ``CapMVRVCur`` (market cap / realised cap) and
``CapMrktCurUSD`` (market cap). Verified 2026-09-13/14 from this
environment: BTC daily rows from 2010-07-18 in one ``page_size=10000``
page; ``next_page_url`` is followed when the server pages. ``CapRealUSD``
and ``SplyAct1d`` return HTTP 403 on the community plan and are **skips**,
never invented — realised cap and NUPL are derived from the two served
series by exact identity instead:

- ``realized_cap = CapMrktCurUSD / CapMVRVCur``
- ``NUPL = (mcap - realized_cap) / mcap = 1 - 1 / MVRV``

MVRV-Z and its percentile are **frozen** (``onchain-regime-v1``) before any
score was seen and are not Settings knobs on purpose:

- ``mvrv_z = (mcap - realized_cap) / pstdev(mcap over the trailing
  ONCHAIN_REGIME_WINDOW_DAYS rows)``; ``None`` until
  ``ONCHAIN_REGIME_MIN_POINTS`` rows exist in that window.
- ``mvrv_z_percentile`` = rank of today's MVRV-Z among the MVRV-Z values
  of the same trailing window (share of window values ``<=`` today's);
  ``None`` until ``ONCHAIN_REGIME_MIN_POINTS`` such values exist.

Every payload value is reduced to a bounded, typed number here. A row
with a missing, non-numeric, non-finite or non-positive metric is
dropped. A payload that is not the documented ``{"data": [...]}`` shape
(including the community 403 ``{"error": {...}}`` body) raises
``TypeError`` so the orchestrator's isolation turns it into "no snapshot".
Nothing in this module can size, side, or authorise a trade; the runtime
gate in ``pipeline.py`` only *adds* a rejection reason.
"""

from __future__ import annotations

import asyncio
import bisect
import json
import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field

from traderstack.intelligence import OnChainRegimeSnapshot

COINMETRICS_COMMUNITY_BASE_URL = "https://community-api.coinmetrics.io"
ASSET_METRICS_PATH = "/v4/timeseries/asset-metrics"
REGIME_METRICS: tuple[str, ...] = ("CapMVRVCur", "CapMrktCurUSD")
PAGE_SIZE = 10_000
# Coin Metrics documents the community plan at 10 requests / 6 s. One
# history pull per run / per UTC day per process, and a polite pause
# between pages when the server does page.
PAGE_SLEEP_SECONDS = 0.7
MAX_PAGES = 50
DEFAULT_START_TIME = "2010-07-18"
# Frozen (pre-registered) derivation constants — not Settings.
ONCHAIN_REGIME_WINDOW_DAYS = 1460
ONCHAIN_REGIME_MIN_POINTS = 730
ONCHAIN_REGIME_MAX_STALE_DAYS = 3
ONCHAIN_REGIME_FEATURE_VERSION = "onchain-regime-v1"
COINMETRICS_SOURCE_ID = "coinmetrics:community:v4:CapMVRVCur+CapMrktCurUSD"
# Bounds applied to every derived value before it leaves the adapter.
MVRV_Z_BOUNDS = (-10.0, 10.0)
NUPL_BOUNDS = (-5.0, 1.0)
COINMETRICS_SKIPPED_METRICS_NOTE = (
    "CapRealUSD and SplyAct1d return HTTP 403 ('not available with supplied "
    "credentials') on the Coin Metrics community plan and are skipped, not "
    "invented; realised cap is CapMrktCurUSD / CapMVRVCur and NUPL is 1 - 1/MVRV "
    "(exact identities)."
)


class OnChainDailyRow(BaseModel):
    """One committed daily row after bounded reduction."""

    model_config = ConfigDict(frozen=True)

    asset: str
    day: date
    mvrv: float = Field(gt=0)
    market_cap_usd: float = Field(gt=0)

    @property
    def realized_cap_usd(self) -> float:
        return self.market_cap_usd / self.mvrv


class OnChainRegimePoint(BaseModel):
    """Derived, versioned, bounded regime values for one day."""

    model_config = ConfigDict(frozen=True)

    day: date
    mvrv: float = Field(gt=0)
    market_cap_usd: float = Field(gt=0)
    realized_cap_usd: float = Field(gt=0)
    nupl: float = Field(ge=NUPL_BOUNDS[0], le=NUPL_BOUNDS[1])
    mvrv_z: float | None = Field(default=None, ge=MVRV_Z_BOUNDS[0], le=MVRV_Z_BOUNDS[1])
    mvrv_z_percentile: float | None = Field(default=None, ge=0, le=1)
    # Rows inside the trailing window at this point (<= window_days).
    points: int = Field(ge=0)
    feature_version: str = ONCHAIN_REGIME_FEATURE_VERSION


def _clip(value: float, bounds: tuple[float, float]) -> float:
    return max(bounds[0], min(bounds[1], value))


def _as_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        try:
            number = float(value.strip())
        except ValueError:
            return None
    else:
        return None
    if not math.isfinite(number):
        return None
    return number


def _as_day(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.astimezone(UTC).date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    # Coin Metrics prints nanoseconds ("...T00:00:00.000000000Z"); trim to µs.
    if "." in text:
        head, tail = text.split(".", 1)
        digits = ""
        rest = ""
        for index, char in enumerate(tail):
            if char.isdigit():
                digits += char
            else:
                rest = tail[index:]
                break
        text = f"{head}.{digits[:6]}{rest}" if digits else f"{head}{rest}"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).date()


def _rows_from_payload(payload: object) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        raise TypeError("unexpected Coin Metrics response (not an object)")
    error = payload.get("error")
    if error is not None:
        message = ""
        if isinstance(error, dict):
            message = str(error.get("message") or error.get("type") or "")
        raise TypeError(f"Coin Metrics error response: {message or error!r}")
    rows = payload.get("data")
    if not isinstance(rows, list):
        raise TypeError("unexpected Coin Metrics payload (no data list)")
    return [row for row in rows if isinstance(row, dict)]


def parse_asset_metric_rows(
    payload: object,
    *,
    asset: str,
    mvrv_metric: str = REGIME_METRICS[0],
    market_cap_metric: str = REGIME_METRICS[1],
) -> tuple[OnChainDailyRow, ...]:
    """Reduce one ``asset-metrics`` page to bounded rows for ``asset``.

    String-valued metrics become floats; rows with a missing, non-finite
    or non-positive metric, an unparsable time, or another asset are
    dropped. Duplicate days keep the last occurrence. Output is sorted.
    """
    wanted = asset.strip().lower()
    by_day: dict[date, OnChainDailyRow] = {}
    for row in _rows_from_payload(payload):
        row_asset = str(row.get("asset") or wanted).strip().lower()
        if row_asset != wanted:
            continue
        day = _as_day(row.get("time"))
        mvrv = _as_float(row.get(mvrv_metric))
        market_cap = _as_float(row.get(market_cap_metric))
        if day is None or mvrv is None or market_cap is None:
            continue
        if mvrv <= 0 or market_cap <= 0:
            continue
        by_day[day] = OnChainDailyRow(asset=wanted, day=day, mvrv=mvrv, market_cap_usd=market_cap)
    return tuple(by_day[key] for key in sorted(by_day))


def drop_uncommitted_rows(
    rows: tuple[OnChainDailyRow, ...], *, today: date | None = None
) -> tuple[OnChainDailyRow, ...]:
    """Drop rows dated today UTC (or later): a daily row for D is final
    only after D closes (mirrors ``binance_spot._drop_uncommitted``)."""
    cutoff = today or datetime.now(UTC).date()
    return tuple(row for row in rows if row.day < cutoff)


def _window_pstdev(values: list[float]) -> float:
    count = len(values)
    if count == 0:
        return 0.0
    mean = sum(values) / count
    return math.sqrt(sum((item - mean) ** 2 for item in values) / count)


def derive_regime_series(
    rows: tuple[OnChainDailyRow, ...],
    *,
    window_days: int = ONCHAIN_REGIME_WINDOW_DAYS,
    min_points: int = ONCHAIN_REGIME_MIN_POINTS,
) -> tuple[OnChainRegimePoint, ...]:
    """Frozen ``onchain-regime-v1`` derivation. Pure Python; no look-ahead:
    the value at row *i* uses rows ``[i - window_days + 1, i]`` only."""
    if window_days <= 0 or min_points <= 0:
        raise ValueError("window_days and min_points must be positive")
    ordered = tuple(sorted(rows, key=lambda row: row.day))
    points: list[OnChainRegimePoint] = []
    caps: list[float] = []
    z_window: list[float] = []  # sorted MVRV-Z values inside the trailing window
    z_by_index: list[float | None] = []
    for index, row in enumerate(ordered):
        caps.append(row.market_cap_usd)
        if len(caps) > window_days:
            caps.pop(0)
        realized = row.realized_cap_usd
        nupl = _clip((row.market_cap_usd - realized) / row.market_cap_usd, NUPL_BOUNDS)
        mvrv_z: float | None = None
        if len(caps) >= min_points:
            stdev = _window_pstdev(caps)
            if stdev > 0:
                mvrv_z = _clip((row.market_cap_usd - realized) / stdev, MVRV_Z_BOUNDS)
        # Maintain the sorted set of z values for rows inside the window.
        leaving = index - window_days
        if leaving >= 0:
            old = z_by_index[leaving]
            if old is not None:
                position = bisect.bisect_left(z_window, old)
                if position < len(z_window) and z_window[position] == old:
                    del z_window[position]
        percentile: float | None = None
        if mvrv_z is not None:
            bisect.insort(z_window, mvrv_z)
            if len(z_window) >= min_points:
                percentile = bisect.bisect_right(z_window, mvrv_z) / len(z_window)
                percentile = _clip(percentile, (0.0, 1.0))
        z_by_index.append(mvrv_z)
        points.append(
            OnChainRegimePoint(
                day=row.day,
                mvrv=row.mvrv,
                market_cap_usd=row.market_cap_usd,
                realized_cap_usd=realized,
                nupl=nupl,
                mvrv_z=mvrv_z,
                mvrv_z_percentile=percentile,
                points=len(caps),
            )
        )
    return tuple(points)


def regime_point_before(
    series: tuple[OnChainRegimePoint, ...],
    decision_at: datetime,
    *,
    max_stale_days: int = ONCHAIN_REGIME_MAX_STALE_DAYS,
) -> OnChainRegimePoint | None:
    """Newest point whose day (at 00:00 UTC) is **strictly before**
    ``decision_at``; ``None`` when that point is older than
    ``max_stale_days`` relative to the decision day (no forward-fill)."""
    if decision_at.tzinfo is None:
        decision_at = decision_at.replace(tzinfo=UTC)
    decision_at = decision_at.astimezone(UTC)
    newest: OnChainRegimePoint | None = None
    for point in series:
        day_start = datetime(point.day.year, point.day.month, point.day.day, tzinfo=UTC)
        if day_start < decision_at and (newest is None or point.day > newest.day):
            newest = point
    if newest is None:
        return None
    if (decision_at.date() - newest.day).days > max_stale_days:
        return None
    return newest


SleepFn = Callable[[float], Awaitable[None]]


async def fetch_asset_metric_rows(
    client: httpx.AsyncClient,
    *,
    asset: str = "btc",
    start_time: str | None = DEFAULT_START_TIME,
    page_size: int = PAGE_SIZE,
    metrics: tuple[str, ...] = REGIME_METRICS,
    sleep: SleepFn = asyncio.sleep,
    page_sleep_seconds: float = PAGE_SLEEP_SECONDS,
    max_pages: int = MAX_PAGES,
) -> tuple[OnChainDailyRow, ...]:
    """Pull the daily series, following ``next_page_url`` politely."""
    params: dict[str, str | int] = {
        "assets": asset.strip().lower(),
        "metrics": ",".join(metrics),
        "frequency": "1d",
        "page_size": page_size,
    }
    if start_time:
        params["start_time"] = start_time
    collected: dict[date, OnChainDailyRow] = {}
    response = await client.get(ASSET_METRICS_PATH, params=params)
    for _page in range(max_pages):
        if response.status_code == 403:
            # Surface the community-plan message instead of a bare 403.
            try:
                _rows_from_payload(response.json())
            except (TypeError, ValueError) as exc:
                raise httpx.HTTPStatusError(
                    str(exc), request=response.request, response=response
                ) from exc
        response.raise_for_status()
        payload = response.json()
        for row in parse_asset_metric_rows(payload, asset=asset):
            collected[row.day] = row
        next_url = payload.get("next_page_url") if isinstance(payload, dict) else None
        if not isinstance(next_url, str) or not next_url.strip():
            break
        await sleep(page_sleep_seconds)
        response = await client.get(next_url)
    return tuple(collected[key] for key in sorted(collected))


def save_regime_rows_json(path: Path, rows: tuple[OnChainDailyRow, ...]) -> None:
    payload = [
        {
            "asset": row.asset,
            "day": row.day.isoformat(),
            "mvrv": row.mvrv,
            "market_cap_usd": row.market_cap_usd,
        }
        for row in rows
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) + "\n")


def load_regime_rows_json(path: Path) -> tuple[OnChainDailyRow, ...]:
    raw = json.loads(path.read_text())
    if not isinstance(raw, list):
        raise TypeError(f"{path}: expected a JSON list of rows")
    by_day: dict[date, OnChainDailyRow] = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        day = _as_day(item.get("day") or item.get("time"))
        mvrv = _as_float(item.get("mvrv"))
        market_cap = _as_float(item.get("market_cap_usd"))
        if day is None or mvrv is None or market_cap is None or mvrv <= 0 or market_cap <= 0:
            continue
        asset = str(item.get("asset") or "btc").strip().lower()
        by_day[day] = OnChainDailyRow(asset=asset, day=day, mvrv=mvrv, market_cap_usd=market_cap)
    return tuple(by_day[key] for key in sorted(by_day))


def snapshot_from_series(
    series: tuple[OnChainRegimePoint, ...],
    *,
    asset: str,
    source_asset: str,
    observed_at: datetime,
) -> OnChainRegimeSnapshot:
    if not series:
        raise ValueError("no committed Coin Metrics rows to build a regime snapshot from")
    latest = series[-1]
    return OnChainRegimeSnapshot(
        asset=asset.upper(),
        source_asset=source_asset.lower(),
        observed_at=observed_at,
        as_of=latest.day,
        mvrv_z=latest.mvrv_z,
        mvrv_z_percentile=latest.mvrv_z_percentile,
        nupl=latest.nupl,
        points=latest.points,
        window_days=ONCHAIN_REGIME_WINDOW_DAYS,
        feature_version=ONCHAIN_REGIME_FEATURE_VERSION,
        source_id=COINMETRICS_SOURCE_ID,
    )


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass
class CoinMetricsRegimeProvider:
    """Fetch-and-derive provider for the ``onchain_regime`` intelligence slot.

    ``fetch(asset)`` returns the BTC-derived regime for *any* requested
    asset (frozen market-regime assumption; ``source_asset`` says so on the
    snapshot). One HTTP pull per UTC day per process; a failed pull raises
    so the orchestrator records "no snapshot" and the pipeline gate fails
    closed for new longs.
    """

    base_url: str = COINMETRICS_COMMUNITY_BASE_URL
    source_asset: str = "btc"
    client: httpx.AsyncClient | None = None
    clock: Callable[[], datetime] = _utc_now
    timeout_seconds: float = 20.0
    _cache: dict[str, tuple[date, tuple[OnChainRegimePoint, ...]]] = field(
        default_factory=dict, repr=False
    )

    async def _series(self) -> tuple[OnChainRegimePoint, ...]:
        now = self.clock()
        today = now.astimezone(UTC).date()
        cached = self._cache.get(self.source_asset)
        if cached is not None and cached[0] == today:
            return cached[1]
        if self.client is not None:
            rows = await fetch_asset_metric_rows(self.client, asset=self.source_asset)
        else:
            async with httpx.AsyncClient(
                base_url=self.base_url.rstrip("/"), timeout=self.timeout_seconds
            ) as client:
                rows = await fetch_asset_metric_rows(client, asset=self.source_asset)
        committed = drop_uncommitted_rows(rows, today=today)
        series = derive_regime_series(committed)
        if not series:
            raise ValueError("Coin Metrics returned no committed rows")
        self._cache[self.source_asset] = (today, series)
        return series

    async def fetch(self, asset: str) -> OnChainRegimeSnapshot:
        series = await self._series()
        return snapshot_from_series(
            series,
            asset=asset,
            source_asset=self.source_asset,
            observed_at=self.clock(),
        )
