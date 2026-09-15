"""Multi-year candle archives (#133): Coinbase, Binance Vision, Kraken OHLCVT.

Every test here is **offline and deterministic**. HTTP is faked with
``httpx.MockTransport`` (the established pattern in ``test_download_candles.py``
and the provider tests); zips, ``.CHECKSUM`` documents and OHLCVT CSVs are
synthesised in-process. Nothing here touches the network.
"""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from traderstack.candles import Candle
from traderstack.research.candle_archives import (
    ArchiveParseError,
    aggregate,
    close_divergence_bps,
    cross_venue_divergence,
    detect_gaps,
    drop_uncommitted,
    finish_series,
    is_aligned,
    skipped_series,
)
from traderstack.research.candles_binance_vision import (
    BINANCE_VISION_BASE_URL,
    ChecksumError,
    binance_vision_symbol,
    fetch_binance_vision_monthly,
    monthly_zip_name,
    monthly_zip_path,
    months_between,
    parse_checksum_document,
    parse_monthly_zip,
)
from traderstack.research.candles_coinbase import (
    COINBASE_EXCHANGE_BASE_URL,
    COINBASE_MAX_CANDLES_PER_REQUEST,
    coinbase_page_windows,
    coinbase_product_id,
    fetch_coinbase_candles,
    parse_coinbase_candle,
)
from traderstack.research.candles_kraken_archive import (
    SURVIVORSHIP_NOTE,
    kraken_archive_filename,
    kraken_archive_pair,
    load_kraken_archive,
)
from traderstack.research.download_candles import (
    _resolve_max_divergence_bps,
    build_archive_report,
    build_parser,
    fetch_archive_series,
    main,
    read_candle_json,
    write_candle_json,
)

DAY = timedelta(days=1)
HOUR = timedelta(hours=1)
EPOCH_DAY = datetime(2016, 1, 1, tzinfo=UTC)


def _candle(opened_at: datetime, close: float, *, interval: str = "1d") -> Candle:
    return Candle(
        symbol="BTC/USD",
        interval=interval,
        opened_at=opened_at,
        open=close,
        high=close + 1.0,
        low=close - 1.0,
        close=close,
        volume=1.0,
    )


# --- shared vocabulary: gaps, alignment, roll-up --------------------------------


def test_detect_gaps_counts_missing_bars_and_never_fills_them() -> None:
    """A three-day hole is reported as two missing bars — and stays a hole."""
    candles = (
        _candle(EPOCH_DAY, 100.0),
        _candle(EPOCH_DAY + DAY, 101.0),
        # 2016-01-03 and 2016-01-04 are absent from the venue's tape.
        _candle(EPOCH_DAY + 4 * DAY, 104.0),
    )
    gaps = detect_gaps(candles, "1d")
    assert len(gaps) == 1
    assert gaps[0].after == EPOCH_DAY + DAY
    assert gaps[0].before == EPOCH_DAY + 4 * DAY
    assert gaps[0].missing_bars == 2
    # The series itself is untouched: nothing interpolated, nothing zero-filled.
    assert len(candles) == 3


def test_detect_gaps_is_empty_for_a_contiguous_series() -> None:
    candles = tuple(_candle(EPOCH_DAY + index * DAY, 100.0 + index) for index in range(10))
    assert detect_gaps(candles, "1d") == ()


def test_is_aligned_rejects_off_grid_and_naive_timestamps() -> None:
    assert is_aligned(EPOCH_DAY, "1d")
    assert not is_aligned(EPOCH_DAY + timedelta(hours=7), "1d")
    assert is_aligned(EPOCH_DAY + timedelta(hours=7), "1h")
    assert not is_aligned(datetime(2016, 1, 1), "1d")  # noqa: DTZ001 - naive on purpose


def test_drop_uncommitted_trims_a_bar_whose_close_has_not_happened() -> None:
    candles = tuple(_candle(EPOCH_DAY + index * DAY, 100.0 + index) for index in range(3))
    # "now" sits inside the third bar, so only two bars have committed.
    kept = drop_uncommitted(candles, interval="1d", now=EPOCH_DAY + 2 * DAY + timedelta(hours=6))
    assert len(kept) == 2
    assert kept[-1].opened_at == EPOCH_DAY + DAY


def test_aggregate_rolls_up_complete_buckets_and_drops_partial_ones() -> None:
    """A 4h bucket missing one of its four hourly bars is dropped, not completed."""
    hours = [_candle(EPOCH_DAY + index * HOUR, 100.0 + index, interval="1h") for index in range(8)]
    del hours[5]  # 05:00 is missing, so the 04:00-08:00 bucket is incomplete
    rolled = aggregate(tuple(hours), source_interval="1h", target_interval="4h")
    assert [candle.opened_at for candle in rolled] == [EPOCH_DAY]
    assert rolled[0].open == hours[0].open
    assert rolled[0].close == hours[3].close
    assert rolled[0].high == max(candle.high for candle in hours[:4])
    assert rolled[0].volume == pytest.approx(4.0)


def test_finish_series_report_header_records_venue_bounds_gaps_and_fetch_time() -> None:
    fetched_at = datetime(2026, 9, 13, 12, 0, tzinfo=UTC)
    series = finish_series(
        name="demo",
        venue="demo_venue",
        symbol="BTC/USD",
        interval="1d",
        candles=[_candle(EPOCH_DAY, 100.0), _candle(EPOCH_DAY + 3 * DAY, 103.0)],
        ok_reason="synthetic",
        fetched_at=fetched_at,
    )
    note = series.as_note()
    assert note["venue"] == "demo_venue"
    assert note["status"] == "ok"
    assert note["bars"] == 2
    assert note["first"] == EPOCH_DAY.isoformat()
    assert note["last"] == (EPOCH_DAY + 3 * DAY).isoformat()
    assert note["missing_bars"] == 2
    assert note["fetched_at"] == fetched_at.isoformat()
    assert len(note["gaps"]) == 1  # type: ignore[arg-type]


