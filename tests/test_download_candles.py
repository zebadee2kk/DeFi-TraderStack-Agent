from datetime import UTC, datetime

import httpx
import pytest

from traderstack.research.download_candles import (
    _kraken_pair,
    _parse_since,
    download_candles,
    download_spot_histories,
    fetch_ohlc_page,
)


def test_kraken_pair_formats_symbol() -> None:
    assert _kraken_pair("BTC/USD") == "BTCUSD"
    assert _kraken_pair("eth/usd") == "ETHUSD"


def test_kraken_pair_rejects_malformed_symbol() -> None:
    with pytest.raises(ValueError):
        _kraken_pair("BTCUSD")


def test_parse_since_accepts_unix_seconds_and_iso() -> None:
    assert _parse_since(None) is None
    assert _parse_since("1700000000") == 1_700_000_000
    parsed = _parse_since("2026-01-01T00:00:00+00:00")
    assert parsed == int(datetime(2026, 1, 1, tzinfo=UTC).timestamp())


def _row(time: int, price: float) -> list[object]:
    return [time, f"{price}", f"{price + 1}", f"{price - 1}", f"{price}", f"{price}", "10.0", 5]


@pytest.mark.asyncio
async def test_fetch_ohlc_page_parses_kraken_response() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/0/public/OHLC"
        assert request.url.params["pair"] == "BTCUSD"
        assert request.url.params["interval"] == "60"
        return httpx.Response(
            200,
            json={
                "error": [],
                "result": {
                    "BTCUSD": [_row(1_700_000_000, 100.0), _row(1_700_003_600, 101.0)],
                    "last": 1_700_003_600,
                },
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(base_url="https://api.kraken.com", transport=transport) as client:
        rows, last = await fetch_ohlc_page(client, pair="BTCUSD", interval_minutes=60, since=None)

    assert last == 1_700_003_600
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_fetch_ohlc_page_raises_on_kraken_error() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"error": ["EQuery:Unknown asset pair"], "result": {}})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(base_url="https://api.kraken.com", transport=transport) as client:
        with pytest.raises(RuntimeError):
            await fetch_ohlc_page(client, pair="NOPE", interval_minutes=60, since=None)


@pytest.mark.asyncio
async def test_download_candles_pages_forward_and_drops_the_uncommitted_bar() -> None:
    """Three calls: an initial page, a page that walks forward via `since`/`last`
    and reveals one genuinely new candle, and a final page with no forward
    progress that stops the walk -- verifying pages are merged by timestamp and
    the very last (always "not yet committed") candle is dropped from the result."""
    base = 1_700_000_000
    pages = [
        (
            [_row(base, 100.0), _row(base + 3600, 101.0), _row(base + 2 * 3600, 102.0)],
            base + 2 * 3600,
        ),
        ([_row(base + 2 * 3600, 102.0), _row(base + 3 * 3600, 103.0)], base + 3 * 3600),
        ([_row(base + 2 * 3600, 102.0), _row(base + 3 * 3600, 103.0)], base + 3 * 3600),
    ]
    calls: list[int | None] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        since_param = request.url.params.get("since")
        since = int(since_param) if since_param else None
        calls.append(since)
        rows, last = pages[min(len(calls) - 1, len(pages) - 1)]
        return httpx.Response(200, json={"error": [], "result": {"BTCUSD": rows, "last": last}})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(base_url="https://api.kraken.com", transport=transport) as client:
        candles = await download_candles("BTC/USD", "1h", client=client, max_candles=100)

    assert calls == [None, base + 2 * 3600, base + 3 * 3600]
    # 4 distinct timestamps observed (0,1,2,3 hours in) minus the always-dropped
    # final (uncommitted) bar.
    assert len(candles) == 3
    assert candles[0].opened_at < candles[-1].opened_at
    assert candles[-1].close == 102.0  # the (now committed) second-page value wins


