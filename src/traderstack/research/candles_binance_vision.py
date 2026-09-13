"""Binance Vision monthly spot kline archives, checksum-verified (#133).

``data.binance.vision`` is the public S3 bucket behind Binance's bulk data
site. It responds even where ``api.binance.com`` returns HTTP 451, which is why
it is the long-history spot source here rather than the REST klines endpoint
(see ``research/binance_spot.py`` for the REST/Binance.US path).

Layout::

    /data/spot/monthly/klines/{SYMBOL}/{interval}/{SYMBOL}-{interval}-{YYYY}-{MM}.zip
    /data/spot/monthly/klines/{SYMBOL}/{interval}/{SYMBOL}-{interval}-{YYYY}-{MM}.zip.CHECKSUM

The ``.CHECKSUM`` body is one ``sha256sum``-style line: ``<hex digest>  <zip
file name>``. The zip holds a single CSV whose columns are::

    open_time, open, high, low, close, volume, close_time, quote_volume,
    trade_count, taker_buy_base, taker_buy_quote, ignore

Two shape drifts this loader tolerates explicitly, because Binance introduced
both mid-archive: newer monthly files carry a **header row**, and newer files
publish ``open_time`` in **microseconds** rather than milliseconds. Both are
detected per row from the value itself, never assumed from the date.

Fail-closed rules:

* The checksum is verified **before** any bytes are parsed. A missing,
  unparsable, wrong-filename or mismatching ``.CHECKSUM`` aborts the whole
  fetch with ``status="skipped"`` — a month is never accepted unverified, and
  a partially-verified run never returns candles.
* Spot history starts 2017-08; months before a symbol listed (and months for a
  delisted symbol the bucket no longer retains) answer 404. That is a recorded
  per-month skip, not an error and not a zero-filled month. LUNAUSDT 2022-04
  was still present at issue time, so retention of delisted symbols must be
  checked per symbol, never assumed.
* Quote asset is **USDT**, not USD. Closes are not comparable to a Kraken USD
  tape bar-for-bar and this module never averages across venues.

Verification note (honest): ``data.binance.vision`` was **not reachable from
the session that wrote this module** — the agent egress proxy answered ``403``
to ``CONNECT data.binance.vision:443`` (organisation policy). The parser
follows the documented archive layout and the row/CHECKSUM samples recorded in
issue #133; it has not been run against a live archive from here. The
committed tests build synthetic zips and checksums instead of downloading.
"""

from __future__ import annotations

import csv
import hashlib
import io
import zipfile
from datetime import UTC, datetime
from typing import Literal

import httpx

from traderstack.candles import Candle
from traderstack.research.candle_archives import (
    ArchiveParseError,
    CandleSeriesFetch,
    finish_series,
    require_aligned,
    skipped_series,
)

BINANCE_VISION_BASE_URL = "https://data.binance.vision"
BINANCE_VISION_VENUE = "binance_vision_spot"
BINANCE_VISION_MONTHLY_PREFIX = "/data/spot/monthly/klines"
#: Binance spot monthly klines begin 2017-08.
BINANCE_VISION_EARLIEST = (2017, 8)

SUPPORTED_INTERVALS: tuple[str, ...] = ("1m", "5m", "15m", "1h", "4h", "1d")

#: Minimum kline CSV fields this loader needs (the archive publishes 12).
KLINE_MIN_FIELDS = 6


class ChecksumError(ValueError):
    """The published ``.CHECKSUM`` is missing, unparsable, or does not match."""


def binance_vision_symbol(symbol: str) -> str:
    """``BTC/USD`` → ``BTCUSDT``. The archive quotes USDT, not USD."""
    base, _, quote = symbol.upper().partition("/")
    if not base:
        raise ValueError(f"symbol must be formatted BASE/QUOTE, got {symbol!r}")
    if not quote:
        # Already a venue contract such as BTCUSDT.
        return base
    if quote == "USD":
        quote = "USDT"
    return f"{base}{quote}"


def monthly_zip_name(contract: str, interval: str, year: int, month: int) -> str:
    return f"{contract}-{interval}-{year:04d}-{month:02d}.zip"


def monthly_zip_path(contract: str, interval: str, year: int, month: int) -> str:
    return (
        f"{BINANCE_VISION_MONTHLY_PREFIX}/{contract}/{interval}/"
        f"{monthly_zip_name(contract, interval, year, month)}"
    )


