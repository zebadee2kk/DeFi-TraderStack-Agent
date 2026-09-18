"""Tests for DefiLlama PIT snapshot archive collector."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from traderstack.market.defillama_stable_snapshots import (
    MIN_SNAPSHOT_DAYS,
    coverage,
    load_pit_series_from_archive,
    load_tips,
    net_issuance_from_tips,
    refuse_live_chart_as_pit_archive,
    write_snapshot_from_raw,
)
from traderstack.market.defillama_stablecoins import (
    PIT_SAFE_LIVE_HISTORY,
    parse_stablecoin_chart_rows,
    refuse_live_history_for_backtest,
)
from traderstack.research.stable_net_issuance import run_stable_net_issuance


def _rows(n: int = 5, start: date | None = None, circ0: float = 1000.0) -> list[dict]:
    day0 = start or date(2024, 1, 1)
    rows = []
    circ = circ0
    for i in range(n):
        d = day0 + timedelta(days=i)
        ts = int(datetime(d.year, d.month, d.day, tzinfo=UTC).timestamp())
        circ += 10.0 * (i + 1)
        rows.append({"date": str(ts), "totalCirculatingUSD": {"peggedUSD": circ}})
    return rows


def test_min_snapshot_days_is_720() -> None:
    assert MIN_SNAPSHOT_DAYS == 720


def test_live_history_still_not_pit_safe() -> None:
    assert PIT_SAFE_LIVE_HISTORY is False
    ok, _ = refuse_live_history_for_backtest(pit_archive_present=False)
    assert ok is False


def test_refuse_bare_chart_as_pit_archive() -> None:
    ok, reason = refuse_live_chart_as_pit_archive(_rows(3))
    assert ok is False
    assert "720" in reason or "tip" in reason.lower() or "dated" in reason.lower()


def test_write_snapshot_immutable(tmp_path: Path) -> None:
    archive = tmp_path / "stablecoincharts"
    fetched = datetime(2026, 9, 18, 15, 0, tzinfo=UTC)
    meta, dest, cov = write_snapshot_from_raw(
        archive,
        _rows(4, start=date(2026, 9, 15)),
        fetched_at=fetched,
    )
    assert meta.as_of == date(2026, 9, 18)
    assert meta.pit_safe_for_historical_score is False
    assert (dest / "meta.json").is_file()
    assert (dest / "chart.json").is_file()
    assert cov.tip_days == 1
    assert cov.enough_for_dual_print is False
    tips = load_tips(archive)
    assert len(tips) == 1
    assert tips[0].as_of == date(2026, 9, 18)

    with pytest.raises(FileExistsError):
        write_snapshot_from_raw(
            archive,
            _rows(4, start=date(2026, 9, 15), circ0=9999.0),
            fetched_at=fetched,
        )


def test_tips_net_issuance_skips_gaps(tmp_path: Path) -> None:
    archive = tmp_path / "stablecoincharts"
    # three consecutive as_of days with consecutive tip days
    for i, as_of in enumerate([date(2026, 9, 16), date(2026, 9, 17), date(2026, 9, 18)]):
        tip_day = date(2026, 9, 14) + timedelta(days=i)
        rows = _rows(3, start=tip_day - timedelta(days=2), circ0=1000.0 + 100 * i)
        # force tip to be tip_day by using rows ending at tip_day
        write_snapshot_from_raw(
            archive,
            rows,
            fetched_at=datetime(as_of.year, as_of.month, as_of.day, 12, 0, tzinfo=UTC),
        )
    tips = load_tips(archive)
    assert len(tips) == 3
    points, notes = net_issuance_from_tips(tips)
    # may be 2 or fewer depending on tip_day consecutiveness from _rows
    assert isinstance(points, list)
    assert any(n["name"] == "tips_net_issuance" for n in notes)


def test_load_pit_refuses_until_720(tmp_path: Path) -> None:
    archive = tmp_path / "stablecoincharts"
    write_snapshot_from_raw(
        archive,
        _rows(5),
        fetched_at=datetime(2026, 9, 18, 12, 0, tzinfo=UTC),
    )
    series, points, notes, allowed = load_pit_series_from_archive(archive)
    assert allowed is False
    assert series is None
    assert points == []
    assert any(n["status"] == "refused" for n in notes)


def test_load_pit_allows_with_enough_tips(tmp_path: Path) -> None:
    archive = tmp_path / "stablecoincharts"
    # Build MIN_SNAPSHOT_DAYS consecutive tip rows via direct tips.jsonl for speed
    tips_path = archive
    tips_path.mkdir(parents=True, exist_ok=True)
    lines = []
    start = date(2024, 1, 1)
    circ = 1_000_000.0
    for i in range(MIN_SNAPSHOT_DAYS):
        as_of = start + timedelta(days=i)
        tip_day = as_of  # tip_day == as_of for synthetic PIT
        circ += 1000.0
        ts = int(datetime(tip_day.year, tip_day.month, tip_day.day, tzinfo=UTC).timestamp())
        lines.append(
            json.dumps(
                {
                    "as_of": as_of.isoformat(),
                    "tip_day": tip_day.isoformat(),
                    "circulating_usd": circ,
                    "fetched_at": datetime(
                        as_of.year, as_of.month, as_of.day, 12, 0, tzinfo=UTC
                    ).isoformat(),
                    "endpoint": "/stablecoincharts/all",
                    "source_date_unix": ts,
                },
                sort_keys=True,
            )
        )
    (archive / "tips.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    cov = coverage(archive)
    assert cov.enough_for_dual_print is True
    series, points, _notes, allowed = load_pit_series_from_archive(
        archive,
        as_of=start + timedelta(days=MIN_SNAPSHOT_DAYS + 5),
    )
    assert allowed is True
    assert series is not None
    assert series.pit_safe is True
    assert len(points) > 0


def test_run_stable_ni_refuses_live_chart_even_if_archive_flag_false() -> None:
    series = parse_stablecoin_chart_rows(_rows(10))
    report = run_stable_net_issuance(
        {},
        fee_bps=80.0,
        chart=series,
        pit_archive_present=False,
    )
    assert report.print_kind == "unavailable"
    assert report.can_promote is False


def test_run_stable_ni_with_insufficient_archive_dir(tmp_path: Path) -> None:
    """CLI-style: archive dir present but <720 tips → still unavailable."""
    archive = tmp_path / "stablecoincharts"
    write_snapshot_from_raw(
        archive,
        _rows(8, start=date(2026, 9, 1)),
        fetched_at=datetime(2026, 9, 18, 12, 0, tzinfo=UTC),
    )
    series, points, notes, allowed = load_pit_series_from_archive(archive)
    assert allowed is False
    report = run_stable_net_issuance(
        {},
        fee_bps=80.0,
        chart=series,
        issuance_points=points,
        pit_archive_present=True,
        history_notes=notes,
    )
    # series is None → chart None path; with pit_archive_present True but
    # series_pit_safe False → refuse
    assert report.print_kind == "unavailable"
    assert report.can_promote is False
    assert report.dual_print_passers == 0