def test_finish_series_with_no_candles_is_a_skip() -> None:
    series = finish_series(
        name="demo",
        venue="demo_venue",
        symbol="BTC/USD",
        interval="1d",
        candles=[],
        ok_reason="synthetic",
        empty_reason="nothing published",
    )
    assert series.status == "skipped"
    assert series.candles == ()
    assert series.reason == "nothing published"


def test_skipped_series_never_carries_candles() -> None:
    series = skipped_series(
        name="demo", venue="v", symbol="BTC/USD", interval="1d", reason="unreachable"
    )
    assert series.status == "skipped"
    assert series.bars == 0
    assert series.first is None and series.last is None


# --- cross-venue sanity ---------------------------------------------------------


def test_close_divergence_bps_is_symmetric() -> None:
    assert close_divergence_bps(100.0, 101.0) == pytest.approx(close_divergence_bps(101.0, 100.0))
    assert close_divergence_bps(100.0, 100.0) == 0.0


def test_cross_venue_divergence_flags_a_synthetic_mismatch() -> None:
    """One deliberately mismatched daily close is flagged, never silently used."""
    kraken = tuple(_candle(EPOCH_DAY + index * DAY, 100.0) for index in range(5))
    coinbase = list(kraken)
    # Bar 2 disagrees by ~200 bps — well beyond the 50 bps reference limit.
    coinbase[2] = _candle(EPOCH_DAY + 2 * DAY, 102.0)

    report = cross_venue_divergence(
        tuple(coinbase),
        kraken,
        left_venue="coinbase_exchange",
        right_venue="kraken_ohlcvt_archive",
        max_bps=50.0,
    )
    assert report.compared_bars == 5
    assert report.status == "flagged"
    assert len(report.flagged) == 1
    flagged = report.flagged[0]
    assert flagged.opened_at == EPOCH_DAY + 2 * DAY
    assert flagged.divergence_bps == pytest.approx(198.02, abs=0.1)
    note = report.as_note()
    assert note["flagged_bars"] == 1
    assert note["max_reference_divergence_bps"] == 50.0
    assert note["flagged"][0]["opened_at"] == (EPOCH_DAY + 2 * DAY).isoformat()  # type: ignore[index]


def test_cross_venue_divergence_inside_tolerance_is_ok() -> None:
    left = tuple(_candle(EPOCH_DAY + index * DAY, 100.0) for index in range(3))
    right = tuple(_candle(EPOCH_DAY + index * DAY, 100.1) for index in range(3))
    report = cross_venue_divergence(left, right, left_venue="a", right_venue="b", max_bps=50.0)
    assert report.status == "ok"
    assert report.flagged == ()
    assert report.worst_bps == pytest.approx(9.995, abs=0.01)


def test_cross_venue_divergence_only_compares_bars_both_venues_published() -> None:
    """A bar one venue is missing is a skip, not a disagreement — and never averaged."""
    left = tuple(_candle(EPOCH_DAY + index * DAY, 100.0) for index in range(5))
    right = (left[0], left[4])
    report = cross_venue_divergence(left, right, left_venue="a", right_venue="b", max_bps=50.0)
    assert report.compared_bars == 2
    assert report.overlap_first == EPOCH_DAY
    assert report.overlap_last == EPOCH_DAY + 4 * DAY


def test_cross_venue_divergence_with_no_overlap_is_a_skip() -> None:
    left = (_candle(EPOCH_DAY, 100.0),)
    right = (_candle(EPOCH_DAY + 10 * DAY, 100.0),)
    report = cross_venue_divergence(left, right, left_venue="a", right_venue="b", max_bps=50.0)
    assert report.status == "skipped"
    assert report.compared_bars == 0


# --- Coinbase Exchange ----------------------------------------------------------


def test_coinbase_product_id_maps_and_rejects() -> None:
    assert coinbase_product_id("BTC/USD") == "BTC-USD"
    assert coinbase_product_id("eth/usd") == "ETH-USD"
    with pytest.raises(ValueError, match="BASE/QUOTE"):
        coinbase_product_id("BTCUSD")


def test_coinbase_page_windows_respect_the_300_bar_cap_at_the_boundary() -> None:
    """Exactly 300 bars is one request; 301 is two, contiguous and non-overlapping."""
    exact_end = EPOCH_DAY + (COINBASE_MAX_CANDLES_PER_REQUEST - 1) * DAY
    windows = coinbase_page_windows(
        start=EPOCH_DAY,
        end=exact_end,
        interval="1d",
        page_size=COINBASE_MAX_CANDLES_PER_REQUEST,
    )
    assert windows == [(EPOCH_DAY, exact_end)]

    one_more = coinbase_page_windows(
        start=EPOCH_DAY,
        end=exact_end + DAY,
        interval="1d",
        page_size=COINBASE_MAX_CANDLES_PER_REQUEST,
    )
    assert len(one_more) == 2
    assert one_more[0] == (EPOCH_DAY, exact_end)
    # The second page starts exactly one bar after the first ends: no overlap, no hole.
    assert one_more[1] == (exact_end + DAY, exact_end + DAY)


def test_parse_coinbase_candle_reads_time_low_high_open_close_volume_order() -> None:
    candle = parse_coinbase_candle(
        [int(EPOCH_DAY.timestamp()), 90.0, 110.0, 95.0, 105.0, 12.5],
        symbol="BTC/USD",
        interval="1d",
    )
    assert candle.opened_at == EPOCH_DAY
    assert (candle.low, candle.high, candle.open, candle.close) == (90.0, 110.0, 95.0, 105.0)
    assert candle.volume == 12.5


