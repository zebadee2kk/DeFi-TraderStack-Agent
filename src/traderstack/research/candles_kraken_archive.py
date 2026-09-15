"""Kraken official OHLCVT archive loader — local files only (#133).

Kraken publishes its **full** venue history as quarterly OHLCVT zips, linked
from support article 360047124832 ("Downloadable historical OHLCVT and Trade
data"). The drops are hosted on Google Drive and are download-gated, so this is
a **loader for a file an operator already downloaded and unpacked**, not a
fetcher: nothing in this module makes a network call.

Unpacked layout: one headerless CSV per pair per timeframe, named
``{PAIR}_{minutes}.csv`` (e.g. ``XBTUSD_1440.csv``), with columns::

    timestamp(unix seconds), open, high, low, close, volume, trades

The pair uses Kraken's own asset codes — **XBT**, not BTC.

Survivorship-bias caveat (documented in ``docs/DATA-SOURCES.md`` too): the
archive ships **active pairs only**. Pairs Kraken has delisted are not in the
drop, so a catalog scored on this archive alone sees only the survivors and
will read better than the venue actually traded. Treat it as one venue's
long tape, not as a bias-free universe. This is recorded as a note on every
loaded series so it reaches the report header.

Fail-closed rules (issue #133: "refuses to run on a partial or unparsable
file"): a missing file, an empty file, a row with the wrong field count, a
non-numeric field, a non-positive price, a timestamp off the interval grid, or
a truncated final line makes the **whole load** a skip with the reason. This
loader never returns the rows that happened to parse — a partial archive is
not history, and silently short history is exactly the failure mode #133
exists to fix.
"""

from __future__ import annotations

import csv
from datetime import UTC, datetime
from pathlib import Path

from traderstack.candles import Candle
from traderstack.research.candle_archives import (
    ArchiveParseError,
    CandleSeriesFetch,
    finish_series,
    require_aligned,
    skipped_series,
)

KRAKEN_ARCHIVE_VENUE = "kraken_ohlcvt_archive"
KRAKEN_ARCHIVE_SUPPORT_ARTICLE = (
    "https://support.kraken.com/hc/en-us/articles/360047124832"
    "-Downloadable-historical-OHLCVT-Open-High-Low-Close-Volume-Trades-data"
)
SURVIVORSHIP_NOTE = (
    "Kraken's OHLCVT archive ships active pairs only; delisted pairs are absent, "
    "so any universe built from it alone is survivorship-biased."
)

#: The 8 timeframes the archive publishes, as minutes in the file name.
KRAKEN_ARCHIVE_INTERVAL_MINUTES: dict[str, int] = {
    "1m": 1,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "4h": 240,
    "1d": 1440,
    "1w": 10080,
}

#: Kraken's own asset codes differ from the pipeline's symbols.
_KRAKEN_ASSET_CODE: dict[str, str] = {"BTC": "XBT"}

OHLCVT_FIELDS = 7


def kraken_archive_pair(symbol: str) -> str:
    """``BTC/USD`` → ``XBTUSD`` (Kraken's archive asset codes)."""
    base, _, quote = symbol.upper().partition("/")
    if not base or not quote:
        raise ValueError(f"symbol must be formatted BASE/QUOTE, got {symbol!r}")
    return f"{_KRAKEN_ASSET_CODE.get(base, base)}{_KRAKEN_ASSET_CODE.get(quote, quote)}"


def kraken_archive_filename(symbol: str, interval: str) -> str:
    """``BTC/USD``, ``1d`` → ``XBTUSD_1440.csv``."""
    if interval not in KRAKEN_ARCHIVE_INTERVAL_MINUTES:
        raise ValueError(
            f"unsupported interval {interval!r}; the archive publishes "
            f"{sorted(KRAKEN_ARCHIVE_INTERVAL_MINUTES)}"
        )
    return f"{kraken_archive_pair(symbol)}_{KRAKEN_ARCHIVE_INTERVAL_MINUTES[interval]}.csv"


def resolve_archive_file(path: Path, symbol: str, interval: str) -> Path:
    """Accept either the CSV itself or the directory the drop was unpacked into."""
    if path.is_dir():
        return path / kraken_archive_filename(symbol, interval)
    return path