@pytest.mark.asyncio
async def test_download_spot_histories_fetches_each_symbol_and_resolution() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        pair = request.url.params["pair"]
        interval = request.url.params["interval"]
        base = 1_700_000_000
        step = int(interval) * 60
        rows = [_row(base, 100.0), _row(base + step, 101.0), _row(base + 2 * step, 102.0)]
        return httpx.Response(
            200,
            json={"error": [], "result": {pair: rows, "last": base + 2 * step}},
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(base_url="https://api.kraken.com", transport=transport) as client:
        histories = await download_spot_histories(
            ("BTC/USD", "ETH/USD"), ("1h", "1d"), client=client, max_candles=10
        )
    assert set(histories) == {"BTC/USD@1h", "BTC/USD@1d", "ETH/USD@1h", "ETH/USD@1d"}
    for candles in histories.values():
        assert len(candles) == 2  # uncommitted last bar dropped


# --- multi-year candle fetchers (#133) ---
import json
from datetime import timedelta
from pathlib import Path

from traderstack.candles import Candle
from traderstack.research import download_candles as dc
from traderstack.research.candle_fetch import CandleFetch, finish_fetch
from traderstack.research.cli import load_candles_from_json

_T0 = datetime(2016, 1, 1, tzinfo=UTC)


def _daily(count: int, close: float = 100.0, symbol: str = "BTC/USD") -> tuple[Candle, ...]:
    return tuple(
        Candle(
            symbol=symbol,
            interval="1d",
            opened_at=_T0 + timedelta(days=i),
            open=close,
            high=close + 1,
            low=close - 1,
            close=close,
            volume=1.0,
        )
        for i in range(count)
    )


def _ok_fetch(candles: tuple[Candle, ...] = ()) -> CandleFetch:
    return finish_fetch(
        "BTC/USD@1d",
        source="coinbase_exchange_candles",
        candles=candles or _daily(3),
        interval="1d",
        ok_reason="3 committed 1d bars",
        fetched_at=datetime(2026, 9, 13, tzinfo=UTC),
    )


def _coinbase_args(out: Path, *extra: str) -> list[str]:
    return [
        "BTC/USD",
        "--venue",
        "coinbase",
        "--resolution",
        "1d",
        "--since",
        "2016-01-01",
        *extra,
        "--out",
        str(out),
    ]


def test_default_venue_still_writes_the_identical_bare_list(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    async def fake_download(symbol: str, resolution: str, **kwargs: object) -> tuple[Candle, ...]:
        assert (symbol, resolution) == ("BTC/USD", "1h")
        assert kwargs == {"since": None, "max_candles": 5_000}  # legacy default unchanged
        return _daily(2)

    monkeypatch.setattr(dc, "download_candles", fake_download)
    out = tmp_path / "btc.json"
    dc.main(["BTC/USD", "--out", str(out)])
    payload = json.loads(out.read_text())
    assert isinstance(payload, list) and len(payload) == 2
    assert payload == [json.loads(c.model_dump_json()) for c in _daily(2)]
    assert not (tmp_path / "btc.meta.json").exists()  # legacy path unchanged
    assert "wrote 2 candles" in capsys.readouterr().out


def test_source_charts_and_venue_kraken_alias_still_route_legacy(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    charts_calls: list[tuple[str, str]] = []
    ohlc_calls: list[tuple[str, str]] = []

    async def fake_charts(symbol: str, resolution: str, *, count: int) -> tuple[Candle, ...]:
        charts_calls.append((symbol, resolution))
        return _daily(1)

    async def fake_download(symbol: str, resolution: str, **kwargs: object) -> tuple[Candle, ...]:
        ohlc_calls.append((symbol, resolution))
        return _daily(1)

    monkeypatch.setattr("traderstack.research.kraken_charts.download_kraken_charts", fake_charts)
    monkeypatch.setattr(dc, "download_candles", fake_download)
    dc.main(["BTC/USD", "--source", "charts", "--out", str(tmp_path / "c.json")])
    dc.main(
        ["BTC/USD", "--venue", "kraken", "--resolution", "1d", "--out", str(tmp_path / "k.json")]
    )
    assert charts_calls == [("BTC/USD", "1h")]
    assert ohlc_calls == [("BTC/USD", "1d")]


def test_venue_coinbase_writes_bare_list_plus_meta_sidecar(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    seen: dict[str, object] = {}

    async def fake_fetch(symbol: str, resolution: str, **kwargs: object) -> CandleFetch:
        seen.update(kwargs, symbol=symbol, resolution=resolution)
        return _ok_fetch()

    monkeypatch.setattr("traderstack.research.candles_coinbase.fetch_coinbase_candles", fake_fetch)
    out = tmp_path / "btc.json"
    dc.main(_coinbase_args(out, "--end", "2016-02-01T00:00:00+00:00"))
    assert seen["symbol"] == "BTC/USD"
    assert seen["start"] == int(datetime(2016, 1, 1, tzinfo=UTC).timestamp())
    assert seen["end"] == int(datetime(2016, 2, 1, tzinfo=UTC).timestamp())
    assert seen["max_candles"] is None  # multi-year venues are unbounded unless --max-candles
    assert len(load_candles_from_json(out)) == 3
    assert isinstance(json.loads(out.read_text()), list)
    meta = json.loads((tmp_path / "btc.meta.json").read_text())
    assert meta["venue"] == "coinbase_exchange_candles"
    assert meta["status"] == "ok"
    assert meta["count"] == 3
    assert meta["first"] == "2016-01-01T00:00:00+00:00"
    assert meta["last"] == "2016-01-03T00:00:00+00:00"
    assert meta["fetched_at"] == "2026-09-13T00:00:00+00:00"
    assert meta["gap_entries_total"] == 0
    assert meta["divergence_flags"] == []
    stdout = capsys.readouterr().out
    assert "status=ok" in stdout and "venue=coinbase_exchange_candles" in stdout
    assert "wrote 3 candles" in stdout


def test_skipped_fetch_writes_only_sidecar_leaves_old_file_and_exits_zero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    async def fake_fetch(symbol: str, resolution: str, **kwargs: object) -> CandleFetch:
        return CandleFetch(
            name="BTC/USD@1d",
            status="skipped",
            reason="HTTP 429 after 3 page(s) (rate limited; rerun later)",
            source="coinbase_exchange_candles",
        )

    monkeypatch.setattr("traderstack.research.candles_coinbase.fetch_coinbase_candles", fake_fetch)
    out = tmp_path / "btc.json"
    out.write_text("[]")  # a previous run's file must survive a skipped refetch
    dc.main(_coinbase_args(out))
    assert out.read_text() == "[]"
    meta = json.loads((tmp_path / "btc.meta.json").read_text())
    assert meta["status"] == "skipped"
    assert "429" in meta["reason"]
    assert meta["count"] == 0
    stdout = capsys.readouterr().out
    assert "status=skipped" in stdout
    assert "untouched" in stdout


def test_cross_check_flags_land_in_sidecar_without_altering_candles(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async def fake_fetch(symbol: str, resolution: str, **kwargs: object) -> CandleFetch:
        return _ok_fetch()

    monkeypatch.setattr("traderstack.research.candles_coinbase.fetch_coinbase_candles", fake_fetch)
    reference = tmp_path / "kraken.json"
    ref_candles = list(_daily(3))
    ref_candles[1] = ref_candles[1].model_copy(update={"close": 100.6, "high": 101.6})  # 60 bps
    reference.write_text(json.dumps([json.loads(c.model_dump_json()) for c in ref_candles]))
    out = tmp_path / "btc.json"
    dc.main(_coinbase_args(out, "--cross-check", str(reference), "--max-divergence-bps", "50"))
    loaded = load_candles_from_json(out)
    assert [c.close for c in loaded] == [100.0, 100.0, 100.0]  # unchanged
    meta = json.loads((tmp_path / "btc.meta.json").read_text())
    assert meta["divergence_max_bps"] == 50.0
    assert meta["divergence_reference"] == str(reference)
    assert len(meta["divergence_flags"]) == 1
    assert meta["divergence_flags"][0]["opened_at"] == "2016-01-02T00:00:00+00:00"
    assert meta["divergence_flags"][0]["divergence_bps"] == pytest.approx(60.0, abs=1e-3)
    assert any("flagged only" in note for note in meta["notes"])


def test_cross_check_default_threshold_reads_settings_not_a_new_field(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async def fake_fetch(symbol: str, resolution: str, **kwargs: object) -> CandleFetch:
        return _ok_fetch()

    monkeypatch.setattr("traderstack.research.candles_coinbase.fetch_coinbase_candles", fake_fetch)
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("MAX_REFERENCE_DIVERGENCE_BPS", "75")
    reference = tmp_path / "ref.json"
    reference.write_text(json.dumps([json.loads(c.model_dump_json()) for c in _daily(3)]))
    out = tmp_path / "btc.json"
    dc.main(_coinbase_args(out, "--cross-check", str(reference)))
    meta = json.loads((tmp_path / "btc.meta.json").read_text())
    assert meta["divergence_max_bps"] == 75.0
    assert meta["divergence_flags"] == []
    with pytest.raises(ValueError):
        dc._resolve_max_divergence_bps(-1.0)


def test_venue_coinbase_4h_and_missing_since_fail_with_clear_messages(tmp_path: Path) -> None:
    out = tmp_path / "x.json"
    with pytest.raises(ValueError, match="no 4h"):
        dc.main(
            [
                "BTC/USD",
                "--venue",
                "coinbase",
                "--resolution",
                "4h",
                "--since",
                "2016-01-01",
                "--out",
                str(out),
            ]
        )
    with pytest.raises(ValueError, match="--since is required"):
        dc.main(["BTC/USD", "--venue", "coinbase", "--resolution", "1d", "--out", str(out)])
    with pytest.raises(ValueError, match="--since is required"):
        dc.main(["BTC/USD", "--venue", "binance_vision", "--resolution", "1d", "--out", str(out)])
    assert not out.exists()


def test_venue_binance_vision_dispatches_with_bounds(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen: dict[str, object] = {}

    async def fake_fetch(symbol: str, resolution: str, **kwargs: object) -> CandleFetch:
        seen.update(kwargs, symbol=symbol, resolution=resolution)
        return finish_fetch(
            "BTCUSDT@1d",
            source="binance_vision_spot_monthly",
            candles=_daily(2, symbol="BTCUSDT"),
            interval="1d",
            ok_reason="ok",
        )

    monkeypatch.setattr(
        "traderstack.research.candles_binance_vision.fetch_binance_vision_candles", fake_fetch
    )
    out = tmp_path / "bv.json"
    dc.main(
        [
            "BTC/USD",
            "--venue",
            "binance_vision",
            "--resolution",
            "1d",
            "--since",
            "1500000000",
            "--out",
            str(out),
        ]
    )
    assert seen == {"symbol": "BTC/USD", "resolution": "1d", "start": 1_500_000_000, "end": None}
    meta = json.loads((tmp_path / "bv.meta.json").read_text())
    assert meta["venue"] == "binance_vision_spot_monthly"
    assert meta["symbol"] == "BTCUSDT"


def test_venue_kraken_archive_uses_flag_then_settings_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen: list[str] = []

    def fake_load(
        archive_dir: object, symbol: str, resolution: str, **kwargs: object
    ) -> CandleFetch:
        seen.append(str(archive_dir))
        return CandleFetch(
            name="x", status="skipped", reason="not found", source="kraken_ohlcvt_archive"
        )

    monkeypatch.setattr(
        "traderstack.research.candles_kraken_archive.load_kraken_archive_candles", fake_load
    )
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("RESEARCH_KRAKEN_ARCHIVE_DIR", str(tmp_path / "from_env"))
    out = tmp_path / "ka.json"
    base = ["BTC/USD", "--venue", "kraken_archive", "--resolution", "1d", "--out", str(out)]
    dc.main([*base, "--archive-dir", str(tmp_path / "flag")])
    dc.main(base)
    monkeypatch.setenv("RESEARCH_KRAKEN_ARCHIVE_DIR", "")
    dc.main(base)
    assert seen == [str(tmp_path / "flag"), str(tmp_path / "from_env"), ""]
    assert not out.exists()
    assert json.loads((tmp_path / "ka.meta.json").read_text())["status"] == "skipped"
