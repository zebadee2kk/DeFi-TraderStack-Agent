"""Kraken official OHLCVT archive loader (#133; offline, research-only).

Kraken publishes its full venue candle history as quarterly Google Drive
zips (support article 360047124832, "Downloadable historical OHLCVT data",
fetched 2026-09-13). **Verified from the article:** each zip holds one CSV
per pair and interval for the 1, 5, 15, 30, 60, 240, 720 and 1440 minute
intervals, from the beginning of each market; "the OHLCVT data only
includes entries for intervals when trades happened, so any missing
candlesticks indicate that no trades occurred" — such holes are reported
as gaps here, never filled. Incremental quarterly updates are published for
existing downloaders.

**Column layout is [S] (secondary source: community guides), not stated in
the article.** This loader assumes ``{PAIR}_{minutes}.csv`` with seven
unlabelled columns ``time (unix seconds), open, high, low, close, volume,
trades`` — verify against the first row of the first drop and fix
:data:`ARCHIVE_COLUMNS` / :func:`parse_archive_csv` if it differs.

The download is manual: the operator unzips the archive into
``RESEARCH_KRAKEN_ARCHIVE_DIR`` (or passes ``--archive-dir``). No network
here. **Survivorship caveat:** the archive covers currently active pairs
only; delisted pairs are absent, so any multi-asset universe built from it
is survivor-biased. A partial, truncated, non-monotonic or misaligned file
is refused (``status="skipped"``, nothing written). Research input only:
nothing here reaches ``RiskEngine`` or a ``PAPER_PROMOTE_*`` default.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from traderstack.candles import Candle, interval_to_seconds
from traderstack.market.kraken_candles import kraken_pair
from traderstack.research.candle_fetch import CandleFetch, finish_fetch, skip_fetch

KRAKEN_ARCHIVE_SOURCE = "kraken_ohlcvt_archive"
KRAKEN_ARCHIVE_QUOTE = "USD"
KRAKEN_ARCHIVE_ARTICLE = "https://support.kraken.com/articles/360047124832"
# Verified from the support article: the eight intervals shipped in every zip.
# (Distinct from market.kraken_candles.INTERVAL_MINUTES, which has 1w and no 12h.)
ARCHIVE_INTERVAL_MINUTES: dict[str, int] = {
    "1m": 1,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "4h": 240,
    "12h": 720,
    "1d": 1440,
}
# [S] seven columns: time, open, high, low, close, volume, trades.
ARCHIVE_COLUMNS = 7
ARCHIVE_COLUMN_NAMES = ("time", "open", "high", "low", "close", "volume", "trades")


def archive_pair(symbol: str) -> str:
    """``BTC/USD`` -> ``XBTUSD`` (archive files use Kraken's XBT naming)."""
    pair = kraken_pair(symbol)
    if pair.startswith("BTC"):
        pair = "XBT" + pair[3:]
    return pair


def archive_filename(symbol: str, resolution: str) -> str:
    if resolution not in ARCHIVE_INTERVAL_MINUTES:
        raise ValueError(
            f"unsupported Kraken archive resolution {resolution!r}; "
            f"use one of {sorted(ARCHIVE_INTERVAL_MINUTES)}"
        )
    return f"{archive_pair(symbol)}_{ARCHIVE_INTERVAL_MINUTES[resolution]}.csv"


def parse_archive_csv(text: str, *, symbol: str, interval: str) -> tuple[Candle, ...]:
    """Strict parse: 7 numeric fields, strictly increasing, aligned; else ``ValueError``.

    Missing intervals (no trades) are legitimate and are *not* an error here;
    ``finish_fetch`` reports them as gaps.
    """
    step = int(interval_to_seconds(interval))
    candles: list[Candle] = []
    previous: int | None = None
    lines = text.split("\n")
    if text and not text.endswith("\n"):
        raise ValueError(f"line {len(lines)}: file does not end with a newline (truncated?)")
    for line_number, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line:
            continue
        fields = line.split(",")
        if len(fields) != ARCHIVE_COLUMNS:
            raise ValueError(
                f"line {line_number}: expected {ARCHIVE_COLUMNS} columns "
                f"{ARCHIVE_COLUMN_NAMES}, got {len(fields)}"
            )
        try:
            opened_seconds = int(fields[0])
            open_f = float(fields[1])
            high_f = float(fields[2])
            low_f = float(fields[3])
            close_f = float(fields[4])
            volume_f = float(fields[5])
            int(float(fields[6]))
        except ValueError as exc:
            raise ValueError(f"line {line_number}: non-numeric field ({exc})") from exc
        if previous is not None and opened_seconds <= previous:
            raise ValueError(
                f"line {line_number}: time {opened_seconds} is not strictly increasing"
            )
        if opened_seconds % step != 0:
            raise ValueError(
                f"line {line_number}: time {opened_seconds} is not aligned to {interval} in UTC"
            )
        if open_f <= 0 or high_f <= 0 or low_f <= 0 or close_f <= 0:
            raise ValueError(f"line {line_number}: prices must be positive")
        try:
            candles.append(
                Candle(
                    symbol=symbol.upper(),
                    interval=interval,
                    opened_at=datetime.fromtimestamp(opened_seconds, tz=UTC),
                    open=open_f,
                    high=max(high_f, open_f, close_f),
                    low=min(low_f, open_f, close_f),
                    close=close_f,
                    volume=volume_f,
                )
            )
        except ValueError as exc:
            raise ValueError(f"line {line_number}: {exc}") from exc
        previous = opened_seconds
    return tuple(candles)


def load_kraken_archive_candles(
    archive_dir: Path | str,
    symbol: str,
    resolution: str,
    *,
    start: int | None = None,
    end: int | None = None,
    now: datetime | None = None,
) -> CandleFetch:
    """Load ``<archive_dir>/<PAIR>_<minutes>.csv`` with strict validation (no network)."""
    name = f"{symbol.upper()}@{resolution}"
    stamp = now or datetime.now(UTC)
    try:
        filename = archive_filename(symbol, resolution)
    except ValueError as exc:
        return skip_fetch(name, source=KRAKEN_ARCHIVE_SOURCE, reason=str(exc), fetched_at=stamp)
    directory = Path(archive_dir) if str(archive_dir) else None
    if directory is None:
        return skip_fetch(
            name,
            source=KRAKEN_ARCHIVE_SOURCE,
            reason=(
                "RESEARCH_KRAKEN_ARCHIVE_DIR / --archive-dir is unset; "
                f"download the archive manually ({KRAKEN_ARCHIVE_ARTICLE}) and unzip it there"
            ),
            fetched_at=stamp,
        )
    target = directory / filename
    if not target.is_file():
        return skip_fetch(
            name,
            source=KRAKEN_ARCHIVE_SOURCE,
            reason=f"archive file not found: {target} (expected {filename})",
            fetched_at=stamp,
        )
    try:
        text = target.read_text(encoding="utf-8")
        candles = parse_archive_csv(text, symbol=symbol, interval=resolution)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        return skip_fetch(
            name,
            source=KRAKEN_ARCHIVE_SOURCE,
            reason=f"refusing {filename}: {exc}",
            fetched_at=stamp,
        )
    if start is not None:
        candles = tuple(c for c in candles if int(c.opened_at.timestamp()) >= int(start))
    if end is not None:
        candles = tuple(c for c in candles if int(c.opened_at.timestamp()) <= int(end))
    notes = (
        (
            f"quote={KRAKEN_ARCHIVE_QUOTE}; file={filename}; column_layout=[S] "
            f"{ARCHIVE_COLUMN_NAMES}; active pairs only (survivorship); "
            "no-trade intervals are absent by design (reported as gaps)"
        ),
    )
    try:
        return finish_fetch(
            name,
            source=KRAKEN_ARCHIVE_SOURCE,
            candles=candles,
            interval=resolution,
            ok_reason=f"{len(candles)} {resolution} bars from {filename}",
            notes=notes,
            fetched_at=stamp,
        )
    except ValueError as exc:
        return skip_fetch(
            name,
            source=KRAKEN_ARCHIVE_SOURCE,
            reason=f"refusing {filename}: {exc}",
            fetched_at=stamp,
        )