def test_parse_coinbase_candle_rejects_an_off_grid_timestamp() -> None:
    with pytest.raises(ArchiveParseError, match="not aligned"):
        parse_coinbase_candle(
            [int(EPOCH_DAY.timestamp()) + 61, 90.0, 110.0, 95.0, 105.0, 1.0],
            symbol="BTC/USD",
            interval="1d",
        )


def test_parse_coinbase_candle_rejects_a_non_positive_price() -> None:
    with pytest.raises(ArchiveParseError, match="positive"):
        parse_coinbase_candle(
            [int(EPOCH_DAY.timestamp()), 0.0, 110.0, 95.0, 105.0, 1.0],
            symbol="BTC/USD",
            interval="1d",
        )


def _coinbase_row(opened_at: datetime, close: float) -> list[float]:
    return [float(int(opened_at.timestamp())), close - 5.0, close + 5.0, close, close, 3.0]


@pytest.mark.asyncio
async def test_fetch_coinbase_candles_paginates_across_the_page_boundary() -> None:
    """Two requests, descending rows, merged into one ascending committed series."""
    page_size = COINBASE_MAX_CANDLES_PER_REQUEST
    start = EPOCH_DAY
    end = EPOCH_DAY + page_size * DAY  # 301 bars ⇒ 2 pages
    seen: list[tuple[str, str]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/products/BTC-USD/candles"
        assert request.url.params["granularity"] == "86400"
        window_start = datetime.fromisoformat(str(request.url.params["start"]))
        window_end = datetime.fromisoformat(str(request.url.params["end"]))
        seen.append((window_start.isoformat(), window_end.isoformat()))
        rows: list[list[float]] = []
        cursor = window_start
        while cursor <= window_end:
            rows.append(_coinbase_row(cursor, 100.0 + (cursor - start).days))
            cursor += DAY
        # Coinbase answers newest-first.
        return httpx.Response(200, json=list(reversed(rows)))

    async with httpx.AsyncClient(
        base_url=COINBASE_EXCHANGE_BASE_URL, transport=httpx.MockTransport(handler)
    ) as client:
        series = await fetch_coinbase_candles(
            "BTC/USD",
            "1d",
            start=start,
            end=end,
            client=client,
            requests_per_second=0,  # unpaced: keeps the test instant and deterministic
            now=end + DAY,
        )

    assert len(seen) == 2
    assert seen[0] == (start.isoformat(), (start + (page_size - 1) * DAY).isoformat())
    assert seen[1] == ((start + page_size * DAY).isoformat(),) * 2
    assert series.status == "ok"
    assert series.bars == page_size + 1
    assert series.first == start
    assert series.last == end
    assert series.gaps == ()
    assert series.venue == "coinbase_exchange"


@pytest.mark.asyncio
async def test_fetch_coinbase_candles_reports_a_gap_it_did_not_fill() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        rows = [
            _coinbase_row(EPOCH_DAY, 100.0),
            # 2016-01-02 and 2016-01-03 simply absent from the venue's answer.
            _coinbase_row(EPOCH_DAY + 3 * DAY, 103.0),
        ]
        return httpx.Response(200, json=list(reversed(rows)))

    async with httpx.AsyncClient(
        base_url=COINBASE_EXCHANGE_BASE_URL, transport=httpx.MockTransport(handler)
    ) as client:
        series = await fetch_coinbase_candles(
            "BTC/USD",
            "1d",
            start=EPOCH_DAY,
            end=EPOCH_DAY + 3 * DAY,
            client=client,
            requests_per_second=0,
            now=EPOCH_DAY + 10 * DAY,
        )

    assert series.status == "ok"
    assert series.bars == 2  # the hole is NOT filled
    assert len(series.gaps) == 1
    assert series.gaps[0].missing_bars == 2
    assert series.missing_bars == 2


@pytest.mark.asyncio
async def test_fetch_coinbase_candles_treats_429_as_a_skip_not_a_retry_storm() -> None:
    """The second page is rate-limited: the walk stops dead, with no retry."""
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            window_start = datetime.fromisoformat(str(request.url.params["start"]))
            return httpx.Response(200, json=[_coinbase_row(window_start, 100.0)])
        return httpx.Response(429, text="Too Many Requests")

    async with httpx.AsyncClient(
        base_url=COINBASE_EXCHANGE_BASE_URL, transport=httpx.MockTransport(handler)
    ) as client:
        series = await fetch_coinbase_candles(
            "BTC/USD",
            "1d",
            start=EPOCH_DAY,
            end=EPOCH_DAY + 2 * COINBASE_MAX_CANDLES_PER_REQUEST * DAY,
            client=client,
            requests_per_second=0,
            now=EPOCH_DAY + 1000 * DAY,
        )

    assert calls == 2, "a 429 must not be retried"
    assert series.status == "skipped"
    assert "429" in series.reason and "no retry" in series.reason
    assert series.candles == ()


@pytest.mark.asyncio
async def test_fetch_coinbase_candles_rolls_4h_up_from_complete_hourly_buckets() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        rows = [_coinbase_row(EPOCH_DAY + index * HOUR, 100.0 + index) for index in range(8)]
        del rows[5]  # one missing hour makes the second 4h bucket incomplete
        return httpx.Response(200, json=list(reversed(rows)))

    async with httpx.AsyncClient(
        base_url=COINBASE_EXCHANGE_BASE_URL, transport=httpx.MockTransport(handler)
    ) as client:
        series = await fetch_coinbase_candles(
            "BTC/USD",
            "4h",
            start=EPOCH_DAY,
            end=EPOCH_DAY + 8 * HOUR,
            client=client,
            requests_per_second=0,
            now=EPOCH_DAY + DAY,
        )

    assert series.status == "ok"
    assert series.interval == "4h"
    assert [candle.opened_at for candle in series.candles] == [EPOCH_DAY]
    assert any("rolled up" in note for note in series.notes)


@pytest.mark.asyncio
async def test_fetch_coinbase_candles_skips_an_unsupported_interval() -> None:
    series = await fetch_coinbase_candles("BTC/USD", "1w", start=EPOCH_DAY)
    assert series.status == "skipped"
    assert "unsupported interval" in series.reason


@pytest.mark.asyncio
async def test_fetch_coinbase_candles_skips_a_transport_error() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("blocked by egress policy")

    async with httpx.AsyncClient(
        base_url=COINBASE_EXCHANGE_BASE_URL, transport=httpx.MockTransport(handler)
    ) as client:
        series = await fetch_coinbase_candles(
            "BTC/USD",
            "1d",
            start=EPOCH_DAY,
            end=EPOCH_DAY + DAY,
            client=client,
            requests_per_second=0,
        )
    assert series.status == "skipped"
    assert "ConnectError" in series.reason
    assert series.candles == ()


# --- Binance Vision -------------------------------------------------------------


def _kline_csv(rows: list[list[object]], *, header: bool = False) -> str:
    lines: list[str] = []
    if header:
        lines.append(
            "open_time,open,high,low,close,volume,close_time,quote_volume,"
            "count,taker_buy_volume,taker_buy_quote_volume,ignore"
        )
    for row in rows:
        lines.append(",".join(str(field) for field in row))
    return "\n".join(lines) + "\n"


def _kline_row(opened_at: datetime, close: float, *, micros: bool = False) -> list[object]:
    scale = 1_000_000 if micros else 1_000
    opened = int(opened_at.timestamp()) * scale
    closed = int((opened_at + DAY).timestamp()) * scale - 1
    return [
        opened,
        close,
        close + 5.0,
        close - 5.0,
        close,
        7.5,
        closed,
        close * 7.5,
        42,
        3.0,
        close * 3.0,
        0,
    ]


def _zip_bytes(csv_name: str, csv_text: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(csv_name, csv_text)
    return buffer.getvalue()


def _checksum_document(payload: bytes, zip_name: str) -> str:
    return f"{hashlib.sha256(payload).hexdigest()}  {zip_name}\n"


def test_binance_vision_symbol_maps_usd_to_the_usdt_contract() -> None:
    assert binance_vision_symbol("BTC/USD") == "BTCUSDT"
    assert binance_vision_symbol("ETH/USDT") == "ETHUSDT"
    assert binance_vision_symbol("BTCUSDT") == "BTCUSDT"


def test_monthly_zip_path_matches_the_published_layout() -> None:
    assert monthly_zip_name("BTCUSDT", "1d", 2017, 9) == "BTCUSDT-1d-2017-09.zip"
    assert monthly_zip_path("BTCUSDT", "1d", 2017, 9) == (
        "/data/spot/monthly/klines/BTCUSDT/1d/BTCUSDT-1d-2017-09.zip"
    )


def test_months_between_is_inclusive_and_crosses_years() -> None:
    assert months_between(datetime(2017, 11, 5, tzinfo=UTC), datetime(2018, 2, 1, tzinfo=UTC)) == (
        (2017, 11),
        (2017, 12),
        (2018, 1),
        (2018, 2),
    )
    assert months_between(datetime(2018, 2, 1, tzinfo=UTC), datetime(2017, 1, 1, tzinfo=UTC)) == ()


def test_parse_checksum_document_extracts_the_named_digest() -> None:
    digest = "a" * 64
    assert (
        parse_checksum_document(
            f"{digest}  BTCUSDT-1d-2017-09.zip\n", zip_name="BTCUSDT-1d-2017-09.zip"
        )
        == digest
    )


def test_parse_checksum_document_fails_closed_on_a_missing_or_bad_digest() -> None:
    with pytest.raises(ChecksumError, match="names no digest"):
        parse_checksum_document("deadbeef  OTHER.zip\n", zip_name="BTCUSDT-1d-2017-09.zip")
    with pytest.raises(ChecksumError, match="not a sha256"):
        parse_checksum_document(
            "nothex  BTCUSDT-1d-2017-09.zip\n", zip_name="BTCUSDT-1d-2017-09.zip"
        )


def test_parse_monthly_zip_handles_a_header_row_and_microsecond_timestamps() -> None:
    rows = [_kline_row(EPOCH_DAY + index * DAY, 100.0 + index, micros=True) for index in range(3)]
    payload = _zip_bytes("BTCUSDT-1d-2016-01.csv", _kline_csv(rows, header=True))
    candles = parse_monthly_zip(payload, symbol="BTC/USD", interval="1d")
    assert len(candles) == 3
    assert candles[0].opened_at == EPOCH_DAY
    assert candles[-1].close == 102.0


def test_parse_monthly_zip_rejects_a_corrupt_archive() -> None:
    with pytest.raises(ArchiveParseError, match="zip"):
        parse_monthly_zip(b"not a zip at all", symbol="BTC/USD", interval="1d")


@pytest.mark.asyncio
async def test_fetch_binance_vision_monthly_verifies_each_month_and_skips_absent_ones() -> None:
    """Two published months load; a 404 month is a recorded skip, never zero-filled."""
    present = {
        (2017, 9): [_kline_row(datetime(2017, 9, day, tzinfo=UTC), 4000.0 + day) for day in (1, 2)],
        (2017, 11): [_kline_row(datetime(2017, 11, 1, tzinfo=UTC), 6400.0)],
    }
    objects: dict[str, bytes] = {}
    for (year, month), rows in present.items():
        zip_name = monthly_zip_name("BTCUSDT", "1d", year, month)
        payload = _zip_bytes(zip_name.replace(".zip", ".csv"), _kline_csv(rows))
        path = monthly_zip_path("BTCUSDT", "1d", year, month)
        objects[path] = payload
        objects[f"{path}.CHECKSUM"] = _checksum_document(payload, zip_name).encode()

    async def handler(request: httpx.Request) -> httpx.Response:
        body = objects.get(request.url.path)
        if body is None:
            return httpx.Response(404, text="Not Found")
        return httpx.Response(200, content=body)

    async with httpx.AsyncClient(
        base_url=BINANCE_VISION_BASE_URL, transport=httpx.MockTransport(handler)
    ) as client:
        series = await fetch_binance_vision_monthly(
            "BTC/USD",
            "1d",
            start=datetime(2017, 9, 1, tzinfo=UTC),
            end=datetime(2017, 11, 30, tzinfo=UTC),
            client=client,
        )

    assert series.status == "ok"
    assert series.bars == 3
    assert series.first == datetime(2017, 9, 1, tzinfo=UTC)
    assert series.last == datetime(2017, 11, 1, tzinfo=UTC)
    assert any("2017-10 (404)" in note for note in series.notes)
    # The absent month is a gap, not a run of invented bars.
    assert series.missing_bars == detect_gaps(series.candles, "1d")[-1].missing_bars


@pytest.mark.asyncio
async def test_binance_vision_checksum_mismatch_fails_closed() -> None:
    """A zip whose bytes do not match the published digest yields NO candles."""
    zip_name = monthly_zip_name("BTCUSDT", "1d", 2017, 9)
    path = monthly_zip_path("BTCUSDT", "1d", 2017, 9)
    good_rows = [_kline_row(datetime(2017, 9, 1, tzinfo=UTC), 4000.0)]
    served = _zip_bytes(zip_name.replace(".zip", ".csv"), _kline_csv(good_rows))
    # The published digest belongs to *different* bytes — i.e. the download is
    # corrupt or substituted.
    published = _checksum_document(b"the bytes the publisher hashed", zip_name).encode()

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(".CHECKSUM"):
            return httpx.Response(200, content=published)
        if request.url.path == path:
            return httpx.Response(200, content=served)
        return httpx.Response(404)

    async with httpx.AsyncClient(
        base_url=BINANCE_VISION_BASE_URL, transport=httpx.MockTransport(handler)
    ) as client:
        series = await fetch_binance_vision_monthly(
            "BTC/USD",
            "1d",
            start=datetime(2017, 9, 1, tzinfo=UTC),
            end=datetime(2017, 9, 30, tzinfo=UTC),
            client=client,
        )

    assert series.status == "skipped"
    assert series.candles == (), "a failed checksum must not yield any candles"
    assert "sha256 mismatch" in series.reason


@pytest.mark.asyncio
async def test_binance_vision_checksum_mismatch_discards_already_verified_months() -> None:
    """Fail-closed is whole-series: a good month does not survive a later bad one."""
    good_name = monthly_zip_name("BTCUSDT", "1d", 2017, 9)
    good_path = monthly_zip_path("BTCUSDT", "1d", 2017, 9)
    good_zip = _zip_bytes(
        good_name.replace(".zip", ".csv"),
        _kline_csv([_kline_row(datetime(2017, 9, 1, tzinfo=UTC), 4000.0)]),
    )
    bad_name = monthly_zip_name("BTCUSDT", "1d", 2017, 10)
    bad_path = monthly_zip_path("BTCUSDT", "1d", 2017, 10)
    bad_zip = _zip_bytes(
        bad_name.replace(".zip", ".csv"),
        _kline_csv([_kline_row(datetime(2017, 10, 1, tzinfo=UTC), 4400.0)]),
    )
    objects = {
        good_path: good_zip,
        f"{good_path}.CHECKSUM": _checksum_document(good_zip, good_name).encode(),
        bad_path: bad_zip,
        f"{bad_path}.CHECKSUM": _checksum_document(b"tampered", bad_name).encode(),
    }

    async def handler(request: httpx.Request) -> httpx.Response:
        body = objects.get(request.url.path)
        return httpx.Response(404) if body is None else httpx.Response(200, content=body)

    async with httpx.AsyncClient(
        base_url=BINANCE_VISION_BASE_URL, transport=httpx.MockTransport(handler)
    ) as client:
        series = await fetch_binance_vision_monthly(
            "BTC/USD",
            "1d",
            start=datetime(2017, 9, 1, tzinfo=UTC),
            end=datetime(2017, 10, 31, tzinfo=UTC),
            client=client,
        )

    assert series.status == "skipped"
    assert series.candles == ()


@pytest.mark.asyncio
async def test_binance_vision_missing_checksum_document_fails_closed() -> None:
    """Data present but no published digest ⇒ refuse it rather than trust it."""
    path = monthly_zip_path("BTCUSDT", "1d", 2017, 9)
    payload = _zip_bytes(
        "BTCUSDT-1d-2017-09.csv",
        _kline_csv([_kline_row(datetime(2017, 9, 1, tzinfo=UTC), 4000.0)]),
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == path:
            return httpx.Response(200, content=payload)
        return httpx.Response(404, text="Not Found")

    async with httpx.AsyncClient(
        base_url=BINANCE_VISION_BASE_URL, transport=httpx.MockTransport(handler)
    ) as client:
        series = await fetch_binance_vision_monthly(
            "BTC/USD",
            "1d",
            start=datetime(2017, 9, 1, tzinfo=UTC),
            end=datetime(2017, 9, 30, tzinfo=UTC),
            client=client,
        )

    assert series.status == "skipped"
    assert series.candles == ()
    assert "no published .CHECKSUM" in series.reason


# --- Kraken OHLCVT archive ------------------------------------------------------


def _ohlcvt_csv(rows: int, *, start: datetime = EPOCH_DAY) -> str:
    lines = []
    for index in range(rows):
        opened = int((start + index * DAY).timestamp())
        close = 400.0 + index
        lines.append(f"{opened},{close},{close + 5},{close - 5},{close},12.5,88")
    return "\n".join(lines) + "\n"


def test_kraken_archive_pair_uses_kraken_asset_codes() -> None:
    assert kraken_archive_pair("BTC/USD") == "XBTUSD"
    assert kraken_archive_pair("ETH/USD") == "ETHUSD"
    assert kraken_archive_filename("BTC/USD", "1d") == "XBTUSD_1440.csv"
    assert kraken_archive_filename("ETH/USD", "1h") == "ETHUSD_60.csv"


def test_load_kraken_archive_reads_a_good_drop_and_flags_survivorship_bias(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "kraken_ohlcvt"
    directory.mkdir()
    (directory / "XBTUSD_1440.csv").write_text(_ohlcvt_csv(5))

    series = load_kraken_archive(directory, "BTC/USD", "1d")

    assert series.status == "ok"
    assert series.bars == 5
    assert series.first == EPOCH_DAY
    assert series.gaps == ()
    assert SURVIVORSHIP_NOTE in series.notes


def test_load_kraken_archive_refuses_a_truncated_row(tmp_path: Path) -> None:
    """A partial file yields NO candles at all — not the rows that happened to parse."""
    path = tmp_path / "XBTUSD_1440.csv"
    path.write_text(_ohlcvt_csv(3) + "1451779200,405.0,410.0")  # truncated final line

    series = load_kraken_archive(path, "BTC/USD", "1d")

    assert series.status == "skipped"
    assert series.candles == ()
    assert "refusing a partial/unparsable archive" in series.reason
    assert "line 4" in series.reason


def test_load_kraken_archive_refuses_a_non_numeric_field(tmp_path: Path) -> None:
    path = tmp_path / "XBTUSD_1440.csv"
    path.write_text("1451606400,400.0,405.0,395.0,not-a-price,12.5,88\n")

    series = load_kraken_archive(path, "BTC/USD", "1d")

    assert series.status == "skipped"
    assert series.candles == ()
    assert "not numeric" in series.reason


def test_load_kraken_archive_refuses_an_off_grid_timestamp(tmp_path: Path) -> None:
    path = tmp_path / "XBTUSD_1440.csv"
    path.write_text("1451606460,400.0,405.0,395.0,402.0,12.5,88\n")

    series = load_kraken_archive(path, "BTC/USD", "1d")

    assert series.status == "skipped"
    assert "not aligned" in series.reason


def test_load_kraken_archive_missing_file_is_a_clean_skip(tmp_path: Path) -> None:
    series = load_kraken_archive(tmp_path / "nope", "BTC/USD", "1d")
    assert series.status == "skipped"
    assert "no such OHLCVT file" in series.reason


def test_load_kraken_archive_empty_file_is_a_clean_skip(tmp_path: Path) -> None:
    path = tmp_path / "XBTUSD_1440.csv"
    path.write_text("\n\n")
    series = load_kraken_archive(path, "BTC/USD", "1d")
    assert series.status == "skipped"
    assert "empty" in series.reason


def test_load_kraken_archive_windows_without_reparsing_partial_data(tmp_path: Path) -> None:
    path = tmp_path / "XBTUSD_1440.csv"
    path.write_text(_ohlcvt_csv(10))
    series = load_kraken_archive(
        path, "BTC/USD", "1d", start=EPOCH_DAY + 2 * DAY, end=EPOCH_DAY + 4 * DAY
    )
    assert series.status == "ok"
    assert [candle.opened_at for candle in series.candles] == [
        EPOCH_DAY + 2 * DAY,
        EPOCH_DAY + 3 * DAY,
        EPOCH_DAY + 4 * DAY,
    ]


# --- traderstack-download-candles wiring ----------------------------------------


def test_candle_json_round_trips_the_existing_format(tmp_path: Path) -> None:
    """The archive writer emits exactly what `traderstack-research --candles` reads."""
    from traderstack.research.cli import load_candles_from_json

    out = tmp_path / "btc.json"
    candles = tuple(_candle(EPOCH_DAY + index * DAY, 100.0 + index) for index in range(3))
    write_candle_json(out, candles)

    payload = json.loads(out.read_text())
    assert isinstance(payload, list)
    assert set(payload[0]) == {
        "symbol",
        "interval",
        "opened_at",
        "open",
        "high",
        "low",
        "close",
        "volume",
    }
    assert load_candles_from_json(out) == candles
    assert read_candle_json(out) == candles


def test_download_candles_cli_kraken_archive_writes_candles_and_a_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    archive = tmp_path / "XBTUSD_1440.csv"
    archive.write_text(_ohlcvt_csv(4))
    out = tmp_path / "btc_1d.json"

    main(
        [
            "BTC/USD",
            "--venue",
            "kraken_archive",
            "--resolution",
            "1d",
            "--archive-path",
            str(archive),
            "--out",
            str(out),
        ]
    )

    assert len(read_candle_json(out)) == 4
    report = json.loads((tmp_path / "btc_1d.json.report.json").read_text())
    header = report["series"]
    assert header["venue"] == "kraken_ohlcvt_archive"
    assert header["status"] == "ok"
    assert header["bars"] == 4
    assert header["first"] == EPOCH_DAY.isoformat()
    assert header["last"] == (EPOCH_DAY + 3 * DAY).isoformat()
    assert header["gaps"] == []
    assert header["fetched_at"]
    assert "wrote 4 candles" in capsys.readouterr().out


def test_download_candles_cli_flags_a_cross_venue_divergence(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A Kraken/Coinbase daily close mismatch is reported, never silently used."""
    archive = tmp_path / "XBTUSD_1440.csv"
    archive.write_text(_ohlcvt_csv(4))
    # A "Coinbase" export that agrees on every bar except one.
    reference = [_candle(EPOCH_DAY + index * DAY, 400.0 + index) for index in range(4)]
    reference[2] = _candle(EPOCH_DAY + 2 * DAY, 500.0)
    reference_path = tmp_path / "coinbase_1d.json"
    write_candle_json(reference_path, tuple(reference))
    out = tmp_path / "btc_1d.json"

    main(
        [
            "BTC/USD",
            "--venue",
            "kraken_archive",
            "--resolution",
            "1d",
            "--archive-path",
            str(archive),
            "--out",
            str(out),
            "--cross-check",
            str(reference_path),
            "--max-divergence-bps",
            "50",
        ]
    )

    report = json.loads((tmp_path / "btc_1d.json.report.json").read_text())
    divergence = report["cross_venue_divergence"]
    assert divergence["status"] == "flagged"
    assert divergence["compared_bars"] == 4
    assert divergence["flagged_bars"] == 1
    assert divergence["flagged"][0]["opened_at"] == (EPOCH_DAY + 2 * DAY).isoformat()
    assert "WARNING" in capsys.readouterr().out


def test_download_candles_cli_skip_writes_a_report_and_no_candle_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "btc_1d.json"
    main(
        [
            "BTC/USD",
            "--venue",
            "kraken_archive",
            "--resolution",
            "1d",
            "--archive-path",
            str(tmp_path / "absent.csv"),
            "--out",
            str(out),
        ]
    )
    assert not out.exists(), "a skipped series must not leave a candle file behind"
    report = json.loads((tmp_path / "btc_1d.json.report.json").read_text())
    assert report["series"]["status"] == "skipped"
    assert "skipped" in capsys.readouterr().out


def test_build_archive_report_without_a_cross_check_has_no_divergence_block() -> None:
    series = finish_series(
        name="demo",
        venue="v",
        symbol="BTC/USD",
        interval="1d",
        candles=[_candle(EPOCH_DAY, 100.0)],
        ok_reason="synthetic",
    )
    assert build_archive_report(series) == {"series": series.as_note()}


# --- additional fail-closed / skip branches -------------------------------------


@pytest.mark.asyncio
async def test_fetch_coinbase_candles_skips_a_malformed_symbol() -> None:
    series = await fetch_coinbase_candles("BTCUSD", "1d", start=EPOCH_DAY)
    assert series.status == "skipped"
    assert "BASE/QUOTE" in series.reason
    assert series.candles == ()


@pytest.mark.asyncio
async def test_fetch_coinbase_candles_skips_an_inverted_window() -> None:
    series = await fetch_coinbase_candles("BTC/USD", "1d", start=EPOCH_DAY + DAY, end=EPOCH_DAY)
    assert series.status == "skipped"
    assert "empty window" in series.reason


@pytest.mark.asyncio
async def test_fetch_coinbase_candles_records_a_max_requests_truncation() -> None:
    """A truncated walk says so in the report rather than looking complete."""

    async def handler(request: httpx.Request) -> httpx.Response:
        window_start = datetime.fromisoformat(str(request.url.params["start"]))
        return httpx.Response(200, json=[_coinbase_row(window_start, 100.0)])

    async with httpx.AsyncClient(
        base_url=COINBASE_EXCHANGE_BASE_URL, transport=httpx.MockTransport(handler)
    ) as client:
        series = await fetch_coinbase_candles(
            "BTC/USD",
            "1d",
            start=EPOCH_DAY,
            end=EPOCH_DAY + 3 * COINBASE_MAX_CANDLES_PER_REQUEST * DAY,
            client=client,
            requests_per_second=0,
            max_requests=1,
            now=EPOCH_DAY + 5000 * DAY,
        )

    assert series.status == "ok"
    assert any("max_requests=1" in note for note in series.notes)


@pytest.mark.asyncio
async def test_fetch_coinbase_candles_skips_a_venue_error_body() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"message": "NotFound"})

    async with httpx.AsyncClient(
        base_url=COINBASE_EXCHANGE_BASE_URL, transport=httpx.MockTransport(handler)
    ) as client:
        series = await fetch_coinbase_candles(
            "BTC/USD",
            "1d",
            start=EPOCH_DAY,
            end=EPOCH_DAY + DAY,
            client=client,
            requests_per_second=0,
        )
    assert series.status == "skipped"
    assert "NotFound" in series.reason


def test_coinbase_page_windows_rejects_a_non_positive_page_size() -> None:
    with pytest.raises(ValueError, match="page_size"):
        coinbase_page_windows(start=EPOCH_DAY, end=EPOCH_DAY + DAY, interval="1d", page_size=0)


@pytest.mark.asyncio
async def test_fetch_binance_vision_skips_an_unsupported_interval() -> None:
    series = await fetch_binance_vision_monthly(
        "BTC/USD", "1w", start=datetime(2017, 9, 1, tzinfo=UTC)
    )
    assert series.status == "skipped"
    assert "unsupported interval" in series.reason


@pytest.mark.asyncio
async def test_fetch_binance_vision_skips_months_before_the_archive_starts() -> None:
    """2017-07 predates the spot archive: noted as absent, never zero-filled."""
    zip_name = monthly_zip_name("BTCUSDT", "1d", 2017, 8)
    path = monthly_zip_path("BTCUSDT", "1d", 2017, 8)
    payload = _zip_bytes(
        zip_name.replace(".zip", ".csv"),
        _kline_csv([_kline_row(datetime(2017, 8, 17, tzinfo=UTC), 4300.0)]),
    )
    objects = {path: payload, f"{path}.CHECKSUM": _checksum_document(payload, zip_name).encode()}

    async def handler(request: httpx.Request) -> httpx.Response:
        body = objects.get(request.url.path)
        return httpx.Response(404) if body is None else httpx.Response(200, content=body)

    async with httpx.AsyncClient(
        base_url=BINANCE_VISION_BASE_URL, transport=httpx.MockTransport(handler)
    ) as client:
        series = await fetch_binance_vision_monthly(
            "BTC/USD",
            "1d",
            start=datetime(2017, 6, 1, tzinfo=UTC),
            end=datetime(2017, 8, 31, tzinfo=UTC),
            client=client,
        )

    assert series.status == "ok"
    assert series.bars == 1
    assert any("before spot archive start" in note for note in series.notes)


@pytest.mark.asyncio
async def test_fetch_binance_vision_skips_a_transport_error() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("blocked by egress policy")

    async with httpx.AsyncClient(
        base_url=BINANCE_VISION_BASE_URL, transport=httpx.MockTransport(handler)
    ) as client:
        series = await fetch_binance_vision_monthly(
            "BTC/USD",
            "1d",
            start=datetime(2017, 9, 1, tzinfo=UTC),
            end=datetime(2017, 9, 30, tzinfo=UTC),
            client=client,
        )
    assert series.status == "skipped"
    assert "ConnectError" in series.reason
    assert series.candles == ()


@pytest.mark.asyncio
async def test_fetch_binance_vision_with_an_empty_month_window_is_a_skip() -> None:
    series = await fetch_binance_vision_monthly(
        "BTC/USD",
        "1d",
        start=datetime(2018, 1, 1, tzinfo=UTC),
        end=datetime(2017, 1, 1, tzinfo=UTC),
    )
    assert series.status == "skipped"
    assert "empty month window" in series.reason


def test_binance_vision_symbol_rejects_an_empty_symbol() -> None:
    with pytest.raises(ValueError, match="BASE/QUOTE"):
        binance_vision_symbol("/USD")


def test_kraken_archive_filename_rejects_an_unsupported_interval() -> None:
    with pytest.raises(ValueError, match="unsupported interval"):
        kraken_archive_filename("BTC/USD", "2h")


def test_kraken_archive_pair_rejects_a_malformed_symbol() -> None:
    with pytest.raises(ValueError, match="BASE/QUOTE"):
        kraken_archive_pair("XBTUSD")


def test_load_kraken_archive_with_a_bad_interval_is_a_skip(tmp_path: Path) -> None:
    series = load_kraken_archive(tmp_path, "BTC/USD", "2h")
    assert series.status == "skipped"
    assert "unsupported interval" in series.reason


def test_load_kraken_archive_refuses_a_negative_volume(tmp_path: Path) -> None:
    path = tmp_path / "XBTUSD_1440.csv"
    path.write_text("1451606400,400.0,405.0,395.0,402.0,-1.0,88\n")
    series = load_kraken_archive(path, "BTC/USD", "1d")
    assert series.status == "skipped"
    assert "volume" in series.reason


def test_load_kraken_archive_refuses_a_non_positive_price(tmp_path: Path) -> None:
    path = tmp_path / "XBTUSD_1440.csv"
    path.write_text("1451606400,0.0,405.0,395.0,402.0,1.0,88\n")
    series = load_kraken_archive(path, "BTC/USD", "1d")
    assert series.status == "skipped"
    assert "positive" in series.reason


def test_load_kraken_archive_window_outside_the_file_is_a_skip(tmp_path: Path) -> None:
    path = tmp_path / "XBTUSD_1440.csv"
    path.write_text(_ohlcvt_csv(3))
    series = load_kraken_archive(path, "BTC/USD", "1d", start=EPOCH_DAY + 100 * DAY)
    assert series.status == "skipped"
    assert "no rows inside the requested window" in series.reason


def test_aggregate_rejects_a_non_multiple_target_interval() -> None:
    with pytest.raises(ValueError, match="whole multiple"):
        aggregate((), source_interval="1h", target_interval="90m")


def test_cross_venue_divergence_rejects_a_non_positive_threshold() -> None:
    with pytest.raises(ValueError, match="max_bps"):
        cross_venue_divergence((), (), left_venue="a", right_venue="b", max_bps=0.0)


# --- CLI dispatch / Settings wiring (no network) ---------------------------------


@pytest.mark.asyncio
async def test_fetch_archive_series_requires_a_start_for_network_venues() -> None:
    parser = build_parser()
    for venue in ("coinbase", "binance_vision"):
        args = parser.parse_args(["BTC/USD", "--venue", venue, "--out", "out.json"])
        with pytest.raises(ValueError, match="--start is required"):
            await fetch_archive_series(args)


@pytest.mark.asyncio
async def test_kraken_archive_venue_reads_the_path_from_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = tmp_path / "XBTUSD_1440.csv"
    archive.write_text(_ohlcvt_csv(2))
    monkeypatch.setenv("RESEARCH_KRAKEN_ARCHIVE_PATH", str(archive))
    args = build_parser().parse_args(
        ["BTC/USD", "--venue", "kraken_archive", "--resolution", "1d", "--out", "out.json"]
    )
    series = await fetch_archive_series(args)
    assert series.status == "ok"
    assert series.bars == 2


@pytest.mark.asyncio
async def test_kraken_archive_venue_without_a_configured_path_is_an_explicit_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RESEARCH_KRAKEN_ARCHIVE_PATH", "")
    args = build_parser().parse_args(
        ["BTC/USD", "--venue", "kraken_archive", "--resolution", "1d", "--out", "out.json"]
    )
    with pytest.raises(ValueError, match="RESEARCH_KRAKEN_ARCHIVE_PATH"):
        await fetch_archive_series(args)


def test_divergence_threshold_defaults_to_the_settings_reference_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The cross-check reads MAX_REFERENCE_DIVERGENCE_BPS; it never writes it."""
    monkeypatch.setenv("MAX_REFERENCE_DIVERGENCE_BPS", "25")
    assert _resolve_max_divergence_bps(None) == 25.0
    assert _resolve_max_divergence_bps(12.5) == 12.5
