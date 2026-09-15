"""Binance Vision daily point-in-time mark−index basis (#134). Research only.

Verified 2026-09-13 (unauthenticated S3 GET, while ``fapi.binance.com``
REST is HTTP 451 from this environment):

* ``https://data.binance.vision/data/futures/um/monthly/{markPriceKlines,
  indexPriceKlines}/{SYMBOL}/1d/{SYMBOL}-1d-YYYY-MM.zip`` returns 200
  from 2020-01 (BTCUSDT and ETHUSDT). 2026-08 is 200; 2026-09 (the
  trailing partial month) is 404 and is covered by
  ``.../daily/.../{SYMBOL}-1d-YYYY-MM-DD.zip`` (2026-09-12 is 200).
* Every zip has a sibling ``.CHECKSUM`` (``sha256  filename``). It is
  verified before a byte is parsed; a mismatch or a missing checksum
  **fails closed** — that month / day is skipped, never used and never
  filled from another source.
* Each zip holds one CSV ``open_time,open,high,low,close,...``; newer
  files carry a header row, 2020 files do not. Timestamps are epoch
  milliseconds (microseconds and seconds are normalised defensively).

Only ``markPriceKlines`` and ``indexPriceKlines`` are ever requested.
``premiumIndexKlines`` (funding premium), ``klines`` (last-trade),
``fundingRate``, ``aggTrades`` and ``trades`` are refused by
:func:`traderstack.research.basis.refuse_forbidden_basis_source`.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import math
import zipfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx

from traderstack.research.basis import (
    basis_from_closes,
    refuse_forbidden_basis_source,
    utc_day,
    yesterday_utc,
)
from traderstack.research.edge_series import (
    EdgeSeriesFetch,
    _finish,
    _ms_to_dt,
    binance_contract,
)

BINANCE_VISION_BASE = "https://data.binance.vision"
VISION_UM_PREFIX = "/data/futures/um"
VISION_MARK_KIND = "markPriceKlines"
VISION_INDEX_KIND = "indexPriceKlines"
VISION_ALLOWED_KINDS: tuple[str, ...] = (VISION_MARK_KIND, VISION_INDEX_KIND)
VISION_FORBIDDEN_KINDS: tuple[str, ...] = (
    "premiumIndexKlines",
    "klines",
    "fundingRate",
    "aggTrades",
    "trades",
)
VISION_BASIS_SOURCE = "binance_vision:markPriceKlines−indexPriceKlines (USDT-M; quote USDT)"
VISION_REQUEST_PAUSE_SECONDS = 0.2
DEFAULT_VISION_CACHE_DIR = Path("var/research/binance_vision")
# A daily-kline CSV for one month is a few KB; refuse anything absurd
# before decompressing it (untrusted archive content).
VISION_MAX_CSV_BYTES = 8 * 1024 * 1024

SleepFn = Callable[[float], Awaitable[None]]


def _check_kind(kind: str) -> None:
    if kind in VISION_FORBIDDEN_KINDS or kind not in VISION_ALLOWED_KINDS:
        raise ValueError(
            f"refused Binance Vision kind {kind!r}: only "
            f"{'/'.join(VISION_ALLOWED_KINDS)} form mark−index basis"
        )
    refuse_forbidden_basis_source(kind)


def vision_zip_path(
    kind: str,
    contract: str,
    *,
    month: tuple[int, int] | None = None,
    day: date | None = None,
) -> str:
    """Published S3 key for one monthly or daily 1d kline zip."""
    _check_kind(kind)
    if (month is None) == (day is None):
        raise ValueError("pass exactly one of month=(year, month) or day=date")
    if month is not None:
        year, month_number = month
        return (
            f"{VISION_UM_PREFIX}/monthly/{kind}/{contract}/1d/"
            f"{contract}-1d-{year:04d}-{month_number:02d}.zip"
        )
    assert day is not None
    return f"{VISION_UM_PREFIX}/daily/{kind}/{contract}/1d/{contract}-1d-{day.isoformat()}.zip"


def normalize_epoch_ms(value: int) -> int:
    """Seconds / milliseconds / microseconds → milliseconds."""
    if value > 10**14:
        return value // 1000
    if value < 10**11:
        return value * 1000
    return value


def parse_vision_kline_csv(data: bytes) -> list[tuple[int, float]]:
    """``[(open_time_ms, close), ...]`` — header row optional, bad rows skipped."""
    text = data.decode("utf-8", errors="replace")
    rows: list[tuple[int, float]] = []
    for line in text.splitlines():
        parts = line.strip().split(",")
        if len(parts) < 5:
            continue
        try:
            open_time = int(parts[0])
            close = float(parts[4])
        except ValueError:
            continue  # header row or corrupt line
        if open_time <= 0 or not math.isfinite(close) or close <= 0:
            continue
        rows.append((normalize_epoch_ms(open_time), close))
    return rows


def verify_vision_checksum(zip_bytes: bytes, checksum_text: str, filename: str) -> None:
    """Raise ``ValueError`` unless ``checksum_text`` is ``sha256  filename`` for *zip_bytes*."""
    parts = checksum_text.strip().split()
    if not parts:
        raise ValueError("empty .CHECKSUM")
    expected = parts[0].lower()
    if len(expected) != 64:
        raise ValueError(".CHECKSUM is not a sha256 digest")
    if len(parts) > 1 and parts[1].strip("*") != filename:
        raise ValueError(f".CHECKSUM names {parts[1]!r}, not {filename!r}")
    actual = hashlib.sha256(zip_bytes).hexdigest()
    if actual != expected:
        raise ValueError("sha256 mismatch")


def unzip_single_csv(data: bytes) -> bytes:
    """Extract the single CSV member; refuse multi-member or oversized archives."""
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        members = archive.infolist()
        if len(members) != 1 or not members[0].filename.lower().endswith(".csv"):
            raise ValueError(
                f"expected exactly one CSV member, got {[m.filename for m in members]}"
            )
        info = members[0]
        if info.file_size > VISION_MAX_CSV_BYTES:
            raise ValueError(f"CSV member too large ({info.file_size} bytes)")
        return archive.read(info)


def _cache_paths(cache_dir: Path, path: str) -> tuple[Path, Path]:
    relative = path.lstrip("/")
    zip_path = cache_dir / relative
    return zip_path, zip_path.with_name(zip_path.name + ".CHECKSUM")


async def fetch_vision_zip(
    client: httpx.AsyncClient,
    path: str,
    *,
    cache_dir: Path,
    pause_seconds: float = VISION_REQUEST_PAUSE_SECONDS,
    sleep: SleepFn = asyncio.sleep,
) -> tuple[bytes | None, str]:
    """Return ``(zip_bytes, status)``; bytes only when the checksum verified.

    ``status`` is ``"ok"``, ``"cache"``, ``"404"`` or a fail-closed reason.
    Cached bytes are re-verified against the cached checksum on every read.
    """
    refuse_forbidden_basis_source(path)
    filename = path.rsplit("/", 1)[-1]
    zip_path, checksum_path = _cache_paths(cache_dir, path)
    if zip_path.is_file() and checksum_path.is_file():
        cached = zip_path.read_bytes()
        try:
            verify_vision_checksum(cached, checksum_path.read_text(), filename)
        except ValueError:
            pass  # stale / corrupt cache entry: refetch below
        else:
            return cached, "cache"
    try:
        response = await client.get(path)
    except httpx.HTTPError as exc:
        return None, f"transport error ({exc})"
    if pause_seconds > 0:
        await sleep(pause_seconds)
    if response.status_code == 404:
        return None, "404"
    if response.status_code != 200 or not response.content:
        return None, f"HTTP {response.status_code}"
    try:
        checksum_response = await client.get(path + ".CHECKSUM")
    except httpx.HTTPError as exc:
        return None, f"checksum transport error ({exc}); fail closed"
    if pause_seconds > 0:
        await sleep(pause_seconds)
    if checksum_response.status_code != 200 or not checksum_response.text.strip():
        return None, f"missing .CHECKSUM (HTTP {checksum_response.status_code}); fail closed"
    try:
        verify_vision_checksum(response.content, checksum_response.text, filename)
    except ValueError as exc:
        return None, f"checksum mismatch ({exc}); fail closed"
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    zip_path.write_bytes(response.content)
    checksum_path.write_text(checksum_response.text)
    return response.content, "ok"


@dataclass
class VisionCloses:
    closes: dict[datetime, float] = field(default_factory=dict)
    months_ok: int = 0
    months_missing: int = 0
    days_ok: int = 0
    days_missing: int = 0
    checksum_failures: int = 0
    notes: list[str] = field(default_factory=list)


def _month_bounds(year: int, month: int) -> tuple[datetime, datetime]:
    start = datetime(year, month, 1, tzinfo=UTC)
    if month == 12:
        next_start = datetime(year + 1, 1, 1, tzinfo=UTC)
    else:
        next_start = datetime(year, month + 1, 1, tzinfo=UTC)
    return start, next_start - timedelta(days=1)


def _rows_from_zip(data: bytes) -> list[tuple[int, float]] | None:
    try:
        return parse_vision_kline_csv(unzip_single_csv(data))
    except (zipfile.BadZipFile, ValueError, OSError):
        return None


async def fetch_binance_vision_daily_closes(
    client: httpx.AsyncClient,
    kind: str,
    contract: str,
    *,
    since: datetime,
    until: datetime,
    cache_dir: Path | None = None,
    pause_seconds: float = VISION_REQUEST_PAUSE_SECONDS,
    sleep: SleepFn = asyncio.sleep,
    now: datetime | None = None,
) -> VisionCloses:
    """Daily closes for one kline kind over ``[since, until]`` (UTC day opens).

    Complete months come from monthly zips; a month whose monthly zip is
    404 (not yet published) and the trailing partial month come from
    daily zips up to yesterday UTC. A checksum failure skips that month
    or day outright (fail closed). Nothing is filled.
    """
    _check_kind(kind)
    cache = cache_dir or DEFAULT_VISION_CACHE_DIR
    result = VisionCloses()
    since_d = utc_day(since)
    until_d = min(utc_day(until), yesterday_utc(now))
    if since_d > until_d:
        result.notes.append("empty window after clamping to yesterday UTC")
        return result
    year, month = since_d.year, since_d.month
    while (year, month) <= (until_d.year, until_d.month):
        month_start, month_end = _month_bounds(year, month)
        rows: list[tuple[int, float]] | None = None
        skip_daily = False
        if month_end <= until_d:
            data, status = await fetch_vision_zip(
                client,
                vision_zip_path(kind, contract, month=(year, month)),
                cache_dir=cache,
                pause_seconds=pause_seconds,
                sleep=sleep,
            )
            if data is not None:
                rows = _rows_from_zip(data)
                if rows is None:
                    result.notes.append(f"{year:04d}-{month:02d} monthly zip unreadable; skipped")
                    skip_daily = True
                else:
                    result.months_ok += 1
            elif status != "404":
                result.checksum_failures += 1
                result.notes.append(f"{year:04d}-{month:02d} monthly: {status}")
                skip_daily = True
            if rows is None:
                result.months_missing += 1
        if rows is None and not skip_daily:
            rows = []
            day = max(since_d, month_start)
            last_day = min(until_d, month_end)
            while day <= last_day:
                data, status = await fetch_vision_zip(
                    client,
                    vision_zip_path(kind, contract, day=day.date()),
                    cache_dir=cache,
                    pause_seconds=pause_seconds,
                    sleep=sleep,
                )
                if data is not None:
                    day_rows = _rows_from_zip(data)
                    if day_rows is None:
                        result.days_missing += 1
                        result.notes.append(f"{day.date()} daily zip unreadable; skipped")
                    else:
                        rows.extend(day_rows)
                        result.days_ok += 1
                else:
                    result.days_missing += 1
                    if status != "404":
                        result.checksum_failures += 1
                        result.notes.append(f"{day.date()} daily: {status}")
                day += timedelta(days=1)
        for ts_ms, close in rows or []:
            open_day = utc_day(_ms_to_dt(ts_ms))
            if since_d <= open_day <= until_d:
                result.closes[open_day] = close
        month += 1
        if month > 12:
            month = 1
            year += 1
    return result


async def fetch_binance_vision_basis(
    symbol: str,
    *,
    client: httpx.AsyncClient,
    since: datetime,
    until: datetime,
    cache_dir: Path | None = None,
    pause_seconds: float = VISION_REQUEST_PAUSE_SECONDS,
    sleep: SleepFn = asyncio.sleep,
    now: datetime | None = None,
) -> EdgeSeriesFetch:
    """Daily ``(mark_close − index_close) / index_close`` from Binance Vision. Skip-not-invent."""
    name = f"binance_vision_basis:{symbol}"
    try:
        contract = binance_contract(symbol)
    except ValueError as exc:
        return EdgeSeriesFetch(
            name=name, status="skipped", reason=str(exc), source="binance_vision"
        )
    mark = await fetch_binance_vision_daily_closes(
        client,
        VISION_MARK_KIND,
        contract,
        since=since,
        until=until,
        cache_dir=cache_dir,
        pause_seconds=pause_seconds,
        sleep=sleep,
        now=now,
    )
    if not mark.closes:
        return EdgeSeriesFetch(
            name=name,
            status="skipped",
            reason="Binance Vision markPriceKlines: no verified daily rows in window "
            + ("; ".join(mark.notes) if mark.notes else "(all zips 404 / unreachable)"),
            source=VISION_BASIS_SOURCE,
        )
    index = await fetch_binance_vision_daily_closes(
        client,
        VISION_INDEX_KIND,
        contract,
        since=since,
        until=until,
        cache_dir=cache_dir,
        pause_seconds=pause_seconds,
        sleep=sleep,
        now=now,
    )
    if not index.closes:
        return EdgeSeriesFetch(
            name=name,
            status="skipped",
            reason="Binance Vision indexPriceKlines: no verified daily rows in window "
            + ("; ".join(index.notes) if index.notes else "(all zips 404 / unreachable)"),
            source=VISION_BASIS_SOURCE,
        )
    points, bounded_skips = basis_from_closes(mark.closes, index.closes)
    one_sided = len(set(mark.closes) ^ set(index.closes))
    notes = [
        (
            f"Binance Vision USDT-M {contract} daily markPriceKlines close minus "
            "indexPriceKlines close over index (sha256 .CHECKSUM verified per zip; "
            "monthly zips + daily zips for the trailing month; today's bar dropped) — "
            "not premiumIndexKlines, not last-trade klines, not funding-implied."
        ),
        (
            f"mark months_ok={mark.months_ok} months_missing={mark.months_missing} "
            f"days_ok={mark.days_ok} days_missing={mark.days_missing} "
            f"checksum_failures={mark.checksum_failures}; "
            f"index months_ok={index.months_ok} months_missing={index.months_missing} "
            f"days_ok={index.days_ok} days_missing={index.days_missing} "
            f"checksum_failures={index.checksum_failures}; "
            f"one_sided_days_skipped={one_sided} bounded_skips={bounded_skips}."
        ),
    ]
    if mark.checksum_failures or index.checksum_failures:
        notes.append("checksum failures fail closed (month/day skipped, not filled).")
    notes.extend(mark.notes[:5])
    notes.extend(index.notes[:5])
    return _finish(name, source=VISION_BASIS_SOURCE, points=points, ok_reason=" ".join(notes))