def months_between(start: datetime, end: datetime) -> tuple[tuple[int, int], ...]:
    """Inclusive ``(year, month)`` pairs covering ``start``..``end``."""
    start_utc = start.astimezone(UTC)
    end_utc = end.astimezone(UTC)
    if end_utc < start_utc:
        return ()
    months: list[tuple[int, int]] = []
    year, month = start_utc.year, start_utc.month
    while (year, month) <= (end_utc.year, end_utc.month):
        months.append((year, month))
        month += 1
        if month > 12:
            year, month = year + 1, 1
    return tuple(months)


def parse_checksum_document(text: str, *, zip_name: str) -> str:
    """Extract the sha256 digest for ``zip_name``. Fails closed on anything odd."""
    digest: str | None = None
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        candidate, named = parts[0].strip().lower(), parts[-1].strip()
        # Binance writes the bare file name; tolerate a path prefix too.
        if named.rsplit("/", 1)[-1] != zip_name:
            continue
        if len(candidate) != 64 or any(char not in "0123456789abcdef" for char in candidate):
            raise ChecksumError(f"{zip_name}: CHECKSUM digest is not a sha256 hex digest")
        digest = candidate
        break
    if digest is None:
        raise ChecksumError(f"{zip_name}: CHECKSUM document names no digest for this file")
    return digest


def verify_checksum(payload: bytes, expected_digest: str, *, zip_name: str) -> None:
    """Raise :class:`ChecksumError` unless ``payload`` hashes to the published digest."""
    actual = hashlib.sha256(payload).hexdigest()
    if actual != expected_digest.strip().lower():
        raise ChecksumError(
            f"{zip_name}: sha256 mismatch — published {expected_digest.strip().lower()}, "
            f"downloaded {actual}"
        )


def _epoch_to_datetime(raw: str) -> datetime:
    """Kline timestamps are s / ms / µs depending on archive vintage."""
    try:
        value = int(float(raw))
    except (TypeError, ValueError) as exc:
        raise ArchiveParseError(f"kline timestamp is not numeric: {raw!r}") from exc
    if value <= 0:
        raise ArchiveParseError("kline timestamp must be positive")
    if value >= 1_000_000_000_000_000:  # microseconds
        seconds = value / 1_000_000.0
    elif value >= 1_000_000_000_000:  # milliseconds
        seconds = value / 1_000.0
    else:  # seconds
        seconds = float(value)
    return datetime.fromtimestamp(seconds, tz=UTC)


def parse_kline_row(row: list[str], *, symbol: str, interval: str) -> Candle:
    if len(row) < KLINE_MIN_FIELDS:
        raise ArchiveParseError(
            f"kline row needs at least {KLINE_MIN_FIELDS} fields, got {len(row)}"
        )
    opened_at = require_aligned(_epoch_to_datetime(row[0]), interval)
    try:
        open_price = float(row[1])
        high = float(row[2])
        low = float(row[3])
        close = float(row[4])
        volume = float(row[5])
    except (TypeError, ValueError) as exc:
        raise ArchiveParseError(f"kline row is not numeric: {exc}") from exc
    if min(open_price, high, low, close) <= 0:
        raise ArchiveParseError("kline prices must be positive")
    if volume < 0:
        raise ArchiveParseError("kline volume must not be negative")
    return Candle(
        symbol=symbol.upper(),
        interval=interval,
        opened_at=opened_at,
        open=open_price,
        high=max(high, open_price, close),
        low=min(low, open_price, close),
        close=close,
        volume=volume,
    )


def _is_header_row(row: list[str]) -> bool:
    if not row:
        return True
    try:
        float(row[0])
    except (TypeError, ValueError):
        return True
    return False


