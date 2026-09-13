"""Binance Vision monthly spot klines (#133; research-only, bulk S3 archive).

**Verified 2026-09-13** (unauthenticated GET from the session environment;
``api.binance.com`` REST is HTTP 451 here and is never used by this module):

* ``https://data.binance.vision/data/spot/monthly/klines/{SYMBOL}/{interval}/``
  ``{SYMBOL}-{interval}-{YYYY}-{MM}.zip`` — one CSV member per zip, no
  header in the 2017 files (a header row is tolerated), twelve columns
  ``open_time, open, high, low, close, volume, close_time, quote_volume,
  trades, taker_base, taker_quote, ignore``. Spot klines exist from 2017-08.
* Sibling ``.zip.CHECKSUM`` holds ``<sha256>  <zipname>``. The checksum is
  verified before the zip is opened; **a mismatch fails the whole fetch
  closed** (``status="skipped"``, nothing written).
* ``open_time`` switched from milliseconds (13 digits, e.g. 2017-09) to
  microseconds (16 digits, e.g. 2026-07). Values above ``10**14`` are
  treated as microseconds and normalised to milliseconds before reuse of
  ``research.binance_spot.parse_binance_kline``.
* A month that is not published (not yet listed, delisted, or the current
  month) is HTTP 404: recorded as a skipped month, the walk continues.
* Untrusted bytes: a zip member above :data:`BINANCE_VISION_MAX_MEMBER_BYTES`
  (uncompressed) or a zip with anything but exactly one ``.csv`` member is
  refused.

Quote is **USDT** (``BTCUSDT``), not Kraken/Coinbase USD; closes differ and
this series must never be averaged into a USD print. Survivorship: some
delisted symbols are retained (LUNAUSDT 2022-04 is still published), others
are not — a missing symbol is a skip. Research input only: nothing here
reaches ``RiskEngine`` or a ``PAPER_PROMOTE_*`` default.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import zipfile
from datetime import UTC, datetime

import httpx

from traderstack.candles import Candle
from traderstack.research.binance_spot import parse_binance_kline
from traderstack.research.candle_fetch import (
    CandleFetch,
    finish_fetch,
    http_skip,
    skip_fetch,
)

BINANCE_VISION_BASE = "https://data.binance.vision"
BINANCE_VISION_ZIP_PATH = (
    "/data/spot/monthly/klines/{symbol}/{interval}/{symbol}-{interval}-{year:04d}-{month:02d}.zip"
)
BINANCE_VISION_CHECKSUM_SUFFIX = ".CHECKSUM"
BINANCE_VISION_INTERVALS: tuple[str, ...] = ("1m", "5m", "15m", "1h", "4h", "1d")
BINANCE_VISION_SOURCE = "binance_vision_spot_monthly"
BINANCE_VISION_QUOTE = "USDT"
BINANCE_VISION_PAGE_PAUSE_SECONDS = 0.1
BINANCE_VISION_MAX_MEMBER_BYTES = 256 * 1024 * 1024
BINANCE_VISION_FIRST_MONTH = (2017, 8)
# open_time above this is microseconds (16 digits), not milliseconds (13).
_MICROSECONDS_THRESHOLD = 10**14

_VISION_SYMBOL: dict[str, str] = {
    "BTC/USD": "BTCUSDT",
    "ETH/USD": "ETHUSDT",
    "SOL/USD": "SOLUSDT",
    "BTC/USDT": "BTCUSDT",
    "ETH/USDT": "ETHUSDT",
    "SOL/USDT": "SOLUSDT",
}


def vision_symbol(symbol: str) -> str:
    """``BTC/USD`` -> ``BTCUSDT``; a native ``BTCUSDT`` passes through."""
    key = symbol.strip().upper()
    if key in _VISION_SYMBOL:
        return _VISION_SYMBOL[key]
    if key.isalnum() and key.endswith(BINANCE_VISION_QUOTE):
        return key
    raise ValueError(
        f"no Binance Vision USDT mapping for {symbol!r}; known: {sorted(_VISION_SYMBOL)} "
        "or a native *USDT symbol"
    )


def vision_interval(resolution: str) -> str:
    if resolution not in BINANCE_VISION_INTERVALS:
        raise ValueError(
            f"unsupported Binance Vision interval {resolution!r}; "
            f"use one of {list(BINANCE_VISION_INTERVALS)}"
        )
    return resolution


def month_range(start: int, end: int) -> tuple[tuple[int, int], ...]:
    """Inclusive ``(year, month)`` sequence covering ``start..end`` (unix seconds)."""
    first = datetime.fromtimestamp(int(start), tz=UTC)
    last = datetime.fromtimestamp(int(end), tz=UTC)
    if (first.year, first.month) > (last.year, last.month):
        return ()
    months: list[tuple[int, int]] = []
    year, month = first.year, first.month
    while (year, month) <= (last.year, last.month):
        months.append((year, month))
        month += 1
        if month > 12:
            month = 1
            year += 1
    return tuple(months)


def last_completed_month_end(now: datetime) -> int:
    """Unix seconds of the last instant before the current UTC month started."""
    month_start = datetime(now.year, now.month, 1, tzinfo=UTC)
    return int(month_start.timestamp()) - 1


def zip_name(symbol: str, interval: str, year: int, month: int) -> str:
    return f"{symbol}-{interval}-{year:04d}-{month:02d}.zip"


def verify_checksum(zip_bytes: bytes, checksum_text: str, expected_name: str) -> bool:
    """``<sha256>  <zipname>`` must name the zip and match its sha256."""
    parts = checksum_text.strip().split()
    if len(parts) < 2:
        return False
    digest, name = parts[0].lower(), parts[-1]
    if name != expected_name or len(digest) != 64:
        return False
    return hashlib.sha256(zip_bytes).hexdigest() == digest


def parse_vision_csv(csv_bytes: bytes, *, symbol: str, interval: str) -> tuple[Candle, ...]:
    """Parse one monthly kline CSV; header tolerated; µs open_time normalised."""
    candles: list[Candle] = []
    text = csv_bytes.decode("utf-8")
    for line_number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        fields = line.split(",")
        if len(fields) < 6:
            raise ValueError(f"line {line_number}: expected at least 6 fields, got {len(fields)}")
        first = fields[0].strip()
        if line_number == 1 and not first.lstrip("-").isdigit():
            continue  # header row
        try:
            open_time = int(first)
        except ValueError as exc:
            raise ValueError(f"line {line_number}: open_time {first!r} is not an integer") from exc
        if open_time > _MICROSECONDS_THRESHOLD:
            open_time //= 1000
        try:
            candles.append(
                parse_binance_kline(
                    [open_time, fields[1], fields[2], fields[3], fields[4], fields[5]],
                    symbol=symbol,
                    interval=interval,
                )
            )
        except (TypeError, ValueError) as exc:
            raise ValueError(f"line {line_number}: {exc}") from exc
    candles.sort(key=lambda candle: candle.opened_at)
    return tuple(candles)


def extract_single_csv(
    zip_bytes: bytes, *, max_member_bytes: int = BINANCE_VISION_MAX_MEMBER_BYTES
) -> bytes:
    """Exactly one ``.csv`` member, bounded in uncompressed size, else ``ValueError``."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile as exc:
        raise ValueError(f"not a zip archive: {exc}") from exc
    with archive:
        members = [info for info in archive.infolist() if not info.is_dir()]
        if len(members) != 1 or not members[0].filename.lower().endswith(".csv"):
            names = [info.filename for info in members]
            raise ValueError(f"expected exactly one .csv member, got {names}")
        member = members[0]
        if member.file_size > max_member_bytes:
            raise ValueError(
                f"member {member.filename} is {member.file_size} bytes uncompressed "
                f"(cap {max_member_bytes})"
            )
        return archive.read(member)


