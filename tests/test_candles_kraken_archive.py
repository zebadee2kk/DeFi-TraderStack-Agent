"""Kraken OHLCVT archive loader (#133): strict refusal, no network."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from traderstack.research.candles_kraken_archive import (
    ARCHIVE_INTERVAL_MINUTES,
    KRAKEN_ARCHIVE_SOURCE,
    archive_filename,
    archive_pair,
    load_kraken_archive_candles,
    parse_archive_csv,
)

DAY = 86_400
T0 = int(datetime(2014, 1, 7, tzinfo=UTC).timestamp())


def _row(time: int, close: float = 800.0) -> str:
    return f"{time},{close - 1},{close + 5},{close - 5},{close},12.5,42"


def _file(tmp_path: Path, text: str, name: str = "XBTUSD_1440.csv") -> Path:
    target = tmp_path / name
    target.write_text(text, encoding="utf-8")
    return target


def test_archive_naming_uses_xbt_and_the_eight_shipped_intervals() -> None:
    assert archive_pair("BTC/USD") == "XBTUSD"
    assert archive_pair("ETH/USD") == "ETHUSD"
    assert archive_filename("BTC/USD", "1d") == "XBTUSD_1440.csv"
    assert archive_filename("ETH/USD", "12h") == "ETHUSD_720.csv"
    assert sorted(ARCHIVE_INTERVAL_MINUTES.values()) == [1, 5, 15, 30, 60, 240, 720, 1440]
    with pytest.raises(ValueError):
        archive_filename("BTC/USD", "1w")


def test_well_formed_file_loads_with_kraken_labels(tmp_path: Path) -> None:
    _file(tmp_path, "\n".join(_row(T0 + i * DAY) for i in range(5)) + "\n")
    fetch = load_kraken_archive_candles(tmp_path, "BTC/USD", "1d")
    assert fetch.status == "ok"
    assert fetch.source == KRAKEN_ARCHIVE_SOURCE
    assert len(fetch.candles) == 5
    assert fetch.candles[0].symbol == "BTC/USD"
    assert fetch.candles[0].interval == "1d"
    assert fetch.candles[0].opened_at == datetime(2014, 1, 7, tzinfo=UTC)
    assert fetch.gap_entries_total == 0
    assert any("quote=USD" in note for note in fetch.notes)


def test_no_trade_gap_is_reported_not_raised(tmp_path: Path) -> None:
    _file(tmp_path, "\n".join(_row(T0 + i * DAY) for i in (0, 1, 4)) + "\n")
    fetch = load_kraken_archive_candles(tmp_path, "BTC/USD", "1d")
    assert fetch.status == "ok"
    assert fetch.gap_entries_total == 1
    assert fetch.missing_bars_total == 2


@pytest.mark.parametrize(
    ("text", "needle"),
    [
        (_row(T0) + "\n" + _row(T0 + DAY) + "\n1389225600,799,805", "line 3"),  # truncated
        (_row(T0) + "\n" + _row(T0 + DAY)[: -len(",42")] + "\n", "line 2: expected 7"),
        (_row(T0) + "\n" + _row(T0 + DAY) + "\n" + _row(T0) + "\n", "line 3: time"),
        (_row(T0) + "\n" + _row(T0 + DAY + 43_200) + "\n", "line 2: time"),
        (_row(T0) + "\n" + _row(T0 + DAY).replace("12.5", "abc") + "\n", "line 2: non-numeric"),
        (_row(T0) + "\n" + _row(T0 + DAY, close=0.0) + "\n", "line 2: prices"),
    ],
)
def test_partial_or_unparsable_file_is_refused(tmp_path: Path, text: str, needle: str) -> None:
    _file(tmp_path, text)
    fetch = load_kraken_archive_candles(tmp_path, "BTC/USD", "1d")
    assert fetch.status == "skipped"
    assert needle in fetch.reason
    assert "XBTUSD_1440.csv" in fetch.reason
    assert fetch.candles == ()
    with pytest.raises(ValueError):
        parse_archive_csv(text, symbol="BTC/USD", interval="1d")


def test_missing_file_unset_dir_and_bad_resolution_are_skips(tmp_path: Path) -> None:
    missing = load_kraken_archive_candles(tmp_path, "ETH/USD", "1h")
    assert missing.status == "skipped"
    assert "not found" in missing.reason
    assert "ETHUSD_60.csv" in missing.reason

    unset = load_kraken_archive_candles("", "BTC/USD", "1d")
    assert unset.status == "skipped"
    assert "RESEARCH_KRAKEN_ARCHIVE_DIR" in unset.reason

    bad = load_kraken_archive_candles(tmp_path, "BTC/USD", "1w")
    assert bad.status == "skipped"
    assert "unsupported" in bad.reason


def test_start_end_slicing_and_empty_slice_is_skipped(tmp_path: Path) -> None:
    _file(tmp_path, "\n".join(_row(T0 + i * DAY) for i in range(5)) + "\n")
    fetch = load_kraken_archive_candles(tmp_path, "BTC/USD", "1d", start=T0 + DAY, end=T0 + 3 * DAY)
    assert fetch.status == "ok"
    assert [int(c.opened_at.timestamp()) for c in fetch.candles] == [
        T0 + DAY,
        T0 + 2 * DAY,
        T0 + 3 * DAY,
    ]
    empty = load_kraken_archive_candles(tmp_path, "BTC/USD", "1d", start=T0 + 10 * DAY)
    assert empty.status == "skipped"
    assert empty.reason == "empty series"


def test_unreadable_bytes_are_refused(tmp_path: Path) -> None:
    (tmp_path / "XBTUSD_1440.csv").write_bytes(b"\xff\xfe\x00bad")
    fetch = load_kraken_archive_candles(tmp_path, "BTC/USD", "1d")
    assert fetch.status == "skipped"
    assert "refusing" in fetch.reason
