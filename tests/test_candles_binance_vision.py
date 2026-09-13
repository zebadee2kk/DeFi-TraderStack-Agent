"""Binance Vision monthly zip loader (#133): checksum fail-closed, 404, µs/ms."""

from __future__ import annotations

import hashlib
import io
import zipfile
from datetime import UTC, datetime

import httpx
import pytest

from traderstack.research.candles_binance_vision import (
    BINANCE_VISION_SOURCE,
    extract_single_csv,
    fetch_binance_vision_candles,
    last_completed_month_end,
    month_range,
    parse_vision_csv,
    verify_checksum,
    vision_interval,
    vision_symbol,
    zip_name,
)

BASE = "https://data.binance.vision"
DAY_MS = 86_400_000


def _csv_rows(year: int, month: int, days: int, *, unit: str = "ms", close: float = 100.0) -> str:
    start = int(datetime(year, month, 1, tzinfo=UTC).timestamp()) * 1000
    lines = []
    for day in range(days):
        open_ms = start + day * DAY_MS
        stamp = open_ms * 1000 if unit == "us" else open_ms
        close_ms = open_ms + DAY_MS - 1
        lines.append(
            f"{stamp},{close - 1},{close + 2},{close - 3},{close},12.5,{close_ms},"
            "1000.0,42,6.0,500.0,0"
        )
    return "\n".join(lines) + "\n"