async def fetch_binance_vision_candles(
    symbol: str,
    resolution: str,
    *,
    start: int,
    end: int | None = None,
    client: httpx.AsyncClient | None = None,
    page_pause_seconds: float = BINANCE_VISION_PAGE_PAUSE_SECONDS,
    max_member_bytes: int = BINANCE_VISION_MAX_MEMBER_BYTES,
    now: datetime | None = None,
) -> CandleFetch:
    """Load every published month in ``start..end`` (default: last completed month).

    A 404 month is skipped and noted; a checksum mismatch, an unexpected zip
    layout, an oversized member, a malformed row, or a misaligned bar fails
    the whole fetch closed (``status="skipped"``, nothing written).
    """
    native = vision_symbol(symbol)
    interval = vision_interval(resolution)
    name = f"{native}@{interval}"
    reference_now = now or datetime.now(UTC)
    end_bound = end if end is not None else last_completed_month_end(reference_now)
    months = month_range(start, end_bound)
    if not months:
        return skip_fetch(
            name,
            source=BINANCE_VISION_SOURCE,
            reason="no complete month between start and end",
            fetched_at=reference_now,
        )
    notes: list[str] = [
        f"quote={BINANCE_VISION_QUOTE}; symbol={native}; months_requested={len(months)}"
    ]
    candles: list[Candle] = []
    loaded = 0

    async def _walk(active: httpx.AsyncClient) -> CandleFetch | None:
        nonlocal loaded
        for index, (year, month) in enumerate(months):
            if index and page_pause_seconds > 0:
                await asyncio.sleep(page_pause_seconds)
            path = BINANCE_VISION_ZIP_PATH.format(
                symbol=native, interval=interval, year=year, month=month
            )
            expected = zip_name(native, interval, year, month)
            zip_response = await active.get(path)
            if zip_response.status_code == 404:
                notes.append(
                    f"skipped month {year:04d}-{month:02d} (HTTP 404: not listed / "
                    "delisted / not yet published)"
                )
                continue
            zip_response.raise_for_status()
            checksum_response = await active.get(path + BINANCE_VISION_CHECKSUM_SUFFIX)
            if checksum_response.status_code == 404:
                return skip_fetch(
                    name,
                    source=BINANCE_VISION_SOURCE,
                    reason=f"checksum missing for {expected} (HTTP 404); refusing unverified zip",
                    notes=tuple(notes),
                    fetched_at=reference_now,
                )
            checksum_response.raise_for_status()
            if not verify_checksum(zip_response.content, checksum_response.text, expected):
                return skip_fetch(
                    name,
                    source=BINANCE_VISION_SOURCE,
                    reason=f"checksum mismatch for {expected}; nothing written",
                    notes=tuple(notes),
                    fetched_at=reference_now,
                )
            try:
                csv_bytes = extract_single_csv(
                    zip_response.content, max_member_bytes=max_member_bytes
                )
                rows = parse_vision_csv(csv_bytes, symbol=native, interval=interval)
            except ValueError as exc:
                return skip_fetch(
                    name,
                    source=BINANCE_VISION_SOURCE,
                    reason=f"{expected}: {exc}",
                    notes=tuple(notes),
                    fetched_at=reference_now,
                )
            candles.extend(rows)
            loaded += 1
        return None

    try:
        if client is not None:
            skipped = await _walk(client)
        else:
            async with httpx.AsyncClient(base_url=BINANCE_VISION_BASE, timeout=60) as owned:
                skipped = await _walk(owned)
    except httpx.HTTPError as exc:
        return http_skip(name, source=BINANCE_VISION_SOURCE, exc=exc, notes=tuple(notes))
    if skipped is not None:
        return skipped

    notes.append(f"months_loaded={loaded}")
    # Monthly zips cover whole months; honour the requested bounds exactly.
    bounded = [
        candle
        for candle in candles
        if int(start) <= int(candle.opened_at.timestamp()) <= int(end_bound)
    ]
    try:
        return finish_fetch(
            name,
            source=BINANCE_VISION_SOURCE,
            candles=bounded,
            interval=interval,
            ok_reason=f"{len(bounded)} {interval} bars from {loaded} verified monthly zip(s)",
            notes=tuple(notes),
            fetched_at=reference_now,
        )
    except ValueError as exc:
        return skip_fetch(
            name,
            source=BINANCE_VISION_SOURCE,
            reason=f"alignment failed: {exc}",
            notes=tuple(notes),
            fetched_at=reference_now,
        )