def parse_ohlcvt_row(row: list[str], *, symbol: str, interval: str) -> Candle:
    if len(row) != OHLCVT_FIELDS:
        raise ArchiveParseError(
            f"OHLCVT row must have {OHLCVT_FIELDS} fields "
            f"(timestamp,open,high,low,close,volume,trades), got {len(row)}"
        )
    try:
        opened_seconds = int(float(row[0]))
        open_price = float(row[1])
        high = float(row[2])
        low = float(row[3])
        close = float(row[4])
        volume = float(row[5])
        float(row[6])  # trade count: validated, not carried on Candle
    except (TypeError, ValueError) as exc:
        raise ArchiveParseError(f"OHLCVT row is not numeric: {exc}") from exc
    if opened_seconds <= 0:
        raise ArchiveParseError("OHLCVT timestamp must be positive")
    if min(open_price, high, low, close) <= 0:
        raise ArchiveParseError("OHLCVT prices must be positive")
    if volume < 0:
        raise ArchiveParseError("OHLCVT volume must not be negative")
    if high < low:
        raise ArchiveParseError("OHLCVT high cannot be below low")
    opened_at = require_aligned(datetime.fromtimestamp(opened_seconds, tz=UTC), interval)
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


def parse_ohlcvt_csv(text: str, *, symbol: str, interval: str) -> tuple[Candle, ...]:
    """Parse a whole OHLCVT CSV. Any bad row raises — there is no partial parse."""
    candles: list[Candle] = []
    for line_number, row in enumerate(csv.reader(text.splitlines()), start=1):
        if not row or all(not field.strip() for field in row):
            continue
        try:
            candles.append(parse_ohlcvt_row(row, symbol=symbol, interval=interval))
        except ArchiveParseError as exc:
            raise ArchiveParseError(f"line {line_number}: {exc}") from exc
    if not candles:
        raise ArchiveParseError("file holds no OHLCVT rows")
    return tuple(candles)


def load_kraken_archive(
    path: Path,
    symbol: str,
    interval: str,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
) -> CandleSeriesFetch:
    """Load one pair/timeframe from an unpacked OHLCVT drop.

    ``path`` is either the CSV file or the directory holding the drop. Returns
    ``status="ok"`` with the full parsed series, or ``status="skipped"`` with
    the reason and **no candles** — a partial or unparsable file is refused
    outright.
    """
    name = f"kraken_archive:{symbol}@{interval}"
    fetched_at = datetime.now(UTC)

    def _skip(reason: str) -> CandleSeriesFetch:
        return skipped_series(
            name=name,
            venue=KRAKEN_ARCHIVE_VENUE,
            symbol=symbol,
            interval=interval,
            reason=reason,
            notes=(SURVIVORSHIP_NOTE,),
            fetched_at=fetched_at,
        )

    try:
        target = resolve_archive_file(path, symbol, interval)
    except ValueError as exc:
        return _skip(str(exc))
    if not target.is_file():
        return _skip(f"{target}: no such OHLCVT file (manual download, see the support article)")
    try:
        text = target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return _skip(f"{target}: unreadable ({type(exc).__name__}: {exc})")
    if not text.strip():
        return _skip(f"{target}: file is empty")
    try:
        candles = parse_ohlcvt_csv(text, symbol=symbol, interval=interval)
    except ArchiveParseError as exc:
        return _skip(f"{target}: refusing a partial/unparsable archive — {exc}")

    window = [
        candle
        for candle in candles
        if (start is None or candle.opened_at >= start.astimezone(UTC))
        and (end is None or candle.opened_at <= end.astimezone(UTC))
    ]
    notes = (
        SURVIVORSHIP_NOTE,
        f"source file: {target.name}",
        f"support article: {KRAKEN_ARCHIVE_SUPPORT_ARTICLE}",
    )
    return finish_series(
        name=name,
        venue=KRAKEN_ARCHIVE_VENUE,
        symbol=symbol,
        interval=interval,
        candles=window,
        ok_reason=f"loaded {len(window)} of {len(candles)} rows from {target.name}",
        empty_reason=f"{target.name} holds no rows inside the requested window",
        notes=notes,
        fetched_at=fetched_at,
    )