def _zip(name: str, content: str, extra: dict[str, str] | None = None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(name, content)
        for member, text in (extra or {}).items():
            archive.writestr(member, text)
    return buffer.getvalue()


def _checksum(zip_bytes: bytes, name: str) -> str:
    return f"{hashlib.sha256(zip_bytes).hexdigest()}  {name}\n"


def _month_zip(year: int, month: int, days: int, **kwargs: object) -> tuple[str, bytes]:
    name = zip_name("BTCUSDT", "1d", year, month)
    csv = _csv_rows(year, month, days, **kwargs)  # type: ignore[arg-type]
    return name, _zip(name.replace(".zip", ".csv"), csv)


def _serve(files: dict[str, bytes], checksums: dict[str, str]) -> httpx.MockTransport:
    async def handler(request: httpx.Request) -> httpx.Response:
        tail = request.url.path.rsplit("/", 1)[-1]
        assert request.url.path.startswith("/data/spot/monthly/klines/BTCUSDT/1d/")
        if tail.endswith(".CHECKSUM"):
            text = checksums.get(tail[: -len(".CHECKSUM")])
            return httpx.Response(200, text=text) if text else httpx.Response(404)
        blob = files.get(tail)
        return httpx.Response(200, content=blob) if blob else httpx.Response(404)

    return httpx.MockTransport(handler)


def test_symbol_interval_and_month_helpers() -> None:
    assert vision_symbol("BTC/USD") == "BTCUSDT"
    assert vision_symbol("ethusdt") == "ETHUSDT"
    with pytest.raises(ValueError):
        vision_symbol("BTC/EUR")
    assert vision_interval("4h") == "4h"
    with pytest.raises(ValueError):
        vision_interval("6h")
    dec = int(datetime(2017, 12, 15, tzinfo=UTC).timestamp())
    feb = int(datetime(2018, 2, 1, tzinfo=UTC).timestamp())
    assert month_range(dec, feb) == ((2017, 12), (2018, 1), (2018, 2))
    assert month_range(feb, feb) == ((2018, 2),)
    assert month_range(feb, dec) == ()
    now = datetime(2026, 9, 13, 10, tzinfo=UTC)
    assert last_completed_month_end(now) == int(datetime(2026, 9, 1, tzinfo=UTC).timestamp()) - 1


def test_verify_checksum_requires_matching_name_and_digest() -> None:
    blob = b"zip bytes"
    good = _checksum(blob, "BTCUSDT-1d-2017-09.zip")
    assert verify_checksum(blob, good, "BTCUSDT-1d-2017-09.zip")
    assert not verify_checksum(blob, good, "BTCUSDT-1d-2017-10.zip")
    assert not verify_checksum(blob + b"x", good, "BTCUSDT-1d-2017-09.zip")
    assert not verify_checksum(blob, "garbage", "BTCUSDT-1d-2017-09.zip")
    assert not verify_checksum(blob, "abc  BTCUSDT-1d-2017-09.zip", "BTCUSDT-1d-2017-09.zip")


def test_parse_vision_csv_ms_and_us_open_time_land_on_the_same_utc_midnight() -> None:
    ms = parse_vision_csv(_csv_rows(2017, 9, 2).encode(), symbol="BTCUSDT", interval="1d")
    us = parse_vision_csv(
        _csv_rows(2017, 9, 2, unit="us").encode(), symbol="BTCUSDT", interval="1d"
    )
    assert [c.opened_at for c in ms] == [c.opened_at for c in us]
    assert ms[0].opened_at == datetime(2017, 9, 1, tzinfo=UTC)
    assert ms[0].symbol == "BTCUSDT"
    assert ms[0].close == 100.0


def test_parse_vision_csv_tolerates_header_and_rejects_bad_rows() -> None:
    with_header = (
        "open_time,open,high,low,close,volume,close_time,quote_volume,count,tb,tq,ignore\n"
        + _csv_rows(2026, 7, 1, unit="us")
    )
    assert len(parse_vision_csv(with_header.encode(), symbol="BTCUSDT", interval="1d")) == 1
    with pytest.raises(ValueError, match="line 2"):
        parse_vision_csv(
            (_csv_rows(2017, 9, 1) + "1504310400000,abc,1,1,1,1\n").encode(),
            symbol="BTCUSDT",
            interval="1d",
        )
    with pytest.raises(ValueError, match="at least 6 fields"):
        parse_vision_csv(b"1504224000000,1,2\n", symbol="BTCUSDT", interval="1d")
    with pytest.raises(ValueError, match="not an integer"):
        parse_vision_csv(
            (_csv_rows(2017, 9, 1) + "x,1,1,1,1,1\n").encode(), symbol="BTCUSDT", interval="1d"
        )


def test_extract_single_csv_refuses_two_members_oversize_and_non_zip() -> None:
    single = _zip("a.csv", "1,2,3,4,5,6\n")
    assert extract_single_csv(single) == b"1,2,3,4,5,6\n"
    with pytest.raises(ValueError, match="exactly one"):
        extract_single_csv(_zip("a.csv", "x", extra={"b.csv": "y"}))
    with pytest.raises(ValueError, match="exactly one"):
        extract_single_csv(_zip("a.txt", "x"))
    with pytest.raises(ValueError, match="uncompressed"):
        extract_single_csv(_zip("a.csv", "0" * 2048), max_member_bytes=1024)
    with pytest.raises(ValueError, match="not a zip"):
        extract_single_csv(b"definitely not a zip")


@pytest.mark.asyncio
async def test_checksum_mismatch_fails_closed_with_nothing_loaded() -> None:
    name, blob = _month_zip(2017, 9, 30)
    name2, blob2 = _month_zip(2017, 10, 31)
    transport = _serve(
        {name: blob, name2: blob2},
        {name: _checksum(blob, name), name2: _checksum(blob, name2)},  # wrong digest
    )
    start = int(datetime(2017, 9, 1, tzinfo=UTC).timestamp())
    end = int(datetime(2017, 10, 31, tzinfo=UTC).timestamp())
    async with httpx.AsyncClient(base_url=BASE, transport=transport) as client:
        fetch = await fetch_binance_vision_candles(
            "BTC/USD", "1d", start=start, end=end, client=client, page_pause_seconds=0
        )
    assert fetch.status == "skipped"
    assert fetch.source == BINANCE_VISION_SOURCE
    assert "checksum mismatch" in fetch.reason
    assert name2 in fetch.reason
    assert fetch.candles == ()


@pytest.mark.asyncio
async def test_missing_checksum_file_refuses_the_zip() -> None:
    name, blob = _month_zip(2017, 9, 30)
    transport = _serve({name: blob}, {})
    start = int(datetime(2017, 9, 1, tzinfo=UTC).timestamp())
    async with httpx.AsyncClient(base_url=BASE, transport=transport) as client:
        fetch = await fetch_binance_vision_candles(
            "BTCUSDT", "1d", start=start, end=start, client=client, page_pause_seconds=0
        )
    assert fetch.status == "skipped"
    assert "checksum missing" in fetch.reason


@pytest.mark.asyncio
async def test_404_month_is_skipped_and_gap_reported_while_others_load() -> None:
    sep, sep_blob = _month_zip(2017, 9, 30)
    nov, nov_blob = _month_zip(2017, 11, 30, unit="us")
    transport = _serve(
        {sep: sep_blob, nov: nov_blob},
        {sep: _checksum(sep_blob, sep), nov: _checksum(nov_blob, nov)},
    )
    start = int(datetime(2017, 9, 1, tzinfo=UTC).timestamp())
    end = int(datetime(2017, 11, 30, tzinfo=UTC).timestamp())
    async with httpx.AsyncClient(base_url=BASE, transport=transport) as client:
        fetch = await fetch_binance_vision_candles(
            "BTC/USD", "1d", start=start, end=end, client=client, page_pause_seconds=0
        )
    assert fetch.status == "ok"
    assert len(fetch.candles) == 60
    assert any("skipped month 2017-10" in note for note in fetch.notes)
    assert fetch.gap_entries_total == 1
    assert fetch.missing_bars_total == 31
    assert fetch.first == datetime(2017, 9, 1, tzinfo=UTC)
    assert fetch.last == datetime(2017, 11, 30, tzinfo=UTC)
    assert any("quote=USDT" in note for note in fetch.notes)


@pytest.mark.asyncio
async def test_start_end_bounds_slice_inside_a_month_and_default_end_excludes_current_month() -> (
    None
):
    name, blob = _month_zip(2017, 9, 30)
    transport = _serve({name: blob}, {name: _checksum(blob, name)})
    start = int(datetime(2017, 9, 10, tzinfo=UTC).timestamp())
    end = int(datetime(2017, 9, 12, tzinfo=UTC).timestamp())
    async with httpx.AsyncClient(base_url=BASE, transport=transport) as client:
        fetch = await fetch_binance_vision_candles(
            "BTC/USD", "1d", start=start, end=end, client=client, page_pause_seconds=0
        )
    assert fetch.status == "ok"
    assert [c.opened_at.day for c in fetch.candles] == [10, 11, 12]

    # end=None -> last completed month; with `now` inside September 2017
    # nothing is complete, so the walk is empty and that is a skip, not a zero.
    async with httpx.AsyncClient(base_url=BASE, transport=transport) as client:
        empty = await fetch_binance_vision_candles(
            "BTC/USD",
            "1d",
            start=start,
            client=client,
            page_pause_seconds=0,
            now=datetime(2017, 9, 20, tzinfo=UTC),
        )
    assert empty.status == "skipped"
    assert "no complete month" in empty.reason


@pytest.mark.asyncio
async def test_malformed_zip_row_and_misaligned_bar_are_skips() -> None:
    name = zip_name("BTCUSDT", "1d", 2017, 9)
    bad_row = _zip(name.replace(".zip", ".csv"), "1504224000000,abc,1,1,1,1\n")
    transport = _serve({name: bad_row}, {name: _checksum(bad_row, name)})
    start = int(datetime(2017, 9, 1, tzinfo=UTC).timestamp())
    async with httpx.AsyncClient(base_url=BASE, transport=transport) as client:
        fetch = await fetch_binance_vision_candles(
            "BTC/USD", "1d", start=start, end=start, client=client, page_pause_seconds=0
        )
    assert fetch.status == "skipped"
    assert name in fetch.reason and "line 1" in fetch.reason

    midday = int(datetime(2017, 9, 1, 12, tzinfo=UTC).timestamp()) * 1000
    misaligned = _zip(name.replace(".zip", ".csv"), f"{midday},99,102,97,100,1,0,0,0,0,0,0\n")
    transport = _serve({name: misaligned}, {name: _checksum(misaligned, name)})
    async with httpx.AsyncClient(base_url=BASE, transport=transport) as client:
        fetch = await fetch_binance_vision_candles(
            "BTC/USD", "1d", start=start, end=start + 86_400, client=client, page_pause_seconds=0
        )
    assert fetch.status == "skipped"
    assert "alignment failed" in fetch.reason

    two_members = _zip(name.replace(".zip", ".csv"), "x", extra={"other.csv": "y"})
    transport = _serve({name: two_members}, {name: _checksum(two_members, name)})
    async with httpx.AsyncClient(base_url=BASE, transport=transport) as client:
        fetch = await fetch_binance_vision_candles(
            "BTC/USD", "1d", start=start, end=start, client=client, page_pause_seconds=0
        )
    assert fetch.status == "skipped"
    assert "exactly one .csv member" in fetch.reason


@pytest.mark.asyncio
async def test_oversized_member_is_refused() -> None:
    name = zip_name("BTCUSDT", "1d", 2017, 9)
    big = _zip(name.replace(".zip", ".csv"), _csv_rows(2017, 9, 30) * 40)
    transport = _serve({name: big}, {name: _checksum(big, name)})
    start = int(datetime(2017, 9, 1, tzinfo=UTC).timestamp())
    async with httpx.AsyncClient(base_url=BASE, transport=transport) as client:
        fetch = await fetch_binance_vision_candles(
            "BTC/USD",
            "1d",
            start=start,
            end=start,
            client=client,
            page_pause_seconds=0,
            max_member_bytes=4096,
        )
    assert fetch.status == "skipped"
    assert "uncompressed" in fetch.reason


@pytest.mark.asyncio
async def test_http_error_and_all_404_months_are_skips() -> None:
    async def boom(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="unavailable")

    start = int(datetime(2017, 9, 1, tzinfo=UTC).timestamp())
    async with httpx.AsyncClient(base_url=BASE, transport=httpx.MockTransport(boom)) as client:
        fetch = await fetch_binance_vision_candles(
            "BTC/USD", "1d", start=start, end=start, client=client, page_pause_seconds=0
        )
    assert fetch.status == "skipped"
    assert "503" in fetch.reason

    async with httpx.AsyncClient(base_url=BASE, transport=_serve({}, {})) as client:
        fetch = await fetch_binance_vision_candles(
            "BTC/USD", "1d", start=start, end=start, client=client, page_pause_seconds=0
        )
    assert fetch.status == "skipped"
    assert fetch.reason == "empty series"
    assert any("skipped month 2017-09" in note for note in fetch.notes)