def parse_monthly_zip(payload: bytes, *, symbol: str, interval: str) -> tuple[Candle, ...]:
    """Read the single CSV member of a monthly klines zip into candles."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except zipfile.BadZipFile as exc:
        raise ArchiveParseError(f"not a readable zip archive: {exc}") from exc
    with archive:
        members = [name for name in archive.namelist() if name.lower().endswith(".csv")]
        if len(members) != 1:
            raise ArchiveParseError(
                f"monthly klines zip must hold exactly one CSV, found {len(members)}"
            )
        raw = archive.read(members[0])
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ArchiveParseError(f"kline CSV is not UTF-8: {exc}") from exc
    candles: list[Candle] = []
    for index, row in enumerate(csv.reader(io.StringIO(text))):
        if not row or all(not field.strip() for field in row):
            continue
        if index == 0 and _is_header_row(row):
            continue
        candles.append(parse_kline_row(row, symbol=symbol, interval=interval))
    return tuple(candles)


async def _get(client: httpx.AsyncClient, path: str) -> tuple[Literal["ok", "missing"], bytes]:
    response = await client.get(path)
    if response.status_code == 404:
        return "missing", b""
    response.raise_for_status()
    return "ok", response.content


async def fetch_binance_vision_monthly(
    symbol: str,
    interval: str,
    *,
    start: datetime,
    end: datetime | None = None,
    client: httpx.AsyncClient | None = None,
    base_url: str = BINANCE_VISION_BASE_URL,
    label_symbol: str | None = None,
) -> CandleSeriesFetch:
    """Download, checksum-verify and parse every monthly zip in the window.

    Returns ``status="ok"`` only when every month that *was* present verified
    and parsed. A checksum mismatch, a corrupt zip or an unparsable row aborts
    the whole series (``status="skipped"``) rather than returning the months
    that happened to pass — a half-verified archive is not history.
    """
    reported_symbol = label_symbol or symbol
    name = f"binance_vision:{reported_symbol}@{interval}"
    fetched_at = datetime.now(UTC)

    if interval not in SUPPORTED_INTERVALS:
        return skipped_series(
            name=name,
            venue=BINANCE_VISION_VENUE,
            symbol=reported_symbol,
            interval=interval,
            reason=f"unsupported interval {interval!r}; archive serves {list(SUPPORTED_INTERVALS)}",
            fetched_at=fetched_at,
        )
    try:
        contract = binance_vision_symbol(symbol)
    except ValueError as exc:
        return skipped_series(
            name=name,
            venue=BINANCE_VISION_VENUE,
            symbol=reported_symbol,
            interval=interval,
            reason=str(exc),
            fetched_at=fetched_at,
        )

    months = months_between(start, end or datetime.now(UTC))
    if not months:
        return skipped_series(
            name=name,
            venue=BINANCE_VISION_VENUE,
            symbol=reported_symbol,
            interval=interval,
            reason="empty month window",
            fetched_at=fetched_at,
        )

    notes = [f"contract={contract} (quote is USDT, not USD)"]
    collected: list[Candle] = []
    missing: list[str] = []
    owned = client is None
    active = client or httpx.AsyncClient(base_url=base_url, timeout=60, follow_redirects=True)
    try:
        for year, month in months:
            if (year, month) < BINANCE_VISION_EARLIEST:
                missing.append(f"{year:04d}-{month:02d} (before spot archive start)")
                continue
            zip_name = monthly_zip_name(contract, interval, year, month)
            path = monthly_zip_path(contract, interval, year, month)
            try:
                # The zip is probed first: a month the bucket does not hold (before
                # listing, or a delisted symbol that was not retained) 404s on both
                # objects and is a per-month skip, not a verification failure.
                zip_state, zip_bytes = await _get(active, path)
                if zip_state == "missing":
                    missing.append(f"{year:04d}-{month:02d} (404)")
                    continue
                checksum_state, checksum_bytes = await _get(active, f"{path}.CHECKSUM")
                if checksum_state == "missing":
                    # The data exists but publishes no digest ⇒ nothing to verify
                    # it against ⇒ refuse rather than trust it.
                    raise ChecksumError(f"{zip_name}: no published .CHECKSUM")
                expected = parse_checksum_document(
                    checksum_bytes.decode("utf-8", errors="replace"), zip_name=zip_name
                )
                verify_checksum(zip_bytes, expected, zip_name=zip_name)
                collected.extend(
                    parse_monthly_zip(zip_bytes, symbol=reported_symbol, interval=interval)
                )
            except ChecksumError as exc:
                return skipped_series(
                    name=name,
                    venue=BINANCE_VISION_VENUE,
                    symbol=reported_symbol,
                    interval=interval,
                    reason=f"checksum verification failed: {exc}",
                    notes=tuple(notes),
                    fetched_at=fetched_at,
                )
            except (httpx.HTTPError, ArchiveParseError) as exc:
                return skipped_series(
                    name=name,
                    venue=BINANCE_VISION_VENUE,
                    symbol=reported_symbol,
                    interval=interval,
                    reason=f"{year:04d}-{month:02d}: {type(exc).__name__}: {exc}",
                    notes=tuple(notes),
                    fetched_at=fetched_at,
                )
    finally:
        if owned:
            await active.aclose()

    if missing:
        notes.append(f"months absent from the bucket (not zero-filled): {', '.join(missing)}")
    return finish_series(
        name=name,
        venue=BINANCE_VISION_VENUE,
        symbol=reported_symbol,
        interval=interval,
        candles=collected,
        ok_reason=(
            f"{len(months) - len(missing)} monthly zip(s) checksum-verified "
            f"from {BINANCE_VISION_VENUE}"
        ),
        empty_reason="no monthly zips present for the requested window",
        notes=tuple(notes),
        fetched_at=fetched_at,
    )
