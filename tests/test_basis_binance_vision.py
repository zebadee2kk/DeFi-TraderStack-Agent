"""Binance Vision daily mark−index basis adapter (#134): zips, checksums, layout."""

from __future__ import annotations

import hashlib
import io
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from traderstack.research.basis_binance_vision import (
    VISION_INDEX_KIND,
    VISION_MARK_KIND,
    fetch_binance_vision_basis,
    fetch_binance_vision_daily_closes,
    fetch_vision_zip,
    normalize_epoch_ms,
    parse_vision_kline_csv,
    unzip_single_csv,
    verify_vision_checksum,
    vision_zip_path,
)


async def no_sleep(_seconds: float) -> None:
    return None


def day_ms(day: datetime) -> int:
    return int(day.timestamp() * 1000)


def kline_csv(days: list[datetime], closes: list[float], *, header: bool) -> bytes:
    lines = []
    if header:
        lines.append(
            "open_time,open,high,low,close,volume,close_time,quote_volume,count,"
            "taker_buy_volume,taker_buy_quote_volume,ignore"
        )
    for day, close in zip(days, closes, strict=True):
        lines.append(f"{day_ms(day)},1,2,0.5,{close},0,{day_ms(day) + 86_399_999},0,86400,0,0,0")
    return ("\n".join(lines) + "\n").encode()


def make_zip(csv_name: str, csv_bytes: bytes) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(csv_name, csv_bytes)
    return buffer.getvalue()


def checksum_line(data: bytes, filename: str) -> str:
    return f"{hashlib.sha256(data).hexdigest()}  {filename}\n"


class VisionServer:
    """Serve monthly / daily zips keyed by published path; 404 otherwise."""

    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.checksums: dict[str, str] = {}
        self.requests: list[str] = []

    def add(self, path: str, data: bytes, *, checksum: str | None = "auto") -> None:
        self.files[path] = data
        if checksum == "auto":
            self.checksums[path + ".CHECKSUM"] = checksum_line(data, path.rsplit("/", 1)[-1])
        elif checksum is not None:
            self.checksums[path + ".CHECKSUM"] = checksum

    async def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.requests.append(path)
        if path in self.files:
            return httpx.Response(200, content=self.files[path])
        if path in self.checksums:
            return httpx.Response(200, text=self.checksums[path])
        return httpx.Response(404, text="not found")


def month_days(year: int, month: int) -> list[datetime]:
    start = datetime(year, month, 1, tzinfo=UTC)
    days = []
    day = start
    while day.month == month:
        days.append(day)
        day += timedelta(days=1)
    return days


def add_month(
    server: VisionServer, kind: str, contract: str, year: int, month: int, base: float
) -> None:
    days = month_days(year, month)
    path = vision_zip_path(kind, contract, month=(year, month))
    name = path.rsplit("/", 1)[-1].replace(".zip", ".csv")
    server.add(
        path,
        make_zip(name, kline_csv(days, [base + i for i in range(len(days))], header=year >= 2025)),
    )


def add_day(server: VisionServer, kind: str, contract: str, day: datetime, close: float) -> None:
    path = vision_zip_path(kind, contract, day=day.date())
    name = path.rsplit("/", 1)[-1].replace(".zip", ".csv")
    server.add(path, make_zip(name, kline_csv([day], [close], header=True)))


def test_zip_paths_follow_the_published_layout_and_refuse_forbidden_kinds() -> None:
    assert (
        vision_zip_path(VISION_MARK_KIND, "BTCUSDT", month=(2020, 1))
        == "/data/futures/um/monthly/markPriceKlines/BTCUSDT/1d/BTCUSDT-1d-2020-01.zip"
    )
    assert (
        vision_zip_path(VISION_INDEX_KIND, "ETHUSDT", day=datetime(2026, 9, 12, tzinfo=UTC).date())
        == "/data/futures/um/daily/indexPriceKlines/ETHUSDT/1d/ETHUSDT-1d-2026-09-12.zip"
    )
    for kind in (
        "premiumIndexKlines",
        "klines",
        "fundingRate",
        "aggTrades",
        "trades",
        "bookTicker",
    ):
        with pytest.raises(ValueError):
            vision_zip_path(kind, "BTCUSDT", month=(2020, 1))
    with pytest.raises(ValueError):
        vision_zip_path(VISION_MARK_KIND, "BTCUSDT")


