"""Pure helpers behind the multi-year candle fetchers (#133)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from traderstack.candles import Candle
from traderstack.research.candle_fetch import (
    MAX_GAP_ENTRIES,
    CandleFetch,
    assert_utc_aligned,
    close_divergence_flags,
    count_missing_bars,
    detect_gaps,
    drop_uncommitted_last,
    finish_fetch,
    floor_to_interval,
    header_line,
    iso_utc,
    meta_path,
    write_candle_json,
    write_meta_sidecar,
)
from traderstack.research.cli import load_candles_from_json

DAY = 86_400
T0 = datetime(2016, 1, 1, tzinfo=UTC)


def _candle(opened_at: datetime, close: float = 100.0, interval: str = "1d") -> Candle:
    return Candle(
        symbol="BTC/USD",
        interval=interval,
        opened_at=opened_at,
        open=close,
        high=close + 1,
        low=close - 1,
        close=close,
        volume=1.0,
    )


def _daily(count: int, *, skip: set[int] = frozenset()) -> tuple[Candle, ...]:
    return tuple(_candle(T0 + timedelta(days=i)) for i in range(count) if i not in skip)


def test_detect_gaps_finds_missing_daily_bar_and_counts() -> None:
    candles = _daily(6, skip={2, 3})
    gaps = detect_gaps(candles, "1d")
    assert len(gaps) == 1
    assert gaps[0].after == T0 + timedelta(days=1)
    assert gaps[0].missing_bars == 2
    assert count_missing_bars(candles, "1d") == 2
    assert detect_gaps(_daily(5), "1d") == ()


def test_detect_gaps_entries_are_bounded_but_total_is_not() -> None:
    # Every other bar missing: 300 gaps of one bar each.
    candles = tuple(_candle(T0 + timedelta(days=2 * i)) for i in range(301))
    fetch = finish_fetch("x", source="s", candles=candles, interval="1d", ok_reason="ok")
    assert len(fetch.gaps) == MAX_GAP_ENTRIES
    assert fetch.gap_entries_total == 300
    assert fetch.missing_bars_total == 300
    assert fetch.as_meta()["gaps_truncated"] is True


def test_assert_utc_aligned_rejects_midday_daily_bar_and_naive_datetime() -> None:
    assert_utc_aligned(_daily(3), "1d")
    with pytest.raises(ValueError, match="not aligned"):
        assert_utc_aligned((_candle(T0 + timedelta(hours=12)),), "1d")
    with pytest.raises(ValueError, match="timezone-aware"):
        assert_utc_aligned((_candle(datetime(2016, 1, 1)),), "1d")  # noqa: DTZ001
    # A non-UTC offset is rejected even when the instant is aligned.
    offset = datetime(2016, 1, 1, 1, tzinfo=UTC).astimezone(timezone(timedelta(hours=1)))
    with pytest.raises(ValueError, match="timezone-aware"):
        assert_utc_aligned((_candle(offset),), "1h")


def test_drop_uncommitted_last_drops_only_a_future_close() -> None:
    now = T0 + timedelta(days=2, hours=6)
    candles = _daily(3)  # opens day0, day1, day2; day2 closes at day3 > now
    kept = drop_uncommitted_last(candles, "1d", now=now)
    assert len(kept) == 2
    assert drop_uncommitted_last(kept, "1d", now=now) == kept
    assert drop_uncommitted_last((), "1d", now=now) == ()


def test_close_divergence_flags_fire_at_60bps_and_stay_silent_otherwise() -> None:
    primary = _daily(3)
    reference = tuple(
        _candle(c.opened_at, close=c.close * (1.006 if i == 1 else 1.0))
        for i, c in enumerate(primary)
    )
    flags = close_divergence_flags(primary, reference, max_bps=50.0)
    assert len(flags) == 1
    assert flags[0].opened_at == T0 + timedelta(days=1)
    assert flags[0].divergence_bps == pytest.approx(60.0)
    assert close_divergence_flags(primary, primary, max_bps=50.0) == ()
    disjoint = tuple(_candle(c.opened_at + timedelta(days=10), close=5.0) for c in primary)
    assert close_divergence_flags(primary, disjoint, max_bps=50.0) == ()
    with pytest.raises(ValueError):
        close_divergence_flags(primary, reference, max_bps=0.0)


def test_floor_and_iso_helpers_align_to_granularity() -> None:
    midday = int((T0 + timedelta(hours=12)).timestamp())
    assert floor_to_interval(midday, "1d") == int(T0.timestamp())
    assert floor_to_interval(midday, "1h") == midday
    assert iso_utc(int(T0.timestamp())) == "2016-01-01T00:00:00Z"


def test_finish_fetch_on_empty_is_skipped_and_misaligned_raises() -> None:
    empty = finish_fetch("x", source="s", candles=(), interval="1d", ok_reason="ok")
    assert empty.status == "skipped"
    assert empty.reason == "empty series"
    assert empty.fetched_at is not None
    with pytest.raises(ValueError):
        finish_fetch(
            "x",
            source="s",
            candles=(_candle(T0 + timedelta(hours=12)),),
            interval="1d",
            ok_reason="ok",
        )
    ok = finish_fetch("x", source="s", candles=_daily(3)[::-1], interval="1d", ok_reason="ok")
    assert ok.status == "ok"
    assert ok.first == T0
    assert ok.last == T0 + timedelta(days=2)
    assert "status=ok" in header_line(ok)
    assert ok.as_note()["points"] == "3"


def test_sidecar_written_and_candle_file_stays_a_bare_list(tmp_path: Path) -> None:
    out = tmp_path / "btc.json"
    fetch = finish_fetch(
        "BTC/USD@1d",
        source="coinbase_exchange_candles",
        candles=_daily(4, skip={2}),
        interval="1d",
        ok_reason="ok",
        fetched_at=datetime(2026, 9, 13, tzinfo=UTC),
    )
    write_candle_json(out, fetch.candles)
    sidecar = write_meta_sidecar(out, fetch)
    assert sidecar == tmp_path / "btc.meta.json"
    assert meta_path(Path("x.csv")) == Path("x.csv.meta.json")
    loaded = load_candles_from_json(out)
    assert len(loaded) == 3
    assert isinstance(json.loads(out.read_text()), list)
    meta = json.loads(sidecar.read_text())
    assert meta["venue"] == "coinbase_exchange_candles"
    assert meta["status"] == "ok"
    assert meta["count"] == 3
    assert meta["first"] == T0.isoformat()
    assert meta["last"] == (T0 + timedelta(days=3)).isoformat()
    assert meta["fetched_at"] == "2026-09-13T00:00:00+00:00"
    assert meta["gap_entries_total"] == 1
    assert meta["gaps"][0]["missing_bars"] == 1
    assert meta["candle_file"] == "btc.json"
    assert meta["symbol"] == "BTC/USD"
    assert meta["interval"] == "1d"


def test_skipped_fetch_meta_carries_reason_without_candles() -> None:
    fetch = CandleFetch(name="x", status="skipped", reason="HTTP 429", source="s")
    meta = fetch.as_meta()
    assert meta["count"] == 0
    assert meta["first"] is None
    assert "symbol" not in meta
    assert "reason='HTTP 429'" in header_line(fetch)