def test_csv_parses_with_and_without_header_and_drops_bad_rows() -> None:
    days = [datetime(2020, 1, 1, tzinfo=UTC), datetime(2020, 1, 2, tzinfo=UTC)]
    with_header = parse_vision_kline_csv(kline_csv(days, [7.0, 8.0], header=True))
    without = parse_vision_kline_csv(kline_csv(days, [7.0, 8.0], header=False))
    assert with_header == without == [(day_ms(days[0]), 7.0), (day_ms(days[1]), 8.0)]
    junk = b"open_time,open\n1577836800000,1,2,0.5,nan,0\n1577923200000,1,2,0.5,-1,0\nx,y,z,w,v\n"
    assert parse_vision_kline_csv(junk) == []
    assert normalize_epoch_ms(1_577_836_800) == 1_577_836_800_000
    assert normalize_epoch_ms(1_577_836_800_000) == 1_577_836_800_000
    assert normalize_epoch_ms(1_577_836_800_000_000) == 1_577_836_800_000


def test_checksum_verification_fails_closed() -> None:
    data = b"zipbytes"
    verify_vision_checksum(data, checksum_line(data, "X-1d-2020-01.zip"), "X-1d-2020-01.zip")
    with pytest.raises(ValueError):
        verify_vision_checksum(data + b"!", checksum_line(data, "X.zip"), "X.zip")
    with pytest.raises(ValueError):
        verify_vision_checksum(data, "", "X.zip")
    with pytest.raises(ValueError):
        verify_vision_checksum(data, "deadbeef  X.zip", "X.zip")
    with pytest.raises(ValueError):
        verify_vision_checksum(data, checksum_line(data, "OTHER.zip"), "X.zip")


def test_unzip_refuses_multi_member_archives() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("a.csv", b"1,2,3,4,5")
        archive.writestr("b.csv", b"1,2,3,4,5")
    with pytest.raises(ValueError):
        unzip_single_csv(buffer.getvalue())
    assert unzip_single_csv(make_zip("only.csv", b"1,2,3,4,5")) == b"1,2,3,4,5"


@pytest.mark.asyncio
async def test_fetch_zip_verifies_checksum_and_reuses_verified_cache(tmp_path: Path) -> None:
    server = VisionServer()
    path = vision_zip_path(VISION_MARK_KIND, "BTCUSDT", month=(2024, 1))
    good = make_zip("BTCUSDT-1d-2024-01.csv", b"1704067200000,1,2,0.5,100,0\n")
    server.add(path, good)
    async with httpx.AsyncClient(
        base_url="https://data.binance.vision", transport=httpx.MockTransport(server.handler)
    ) as client:
        data, status = await fetch_vision_zip(client, path, cache_dir=tmp_path, sleep=no_sleep)
        assert status == "ok" and data == good
        data, status = await fetch_vision_zip(client, path, cache_dir=tmp_path, sleep=no_sleep)
        assert status == "cache" and data == good
        # Tamper with the cached zip: the cache is re-verified and refetched, not trusted.
        cached = tmp_path / path.lstrip("/")
        cached.write_bytes(b"tampered")
        data, status = await fetch_vision_zip(client, path, cache_dir=tmp_path, sleep=no_sleep)
        assert status == "ok" and data == good
    assert server.requests.count(path) == 2


@pytest.mark.asyncio
async def test_checksum_mismatch_and_missing_checksum_skip_that_month(tmp_path: Path) -> None:
    server = VisionServer()
    bad_path = vision_zip_path(VISION_MARK_KIND, "BTCUSDT", month=(2024, 1))
    server.add(
        bad_path, make_zip("x.csv", b"1704067200000,1,2,0.5,100,0\n"), checksum="0" * 64 + "  x\n"
    )
    nochk_path = vision_zip_path(VISION_MARK_KIND, "BTCUSDT", month=(2024, 2))
    server.add(nochk_path, make_zip("y.csv", b"1706745600000,1,2,0.5,100,0\n"), checksum=None)
    async with httpx.AsyncClient(
        base_url="https://data.binance.vision", transport=httpx.MockTransport(server.handler)
    ) as client:
        data, status = await fetch_vision_zip(client, bad_path, cache_dir=tmp_path, sleep=no_sleep)
        assert data is None and "mismatch" in status
        data, status = await fetch_vision_zip(
            client, nochk_path, cache_dir=tmp_path, sleep=no_sleep
        )
        assert data is None and "missing .CHECKSUM" in status
        result = await fetch_binance_vision_daily_closes(
            client,
            VISION_MARK_KIND,
            "BTCUSDT",
            since=datetime(2024, 1, 1, tzinfo=UTC),
            until=datetime(2024, 2, 29, tzinfo=UTC),
            cache_dir=tmp_path,
            sleep=no_sleep,
            now=datetime(2024, 6, 1, tzinfo=UTC),
        )
    assert result.closes == {}
    assert result.checksum_failures == 2
    assert result.months_missing == 2
    # fail closed: no daily fallback was attempted for a checksum-failed month
    assert not any("/daily/" in path for path in server.requests)
    assert not list(tmp_path.rglob("*.zip"))


@pytest.mark.asyncio
async def test_404_month_is_skipped_without_zero_fill(tmp_path: Path) -> None:
    server = VisionServer()
    add_month(server, VISION_MARK_KIND, "BTCUSDT", 2024, 1, 100.0)
    # 2024-02 is absent (404); daily fallback is also 404 → simply missing
    add_month(server, VISION_MARK_KIND, "BTCUSDT", 2024, 3, 200.0)
    async with httpx.AsyncClient(
        base_url="https://data.binance.vision", transport=httpx.MockTransport(server.handler)
    ) as client:
        result = await fetch_binance_vision_daily_closes(
            client,
            VISION_MARK_KIND,
            "BTCUSDT",
            since=datetime(2024, 1, 1, tzinfo=UTC),
            until=datetime(2024, 3, 31, tzinfo=UTC),
            cache_dir=tmp_path,
            sleep=no_sleep,
            now=datetime(2024, 6, 1, tzinfo=UTC),
        )
    assert len(result.closes) == 31 + 31
    assert all(day.month != 2 for day in result.closes)
    assert result.months_ok == 2 and result.months_missing == 1
    assert result.days_missing == 29
    assert 0.0 not in result.closes.values()


@pytest.mark.asyncio
async def test_trailing_month_uses_daily_zips_and_drops_today(tmp_path: Path) -> None:
    server = VisionServer()
    add_month(server, VISION_MARK_KIND, "ETHUSDT", 2026, 8, 50.0)
    for offset in range(1, 14):
        add_day(
            server,
            VISION_MARK_KIND,
            "ETHUSDT",
            datetime(2026, 9, offset, tzinfo=UTC),
            60.0 + offset,
        )
    now = datetime(2026, 9, 13, 10, 0, tzinfo=UTC)
    async with httpx.AsyncClient(
        base_url="https://data.binance.vision", transport=httpx.MockTransport(server.handler)
    ) as client:
        result = await fetch_binance_vision_daily_closes(
            client,
            VISION_MARK_KIND,
            "ETHUSDT",
            since=datetime(2026, 8, 20, tzinfo=UTC),
            until=datetime(2026, 9, 13, tzinfo=UTC),
            cache_dir=tmp_path,
            sleep=no_sleep,
            now=now,
        )
    days = sorted(result.closes)
    assert days[0] == datetime(2026, 8, 20, tzinfo=UTC)
    assert days[-1] == datetime(2026, 9, 12, tzinfo=UTC)  # today (13th) dropped
    assert datetime(2026, 9, 13, tzinfo=UTC) not in result.closes
    assert result.months_ok == 1 and result.days_ok == 12
    daily_paths = [p for p in server.requests if "/daily/" in p and p.endswith(".zip")]
    assert not any("2026-09-13" in p for p in daily_paths)
    monthly_sept = [p for p in server.requests if "/monthly/" in p and "2026-09" in p]
    assert monthly_sept == []


@pytest.mark.asyncio
async def test_basis_is_mark_minus_index_and_one_sided_days_skipped(tmp_path: Path) -> None:
    server = VisionServer()
    add_month(server, VISION_MARK_KIND, "BTCUSDT", 2024, 1, 101.0)
    add_month(server, VISION_INDEX_KIND, "BTCUSDT", 2024, 1, 100.0)
    add_month(server, VISION_MARK_KIND, "BTCUSDT", 2024, 2, 101.0)
    # index for 2024-02 missing → those days are one-sided → skipped, never zero
    async with httpx.AsyncClient(
        base_url="https://data.binance.vision", transport=httpx.MockTransport(server.handler)
    ) as client:
        result = await fetch_binance_vision_basis(
            "BTC/USD",
            client=client,
            since=datetime(2024, 1, 1, tzinfo=UTC),
            until=datetime(2024, 2, 29, tzinfo=UTC),
            cache_dir=tmp_path,
            sleep=no_sleep,
            now=datetime(2024, 6, 1, tzinfo=UTC),
        )
    assert result.status == "ok"
    assert len(result.points) == 31
    assert result.points[0][0] == datetime(2024, 1, 1, tzinfo=UTC)
    assert result.points[0][1] == pytest.approx(0.01)
    assert "premium" not in result.source
    assert "one_sided_days_skipped=29" in result.reason
    assert not any("premiumIndexKlines" in p or "/klines/" in p for p in server.requests)


@pytest.mark.asyncio
async def test_unreachable_venue_is_a_skip_not_a_series(tmp_path: Path) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    async with httpx.AsyncClient(
        base_url="https://data.binance.vision", transport=httpx.MockTransport(handler)
    ) as client:
        result = await fetch_binance_vision_basis(
            "ETH/USD",
            client=client,
            since=datetime(2024, 1, 1, tzinfo=UTC),
            until=datetime(2024, 1, 31, tzinfo=UTC),
            cache_dir=tmp_path,
            sleep=no_sleep,
            now=datetime(2024, 6, 1, tzinfo=UTC),
        )
    assert result.status == "skipped"
    assert result.points == ()
    assert "no verified daily rows" in result.reason
